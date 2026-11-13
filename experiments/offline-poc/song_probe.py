"""Compare actual ASR on a bounded public preview; no lyrics in console output."""

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

import numpy as np
import probe
import soundfile as sf
from desktop_engine import MAX_LIVE_SEGMENT_SECONDS, PlaybackProcessor

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs/song-diagnostics"


def qwen(path, size="0.6B", force_cantonese=False):
    if size not in {"0.6B", "1.7B"}:
        raise ValueError("Unknown diagnostic ASR size")
    directory = "song-asr" if size == "0.6B" else "song-asr-large"
    command = [
        str(ROOT / "runtime/llama-b12314/llama-mtmd-cli.exe"),
        "-m",
        str(ROOT / f"models/{directory}/Qwen3-ASR-{size}-Q8_0.gguf"),
        "--mmproj",
        str(ROOT / f"models/{directory}/mmproj-Qwen3-ASR-{size}-Q8_0.gguf"),
        "--audio",
        str(path),
        "-p",
        " ",
        "-sys",
        "",
        "--offline",
        "--no-mmproj-offload",
        "-ngl",
        "0",
        "-t",
        "4",
        "-c",
        "2048",
        "-n",
        "192",
        "--temp",
        "0",
        "--no-warmup",
    ]
    if force_cantonese:
        command.extend(
            [
                "--jinja",
                "--chat-template",
                (ROOT / "force_cantonese_asr.jinja").read_text(encoding="utf-8"),
            ]
        )
    started = time.perf_counter()
    result = subprocess.run(
        command,
        input="",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode:
        raise RuntimeError("Song ASR process failed: " + result.stderr[-500:])
    if force_cantonese:
        return dict(
            language="Cantonese",
            language_mode="forced-cantonese",
            text=result.stdout.strip(),
            seconds=time.perf_counter() - started,
        )
    matched = re.fullmatch(r"\s*language\s+([^<\n]+)<asr_text>(.*?)\s*", result.stdout, re.S)
    if not matched:
        raise RuntimeError("Invalid song ASR output: " + repr(result.stdout[:200]))
    return dict(
        language=matched[1].strip(), text=matched[2].strip(), seconds=time.perf_counter() - started
    )


def main():
    audio, rate = sf.read(str(OUT / "apple-preview.wav"), dtype="float32")
    records = []
    engines = {lang: probe.recognizer(lang) for lang in ("", "yue", "zh")}
    # Reproduce current device-VAD cut points by replaying only the preview PCM.
    segmented = []
    position = [0.0]
    processor = PlaybackProcessor(
        rate, 1, lambda samples: segmented.append((position[0], samples.copy()))
    )
    padded = np.concatenate([audio, np.zeros(16000, dtype=np.float32)])
    for start in range(0, len(padded), 512):
        position[0] = min(start + 512, len(padded)) / rate
        processor.feed(padded[start : start + 512, None])
    for index, (emitted, samples) in enumerate(segmented):
        row = dict(
            kind="current-vad",
            index=index,
            emitted_audio_second=emitted,
            audio_seconds=len(samples) / rate,
            sensevoice={},
        )
        for lang, engine in engines.items():
            stream = engine.create_stream()
            stream.accept_waveform(rate, samples)
            tick = time.perf_counter()
            engine.decode_stream(stream)
            row["sensevoice"][lang or "auto"] = dict(
                text=stream.result.text,
                language=stream.result.lang,
                event=stream.result.event,
                seconds=time.perf_counter() - tick,
            )
        records.append(row)
    # Equal audio windows for the two recognizers, including context variation.
    for start, duration in [
        (0, 4),
        (4, 4),
        (8, 4),
        (12, 4),
        (16, 4),
        (20, 4),
        (0, 8),
        (8, 8),
        (16, 8),
        (0, 12),
        (12, 12),
    ]:
        samples = audio[round(start * rate) : round((start + duration) * rate)]
        path = OUT / f"window-{start}-{duration}.wav"
        sf.write(str(path), samples, rate, subtype="PCM_16")
        engine = engines["yue"]
        stream = engine.create_stream()
        stream.accept_waveform(rate, samples)
        tick = time.perf_counter()
        engine.decode_stream(stream)
        previous = dict(
            text=stream.result.text, language=stream.result.lang, seconds=time.perf_counter() - tick
        )
        candidate = qwen(path)
        records.append(
            dict(
                kind="equal-window",
                start=start,
                duration=duration,
                sensevoice=previous,
                qwen=candidate,
            )
        )
        print(
            json.dumps(
                {
                    "start": start,
                    "duration": duration,
                    "sensevoice_seconds": previous["seconds"],
                    "qwen_seconds": candidate["seconds"],
                    "qwen_language": candidate["language"],
                }
            ),
            flush=True,
        )
    payload = dict(
        source="Apple official 29.98-second public preview; user version unverified",
        records=records,
        exact_lyrics_ground_truth="not established",
        song_quality_passed=False,
    )
    (OUT / "comparison.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "executed": True,
                "current_vad_segments": len(segmented),
                "window_cases": 11,
                "quality_passed": False,
            }
        )
    )


def latency_check():
    audio, rate = sf.read(str(OUT / "apple-preview.wav"), dtype="float32")
    old = json.loads((OUT / "comparison-before-latency-fix.json").read_text(encoding="utf-8"))
    old_rows = [r for r in old["records"] if r["kind"] == "current-vad"]
    assert (
        max(r["audio_seconds"] for r in old_rows) > 8
    )  # Fresh reproduction retained before the fix.
    segments = []
    position = [0.0]
    processor = PlaybackProcessor(
        rate, 1, lambda s: segments.append(dict(emitted_at=position[0], seconds=len(s) / 16000))
    )
    for start in range(0, len(audio), 512):
        position[0] = min(start + 512, len(audio)) / rate
        processor.feed(audio[start : start + 512, None])
    processor.flush()
    count = len(segments)
    processor.flush()
    assert len(segments) == count and segments
    assert max(r["seconds"] for r in segments) <= MAX_LIVE_SEGMENT_SECONDS + 512 / 16000
    assert processor.input_frames == len(audio) and processor.output_frames == len(audio)
    report = dict(
        source="Official Apple preview; not the inaccessible user Bilibili audio",
        before_max_segment_seconds=max(r["audio_seconds"] for r in old_rows),
        after_max_segment_seconds=max(r["seconds"] for r in segments),
        before_first_emission_seconds=old_rows[0]["emitted_audio_second"],
        after_first_emission_seconds=segments[0]["emitted_at"],
        segments=segments,
        real_input_frames=processor.input_frames,
        converted_frames=processor.output_frames,
        final_block_padding_frames=processor.tail_padding_frames,
        duplicate_flush_rejected=True,
        scope="Audio-time segmentation and sample integrity; excludes computation, queues and real device delivery",
        song_quality_passed=False,
        bilibili_reproduction="blocked: HTTP 412",
    )
    (OUT / "latency-verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--latency-only", action="store_true")
    args = parser.parse_args()
    latency_check() if args.latency_only else main()
