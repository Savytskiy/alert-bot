# Alert Bot

Локальный сервис, который принимает вебхуки от проектов на этом сервере и
шлёт уведомления в Telegram — каждый проект в своём топике личного чата с ботом.

Если наткнулись на этот файл, не разобравшись — можно просто попросить Клода
"почитай README в /root/alert_bot и подключи туда уведомления для проекта X".
Всё, что нужно знать для интеграции, есть в разделе [Как подключить проект](#как-подключить-проект).

## Архитектура

- **Push-модель**: проекты сами шлют `POST http://127.0.0.1:8000/webhook/<token>`
  при возникновении события. Сервер слушает только `127.0.0.1` — наружу не торчит,
  токен нужен только чтобы разные проекты не путали друг друга, а не как защита
  от интернета.
- **Топики**: у бота включён threaded mode (BotFather → Threaded Mode). Каждый
  проект — отдельный топик в личном чате бот↔владелец. Группа не нужна.
- **Дедуп/антифлуд**: алерты группируются по `fingerprint`. Если тот же
  `fingerprint` повторяется в течение `dedup_cooldown_minutes` (по умолчанию 15)
  после последнего появления — исходное сообщение в Telegram редактируется
  ("повторилось N раз"), новое не шлётся. Если после алерта было дольше
  cooldown тишины — следующий такой же `fingerprint` считается новым инцидентом.
- **Severity**: `critical` / `warning` / `info`. По умолчанию все три уровня
  долетают до Telegram (critical — громко, warning/info — тихо), но это
  настраивается per-project в `config.yaml` (`severity_rules`), вплоть до
  полного отключения уровня для конкретного проекта.
- **История**: вообще все входящие алерты (даже отключённых уровней) пишутся
  в SQLite (`data/alerts.db`), даже если в Telegram не отправлены.

Код: `bot/main.py` (FastAPI, роут `/webhook/{token}`), `bot/db.py` (SQLite),
`bot/telegram.py` (отправка/редактирование через aiogram), `bot/config.py`
(схема `config.yaml`), `manage.py` (CLI для управления проектами).

## Установка

```bash
cd /root/alert_bot
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp config.example.yaml config.yaml
```

В `config.yaml` заполнить:
- `bot_token` — токен от @BotFather (у бота должен быть включён Threaded Mode)
- `owner_chat_id` — ваш Telegram user id (chat_id личного чата с ботом)

Запуск вручную (для проверки):
```bash
venv/bin/uvicorn bot.main:app --host 127.0.0.1 --port 8000
```

Как systemd-сервис:
```bash
sudo cp alert-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now alert-bot
sudo systemctl status alert-bot
journalctl -u alert-bot -f   # логи
```

## Как подключить проект

1. Создать проект и получить токен:
   ```bash
   cd /root/alert_bot
   venv/bin/python manage.py add-project my_service
   ```
   Это создаст топик в Telegram и допишет проект (имя, токен, thread_id) в `config.yaml`.
   **Сервис нужно перезапустить**, чтобы подхватить новый конфиг: `systemctl restart alert-bot`.

2. Слать алерты из проекта — любым HTTP-клиентом:
   ```bash
   curl -X POST http://127.0.0.1:8000/webhook/<TOKEN> \
     -H "Content-Type: application/json" \
     -d '{
       "severity": "critical",
       "title": "DB connection failed",
       "message": "Connection to postgres timed out after 5s",
       "fingerprint": "db-connection-failed"
     }'
   ```

   Поля:
   - `severity` — `critical` | `warning` | `info` (обязательное)
   - `title` — короткий заголовок (обязательное)
   - `message` — подробности (необязательное)
   - `fingerprint` — **обязательное**, стабильный идентификатор *типа* проблемы
     (не должен включать переменные данные вроде конкретного IP/времени —
     иначе дедуп не сработает). Например: `"disk-full:/var"`, `"db-connection-failed"`.

3. Для python-проектов проще скопировать `client/alert_bot_client.py` (без
   внешних зависимостей) и вызывать:
   ```python
   from alert_bot_client import notify

   notify(
       base_url="http://127.0.0.1:8000",
       token="<TOKEN>",
       severity="critical",
       title="DB connection failed",
       message="Connection to postgres timed out after 5s",
       fingerprint="db-connection-failed",
   )
   ```

## Управление проектами

```bash
venv/bin/python manage.py list-projects
venv/bin/python manage.py revoke-project my_service   # удаляет топик и токен
```

## Настройка severity per-project

В `config.yaml`:
```yaml
projects:
  - name: my_service
    token: "..."
    thread_id: 12345
    severity_rules:
      info:
        enabled: false   # для этого проекта info вообще не шлём в Telegram
```
Любой не переопределённый уровень берётся из `default_severity_rules`.

## Известные ограничения

- Threaded mode в приватных чатах — свежая фича Bot API (9.3+, декабрь 2025).
  Если Telegram что-то поломает в очередном обновлении API — смотрите
  `journalctl -u alert-bot` на ошибки `message thread not found` /
  `BOT_FORUM_CREATE_FORBIDDEN`.
