"""Resident 1.7B song session. The UI owns capture and transcript retention."""

import time
from pathlib import Path

import numpy as np

from .audio_profile import DEFAULT_SENSITIVITY, voice_profile
from .enhanced_inference import SessionInference
from .inference_control import InferenceCancelled, check_cancel, speak_translation
from .paragraphs import ParagraphRevision, accept_punctuation
from .song_stream import SongMailbox, SongWindow, draft_fits, trim_context
from .translation_state import IncrementalTranslation


def make_voice_detector(*, live=False, sensitivity=DEFAULT_SENSITIVITY):
    """Native voice gate; live input also admits short and quiet replies."""
    from .desktop_engine import make_vad

    profile = voice_profile(sensitivity)
    vad = make_vad(live=live, sensitivity=sensitivity)

    def activity(frame):
        if len(frame) < 512:
            frame = np.pad(frame, (0, 512 - len(frame)))
        if live and profile.max_gain > 1:
            # Boost only the detector's copy, at most 8x. Raw PCM, ASR input,
            # playback and file processing retain their original amplitude.
            peak = float(np.max(np.abs(frame)))
            gain = max(1.0, min(profile.max_gain, 0.1 / max(peak, 0.0001)))
            if gain > 1:
                frame = frame * gain
        vad.accept_waveform(frame)
        while not vad.empty():
            vad.pop()
        return vad.is_speech_detected()

    return activity


def make_song_stream(emit, *, sensitivity=DEFAULT_SENSITIVITY):
    """Native voice activity gates inference; it never cuts audio into UI rows."""
    from .song_stream import RollingAudio

    return RollingAudio(
        emit,
        detector=make_voice_detector(live=True, sensitivity=sensitivity),
        first_seconds=0.8,
        update_seconds=0.64,
        context_seconds=8,
        overlap_seconds=2,
        max_segment_seconds=15,
    )


class SongSession:
    def __init__(self, source, autoplay=False, number_mode="original", cloud=None):
        if source not in {"yue", "zh"}:
            raise ValueError("请选择粤语或普通话方向。")
        self.source, self.autoplay, self.number_mode = source, autoplay, number_mode
        self.mailbox = SongMailbox.for_capture()
        self.file_mode = False
        self.cloud_config = cloud

    def windows(self, cancel, emit):
        emit("song_ready", True)
        while (window := self.mailbox.get(cancel)) is not None:
            yield window

    def run(self, engine, player, cancel, emit):
        if not self.file_mode:
            from .paragraph_live import run_live

            return run_live(self, engine, player, cancel, emit, SessionInference)

        from .desktop_engine import UNSUPPORTED_SCRIPT, Cancelled

        inference = SessionInference(self.source, self.cloud_config, emit, engine=engine)
        previous = ""
        previous_end = -1
        states = {}
        cached_asr = None
        confirmed_count = 0
        partial_count = 0
        seconds_per_audio, translation_cost = 0.16, 0.5

        def close_empty(block):
            nonlocal partial_count
            state = states.pop(block, None)
            value = dict(block=block)
            if state is not None and state["revision"].frozen:
                value.update(
                    source=state["revision"].frozen,
                    target=state["translation"].target,
                    partial=True,
                )
                partial_count += 1
            emit("song_empty", value)

        try:
            emit("status", "正在准备本地段落模型" + ("与联网增强…" if self.cloud_config else "…"))
            inference.start(cancel)
            for window in self.windows(cancel, emit):
                check_cancel(cancel)
                if not draft_fits(window, seconds_per_audio, translation_cost, time.monotonic()):
                    self.mailbox.coalesced += 1
                    continue
                if window.silent:
                    if window.final:
                        close_empty(window.block)
                        # No context can be carried through an entirely quiet window.
                        previous = ""
                    continue
                begin = time.perf_counter()
                reused_asr = bool(
                    not self.file_mode
                    and window.final
                    and cached_asr is not None
                    and cached_asr[0] == window.block
                    and cached_asr[2] >= window.voice_end
                )
                origin = window.start
                if reused_asr:
                    _, origin, _, text = cached_asr
                else:
                    text = engine.converters["zh"].convert(
                        inference.transcribe(window.samples, cancel)
                    )
                    cached_asr = (window.block, window.start, window.end, text)
                if UNSUPPORTED_SCRIPT.search(text):
                    raise ValueError("歌曲未识别为普通话、粤语或英文，请检查所选方向。")
                if (
                    not window.final
                    and not window.checkpoint
                    and self.mailbox.has_waiting_confirmation(window.block)
                ):
                    # The completed ASR remains reusable for coverage checks;
                    # do not translate a draft whose confirmation is already queued.
                    continue
                if not any(c.isalnum() for c in text):
                    if window.final:
                        close_empty(window.block)
                    continue
                if window.final and not self.file_mode:
                    text = accept_punctuation(text, text)
                state = states.setdefault(
                    window.block,
                    dict(
                        revision=ParagraphRevision(),
                        start=window.start,
                        translation=IncrementalTranslation(),
                    ),
                )
                if self.file_mode:
                    current = trim_context(previous, text) if window.start < previous_end else text
                    if not any(c.isalnum() for c in current):
                        previous, previous_end = "", window.end
                        close_empty(window.block)
                        continue
                else:
                    current = text
                revision = state["revision"].update(
                    current,
                    origin,
                    state["revision"].version + 1,
                    (window.end - state["start"]) / 16000,
                    final=window.final,
                )
                if revision is None:
                    continue
                emit(
                    "song_source",
                    dict(
                        block=window.block,
                        text=revision.source,
                        final=window.final,
                        frozen_characters=len(state["revision"].frozen),
                        frozen_target=state["translation"].target,
                    ),
                )
                recognized = time.perf_counter()
                if not reused_asr:
                    seconds_per_audio = (recognized - begin) / (len(window.samples) / 16000)

                translated = state["translation"].update(
                    state["revision"].frozen,
                    revision.tail,
                    lambda source: inference.translate(source, cancel),
                )
                translation_cost = time.perf_counter() - recognized
                check_cancel(cancel)
                emit(
                    "song_translation",
                    dict(
                        block=window.block,
                        text=translated,
                        final=window.final,
                        recognition_seconds=recognized - begin,
                        translation_seconds=time.perf_counter() - recognized,
                        lag_seconds=time.monotonic() - window.captured_at,
                        audio_seconds=len(window.samples) / 16000,
                        coalesced=self.mailbox.coalesced,
                        reused_asr=reused_asr,
                        frozen_characters=len(state["revision"].frozen),
                        frozen_target=state["translation"].target,
                    ),
                )
                if window.final:
                    confirmed_count += 1
                    previous = text
                    previous_end = window.end
                    # Only confirmed passages may reach TTS. System capture passes False.
                    if self.autoplay:
                        target = "zh" if self.source == "yue" else "yue"
                        for confirmed in state["translation"].speech:
                            if not speak_translation(
                                engine, confirmed, target, self.number_mode, player, cancel, emit
                            ):
                                self.autoplay = False
                                break
                    states.pop(window.block, None)
            check_cancel(cancel)
            emit("song_drained", dict(confirmed_count=confirmed_count, partial_count=partial_count))
        except InferenceCancelled:
            raise Cancelled() from None
        finally:
            self.mailbox.finish()
            inference.close()


