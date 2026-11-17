"""Model-free previews of the Windows composer, settings menu and saved sessions.

Run from the repository root. Captions are synthetic, and files stay under outputs/ui-review.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "windows" if os.name == "nt" else "offscreen")

import _bootstrap  # noqa: E402, F401
from PySide6.QtCore import QPoint, QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QPushButton, QToolButton  # noqa: E402

from yuepu_translate.cloud_config import CloudConfig  # noqa: E402
from yuepu_translate.cloud_dialog import CloudDialog  # noqa: E402
from yuepu_translate.desktop_qt import WELCOME_LINES, Window  # noqa: E402
from yuepu_translate.desktop_theme import THEMES  # noqa: E402
from yuepu_translate.session_history import SessionHistory  # noqa: E402
from yuepu_translate.settings_dialog import SettingsDialog  # noqa: E402
from yuepu_translate.transcript_model import TranscriptEntry  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "outputs" / "ui-review"


def contrast(first, second):
    def luminance(color):
        values = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
        return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    a, b = sorted((luminance(first), luminance(second)))
    return (b + 0.05) / (a + 0.05)


def verify(app, history):
    checks = []

    def pump():
        for _ in range(4):
            app.processEvents()

    def open_window():
        window = Window(muted=True, history=history)
        window.setAttribute(Qt.WA_DontShowOnScreen)
        window.show()
        pump()
        return window

    def close_window(window):
        window.close()
        end = time.monotonic() + 5
        while window.worker.is_alive() and time.monotonic() < end:
            app.processEvents()
            window.worker.join(timeout=0.01)
        pump()
        assert not window.worker.is_alive(), "Worker did not stop"

    def capture(widget, name):
        pump()
        assert widget.grab().save(str(OUT / f"{name}.png")), name

    def capture_settings(window, theme):
        menu = window.settings_button.menu()
        appearance = window.theme_actions[theme].parent()
        assert window.theme_actions[theme].isChecked()
        for popup, name in ((menu, "settings-menu"), (appearance, "appearance-menu")):
            popup.setAttribute(Qt.WA_DontShowOnScreen)
            popup.show()
            capture(popup, f"{theme}-{name}")
            popup.hide()

        preferences = SettingsDialog(window.defaults, window.preferences, window)
        preferences.setAttribute(Qt.WA_DontShowOnScreen)
        preferences.show()
        try:
            for index, name in enumerate(("general", "reading", "files")):
                preferences.tabs.setCurrentIndex(index)
                capture(preferences, f"{theme}-preferences-{name}")
        finally:
            preferences.reject()

        cloud = CloudDialog(CloudConfig(), parent=window)
        cloud.setAttribute(Qt.WA_DontShowOnScreen)
        cloud.show()
        try:
            capture(cloud, f"{theme}-cloud-settings")
        finally:
            cloud.reject()

    def check_layout(window):
        controls = [
            *window.findChildren(QPushButton),
            *window.findChildren(QToolButton),
            *window.findChildren(QComboBox),
        ]
        for widget in controls:
            if not widget.isVisible() or widget.window() is not window:
                continue
            top_left = widget.mapTo(window, widget.rect().topLeft())
            bottom_right = widget.mapTo(window, widget.rect().bottomRight())
            assert window.rect().contains(top_left) and window.rect().contains(bottom_right), (
                widget.text() if hasattr(widget, "text") else widget.currentText(),
                window.size(),
            )
        assert window.input.isVisible() and window.composer.isVisible()
        assert window.audio_button.isVisible() and window.record_button.isVisible()
        for widget in (
            window.direction_box,
            window.file_button,
            window.audio_button,
            window.record_button,
        ):
            bottom_right = widget.mapTo(window.composer, widget.rect().bottomRight())
            assert window.composer.rect().contains(bottom_right), widget

    def check_greetings(window):
        title = window.welcome_title
        original = title.text()
        for _, mandarin, cantonese in WELCOME_LINES:
            for message in (mandarin, cantonese):
                title.setText(message)
                pump()
                bounds = title.fontMetrics().boundingRect(message)
                assert bounds.width() <= title.contentsRect().width(), (message, title.size())
                assert title.sizeHint().height() <= title.contentsRect().height(), (
                    message,
                    title.size(),
                )
        title.setText(original)

    def select_session(window, row):
        view = window.history_list
        item = view.item(row)
        assert item is not None
        QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=view.visualItemRect(item).center())
        pump()

    window = open_window()
    try:
        assert not window.windowIcon().isNull() and window.empty_brand.isVisible()
        assert not window.ready and window.record_button.isEnabled()
        assert not window.history_list.count()
        for theme in THEMES:
            window.apply_theme(theme)
            for size, label in (
                ((1240, 850), ""),
                ((window.minimumWidth(), window.minimumHeight()), "-compact"),
            ):
                window.resize(*size)
                capture(window, theme + "-empty" + label)
                check_layout(window)
                check_greetings(window)
            window.source_box.setCurrentIndex(1)
            for width, compact in ((window.minimumWidth(), True), (1240, False)):
                window.resize(width, window.minimumHeight())
                pump()
                assert window.record_button.text() == "翻译设备声音"
                assert window.compact_layout == compact
                check_layout(window)
            window.source_box.setCurrentIndex(0)
            window.resize(1240, 850)
            menu = window.audio_button.menu()
            assert menu is not None
            menu.setAttribute(Qt.WA_DontShowOnScreen)
            menu.show()
            capture(menu, theme + "-audio-options")
            assert window.source_box.isVisible() and window.profile_box.isVisible()
            assert window.sensitivity_box.isVisible() and window.auto_box.isVisible()
            menu.hide()
            capture_settings(window, theme)
        checks.append("both themes and minimum layout keep one accessible composer")
        checks.append("Mandarin and Cantonese greetings fit on one line in both themes")
        checks.append(
            "settings menus, three preference pages and cloud settings render in both themes"
        )

        splitter = window.history_splitter
        window.resize(1240, 850)
        pump()
        assert splitter.sidebar_width == splitter.DEFAULT_WIDTH
        handle = splitter.handle(1)
        QTest.keyClick(handle, Qt.Key_Right)
        resized_width = splitter.DEFAULT_WIDTH + 16
        assert splitter.sidebar_width == resized_width
        QTest.mouseClick(window.sidebar_toggle, Qt.LeftButton)
        QTest.qWait(240)
        assert not window.sidebar.isVisible() and splitter.sidebar_width == 0
        check_layout(window)
        QTest.mouseClick(window.sidebar_toggle, Qt.LeftButton)
        QTest.qWait(240)
        assert window.sidebar.isVisible() and splitter.sidebar_width == resized_width
        checks.append("sidebar resizes, collapses and returns to the chosen width")

        window.apply_theme("dark")
        with (
            patch("yuepu_translate.desktop_qt.datetime") as clock,
            patch(
                "yuepu_translate.desktop_qt.random.choice", side_effect=lambda choices: choices[1]
            ),
        ):
            clock.now.return_value = datetime(2026, 11, 17, 8, 30)
            window.new_session()
        assert window.welcome_title.text() == "早晨，今日想譯啲咩？"
        pump()
        welcome_top = window.empty_brand.mapTo(window, window.empty_brand.rect().topLeft()).y()
        composer_bottom = window.composer.mapTo(window, window.composer.rect().bottomLeft()).y()
        assert welcome_top + composer_bottom < window.height()
        capture(window, "dark-welcome")
        checks.append("new session uses the local time for a Cantonese greeting above the midpoint")

        window.input.setPlainText("你好，想问一下去地铁站怎么走？")
        pump()
        assert window.translate_button.isEnabled() and window.record_button.isEnabled()
        window.input.clear()
        direction = window.direction_box
        choices = direction.view()
        choices.window().setAttribute(Qt.WA_DontShowOnScreen)
        direction.showPopup()
        pump()
        assert choices.isVisible() and choices.model().rowCount() == 2
        capture(choices.window(), "translation-direction")
        QTest.mouseClick(
            choices.viewport(),
            Qt.LeftButton,
            pos=choices.visualRect(choices.model().index(1, 0)).center(),
        )
        assert window.source_language() == "zh"
        direction.setCurrentIndex(0)
        assert window.source_language() == "yue"
        checks.append("cold-start text and audio actions share a composer and direction")

        previous = TranscriptEntry(
            1, "yue", "zh", source="早晨。", target="早上好。", status="已确认"
        )
        history.save("previous", [previous])
        examples = [
            ("唔好意思，請問去地鐵站應該點行？", "不好意思，请问去地铁站应该怎么走？"),
            (
                "沿住呢條路直行，第二個路口轉左就見到。",
                "沿着这条路直走，到第二个路口左转就能看到。",
            ),
            ("好，多謝你幫手！", "好的，谢谢你的帮忙！"),
        ]
        captions = [
            TranscriptEntry(
                i,
                "yue",
                "zh",
                source=source,
                target=target,
                status="已确认",
                source_confirmed=len(source),
                target_confirmed=len(target),
            )
            for i, (source, target) in enumerate(examples, 1)
        ]
        history.save("direction-example", captions)
        window.refresh_history()
        select_session(window, 0)
        assert window.model.items == captions
        assert not window.empty_brand.isVisible()
        select_session(window, 1)
        assert window.model.items == [previous]
        select_session(window, 0)
        assert window.model.items == captions
        for theme in THEMES:
            window.apply_theme(theme)
            capture(window, theme + "-transcript")
            window.resize(window.minimumSize())
            capture(window, theme + "-transcript-compact")
            check_layout(window)
            window.resize(1240, 850)
        assert window.model.items == captions
        window.write_export(OUT / "preview-export.txt")
        assert captions[0].target in (OUT / "preview-export.txt").read_text(encoding="utf-8-sig")
        checks.append("history selection restores paired text and permits export")

        for name, colors in THEMES.items():
            for foreground in ("text", "muted", "draft"):
                for background in ("paper", "target", "panel", "selected"):
                    assert contrast(colors[foreground], colors[background]) >= 4.5, (
                        name,
                        foreground,
                        background,
                    )
            assert contrast(colors["on_accent"], colors["accent"]) >= 4.5
            assert contrast(colors["control_border"], colors["field"]) >= 3
        checks.append("enabled text and form control outlines have adequate contrast")

        window.apply_theme("light")
        window.preferences.sync()
    finally:
        close_window(window)

    restored = open_window()
    try:
        assert restored.theme == "light"
        assert restored.history_splitter.sidebar_width == resized_width
        assert not restored.cloud_enabled and not restored.listening and not restored.ready
        assert restored.history_list.count() == 2
        select_session(restored, 0)
        assert restored.model.items == captions
        close = restored.findChild(QPushButton, "windowClose")
        if close is not None:
            restored.showMaximized()
            pump()
            assert restored.isMaximized()
            assert restored.childAt(QPoint(restored.width() - 1, 0)) is close
            restored.showNormal()
            pump()
            assert restored.childAt(QPoint(restored.width() - 1, 0)) is not close
            checks.append("maximized Windows close button reaches the exact top-right corner")
    finally:
        close_window(restored)
    checks.append("new window can restore persisted theme and reopen saved sessions")
    return checks


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setStyle("Fusion")
    with (
        TemporaryDirectory(prefix="yuepu-ui-preview-") as scratch,
        patch("yuepu_translate.desktop_qt.load_settings", return_value=(CloudConfig(), False)),
    ):
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, scratch)
        checks = verify(app, SessionHistory(Path(scratch) / "history.sqlite3"))
    report = {"checks": checks, "inference": "not run", "audio": "not activated"}
    (OUT / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
