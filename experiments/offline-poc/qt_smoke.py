"""Qt validation: real model cases separate from clearly synthetic load fixtures."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from desktop_engine import Request
from desktop_qt import STYLE, Window
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QFontDatabase, QWheelEvent
from PySide6.QtWidgets import QApplication
from transcript_model import TranscriptEntry, TranscriptModel

from yuepu_translate.session_history import SessionHistory

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs/qt-smoke"


def cache_checks():
    model = TranscriptModel(max_rows=2, max_chars=20)
    model.append(TranscriptEntry(1, "yue", "zh", source="甲", target="乙"))
    model.append(TranscriptEntry(2, "zh", "yue", source="丙"))
    model.update_entry(2, target="丁")
    model.append(TranscriptEntry(3, "yue", "zh", source="戊"))
    assert [e.key for e in model.items] == [2, 3] and model.characters == 3 and model.evicted == 1
    assert not model.update_entry(1, target="迟到的结果不能写入其他字幕")
    assert "丁" in model.export_text()
    by_chars = TranscriptModel(max_rows=10, max_chars=8)
    by_chars.append(TranscriptEntry(1, "yue", "zh", source="1234"))
    by_chars.append(TranscriptEntry(2, "yue", "zh", source="56"))
    by_chars.update_entry(2, target="7890")
    assert [e.key for e in by_chars.items] == [2] and by_chars.characters == 6
    rejected = 0
    for action in (
        lambda: by_chars.append(TranscriptEntry(2, "zh", "yue")),
        lambda: by_chars.update_entry(2, target="x" * 20),
    ):
        try:
            action()
            raise AssertionError("Invalid transcript mutation accepted")
        except ValueError:
            rejected += 1
    assert rejected == 2 and by_chars.characters == 6
    full = TranscriptModel()
    full.append(TranscriptEntry(1, "yue", "zh", source="甲" * 999999, target="乙" * 999999))
    full.append(TranscriptEntry(2, "zh", "yue", source="丙"))
    assert full.characters == 1999999
    full.update_entry(2, target="丁丁")
    assert full.characters == 3 and [e.key for e in full.items] == [2]
    big = TranscriptModel()
    for i in range(10001):
        big.append(TranscriptEntry(i, "yue", "zh", source="缓存测试", target="仅用于负载测试"))
    assert len(big.items) == 10000 and big.items[0].key == 1 and big.evicted == 1
    return dict(
        row_limit=True,
        character_limit=True,
        paired_export=True,
        late_result_ignored=True,
        invalid_changes_rejected=True,
        ten_thousand_records=True,
        two_million_character_boundary=True,
    )


def scroll_input_check(window, app, pump):
    bar = window.view.verticalScrollBar()
    window.view.smooth = False
    window.go_latest()
    window.view.smooth = True
    start = bar.value()
    assert start > 300
    point = QPointF(100, 100)

    def wheel(pixel, angle):
        event = QWheelEvent(
            point,
            point,
            QPoint(0, pixel),
            QPoint(0, angle),
            Qt.NoButton,
            Qt.NoModifier,
            Qt.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(window.view.viewport(), event)

    wheel(0, 120)
    pump(0.05)
    middle = bar.value()
    assert middle < start and not window.view.follow_tail
    wheel(0, 120)  # Retarget an animation already in progress.
    pump(0.3)
    assert bar.value() <= start - 170 and not window.view.follow_tail
    before = bar.value()
    wheel(-25, 0)  # Precision touchpad pixels should not get a second animation.
    assert bar.value() == before + 25
    value = bar.value()
    pump(0.25)
    assert bar.value() == value
    return dict(
        wheel_event_animated=True, repeated_wheel_retargets=True, touchpad_pixel_delta_exact=True
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    checks = cache_checks()
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(OUT / "settings"))
    app = QApplication([])
    # The offscreen plugin has no Windows font database; register a real system
    # CJK font explicitly for faithful Chinese rendering in verification images.
    if not QFontDatabase.families():
        assert QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc") >= 0
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = Window(muted=True, history=SessionHistory(OUT / "history.sqlite3"))
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    if os.environ["QT_QPA_PLATFORM"] == "windows":
        window.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
    window.show()

    def pump(seconds=0.1):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.008)

    def until(test, timeout=150):
        end = time.monotonic() + timeout
        while not test():
            if time.monotonic() > end:
                raise TimeoutError("Qt verification timed out")
            pump(0.025)
        pump(0.08)

    report = {
        "cache": checks,
        "real_model_cases": [],
        "physical_audio": "not activated",
        "platform": os.environ["QT_QPA_PLATFORM"],
    }
    try:
        pump()
        window.grab().save(str(OUT / "initial.png"))
        assert window.microphone is None and window.engine.translator.child is None
        for source, text in [
            ("yue", "佢今日唔得閒，聽日下晝三點先嚟。"),
            ("zh", "请在明天下午三点来，不要上午来。"),
            ("yue", "我唔係話唔去，我係聽日先去。"),
        ]:
            before = len(window.model.items)
            old = [(e.key, e.source, e.target) for e in window.model.items]
            window.direction_box.setCurrentIndex(0 if source == "yue" else 1)
            window.input.setPlainText(text)
            window.translate_button.click()
            until(lambda: window.pending == 0)
            assert window.engine.translator.child is not None
            assert len(window.model.items) == before + 1
            item = window.model.items[-1]
            assert item.source == text and item.target and item.status == "已翻译"
            assert [(e.key, e.source, e.target) for e in window.model.items[:-1]] == old
            report["real_model_cases"].append(
                dict(source=source, text=text, translation=item.target)
            )
        before = [(e.key, e.source, e.target) for e in window.model.items]
        window.stop()
        window.direction_box.setCurrentIndex(1 - window.direction_box.currentIndex())
        assert [(e.key, e.source, e.target) for e in window.model.items] == before
        window.source_box.setCurrentIndex(1)
        assert window.microphone is None
        pcm_before = len(window.player.chunks)
        window.cancel.clear()  # The real Start action clears cancellation too.
        window.listening = True  # State-only test: no device is opened.
        window._buttons()
        assert not window.auto_box.isEnabled()
        assert not window.submit(Request(window.epoch, "speak", text="禁止播报"))
        samples, rate = sf.read(str(ROOT / "models/asr-wenet/test_wavs/yue.wav"), dtype="float32")
        assert window.submit(
            Request(window.epoch, "audio", source="yue", samples=samples, rate=rate, autoplay=True)
        )
        until(lambda: window.pending == 0)
        assert window.model.items[-1].target and len(window.player.chunks) == pcm_before
        window.stop()
        pump(0.4)
        window.grab().save(str(OUT / "translated.png"))
        window.resize(960, 700)
        pump(0.4)
        window.grab().save(str(OUT / "compact.png"))
        assert (
            window.status_label.isVisible()
            and window.status_label.geometry().bottom() < window.centralWidget().height()
        )
        export = OUT / "real-transcript.txt"
        window.write_export(export)
        text = export.read_text(encoding="utf-8-sig")
        assert all(e.source in text and e.target in text for e in window.model.items)
        report.update(
            retained_on_stop_and_direction_change=True,
            system_capture_state_suppresses_speech=True,
            selector_does_not_capture=True,
            export_utf8_verified=True,
        )
        # Synthetic rows below are load fixtures, not generated translations.
        window.resize(1240, 850)
        for i in range(120):
            window.model.append(
                TranscriptEntry(
                    1000 + i,
                    "yue",
                    "zh",
                    source=f"滚动负载测试 {i}：回看时不要跳回底部。",
                    target="这是明确标注的界面测试数据。",
                    status="测试数据",
                )
            )
        pump(1)
        window.view.interrupt()
        bar = window.view.verticalScrollBar()
        bar.setValue(100)
        position = bar.value()
        window._change_transcript(
            lambda: window.model.append(
                TranscriptEntry(5000, "yue", "zh", source="新增负载测试", target="非翻译结果")
            ),
            new=True,
        )
        pump(0.5)
        assert (
            bar.value() == position
            and not window.view.follow_tail
            and window.latest_button.isVisible()
        )
        window.go_latest()
        values = []
        end = time.monotonic() + 0.5
        while time.monotonic() < end:
            app.processEvents()
            values.append(bar.value())
            time.sleep(0.008)
        assert len(set(values)) >= 5 and bar.maximum() - bar.value() <= 2
        assert all(a <= b for a, b in zip(values, values[1:]))
        window._change_transcript(
            lambda: window.model.append(
                TranscriptEntry(
                    5001, "zh", "yue", source="自动跟随负载测试", target="新增行后继续跟随"
                )
            ),
            new=True,
        )
        pump(0.5)
        assert bar.maximum() - bar.value() <= 2 and window.view.follow_tail
        window.view.animate_to(0, 400)
        pump(0.06)
        window.view.interrupt()
        halted = bar.value()
        pump(0.3)
        assert bar.value() == halted and not window.view.follow_tail
        window.view.smooth = False
        window.go_latest()
        assert bar.value() == bar.maximum()
        report.update(
            review_position_preserved=True,
            smooth_animation_distinct_positions=len(set(values)),
            animation_monotonic=True,
            animation_interruptible=True,
            reduced_motion=True,
            append_follows_tail=True,
        )
        report["scroll_input"] = scroll_input_check(window, app, pump)
        # Bind a full retained history, allow batched layout, then measure UI
        # paint work while animating. This is not a display refresh/FPS claim.
        window.model.clear()
        start = time.perf_counter()
        for i in range(10000):
            window.model.append(
                TranscriptEntry(
                    10000 + i,
                    "yue",
                    "zh",
                    source=f"负载测试字幕 {i}，仅用于验证滚动。",
                    target="一万条记录中的测试行，不是模型译文。",
                    status="测试数据",
                )
            )
        insertion = time.perf_counter() - start
        pump(4)
        window.view.interrupt()
        bar.setValue(0)
        pump(0.1)
        window.view.smooth = True
        window.view.paint_times.clear()
        window.view.animate_to(bar.maximum(), 700)
        pump(1)
        paints = list(window.view.paint_times)
        assert len(window.model.items) == 10000 and paints
        report["synthetic_load"] = dict(
            rows=10000,
            insertion_seconds=insertion,
            paint_samples=len(paints),
            paint_p95_ms=float(np.percentile(paints, 95)),
            paint_max_ms=max(paints),
            note="Rendering timings only; does not prove screen FPS or live capture latency",
        )
        report["status"] = "executed"
        report["quality_passed"] = False
        (OUT / "verification.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (OUT / ("verification-" + os.environ["QT_QPA_PLATFORM"] + ".json")).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=True), flush=True)
    finally:
        window.close()
        until(lambda: not window.worker.is_alive(), timeout=40)
        pump(0.1)


if __name__ == "__main__":
    main()
