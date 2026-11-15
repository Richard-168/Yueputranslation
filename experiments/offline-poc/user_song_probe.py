"""Local-only diagnosis of user-supplied audio; never modifies or uploads it."""

import argparse
import hashlib
import json
import threading
import time
from pathlib import Path

import av
import numpy as np
import probe
import soundfile as sf
from desktop_engine import MAX_LIVE_SEGMENT_SECONDS, AudioPlayer, Engine, PlaybackProcessor, Request
from song_probe import qwen

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs/user-song-diagnostics"


def stamp(seconds):
    return f"{int(seconds) // 60:02}:{seconds % 60:05.2f}"


def decode(path):
    if not path.is_file() or path.stat().st_size > 50 * 1024 * 1024:
        raise ValueError("Diagnostic input missing or larger than 50 MiB")
    chunks = []
    total = 0
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        info = dict(
            source_name=path.name,
            bytes=path.stat().st_size,
            original_sample_rate=stream.codec_context.sample_rate,
            original_channels=stream.codec_context.channels,
            codec=stream.codec_context.name,
        )
        resampler = av.AudioResampler(format="fltp", layout="stereo", rate=16000)
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                samples = converted.to_ndarray().T.copy()
                total += len(samples)
                if total > 600 * 16000:
                    raise ValueError("Diagnostic duration cap is 10 minutes")
                chunks.append(samples)
        for converted in resampler.resample(None):
            chunks.append(converted.to_ndarray().T.copy())
    audio = np.concatenate(chunks).astype(np.float32)
    assert np.isfinite(audio).all()
    info.update(
        decoded_seconds=len(audio) / 16000,
        left_rms=float(np.sqrt(np.mean(audio[:, 0] ** 2))),
        right_rms=float(np.sqrt(np.mean(audio[:, 1] ** 2))),
        mono_rms=float(np.sqrt(np.mean(audio.mean(axis=1) ** 2))),
        channel_correlation=float(np.corrcoef(audio.T)[0, 1]),
        peak=float(np.max(np.abs(audio))),
    )
    return audio, info


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    parser.add_argument("--verify-lexical-gate", action="store_true")
    args = parser.parse_args()
    if args.verify_lexical_gate:
        verify_lexical_gate()
        return
    if args.input is None:
        parser.error("--input is required for an audio comparison")
    OUT.mkdir(exist_ok=True)
    original_hash = hashlib.sha256(args.input.read_bytes()).hexdigest()
    audio, info = decode(args.input)
    info["sha256"] = original_hash
    mono = audio.mean(axis=1)
    collected = []
    position = [0.0]
    processor = PlaybackProcessor(16000, 2, lambda s: collected.append((position[0], s.copy())))
    for start in range(0, len(audio), 512):
        position[0] = min(start + 512, len(audio)) / 16000
        processor.feed(audio[start : start + 512])
    processor.flush()
    assert processor.input_frames == len(audio) and processor.output_frames == len(audio)
    assert max(len(s) / 16000 for _, s in collected) <= MAX_LIVE_SEGMENT_SECONDS + 0.032
    engine = Engine()
    engine.asr = probe.recognizer()
    current = []
    for index, (emitted, samples) in enumerate(collected):
        events = []
        tick = time.perf_counter()
        row = dict(index=index, submitted_audio_time=emitted, audio_seconds=len(samples) / 16000)
        try:
            row["text"] = engine.recognize(
                samples, 16000, threading.Event(), "yue", lambda k, v: events.append((k, v))
            )
            row["nonlexical"] = not any(char.isalnum() for char in row["text"])
        except ValueError as exc:
            row["error"] = str(exc)
        row["seconds"] = time.perf_counter() - tick
        row["recognition"] = next((v for k, v in events if k == "recognition"), None)
        current.append(row)
    cases = []
    # Audio given to both models is identical. Keep live VAD cuts separate from
    # wider fixed windows so extra context is not confused with model quality.
    for index in (0, 1, 2, 3, 5, 6, 7, 10, 20, 30, 38):
        if index < len(collected):
            emitted, samples = collected[index]
            cases.append(
                (
                    dict(
                        kind="live-segment",
                        index=index,
                        submitted_audio_time=emitted,
                        audio_seconds=len(samples) / 16000,
                    ),
                    samples,
                )
            )
    for start, duration in (
        (0, 12),
        (24, 8),
        (28, 8),
        (30, 12),
        (60, 8),
        (90, 8),
        (118, 8),
        (176, 8),
        (208, 8),
    ):
        if start + duration <= len(mono) / 16000:
            cases.append(
                (
                    dict(kind="fixed-window", start=start, audio_seconds=duration),
                    mono[start * 16000 : (start + duration) * 16000],
                )
            )
    compared = []
    for number, (meta, samples) in enumerate(cases):
        path = OUT / f"case-{number:02}.wav"
        sf.write(str(path), samples, 16000, subtype="PCM_16")
        events = []
        tick = time.perf_counter()
        try:
            previous = dict(
                text=engine.recognize(
                    samples, 16000, threading.Event(), "yue", lambda k, v: events.append((k, v))
                )
            )
        except ValueError as exc:
            previous = dict(error=str(exc), text="")
        previous["seconds"] = time.perf_counter() - tick
        candidate = qwen(path, size="1.7B")
        row = {**meta, "current": previous, "qwen_1_7b": candidate}
        if (
            meta["kind"] == "fixed-window"
            and meta["start"] in (30, 90, 176)
            and 0 < len(candidate["text"]) <= 120
        ):
            tick = time.perf_counter()
            row["candidate_translation"] = engine.translate(
                candidate["text"], "yue", threading.Event()
            )
            row["translation_seconds"] = time.perf_counter() - tick
        compared.append(row)
        # Checkpoint after each real native process; do not print whole lyrics.
        (OUT / "comparison-progress.json").write_text(
            json.dumps(compared, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                dict(
                    case=number + 1,
                    total=len(cases),
                    kind=meta["kind"],
                    audio_seconds=meta["audio_seconds"],
                    current_seconds=previous["seconds"],
                    candidate_seconds=candidate["seconds"],
                    candidate_language=candidate["language"],
                    candidate_characters=len(candidate["text"]),
                )
            ),
            flush=True,
        )
    assert hashlib.sha256(args.input.read_bytes()).hexdigest() == original_hash
    report = dict(
        source=info,
        source_unchanged=True,
        audio_uploaded=False,
        full_current_pipeline=current,
        comparison=compared,
        native_asr_p50_seconds=float(np.median([r["seconds"] for r in current])),
        qwen_1_7b_p50_seconds=float(np.median([r["qwen_1_7b"]["seconds"] for r in compared])),
        maximum_live_segment_seconds=max(len(s) / 16000 for _, s in collected),
        first_segment_submission_audio_time=collected[0][0],
        exact_lyrics_ground_truth="No manually aligned reference; do not report accuracy percentage",
        scope="Same user file, file replay only; native process loading included; no live speaker/microphone capture",
        default_model_changed=False,
        song_quality_passed=False,
    )
    (OUT / "comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# 用户音源诊断：一生不变",
        "",
        f"音频时长 {info['decoded_seconds']:.2f} 秒；原文件未修改，没有上传。",
        f"声道相关系数 {info['channel_correlation']:.3f}；不能仅凭这个数值判断人声可懂度。",
        f"当前流程共 {len(current)} 个片段，最长 {report['maximum_live_segment_seconds']:.3f} 秒。",
        "首段提交的音频位置包含前奏／等待人声，不能当成模型计算时间。",
        "没有人工逐字时间对齐的歌词真值，下表供同音源人工核对，不提供准确率。",
        "两个模型使用相同 WAV；固定窗口与软件实际分段分别标注。Qwen 耗时包含每次加载，不能当作常驻模型速度。",
        "",
        "| 输入位置／类型 | 现有 WenetSpeech-Yue U2++ | Qwen3-ASR-1.7B | 识别耗时（现有／候选） |",
        "| --- | --- | --- | --- |",
    ]
    for row in compared:
        label = (
            f"软件段 #{row['index']}，{stamp(row['submitted_audio_time'])} 提交，{row['audio_seconds']:.2f}秒"
            if row["kind"] == "live-segment"
            else f"固定窗口 {stamp(row['start'])}–{stamp(row['start'] + row['audio_seconds'])}"
        )

        def clean(text):
            return text.replace("|", "｜").replace("\n", " ")

        lines.append(
            f"| {label} | {clean(row['current']['text']) or '（无有效文本）'} | {clean(row['qwen_1_7b']['text']) or '（无文本）'} | {row['current']['seconds']:.2f} / {row['qwen_1_7b']['seconds']:.2f} 秒 |"
        )
    lines.extend(
        [
            "",
            "当前默认模型保持不变。更大的模型能否达到所需歌词准确性、流式延迟，仍需核对；这不是整首歌曲已通过验收的声明。",
        ]
    )
    (OUT / "对比报告.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "completed": True,
                "full_live_segments": len(current),
                "same_audio_cases": len(compared),
                "current_asr_p50": report["native_asr_p50_seconds"],
                "qwen_asr_p50": report["qwen_1_7b_p50_seconds"],
                "source_unchanged": True,
                "default_model_changed": False,
                "quality_passed": False,
            }
        )
    )


