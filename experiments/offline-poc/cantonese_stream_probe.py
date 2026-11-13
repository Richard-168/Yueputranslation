"""T4: codec frame callbacks vs full-sentence Cantonese synthesis.

Uses the pinned SDK's internal backend for feasibility only; not an application
interface. Writes PCM chunks to a local file, does not open speakers/microphone.
First-PCM timings exclude model initialization and text translation.
"""

from __future__ import annotations

import argparse
import gc
import json
import time
from pathlib import Path

import numpy as np
import probe
import psutil
import soundfile as sf
from canto_tts.backends.base import safe_prepare_text

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "outputs/quality-v2"
TEXT = "佢今日冇空，聽日晏晝三點先嚟。"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames-per-chunk", type=int, choices=[1, 2, 4, 8], default=4)
    args = parser.parse_args()
    OUTPUT.mkdir(exist_ok=True)
    report_path = OUTPUT / f"canto-stream-{args.frames_per_chunk}.json"
    report = dict(
        scope="Windows CPU PCM-chunk experiment; no audio-device playback or microphone",
        sdk_internal_api=True,
        text=TEXT,
        frames_per_chunk=args.frames_per_chunk,
        package="canto-tts==0.1.4",
        quality_passed=False,
    )
    started = time.perf_counter()
    try:
        engine = probe.canto_engine()
        report["model_load_seconds"] = time.perf_counter() - started
        backend = engine._backend
        runtime = backend._runtime
        report["rss_after_load_mib"] = psutil.Process().memory_info().rss / 2**20
        runtime.rng = np.random.default_rng(1234)
        report["whole_sentence"] = probe.synthesize(
            engine, "yue", TEXT, "canto-stream-whole-control"
        )
        runtime.rng = np.random.default_rng(1234)
        runtime.codec_streaming_session.reset()
        phoneme = backend.to_phoneme(TEXT)
        token_ids = backend._encoder.encode(safe_prepare_text(phoneme))
        request = runtime.build_voice_clone_request_rows(backend._default_voice_codes, token_ids)
        rate = int(runtime.codec_meta["codec_config"]["sample_rate"])
        channels = int(runtime.codec_meta["codec_config"]["channels"])
        pending, pieces, arrivals = [], [], []
        emitted_samples = 0
        first_chunk_at = None
        first_non_silent_at = None
        tick = time.perf_counter()
        path = probe.OUTPUT / f"canto-stream-{args.frames_per_chunk}.wav"
        with sf.SoundFile(
            str(path), "w", samplerate=rate, channels=channels, subtype="PCM_16"
        ) as writer:

            def emit():
                nonlocal emitted_samples, first_chunk_at, first_non_silent_at
                if not pending:
                    return
                decoded = runtime.codec_streaming_session.run_frames(pending.copy())
                pending.clear()
                if decoded is None:
                    return
                tensor, length = decoded
                if tensor.ndim != 3 or tensor.shape[:2] != (1, channels):
                    raise RuntimeError(f"Unexpected streaming audio shape: {tensor.shape}")
                audio = tensor[0, :, :length].T.astype(np.float32, copy=False)
                if not len(audio) or not np.isfinite(audio).all():
                    raise RuntimeError("Streaming decoder produced no finite samples")
                ready = time.perf_counter() - tick
                if first_chunk_at is None:
                    first_chunk_at = ready
                if first_non_silent_at is None and float(np.max(np.abs(audio))) > 0.0001:
                    first_non_silent_at = ready
                arrivals.append(
                    dict(ready_seconds=ready, samples=len(audio), prior_samples=emitted_samples)
                )
                emitted_samples += len(audio)
                pieces.append(audio.copy())
                writer.write(audio)

            def on_frame(all_frames, step, frame):
                pending.append(frame)
                if len(pending) >= args.frames_per_chunk:
                    emit()

            frames = runtime.generate_audio_frames(request, on_frame=on_frame)
            emit()
        elapsed = time.perf_counter() - tick
        if first_chunk_at is None or first_non_silent_at is None or len(pieces) < 2:
            raise RuntimeError("No non-silent multi-chunk speech produced")
        merged = np.concatenate(pieces, axis=0)
        control_channels, control_length = runtime.decode_full_audio(frames)
        control = np.stack([c[:control_length] for c in control_channels], axis=1)
        same_length = merged.shape == control.shape
        difference = np.abs(merged - control) if same_length else None
        extra_buffer = max(
            0.0,
            max(
                a["ready_seconds"] - first_chunk_at - a["prior_samples"] / rate
                for a in arrivals[1:]
            ),
        )
        report["stream"] = dict(
            file=path.name,
            sample_rate=rate,
            channels=channels,
            frames=len(frames),
            chunks=len(pieces),
            first_pcm_seconds=first_chunk_at,
            first_non_silent_pcm_seconds=first_non_silent_at,
            total_generation_seconds=elapsed,
            audio_seconds=emitted_samples / rate,
            rtf=elapsed / (emitted_samples / rate),
            required_extra_playout_buffer_seconds=extra_buffer,
            full_decode_same_length=same_length,
            max_abs_difference_from_full_decode=None
            if difference is None
            else float(difference.max()),
            mean_abs_difference_from_full_decode=None
            if difference is None
            else float(difference.mean()),
            arrivals=arrivals,
        )
        print(
            json.dumps(
                {k: v for k, v in report["stream"].items() if k != "arrivals"}, ensure_ascii=False
            ),
            flush=True,
        )
        del engine, backend
        gc.collect()
        asr = probe.recognizer()
        report["asr_roundtrip"] = probe.transcribe(asr, path)
        report["status"] = "executed"
    except Exception as exc:
        report.update(status="error", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        report.update(
            elapsed_seconds=time.perf_counter() - started,
            blocked_external_socket_attempts=probe.OUTBOUND_ATTEMPTS,
            human_listening="unverified",
            android_verification="unverified",
        )
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
