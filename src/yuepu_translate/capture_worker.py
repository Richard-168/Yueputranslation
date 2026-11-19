"""Native capture callbacks copy PCM into a bounded queue for the pipe writer."""

import argparse
import json
import sys
import threading
import time
from collections import deque

from .capture_process import AUDIO_HEADER, write_packet

MAX_BUFFER_SECONDS = 4
MAX_BUFFER_BYTES = 4 * 1024 * 1024
MAX_BUFFER_PACKETS = 512


class CaptureBuffer:
    """Seal the prefix at the first loss; send all admitted PCM before its end marker."""

    def __init__(self, rate, channels):
        self.frame_bytes = 4 * channels
        self.limit = min(MAX_BUFFER_SECONDS * rate, MAX_BUFFER_BYTES // self.frame_bytes)
        self.condition = threading.Condition()
        self.pending = deque()
        self.queued_frames = self.peak_frames = 0
        self.frames = self.packets = self.rejected_frames = 0
        self.reason = None

    def push(self, data, status):
        stamp = time.monotonic_ns()
        frames, remainder = divmod(len(data), self.frame_bytes)
        with self.condition:
            if self.reason is not None:
                return False
            if status or remainder or not frames:
                self.reason = "device"
            elif (
                self.queued_frames + frames > self.limit or len(self.pending) >= MAX_BUFFER_PACKETS
            ):
                self.reason = "overload"
                self.rejected_frames = frames
            else:
                self.pending.append((self.packets, stamp, bytes(data)))
                self.packets += 1
                self.frames += frames
                self.queued_frames += frames
                self.peak_frames = max(self.peak_frames, self.queued_frames)
            self.condition.notify()
            return self.reason is None

    def close(self, reason="stopped"):
        with self.condition:
            if self.reason is None:
                self.reason = reason
            self.condition.notify()

    def drain(self, stream, active):
        while True:
            with self.condition:
                if not self.pending and self.reason is None:
                    self.condition.wait(0.05)
                if self.pending:
                    sequence, stamp, data = self.pending.popleft()
                    self.queued_frames -= len(data) // self.frame_bytes
                elif self.reason is not None:
                    break
                else:
                    data = None
            if data is None:
                try:
                    running = active()
                except (OSError, RuntimeError):
                    running = False
                if not running:
                    self.close("device")
                continue
            write_packet(stream, b"A", AUDIO_HEADER.pack(sequence, stamp) + data)
        summary = dict(
            reason=self.reason,
            packets=self.packets,
            frames=self.frames,
            peak_frames=self.peak_frames,
            rejected_frames=self.rejected_frames,
        )
        write_packet(stream, b"D", json.dumps(summary).encode("ascii"))


def main():
    parser = argparse.ArgumentParser(description="Internal local audio capture helper")
    parser.add_argument("source", choices=["microphone", "system", "keepalive"])
    parser.add_argument("mode", choices=["speech", "paragraph"])
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    output = sys.stdout.buffer
    done = threading.Event()
    awake = threading.Event()
    armed = threading.Event()
    buffers = None

    def send(kind, payload):
        write_packet(output, kind, payload)

    def ready(name, rate, channels):
        send(
            b"R",
            json.dumps(
                dict(name=name, rate=rate, channels=channels, mode=args.mode, version=2)
            ).encode("utf-8"),
        )

    def control():
        if sys.stdin.buffer.read(1) == b"g":
            armed.set()
            sys.stdin.buffer.read(1)
        done.set()
        armed.set()
        if buffers is not None:
            buffers.close()

    def prepare(rate, channels):
        nonlocal buffers
        buffers = CaptureBuffer(rate, channels)
        if args.prepare:
            send(b"F", json.dumps(dict(rate=rate, channels=channels)).encode("ascii"))
            armed.wait()
        return not done.is_set()

    threading.Thread(target=control, daemon=True).start()
    try:
        if args.source == "keepalive":
            import sounddevice as sd

            device = sd.query_devices(kind="output")
            rate, channels = (
                int(device["default_samplerate"]),
                min(2, int(device["max_output_channels"])),
            )

            def silence(data, frames, timing, status):
                data[:] = bytes(len(data))
                awake.set()

            with sd.RawOutputStream(
                samplerate=rate, channels=channels, dtype="float32", callback=silence
            ):
                if not awake.wait(3):
                    send(b"E", "无法唤醒默认输出设备，请检查设备后重试。".encode("utf-8"))
                else:
                    ready(str(device["name"]), rate, channels)
                    done.wait()
        elif args.source == "microphone":
            import sounddevice as sd

            if not prepare(16000, 1):
                return

            def microphone(data, frames, timing, status):
                buffers.push(data, status)

            with sd.RawInputStream(
                samplerate=16000, channels=1, blocksize=512, dtype="float32", callback=microphone
            ) as stream:
                ready("默认麦克风", 16000, 1)
                buffers.drain(output, lambda: stream.active)
        else:
            import pyaudiowpatch as pa

            with pa.PyAudio() as manager:
                device = manager.get_default_wasapi_loopback()
                rate, channels = int(device["defaultSampleRate"]), int(device["maxInputChannels"])
                if not device.get("isLoopbackDevice") or not 1 <= channels <= 32:
                    raise RuntimeError("Invalid loopback device")
                if not prepare(rate, channels):
                    return

                def system(data, frames, timing, status):
                    return None, pa.paContinue if buffers.push(data, status) else pa.paComplete

                with manager.open(
                    format=pa.paFloat32,
                    channels=channels,
                    rate=rate,
                    input=True,
                    input_device_index=int(device["index"]),
                    frames_per_buffer=1024,
                    stream_callback=system,
                ) as stream:
                    ready(str(device["name"]), rate, channels)
                    buffers.drain(output, stream.is_active)
    except (OSError, RuntimeError, ValueError):
        if not done.is_set():
            send(b"E", "无法启用输入设备，请检查默认设备及权限后重试。".encode("utf-8"))


if __name__ == "__main__":
    main()
