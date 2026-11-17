"""Scheduling contracts only; synthetic text is not model quality evidence."""

import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from yuepu_translate.inference_control import InferenceCancelled
from yuepu_translate.live_session import LiveSession, make_live_stream
from yuepu_translate.song_stream import SongWindow


class Converter:
    def convert(self, text):
        return text


class Engine:
    converters = {"zh": Converter()}

    def recognize(self, samples, rate, cancel, source, emit):
        return "测试" + str(round(float(samples[0])))

    def speak(self, text, target, mode, player, cancel, first_audio):
        pass


class SlowTranslation:
    entered = release = None

    def __init__(self, *args, **kwargs):
        pass

    def start(self, cancel):
        pass

    def transcribe(self, samples, cancel):
        return "测试" + str(round(float(samples[0])))

    def translate(self, text, cancel):
        self.entered.set()
        while not self.release.wait(0.01):
            if cancel.is_set():
                return ""
        return "译文" + text

    def punctuate(self, text, cancel):
        return text

    def close(self):
        pass


def window(block=0, value=1, final=False):
    tick = time.monotonic()
    return SongWindow(
        block,
        0,
        16000 * value,
        np.full(16000 * value, value, dtype=np.float32),
        final,
        tick,
        tick + 30,
        voice_end=16000 * value,
    )


