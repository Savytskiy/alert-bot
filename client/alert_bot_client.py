"""Копируйте этот файл в свой проект для отправки алертов в alert-bot.

Без внешних зависимостей — использует только стандартную библиотеку.

Пример:
    from alert_bot_client import notify

    notify(
        base_url="http://127.0.0.1:8000",
        token="<токен проекта из manage.py add-project>",
        severity="critical",
        title="DB connection failed",
        message="Connection to postgres timed out after 5s",
        fingerprint="db-connection-failed",
    )
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request


def notify(
    base_url: str,
    token: str,
    severity: str,
    title: str,
    fingerprint: str,
    message: str = "",
    timeout: float = 5.0,
) -> bool:
    """Отправляет алерт в alert-bot. Возвращает True при успехе, False при ошибке
    (не бросает исключение — сбой алертинга не должен ронять вызывающий проект)."""
    url = f"{base_url.rstrip('/')}/webhook/{token}"
    payload = {
        "severity": severity,
        "title": title,
        "message": message,
        "fingerprint": fingerprint,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError):
        return False
