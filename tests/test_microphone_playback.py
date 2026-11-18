"""Clocked speaker and synthetic microphone tests, without native audio devices."""

import subprocess
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from yuepu_translate.capture_process import CaptureProcess, mute_playback_overlap
from yuepu_translate.desktop_engine import AudioPlayer


class MicrophonePlaybackTests(unittest.TestCase):
    def test_partial_overlap_keeps_both_edges_and_does_not_edit_original_pcm(self):
        pcm = np.arange(10, dtype=np.float32).reshape(-1, 1)
        muted, count = mute_playback_overlap(
            pcm, 10, 101.0, lambda _a, _b: [(100.2, 100.6), (100.5, 100.8)]
        )
        self.assertEqual(count, 6)
        np.testing.assert_array_equal(muted[:, 0], [0, 1, 0, 0, 0, 0, 0, 0, 8, 9])
        np.testing.assert_array_equal(pcm[:, 0], np.arange(10))

    def test_delayed_microphone_delivery_uses_the_played_interval_and_preserves_timeline(self):
        errors = []
        wrote = threading.Event()
        fake_stream = SimpleNamespace(
            start=lambda: None, close=lambda: None, write=lambda _pcm: wrote.set(), latency=0.006
        )
        with patch.dict(
            sys.modules, {"sounddevice": SimpleNamespace(OutputStream=lambda **kw: fake_stream)}
        ):
            speaker = AudioPlayer(errors.append)
            try:
                speaker.put(np.ones(512, dtype=np.float32), 16000, threading.Event())
                self.assertTrue(wrote.wait(2))
                intervals = speaker.playback_intervals(0, time.monotonic() + 1)
                self.assertEqual(len(intervals), 1)
                start_ns = round(intervals[0][0] * 1_000_000_000)
                helper = """
import json, struct, sys
from yuepu_translate.capture_process import AUDIO_HEADER, write_packet
out = sys.stdout.buffer
fmt = dict(rate=16000, channels=1)
write_packet(out,b'F',json.dumps(fmt).encode())
assert sys.stdin.buffer.read(1)==b'g'
write_packet(out,b'R',json.dumps(dict(**fmt,name='simulated microphone',mode='paragraph',version=2)).encode())
for n, sample in enumerate((0.125, 0.75, 0.25)):
    timestamp = int(sys.argv[1]) + n*32_000_000
    write_packet(out,b'A',AUDIO_HEADER.pack(n,timestamp) + struct.pack('<f',sample)*512)
write_packet(out,b'D',b'{"reason":"stopped","packets":3,"frames":1536,"peak_frames":1536,"rejected_frames":0}')
"""
                for enabled in (False, True):
                    with self.subTest(enabled=enabled):
                        seen = []
                        sink = SimpleNamespace(
                            feed=lambda samples: seen.append(samples.copy()), flush=lambda: None
                        )
                        capture = CaptureProcess(
                            "microphone",
                            lambda w: None,
                            errors.append,
                            paragraph=True,
                            segmenter_factory=lambda _: sink,
                        )
                        if enabled:
                            capture.playback_intervals = speaker.playback_intervals
                        done = threading.Event()
                        capture.on_finished = done.set
                        popen = subprocess.Popen
                        with patch(
                            "yuepu_translate.capture_process.subprocess.Popen",
                            lambda cmd, **kw: popen(
                                [sys.executable, "-c", helper, str(start_ns)], **kw
                            ),
                        ):
                            capture.start()
                            try:
                                self.assertTrue(done.wait(8))
                            finally:
                                capture.stop()
                        values = np.concatenate(seen)
                        np.testing.assert_array_equal(
                            values, np.repeat([0.125, 0 if enabled else 0.75, 0.25], 512)
                        )
                        self.assertEqual(capture.report.frames, 1536)
                        self.assertEqual(capture.report.muted_frames, 512 if enabled else 0)
                        self.assertEqual(capture.report.reason, "stopped")
                        self.assertFalse(errors)
            finally:
                speaker.close()
