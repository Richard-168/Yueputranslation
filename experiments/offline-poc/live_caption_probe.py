"""Real local inference through Qt capture controls, with paced PCM injection.

This is not physical microphone/loopback or cloud evidence. Input audio and
screenshots stay in local ignored outputs. No audio is uploaded or recorded.
"""

import argparse
import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import soundfile as sf
from PySide6.QtCore import QSettings
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication

from yuepu_translate import model_runtime
from yuepu_translate.audio_profile import DEFAULT_SENSITIVITY, VOICE_PROFILES
from yuepu_translate.desktop_engine import PlaybackProcessor, SpeechSegmenter
from yuepu_translate.desktop_qt import STYLE, Window
from yuepu_translate.desktop_theme import THEMES
from yuepu_translate.local_inference import LocalInference
from yuepu_translate.song_pipeline import make_song_stream
from yuepu_translate.transcript_model import TranscriptEntry


def check_ui_versions(window):
    """Synthetic ordering checks, separate from the real-model timing sample."""
    epoch, block = window.epoch, 1000

    def send(kind, value):
        window.events.put((epoch, 0, kind, value))
        window.poll()

    def source(text, version, final=False):
        send(
            "live_source",
            dict(
                block=block,
                text=text,
                version=version,
                final=final,
                frozen_characters=len(text) if final else 0,
                recognition_seconds=0,
                lag_seconds=0,
            ),
        )

    def translation(text, version, final=False):
        send("live_translation", dict(block=block, text=text, version=version, final=final))

    source("测试草稿", 1)
    source("测试修订", 2)
    translation("过期译文", 1)
    item = window.model.items[-1]
    assert item.source == "测试修订" and item.target == ""
    source("测试确认", 3, final=True)
    translation("确认译文", 3, final=True)
    translation("迟到译文", 2)
    assert item.source == "测试确认" and item.target == "确认译文" and item.status == "已确认"
    count = window.model.rowCount()
    window.stop()
    source("取消前迟到的文字", 4)
    assert window.model.rowCount() == count and item.source == "测试确认"
    return dict(
        stale_translation_ignored=True, final_translation_retained=True, canceled_epoch_ignored=True
    )


