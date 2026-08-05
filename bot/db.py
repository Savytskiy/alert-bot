from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "alerts.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    received_at TEXT NOT NULL,
    delivered_to_telegram INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS active_incidents (
    project TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    telegram_message_id INTEGER,
    PRIMARY KEY (project, fingerprint)
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


@dataclass
class ActiveIncident:
    project: str
    fingerprint: str
    severity: str
    title: str
    message: str
    first_seen: datetime
    last_seen: datetime
    count: int
    telegram_message_id: int | None


class AlertStore:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def record_alert(
        self,
        project: str,
        severity: str,
        title: str,
        message: str,
        fingerprint: str,
        delivered_to_telegram: bool,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO alerts
                   (project, severity, title, message, fingerprint, received_at, delivered_to_telegram)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project, severity, title, message, fingerprint, _iso(_now()), int(delivered_to_telegram)),
            )
            self._conn.commit()
            return cur.lastrowid

    def get_active_incident(
        self, project: str, fingerprint: str, cooldown_minutes: int
    ) -> ActiveIncident | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM active_incidents WHERE project = ? AND fingerprint = ?",
                (project, fingerprint),
            ).fetchone()
        if row is None:
            return None
        last_seen = datetime.fromisoformat(row["last_seen"])
        if _now() - last_seen > timedelta(minutes=cooldown_minutes):
            return None  # остыло — считаем новым инцидентом
        return ActiveIncident(
            project=row["project"],
            fingerprint=row["fingerprint"],
            severity=row["severity"],
            title=row["title"],
            message=row["message"],
            first_seen=datetime.fromisoformat(row["first_seen"]),
            last_seen=last_seen,
            count=row["count"],
            telegram_message_id=row["telegram_message_id"],
        )

    def start_incident(
        self,
        project: str,
        fingerprint: str,
        severity: str,
        title: str,
        message: str,
        telegram_message_id: int | None,
    ) -> None:
        now = _iso(_now())
        with self._lock:
            self._conn.execute(
                """INSERT INTO active_incidents
                   (project, fingerprint, severity, title, message, first_seen, last_seen, count, telegram_message_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                   ON CONFLICT(project, fingerprint) DO UPDATE SET
                     severity=excluded.severity,
                     title=excluded.title,
                     message=excluded.message,
                     first_seen=excluded.first_seen,
                     last_seen=excluded.last_seen,
                     count=1,
                     telegram_message_id=excluded.telegram_message_id""",
                (project, fingerprint, severity, title, message, now, now, telegram_message_id),
            )
            self._conn.commit()

    def bump_incident(self, project: str, fingerprint: str, message: str) -> int:
        now = _iso(_now())
        with self._lock:
            self._conn.execute(
                """UPDATE active_incidents
                   SET count = count + 1, last_seen = ?, message = ?
                   WHERE project = ? AND fingerprint = ?""",
                (now, message, project, fingerprint),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT count FROM active_incidents WHERE project = ? AND fingerprint = ?",
                (project, fingerprint),
            ).fetchone()
            return row["count"]

    def close(self) -> None:
        self._conn.close()
