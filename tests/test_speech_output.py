"""Task-owned sound device failures, live scheduling and Cantonese phrase limits."""

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from yuepu_translate.desktop_engine import AudioPlayer, Cancelled, Engine, cantonese_phrases
from yuepu_translate.inference_control import IncompleteSpeech, LiveSpeech, PlaybackUnavailable


class PlaybackTests(unittest.TestCase):
    def exercise_device_error(self, replace_task):
        entered, release, heard = threading.Event(), threading.Event(), threading.Event()
        notices, opens = [], []
        cancel = threading.Event()
        pcm = np.ones(16, dtype=np.float32)

        def open_stream(**kwargs):
            fail = not opens
            opens.append(fail)

            def write(data):
                if fail:
                    entered.set()
                    release.wait(3)
                    raise OSError("simulated disconnect")
                heard.set()

            return SimpleNamespace(start=lambda: None, write=write, close=lambda: None)

        with patch.dict("sys.modules", {"sounddevice": SimpleNamespace(OutputStream=open_stream)}):
            player = AudioPlayer(self.fail)
            try:
                old = player.for_task(notices.append)
                for _ in range(6):
                    old.put(pcm, 16000, cancel)
                self.assertTrue(entered.wait(2))
                if replace_task:
                    player.stop()
                new = player.for_task(self.fail)
                new.put(pcm, 16000, cancel)
                release.set()
                self.assertTrue(heard.wait(2))
                self.assertEqual(len(opens), 2)
                self.assertEqual(len(notices), 0 if replace_task else 1)
                with self.assertRaises(Cancelled if replace_task else PlaybackUnavailable):
                    old.put(pcm, 16000, cancel)
            finally:
                release.set()
                player.close()

    def test_late_write_failure_cannot_clear_or_mute_a_new_session(self):
        self.exercise_device_error(replace_task=True)

    def test_one_device_error_per_task_and_independent_replay(self):
        self.exercise_device_error(replace_task=False)

    def test_mic_mask_only_tracks_audio_written_to_device_and_clips_requested_time(self):
        writing, release = threading.Event(), threading.Event()

        def write(data):
            writing.set()
            release.wait(3)

        stream = SimpleNamespace(start=lambda: None, write=write, close=lambda: None, latency=0.05)
        with patch.dict(
            "sys.modules", {"sounddevice": SimpleNamespace(OutputStream=lambda **kw: stream)}
        ):
            player = AudioPlayer(self.fail)
            try:
                before = time.monotonic()
                self.assertEqual(player.playback_intervals(before - 2, before + 2), ())
                output = player.for_task(self.fail)
                output.put(np.ones(160), 16000, threading.Event())
                self.assertTrue(writing.wait(2))
                ((begin, end),) = player.playback_intervals(before - 2, before + 2)
                self.assertGreaterEqual(begin, before + 0.05)
                self.assertAlmostEqual(end - begin, 0.010, places=5)
                self.assertEqual(
                    player.playback_intervals(begin + 0.002, end - 0.001),
                    ((begin + 0.002, end - 0.001),),
                )
                self.assertEqual(player.playback_intervals(end, end + 1), ())
            finally:
                release.set()
                player.close()

    def test_live_speech_backlog_preserves_admitted_phrases_and_warns_once(self):
        playing, release = threading.Event(), threading.Event()
        phrases, notices = [], []

        def speak(text, *args):
            phrases.append(text)
            playing.set()
            release.wait(3)

        owner = SimpleNamespace(source="zh", number_mode="original", autoplay=True)
        speech = LiveSpeech(
            owner,
            SimpleNamespace(speak=speak),
            None,
            threading.Event(),
            lambda k, v: notices.append(k),
        )
        try:
            speech.submit("first")
            self.assertTrue(playing.wait(2))
            for text in ("second", "third", "fourth", "fifth"):
                speech.submit(text)
            self.assertEqual(phrases, ["first"])
            self.assertEqual(notices, ["speech_warning"])
            self.assertFalse(owner.autoplay)
        finally:
            release.set()
            speech.finish()
        self.assertEqual(phrases, ["first", "second", "third"])

    def test_cancel_stops_pending_speech(self):
        playing, cancel = threading.Event(), threading.Event()
        spoken = []

        def speak(text, *args):
            spoken.append(text)
            playing.set()
            cancel.wait(2)
            raise Cancelled()

        session = SimpleNamespace(source="zh", number_mode="original", autoplay=True)
        lane = LiveSpeech(session, SimpleNamespace(speak=speak), None, cancel, self.fail)
        lane.submit("正在播")
        self.assertTrue(playing.wait(2))
        lane.submit("等待播")
        cancel.set()
        lane.finish()
        self.assertEqual(spoken, ["正在播"])


class CantoneseSpeechTests(unittest.TestCase):
    def test_long_text_preserves_all_words_and_short_sentences_are_unchanged(self):
        short = "佢今日唔得閒，聽日下晝三點先嚟。"
        self.assertEqual(list(cantonese_phrases(short)), [short])
        long = short * 6 + "最後個密碼係七二九。"
        pieces = list(cantonese_phrases(long))
        self.assertEqual("".join(pieces), long)
        self.assertTrue(all(0 < len(p) <= 28 for p in pieces))
        self.assertTrue(pieces[-1].endswith("最後個密碼係七二九。"))

    def test_hitting_frame_limit_explicitly_marks_speech_incomplete(self):
        engine = Engine()
        self.addCleanup(engine.close)
        engine.converters = {"yue": SimpleNamespace(convert=lambda t: t)}
        runtime = Mock()
        runtime.manifest = {"generation_defaults": {}}
        runtime.codec_meta = {"codec_config": {"sample_rate": 48000}}
        runtime.codec_streaming_session.run_frames.return_value = (np.ones((1, 2, 8)), 8)

        def generate(request, on_frame):
            frames = []
            for i in range(200):
                frames.append([1])
                on_frame(frames, i, frames[-1])
            return frames

        runtime.generate_audio_frames.side_effect = generate
        engine.yue_tts = SimpleNamespace(
            _backend=SimpleNamespace(
                _runtime=runtime, _default_voice_codes=[], _encoder=Mock(), to_phoneme=lambda t: t
            )
        )
        player = AudioPlayer(self.fail, muted=True)
        self.addCleanup(player.close)
        first = Mock()
        with self.assertRaises(IncompleteSpeech):
            engine.speak("短句", "yue", "original", player, threading.Event(), first)
        first.assert_called_once()


if __name__ == "__main__":
    unittest.main()