def check_confirmed_spans(window, output):
    block, epoch = 2000, window.epoch
    prefix, target_prefix = "我哋今日下晝三點喺車站見面，", "我们今天下午三点在车站见面，"
    source, target = prefix + "末尾仲喺度修訂", target_prefix + "末尾仍在校正"
    window.events.put(
        (
            epoch,
            0,
            "live_source",
            dict(
                block=block,
                text=source,
                version=1,
                final=False,
                frozen_characters=len(prefix),
                recognition_seconds=0,
                lag_seconds=0,
            ),
        )
    )
    window.events.put(
        (
            epoch,
            0,
            "live_translation",
            dict(
                block=block,
                text=target,
                source=source,
                version=1,
                final=False,
                frozen_source=prefix,
                frozen_target=target_prefix,
            ),
        )
    )
    window.poll()
    row = window.model.items[-1]
    assert row.source_confirmed == len(prefix) and row.target_confirmed == len(target_prefix)
    window.events.put(
        (
            epoch,
            0,
            "live_source",
            dict(
                block=block,
                text=prefix + "而家更新末尾",
                version=2,
                final=False,
                frozen_characters=len(prefix),
                recognition_seconds=0,
                lag_seconds=0,
            ),
        )
    )
    window.poll()
    assert row.target == target, "A new source must retain its fixed and provisional translation"
    docs, _ = window.delegate.documents(row, window.view.viewport().width())
    assert docs[0].toPlainText() == row.source and docs[1].toPlainText() == target
    fragments = []
    iterator = docs[1].begin().begin()
    while not iterator.atEnd():
        fragment = iterator.fragment()
        fragments.append((fragment.text(), fragment.charFormat().foreground().color().name()))
        iterator += 1
    colors = THEMES[window.theme]
    assert fragments == [(target_prefix, colors["text"]), ("末尾仍在校正", colors["draft"])], (
        fragments
    )
    for _ in range(20):
        window.model.update_entry(row.key, status="亮色已固定 · 浅色暂定")
        window.delegate.documents(row, window.view.viewport().width())
    assert len([key for key in window.delegate.heights if key[0] == row.key]) <= 2
    window.go_latest()
    QApplication.processEvents()
    window.grab().save(str(output / "synthetic-spans.png"))
    index = window.model.index(window.model.rowCount() - 1)
    window.view.scrollTo(index)
    window.view.viewport().grab(window.view.visualRect(index)).save(str(output / "span-detail.png"))
    return dict(
        fixed_translation_retained=True,
        confirmed_and_draft_colors=True,
        height_cache_does_not_grow_with_revisions=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--source", choices=("zh", "yue"), required=True)
    parser.add_argument("--device", action="store_true", help="Exercise device-input UI wiring")
    parser.add_argument(
        "--speak",
        action="store_true",
        help="Generate real TTS into muted PCM; never opens speakers",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=1, choices=range(1, 7))
    parser.add_argument("--history-rows", type=int, default=0, choices=(0, 2000, 10000))
    parser.add_argument("--profile", choices=("flash", "pro"), default="pro")
    parser.add_argument("--sensitivity", choices=tuple(VOICE_PROFILES), default=DEFAULT_SENSITIVITY)
    args = parser.parse_args()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(args.output / "settings"))
    preferences = QSettings(QSettings.IniFormat, QSettings.UserScope, "YuePuTranslate", "Desktop")
    preferences.setValue("defaults/cache_directory", str(args.output / "cache"))
    preferences.sync()
    audio, rate = sf.read(args.audio, dtype="float32", always_2d=True)
    if not 0 < len(audio) <= rate * 30:
        parser.error("Use a local speech sample of at most 30 seconds")
    audio = np.tile(audio, (args.repeat, 1))
    # Trailing silence lets the real VAD finalize the last words.
    audio = np.concatenate((audio, np.zeros((round(rate * 1.2), audio.shape[1]), np.float32)))
    app = QApplication([])
    if not QFontDatabase.families():
        if QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc") < 0:
            raise RuntimeError("Chinese font is unavailable for offscreen rendering")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Window(muted=True)
    window.engine.asr = model_runtime.recognizer()
    if args.speak and not args.device:
        if args.source == "yue":
            window.engine.zh_tts = model_runtime.mandarin_engine()
        else:
            window.engine.yue_tts = model_runtime.canto_engine()
    window.ready = True
    window.direction_box.setCurrentIndex(0 if args.source == "yue" else 1)
    window.source_box.setCurrentIndex(int(args.device))
    window.profile_box.setCurrentIndex(int(args.profile == "pro"))
    window.sensitivity_box.setCurrentIndex(window.sensitivity_box.findData(args.sensitivity))
    # Even when checked, device capture must suppress automatic speech.
    window.auto_box.setChecked(args.device or args.speak)
    window._buttons()
    for key in range(args.history_rows):
        text = "历史字幕负载测试，已固定的内容不重新翻译。"
        window.sequence += 1
        window.model.append(
            TranscriptEntry(
                window.sequence,
                "zh",
                "yue",
                source=text,
                target=text,
                status="已确认",
                source_confirmed=len(text),
                target_confirmed=len(text),
            )
        )
    window.show()
    args.output.mkdir(parents=True, exist_ok=True)
    started, feed_done = threading.Event(), threading.Event()
    timing, sources, capture_errors, inference_calls, runtime_errors = {}, [], [], [], []
    translation_updates = []
    original_status = window.status

    def status(text, error=False):
        if error:
            runtime_errors.append(text)
        original_status(text, error)

    window.status = status
    original_recognize = window.engine.recognize
    original_translate, original_transcribe = LocalInference.translate, LocalInference.transcribe

    def recognize(samples, rate, cancel, source, emit):
        begin = time.perf_counter()
        text = original_recognize(samples, rate, cancel, source, emit)
        inference_calls.append(
            dict(
                kind="asr",
                input_seconds=round(len(samples) / rate, 3),
                seconds=round(time.perf_counter() - begin, 3),
            )
        )
        return text

    def translate(model, text, cancel):
        begin = time.perf_counter()
        result = original_translate(model, text, cancel)
        inference_calls.append(
            dict(
                kind="translation",
                input_characters=len(text),
                seconds=round(time.perf_counter() - begin, 3),
            )
        )
        return result

    def transcribe(model, samples, cancel):
        begin = time.perf_counter()
        result = original_transcribe(model, samples, cancel)
        inference_calls.append(
            dict(
                kind="asr",
                input_seconds=round(len(samples) / 16000, 3),
                seconds=round(time.perf_counter() - begin, 3),
            )
        )
        return result

    window.engine.recognize = recognize

    class InjectedCapture:
        def __init__(self, emit, error, ready=None, paragraph=False, segmenter_factory=None):
            self.stop_event = threading.Event()
            self.processor = PlaybackProcessor(
                rate,
                audio.shape[1],
                emit,
                segmenter_factory=segmenter_factory or (make_song_stream if paragraph else None),
            )
            self.thread = None
            self.ready, self.error = ready, error

        def start(self):
            def feed():
                try:
                    if self.ready:
                        self.ready("本地 PCM 注入（非真实设备）")
                    timing["start"] = time.monotonic()
                    started.set()
                    size = max(1, round(rate * 0.032))
                    for offset in range(0, len(audio), size):
                        if self.stop_event.is_set():
                            break
                        self.processor.feed(audio[offset : offset + size])
                        wait = timing["start"] + (offset + size) / rate - time.monotonic()
                        if wait > 0:
                            self.stop_event.wait(wait)
                    self.processor.flush()
                except Exception as exc:
                    capture_errors.append(str(exc))
                    self.error(str(exc))
                finally:
                    feed_done.set()

            self.thread = threading.Thread(target=feed, daemon=True)
            self.thread.start()

        def stop(self):
            self.stop_event.set()
            if self.thread:
                self.thread.join(4)

    report = dict(
        input="paced local PCM injection; no physical device",
        asr="real WenetSpeech-Yue U2++ drafts + Qwen3-ASR-1.7B paragraph review"
        if args.profile == "pro"
        else "real WenetSpeech-Yue U2++",
        translation="real local Hy-MT2",
        source=args.source,
        device_ui=args.device,
        history_rows=args.history_rows,
        repeat=args.repeat,
        profile=args.profile,
        sensitivity=args.sensitivity,
        speech="real local TTS into muted PCM" if args.speak and not args.device else "disabled",
    )
    try:
        with (
            patch("yuepu_translate.desktop_qt.Microphone", InjectedCapture),
            patch("yuepu_translate.desktop_qt.SystemAudio", InjectedCapture),
            patch.object(LocalInference, "translate", translate),
            patch.object(LocalInference, "transcribe", transcribe),
        ):
            window.record_button.click()
            deadline = time.monotonic() + 90
            last = {item.key: item.source for item in window.model.items}
            last_targets = {}
            stopped = False
            while time.monotonic() < deadline:
                app.processEvents()
                if started.is_set():
                    for item in window.model.items:
                        if item.key <= args.history_rows:
                            continue
                        if item.source and last.get(item.key) != item.source:
                            value = dict(
                                seconds=round(time.monotonic() - timing["start"], 3),
                                row=item.key,
                                text=item.source,
                                status=item.status,
                                source_confirmed=item.source_confirmed,
                                target_confirmed=item.target_confirmed,
                            )
                            sources.append(value)
                            last[item.key] = item.source
                            if len(sources) == 1:
                                window.grab().save(str(args.output / "first-source.png"))
                        if item.target and last_targets.get(item.key) != item.target:
                            translation_updates.append(
                                dict(
                                    seconds=round(time.monotonic() - timing["start"], 3),
                                    row=item.key,
                                    text=item.target,
                                    status=item.status,
                                    source_confirmed=item.source_confirmed,
                                    target_confirmed=item.target_confirmed,
                                )
                            )
                            last_targets[item.key] = item.target
                            if not item.target_confirmed:
                                window.grab().save(str(args.output / "coarse-translation.png"))
                        if item.target_confirmed and item.target_confirmed < len(item.target):
                            window.grab().save(str(args.output / "mixed-spans.png"))
                if feed_done.is_set() and not stopped:
                    # The same user button requests a graceful final drain.
                    window.record_button.click()
                    stopped = True
                if stopped and not window.pending:
                    break
                time.sleep(0.01)
            else:
                raise TimeoutError("Qt live session did not drain within 90 seconds")
            report.update(
                first_source_seconds=sources[0]["seconds"] if sources else None,
                source_updates=sources,
                translation_updates=translation_updates,
                errors=capture_errors + runtime_errors,
                rows=[
                    dict(source=item.source, target=item.target, status=item.status)
                    for item in window.model.items
                    if item.key > args.history_rows
                ],
                inference_calls=inference_calls,
                generated_pcm_chunks=len(window.player.chunks),
            )
            if args.speak and not args.device:
                assert window.player.chunks, "Confirmed translation must generate muted PCM"
            if (
                not sources
                or not any(
                    item.target for item in window.model.items if item.key > args.history_rows
                )
                or capture_errors
                or runtime_errors
            ):
                raise AssertionError(
                    "Expected real source and translation without capture errors: "
                    + str(capture_errors)
                    + "; "
                    + window.status_label.text()
                )
            window.grab().save(str(args.output / "final.png"))

        # Old default capture's earliest completed segment, with the same PCM.
        boundaries = []
        position = 0
        processor = PlaybackProcessor(
            rate,
            audio.shape[1],
            lambda samples: boundaries.append(position / rate),
            segmenter_factory=lambda emit: SpeechSegmenter(emit),
        )
        for position in range(0, len(audio), max(1, round(rate * 0.032))):
            processor.feed(audio[position : position + round(rate * 0.032)])
        processor.flush()
        report["old_first_segment_ready_seconds"] = boundaries[0] if boundaries else None
        report["synthetic_ui_checks"] = check_ui_versions(window)
        report["synthetic_span_checks"] = check_confirmed_spans(window, args.output)
        (args.output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    key: value
                    for key, value in report.items()
                    if key
                    not in {"source_updates", "translation_updates", "rows", "inference_calls"}
                },
                ensure_ascii=False,
            )
        )
    finally:
        window.close()
        deadline = time.monotonic() + 40
        while window.worker.is_alive() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)
        if window.worker.is_alive():
            raise TimeoutError("Qt worker did not stop")


if __name__ == "__main__":
    main()
