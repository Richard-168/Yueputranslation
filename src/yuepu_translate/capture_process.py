"""Killable audio-device boundary. PCM travels through anonymous local pipes."""

import json
import os
import queue
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

MAX_PACKET = 1024 * 1024
STARTUP_TIMEOUT_SECONDS = 12
STOP_TIMEOUT_SECONDS = 1


def write_packet(stream, kind, payload):
    if kind not in {b"R", b"A", b"E"} or len(payload) > MAX_PACKET:
        raise ValueError("Invalid capture packet")
    stream.write(struct.pack("<cI", kind, len(payload)) + payload)
    stream.flush()


def read_exact(stream, count):
    pieces = []
    remaining = count
    while remaining:
        part = stream.read(remaining)
        if not part:
            raise EOFError("Capture pipe closed")
        pieces.append(part)
        remaining -= len(part)
    return b"".join(pieces)


def read_packet(stream):
    kind, size = struct.unpack("<cI", read_exact(stream, 5))
    if kind not in {b"R", b"A", b"E"} or size > MAX_PACKET:
        raise ValueError("Invalid capture packet")
    return kind, read_exact(stream, size)


class CaptureProcess:
    """The owned helper can be terminated even when a native driver blocks."""

    def __init__(
        self,
        source,
        segment,
        error,
        started=None,
        paragraph=False,
        segmenter_factory=None,
    ):
        self.source, self.segment, self.error = source, segment, error
        self.started, self.paragraph = started, paragraph
        self.segmenter_factory = segmenter_factory
        self.stop_event = threading.Event()
        self.thread = self.child = None
        self.keepalive = None

    def start(self):
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        import numpy as np

        messages = queue.Queue(maxsize=8)
        reader = None
        keepalive_reader = None
        processor = None
        channels = 0
        try:
            environment = os.environ.copy()
            # Also supports the existing source bootstrap without installing
            # the package into its older virtual environment.
            environment["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
            # Audio helpers do no large matrix inference. Avoid initializing
            # large BLAS/OpenMP pools merely to import their PCM dependencies.
            environment["OPENBLAS_NUM_THREADS"] = "1"
            environment["OMP_NUM_THREADS"] = "1"
            environment["MKL_NUM_THREADS"] = "1"
            startup_limit = time.monotonic() + STARTUP_TIMEOUT_SECONDS
            if self.source == "system":
                self.keepalive = subprocess.Popen(
                    [sys.executable, "-m", "yuepu_translate.capture_worker", "keepalive", "speech"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=environment,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                awakened = threading.Event()
                result = []

                def wake():
                    try:
                        result.append(read_packet(self.keepalive.stdout))
                    except (EOFError, OSError, ValueError):
                        pass
                    finally:
                        awakened.set()

                keepalive_reader = threading.Thread(target=wake, daemon=True)
                keepalive_reader.start()
                while not awakened.wait(0.05):
                    if self.stop_event.is_set():
                        return
                    if time.monotonic() >= startup_limit:
                        raise TimeoutError(
                            "默认输出设备启动超时，已结束本次采集。请检查音频设备后重试。"
                        )
                if not result or result[0][0] != b"R":
                    raise RuntimeError("无法启动默认输出设备，请检查设备后重试。")
                if self.stop_event.is_set():
                    return
            self.child = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "yuepu_translate.capture_worker",
                    self.source,
                    "paragraph" if self.paragraph else "speech",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            def receive():
                try:
                    while True:
                        packet = read_packet(self.child.stdout)
                        while not self.stop_event.is_set():
                            try:
                                messages.put(packet, timeout=0.05)
                                break
                            except queue.Full:
                                continue
                        else:
                            # Continue draining during cooperative Stop.
                            try:
                                messages.put(packet, timeout=0.1)
                            except queue.Full:
                                return
                except (EOFError, OSError, ValueError):
                    pass

            reader = threading.Thread(target=receive, daemon=True)
            reader.start()
            ready = False
            deadline = startup_limit
            stop_deadline = None
            while True:
                if self.stop_event.is_set() and stop_deadline is None:
                    # Keep the silent playback client alive until loopback
                    # has flushed and closed its device stream.
                    for child in (self.child,):
                        if child is not None:
                            try:
                                child.stdin.write(b"s")
                                child.stdin.flush()
                            except (OSError, ValueError):
                                pass
                    stop_deadline = time.monotonic() + STOP_TIMEOUT_SECONDS
                if stop_deadline is not None and time.monotonic() >= stop_deadline:
                    break
                if not ready and not self.stop_event.is_set() and time.monotonic() >= deadline:
                    raise TimeoutError(
                        "输入设备启动超时，已结束本次采集。请检查默认音频设备后重试。"
                    )
                try:
                    kind, payload = messages.get(timeout=0.05)
                except queue.Empty:
                    if self.child.poll() is not None and not reader.is_alive():
                        if not self.stop_event.is_set():
                            raise RuntimeError("输入设备进程已退出，请检查音频设备后重试。")
                        break
                    continue
                if kind == b"R":
                    from .desktop_engine import PlaybackProcessor
                    from .song_pipeline import make_song_stream

                    metadata = json.loads(payload)
                    rate, channels = int(metadata["rate"]), int(metadata["channels"])
                    if not 8000 <= rate <= 192000 or not 1 <= channels <= 32:
                        raise ValueError("Invalid input format")
                    if metadata["mode"] != ("paragraph" if self.paragraph else "speech"):
                        raise ValueError("Invalid capture mode")
                    processor = PlaybackProcessor(
                        rate,
                        channels,
                        self.segment,
                        segmenter_factory=self.segmenter_factory
                        or (make_song_stream if self.paragraph else None),
                    )
                    ready = True
                    if self.started:
                        self.started(metadata["name"])
                elif kind == b"E":
                    raise RuntimeError(payload.decode("utf-8"))
                elif kind == b"A":
                    if processor is None or len(payload) % (channels * 4):
                        raise ValueError("Invalid PCM packet")
                    processor.feed(np.frombuffer(payload, dtype="<f4").reshape(-1, channels))
        except (RuntimeError, TimeoutError) as exc:
            if not self.stop_event.is_set():
                self.error(str(exc))
        except Exception:
            if not self.stop_event.is_set():
                self.error("无法启动音频采集，请检查默认设备及权限后重试。")
        finally:
            self.stop_event.set()
            if processor is not None:
                try:
                    processor.flush()
                except (RuntimeError, ValueError) as exc:
                    self.error(str(exc))
            children = [child for child in (self.child, self.keepalive) if child is not None]
            for child in children:
                if child.poll() is None:
                    child.terminate()
            for child in children:
                if child.poll() is None:
                    try:
                        child.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=1)
            for thread in (reader, keepalive_reader):
                if thread is not None:
                    thread.join(1)
            for child in children:
                child.stdin.close()
                child.stdout.close()

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=4)
