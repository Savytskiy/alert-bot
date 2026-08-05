from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

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
