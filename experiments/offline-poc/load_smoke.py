"""Exercise on-demand Windows startup and reuse one real MT process in both directions."""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _bootstrap  # noqa: E402, F401
from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from yuepu_translate.cloud_config import CloudConfig  # noqa: E402
from yuepu_translate.desktop_qt import Window  # noqa: E402
from yuepu_translate.session_history import SessionHistory  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "outputs/demand-load-smoke"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(OUT / "settings"))
    app = QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    errors, statuses = [], []
    with patch("yuepu_translate.desktop_qt.load_settings", return_value=(CloudConfig(), False)):
        window = Window(muted=True, history=SessionHistory(OUT / "history.sqlite3"))
    original_status = window.status

    def status(text, error=False):
        (errors if error else statuses).append(text)
        print(text, flush=True)
        original_status(text, error)

    window.status = status
    child = None
    try:
        window.show()
        app.processEvents()
        assert window.pending == 0 and not window.input.isReadOnly()
        assert window.engine.translator.child is None
        window.auto_box.setChecked(False)
        seconds = []
        for direction, text in ((0, "多謝你幫手。"), (1, "谢谢你帮忙。")):
            window.direction_box.setCurrentIndex(direction)
            window.input.setPlainText(text)
            begin = time.monotonic()
            window.translate_button.click()
            assert window.pending == 1
            while window.pending and time.monotonic() - begin < 90:
                app.processEvents()
                time.sleep(0.01)
            seconds.append(round(time.monotonic() - begin, 3))
            assert not errors and not window.pending, (errors, statuses)
            assert window.model.items[-1].target
            if child is None:
                child = window.engine.translator.child
            assert child is not None and child.poll() is None
            assert window.engine.translator.child is child
            assert window.engine.asr is window.engine.zh_tts is window.engine.yue_tts is None
        assert window.record_button.isVisible() and window.record_button.isEnabled()
        window.grab().save(str(OUT / "ready.png"))
        report = dict(
            result="passed",
            entry="idle window, first local translation and reverse translation",
            translation_seconds=seconds,
            reused_mt_process=True,
            errors=errors,
            statuses=statuses,
            audio="muted sink, no input/output device",
            cloud="not called",
        )
        (OUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        window.close()
        deadline = time.monotonic() + 40
        while window.worker.is_alive() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)
        assert not window.worker.is_alive(), "Worker did not stop"
        assert child is None or child.poll() is not None, "Translation process did not stop"


if __name__ == "__main__":
    main()
