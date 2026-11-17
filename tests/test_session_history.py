"""Verify the desktop session list and subtitle restoration across restarts."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from yuepu_translate.session_history import (
    SessionHistory,
    SessionHistoryConflict,
    SessionHistoryError,
)
from yuepu_translate.transcript_model import TranscriptEntry


class SessionHistoryTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(directory) / "history" / "test.sqlite3"
        self.history = SessionHistory(self.path)

    def test_round_trip_keeps_bilingual_caption_metadata(self):
        caption = TranscriptEntry(
            1,
            "yue",
            "zh",
            source=" 多謝\n你嘅幫忙。",
            target="谢谢你的帮助。",
            status="已确认",
            timestamp="09:10:11",
            revision=3,
            source_confirmed=8,
            target_confirmed=7,
        )
        self.assertFalse(self.path.exists())
        self.history.save("first", [TranscriptEntry(0, "zh", "yue"), caption])
        reopened = SessionHistory(self.path)
        self.assertEqual(reopened.load("first"), [caption])
        summary = reopened.list_sessions()[0]
        self.assertEqual((summary.id, summary.title), ("first", "多謝 你嘅幫忙。"))
        self.assertIsNotNone(summary.updated_at.utcoffset())

    def test_revision_updates_order_empty_save_preserves_and_delete_is_idempotent(self):
        caption = TranscriptEntry(1, "zh", "yue", source="早上好")
        edit_times = [datetime(2026, 11, 17, 8, minute, tzinfo=UTC) for minute in range(4)]
        with patch("yuepu_translate.session_history.datetime", wraps=datetime) as clock:
            clock.now.side_effect = edit_times
            self.history.save("first", [caption])
            self.history.save("second", [caption])
            self.history.save("first", [caption])
            self.assertEqual(
                [entry.id for entry in self.history.list_sessions()], ["second", "first"]
            )
            caption.target = "早晨"
            self.history.save("first", [caption])
        self.history.save("first", [])
        self.assertEqual(self.history.load("first"), [caption])
        self.assertEqual([entry.id for entry in self.history.list_sessions()], ["first", "second"])
        self.history.delete("first")
        self.history.delete("first")
        self.assertEqual(self.history.load("first"), [])
        self.assertEqual([entry.id for entry in self.history.list_sessions()], ["second"])

    def test_malformed_saved_session_reports_error_without_losing_other_sessions(self):
        caption = TranscriptEntry(1, "zh", "yue", source="早上好")
        self.history.save("first", [caption])
        self.history.save("second", [caption])
        with closing(sqlite3.connect(self.path)) as database, database:
            database.execute("UPDATE sessions SET entries = '{}' WHERE id = 'first'")
        with self.assertRaises(SessionHistoryError):
            self.history.load("first")
        self.assertEqual(self.history.load("second"), [caption])

    def test_stale_window_cannot_overwrite_or_delete_newer_transcript(self):
        original = TranscriptEntry(1, "zh", "yue", source="早上好")
        newer = replace(original, target="早晨")
        self.history.save("session", [original])
        second_window = SessionHistory(self.path)
        self.assertEqual(second_window.load("session"), [original])
        self.history.save("session", [newer])

        with self.assertRaises(SessionHistoryConflict):
            second_window.save("session", [original])
        with self.assertRaises(SessionHistoryConflict):
            second_window.delete("session")
        self.assertEqual(second_window.load("session"), [newer])
        second_window.delete("session")
        self.assertEqual(self.history.list_sessions(), [])

    def test_stale_window_can_save_a_copy_without_resurrecting_deleted_session(self):
        caption = TranscriptEntry(1, "zh", "yue", source="早上好", target="早晨")
        self.history.save("session", [caption])
        second_window = SessionHistory(self.path)
        self.assertEqual(second_window.load("session"), [caption])
        second_window.delete("session")

        with self.assertRaises(SessionHistoryConflict):
            self.history.save("session", [caption])
        self.history.save("copy", [caption])
        self.assertEqual(self.history.load("copy"), [caption])
        self.assertEqual([entry.id for entry in second_window.list_sessions()], ["copy"])


if __name__ == "__main__":
    unittest.main()
