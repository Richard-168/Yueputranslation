"""Actual Qt entry/setting checks with synthetic PCM and fake inference, no devices/cloud."""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _bootstrap  # noqa: E402, F401
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
from PySide6.QtCore import QSettings, QTimer  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialogButtonBox  # noqa: E402

from yuepu_translate.cloud_config import CloudConfig  # noqa: E402
from yuepu_translate.desktop_qt import Window  # noqa: E402
from yuepu_translate.preferences import cache_directory, load_preferences  # noqa: E402
from yuepu_translate.session_history import SessionHistory  # noqa: E402
from yuepu_translate.settings_dialog import SettingsDialog  # noqa: E402
from yuepu_translate.song_pipeline import SongFile, make_song_stream  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "outputs/paragraph-pro/ui"


class Inference:
    received = []

    def __init__(self, source, config, emit, **kwargs):
        self.source = source

    def start(self, cancel):
        pass

    def transcribe(self, samples, cancel):
        return "复核后的测试短句"

    def translate(self, text, cancel):
        self.received.append(text)
        return "译文：" + text

    def close(self):
        pass


class Capture:
    selections = []

    def __init__(self, emit, error, started=None, **kwargs):
        self.started = started
        factory = kwargs.get("segmenter_factory") or make_song_stream
        self.selections.append((factory.func.__name__, factory.keywords["sensitivity"]))
        self.stream = factory(emit)

    def start(self):
        if self.started:
            self.started("模拟音源")
        self.stream.feed(np.ones(4 * 16000, np.float32))

    def stop(self):
        self.stream.flush()
        self.on_finished()

    request_stop = stop


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(OUT / "preferences"))
    settings = QSettings(QSettings.IniFormat, QSettings.UserScope, "YuePuTranslate", "Desktop")
    settings.clear()
    settings.sync()
    app = QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/consola.ttf")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyle("Fusion")
    checks = []

    def wait_for(predicate, seconds=4):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        assert predicate(), "Qt condition timed out"

    def finish(window):
        window.stop()
        wait_for(lambda: window.pending == 0)
        window.close()
        wait_for(lambda: not window.worker.is_alive())
        app.processEvents()

    with (
        patch("yuepu_translate.desktop_qt.load_settings", return_value=(CloudConfig(), False)),
        patch("yuepu_translate.live_session.SessionInference", Inference),
        patch("yuepu_translate.enhanced_inference.SessionInference", Inference),
        patch("yuepu_translate.song_pipeline.SessionInference", Inference),
        patch("yuepu_translate.song_pipeline.make_voice_detector", return_value=lambda frame: True),
        patch("yuepu_translate.desktop_qt.Microphone", Capture),
        patch("yuepu_translate.desktop_qt.SystemAudio", Capture),
    ):
        history = SessionHistory(OUT / "history.sqlite3")
        window = Window(muted=True, history=history)
        window.show()
        window.engine.prepare_recognition = lambda cancel: None
        window.engine.prepare_voice = lambda target, cancel: None
        window.engine.recognize = lambda *args: "轻量草稿测试"
        window.engine.speak = lambda *args: None
        window._buttons()
        try:
            assert [window.profile_box.itemText(i) for i in range(2)] == [
                "快速  (flash)",
                "精细  (pro)",
            ]
            assert window.profile_box.currentIndex() == 1
            assert window.sensitivity_box.currentData() == "standard"
            assert [window.sensitivity_box.itemText(i) for i in range(2)] == ["标准", "灵敏"]
            window.sensitivity_box.setCurrentIndex(1)
            assert load_preferences().sensitivity == "sensitive"
            checks.append("default pro and flash/pro selector")
            for index in (1, 0):
                for source in (0, 1):
                    for sensitivity in ("standard", "sensitive"):
                        window.profile_box.setCurrentIndex(index)
                        window.source_box.setCurrentIndex(source)
                        window.sensitivity_box.setCurrentIndex(
                            window.sensitivity_box.findData(sensitivity)
                        )
                        previous_key = window.model.items[-1].key if window.model.items else 0
                        window.record_button.click()
                        wait_for(
                            lambda: (
                                bool(window.model.items)
                                and window.model.items[-1].key > previous_key
                                and window.microphone is not None
                                and window.capture_started
                            )
                        )
                        assert not window.audio_button.isEnabled()
                        assert Capture.selections[-1] == (
                            "make_song_stream" if index else "make_live_stream",
                            sensitivity,
                        )
                        wait_for(lambda: bool(window.model.items[-1].source))
                        if index == 1:
                            assert window.model.items[-1].source_confirmed == 0
                            assert window.model.items[-1].status != "已确认"
                        window.record_button.click()
                        wait_for(lambda: window.pending == 0)
                        assert window.audio_button.isEnabled()
                        item = window.model.items[-1]
                        assert item.status == "已确认" and item.target
                        assert item.source == ("复核后的测试短句。" if index else "轻量草稿测试。")
            checks.append("both saved sensitivities reach pro/flash capture on both audio sources")
            with patch("yuepu_translate.desktop_qt.save_preferences", side_effect=OSError):
                window.sensitivity_box.setCurrentIndex(0)
            assert window.sensitivity_box.currentData() == "sensitive"
            assert load_preferences().sensitivity == "sensitive"
            assert "无法保存" in window.status_label.text()
            checks.append("failed sensitivity save restores visible and stored selection")
            checks.append("real recording buttons, provisional/reviewed/final events in both modes")

            def send(kind, value):
                window.events.put((window.epoch, 0, kind, value))
                window.poll()

            def source(text, version, final=False):
                send(
                    "live_source",
                    dict(
                        block=20001,
                        text=text,
                        version=version,
                        final=final,
                        frozen_characters=len(text) if final else 0,
                        recognition_seconds=0,
                        lag_seconds=0,
                        reviewing=not final,
                    ),
                )

            def translation(text, version, final=False):
                send(
                    "live_translation",
                    dict(
                        block=20001,
                        text=text,
                        source="测试",
                        version=version,
                        final=final,
                        preview=not final,
                        frozen_source="",
                        frozen_target=text if final else "",
                    ),
                )

            source("今天去公园", 1)
            source("今天去医院，不是公园", 2)
            translation("粗译：今天去公园", 1)
            row = window.model.items[-1]
            assert row.target == "粗译：今天去公园" and row.target_confirmed == 0
            assert "粗略译文" in row.status
            translation("更旧的粗译", 0)
            assert row.target == "粗译：今天去公园"
            source("今天去医院。", 3, True)
            translation("迟到的粗译", 2)
            assert row.target == "粗译：今天去公园"
            translation("确认译文：今天去医院。", 3, True)
            translation("更晚到达的粗译", 1)
            assert row.target == "确认译文：今天去医院。" and row.status == "已确认"
            checks.append(
                "delayed coarse translation is visible; confirmed source rejects late previews"
            )

            for theme in ("dark", "light"):
                window.apply_theme(theme)
                for width, height in ((1240, 850), (960, 700)):
                    window.resize(width, height)
                    app.processEvents()
                    assert window.grab().save(str(OUT / f"{theme}-{width}.png"))
            window.apply_theme("dark")

            def save_defaults():
                dialog = app.activeModalWidget()
                assert isinstance(dialog, SettingsDialog)
                dialog.mode.setCurrentIndex(dialog.mode.findData("flash"))
                dialog.direction.setCurrentIndex(dialog.direction.findData("zh"))
                dialog.audio_source.setCurrentIndex(dialog.audio_source.findData("system"))
                dialog.autoplay.setChecked(False)
                dialog.sensitivity.setCurrentIndex(dialog.sensitivity.findData("standard"))
                dialog.cache.setText(str(OUT / "cache"))
                dialog.exports.setText(str(OUT / "exports"))
                for i in range(3):
                    dialog.tabs.setCurrentIndex(i)
                    app.processEvents()
                    assert dialog.grab().save(str(OUT / f"settings-{i}.png"))
                dialog.buttons.button(QDialogButtonBox.Save).click()

            QTimer.singleShot(50, save_defaults)
            preferences_action = next(
                action
                for action in window.settings_button.menu().actions()
                if action.text() == "首选项…"
            )
            preferences_action.trigger()
            assert window.profile_box.currentIndex() == 0
            assert window.source_box.currentIndex() == 1
            assert window.sensitivity_box.currentData() == "standard"
            assert cache_directory() == OUT / "cache"
            checks.append("settings Save via real modal, chosen cache path, immediate defaults")
            export = OUT / "exports/subtitles.txt"
            with patch(
                "yuepu_translate.desktop_qt.QFileDialog.getSaveFileName",
                return_value=(str(export), ""),
            ) as picker:
                window.export_button.click()
                assert str(OUT / "exports") in picker.call_args.args[2]
            assert export.exists()
            checks.append("export button uses configured folder and writes synthetic subtitles")

            # Both restored paragraph capture and file tasks own a bounded mailbox.
            sample = OUT / "synthetic.wav"
            sf.write(sample, np.ones(16000, np.float32) * 0.2, 16000)
            window.song_session = SongFile(sample, "yue")
            window.stop()
            assert window.song_session is None
            checks.append("restored file task Stop")

            sample = OUT / "synthetic.wav"
            sf.write(sample, np.ones(16000, np.float32) * 0.2, 16000)
            window.cloud_enabled = True
            window.cloud_config = CloudConfig("synthetic-test-key")
            window.open_audio(str(sample))
            wait_for(lambda: window.pending == 0)
            assert window.model.items[-1].target == "译文：轻量草稿测试"
            checks.append("flash file reaches opt-in translation entry without changing mode")
            window.profile_box.setCurrentIndex(1)
            window.open_audio(str(sample))
            wait_for(lambda: window.pending == 0)
            assert window.model.items[-1].source == "复核后的测试短句"
            assert window.model.items[-1].status == "已确认"
            checks.append("pro file entry")
            assert window.audio_button.isEnabled()
        finally:
            finish(window)

        restored = Window(muted=True, history=history)
        try:
            assert restored.profile_box.currentIndex() == 0
            assert restored.source_language() == "zh"
            assert restored.source_box.currentIndex() == 1
            assert restored.sensitivity_box.currentData() == "standard"
            assert not restored.auto_box.isChecked()
            assert not restored.cloud_enabled
            assert load_preferences().export_directory == str(OUT / "exports")
            checks.append(
                "new Window restores defaults and locations; upload consent stays disabled"
            )
        finally:
            finish(restored)
    (OUT / "checks.json").write_text(
        json.dumps(
            dict(
                evidence="synthetic inference, actual Qt controls; no devices or cloud",
                checks=checks,
            ),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(dict(passed=len(checks), checks=checks), ensure_ascii=False))


if __name__ == "__main__":
    main()
