"""Load real models through the Qt Load button using the default temporary cache.

No capture, playback, cloud calls, or custom cache-directory override.
Preferences are isolated; actual recognizers, both TTS engines, and MT warm up.
"""

import json
import os
import tempfile
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
from yuepu_translate.preferences import cache_directory, load_preferences  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "outputs/load-smoke"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(OUT / "settings"))
    app = QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    errors, statuses = [], []
    created_temporary_directories = []
    original_temporary_directory = tempfile.TemporaryDirectory

    def track_temporary_directory(*args, **kwargs):
        directory = original_temporary_directory(*args, **kwargs)
        if str(kwargs.get("prefix", "")).startswith("yuepu-"):
            created_temporary_directories.append(Path(directory.name))
        return directory

    with patch("yuepu_translate.desktop_qt.load_settings", return_value=(CloudConfig(), False)):
        window = Window(muted=True)
    window.show()
    original_status = window.status

    def status(text, error=False):
        (errors if error else statuses).append(text)
        print(text, flush=True)
        original_status(text, error)

    window.status = status
    assert not load_preferences().cache_directory, "Do not override the cache in this test"
    started = time.monotonic()
    tracking = patch(
        "yuepu_translate.desktop_engine.tempfile.TemporaryDirectory",
        side_effect=track_temporary_directory,
    )
    tracking.start()
    try:
        window.load_button.click()
        deadline = started + 120
        while window.pending and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        assert not window.pending, "Loading timed out"
        assert window.ready and window.engine.warmed, errors
        assert not errors, errors
        assert window.record_button.isVisible() and window.record_button.isEnabled()
        assert not window.load_button.isVisible()
        cache_directory()
        assert created_temporary_directories
        assert not any(path.exists() for path in created_temporary_directories), (
            "This process's warmup temporary files must be cleaned"
        )
        window.grab().save(str(OUT / "ready.png"))
        report = dict(
            result="passed",
            entry="actual Qt Load button",
            cache="OS temporary directory, no override",
            seconds=round(time.monotonic() - started, 3),
            ready=window.ready,
            engine_warmed=window.engine.warmed,
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
        tracking.stop()
        window.close()
        deadline = time.monotonic() + 40
        while window.worker.is_alive() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.02)
        assert not window.worker.is_alive(), "Worker did not stop"


if __name__ == "__main__":
    main()
