"""Render desktop themes without loading models, recording, playback, or cloud calls.

All transcript rows and runtime states are explicitly UI fixtures, not inference evidence.
Run from the repository root. Images and checks stay in ignored outputs/ui-review/.
"""

import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _bootstrap  # noqa: E402, F401
from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QPushButton  # noqa: E402

from yuepu_translate.cloud_dialog import CloudDialog  # noqa: E402
from yuepu_translate.desktop_qt import Window  # noqa: E402
from yuepu_translate.desktop_theme import THEMES  # noqa: E402
from yuepu_translate.transcript_model import TranscriptEntry  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "outputs" / "ui-review"


def contrast(first, second):
    def luminance(color):
        values = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
        return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    a, b = sorted((luminance(first), luminance(second)))
    return (b + 0.05) / (a + 0.05)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # Isolate preference checks from the user's actual Windows appearance setting.
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(OUT / "settings"))
    app = QApplication([])
    app.setStyle("Fusion")
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    window = Window(muted=True)
    window.show()
    checks = []

    def pump():
        end = time.monotonic() + 0.15
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.005)

    def capture(name):
        pump()
        assert window.grab().save(str(OUT / (name + ".png")))

    def check_layout():
        bounds = window.centralWidget().rect()
        for widget in window.findChildren(QPushButton) + window.findChildren(QComboBox):
            if not widget.isVisible():
                continue
            position = widget.mapTo(window.centralWidget(), widget.rect().topLeft())
            assert bounds.contains(position), widget.text() if hasattr(widget, "text") else widget
            assert bounds.contains(position + widget.rect().bottomRight()), widget.objectName()
        buttons = [window.load_button, window.record_button, window.stop_button]
        visible = [b for b in buttons if b.isVisible()]
        for first, second in zip(visible, visible[1:]):
            assert first.geometry().bottom() < second.geometry().top()
        assert window.status_label.isVisible()
        assert window.empty.title.geometry().top() >= 0

    try:
        for theme, button in (("dark", window.dark_button), ("light", window.light_button)):
            button.click()
            pump()
            assert window.theme == theme and button.isChecked()
            assert window.preferences.value("appearance") == theme
            for size, label in (((1240, 850), ""), ((960, 700), "-compact")):
                window.resize(*size)
                capture(theme + "-empty" + label)
                check_layout()
                window.text_tab.click()
                pump()
                assert window.input.hasFocus() and window.composer.isVisible()
                capture(theme + "-composer" + label)
                check_layout()
                window.live_tab.click()
        checks.append("dark/light buttons, persisted preference, empty and composer at both sizes")
        window.swap_button.click()
        assert window.source_language() == "zh" and "普通话" in window.source_header.text()
        window.swap_button.click()
        checks.append("direction exchange updates paired column headings")
        examples = [
            ("唔好意思，请问去地铁站应该点行？", "不好意思，请问去地铁站应该怎么走？"),
            (
                "沿住呢条路直行，第二个路口转左就见到。",
                "沿着这条路直走，到第二个路口左转就能看到。",
            ),
            ("好，多谢你帮手！", "好的，谢谢你的帮忙！"),
        ]
        for i, (source, target) in enumerate(examples):
            window.model.append(
                TranscriptEntry(
                    i + 1,
                    "yue",
                    "zh",
                    source=source,
                    target=target,
                    status="示例 · 已确认",
                    source_confirmed=len(source),
                    target_confirmed=len(target),
                )
            )
        window.status("界面预览：示例字幕，未启动模型或收音。")
        for theme in THEMES:
            window.apply_theme(theme)
            window.resize(1240, 850)
            capture(theme + "-transcript")
            window.resize(960, 700)
            capture(theme + "-transcript-compact")
            check_layout()
        window.view.setCurrentIndex(window.model.index(1))
        before = window.model.export_text(window.model.items)
        window.dark_button.click()
        window.light_button.click()
        assert window.view.currentIndex().row() == 1
        assert window.model.export_text(window.model.items) == before
        docs, _ = window.delegate.documents(window.model.items[0], 600)
        color = docs[0].begin().begin().fragment().charFormat().foreground().color().name()
        assert color == THEMES["light"]["text"]
        checks.append(
            "theme switch preserves transcript, selection, export and refreshes cached text colors"
        )
        for theme in THEMES:
            window.apply_theme(theme)
            window.status("界面预览：错误状态示例，请检查音频输入。", True)
            capture(theme + "-error")
            assert window.state_label.text() == "异常 / ERROR"
            dialog = CloudDialog(window.cloud_config, parent=window)
            dialog.show()
            pump()
            dialog.grab().save(str(OUT / (theme + "-cloud-dialog.png")))
            dialog.reject()
        checks.append(
            "error state and credential dialog render in both themes; no connection initiated"
        )
        window.status("界面预览：准备就绪状态示例。")
        window.ready = True  # State fixture only. Never start an inference request.
        window._buttons()
        assert window.record_button.isVisible() and not window.load_button.isVisible()
        window.source_box.setCurrentIndex(1)
        window.listening = True  # State fixture only. No physical device is opened.
        window._buttons()
        assert not window.auto_box.isEnabled() and not window.swap_button.isEnabled()
        assert window.state_label.text() == "收音中 / LIVE"
        capture("light-capture-state")
        window.listening = False
        window._buttons()
        checks.append("load/ready/capture controls and device-capture speech protection states")
        window.cloud_enabled = True  # Display fixture only. Never submit a cloud request.
        window.profile_box.setCurrentIndex(1)
        window.source_changed()
        window.network_pill.setText("联网待请求")
        window.status("界面预览：联网提示布局，未发起连接。")
        for theme in THEMES:
            window.apply_theme(theme)
            capture(theme + "-cloud-hint-compact")
            assert window.record_button.geometry().bottom() < window.sidebar.height()
            assert window.stop_button.geometry().bottom() < window.sidebar.height()
        window.cloud_enabled = False
        window.network_pill.setText("本地离线")
        window.source_changed()
        checks.append("long cloud disclosure scrolls independently of pinned start/stop actions")
        window.text_tab.click()
        window.activateWindow()
        window.input.setFocus()
        pump()
        QTest.keyClick(window.input, Qt.Key_Tab)
        assert app.focusWidget() is not None
        QTest.keyClick(window, Qt.Key_Escape)
        assert not window.listening
        checks.append("keyboard focus traversal and Esc cancellation")
        for i in range(120):
            window.model.append(
                TranscriptEntry(
                    1000 + i,
                    "yue",
                    "zh",
                    source="滚动界面测试，非识别结果。",
                    target="界面测试示例。",
                    status="示例",
                )
            )
        pump()
        window.view.interrupt()
        bar = window.view.verticalScrollBar()
        bar.setValue(200)
        window.dark_button.click()
        pump()
        assert not window.view.follow_tail and abs(bar.value() - 200) <= 1
        window.copy_button.click()
        assert QApplication.clipboard().text()
        window.write_export(OUT / "preview-export.txt")
        assert "界面测试" in (OUT / "preview-export.txt").read_text(encoding="utf-8-sig")
        checks.append("theme switch retains history position; actual copy and export paths work")
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
        checks.append("text contrast >= 4.5:1 and field boundaries >= 3:1 in both themes")
        window.light_button.click()
        window.preferences.sync()
        restored = Window(muted=True)
        try:
            assert restored.theme == "light"
            assert not restored.cloud_enabled and not restored.model.items
        finally:
            restored.close()
            restored.worker.join(timeout=5)
            pump()
            assert not restored.worker.is_alive()
        checks.append(
            "new window restores appearance while remaining offline with an empty session"
        )
        print(
            json.dumps(
                {"checks": checks, "inference": "not run", "audio": "not activated"},
                ensure_ascii=True,
                indent=2,
            )
        )
        (OUT / "verification.json").write_text(
            json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        window.listening = False
        window.close()
        window.worker.join(timeout=5)
        pump()
        assert not window.worker.is_alive()


if __name__ == "__main__":
    main()
