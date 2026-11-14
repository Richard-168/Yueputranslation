"""Realtime voice gating retains short/quiet PCM without boosting recognition input."""

import sys
import types
import unittest
from unittest.mock import patch

import numpy as np

from yuepu_translate.live_session import make_live_stream
from yuepu_translate.song_pipeline import make_song_stream, make_voice_detector


class VoiceGate:
    """A deterministic onset-duration gate, not a substitute for Silero quality tests."""

    def __init__(self, live=False, sensitivity="standard"):
        self.minimum = (3 if sensitivity == "sensitive" else 4) if live else 8
        self.frames = 0
        self.inputs = []

    def accept_waveform(self, frame):
        self.inputs.append(frame.copy())
        self.frames = self.frames + 1 if np.max(np.abs(frame)) >= 0.04 else 0

    def empty(self):
        return True

    def is_speech_detected(self):
        return self.frames >= self.minimum


class VoiceActivityTests(unittest.TestCase):
    def engine(self):
        engine = types.ModuleType("yuepu_translate.desktop_engine")
        self.gates = []

        def make_vad(*, live=False, sensitivity="standard"):
            gate = VoiceGate(live, sensitivity)
            self.gates.append(gate)
            return gate

        engine.make_vad = make_vad
        return patch.dict(sys.modules, {"yuepu_translate.desktop_engine": engine})

    def test_both_live_modes_detect_short_quiet_speech_and_keep_original_audio(self):
        audio = np.concatenate((np.zeros(16000, np.float32), np.full(512 * 6, 0.006, np.float32)))
        for factory in (make_live_stream, make_song_stream):
            with self.subTest(mode=factory.__name__), self.engine():
                windows = []
                stream = factory(windows.append, sensitivity="sensitive")
                stream.feed(audio)
                stream.flush()
                self.assertTrue(windows, "Quiet short speech must reach recognition")
                self.assertTrue(windows[-1].final)
                for window in windows:
                    np.testing.assert_array_equal(window.samples, audio[window.start : window.end])
                self.assertAlmostEqual(float(np.max(self.gates[0].inputs[-1])), 0.048)

    def test_file_detector_keeps_original_gate_and_amplitude(self):
        with self.engine():
            activity = make_voice_detector()
            frame = np.full(512, 0.006, np.float32)
            self.assertFalse(any(activity(frame) for _ in range(6)))
            np.testing.assert_array_equal(self.gates[0].inputs[0], frame)
            self.assertEqual(self.gates[0].minimum, 8)

    def test_live_gain_is_bounded_and_never_attenuates_loud_input(self):
        with self.engine():
            activity = make_voice_detector(live=True, sensitivity="sensitive")
            for value in (0, 0.0001, 0.005, 0.05, 0.5):
                frame = np.full(512, value, np.float32)
                before = frame.copy()
                activity(frame)
                actual = self.gates[0].inputs[-1]
                np.testing.assert_array_equal(frame, before)
                self.assertTrue(np.isfinite(actual).all())
                self.assertLessEqual(float(actual.max()), value * 8 + 1e-7)
                self.assertGreaterEqual(float(actual.max()), value - 1e-7)
            self.assertAlmostEqual(float(self.gates[0].inputs[-1].max()), 0.5)

    def test_standard_does_not_boost_quiet_background_but_admits_short_audible_speech(self):
        with self.engine():
            activity = make_voice_detector(live=True)
            quiet = np.full(512, 0.006, np.float32)
            self.assertFalse(any(activity(quiet) for _ in range(6)))
            audible = np.full(512, 0.1, np.float32)
            self.assertTrue(any(activity(audible) for _ in range(6)))
            np.testing.assert_array_equal(self.gates[0].inputs[0], quiet)

    def test_invalid_sensitivity_is_rejected_before_native_detector_is_created(self):
        with self.engine():
            with self.assertRaises(ValueError):
                make_voice_detector(live=True, sensitivity="unknown")
            self.assertEqual(self.gates, [])


if __name__ == "__main__":
    unittest.main()