class LiveSessionTests(unittest.TestCase):
    def test_first_draft_appears_before_a_pause_and_keeps_updating(self):
        windows = []
        stream = make_live_stream(windows.append, detector=lambda frame: True)
        stream.feed(np.ones(16000, dtype=np.float32))
        self.assertEqual(len(windows), 1)
        self.assertLessEqual(windows[0].end / 16000, 0.84)
        self.assertFalse(windows[0].final)
        stream.feed(np.ones(16000 * 2, dtype=np.float32))
        self.assertGreaterEqual(len(windows), 4)
        self.assertEqual({w.block for w in windows}, {0})
        self.assertFalse(any(w.final for w in windows))

    def test_uninterrupted_speech_stays_bounded_without_losing_cut_audio(self):
        windows = []
        stream = make_live_stream(windows.append, detector=lambda frame: True)
        audio = np.linspace(0.1, 1, 25 * 16000, dtype=np.float32)
        stream.feed(audio)
        stream.flush()
        finals = [w for w in windows if w.final]
        self.assertEqual([w.block for w in finals], [0, 1, 2, 3])
        self.assertTrue(all(len(w.samples) <= 8.032 * 16000 for w in windows))
        np.testing.assert_array_equal(np.concatenate([w.samples for w in finals]), audio)

    def test_silence_is_not_sent_to_the_recognizer(self):
        windows = []
        stream = make_live_stream(windows.append, detector=lambda frame: False)
        stream.feed(np.zeros(16000 * 10, dtype=np.float32))
        stream.flush()
        self.assertEqual(windows, [])

    def test_stop_drains_confirmations_after_a_burst_during_slow_translation(self):
        entered, release, backlog_reached = threading.Event(), threading.Event(), threading.Event()
        SlowTranslation.entered, SlowTranslation.release = entered, release
        session, cancel = LiveSession("yue"), threading.Event()
        events, errors = [], []

        def emit(kind, value):
            events.append((kind, value))
            if kind == "live_source" and value["final"] and value["block"] == 4:
                backlog_reached.set()

        def run():
            try:
                session.run(Engine(), None, cancel, emit)
            except Exception as exc:
                errors.append(exc)

        with patch("yuepu_translate.live_session.SessionInference", SlowTranslation):
            worker = threading.Thread(target=run)
            worker.start()
            try:
                session.mailbox.put(window(final=True))
                self.assertTrue(entered.wait(2))
                for block in range(1, 8):
                    session.mailbox.put(window(block, value=block + 1, final=True))
                self.assertTrue(backlog_reached.wait(2))
                session.mailbox.finish()
                release.set()
                worker.join(3)
                self.assertFalse(worker.is_alive())
                self.assertFalse(cancel.is_set())
            finally:
                release.set()
                cancel.set()
                session.mailbox.finish()
                worker.join(3)
        self.assertEqual(errors, [])
        self.assertEqual(
            [
                value["block"]
                for kind, value in events
                if kind == "live_translation" and value["final"]
            ],
            list(range(8)),
        )
        self.assertEqual(events[-1], ("song_drained", dict(confirmed_count=8, partial_count=0)))

    def test_source_keeps_up_while_translation_is_blocked(self):
        entered, release, updated = threading.Event(), threading.Event(), threading.Event()
        SlowTranslation.entered, SlowTranslation.release = entered, release
        session, cancel, errors = LiveSession("yue"), threading.Event(), []

        def emit(kind, value):
            if kind.endswith("_source") and value["text"] == "测试2":
                updated.set()

        def run():
            try:
                session.run(Engine(), None, cancel, emit)
            except Exception as exc:
                errors.append(exc)

        with patch("yuepu_translate.live_session.SessionInference", SlowTranslation):
            thread = threading.Thread(target=run)
            thread.start()
            try:
                session.mailbox.put(window())
                self.assertTrue(entered.wait(2), "First translation must start")
                session.mailbox.put(window(value=2))
                self.assertTrue(
                    updated.wait(1), "Translation must not block the next source caption"
                )
            finally:
                release.set()
                session.mailbox.finish()
                thread.join(3)
                cancel.set()
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_translation_warmup_does_not_delay_the_first_source(self):
        starting, release, source = threading.Event(), threading.Event(), threading.Event()
        session, cancel, errors = LiveSession("zh"), threading.Event(), []

        class LoadingTranslation(SlowTranslation):
            def start(self, cancel):
                starting.set()
                release.wait(3)

            def translate(self, text, cancel):
                return "译文"

        def run():
            try:
                session.run(
                    Engine(),
                    None,
                    cancel,
                    lambda kind, value: source.set() if kind == "live_source" else None,
                )
            except Exception as exc:
                errors.append(exc)

        with patch("yuepu_translate.live_session.SessionInference", LoadingTranslation):
            thread = threading.Thread(target=run)
            thread.start()
            try:
                self.assertTrue(starting.wait(2))
                session.mailbox.put(window())
                self.assertTrue(source.wait(1), "ASR must not wait for translation warm-up")
            finally:
                release.set()
                session.mailbox.finish()
                thread.join(3)
                cancel.set()
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_cancel_reaps_translation_and_does_not_emit_a_completed_draft(self):
        entered, release = threading.Event(), threading.Event()
        SlowTranslation.entered, SlowTranslation.release = entered, release
        session, cancel, events, errors = LiveSession("yue"), threading.Event(), [], []

        def run():
            try:
                session.run(Engine(), None, cancel, lambda *event: events.append(event))
            except InferenceCancelled:
                pass
            except Exception as exc:
                errors.append(exc)

        with patch("yuepu_translate.live_session.SessionInference", SlowTranslation):
            thread = threading.Thread(target=run)
            thread.start()
            try:
                session.mailbox.put(window())
                self.assertTrue(entered.wait(2))
                cancel.set()
                thread.join(3)
            finally:
                release.set()
                session.mailbox.finish()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertNotIn("live_translation", [kind for kind, _ in events])
        self.assertNotIn("song_drained", [kind for kind, _ in events])

    def test_only_final_text_is_spoken_and_final_source_is_versioned(self):
        entered, release = threading.Event(), threading.Event()
        SlowTranslation.entered, SlowTranslation.release = entered, release
        session, cancel, events, spoken = (
            LiveSession("zh", autoplay=True),
            threading.Event(),
            [],
            [],
        )
        engine = Engine()
        engine.speak = lambda text, *args: spoken.append(text)

        def emit(kind, value):
            events.append((kind, value))
            if kind == "live_source" and not value["final"]:
                session.mailbox.put(window(final=True))
                session.mailbox.finish()

        release.set()
        with patch("yuepu_translate.live_session.SessionInference", SlowTranslation):
            session.mailbox.put(window())
            session.run(engine, None, cancel, emit)
        sources = [value for kind, value in events if kind == "live_source"]
        self.assertEqual([value["version"] for value in sources], [1, 2])
        self.assertEqual([value["final"] for value in sources], [False, True])
        self.assertEqual(len(spoken), 1)
        self.assertEqual(spoken[0], "译文测试1。")
        self.assertEqual(events[-1][0], "song_drained")


if __name__ == "__main__":
    unittest.main()
