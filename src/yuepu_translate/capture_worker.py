"""Minimal native audio helper. Only raw PCM goes through anonymous pipes."""

import argparse
import json
import queue
import sys
import threading

from .capture_process import write_packet


def main():
    parser = argparse.ArgumentParser(description="Internal local audio capture helper")
    parser.add_argument("source", choices=["microphone", "system", "keepalive"])
    parser.add_argument("mode", choices=["speech", "paragraph"])
    args = parser.parse_args()
    output = sys.stdout.buffer
    done = threading.Event()
    awake = threading.Event()
    buffers = queue.Queue(maxsize=64)
    errors = []

    def send(kind, payload):
        write_packet(output, kind, payload)

    def ready(name, rate, channels):
        send(
            b"R",
            json.dumps(dict(name=name, rate=rate, channels=channels, mode=args.mode)).encode(
                "utf-8"
            ),
        )

    def control():
        sys.stdin.buffer.read(1)
        done.set()

    def push(data, status):
        if status:
            errors.append("输入设备缓冲异常，请暂停来源后重试。")
            done.set()
        if done.is_set():
            return
        try:
            buffers.put_nowait(bytes(data))
        except queue.Full:
            errors.append("输入处理跟不上，已停止收音。请暂停来源后重试。")
            done.set()

    def drain(stream):
        while not done.is_set() or not buffers.empty():
            if errors:
                send(b"E", errors[0].encode("utf-8"))
                break
            try:
                data = buffers.get(timeout=0.05)
            except queue.Empty:
                active = stream.is_active() if args.source == "system" else stream.active
                if not active and not done.is_set():
                    send(b"E", "输入设备已停止，请检查默认设备后重试。".encode("utf-8"))
                    break
                continue
            send(b"A", data)

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

            def microphone(data, frames, timing, status):
                push(data, status)

            with sd.RawInputStream(
                samplerate=16000, channels=1, blocksize=512, dtype="float32", callback=microphone
            ) as stream:
                ready("默认麦克风", 16000, 1)
                drain(stream)
        else:
            import pyaudiowpatch as pa

            with pa.PyAudio() as manager:
                device = manager.get_default_wasapi_loopback()
                rate, channels = int(device["defaultSampleRate"]), int(device["maxInputChannels"])
                if not device.get("isLoopbackDevice") or not 1 <= channels <= 32:
                    raise RuntimeError("Invalid loopback device")

                def system(data, frames, timing, status):
                    if done.is_set():
                        return None, pa.paComplete
                    push(data, status)
                    return None, pa.paAbort if done.is_set() else pa.paContinue

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
                    drain(stream)
    except (OSError, RuntimeError, ValueError):
        if not done.is_set():
            send(b"E", "无法启用输入设备，请检查默认设备及权限后重试。".encode("utf-8"))


if __name__ == "__main__":
    main()
