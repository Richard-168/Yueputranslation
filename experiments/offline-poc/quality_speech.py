"""T4: feed selected MT2 outputs to real TTS, then independently transcribe.

Round-trip mismatches need human listening; they cannot identify ASR vs TTS errors.
OpenCC changes character forms only. Raw translations are retained separately.
"""

from __future__ import annotations

import gc
import importlib.metadata
import json
import time
from pathlib import Path

import opencc
import probe
import translation_quality as quality

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "outputs/quality-v2"
SELECTED = {
    f"{name}-to-{language}"
    for name in ["dev-time", "dev-double-negative", "holdout-decimal", "holdout-phone-digits"]
    for language in ("zh", "yue")
}


def main():
    report_path = OUTPUT / "speech-mt2.json"
    source_path = OUTPUT / "comparison-hymt2-official-all.json"
    data = json.loads(source_path.read_text(encoding="utf-8"))
    cases = [row for row in data["rows"] if row["id"] in SELECTED]
    if len(cases) != 8 or data.get("status") != "executed":
        raise RuntimeError("Expected eight executed MT2 cases")
    report = dict(
        scope="text-fixture MT2-to-TTS plus ASR back-transcription; not microphone or streaming",
        source_file=source_path.name,
        opencc_version=importlib.metadata.version("OpenCC"),
        character_conversion_only=True,
        human_listening="unverified",
        samples=[],
        quality_passed=False,
    )
    started = time.perf_counter()
    try:
        for language in ("zh", "yue"):
            tick = time.perf_counter()
            engine = probe.canto_engine() if language == "yue" else probe.mandarin_engine()
            load_seconds = time.perf_counter() - tick
            converter = opencc.OpenCC("s2t" if language == "yue" else "t2s")
            for row in cases:
                if row["target"] != language:
                    continue
                text = converter.convert(row["output"])
                item = probe.synthesize(engine, language, text, "mt2-" + row["id"])
                item.update(
                    id=row["id"],
                    source_input=row["input"],
                    raw_translation=row["output"],
                    target=language,
                    model_load_seconds=load_seconds,
                )
                report["samples"].append(item)
                report_path.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(json.dumps(item, ensure_ascii=False), flush=True)
            del engine
            gc.collect()
        engine = probe.recognizer()
        by_id = {r["id"]: r for r in cases}
        for item in report["samples"]:
            item["asr_roundtrip"] = probe.transcribe(engine, probe.OUTPUT / item["file"])
            item["roundtrip_screen"] = quality.screen(
                by_id[item["id"]], item["asr_roundtrip"]["text"]
            )
            print(
                json.dumps(
                    {
                        "id": item["id"],
                        "expected_text": item["input"],
                        "roundtrip": item["asr_roundtrip"]["text"],
                        "screen": item["roundtrip_screen"],
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        report["status"] = "executed"
    except Exception as exc:
        report.update(status="error", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        report.update(
            elapsed_seconds=time.perf_counter() - started,
            blocked_external_socket_attempts=probe.OUTBOUND_ATTEMPTS,
        )
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
