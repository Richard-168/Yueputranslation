"""Verify that an interrupted Windows capture drains into history and export."""

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from yuepu_translate.cloud_config import CloudConfig  # noqa: E402
from yuepu_translate.desktop_qt import Window  # noqa: E402
from yuepu_translate.live_session import LiveSession  # noqa: E402
from yuepu_translate.session_history import SessionHistory  # noqa: E402
from yuepu_translate.transcript_model import TranscriptEntry  # noqa: E402


class CaptureRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        settings = QSettings(str(root / "prefs.ini"), QSettings.IniFormat)
        self.history = SessionHistory(root / "history.sqlite3")
        with (
            patch("yuepu_translate.desktop_qt.settings_store", return_value=settings),
            patch("yuepu_translate.desktop_qt.load_settings", return_value=(CloudConfig(), False)),
        ):
            self.window = Window(muted=True, history=self.history)
        self.addCleanup(self.close_window)
        self.window.listening = True
        self.window.song_session = LiveSession("yue")

    def close_window(self):
        self.window.close()
        self.window.worker.join(3)
        self.window.poll()

    def test_late_playback_error_does_not_disable_the_next_session(self):
        session = self.window.song_session
        session.autoplay = True
        with patch.object(self.window.jobs, "put_nowait"):
            self.window._queue_task(0, session)
            old_token = self.window.playback_token
            self.window._queue_task(0, session)
        self.window.pending = 0
        self.send("audio_error", (old_token, "旧播放器的错误"))
        self.assertTrue(session.autoplay)
        self.assertNotEqual(self.window.status_label.text(), "旧播放器的错误")
        self.send("audio_error", (self.window.playback_token, "当前播放器的错误"))
        self.assertFalse(session.autoplay)
        self.assertEqual(self.window.status_label.text(), "当前播放器的错误")

    def test_new_conversation_discards_remaining_audio_and_its_late_error(self):
        window = self.window
        window.listening = False
        window.song_session = None
        with patch.object(window.jobs, "put_nowait"):
            window._queue_task(1, object())
        old_token = window.playback_token
        output = window.player.for_task(
            lambda message: self.send("audio_error", (old_token, message))
        )
        # Use the real queue without a sound-device consumer.
        window.player.muted = False
        output.put([0.1], 16000, window.cancel)
        self.send("finished", None)
        self.assertTrue(window.player.busy)
        old_session = window.session_id
        window.new_session()
        self.assertNotEqual(old_session, window.session_id)
        self.assertFalse(window.player.busy)
        self.assertNotEqual(output.generation, window.player.generation)
        output.error("旧会话的声卡迟报")
        self.assertNotEqual(window.status_label.text(), "旧会话的声卡迟报")

    def test_waiting_for_audio_keeps_controls_live_and_recovers(self):
        self.window.capture_started = True
        session = self.window.song_session
        self.send("capture_waiting", (session, True))
        self.assertTrue(self.window.listening)
        self.assertIn("音频包", self.window.status_label.text())
        self.assertTrue(self.window.record_button.isEnabled())
        self.send("capture_waiting", (session, False))
        self.assertFalse(self.window.capture_waiting)
        self.assertIn("恢复", self.window.status_label.text())
        self.send("capture_waiting", (LiveSession("zh"), True))
        self.assertFalse(self.window.capture_waiting)

    def test_replay_only_reads_current_translation_or_its_fixed_prefix(self):
        window = self.window
        window.listening = False
        window.song_session = None
        target = "明天出发"
        for restored, current, prefix, final, expected in (
            (False, True, 0, False, target),
            (False, False, 2, False, "明天"),
            (False, False, 0, False, ""),
            (True, True, 2, False, "明天"),
            (True, True, 0, False, ""),
            (True, False, 0, True, target),
        ):
            with self.subTest(restored=restored, current=current, prefix=prefix, final=final):
                entry = TranscriptEntry(
                    1,
                    "yue",
                    "zh",
                    source="听日出发",
                    target=target,
                    status="已确认" if final else "暂定 · 已停止",
                    target_confirmed=prefix,
                    target_current=current,
                )
                entries = [entry]
                if restored:
                    self.history.save("past", entries)
                    entries = self.history.load("past")
                window.model.replace_entries(entries)
                window._buttons()
                self.assertEqual(window.replay_button.isEnabled(), bool(expected))
                with patch.object(window, "submit") as submit:
                    window.replay()
                if expected:
                    self.assertEqual(submit.call_args.args[0].text, expected)
                else:
                    submit.assert_not_called()

    def send(self, kind, value):
        self.window.events.put((self.window.epoch, 0, kind, value))
        self.window.poll()

    def caption(self, block, text, target, final):
        fields = dict(block=block, version=2 if final else 1, final=final)
        self.send("live_source", dict(**fields, text=text, recognition_seconds=0, lag_seconds=0))
        self.send("live_translation", dict(**fields, text=target, preview=not final))

    def test_overload_drains_then_saves_notice_after_translated_rows(self):
        self.caption(0, "頭一句", "第一句", True)
        self.caption(1, "落", "下", False)
        notice = "从 4.000 秒起缺音。"
        self.send("capture_interrupted", (self.window.song_session, notice))
        self.assertFalse(self.window.cancel.is_set())
        self.assertFalse(self.window.listening)
        self.caption(1, "落雨", "下雨", True)
        self.send("song_drained", dict(confirmed_count=2, partial_count=0))
        rows = self.window.model.items
        self.assertEqual([row.status for row in rows], ["已确认", "已确认", "收音中断"])
        self.assertEqual([row.target for row in rows[:2]], ["第一句", "下雨"])
        self.assertTrue(rows[-1].is_capture_notice)
        self.assertTrue(self.window.save_history())
        self.assertEqual(SessionHistory(self.history.path).load(self.window.session_id), rows)
        self.assertIn("收音中断\n" + notice, self.window.model.export_text())

    def test_cancel_keeps_confirmed_and_labels_unfinished_translation(self):
        self.caption(0, "頭一句", "第一句", True)
        self.caption(1, "落", "下", False)
        self.window.stop()
        self.assertEqual(self.window.model.items[0].status, "已确认")
        self.assertEqual(self.window.model.items[1].target_confirmed, 0)
        self.assertIn("译文：下\n状态：暂定 · 已停止", self.window.model.export_text())
        self.assertTrue(self.window.save_history())
        restored = self.history.load(self.window.session_id)
        self.assertEqual(restored[1].target, "下")
        self.assertFalse(restored[1].target_current)
        self.assertIn("与本版原文未核对", self.window.model.export_text(restored))

    def queue_final_and_interrupt(self):
        window = self.window
        self.caption(0, "听日下集", "明天下一集", False)
        # Final events sit behind a full timer tick's worth of pending messages.
        for _ in range(170):
            window.events.put((window.epoch, 0, "status", "处理中"))
        fields = dict(block=0, version=2, final=True)
        window.events.put(
            (
                window.epoch,
                0,
                "live_source",
                dict(
                    **fields,
                    text="听日下昼",
                    frozen_characters=4,
                    recognition_seconds=0,
                    lag_seconds=0,
                ),
            )
        )
        window.events.put((window.epoch, 0, "live_translation", dict(**fields, text="明天下午")))
        window.events.put(
            (window.epoch, 0, "capture_interrupted", (window.song_session, "从 4.000 秒起缺音。"))
        )

    def test_playback_mask_only_attaches_to_opted_in_microphone_autoplay(self):
        window = self.window
        cases = (
            (0, True, False, False),
            (0, True, True, True),
            (0, False, True, False),
            (1, True, True, False),
        )
        with patch("yuepu_translate.capture_process.CaptureProcess.start"):
            for source, autoplay, enabled, expect_mask in cases:
                with self.subTest(source=source, autoplay=autoplay, enabled=enabled):
                    window.source_box.setCurrentIndex(source)
                    window.song_session.autoplay = autoplay
                    window.defaults = replace(window.defaults, mute_mic_during_playback=enabled)
                    window._start_song_capture()
                    self.assertEqual(window.microphone.playback_intervals is not None, expect_mask)
                    window.microphone = None

    def assert_saved_final_and_notice(self):
        window = self.window
        saved = SessionHistory(self.history.path).load(window.session_id)
        self.assertEqual([row.status for row in saved], ["已确认", "收音中断"])
        self.assertEqual((saved[0].source, saved[0].target), ("听日下昼", "明天下午"))
        self.assertEqual(saved[1].source, "从 4.000 秒起缺音。")
        self.assertEqual(window.model.items, saved)

    def test_escape_commits_waiting_results_without_starting_a_source(self):
        self.queue_final_and_interrupt()
        old_epoch = self.window.epoch
        self.window.events.put((old_epoch, 0, "song_ready", True))
        with patch.object(self.window, "_start_song_capture") as start:
            self.window.stop()
        start.assert_not_called()
        self.window.events.put((old_epoch, 0, "live_translation", {}))
        self.window.poll()
        self.assertTrue(self.window.save_history())
        self.assert_saved_final_and_notice()

    def test_close_saves_already_published_final_and_interrupt(self):
        self.queue_final_and_interrupt()
        self.window.close()
        self.assert_saved_final_and_notice()

    def test_copy_export_and_restored_history_label_the_mismatched_draft(self):
        window = self.window
        self.caption(0, "听日下集", "明天下一集", False)
        self.assertIn("译文：明天下一集\n状态：粗略译文 · 待复核", window.model.export_text())
        self.send(
            "live_source",
            dict(
                block=0,
                version=2,
                text="听日下昼",
                final=True,
                frozen_characters=4,
                recognition_seconds=0,
                lag_seconds=0,
            ),
        )
        path = self.history.path.parent / "export.txt"
        window.write_export(path)
        snapshot = path.read_text(encoding="utf-8-sig")
        with patch.object(QApplication, "clipboard") as clipboard:
            window.copy_records()
        clipboard.return_value.setText.assert_called_once_with(snapshot)
        self.assertIn("原文：听日下昼\n译文：[当前原文译文未确认]", snapshot)
        self.assertIn("此前的译文草稿（与本版原文未核对）：明天下一集", snapshot)
        self.assertTrue(window.save_history())
        self.assertEqual(window.model.export_text(self.history.load(window.session_id)), snapshot)
        self.send("live_translation", dict(block=0, version=2, final=True, text="明天下午"))
        self.assertIn("原文：听日下昼\n译文：明天下午", window.model.export_text())
        self.assertNotIn("草稿", window.model.export_text())
