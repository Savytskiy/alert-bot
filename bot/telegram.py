from __future__ import annotations

from datetime import datetime
from html import escape as h

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

SEVERITY_EMOJI = {
    "critical": "🔴",
    "warning": "🟡",
    "info": "ℹ️",
}


def _format(project: str, severity: str, title: str, message: str, count: int, last_seen: datetime) -> str:
    emoji = SEVERITY_EMOJI.get(severity, "⚪")
    lines = [f"{emoji} <b>{h(title)}</b>"]
    if message:
        lines.append(h(message))
    lines.append("")
    footer = f"<i>{h(project)} · {last_seen.strftime('%d.%m.%Y %H:%M')}"
    if count > 1:
        footer += f" · повторилось {count} раз"
    footer += "</i>"
    lines.append(footer)
    return "\n".join(lines)


async def send_alert(
    bot: Bot,
    chat_id: int,
    thread_id: int,
    project: str,
    severity: str,
    title: str,
    message: str,
    silent: bool,
    sent_at: datetime,
) -> int:
    text = _format(project, severity, title, message, count=1, last_seen=sent_at)
    sent = await bot.send_message(
        chat_id=chat_id,
        message_thread_id=thread_id,
        text=text,
        parse_mode="HTML",
        disable_notification=silent,
    )
    return sent.message_id


async def edit_alert(
    bot: Bot,
    chat_id: int,
    message_id: int,
    project: str,
    severity: str,
    title: str,
    message: str,
    count: int,
    last_seen: datetime,
) -> bool:
    text = _format(project, severity, title, message, count=count, last_seen=last_seen)
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
        )
        return True
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc):
            return True
        return False
