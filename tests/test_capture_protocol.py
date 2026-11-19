"""No-device PCM checks; owned synthetic helpers verify bounded recovery."""

import io
import json
import struct
import subprocess
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from yuepu_translate import capture_worker
from yuepu_translate.capture_process import (
    AUDIO_HEADER,
    MAX_PACKET,
    CaptureProcess,
    read_packet,
    write_packet,
)
from yuepu_translate.song_stream import RollingAudio


class CaptureProtocolTests(unittest.TestCase):
    @staticmethod
    def microphone_burst(count, *, device_fault=False):
        """Run the actual helper with callbacks arriving before its writer can drain."""
        stop = threading.Event()

        class Pipe(io.BytesIO):
            packets = 0

            def write(self, data):
                if data[:1] == b"A":
                    self.packets += 1
                    if self.packets == count:
                        stop.set()
                return super().write(data)

        class Microphone:
            active = True

            def __init__(self, callback, **kwargs):
                self.callback = callback

            def __enter__(self):
                for sequence in range(count):
                    data = struct.pack("<512f", *([float(sequence)] * 512))
                    self.callback(data, 512, None, device_fault and sequence == count - 1)
                return self

            def __exit__(self, *exc):
                pass

        output = Pipe()
        stdin = SimpleNamespace(buffer=SimpleNamespace(read=lambda size: (stop.wait(2), b"s")[1]))
        streams = SimpleNamespace(stdin=stdin, stdout=SimpleNamespace(buffer=output))
        try:
            with (
                patch.object(sys, "argv", ["capture_worker", "microphone", "paragraph"]),
                patch.object(capture_worker, "sys", streams),
                patch.dict(sys.modules, sounddevice=SimpleNamespace(RawInputStream=Microphone)),
            ):
                capture_worker.main()
        finally:
            stop.set()
        output.seek(0)
        packets = []
        while output.tell() < len(output.getbuffer()):
            packets.append(read_packet(output))
        return packets

    def test_burst_preserves_pcm_in_order_and_reports_first_unaccepted_packet(self):
        for offered in (64, 65, 125, 126):
            with self.subTest(offered=offered):
                packets = self.microphone_burst(offered)
                self.assertEqual(packets[0][0], b"R")
                self.assertEqual(packets[-1][0], b"D")
                retained = min(offered, 125)
                self.assertEqual(len(packets) - 2, retained)
                for sequence, (kind, payload) in enumerate(packets[1:-1]):
                    index, stamp = AUDIO_HEADER.unpack_from(payload)
                    self.assertEqual((kind, index), (b"A", sequence))
                    self.assertGreater(stamp, 0)
                    self.assertEqual(
                        payload[AUDIO_HEADER.size :], struct.pack("<f", sequence) * 512
                    )
                summary = json.loads(packets[-1][1])
                self.assertEqual(summary["frames"], retained * 512)
                self.assertEqual(summary["peak_frames"], retained * 512)
                self.assertEqual(summary["packets"], retained)
                self.assertEqual(summary["reason"], "overload" if offered > 125 else "stopped")
                self.assertEqual(summary["rejected_frames"], 512 if offered > 125 else 0)

    def test_device_discontinuity_flushes_accepted_pcm_without_claiming_loss_duration(self):
        packets = self.microphone_burst(4, device_fault=True)
        self.assertEqual([kind for kind, _ in packets], [b"R", b"A", b"A", b"A", b"D"])
        summary = json.loads(packets[-1][1])
        self.assertEqual(summary["reason"], "device")
        self.assertEqual(summary["frames"], 3 * 512)
        self.assertEqual(summary["rejected_frames"], 0)

    def test_buffer_counts_frames_at_device_rate_and_caps_memory_and_packet_count(self):
        for rate, channels, chunk_frames, expected in (
            (48000, 2, 1024, 187),
            (192000, 32, 1024, 32),
            (48000, 1, 1, 512),
        ):
            with self.subTest(rate=rate, channels=channels, chunk_frames=chunk_frames):
                buffer = capture_worker.CaptureBuffer(rate, channels)
                data = bytes(chunk_frames * channels * 4)
                for _ in range(expected):
                    self.assertTrue(buffer.push(data, False))
                self.assertFalse(buffer.push(data, False))
                self.assertEqual(buffer.reason, "overload")
                self.assertEqual(buffer.queued_frames, expected * chunk_frames)
                self.assertEqual(buffer.rejected_frames, chunk_frames)

    def test_capture_flushes_tail_before_interruption_and_finished(self):
        helper = """
import json,struct,sys,time
from yuepu_translate.capture_process import AUDIO_HEADER,write_packet
def send(k,v):
    write_packet(sys.stdout.buffer,k,json.dumps(v).encode())
fmt = dict(rate=16000,channels=1)
send(b'F',fmt)
assert sys.stdin.buffer.read(1) == b'g'
send(b'R',dict(**fmt,name='模拟麦克风',mode='paragraph',version=2))
now = time.monotonic_ns() - 3_000_000_000
for n in range(32):
    write_packet(sys.stdout.buffer,b'A',AUDIO_HEADER.pack(n,now+n*32_000_000)+struct.pack('<f',0.1)*512)
send(b'D',dict(reason='overload',packets=32,frames=16384,peak_frames=8192,rejected_frames=512))
"""
        popen = subprocess.Popen
        events, errors = [], []
        finished = threading.Event()

        def end():
            events.append("finished")
            finished.set()

        def segment(window):
            if window.final:
                events.append(window)

        capture = CaptureProcess(
            "microphone",
            segment,
            errors.append,
            paragraph=True,
            segmenter_factory=lambda emit: RollingAudio(emit, first_seconds=0.8),
        )
        capture.on_interrupted = lambda report: events.append(report)
        capture.on_finished = end
        with patch(
            "yuepu_translate.capture_process.subprocess.Popen",
            lambda cmd, **kw: popen([sys.executable, "-X", "utf8", "-c", helper], **kw),
        ):
            capture.start()
            try:
                self.assertTrue(finished.wait(8))
            finally:
                capture.stop()
        self.assertEqual(errors, [])
        window, report, complete = events
        self.assertEqual(complete, "finished")
        self.assertEqual((window.end, report.frames, report.rejected_frames), (16384, 16384, 512))
        self.assertEqual(report.reason, "overload")
        self.assertGreater(time.monotonic() - window.captured_at, 1.8)
        self.assertGreater(report.max_delivery_lag_seconds, 1.8)
        self.assertFalse(capture.thread.is_alive())

    def test_binary_pcm_and_utf8_status_round_trip(self):
        stream = io.BytesIO()
        status = "默认耳机".encode()
        pcm = struct.pack("<fff", -0.1, 0.2, 0.3)
        write_packet(stream, b"R", status)
        write_packet(stream, b"A", pcm)
        stream.seek(0)
        self.assertEqual(read_packet(stream), (b"R", status))
        self.assertEqual(read_packet(stream), (b"A", pcm))
        with self.assertRaises(EOFError):
            read_packet(stream)

    def test_requested_stop_accepts_tail_packets_before_finished(self):
        helper = """
import json, struct, sys, time
from yuepu_translate.capture_process import AUDIO_HEADER, write_packet
fmt = dict(rate=16000, channels=1)
out, control = sys.stdout.buffer, sys.stdin.buffer
write_packet(out, b'F', json.dumps(fmt).encode())
assert control.read(1) == b'g'
write_packet(out, b'R', json.dumps(dict(**fmt,name='test',mode='paragraph',version=2)).encode())
packets = [AUDIO_HEADER.pack(i,time.monotonic_ns())+struct.pack('<f',0.1)*512 for i in (0,1)]
write_packet(out, b'A', packets[0])
assert control.read(1) == b's'
time.sleep(1.5)
write_packet(out, b'A', packets[1])
write_packet(out, b'D', b'{"reason":"stopped","packets":2,"frames":1024,"peak_frames":1024,"rejected_frames":0}')
"""
        popen = subprocess.Popen
        errors, segments = [], []
        ready, finished = threading.Event(), threading.Event()
        capture = CaptureProcess(
            "microphone",
            segments.append,
            errors.append,
            started=lambda name: ready.set(),
            paragraph=True,
            segmenter_factory=RollingAudio,
        )
        capture.on_interrupted = errors.append
        capture.on_finished = finished.set
        with patch(
            "yuepu_translate.capture_process.subprocess.Popen",
            lambda cmd, **kw: popen([sys.executable, "-c", helper], **kw),
        ):
            capture.start()
            try:
                self.assertTrue(ready.wait(8))
                capture.request_stop()
                self.assertTrue(finished.wait(5))
            finally:
                capture.stop()
        self.assertFalse(errors)
        self.assertEqual([w.end for w in segments if w.final], [1024])
        self.assertEqual((capture.report.reason, capture.report.frames), ("stopped", 1024))

    def run_ready_helper(self, body, interact=None):
        helper = """
import json, sys, time
from yuepu_translate.capture_process import AUDIO_HEADER, write_packet
out, control = sys.stdout.buffer, sys.stdin.buffer
fmt = dict(rate=16000, channels=1)
write_packet(out, b'F', json.dumps(fmt).encode())
assert control.read(1) == b'g'
write_packet(out, b'R', json.dumps(dict(**fmt, name='test', mode='paragraph', version=2)).encode())
def silence(n):
    write_packet(out, b'A', AUDIO_HEADER.pack(n, time.monotonic_ns()) + bytes(512 * 4))
def finish(reason, count, rejected=0):
    summary = dict(reason=reason, packets=count, frames=count*512,
                   peak_frames=count*512, rejected_frames=rejected)
    write_packet(out, b'D', json.dumps(summary).encode())
"""
        popen = subprocess.Popen
        errors, interrupted, waiting = [], [], []
        ready, finished = threading.Event(), threading.Event()
        capture = CaptureProcess(
            "microphone",
            lambda window: None,
            errors.append,
            started=lambda name: ready.set(),
            paragraph=True,
            segmenter_factory=RollingAudio,
        )
        capture.on_interrupted = interrupted.append
        capture.on_waiting = waiting.append
        capture.on_finished = finished.set
        with patch(
            "yuepu_translate.capture_process.subprocess.Popen",
            lambda cmd, **kw: popen([sys.executable, "-c", helper + body], **kw),
        ):
            capture.start()
            try:
                self.assertTrue(ready.wait(8))
                if interact is not None:
                    interact(capture)
                self.assertTrue(finished.wait(8))
            finally:
                capture.stop()
        self.assertFalse(errors)
        return capture.report, waiting, interrupted

    def test_waiting_before_first_pcm_and_on_stall_recovers_with_silent_pcm(self):
        body = """
time.sleep(0.65)
for i in range(12):
    silence(i)
    time.sleep(0.05)
time.sleep(0.65)
silence(12)
finish("stopped", 13)
"""
        with patch("yuepu_translate.capture_process.NO_PCM_WARNING_SECONDS", 0.3):
            report, waiting, interrupted = self.run_ready_helper(body)
        self.assertEqual(waiting, [True, False, True, False])
        self.assertFalse(interrupted)
        self.assertEqual((report.reason, report.packets), ("stopped", 13))

    def test_normal_stop_reports_missing_end_summary_at_drain_bound(self):
        body = "silence(0)\nassert control.read(1) == b's'\ntime.sleep(10)"
        with patch("yuepu_translate.capture_process.MAX_DRAIN_SECONDS", 0.3):
            report, _, interrupted = self.run_ready_helper(body, lambda c: c.request_stop())
        self.assertEqual((report.reason, report.frames), ("drain_timeout", 512))
        self.assertEqual(interrupted, [report])

    def test_cancel_during_graceful_drain_is_prompt_and_does_not_invent_loss(self):
        def cancel(capture):
            capture.request_stop()
            time.sleep(0.1)
            start = time.monotonic()
            capture.stop()
            self.assertLess(time.monotonic() - start, 3.5)

        body = "silence(0)\nassert control.read(1) == b's'\ntime.sleep(20)"
        report, _, interrupted = self.run_ready_helper(body, cancel)
        self.assertEqual((report.reason, report.frames), ("cancelled", 512))
        self.assertFalse(interrupted)

    def test_cancel_keeps_explicit_overload_summary_received_while_draining(self):
        body = """silence(0)
assert control.read(1) == b's'
finish("overload", 1, 512)
"""
        report, _, interrupted = self.run_ready_helper(body, lambda c: c.stop())
        self.assertEqual((report.reason, report.rejected_frames), ("overload", 512))
        self.assertEqual(interrupted, [report])

    def test_partial_pipe_reads_are_reassembled(self):
        class Partial(io.BytesIO):
            def read(self, count):
                return super().read(min(count, 2))

        stream = Partial(struct.pack("<cI", b"E", 5) + b"error")
        self.assertEqual(read_packet(stream), (b"E", b"error"))

    def test_oversized_or_unknown_packet_rejected_before_body_allocation(self):
        for header in (struct.pack("<cI", b"A", MAX_PACKET + 1), struct.pack("<cI", b"X", 0)):
            with self.assertRaises(ValueError):
                read_packet(io.BytesIO(header))

    def test_truncated_body_and_invalid_write_rejected(self):
        with self.assertRaises(EOFError):
            read_packet(io.BytesIO(struct.pack("<cI", b"A", 10) + b"short"))
        with self.assertRaises(ValueError):
            write_packet(io.BytesIO(), b"X", b"")

    def test_blocked_native_startup_is_bounded_and_owned_child_is_reaped(self):
        real_popen = subprocess.Popen
        failed = threading.Event()

        def blocked_device(command, **kwargs):
            return real_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)

        capture = CaptureProcess("system", lambda pcm: None, lambda error: failed.set())
        with (
            patch("yuepu_translate.capture_process.subprocess.Popen", blocked_device),
            patch("yuepu_translate.capture_process.STARTUP_TIMEOUT_SECONDS", 0.1),
        ):
            try:
                capture.start()
                self.assertTrue(failed.wait(3), "A blocked device must report startup failure")
            finally:
                capture.stop()
        self.assertFalse(capture.thread.is_alive())
        self.assertIsNotNone(capture.child or capture.keepalive)
        self.assertTrue(
            all(
                child.poll() is not None
                for child in (capture.child, capture.keepalive)
                if child is not None
            )
        )

    def test_cancel_can_end_a_helper_that_ignores_cooperative_stop(self):
        real_popen = subprocess.Popen
        spawned = threading.Event()
        errors = []

        def blocked_device(command, **kwargs):
            child = real_popen([sys.executable, "-c", "import time; time.sleep(60)"], **kwargs)
            spawned.set()
            return child

        capture = CaptureProcess("system", lambda pcm: None, errors.append)
        finished = []
        capture.on_finished = lambda: finished.append(True)
        with (
            patch("yuepu_translate.capture_process.subprocess.Popen", blocked_device),
            patch("yuepu_translate.capture_process.STOP_TIMEOUT_SECONDS", 0.1),
        ):
            try:
                capture.start()
                self.assertTrue(spawned.wait(3))
            finally:
                capture.stop()
        self.assertFalse(capture.thread.is_alive())
        self.assertIsNotNone(capture.child or capture.keepalive)
        self.assertTrue(
            all(
                child.poll() is not None
                for child in (capture.child, capture.keepalive)
                if child is not None
            )
        )
        self.assertEqual(errors, [])
        self.assertEqual(finished, [True])


if __name__ == "__main__":
    unittest.main()
