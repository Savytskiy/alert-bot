#!/usr/bin/env python3
"""Управление проектами alert-bot: add-project / list-projects / revoke-project.

Не требует запущенного сервера — работает напрямую с config.yaml и Telegram Bot API.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import urllib.request

from bot.config import Project, load_config, save_config


def _telegram_call(bot_token: str, method: str, **params) -> dict:
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    data = json.dumps(params).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error on {method}: {result}")
    return result["result"]


def cmd_add_project(args: argparse.Namespace) -> None:
    config = load_config()
    if config.project_by_name(args.name) is not None:
        print(f"Проект '{args.name}' уже существует.", file=sys.stderr)
        sys.exit(1)

    topic = _telegram_call(config.bot_token, "createForumTopic", chat_id=config.owner_chat_id, name=args.name)
    thread_id = topic["message_thread_id"]
    token = secrets.token_urlsafe(24)

    config.projects.append(Project(name=args.name, token=token, thread_id=thread_id))
    save_config(config)

    print(f"Проект '{args.name}' добавлен.")
    print(f"  thread_id: {thread_id}")
    print(f"  token:     {token}")
    print()
    print("Пример вызова из проекта:")
    print(
        f'  curl -X POST http://127.0.0.1:8000/webhook/{token} '
        f'-H "Content-Type: application/json" '
        f'-d \'{{"severity": "critical", "title": "...", "message": "...", "fingerprint": "..."}}\''
    )


def cmd_list_projects(args: argparse.Namespace) -> None:
    config = load_config()
    if not config.projects:
        print("Проектов пока нет.")
        return
    for p in config.projects:
        masked = p.token[:6] + "…" if len(p.token) > 6 else p.token
        print(f"{p.name:20s} thread_id={p.thread_id:<10} token={masked}")


def cmd_revoke_project(args: argparse.Namespace) -> None:
    config = load_config()
    project = config.project_by_name(args.name)
    if project is None:
        print(f"Проект '{args.name}' не найден.", file=sys.stderr)
        sys.exit(1)

    try:
        _telegram_call(config.bot_token, "deleteForumTopic", chat_id=config.owner_chat_id, message_thread_id=project.thread_id)
    except RuntimeError as exc:
        print(f"Не удалось удалить топик в Telegram (продолжаю): {exc}", file=sys.stderr)

    config.projects = [p for p in config.projects if p.name != args.name]
    save_config(config)
    print(f"Проект '{args.name}' отозван.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add-project", help="Создать топик и токен для нового проекта")
    p_add.add_argument("name")
    p_add.set_defaults(func=cmd_add_project)

    p_list = sub.add_parser("list-projects", help="Показать все подключённые проекты")
    p_list.set_defaults(func=cmd_list_projects)

    p_revoke = sub.add_parser("revoke-project", help="Удалить проект и его токен")
    p_revoke.add_argument("name")
    p_revoke.set_defaults(func=cmd_revoke_project)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
