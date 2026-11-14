"""Fast provisional captions preserve the existing paragraph audio boundaries."""

import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

from yuepu_translate.inference_control import InferenceCancelled
from yuepu_translate.song_pipeline import SongSession, make_song_stream
from yuepu_translate.song_stream import RollingAudio, SongWindow


class Engine:
    converters = {"zh": type("Converter", (), {"convert": lambda self, text: text})()}

    def recognize(self, samples, rate, cancel, source, emit):
        return "轻量暂定内容" + str(int(samples[0]))

    def speak(self, *args):
        pass


def window(block=0, *, final=False, checkpoint=False, start=0, end=16000, value=1):
    tick = time.monotonic()
    return SongWindow(
        block,
        start,
        end,
        np.full(end - start, value, np.float32),
        final,
        tick,
        tick + 30,
        checkpoint=checkpoint,
        voice_end=end,
    )


class ParagraphLiveTests(unittest.TestCase):
    def test_draft_translation_is_shown_before_final_review_and_then_corrected(self):
        preview_ready, final_ready = threading.Event(), threading.Event()
        events, spoken, errors = [], [], []
        session, cancel = SongSession("zh", autoplay=True), threading.Event()

        class Inference:
            def __init__(self, *args, **kwargs):
                pass

            def start(self, cancel):
                pass

            def transcribe(self, samples, cancel):
                final_ready.set()
                return "大模型确认的正确内容"

            def translate(self, text, cancel):
                return "译文" + text

            def close(self):
                pass

        def emit(kind, value):
            events.append((kind, value))
            if kind == "live_translation" and not value["final"]:
                preview_ready.set()

        engine = Engine()
        engine.speak = lambda text, *args: spoken.append(text)

        def run():
            try:
                session.run(engine, None, cancel, emit)
            except Exception as exc:
                errors.append(exc)

        with patch("yuepu_translate.song_pipeline.SessionInference", Inference):
            thread = threading.Thread(target=run)
            thread.start()
            try:
                session.mailbox.put(window())
                self.assertTrue(preview_ready.wait(2), "Do not wait for source confirmation")
                self.assertFalse(final_ready.is_set() or spoken)
                draft = [v for k, v in events if k == "live_translation"][-1]
                self.assertEqual(draft["text"], "译文轻量暂定内容1")
                self.assertEqual(draft["frozen_target"], "")
                session.mailbox.put(window(final=True))
                session.mailbox.finish()
                thread.join(3)
            finally:
                cancel.set()
                session.mailbox.finish()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        translations = [v for k, v in events if k == "live_translation"]
        self.assertEqual(translations[-1]["text"], "译文大模型确认的正确内容。")
        self.assertTrue(translations[-1]["final"])
        self.assertEqual(spoken, ["译文大模型确认的正确内容。"])

    def test_blocked_draft_translation_does_not_block_source_and_final_has_priority(self):
        entered, release, updated = threading.Event(), threading.Event(), threading.Event()
        calls, events, errors = [], [], []
        session, cancel = SongSession("zh"), threading.Event()

        class Inference:
            def __init__(self, *args, **kwargs):
                pass

            def start(self, cancel):
                pass

            def transcribe(self, samples, cancel):
                return "最后确认内容"

            def translate(self, text, cancel):
                calls.append(text)
                if len(calls) == 1:
                    entered.set()
                    while not release.wait(0.01):
                        if cancel.is_set():
                            raise InferenceCancelled()
                return text

            def close(self):
                pass

        def emit(kind, value):
            events.append((kind, value))
            if kind == "live_source" and value["text"] == "轻量暂定内容2":
                updated.set()

        def run():
            try:
                session.run(Engine(), None, cancel, emit)
            except Exception as exc:
                errors.append(exc)

        with patch("yuepu_translate.song_pipeline.SessionInference", Inference):
            thread = threading.Thread(target=run)
            thread.start()
            try:
                session.mailbox.put(window())
                self.assertTrue(entered.wait(2))
                session.mailbox.put(window(end=32000, value=2))
                self.assertTrue(updated.wait(1))
                session.mailbox.put(window(final=True, end=32000, value=2))
                session.mailbox.finish()
                release.set()
                thread.join(3)
            finally:
                release.set()
                cancel.set()
                session.mailbox.finish()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(calls, ["轻量暂定内容1", "最后确认内容。"])

    def test_cancel_reaps_review_without_confirming_a_light_guess(self):
        entered, closed = threading.Event(), threading.Event()
        events, errors = [], []
        session, cancel = SongSession("zh"), threading.Event()

        class Inference:
            def __init__(self, *args, **kwargs):
                pass

            def start(self, cancel):
                pass

            def transcribe(self, samples, cancel):
                entered.set()
                cancel.wait(3)
                raise InferenceCancelled()

            def translate(self, text, cancel):
                raise AssertionError("Canceled guesses must not be translated")

            def close(self):
                closed.set()

        def run():
            try:
                session.run(Engine(), None, cancel, lambda *event: events.append(event))
            except InferenceCancelled:
                pass
            except Exception as exc:
                errors.append(exc)

        with patch("yuepu_translate.song_pipeline.SessionInference", Inference):
            thread = threading.Thread(target=run)
            thread.start()
            try:
                session.mailbox.put(window(final=True))
                self.assertTrue(entered.wait(2))
            finally:
                cancel.set()
                session.mailbox.finish()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(closed.is_set())
        self.assertEqual(errors, [])
        self.assertFalse(any(k == "live_source" and v["final"] for k, v in events))
        self.assertNotIn("song_drained", [k for k, _ in events])

    def test_empty_review_leaves_the_light_guess_unconfirmed(self):
        events = []

        class Inference:
            def __init__(self, *args, **kwargs):
                pass

            def start(self, cancel):
                pass

            def transcribe(self, samples, cancel):
                return ""

            def translate(self, text, cancel):
                raise AssertionError("An unreviewed guess must not be translated")

            def close(self):
                pass

        session = SongSession("zh")
        session.mailbox.put(window(final=True))
        session.mailbox.finish()
        with patch("yuepu_translate.song_pipeline.SessionInference", Inference):
            session.run(Engine(), None, threading.Event(), lambda *event: events.append(event))
        self.assertFalse(any(k == "live_source" and v["final"] for k, v in events))
        self.assertIn("live_empty", [k for k, _ in events])
        self.assertEqual(events[-1][1], dict(confirmed_count=0, partial_count=1))

    def test_flush_immediately_after_checkpoint_still_confirms_the_same_audio_end(self):
        events, calls = [], []

        class Inference:
            def __init__(self, *args, **kwargs):
                pass

            def start(self, cancel):
                pass

            def transcribe(self, samples, cancel):
                return "检查点之后立即停止"

            def translate(self, text, cancel):
                calls.append(text)
                return text

            def close(self):
                pass

        session = SongSession("zh")
        session.mailbox.put(window(checkpoint=True, end=128000))
        session.mailbox.put(window(final=True, start=96000, end=128000))
        session.mailbox.finish()
        with patch("yuepu_translate.song_pipeline.SessionInference", Inference):
            session.run(Engine(), None, threading.Event(), lambda *event: events.append(event))
        sources = [v for k, v in events if k == "live_source"]
        self.assertTrue(sources[-1]["final"])
        reviewed = [v for v in sources if v.get("reviewed")]
        self.assertGreater(reviewed[-1]["version"], reviewed[0]["version"])
        self.assertEqual(calls, ["检查点之后立即停止。"])

    def test_preview_is_early_while_pause_checkpoints_and_final_audio_are_unchanged(self):
        old, new = [], []

        def detector(frame):
            return bool(np.max(np.abs(frame)) > 0.1)

        baseline = RollingAudio(
            old.append,
            detector=detector,
            context_seconds=8,
            overlap_seconds=2,
            max_segment_seconds=15,
        )
        with patch("yuepu_translate.song_pipeline.make_voice_detector", return_value=detector):
            stream = make_song_stream(new.append)
        audio = np.concatenate((np.ones(17 * 16000, np.float32), np.zeros(4 * 16000, np.float32)))
        baseline.feed(audio)
        baseline.flush()
        stream.feed(audio)
        stream.flush()
        self.assertLessEqual(new[0].end / 16000, 0.832)

        def endings(windows):
            return [
                (w.block, w.start, w.end, w.final, w.checkpoint, w.voice_end)
                for w in windows
                if w.final or w.checkpoint
            ]

        self.assertEqual(endings(new), endings(old))
        self.assertEqual(stream.pause_samples, baseline.pause_samples)
        self.assertEqual(stream.pre_roll_samples, baseline.pre_roll_samples)

    def test_blocked_review_keeps_new_captions_provisional_until_reviewed(self):
        entered, release, next_source = threading.Event(), threading.Event(), threading.Event()
        calls, spoken, events, errors = [], [], [], []
        session, cancel = SongSession("zh", autoplay=True), threading.Event()

        class Inference:
            def __init__(self, *args, **kwargs):
                pass

            def start(self, cancel):
                pass

            def transcribe(self, samples, cancel):
                entered.set()
                while not release.wait(0.01):
                    if cancel.is_set():
                        raise InferenceCancelled()
                return "大模型修正内容" + str(int(samples[0]))

            def translate(self, text, cancel):
                calls.append(text)
                return "译文" + text

            def close(self):
                pass

        def emit(kind, value):
            events.append((kind, value))
            if kind == "live_source" and value["block"] == 1:
                next_source.set()

        engine = Engine()
        engine.speak = lambda text, *args: spoken.append(text)

        def run():
            try:
                session.run(engine, None, cancel, emit)
            except Exception as exc:
                errors.append(exc)

        with patch("yuepu_translate.song_pipeline.SessionInference", Inference):
            thread = threading.Thread(target=run)
            thread.start()
            try:
                session.mailbox.put(window(final=True))
                self.assertTrue(entered.wait(2))
                session.mailbox.put(window(1, value=2))
                self.assertTrue(next_source.wait(1))
                self.assertFalse(calls or spoken)
                self.assertTrue(
                    all(v["frozen_characters"] == 0 for k, v in events if k == "live_source")
                )
                session.mailbox.put(window(1, final=True, value=2))
                session.mailbox.finish()
                release.set()
                thread.join(3)
            finally:
                release.set()
                cancel.set()
                session.mailbox.finish()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        confirmed = ["大模型修正内容1。", "大模型修正内容2。"]
        # The worker may translate block 1's preview before its final window
        # reaches the review queue. Both schedules must confirm the same text.
        self.assertIn(calls, [confirmed, [confirmed[0], "轻量暂定内容2", confirmed[1]]])
        self.assertEqual(
            [v["source"] for k, v in events if k == "live_translation" and v["final"]],
            confirmed,
        )
        self.assertEqual(spoken, ["译文大模型修正内容1。", "译文大模型修正内容2。"])
        self.assertEqual(events[-1][0], "song_drained")

    def test_review_checkpoints_keep_history_when_final_audio_only_contains_the_tail(self):
        calls, events = [], []

        class Inference:
            def __init__(self, *args, **kwargs):
                pass

            def start(self, cancel):
                pass

            def transcribe(self, samples, cancel):
                return (
                    "前面的内容已经说明，今天天气真的很好"
                    if int(samples[0]) == 1
                    else "今天天气真的很好，我们现在出发"
                )

            def translate(self, text, cancel):
                calls.append(text)
                return text

            def close(self):
                pass

        session = SongSession("yue")
        session.mailbox.put(window(checkpoint=True, end=128000))
        session.mailbox.put(window(final=True, start=96000, end=160000, value=2))
        session.mailbox.finish()
        with patch("yuepu_translate.song_pipeline.SessionInference", Inference):
            session.run(Engine(), None, threading.Event(), lambda *event: events.append(event))
        expected = "前面的内容已经说明，今天天气真的很好，我们现在出发。"
        finals = [v for k, v in events if k == "live_source" and v["final"]]
        self.assertEqual([v["text"] for v in finals], [expected])
        self.assertEqual(calls, [expected])


if __name__ == "__main__":
    unittest.main()
