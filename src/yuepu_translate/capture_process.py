"""Killable audio-device boundary. PCM travels through anonymous local pipes."""

import json
import os
import queue
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

MAX_PACKET = 1024 * 1024
STARTUP_TIMEOUT_SECONDS = 12
NO_PCM_WARNING_SECONDS = 3
STOP_TIMEOUT_SECONDS = 1
MAX_DRAIN_SECONDS = 12
AUDIO_HEADER = struct.Struct("<QQ")  # callback sequence, monotonic callback time in ns
PACKET_KINDS = {b"F", b"R", b"A", b"D", b"E"}


@dataclass(frozen=True)
class CaptureReport:
    reason: str
    rate: int
    packets: int
    frames: int
    rejected_frames: int
    peak_buffer_frames: int
    max_delivery_lag_seconds: float
    peak_receiver_packets: int
    muted_frames: int = 0

    @property
    def message(self):
        boundary = self.frames / self.rate
        if self.reason == "overload":
            return (
                f"输入积压，已停止收音。已收到前 {boundary:.3f} 秒的音频，"
                f"从此处起缺音，首个未收入的音频包为 {self.rejected_frames / self.rate:.3f} 秒。"
            )
        if self.reason == "processing":
            return f"已收到前 {boundary:.3f} 秒的音频，末尾分段未能完成。"
        if self.reason == "drain_timeout":
            return f"等待采集端结束超时，已收到前 {boundary:.3f} 秒的音频，之后的尾音无法确认。"
        return f"采集发生中断。已收到前 {boundary:.3f} 秒的音频，之后的缺音时长未知。"


def mute_playback_overlap(samples, rate, packet_end, playback_intervals):
    """Silence only the part of this timestamped microphone packet played by our speaker."""
    start = packet_end - len(samples) / rate
    muted = right = 0
    for begin, finish in playback_intervals(start, packet_end):
        left = max(right, round((begin - start) * rate), 0)
        right = max(left, min(len(samples), round((finish - start) * rate)))
        if right > left:
            if not muted:
                samples = samples.copy()
            samples[left:right] = 0
            muted += right - left
    return samples, muted


