"""Bounded streaming, overlap and queue behavior without speech model assets."""

import threading
import unittest
from unittest.mock import patch

import numpy as np

from yuepu_translate.song_pipeline import make_song_stream
from yuepu_translate.song_stream import RollingAudio, SongMailbox, draft_fits, trim_context


class SongStreamTests(unittest.TestCase):
    def test_checkpoint_after_idle_keeps_frame_alignment_context(self):
        windows = []
        with patch(
            "yuepu_translate.song_pipeline.make_voice_detector",
            return_value=lambda frame: np.max(np.abs(frame)) > 0.1,
        ):
            stream = make_song_stream(windows.append)
        audio = np.concatenate(
            (np.zeros(10 * 16000, np.float32), np.linspace(0.2, 0.8, 20 * 16000, dtype=np.float32))
        )
        stream.feed(audio)
        stream.flush()
        self.assertTrue(any(w.checkpoint for w in windows))
        for window in windows:
            self.assertGreater(len(window.samples), 0)
            np.testing.assert_array_equal(window.samples, audio[window.start : window.end])

    def test_paragraph_capture_does_not_grow_its_decode_window_with_history(self):
        windows = []
        with patch(
            "yuepu_translate.song_pipeline.make_voice_detector", return_value=lambda f: True
        ):
            stream = make_song_stream(windows.append)
        stream.feed(np.ones(120 * 16000, dtype=np.float32))
        stream.flush()
        self.assertLessEqual(max(len(w.samples) for w in windows), 8.032 * 16000)
        finals = [w for w in windows if w.final]
        self.assertGreaterEqual(len(finals), 8, "Archive bounded passages during continuous speech")

    def test_continuous_speech_updates_one_paragraph_until_a_real_end(self):
        windows = []
        stream = RollingAudio(windows.append)
        stream.feed(np.ones(31 * 16000, dtype=np.float32))
        self.assertFalse(any(w.final for w in windows))
        self.assertEqual({w.block for w in windows}, {0})
        stream.flush()
        self.assertEqual(sum(w.final for w in windows), 1)

    def test_long_input_keeps_overlap_and_never_rechecks_whole_history(self):
        windows = []
        stream = RollingAudio(windows.append)
        audio = 0.05 + np.arange(16000 * 31, dtype=np.float32) / 1e7
        for begin in range(0, len(audio), 512):
            stream.feed(audio[begin : begin + 512])
        stream.flush()
        finals = [w for w in windows if w.final or w.checkpoint]
        self.assertEqual(len(finals), 2)
        self.assertEqual([round(w.end / 16000) for w in finals], [30, 31])
        self.assertTrue(all(len(w.samples) <= 16000 * 30 for w in windows))
        self.assertTrue(all(w.end > w.start for w in windows))
        for window in finals:
            np.testing.assert_array_equal(window.samples, audio[window.start : window.end])
        self.assertEqual(finals[1].start, 16000 * 22)
        self.assertEqual(finals[-1].end, len(audio))
        count = len(windows)
        stream.flush()
        self.assertEqual(len(windows), count)

    def test_latest_drafts_coalesce_but_final_audio_is_preserved(self):
        windows = []
        stream = RollingAudio(windows.append)
        stream.feed(np.full(16000 * 17, 0.05, dtype=np.float32))
        stream.flush()
        mailbox = SongMailbox()
        for window in windows:
            mailbox.put(window)
        mailbox.finish()
        received = []
        while (window := mailbox.get(threading.Event())) is not None:
            received.append(window)
        self.assertEqual([w.block for w in received], [0])
        self.assertTrue(all(w.final for w in received))

    def test_queue_overload_is_explicit_instead_of_silently_losing_final_audio(self):
        windows = []
        RollingAudio(windows.append).feed(np.ones(16000 * 96, dtype=np.float32))
        mailbox = SongMailbox(max_finals=2)
        with self.assertRaisesRegex(RuntimeError, "跟不上"):
            for window in windows:
                mailbox.put(window)

    def test_cancel_discards_pending_work(self):
        mailbox = SongMailbox()
        cancel = threading.Event()
        cancel.set()
        self.assertIsNone(mailbox.get(cancel))

    def test_late_draft_cannot_reopen_a_confirmed_paragraph(self):
        windows = []
        stream = RollingAudio(windows.append)
        stream.feed(np.ones(16000 * 6, dtype=np.float32))
        stream.flush()
        mailbox = SongMailbox()
        mailbox.put(windows[-1])
        mailbox.put(windows[0])
        self.assertTrue(mailbox.has_waiting_confirmation(windows[-1].block))
        mailbox.finish()
        self.assertTrue(mailbox.get(threading.Event()).final)
        self.assertFalse(mailbox.has_waiting_confirmation(windows[-1].block))
        self.assertIsNone(mailbox.get(threading.Event()))

    def test_near_silence_does_not_produce_lyrics(self):
        windows = []
        stream = RollingAudio(windows.append)
        stream.feed(np.zeros(16000 * 10, dtype=np.float32))
        stream.flush()
        self.assertFalse(windows)

    def test_only_adjacent_context_is_removed_and_later_refrains_survive(self):
        self.assertEqual(trim_context("今日天气很好", "天气很好我们出发"), "我们出发")
        self.assertEqual(trim_context("测试完成", "新的测试完成"), "新的测试完成")
        self.assertEqual(trim_context("这是一段话", "这是一段话"), "")
        self.assertEqual(trim_context("甲乙丙", "丙丁"), "丙丁")
        self.assertEqual(trim_context("繁體測試", "测试新的内容"), "测试新的内容")

    def test_invalid_audio_does_not_enter_buffers(self):
        stream = RollingAudio(lambda window: None)
        for audio in (np.array([np.nan]), np.zeros((5, 2))):
            with self.assertRaises(ValueError):
                stream.feed(audio)

    def test_draft_that_would_delay_confirmation_is_skipped(self):
        windows = []
        stream = RollingAudio(windows.append)
        stream.feed(np.ones(16000 * 30, dtype=np.float32))
        stream.flush()
        first, near_final, final = windows[0], windows[-3], windows[-1]
        self.assertTrue(draft_fits(first, 0.15, 0.5, first.captured_at))
        self.assertFalse(draft_fits(near_final, 0.15, 0.5, near_final.captured_at))
        self.assertTrue(draft_fits(final, 100, 100, final.captured_at))

    def test_real_idle_resume_keeps_distinct_passages_and_only_recent_context(self):
        windows = []
        stream = RollingAudio(windows.append)
        stream.feed(np.ones(16000 * 3, dtype=np.float32))
        stream.flush()
        stream.feed(np.full(16000 * 5, 0.5, dtype=np.float32))
        stream.flush()
        finals = [w for w in windows if w.final]
        self.assertEqual([w.block for w in finals], [0, 1])
        self.assertEqual([w.start for w in finals], [0, 48000])
        self.assertEqual([w.end for w in finals], [48000, 128000])
        np.testing.assert_array_equal(finals[1].samples, np.full(80000, 0.5))


if __name__ == "__main__":
    unittest.main()