def verify_lexical_gate():
    baseline = json.loads(
        (OUT / "comparison-before-lexical-check.json").read_text(encoding="utf-8")
    )
    cases = [
        i
        for i, row in enumerate(baseline["comparison"])
        if row["current"]["text"] and not any(c.isalnum() for c in row["current"]["text"])
    ]
    assert cases
    engine = Engine()
    engine.asr = probe.recognizer()
    errors = []
    player = AudioPlayer(errors.append, muted=True)
    rejected = []
    try:
        for index in cases:
            events = []
            try:
                engine.process(
                    Request(
                        1,
                        "file",
                        source="yue",
                        path=str(OUT / f"case-{index:02}.wav"),
                        autoplay=False,
                    ),
                    threading.Event(),
                    player,
                    lambda k, v: events.append((k, v)),
                )
                raise AssertionError("Nonlexical recognition reached translation")
            except ValueError as exc:
                assert "有效的人声文字" in str(exc)
            assert not any(k in {"source", "translation", "first_audio"} for k, v in events)
            rejected.append(index)
        positive_languages = []
        for fixture, source in (("yue", "yue"), ("zh", "zh"), ("en", "zh")):
            samples, rate = sf.read(
                str(ROOT / f"models/asr-wenet/test_wavs/{fixture}.wav"), dtype="float32"
            )
            positive = engine.recognize(
                samples, rate, threading.Event(), source, lambda *args: None
            )
            assert positive and any(c.isalnum() for c in positive)
            positive_languages.append(fixture)
        result = dict(
            status="executed",
            actual_user_audio_cases_rejected=rejected,
            rejected_before_translation=True,
            ordinary_languages_retained=positive_languages,
            scope="Real offline ASR/job path; no microphone/speaker activation",
            errors=errors,
        )
        (OUT / "lexical-gate-verification.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        print(json.dumps(result))
    finally:
        player.close()


if __name__ == "__main__":
    main()