class SongFile(SongSession):
    """Longer offline blocks for files; separation is opt-in, never a live default."""

    def __init__(self, path, source, vocals=False, cloud=None):
        super().__init__(source, cloud=cloud)
        self.file_mode = True
        self.path = Path(path)
        self.vocals = vocals
        import soundfile as sf

        if not self.path.is_file() or self.path.stat().st_size > 100 * 1024 * 1024:
            raise ValueError("请选择不超过 100 MB 的本地歌曲音频。")
        info = sf.info(self.path)
        if (
            not 0 < info.duration <= 600
            or info.channels not in {1, 2}
            or not 8000 <= info.samplerate <= 192000
        ):
            raise ValueError("歌曲文件仅支持不超过 10 分钟的单声道或双声道音频。")

    def windows(self, cancel, emit):
        import soundfile as sf
        import soxr

        emit("status", "正在读取歌曲文件…")
        # Recheck the header and bound the read even if the file changed after selection.
        info = sf.info(self.path)
        if not 8000 <= info.samplerate <= 192000 or info.channels not in {1, 2}:
            raise ValueError("歌曲文件格式已改变，请重新选择。")
        audio, rate = sf.read(
            self.path, frames=info.samplerate * 600 + 1, dtype="float32", always_2d=True
        )
        if not 0 < len(audio) <= rate * 600 or not np.isfinite(audio).all():
            raise ValueError("歌曲文件为空、超长或包含无效音频。")
        check_cancel(cancel)
        if self.vocals:
            from .vocals import separate_vocals

            if rate != 44100:
                audio = soxr.resample(audio, rate, 44100)
            if audio.shape[1] == 1:
                audio = np.repeat(audio, 2, axis=1)
            audio = separate_vocals(audio, cancel, lambda text: emit("status", text))
            rate = 44100
        mono = np.ascontiguousarray(audio.mean(axis=1), dtype=np.float32)
        if rate != 16000:
            mono = soxr.resample(mono, rate, 16000)
        emit("status", "正在检测歌曲文件中的人声区间…")
        detector = make_voice_detector()
        activity = np.zeros((len(mono) + 511) // 512, dtype=bool)
        for index, offset in enumerate(range(0, len(mono), 512)):
            check_cancel(cancel)
            activity[index] = detector(mono[offset : offset + 512])
        for block, start in enumerate(range(0, len(mono), 26 * 16000)):
            check_cancel(cancel)
            end = min(start + 30 * 16000, len(mono))
            if not activity[start // 512 : (end + 511) // 512].any():
                if end == len(mono):
                    break
                continue
            tick = time.monotonic()
            emit("status", f"正在处理歌曲 {start / 16000:.0f}–{end / 16000:.0f} 秒…")
            yield SongWindow(block, start, end, mono[start:end], True, tick, tick)
            if end == len(mono):
                break
