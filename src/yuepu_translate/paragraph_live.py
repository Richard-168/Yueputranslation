"""Provisional light captions over the existing paragraph detector and boundaries."""

import threading
import time
from dataclasses import dataclass

from .inference_control import check_cancel
from .languages import UNSUPPORTED_SCRIPT
from .paragraphs import ParagraphRevision, accept_punctuation
from .song_stream import SongMailbox
from .translation_state import IncrementalTranslation


@dataclass(frozen=True)
class Preview:
    block: int
    text: str
    version: int
    captured_at: float
    recognition_seconds: float
    final: bool = False
    checkpoint: bool = False


def run_live(session, engine, player, cancel, emit, inference_factory):
    # One owner handles large-model ASR and translation, preserving its task-wide
    # cloud fallback latch. The main lane can keep producing local captions.
    work = SongMailbox()
    failures = []
    counts = dict(confirmed_count=0, partial_count=0)

    def version(window, reviewed):
        return window.end * 4 + (2 if window.final else 1) * int(reviewed)

    def source(window, text, final, seconds, *, reviewed=False):
        emit(
            "live_source",
            dict(
                block=window.block,
                text=text,
                final=final,
                version=version(window, reviewed),
                frozen_characters=len(text) if final else 0,
                recognition_seconds=seconds,
                lag_seconds=time.monotonic() - window.captured_at,
                reviewing=not final,
                reviewed=reviewed,
            ),
        )

    def review():
        inference = None
        try:
            inference = inference_factory(session.source, session.cloud_config, emit)
            inference.start(cancel)
            block, revision, cached = -1, None, None
            translated_block, state, preview_at = -1, None, 0
            while (job := work.get(cancel)) is not None:
                check_cancel(cancel)
                if job.block != translated_block:
                    translated_block, state, preview_at = job.block, IncrementalTranslation(), 0
                if isinstance(job, Preview):
                    start = time.perf_counter()
                    changed = job.text != state.preview_source
                    if changed and state.preview_target and start - preview_at < 2.5:
                        continue
                    target = state.update(
                        "", job.text, lambda text: inference.translate(text, cancel)
                    )
                    if changed:
                        preview_at = time.perf_counter()
                    check_cancel(cancel)
                    emit(
                        "live_translation",
                        dict(
                            block=job.block,
                            source=job.text,
                            text=target,
                            final=False,
                            version=job.version,
                            frozen_source="",
                            frozen_target="",
                            preview=True,
                            tail_current=True,
                            recognition_seconds=job.recognition_seconds,
                            translation_seconds=time.perf_counter() - start,
                            lag_seconds=time.monotonic() - job.captured_at,
                        ),
                    )
                    continue
                window = job
                if window.block != block:
                    block, revision, cached = window.block, ParagraphRevision(), None
                start = time.perf_counter()
                if window.silent:
                    text = ""
                elif window.final and cached is not None and cached[1] >= window.voice_end:
                    origin, _, text = cached
                else:
                    origin = window.start
                    text = engine.converters["zh"].convert(
                        inference.transcribe(window.samples, cancel)
                    )
                    cached = origin, window.end, text
                check_cancel(cancel)
                if UNSUPPORTED_SCRIPT.search(text):
                    raise ValueError("pro 复核未识别为普通话、粤语或英文，请检查翻译方向。")
                if not any(char.isalnum() for char in text):
                    if window.final:
                        counts["partial_count"] += 1
                        emit("live_empty", dict(block=block, reason="复核没有识别到有效人声"))
                    continue
                if window.final:
                    text = accept_punctuation(text, text)
                result = revision.update(
                    text,
                    origin,
                    revision.version + 1,
                    0,
                    final=window.final,
                )
                if result is None:
                    continue
                # Checkpoints retain older reviewed context before audio rolls
                # out of the 8 s window; they do not invent a pause or freeze a guess.
                seconds = time.perf_counter() - start
                source(window, result.source, window.final, seconds, reviewed=True)
                if not window.final:
                    continue
                translating = time.perf_counter()
                target = state.update(
                    revision.frozen, "", lambda text: inference.translate(text, cancel)
                )
                check_cancel(cancel)
                emit(
                    "live_translation",
                    dict(
                        block=block,
                        source=result.source,
                        text=target,
                        final=True,
                        version=version(window, True),
                        frozen_source=revision.frozen,
                        frozen_target=state.target,
                        tail_current=True,
                        recognition_seconds=seconds,
                        translation_seconds=time.perf_counter() - translating,
                        lag_seconds=time.monotonic() - window.captured_at,
                    ),
                )
                counts["confirmed_count"] += 1
                if session.autoplay:
                    engine.speak(
                        target,
                        "zh" if session.source == "yue" else "yue",
                        session.number_mode,
                        player,
                        cancel,
                        lambda: None,
                    )
        except Exception as exc:
            failures.append(exc)
            cancel.set()
            session.mailbox.finish()
        finally:
            if inference is not None:
                inference.close()

    worker = threading.Thread(target=review, name="pro-paragraph-review", daemon=True)
    try:
        worker.start()
        block, draft = -1, None
        for window in session.windows(cancel, emit):
            check_cancel(cancel)
            if window.block != block:
                block, draft = window.block, ParagraphRevision()
            start = time.perf_counter()
            if not window.silent:
                try:
                    text = engine.converters["zh"].convert(
                        engine.recognize(window.samples, 16000, cancel, session.source, emit)
                    )
                    if any(char.isalnum() for char in text):
                        result = draft.update(text, window.start, window.end, 0)
                        if result is not None:
                            seconds = time.perf_counter() - start
                            source(window, result.source, False, seconds)
                            if not window.final and not window.checkpoint:
                                work.put(
                                    Preview(
                                        window.block,
                                        result.source,
                                        version(window, False),
                                        window.captured_at,
                                        seconds,
                                    )
                                )
                except ValueError:
                    # A short or rejected light guess must not prevent final review.
                    pass
            if window.checkpoint or window.final:
                work.put(window)
        work.finish()
        while worker.is_alive():
            worker.join(0.05)
            if failures:
                raise failures[0]
            check_cancel(cancel)
        if failures:
            raise failures[0]
        check_cancel(cancel)
        emit("song_drained", counts)
    except Exception:
        if failures:
            raise failures[0]
        raise
    finally:
        session.mailbox.finish()
        work.finish()
        if worker.is_alive():
            cancel.set()
            worker.join()
