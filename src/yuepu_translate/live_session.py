"""Low-latency source captions; translation and confirmed speech run separately."""

import threading
import time
from dataclasses import dataclass

from .audio_profile import DEFAULT_SENSITIVITY
from .enhanced_inference import SessionInference
from .inference_control import check_cancel
from .paragraphs import ParagraphRevision, accept_punctuation
from .song_stream import RollingAudio, SongMailbox
from .translation_state import IncrementalTranslation


def make_live_stream(emit, detector=None, *, sensitivity=DEFAULT_SENSITIVITY):
    if detector is None:
        from .song_pipeline import make_voice_detector

        detector = make_voice_detector(live=True, sensitivity=sensitivity)
    return RollingAudio(
        emit,
        detector=detector,
        pause_seconds=0.65,
        first_seconds=0.8,
        update_seconds=0.64,
        pre_roll_seconds=0.32,
        max_segment_seconds=8,
    )


@dataclass(frozen=True)
class Translation:
    block: int
    text: str
    final: bool
    version: int
    recognition_seconds: float
    captured_at: float
    frozen_source: str
    tail: str
    checkpoint: bool = False


class LiveSession:
    """One ASR owner and one bounded translation/TTS lane per capture session.

    Source events carry a version. A translated draft can only update the
    matching source version. Confirmed jobs are retained in order, and only
    the latest draft waits on either lane.
    """

    def __init__(self, source, autoplay=False, number_mode="original", cloud=None):
        if source not in {"yue", "zh"}:
            raise ValueError("请选择粤语或普通话方向。")
        self.source, self.autoplay, self.number_mode = source, autoplay, number_mode
        self.mailbox = SongMailbox.for_capture()
        self.cloud_config = cloud

    def run(self, engine, player, cancel, emit):
        translations = SongMailbox()
        failures = []
        confirmed_count = partial_count = 0

        def translate():
            inference = None
            try:
                inference = SessionInference(
                    self.source, self.cloud_config, emit, roles=("translation",)
                )
                inference.start(cancel)
                translated_block, state, preview_at = -1, None, 0
                while (job := translations.get(cancel)) is not None:
                    check_cancel(cancel)
                    if not job.final and (
                        translations.has_waiting_confirmation()
                        or self.mailbox.has_waiting_confirmation()
                    ):
                        continue
                    begin = time.perf_counter()
                    if job.block != translated_block:
                        translated_block, state, preview_at = job.block, IncrementalTranslation(), 0
                    preview = (
                        not state.target and not state.preview_target
                    ) or begin - preview_at >= 2.5
                    target = state.update(
                        job.frozen_source,
                        job.tail,
                        lambda text: inference.translate(text, cancel),
                        preview=preview,
                    )
                    if preview and job.tail:
                        preview_at = time.perf_counter()
                    check_cancel(cancel)
                    emit(
                        "live_translation",
                        dict(
                            block=job.block,
                            source=job.text,
                            text=target,
                            final=job.final,
                            version=job.version,
                            frozen_source=state.source,
                            frozen_target=state.target,
                            tail_current=state.preview_source == job.tail,
                            recognition_seconds=job.recognition_seconds,
                            translation_seconds=time.perf_counter() - begin,
                            lag_seconds=time.monotonic() - job.captured_at,
                        ),
                    )
                    if job.final and self.autoplay:
                        engine.speak(
                            target,
                            "zh" if self.source == "yue" else "yue",
                            self.number_mode,
                            player,
                            cancel,
                            lambda: None,
                        )
            except Exception as exc:
                failures.append(exc)
                cancel.set()
                self.mailbox.finish()
            finally:
                if inference is not None:
                    inference.close()

        worker = threading.Thread(target=translate, name="live-translation", daemon=True)
        block, text, version, covered_end = -1, "", 0, -1
        revision = None
        last_asr = ""
        start = 0
        try:
            worker.start()
            # Source recognition uses the already-loaded base model. Starting
            # capture does not wait for translation warm-up or a final pause.
            emit("song_ready", True)
            while (window := self.mailbox.get(cancel)) is not None:
                check_cancel(cancel)
                if window.block != block:
                    block, text, version, covered_end = window.block, "", 0, -1
                    revision, last_asr, start = ParagraphRevision(), "", window.start
                begin = time.perf_counter()
                try:
                    if window.final and covered_end >= window.voice_end and text:
                        recognized = last_asr
                    elif window.silent:
                        recognized = ""
                    else:
                        recognized = engine.converters["zh"].convert(
                            engine.recognize(window.samples, 16000, cancel, self.source, emit)
                        )
                except ValueError as exc:
                    # Very short drafts may not yet contain a recognizable word.
                    # Failed final recognition must not confirm a provisional guess.
                    if window.final:
                        emit("live_empty", dict(block=block, reason=str(exc)))
                        partial_count += bool(text)
                    continue
                if not any(c.isalnum() for c in recognized):
                    if window.final:
                        emit("live_empty", dict(block=block, reason="未识别到有效人声"))
                        partial_count += bool(text)
                    continue
                covered_end = window.end
                last_asr = recognized
                if window.final:
                    recognized = accept_punctuation(recognized, recognized)
                frozen_before = revision.frozen
                version += 1
                result = revision.update(
                    recognized,
                    window.start,
                    version,
                    (window.end - start) / 16000,
                    final=window.final,
                )
                if result.source == text and revision.frozen == frozen_before and not window.final:
                    continue
                text = result.source
                seconds = time.perf_counter() - begin
                emit(
                    "live_source",
                    dict(
                        block=block,
                        text=text,
                        final=window.final,
                        version=version,
                        frozen_characters=len(revision.frozen),
                        recognition_seconds=seconds,
                        lag_seconds=time.monotonic() - window.captured_at,
                    ),
                )
                if window.final or not (
                    self.mailbox.has_waiting_confirmation()
                    or translations.has_waiting_confirmation()
                ):
                    translations.put(
                        Translation(
                            block,
                            text,
                            window.final,
                            version,
                            seconds,
                            window.captured_at,
                            revision.frozen,
                            result.tail,
                        ),
                        cancel=cancel,
                    )
                confirmed_count += window.final
            translations.finish()
            while worker.is_alive():
                worker.join(0.05)
                if failures:
                    raise failures[0]
                check_cancel(cancel)
            if failures:
                raise failures[0]
            check_cancel(cancel)
            emit("song_drained", dict(confirmed_count=confirmed_count, partial_count=partial_count))
        except Exception:
            if failures:
                raise failures[0]
            raise
        finally:
            self.mailbox.finish()
            translations.finish()
            if worker.is_alive():
                cancel.set()
                worker.join()
