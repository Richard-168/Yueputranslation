"""Local, text-only history for the Windows desktop app."""

import json
import os
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from .transcript_model import TranscriptEntry

_ENTRY_TYPES = {field.name: field.type for field in fields(TranscriptEntry)}
_SAVED_FIELDS = tuple(name for name in _ENTRY_TYPES if name != "target_current")


class SessionHistoryError(RuntimeError):
    """The local database or a saved session could not be read or changed."""


class SessionHistoryConflict(SessionHistoryError):
    """Another writer changed or removed a previously opened session."""


@dataclass(frozen=True)
class SessionSummary:
    id: str
    title: str
    updated_at: datetime


class SessionHistory:
    def __init__(self, path=None):
        local_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share"))
        self.path = (
            Path(path) if path is not None else local_data / "YuePuTranslate/history.sqlite3"
        )
        self._versions = {}

    @contextmanager
    def _database(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=0.5)) as database, database:
                database.execute(
                    """CREATE TABLE IF NOT EXISTS sessions (
                        id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        entries TEXT NOT NULL
                    )"""
                )
                yield database
        except (OSError, sqlite3.Error) as exc:
            raise SessionHistoryError("无法访问本地会话历史。请稍后重试或检查存储权限。") from exc

    @staticmethod
    def _record(database, session_id):
        return database.execute(
            "SELECT updated_at, entries FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()

    @staticmethod
    def _version(record):
        if record is None:
            return None
        updated_at, payload = record
        encoded = payload.encode("utf-8") if isinstance(payload, str) else payload
        return updated_at, sha256(encoded).digest()

    def _record_for_write(self, database, session_id):
        database.execute("BEGIN IMMEDIATE")
        record = self._record(database, session_id)
        if session_id in self._versions and self._versions[session_id] != self._version(record):
            raise SessionHistoryConflict("这条会话已在另一个窗口中修改或删除。")
        return record

    def list_sessions(self):
        with self._database() as database:
            rows = database.execute(
                "SELECT id, title, updated_at FROM sessions ORDER BY updated_at DESC, id"
            ).fetchall()
        try:
            return [
                SessionSummary(session_id, title, datetime.fromisoformat(updated).astimezone())
                for session_id, title, updated in rows
            ]
        except (TypeError, ValueError, OSError) as exc:
            raise SessionHistoryError("无法读取本地会话的日期。") from exc

    def load(self, session_id):
        with self._database() as database:
            row = self._record(database, session_id)
        if row is None:
            self._versions[session_id] = None
            return []
        try:
            records = json.loads(row[1])
            if not isinstance(records, list):
                raise ValueError("invalid transcript list")
            entries = [TranscriptEntry(**record) for record in records]
            keys = set()
            for entry in entries:
                if any(type(getattr(entry, key)) is not kind for key, kind in _ENTRY_TYPES.items()):
                    raise ValueError("invalid transcript field")
                if entry.key in keys or not (
                    0 <= entry.source_confirmed <= len(entry.source)
                    and 0 <= entry.target_confirmed <= len(entry.target)
                ):
                    raise ValueError("invalid transcript sequence or span")
                entry.target_current = False
                keys.add(entry.key)
            self._versions[session_id] = self._version(row)
            return entries
        except (TypeError, ValueError) as exc:
            raise SessionHistoryError("无法读取这条会话的字幕。") from exc

    def save(self, session_id, entries):
        captions = [entry for entry in entries if entry.source.strip() or entry.target.strip()]
        if not captions:
            return
        first = captions[0]
        title = " ".join((first.source.strip() or first.target).split())
        if len(title) > 48:
            title = title[:47] + "…"
        serialized = json.dumps(
            [{name: getattr(entry, name) for name in _SAVED_FIELDS} for entry in captions],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._database() as database:
            row = self._record_for_write(database, session_id)
            if row is None or row[1] != serialized:
                updated_at = datetime.now(UTC).isoformat()
                database.execute(
                    """INSERT INTO sessions (id, title, updated_at, entries) VALUES (?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET title = excluded.title,
                           updated_at = excluded.updated_at, entries = excluded.entries""",
                    (session_id, title, updated_at, serialized),
                )
                row = (updated_at, serialized)
        self._versions[session_id] = self._version(row)

    def delete(self, session_id):
        with self._database() as database:
            self._record_for_write(database, session_id)
            database.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        self._versions[session_id] = None
