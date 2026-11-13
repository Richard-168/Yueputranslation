"""Real model/window validation. Does not activate audio input or output devices."""

from __future__ import annotations

import argparse
import ctypes
import json
import threading
import time
from pathlib import Path

import numpy as np
import psutil
import soundfile as sf
from desktop_engine import (
    ASR_LANGUAGES,
    UNSUPPORTED_SCRIPT,
    AudioPlayer,
    Cancelled,
    Engine,
    PlaybackProcessor,
    Request,
    make_vad,
)
from PIL import ImageGrab

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "outputs/desktop-smoke"


def engine_check():
    OUTPUT.mkdir(exist_ok=True)
    engine = Engine()
    cancel = threading.Event()
    errors = []
    player = AudioPlayer(errors.append, muted=True)
    load_start = time.perf_counter()
    engine.load(cancel, lambda text: print(text, flush=True))
    preparation_seconds = time.perf_counter() - load_start
    records = []
    for language in ("yue", "zh"):
        player.chunks.clear()
        events = []
        request = Request(
            1, "file", source=language, path=str(ROOT / f"models/asr/test_wavs/{language}.wav")
        )
        job_start = time.perf_counter()
        engine.process(request, cancel, player, lambda key, value: events.append((key, value)))
        generation_seconds = time.perf_counter() - job_start
        translated = next(value for key, value in events if key == "translation")
        assert translated["text"].strip() and player.chunks
        assert any(key == "first_audio" for key, _ in events)
        formats = {(rate, chunk.shape[1]) for chunk, rate in player.chunks}
        assert len(formats) == 1
        merged = np.concatenate([chunk for chunk, _ in player.chunks], axis=0)
        assert np.isfinite(merged).all() and float(np.max(np.abs(merged))) > 0.0001
        rate = player.chunks[0][1]
        path = OUTPUT / f"desktop-{language}.wav"
        sf.write(str(path), merged, rate, subtype="PCM_16")
        row = dict(
            source=language,
            translation=translated,
            chunks=len(player.chunks),
            audio_seconds=len(merged) / rate,
            first_pcm_seconds=next(value for key, value in events if key == "first_audio"),
            generation_seconds=generation_seconds,
            file=path.name,
        )
        records.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    rejected = False
    try:
        engine.process(Request(2, "text", text=""), cancel, player, lambda *args: None)
    except ValueError:
        rejected = True
    assert rejected
    timer = threading.Timer(0.25, cancel.set)
    tick = time.perf_counter()
    timer.start()
    try:
        engine.translate("他今天没空，明天下午三点才来。", "zh", cancel)
        raise AssertionError("Cancellation did not stop the native translation process")
    except Cancelled:
        cancellation_seconds = time.perf_counter() - tick
    finally:
        timer.cancel()
    assert cancellation_seconds < 3
    owned = [
        p
        for p in psutil.Process().children(recursive=True)
        if "llama-completion" in p.name().lower()
    ]
    assert not owned
    vad = make_vad()
    samples, rate = sf.read(str(ROOT / "models/asr/test_wavs/yue.wav"), dtype="float32")
    assert rate == 16000
    padded = np.concatenate([samples, np.zeros(16000, dtype=np.float32)])
    segments = []
    for start in range(0, len(padded), 512):
        chunk = padded[start : start + 512]
        if len(chunk) < 512:
            chunk = np.pad(chunk, (0, 512 - len(chunk)))
        vad.accept_waveform(chunk)
        while not vad.empty():
            segments.append(len(vad.front.samples) / 16000)
            vad.pop()
    assert segments and all(0.25 <= x <= 5 for x in segments), segments
    language_checks = []
    for source in ("zh", "yue"):
        events = []
        engine.process(
            Request(
                3,
                "file",
                source=source,
                path=str(ROOT / "models/asr/test_wavs/en.wav"),
                autoplay=False,
            ),
            threading.Event(),
            player,
            lambda key, value: events.append((key, value)),
        )
        recognition = next(v for k, v in events if k == "recognition")
        original = next(v for k, v in events if k == "source")
        assert recognition["language"] == "en" and "tribal chieftain" in original
        assert any(k == "translation" and v["text"].strip() for k, v in events)
        language_checks.append(
            dict(fixture="en", direction=source, recognition=recognition, source_text=original)
        )
        for fixture in ("ja", "ko"):
            events = []
            try:
                engine.process(
                    Request(
                        4,
                        "file",
                        source=source,
                        path=str(ROOT / f"models/asr/test_wavs/{fixture}.wav"),
                        autoplay=False,
                    ),
                    threading.Event(),
                    player,
                    lambda key, value: events.append((key, value)),
                )
                raise AssertionError(
                    f"Unsupported language reached translation: {fixture}/{source}"
                )
            except ValueError as exc:
                assert "普通话、粤语或英文" in str(exc)
            assert not any(k in {"source", "translation", "first_audio"} for k, v in events)
            language_checks.append(
                dict(fixture=fixture, direction=source, rejected_before_translation=True)
            )
    short_segments = []
    # Reproduce confusion from fixed real audio crops; no old output dependency.
    crops = [
        ("zh", 1, 0.3),
        ("zh", 1.5, 0.3),
        ("zh", 2, 0.3),
        ("zh", 2, 0.5),
        ("yue", 1.5, 0.3),
        ("yue", 1.5, 0.5),
        ("yue", 2, 0.3),
        ("yue", 2, 0.5),
    ]
    for source, start, duration in crops:
        samples, rate = sf.read(str(ROOT / f"models/asr/test_wavs/{source}.wav"), dtype="float32")
        samples = samples[int(start * rate) : int((start + duration) * rate)]
        stream = engine.asr.create_stream()
        stream.accept_waveform(rate, samples)
        engine.asr.decode_stream(stream)
        assert stream.result.lang == "<|ja|>"
        row = dict(
            source=source,
            start=start,
            duration=duration,
            text=stream.result.text,
            lang=stream.result.lang,
        )
        events = []
        try:
            text = engine.recognize(
                samples, rate, threading.Event(), source, lambda k, v: events.append((k, v))
            )
            recognition = next(v for k, v in events if k == "recognition")
            assert recognition["redirected"] and recognition["language"] in ASR_LANGUAGES
            assert not UNSUPPORTED_SCRIPT.search(text)
            result = dict(text=text, recognition=recognition)
        except ValueError as exc:
            result = dict(rejected=True, error=str(exc))
        short_segments.append(dict(fixture=row, result=result))
    report = dict(
        status="executed",
        scope="real desktop engine with file input and muted PCM sink; no microphone/speaker acceptance",
        preparation_seconds=preparation_seconds,
        records=records,
        empty_input_rejected=rejected,
        cancellation_seconds=cancellation_seconds,
        native_child_cleanup=True,
        vad_segments_seconds=segments,
        language_checks=language_checks,
        short_segment_checks=short_segments,
        errors=errors,
        quality_passed=False,
    )
    (OUTPUT / "engine-verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    player.close()
    print(json.dumps(report, ensure_ascii=False), flush=True)


def capture_window(root, name):
    root.update_idletasks()
    root.update()
    for _ in range(6):
        root.update()
        time.sleep(0.03)
    user32 = ctypes.windll.user32
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    hwnd = user32.GetAncestor(root.winfo_id(), 2)
    image = ImageGrab.grab(window=hwnd)
    path = OUTPUT / name
    image.save(path)
    return dict(file=name, width=image.width, height=image.height)


def playback_check():
    """Actual resampler/VAD/ASR/MT with fixture PCM; no system audio captured."""
    import probe
    import pyaudiowpatch as pa
    import soxr

    OUTPUT.mkdir(exist_ok=True)
    with pa.PyAudio() as manager:
        device = manager.get_default_wasapi_loopback()
        assert device["isLoopbackDevice"] and device["maxInputChannels"] > 0
        endpoint = dict(
            available=True,
            sample_rate=device["defaultSampleRate"],
            channels=device["maxInputChannels"],
        )
    engine = Engine()
    engine.asr = probe.recognizer()
    errors = []
    player = AudioPlayer(errors.append, muted=True)
    records = []
    try:
        for source in ("zh", "yue"):
            audio, rate = sf.read(str(ROOT / f"models/asr/test_wavs/{source}.wav"), dtype="float32")
            for device_rate in (44100, 48000):
                device_pcm = soxr.resample(audio, rate, device_rate).astype(np.float32)
                device_pcm = np.concatenate(
                    [
                        np.zeros(round(device_rate * 0.1), np.float32),
                        device_pcm,
                        np.zeros(round(device_rate * 1.5), np.float32),
                    ]
                )
                stereo = np.column_stack([device_pcm, device_pcm * 0.8])
                segments = []
                processor = PlaybackProcessor(device_rate, 2, segments.append)
                for start in range(0, len(stereo), 1024):
                    processor.feed(stereo[start : start + 1024])
                processor.flush()
                assert segments and len(processor.pending) < 512
                assert processor.input_frames == len(stereo)
                assert abs(processor.output_frames - round(len(stereo) * 16000 / device_rate)) <= 1
                assert processor.tail_padding_frames < 512
                finished_count = len(segments)
                processor.flush()
                assert len(segments) == finished_count
                # VAD retains edge context around its approximate 4s split.
                assert all(np.isfinite(s).all() and 0.25 <= len(s) / 16000 <= 5 for s in segments)
                translations = []
                for segment in segments:
                    events = []
                    engine.process(
                        Request(1, "audio", source=source, samples=segment, autoplay=False),
                        threading.Event(),
                        player,
                        lambda k, v: events.append((k, v)),
                    )
                    assert any(k == "source" and v.strip() for k, v in events)
                    translated = next(v for k, v in events if k == "translation")
                    assert translated["text"].strip()
                    assert not any(k == "first_audio" for k, v in events) and not player.chunks
                    translations.append(translated)
                records.append(
                    dict(
                        source=source,
                        device_rate=device_rate,
                        channels=2,
                        segments_seconds=[len(s) / 16000 for s in segments],
                        translations=translations,
                        generated_speech=False,
                        real_input_frames=processor.input_frames,
                        converted_frames=processor.output_frames,
                        tail_padding_frames=processor.tail_padding_frames,
                        repeated_idle_flush_does_not_duplicate=True,
                    )
                )
        # Actual pause/resume finalizes a tail once and starts fresh conversion;
        # a consumer timeout must not manufacture time-sized blocks of silence.
        pieces = []
        paused = PlaybackProcessor(16000, 1, pieces.append)
        source_audio, _ = sf.read(str(ROOT / "models/asr/test_wavs/yue.wav"), dtype="float32")
        split = len(source_audio) // 2
        paused.feed(source_audio[:split, None])
        paused.flush()
        first_count = len(pieces)
        paused.flush()
        assert len(pieces) == first_count
        paused.feed(source_audio[split:, None])
        paused.flush()
        assert paused.input_frames == len(source_audio) and paused.output_frames == len(
            source_audio
        )
        assert len(pieces) > first_count and paused.tail_padding_frames < 1024
        invalid = PlaybackProcessor(48000, 2, lambda samples: None)
        rejected = 0
        for data in (np.zeros((10, 1), np.float32), np.full((10, 2), np.nan, np.float32)):
            try:
                invalid.feed(data)
                raise AssertionError("Invalid device PCM accepted")
            except ValueError:
                rejected += 1
        report = dict(
            status="executed",
            endpoint_enumeration=endpoint,
            records=records,
            invalid_pcm_rejected=rejected,
            physical_capture="not activated",
            physical_playback="not activated",
            scope="real device-rate PCM conversion/VAD/audio job/ASR/MT using official fixtures; endpoint capture requires user test",
            pause_resume_real_frame_counts=True,
            errors=errors,
            quality_passed=False,
        )
        (OUTPUT / "playback-verification.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=True), flush=True)
    finally:
        player.close()


def ui_check():
    import tkinter as tk

    from desktop_tool import Window

    OUTPUT.mkdir(exist_ok=True)
    root = tk.Tk()
    root.withdraw()
    app = Window(root, muted=True)
    root.geometry("1140x760+40+40")
    root.update_idletasks()
    # Keep the verification window behind existing windows and avoid requesting
    # foreground activation. Capture only this process's own window handle.
    user32 = ctypes.windll.user32
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    hwnd = user32.GetAncestor(root.winfo_id(), 2)
    user32.GetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.SetWindowLongPtrW(hwnd, -20, user32.GetWindowLongPtrW(hwnd, -20) | 0x08000000)
    root.deiconify()
    user32.SetWindowPos.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos(hwnd, ctypes.c_void_p(1), 40, 40, 0, 0, 0x0010 | 0x0001)
    deadline = time.monotonic() + 120

    def pump_until(test):
        while not test():
            if time.monotonic() > deadline:
                raise TimeoutError("Native UI verification deadline exceeded")
            root.update()
            time.sleep(0.03)
        root.update()

    screenshots = []
    try:
        root.update()
        screenshots.append(capture_window(root, "window-initial.png"))
        assert str(app.record_button["state"]) == "disabled"
        app.load_button.invoke()
        pump_until(lambda: app.ready and app.pending == 0)
        assert str(app.record_button["state"]) == "normal"
        app.source.focus_set()
        root.update()
        assert root.focus_lastfor() == app.source
        physical_focus = root.focus_get() == app.source
        app.translate_button.invoke()
        assert "请先" in app.status.get() and app.pending == 0
        app.source.insert("1.0", "佢今日唔得閒，聽日下晝三點先嚟。")
        app.translate_button.invoke()
        pump_until(lambda: app.pending == 0 and app.last_translation is not None)
        translated = app.target.get("1.0", "end-1c")
        assert "下午" in translated and "今天" in translated
        screenshots.append(capture_window(root, "window-translated.png"))
        app.direction.set("普通话 → 粤语")
        app.update_options()
        app.open_audio(ROOT / "models/asr/test_wavs/zh.wav")
        pump_until(lambda: app.pending == 0 and app.last_translation[1] == "yue")
        assert app.player.chunks
        app.audio_source_box.set("设备播放声音")
        app.audio_source_box.event_generate("<<ComboboxSelected>>")
        root.update()
        assert "设备声音" in str(app.record_button["text"])
        assert app.microphone is None
        screenshots.append(capture_window(root, "window-system-audio.png"))
        # Set the capture state without opening a device, then send real fixture
        # PCM through the same submit/worker path as a live capture segment.
        pcm_before = len(app.player.chunks)
        app.listening = True
        app._buttons()
        assert str(app.auto_box["state"]) == "disabled"
        assert not app.submit(Request(app.epoch, "speak", source="zh", text="不可在设备收音中播报"))
        samples, rate = sf.read(str(ROOT / "models/asr/test_wavs/zh.wav"), dtype="float32")
        assert app.submit(
            Request(app.epoch, "audio", source="zh", samples=samples, rate=rate, autoplay=True)
        )
        pump_until(lambda: app.pending == 0)
        assert len(app.player.chunks) == pcm_before and "仅字幕" in app.status.get()
        app.stop()
        root.geometry("940x650+40+40")
        root.update()
        screenshots.append(capture_window(root, "window-compact.png"))
        controls = [
            app.load_button,
            app.record_button,
            app.file_button,
            app.translate_button,
            app.replay_button,
            app.stop_button,
        ]
        for widget in controls:
            assert widget.winfo_width() > 30 and widget.winfo_height() > 20
            assert widget.winfo_rootx() >= root.winfo_rootx()
            assert (
                widget.winfo_rootx() + widget.winfo_width()
                <= root.winfo_rootx() + root.winfo_width() + 2
            )
        assert app.status_label.winfo_ismapped()
        assert (
            app.status_label.winfo_rooty() + app.status_label.winfo_height()
            <= root.winfo_rooty() + root.winfo_height()
        )
        assert app.footer_label.winfo_height() >= app.footer_label.winfo_reqheight()
        assert (
            app.footer_label.winfo_rooty() + app.footer_label.winfo_height()
            <= root.winfo_rooty() + root.winfo_height()
        )
        # Reproduce the state after synthesis ends while PCM is still queued.
        # The test sink remains muted: this checks UI/queue state, not a speaker.
        assert app.pending == 0
        pcm, rate = app.player.chunks[0]
        app.player.queue.put_nowait((app.player.generation, pcm, rate))
        block = app.player.queue.get_nowait()
        assert app.player.queue.empty() and app.player.busy
        app.player.queue.task_done()
        app.player.queue.put_nowait(block)
        app._buttons()
        assert str(app.stop_button["state"]) == "normal"
        # Exercise the registered keyboard stop path without accessing devices.
        old_epoch = app.epoch
        app.source.focus_set()
        root.update()
        root.event_generate("<Escape>")
        root.update()
        escape_delivered = app.epoch == old_epoch + 1
        # A background WS_EX_NOACTIVATE QA window may not own keyboard focus.
        # Record that plane honestly and also exercise the visible stop action.
        if not escape_delivered:
            app.stop_button.invoke()
            root.update()
        assert not app.listening
        assert not app.player.busy
        app.player.queue.put_nowait(block)
        app._buttons()
        app.stop_button.invoke()
        root.update()
        assert not app.player.busy
        widgets = [
            dict(
                text=str(w["text"]),
                state=str(w["state"]),
                x=w.winfo_x(),
                y=w.winfo_y(),
                width=w.winfo_width(),
                height=w.winfo_height(),
            )
            for w in controls
        ]
        report = dict(
            status="executed",
            source="real Tk window and real model outputs; muted PCM sink",
            screenshots=screenshots,
            empty_input_error=True,
            focus_request=True,
            physical_keyboard_focus=physical_focus,
            escape_event_delivered=escape_delivered,
            escape_binding_present=bool(root.bind("<Escape>")),
            stop_button_exercised=True,
            file_input=True,
            direction_switch=True,
            controls=widgets,
            pending_pcm_stop_enabled=True,
            in_progress_pcm_busy=True,
            system_source_selector=True,
            selector_does_not_start_capture=app.microphone is None,
            system_capture_state_suppresses_speech=True,
            physical_audio_devices="not activated",
            android="unverified",
            host_ui_governance="UNVERIFIED",
        )
        (OUTPUT / "ui-verification.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        app.close()
        while app.worker.is_alive() and time.monotonic() < deadline:
            root.update()
            time.sleep(0.03)
        try:
            root.update()
        except tk.TclError:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["engine", "ui", "playback"])
    args = parser.parse_args()
    {"engine": engine_check, "ui": ui_check, "playback": playback_check}[args.mode]()
