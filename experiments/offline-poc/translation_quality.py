"""T4 prompt comparison on fixed synthetic fixtures, not a production translator.

Hypothesis: upstream terminology hints and explicit target register improve the
small HY model without output substitutions. Time box: 10 minutes, 20s per call.
Checks screen a few stated facts only; passing is not a translation accuracy score.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import subprocess
import time
import unicodedata
from pathlib import Path

import probe  # Reuse the experiment's Python external-network denial.

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "outputs" / "quality-v2"
MODEL = ROOT / "models/hymt/HY-MT1.5-1.8B-Q4_K_M.gguf"
MODEL_ID = "hymt15"
MODEL_SOURCE = "tencent/HY-MT1.5-1.8B-GGUF@265b2e615a7dc9b06c435dc878829ad99a512ba2"
EXECUTABLE = ROOT / "runtime/llama-b12314/llama-completion.exe"
TERMS = {
    "zh": [
        ("下晝", "下午"),
        ("朝早", "早上"),
        ("聽日", "明天"),
        ("噚日", "昨天"),
        ("後日", "后天"),
        ("唔使", "不用"),
        ("唔係", "不是"),
        ("未", "还没"),
        ("你哋", "你们"),
        ("我哋", "我们"),
        ("佢哋", "他们"),
        ("蚊", "元"),
    ],
    "yue": [
        ("下午", "下晝"),
        ("早上", "朝早"),
        ("明天", "聽日"),
        ("昨天", "噚日"),
        ("后天", "後日"),
        ("不用", "唔使"),
        ("不是", "唔係"),
        ("还没", "仲未"),
        ("你们", "你哋"),
        ("我们", "我哋"),
        ("他们", "佢哋"),
        ("元", "蚊"),
    ],
}

# Each pair's required regexes describe semantic probes, not exact translations.
# Examples in the glossary are words only. No fixture sentence or expected full
# translation is inserted in the inference prompt. Both profiles see the same cases.
PAIRS = [
    (
        "dev-time",
        "development",
        "佢今日唔得閒，聽日下晝三點先嚟。",
        "他今天没空，明天下午三点才来。",
        ["今天|今日", "明天|明日", "下午|午后|午後", "三[点點]|3[点點]|15[：:]00"],
        ["今日|今天", "聽日|听日|明天|明日", "下晝|下昼|晏晝|晏昼", "三[点點]|3[点點]|15[：:]00"],
    ),
    (
        "dev-double-negative",
        "development",
        "我唔係話唔去，我係聽日先去。",
        "我不是说不去，我是明天才去。",
        ["不是.*不去|并非.*不去|並非.*不去", "明天|明日"],
        ["唔[係系].*唔去|唔[係系].*唔想去", "聽日|听日|明天|明日"],
    ),
    (
        "dev-amount",
        "development",
        "唔該，兩個人一共八十八蚊，唔係八百八十八。",
        "两个人一共八十八元，不是八百八十八元。",
        ["八十八|(?<![0-9])88(?![0-9])", "八百八十八|(?<![0-9])888(?![0-9])", "不是|并非|並非"],
        ["八十八|(?<![0-9])88(?![0-9])", "八百八十八|(?<![0-9])888(?![0-9])", "唔[係系]"],
    ),
    (
        "dev-pronouns",
        "development",
        "我未食飯，唔使等我，你哋食先。",
        "我还没吃饭，不用等我，你们先吃。",
        ["还没|還沒|尚未|没有|沒有", "不用等我|不必等我|不需要等我", "你们|你們"],
        ["未|冇", "唔使等我|唔使等我", "你哋"],
    ),
    (
        "dev-tomorrow-morning",
        "development",
        "聽日朝早七點，唔係下晝七點。",
        "明天早上七点，不是下午七点。",
        ["明天|明日", "早上|早晨|上午|清晨", "下午|午后|午後", "不是|并非|並非"],
        [
            "聽日|听日|聽朝|听朝|明天|明日",
            "朝早|早上|早晨|聽朝|听朝",
            "下晝|下昼|晏晝|晏昼",
            "唔[係系]",
        ],
    ),
    (
        "dev-contrast",
        "development",
        "係我哋去，唔係佢哋去。",
        "是我们去，不是他们去。",
        ["我们|我們", "不是|并非|並非", "他们|他們"],
        ["我哋", "唔[係系]", "佢哋"],
    ),
    (
        "holdout-afternoon",
        "holdout",
        "星期五下晝四點開會，唔好朝早嚟。",
        "星期五下午四点开会，不要早上来。",
        ["星期五|周五|週五", "下午|午后|午後", "四[点點]|4[点點]|16[：:]00", "不要|别|別"],
        [
            "星期五|禮拜五|礼拜五|周五|週五",
            "下晝|下昼|晏晝|晏昼",
            "四[点點]|4[点點]|16[：:]00",
            "唔好",
        ],
    ),
    (
        "holdout-yesterday",
        "holdout",
        "我噚日下晝已經畀咗錢，唔使再畀。",
        "我昨天下午已经付过钱，不用再付。",
        ["昨天|昨日", "下午|午后|午後", "不用|不必|不需要"],
        ["噚日|尋日|寻日|昨日|昨天", "下晝|下昼|晏晝|晏昼", "唔使"],
    ),
    (
        "holdout-day-after",
        "holdout",
        "後日朝早八點半見，唔係聽日。",
        "后天早上八点半见，不是明天。",
        ["后天|後天|后日|後日", "早上|上午|早晨|清晨", "八[点點]半|8[：:]30", "不是|并非|並非"],
        ["後日|后日|後天|后天", "朝早|早上|早晨", "八[点點]半|8[：:]30", "唔[係系]"],
    ),
    (
        "holdout-decimal",
        "holdout",
        "一共42.5蚊，唔係425蚊。",
        "一共42.5元，不是425元。",
        ["42[.．]5|四十二[点點]五", "(?<![0-9])425(?![0-9])|四百二十五", "不是|并非|並非"],
        ["42[.．]5|四十二[点點]五", "(?<![0-9])425(?![0-9])|四百二十五", "唔[係系]"],
    ),
    (
        "holdout-phone-digits",
        "holdout",
        "號碼係2038，唔係2308。",
        "号码是2038，不是2308。",
        [
            "2038|二零三八|二千零三十八|两千零三十八|兩千零三十八",
            "2308|二三零八|二千三百零八|两千三百零八|兩千三百零八",
            "不是|并非|並非",
        ],
        ["2038|二零三八|二千零三十八", "2308|二三零八|二千三百零八", "唔[係系]"],
    ),
    (
        "holdout-wait-for-them",
        "holdout",
        "我哋等你哋，唔係等佢哋。",
        "我们等你们，不是在等他们。",
        ["我们|我們", "你们|你們", "他们|他們", "不是|并非|並非"],
        ["我哋", "你哋", "佢哋", "唔[係系]"],
    ),
    (
        "holdout-not-yet",
        "holdout",
        "佢仲未返嚟，唔好閂門。",
        "他还没回来，不要关门。",
        ["还没|還沒|尚未|没有|沒有", "不要|别|別"],
        ["未|冇", "唔好"],
    ),
    (
        "holdout-three-not-two",
        "holdout",
        "我要三張飛，唔係兩張。",
        "我要三张票，不是两张。",
        ["三[张張]|(?<![0-9])3[张張]", "[两兩二][张張]|(?<![0-9])2[张張]", "不是|并非|並非"],
        ["三[張张]|(?<![0-9])3[張张]", "[兩两二][張张]|(?<![0-9])2[張张]", "唔[係系]"],
    ),
    (
        "holdout-permission",
        "holdout",
        "你唔使而家走，可以食完先走。",
        "你不用现在走，可以吃完再走。",
        ["不用|不必|不需要", "可以"],
        ["唔使", "可以"],
    ),
    (
        "holdout-tonight",
        "holdout",
        "今晚九點喺門口等我，唔係聽晚。",
        "今晚九点在门口等我，不是明晚。",
        ["今晚|今天晚上|今日晚上", "九[点點]|9[点點]|21[：:]00", "不是|并非|並非", "明晚|明天晚上"],
        ["今晚", "九[点點]|9[点點]|21[：:]00", "唔[係系]", "聽晚|听晚|明晚"],
    ),
]


def fixture_cases():
    cases = []
    for name, split, yue, zh, zh_checks, yue_checks in PAIRS:
        cases.append(
            dict(
                id=name + "-to-zh",
                split=split,
                source="yue",
                target="zh",
                input=yue,
                require=zh_checks,
            )
        )
        cases.append(
            dict(
                id=name + "-to-yue",
                split=split,
                source="zh",
                target="yue",
                input=zh,
                require=yue_checks,
            )
        )
    return cases


def build_prompt(case, profile):
    target = "中文" if case["target"] == "zh" else "粤语"
    source = case["input"]
    matched = []
    if profile == "guided":
        matched = [(s, t) for s, t in TERMS[case["target"]] if s in source]
        style = (
            "自然普通话（简体中文）" if case["target"] == "zh" else "自然香港粤语口语（繁體中文）"
        )
        user = ""
        if matched:
            user += "参考下面的翻译：\n" + "\n".join(f"{s} 翻译成 {t}" for s, t in matched) + "\n\n"
        user += f"将以下文本翻译为{target}，注意只需要输出翻译后的结果，不要额外解释。译文应使用{style}，保留原文的时间、否定、数字及人称：\n\n{source}"
    elif profile == "directed":
        source_name = "粤语口语" if case["source"] == "yue" else "普通话"
        target_name = "普通话（简体中文）" if case["target"] == "zh" else "粤语口语（繁體中文）"
        user = f"将以下{source_name}翻译为{target_name}，注意只需要输出翻译后的结果，不要额外解释：\n\n{source}"
    else:
        user = f"将以下文本翻译为{target}，注意只需要输出翻译后的结果，不要额外解释：\n\n{source}"
    return f"<｜hy_begin▁of▁sentence｜><｜hy_User｜>{user}<｜hy_Assistant｜>", matched


def screen(case, output):
    normalized = re.sub(r"\s+", "", unicodedata.normalize("NFKC", output))
    # '下午' also means afternoon when used in Cantonese. A semantic screen
    # must not reject a correct time merely for using a more formal synonym.
    patterns = [
        p.replace("下晝|下昼|晏晝|晏昼", "下晝|下昼|晏晝|晏昼|下午|午后|午後")
        for p in case["require"]
    ]
    missing = [pattern for pattern in patterns if re.search(pattern, normalized) is None]
    issues = []
    if "翻译成" in normalized or "翻譯成" in normalized:
        if "翻译成" not in case["input"] and "翻譯成" not in case["input"]:
            issues.append("terminology prompt echoed into translation")
    if re.search("出发|出發", normalized) and not re.search("出发|出發|起程", case["input"]):
        issues.append("added departure action absent from source")
    return dict(
        required_facts_present=not missing,
        missing_patterns=missing,
        obvious_issues=issues,
        screen_passed=not missing and not issues,
        limitation="lexical fact screen; does not prove sentence meaning, fluency or audio quality",
    )


def infer(case, profile):
    prompt, matched = build_prompt(case, profile)
    prompt_path = OUTPUT / f"{MODEL_ID}-{profile}-{case['id']}.txt"
    prompt_path.write_text(prompt, encoding="utf-8")
    command = [
        str(EXECUTABLE),
        "-m",
        str(MODEL),
        "--offline",
        "--no-conversation",
        "--no-display-prompt",
        "--simple-io",
        "--color",
        "off",
        "--ctx-size",
        "2048",
        "--threads",
        "4",
        "--n-gpu-layers",
        "0",
        "--no-warmup",
        "--seed",
        "42",
        "--temp",
        "0.1",
        "-n",
        "160",
        "-f",
        str(prompt_path),
    ]
    if profile == "official":
        command[command.index("--temp") + 1] = "0.7"
        command.extend(["--top-k", "20", "--top-p", "0.6", "--repeat-penalty", "1.05"])
    tick = time.perf_counter()
    result = subprocess.run(
        command,
        input="",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    (OUTPUT / f"{MODEL_ID}-{profile}-{case['id']}.log").write_text(result.stderr, encoding="utf-8")
    text = re.sub(r"\s*\[end of text\]\s*$", "", result.stdout).strip()
    if result.returncode != 0 or not text:
        raise RuntimeError(f"Inference failed for {case['id']}: exit {result.returncode}")
    return dict(
        **case,
        profile=profile,
        output=text,
        process_seconds=time.perf_counter() - tick,
        matched_terms=matched,
        prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        checks=screen(case, text),
    )


def main():
    global MODEL, MODEL_ID, MODEL_SOURCE
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["hymt15", "hymt2"], default="hymt15")
    parser.add_argument(
        "--profile", choices=["baseline", "guided", "official", "directed", "both"], default="both"
    )
    parser.add_argument("--split", choices=["development", "holdout", "all"], default="all")
    args = parser.parse_args()
    MODEL_ID = args.model
    if MODEL_ID == "hymt2":
        MODEL = ROOT / "models/hymt2/Hy-MT2-1.8B-Q4_K_M.gguf"
        MODEL_SOURCE = "tencent/Hy-MT2-1.8B-GGUF@a0c709d9fac510f2c807aa3af52872340dc37a4a"
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fixtures = fixture_cases()
    cases = [c for c in fixtures if args.split == "all" or c["split"] == args.split]
    fixture_blob = json.dumps(fixtures, ensure_ascii=False, sort_keys=True, indent=2)
    digest = hashlib.sha256(fixture_blob.encode()).hexdigest()
    fixture_file = f"fixtures-{digest[:12]}.json"
    (OUTPUT / fixture_file).write_text(fixture_blob, encoding="utf-8", newline="\n")
    profiles = ["baseline", "guided"] if args.profile == "both" else [args.profile]
    rows = []
    started = time.monotonic()
    report_path = OUTPUT / f"comparison-{MODEL_ID}-{args.profile}-{args.split}.json"
    report = dict(
        scope="T4, synthetic textual fact screen; not release acceptance",
        fixture_sha256=hashlib.sha256(fixture_blob.encode()).hexdigest(),
        fixture_file=fixture_file,
        model=MODEL_SOURCE,
        quantization="Q4_K_M",
        parameters=dict(
            threads=4,
            seed=42,
            temperature=0.1,
            max_tokens=160,
            official_override=dict(temperature=0.7, top_k=20, top_p=0.6, repeat_penalty=1.05),
        ),
        screen_version=3,
        output_rewriting=False,
        rows=rows,
        quality_passed=False,
    )
    try:
        for profile in profiles:
            for case in cases:
                if time.monotonic() - started > 600:
                    raise TimeoutError("10-minute experiment time box exceeded")
                row = infer(case, profile)
                rows.append(row)
                report_path.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(
                    json.dumps(
                        {k: row[k] for k in ["id", "profile", "input", "output", "checks"]},
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
        report["summary"] = []
        for profile in profiles:
            for split in ("development", "holdout"):
                selected = [r for r in rows if r["profile"] == profile and r["split"] == split]
                if selected:
                    report["summary"].append(
                        dict(
                            profile=profile,
                            split=split,
                            cases=len(selected),
                            flagged=sum(not r["checks"]["screen_passed"] for r in selected),
                            median_process_seconds=statistics.median(
                                r["process_seconds"] for r in selected
                            ),
                        )
                    )
        report["status"] = "executed"
    except Exception as exc:
        report.update(status="error", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        report.update(
            elapsed_seconds=time.monotonic() - started,
            blocked_external_socket_attempts=probe.OUTBOUND_ATTEMPTS,
        )
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report.get("summary", []), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
