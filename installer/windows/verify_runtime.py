"""Exercise the packaged/installed runtime with synthetic text and muted audio."""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path


def verify(installation, evidence):
    installation = installation.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    evidence = evidence.resolve()
    assert sys.flags.isolated and Path(sys.executable).resolve().is_relative_to(installation)
    assert all(Path(path).is_relative_to(installation) for path in sys.path)
    os.environ["YUEPU_DATA_DIR"] = str(installation / "data")
    os.environ["LOCALAPPDATA"] = str(evidence / "user-data")
    os.environ["QT_QPA_PLATFORM"] = "windows"
    os.environ["TEMP"] = os.environ["TMP"] = str(evidence / "temp")
    Path(os.environ["TEMP"]).mkdir(parents=True, exist_ok=True)

    import numpy as np
    import onnxruntime as ort
    import soxr
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtWidgets import QApplication

    from yuepu_translate.desktop_qt import STYLE, Window
    from yuepu_translate.local_inference import LocalInference

    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(evidence / "settings"))
    app = QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Window(muted=True)
    window.setAttribute(Qt.WA_DontShowOnScreen)
    window.show()
    result = {
        "scope": "local packaged runtime verification; independent of installer registration and clean-VM acceptance",
        "microphone_opened": False,
        "speaker_opened": False,
        "translations": [],
    }

    def wait(predicate, timeout=180):
        deadline = time.monotonic() + timeout
        while not predicate():
            app.processEvents()
            if time.monotonic() >= deadline:
                raise TimeoutError(window.status_label.text())
            time.sleep(0.02)
        app.processEvents()

    try:
        window.input.setPlainText("x" * 121)
        window.translate_input()
        assert window.pending == 0 and "120" in window.status_label.text()
        result["oversized_text_rejected"] = True
        print("Loading actual packaged models", flush=True)
        started = time.monotonic()
        window.load()
        wait(lambda: window.pending == 0)
        assert window.ready, window.status_label.text()
        result["load_seconds"] = round(time.monotonic() - started, 3)
        print("Models loaded", result["load_seconds"], flush=True)
        for direction, source in (
            (1, "他今天没空，请明天再来。"),
            (0, "佢今日唔得閒，唔該聽日再嚟。"),
        ):
            window.player.chunks.clear()
            window.direction_box.setCurrentIndex(direction)
            window.auto_box.setChecked(True)
            window.input.setPlainText(source)
            window.translate_input()
            wait(lambda: window.pending == 0)
            row = window.model.items[-1]
            assert row.target and row.target_confirmed == len(row.target), (
                window.status_label.text()
            )
            assert window.player.chunks, "Missing synthesized speech"
            assert all(np.isfinite(pcm).all() for pcm, _ in window.player.chunks)
            assert any(np.max(np.abs(pcm)) > 0.00001 for pcm, _ in window.player.chunks)
            result["translations"].append(
                {
                    "source": source,
                    "target": row.target,
                    "speech_samples": sum(len(pcm) for pcm, _ in window.player.chunks),
                }
            )
            print("Translation and muted TTS passed", direction, flush=True)
        window.player.chunks.clear()
        cancelled = threading.Event()
        window.engine.speak(
            "香港西九龙高铁站。", "zh", "original", window.player, cancelled, lambda: None
        )
        rate = window.player.chunks[0][1]
        audio = np.concatenate([pcm.mean(axis=1) for pcm, _ in window.player.chunks])
        recognized = window.engine.recognize(audio, rate, cancelled, "zh", lambda *args: None)
        assert "香港" in recognized
        result["light_asr"] = recognized
        print("Light ASR passed", flush=True)
        data = soxr.resample(audio, rate, 16000).astype(np.float32)
        large = LocalInference("asr", "zh", root=installation / "data")
        try:
            started = time.monotonic()
            large.start(cancelled)
            result["pro_asr"] = large.transcribe(data, cancelled)
            result["pro_asr_seconds"] = round(time.monotonic() - started, 3)
            assert "香港" in result["pro_asr"]
        finally:
            large.close()
        print("Pro ASR passed", flush=True)
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        separator = ort.InferenceSession(
            str(installation / "data/models/song-separator/Kim_Vocal_2.onnx"),
            options,
            providers=["CPUExecutionProvider"],
        )
        assert separator.get_inputs() and separator.get_outputs()
        result["separator_loads"] = True
        del separator
        assert window.grab().save(str(evidence / "window.png"))
    finally:
        window.close()
        wait(lambda: not window.worker.is_alive(), 20)
        app.processEvents()
    # Exercise the real launcher as a separate process, using only this runtime.
    log = evidence / "launcher.log"
    with log.open("wb") as stream:
        launch_environment = os.environ.copy()
        launch_environment["QT_QPA_PLATFORM"] = "offscreen"
        child = subprocess.Popen(
            [
                str(installation / "python/pythonw.exe"),
                "-I",
                "-B",
                str(installation / "launch.py"),
                "--muted",
            ],
            cwd=evidence,
            stdout=stream,
            stderr=stream,
            env=launch_environment,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            time.sleep(3)
            assert child.poll() is None, log.read_text(encoding="utf-8", errors="replace")
            result["real_launcher_starts"] = True
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(10)
    (evidence / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    verify(args.installation, args.evidence)
