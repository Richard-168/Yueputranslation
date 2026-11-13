"""No-device PCM checks; owned synthetic helpers verify bounded recovery."""

import io
import struct
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from yuepu_translate.capture_process import MAX_PACKET, CaptureProcess, read_packet, write_packet


class CaptureProtocolTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
