"""T4 number-rendering contrast for Mandarin TTS; no automatic context classifier.

Fixture modes are explicit annotations. Amounts use cardinal readings; identifiers
use individual digits. Original translation/display strings are never rewritten.
This experiment cannot be used as an unrestricted production text normalizer.
"""

from __future__ import annotations

import importlib.metadata
import json
import re
import time
from decimal import Decimal
from pathlib import Path

import cn2an
import probe

from yuepu_translate.numbers import spoken_numbers

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "outputs/quality-v2"

CASES = [
    dict(
        id="decimal",
        split="reproduction",
        mode="amount",
        text="一共42.5元，不是425元。",
        expected=["42.5", "425"],
    ),
    dict(
        id="digits",
        split="reproduction",
        mode="identifier",
        text="号码是2038，不是2308。",
        expected=["2038", "2308"],
    ),
    dict(
        id="new-decimal",
        split="new-tts-fixture",
        mode="amount",
        text="一共105.05元，不是150.50元。",
        expected=["105.05", "150.50"],
    ),
    dict(
        id="new-leading-zero",
        split="new-tts-fixture",
        mode="identifier",
        text="编号是0076，不是0760。",
        expected=["0076", "0760"],
    ),
]


def observed_numbers(transcript, mode):
    # This parser is only for these controlled fixtures, not a generic ASR scorer.
    transcript = transcript.replace("一共", "共")
    groups = re.findall(
        r"[0-9]+(?:\.[0-9]+)?|[零〇一二两兩三四五六七八九十百千万萬亿億点點]+", transcript
    )
    values = []
    for token in groups:
        try:
            if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", token):
                values.append(token)
            elif mode == "identifier" and not any(c in token for c in "十百千万萬亿億"):
                values.append(cn2an.cn2an(token, "direct"))
            else:
                values.append(str(cn2an.cn2an(token, "smart")))
        except ValueError:
            values.append("unparsed:" + token)
    return values


def same_values(observed, expected, mode):
    if len(observed) != len(expected):
        return False
    if mode == "identifier":
        return observed == expected
    try:
        return all(Decimal(a) == Decimal(b) for a, b in zip(observed, expected))
    except Exception:
        return False


def main():
    OUTPUT.mkdir(exist_ok=True)
    report_path = OUTPUT / "mandarin-number-contrast.json"
    report = dict(
        scope="four explicitly typed synthetic Mandarin TTS fixtures; no free-text normalization contract",
        cn2an_version=importlib.metadata.version("cn2an"),
        context_detection="not implemented; fixture annotations only",
        human_listening="unverified",
        quality_passed=False,
        samples=[],
    )
    started = time.perf_counter()
    try:
        tts = probe.mandarin_engine()
        for case in CASES:
            rendered, edits = spoken_numbers(case["text"], case["mode"])
            for variant, text in [("raw", case["text"]), ("rendered", rendered)]:
                audio = probe.synthesize(tts, "zh", text, f"number-{case['id']}-{variant}")
                report["samples"].append(
                    dict(
                        **case,
                        variant=variant,
                        tts_text=text,
                        edits=edits if variant == "rendered" else [],
                        audio=audio,
                    )
                )
        asr = probe.recognizer()
        for row in report["samples"]:
            row["roundtrip"] = probe.transcribe(asr, probe.OUTPUT / row["audio"]["file"])
            row["observed_numbers"] = observed_numbers(row["roundtrip"]["text"], row["mode"])
            row["number_screen_passed"] = same_values(
                row["observed_numbers"], row["expected"], row["mode"]
            )
            print(
                json.dumps(
                    {
                        k: row[k]
                        for k in [
                            "id",
                            "variant",
                            "tts_text",
                            "roundtrip",
                            "observed_numbers",
                            "number_screen_passed",
                        ]
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
