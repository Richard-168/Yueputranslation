"""Verify saved experiment artifacts, without treating execution as accuracy."""

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "outputs/quality-v2"


def main():
    scripts = [
        "prepare_models.py",
        "probe.py",
        "translation_quality.py",
        "quality_speech.py",
        "mandarin_number_probe.py",
        "cantonese_stream_probe.py",
    ]
    for name in scripts:
        ast.parse((ROOT / name).read_text(encoding="utf-8"))
    r = json.loads((OUTPUT / "comparison-hymt2-official-all.json").read_text(encoding="utf-8"))
    assert r["status"] == "executed" and len(r["rows"]) == 32
    assert sum(x["split"] == "development" for x in r["rows"]) == 12
    assert sum(x["split"] == "holdout" for x in r["rows"]) == 20
    assert (
        hashlib.sha256((OUTPUT / r["fixture_file"]).read_bytes()).hexdigest() == r["fixture_sha256"]
    )
    assert len({x["id"] for x in r["rows"]}) == 32
    by_id = {x["id"]: x for x in r["rows"]}
    assert "下午" in by_id["dev-time-to-zh"]["output"]
    assert "下午" in by_id["holdout-yesterday-to-zh"]["output"]
    assert r["quality_passed"] is False
    s = json.loads((OUTPUT / "speech-mt2.json").read_text(encoding="utf-8"))
    assert s["status"] == "executed" and len(s["samples"]) == 8
    n = json.loads((OUTPUT / "mandarin-number-contrast.json").read_text(encoding="utf-8"))
    assert n["status"] == "executed" and len(n["samples"]) == 8
    rendered = {x["id"]: x for x in n["samples"] if x["variant"] == "rendered"}
    assert (
        rendered["decimal"]["number_screen_passed"]
        and rendered["new-decimal"]["number_screen_passed"]
    )
    assert not rendered["digits"]["number_screen_passed"]
    t = json.loads((OUTPUT / "canto-stream-4.json").read_text(encoding="utf-8"))
    assert t["status"] == "executed" and t["stream"]["chunks"] > 1
    assert (
        t["stream"]["full_decode_same_length"]
        and t["stream"]["max_abs_difference_from_full_decode"] < 1e-5
    )
    assert t["stream"]["first_non_silent_pcm_seconds"] < t["stream"]["total_generation_seconds"]
    paths = {ROOT / "outputs" / x["file"] for x in s["samples"]}
    paths.update(ROOT / "outputs" / x["audio"]["file"] for x in n["samples"])
    paths.add(ROOT / "outputs" / t["stream"]["file"])
    for path in paths:
        audio, rate = sf.read(str(path), dtype="float32")
        assert (
            rate > 0
            and len(audio) > 0
            and np.isfinite(audio).all()
            and float(np.max(np.abs(audio))) > 0.0001
        ), path
    for script, args in [
        ("translation_quality.py", ["--model", "not-a-model"]),
        ("cantonese_stream_probe.py", ["--frames-per-chunk", "3"]),
    ]:
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-B", str(ROOT / script), *args],
            capture_output=True,
            encoding="utf-8",
            timeout=10,
        )
        assert result.returncode == 2, (script, result.returncode)
    verification = dict(
        scope="second-round isolated Windows exploration; not production acceptance",
        scripts_parsed=len(scripts),
        mt2_cases=32,
        development_cases=12,
        holdout_cases=20,
        fixture_digest_verified=True,
        speech_inputs=8,
        numeric_contrasts=8,
        non_silent_audio_files_checked=len(paths),
        stream_vs_full_decode_max_difference=t["stream"]["max_abs_difference_from_full_decode"],
        first_non_silent_pcm_seconds=t["stream"]["first_non_silent_pcm_seconds"],
        invalid_cli_inputs_rejected=True,
        quality_passed=False,
        remaining=[
            "manual listening for identifier digits",
            "semantic simplification and modal nuance",
            "live audio playback and microphone",
            "Android implementation and Xiaomi verification",
        ],
    )
    (OUTPUT / "verification.json").write_text(
        json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(verification, ensure_ascii=False))


if __name__ == "__main__":
    main()
