from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from bot.config import load_config
from bot.db import AlertStore
from bot.models import AlertPayload
from bot.telegram import edit_alert, send_alert

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("alert_bot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()
    app.state.config = config
    app.state.bot = Bot(token=config.bot_token)
    app.state.store = AlertStore()
    logger.info("alert-bot started, %d project(s) configured", len(config.projects))
    yield
    await app.state.bot.session.close()
    app.state.store.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


@app.post("/webhook/{token}")
async def webhook(token: str, request: Request) -> JSONResponse:
    config = app.state.config
    project = config.project_by_token(token)
    if project is None:
        raise HTTPException(status_code=404, detail="unknown project token")

    try:
        body = await request.json()
        payload = AlertPayload(**body)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    store: AlertStore = app.state.store
    bot: Bot = app.state.bot

    rule = project.rule_for(payload.severity, config.default_severity_rules)
    now = datetime.now(timezone.utc)

    if not rule.enabled:
        store.record_alert(
            project.name, payload.severity, payload.title, payload.message,
            payload.fingerprint, delivered_to_telegram=False,
        )
        return JSONResponse({"ok": True, "delivered": False})

    incident = store.get_active_incident(project.name, payload.fingerprint, config.dedup_cooldown_minutes)

    if incident is not None and incident.telegram_message_id is not None:
        count = store.bump_incident(project.name, payload.fingerprint, payload.message)
        edited = await edit_alert(
            bot, config.owner_chat_id, incident.telegram_message_id,
            project.name, payload.severity, payload.title, payload.message,
            count=count, last_seen=now,
        )
        delivered = edited
        if not edited:
            logger.warning(
                "failed to edit message %s for %s/%s, falling back to new message",
                incident.telegram_message_id, project.name, payload.fingerprint,
            )
            message_id = await send_alert(
                bot, config.owner_chat_id, project.thread_id, project.name,
                payload.severity, payload.title, payload.message,
                silent=rule.silent, sent_at=now,
            )
            store.start_incident(
                project.name, payload.fingerprint, payload.severity,
                payload.title, payload.message, telegram_message_id=message_id,
            )
            delivered = True
        else:
            # A same-fingerprint incident that just keeps getting edited
            # ("повторилось N раз") is easy to miss - it never re-notifies,
            # so a warning-severity incident stuck for hours/days looks
            # identical to a one-off blip unless you scroll up. Once it's
            # been continuously active (never cooled off past
            # dedup_cooldown_minutes) for escalation_hours, send a fresh
            # loud/critical message instead of another silent edit -
            # repeats every escalation_hours for as long as it's still
            # going, so a multi-day incident keeps getting flagged.
            elapsed = now - incident.first_seen
            threshold = timedelta(hours=config.escalation_hours)
            since_last_escalation = now - incident.last_escalated_at if incident.last_escalated_at else elapsed
            if elapsed >= threshold and since_last_escalation >= threshold:
                hours_running = int(elapsed.total_seconds() // 3600)
                escalation_title = f"⏰ Инцидент не прекращается уже {hours_running}ч: {payload.title}"
                escalation_message = f"Повторяется без перерыва, счётчик: {count}."
                await send_alert(
                    bot, config.owner_chat_id, project.thread_id, project.name,
                    "critical", escalation_title, escalation_message,
                    silent=False, sent_at=now,
                )
                store.mark_escalated(project.name, payload.fingerprint)
                store.record_alert(
                    project.name, "critical", escalation_title, escalation_message,
                    payload.fingerprint, delivered_to_telegram=True,
                )
    else:
        message_id = await send_alert(
            bot, config.owner_chat_id, project.thread_id, project.name,
            payload.severity, payload.title, payload.message,
            silent=rule.silent, sent_at=now,
        )
        store.start_incident(
            project.name, payload.fingerprint, payload.severity,
            payload.title, payload.message, telegram_message_id=message_id,
        )
        delivered = True

    store.record_alert(
        project.name, payload.severity, payload.title, payload.message,
        payload.fingerprint, delivered_to_telegram=delivered,
    )
    return JSONResponse({"ok": True, "delivered": delivered})