def write_packet(stream, kind, payload):
    if kind not in PACKET_KINDS or len(payload) > MAX_PACKET:
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
    if kind not in PACKET_KINDS or size > MAX_PACKET:
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
        self.cancel_drain = threading.Event()
        self.thread = self.child = None
        self.keepalive = None
        self.on_waiting = None
        self.on_interrupted = None
        self.on_finished = None
        self.playback_intervals = None
        self.report = None

    def start(self):
        self.stop_event.clear()
        self.cancel_drain.clear()
        self.report = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self._capture()
        finally:
            try:
                if self.report is not None and self.report.reason not in ("stopped", "cancelled"):
                    if self.on_interrupted is not None:
                        self.on_interrupted(self.report)
                    else:
                        self.error(self.report.message)
            finally:
                if self.on_finished is not None:
                    self.on_finished()

    def _capture(self):
        import numpy as np

        from .song_stream import RATE, RollingAudio

        messages = queue.Queue(maxsize=8)
        closing = threading.Event()
        reader_done = threading.Event()
        reader = None
        keepalive_reader = None
        processor = None
        rate = channels = version = 0
        packets = frames = peak_receiver_packets = muted_frames = 0
        max_delivery_lag = 0.0
        packet_end_time = 0.0
        packet_end_frame = 0

        def emit_segment(window):
            if packet_end_time and hasattr(window, "captured_at"):
                # Resampling/VAD may emit a window ending before the current packet.
                seconds_behind = max(0.0, packet_end_frame / rate - window.end / 16000)
                captured_at = packet_end_time - seconds_behind
                window = replace(
                    window,
                    captured_at=captured_at,
                    confirm_at=captured_at + (window.confirm_at - window.captured_at),
                )
            self.segment(window)

        def prepare(metadata):
            from .desktop_engine import PlaybackProcessor
            from .song_pipeline import make_song_stream

            rate, channels = int(metadata["rate"]), int(metadata["channels"])
            if not 8000 <= rate <= 192000 or not 1 <= channels <= 32:
                raise ValueError("Invalid input format")
            return (
                rate,
                channels,
                PlaybackProcessor(
                    rate,
                    channels,
                    emit_segment,
                    segmenter_factory=self.segmenter_factory
                    or (make_song_stream if self.paragraph else None),
                ),
            )

        def report(reason, rejected_frames=0, peak_frames=0):
            return CaptureReport(
                reason,
                rate,
                packets,
                frames,
                rejected_frames,
                peak_frames,
                max_delivery_lag,
                peak_receiver_packets,
                muted_frames,
            )

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
                    "--prepare",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            def receive():
                nonlocal peak_receiver_packets
                try:
                    while True:
                        packet = read_packet(self.child.stdout)
                        while not closing.is_set():
                            try:
                                messages.put(packet, timeout=0.05)
                                peak_receiver_packets = max(peak_receiver_packets, messages.qsize())
                                break
                            except queue.Full:
                                continue
                        else:
                            return
                except (EOFError, OSError, ValueError):
                    pass
                finally:
                    reader_done.set()

            reader = threading.Thread(target=receive, daemon=True)
            reader.start()
            ready = False
            deadline = startup_limit
            last_pcm_time = None
            waiting_for_pcm = False
            stop_started = None
            while True:
                if self.stop_event.is_set() and stop_started is None:
                    stop_started = time.monotonic()
                    # Keep the silent playback client alive until loopback
                    # has flushed and closed its device stream.
                    try:
                        self.child.stdin.write(b"s")
                        self.child.stdin.flush()
                    except (OSError, ValueError):
                        pass
                if stop_started is not None:
                    # Only the final D packet certifies the complete accepted prefix.
                    # A temporarily empty pipe can still have tail audio in the helper.
                    cancelled = self.cancel_drain.is_set()
                    limit = STOP_TIMEOUT_SECONDS if cancelled else MAX_DRAIN_SECONDS
                    if time.monotonic() - stop_started >= limit:
                        if ready and version == 2:
                            self.report = report("cancelled" if cancelled else "drain_timeout")
                        break
                if not ready and not self.stop_event.is_set() and time.monotonic() >= deadline:
                    raise TimeoutError(
                        "输入设备启动超时，已结束本次采集。请检查默认音频设备后重试。"
                    )
                try:
                    kind, payload = messages.get(timeout=0.05)
                except queue.Empty:
                    if reader_done.is_set() and messages.empty():
                        if ready and version == 2:
                            self.report = report(
                                "cancelled" if self.cancel_drain.is_set() else "transport"
                            )
                        elif not self.stop_event.is_set():
                            raise RuntimeError("输入设备进程已退出，请检查音频设备后重试。")
                        break
                    if (
                        last_pcm_time is not None
                        and not self.stop_event.is_set()
                        and not waiting_for_pcm
                        and time.monotonic() - last_pcm_time >= NO_PCM_WARNING_SECONDS
                    ):
                        waiting_for_pcm = True
                        if self.on_waiting:
                            self.on_waiting(True)
                    continue
                if kind == b"F":
                    if processor is not None:
                        raise ValueError("Duplicate input format")
                    if not self.stop_event.is_set():
                        rate, channels, processor = prepare(json.loads(payload))
                        if not self.stop_event.is_set():
                            self.child.stdin.write(b"g")
                            self.child.stdin.flush()
                            deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
                elif kind == b"R":
                    metadata = json.loads(payload)
                    if processor is None:
                        rate, channels, processor = prepare(metadata)
                    if (rate, channels) != (metadata["rate"], metadata["channels"]) or ready:
                        raise ValueError("Unexpected input format")
                    version = metadata.get("version", 0)
                    if version not in (0, 2):
                        raise ValueError("Unknown capture protocol")
                    if metadata["mode"] != ("paragraph" if self.paragraph else "speech"):
                        raise ValueError("Invalid capture mode")
                    ready = True
                    last_pcm_time = time.monotonic()
                    if self.started:
                        self.started(metadata["name"])
                elif kind == b"E":
                    raise RuntimeError(payload.decode("utf-8"))
                elif kind == b"A":
                    if not ready:
                        raise ValueError("Audio before ready")
                    offset = AUDIO_HEADER.size if version == 2 else 0
                    size = len(payload) - offset
                    if size <= 0 or size % (channels * 4):
                        raise ValueError("Invalid PCM packet")
                    packet_end_frame = frames + size // (channels * 4)
                    if version == 2:
                        sequence, stamp = AUDIO_HEADER.unpack_from(payload)
                        if sequence != packets or stamp <= 0:
                            raise ValueError("Missing or invalid PCM packet")
                        packet_end_time = stamp / 1_000_000_000
                        lag = max(0.0, time.monotonic() - packet_end_time)
                        max_delivery_lag = max(max_delivery_lag, lag)
                        if isinstance(processor.segmenter, RollingAudio):
                            # Skip stale previews before allocating their overlapping audio.
                            # VAD, checkpoints, and final windows still see every frame.
                            processor.segmenter.defer_drafts = (
                                lag * RATE >= processor.segmenter.update_samples
                            )
                    samples = np.frombuffer(payload, dtype="<f4", offset=offset).reshape(
                        -1, channels
                    )
                    if self.source == "microphone" and version == 2 and self.playback_intervals:
                        samples, muted = mute_playback_overlap(
                            samples, rate, packet_end_time, self.playback_intervals
                        )
                        muted_frames += muted
                    processor.feed(samples)
                    frames = packet_end_frame
                    packets += 1
                    # Any valid packet, including device silence, proves delivery.
                    last_pcm_time = time.monotonic()
                    if waiting_for_pcm and not self.stop_event.is_set():
                        waiting_for_pcm = False
                        if self.on_waiting:
                            self.on_waiting(False)
                elif kind == b"D":
                    summary = json.loads(payload)
                    if (
                        not ready
                        or summary["reason"] not in ("stopped", "device", "overload")
                        or summary["frames"] != frames
                        or summary["packets"] != packets
                        or not 0 <= summary["peak_frames"] <= frames
                        or summary["rejected_frames"] < 0
                    ):
                        raise ValueError("Incomplete capture")
                    self.report = report(
                        summary["reason"], summary["rejected_frames"], summary["peak_frames"]
                    )
                    break
        except Exception as exc:
            if version == 2:
                self.report = report("transport")
            elif not self.stop_event.is_set():
                self.error(
                    str(exc)
                    if isinstance(exc, (RuntimeError, TimeoutError))
                    else "无法启动音频采集，请检查默认设备及权限后重试。"
                )
        finally:
            closing.set()
            self.stop_event.set()
            if processor is not None:
                try:
                    processor.flush()
                except Exception as exc:
                    if packets and self.on_interrupted is not None:
                        self.report = report("processing")
                    else:
                        self.error(str(exc))
            children = [child for child in (self.child, self.keepalive) if child is not None]
            for child in children:
                try:
                    child.stdin.close()
                except OSError:
                    pass
            for child in children:
                if child.poll() is None:
                    try:
                        child.wait(timeout=0.25)
                    except subprocess.TimeoutExpired:
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
                child.stdout.close()

    def request_stop(self):
        self.stop_event.set()

    def stop(self):
        self.cancel_drain.set()
        self.request_stop()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=4)
