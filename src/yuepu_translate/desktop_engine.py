"""Offline desktop audio and inference engine.

It reuses pinned, tested model assets. It is not the Android/product architecture.
Microphone and speakers are accessed only when their user-facing actions run.
"""

from __future__ import annotations

import os
import queue
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from functools import cached_property

import numpy as np

from . import model_runtime
from .audio_profile import DEFAULT_SENSITIVITY, voice_profile
from .capture_process import CaptureProcess
from .inference_control import (
    IncompleteSpeech,
    InferenceCancelled,
    PlaybackUnavailable,
    speak_translation,
)
from .languages import ASR_LANGUAGES as ASR_LANGUAGES
from .languages import UNSUPPORTED_SCRIPT
from .local_inference import LocalInference
from .numbers import spoken_numbers
from .paths import DATA_DIR

ROOT = DATA_DIR
# The native 4s setting is a soft VAD heuristic, not a hard cut. Keep its
# normal edge context while bounding continuous BGM/singing segments.
MAX_LIVE_SEGMENT_SECONDS = 4.5


class Cancelled(InferenceCancelled):
    pass


@dataclass(frozen=True)
class Request:
    token: int
    kind: str
    source: str = "yue"
    text: str = ""
    path: str = ""
    samples: object = None
    rate: int = 16000
    autoplay: bool = True
    number_mode: str = "original"


class PlaybackOutput:
    """All chunks and asynchronous device errors belong to the task that made them."""

    def __init__(self, player, error):
        self.player = player
        self.error = error
        self.generation = player.generation
        self.failed = threading.Event()

    def check(self, cancel):
        if (
            cancel.is_set()
            or self.player.closed.is_set()
            or self.generation != self.player.generation
        ):
            raise Cancelled()
        if self.failed.is_set():
            raise PlaybackUnavailable("译音设备不可用，已停止本次播报。")

    def put(self, samples, rate, cancel):
        self.check(cancel)
        data = np.asarray(samples, dtype=np.float32)
        if data.ndim == 1:
            data = data[:, None]
        chunk = data.copy()
        if self.player.muted:
            self.player.chunks.append((chunk, rate))
            return
        while True:
            self.check(cancel)
            try:
                self.player.queue.put((self, chunk, rate), timeout=0.05)
                return
            except queue.Full:
                continue


class AudioPlayer:
    def __init__(self, error, muted=False):
        self.error, self.muted = error, muted
        self.queue = queue.Queue(maxsize=48)
        self.closed = threading.Event()
        self.generation = 0
        self.chunks = []
        # At 50 ms writes this covers well beyond the capture transport backlog.
        self._play_times = deque(maxlen=2048)
        self._play_times_lock = threading.Lock()
        self.output = self.for_task(error)
        self.thread = None
        if not muted:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    @property
    def busy(self):
        # Includes the block currently being written, not just waiting blocks.
        return self.queue.unfinished_tasks > 0

    def for_task(self, error):
        return PlaybackOutput(self, error)

    def put(self, samples, rate, cancel):
        self.output.put(samples, rate, cancel)

    def playback_intervals(self, start, end):
        """Monotonic seconds, estimated from writes and the output device latency."""
        if end <= start:
            return ()
        with self._play_times_lock:
            return tuple(
                (max(start, begin), min(end, finish))
                for begin, finish in self._play_times
                if finish > start and begin < end
            )

    def stop(self):
        self.generation += 1
        self.output = self.for_task(self.error)
        while True:
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except queue.Empty:
                break

    def _run(self):
        stream = None
        current_format = None
        audible_until = 0.0
        try:
            while not self.closed.is_set():
                try:
                    output, data, rate = self.queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    if output.generation != self.generation or output.failed.is_set():
                        continue
                    fmt = (rate, data.shape[1])
                    if fmt != current_format:
                        import sounddevice as sd

                        if stream is not None:
                            stream.close()
                        stream = sd.OutputStream(
                            samplerate=rate, channels=data.shape[1], dtype="float32", blocksize=0
                        )
                        stream.start()
                        current_format = fmt
                        audible_until = 0.0
                    # Short writes bound Stop latency; no unbounded playback buffer.
                    size = max(1, int(rate * 0.05))
                    for start in range(0, len(data), size):
                        if output.generation != self.generation or self.closed.is_set():
                            break
                        chunk = data[start : start + size]
                        latency = max(0, float(getattr(stream, "latency", 0)))
                        begins = max(audible_until, time.monotonic() + latency)
                        audible_until = begins + len(chunk) / rate
                        interval = (begins, audible_until)
                        with self._play_times_lock:
                            self._play_times.append(interval)
                        try:
                            stream.write(chunk)
                        except Exception:
                            with self._play_times_lock:
                                self._play_times.pop()
                            raise
                except Exception:
                    output.failed.set()
                    if stream is not None:
                        try:
                            stream.close()
                        except Exception:
                            pass
                        stream = None
                    current_format = None
                    if output.generation == self.generation and not self.closed.is_set():
                        output.error("无法播放译音，请检查 Windows 默认输出设备后重试。")
                finally:
                    self.queue.task_done()
        finally:
            if stream is not None:
                stream.close()

    def close(self):
        self.stop()
        self.closed.set()
        if self.thread:
            self.thread.join(timeout=2)


def cantonese_phrases(text, limit=28):
    """Keep short utterances intact; bound each long Cantonese synthesis request."""
    while len(text) > limit:
        prefix = text[:limit]
        # Prefer sentence/phrase boundaries; keep decimal separators inside numbers.
        cuts = [
            m.end()
            for m in re.finditer(
                r"[。！？；，、：…]|[!?;]|(?<!\d)[.,:]|[.,:](?!\d)|\s+", text[: limit + 1]
            )
            if m.end() <= limit
        ]
        cut = cuts[-1] if cuts else limit
        # Keep a whole Latin word where it fits within the next phrase.
        if (
            not cuts
            and prefix[-1].isascii()
            and prefix[-1].isalnum()
            and text[limit].isascii()
            and text[limit].isalnum()
        ):
            word = re.search(r"[A-Za-z0-9]+$", prefix)
            if word and word.start():
                cut = word.start()
        phrase, text = text[:cut], text[cut:]
        if any(c.isalnum() for c in phrase):
            yield phrase
    if any(c.isalnum() for c in text):
        yield text


class Engine:
    def __init__(self):
        self.asr = self.zh_tts = self.yue_tts = None
        self.translator = LocalInference(
            "translation", root=ROOT, threads=min(12, os.cpu_count() or 4)
        )
        self.warmed = False

    @cached_property
    def converters(self):
        import opencc

        return {"zh": opencc.OpenCC("t2s"), "yue": opencc.OpenCC("s2t")}

    @staticmethod
    def check(cancel):
        if cancel.is_set():
            raise Cancelled()

    def prepare_recognition(self, cancel):
        self.check(cancel)
        if self.asr is None:
            self.asr = model_runtime.recognizer()
        self.check(cancel)

    def prepare_voice(self, target, cancel):
        self.check(cancel)
        if target == "zh" and self.zh_tts is None:
            self.zh_tts = model_runtime.mandarin_engine()
        elif target == "yue" and self.yue_tts is None:
            self.yue_tts = model_runtime.canto_engine()
        self.check(cancel)

    def close(self):
        self.translator.close()
        self.asr = self.zh_tts = self.yue_tts = None
        self.warmed = False

    def load(self, cancel, status):
        """Explicit full offline warm-up for diagnostics; user tasks load by role."""
        status("正在加载语音识别…")
        self.prepare_recognition(cancel)
        status("正在加载普通话译音…")
        self.prepare_voice("zh", cancel)
        status("正在加载粤语译音…")
        self.prepare_voice("yue", cancel)
        if not self.warmed:
            status("正在预热离线翻译和译音，完成后即可开始交流…")
            self.translate("你好。", "zh", cancel)
            # Exercise kernels without opening speakers or persisting audio.
            sink = AudioPlayer(lambda message: None, muted=True)
            try:
                self.speak("你好。", "zh", "original", sink, cancel, lambda: None)
                sink.chunks.clear()
                self.speak("多謝。", "yue", "original", sink, cancel, lambda: None)
            finally:
                sink.close()
                sink.chunks.clear()
            self.check(cancel)
            self.warmed = True

    def recognize(self, samples, rate, cancel, source, event):
        self.check(cancel)
        if source not in {"zh", "yue"}:
            raise ValueError("请选择粤语或普通话作为交流方向。")
        data = np.asarray(samples, dtype=np.float32)
        if data.ndim == 2:
            data = data.mean(axis=1)
        if not len(data) or len(data) / rate > 15 or not np.isfinite(data).all():
            raise ValueError("验证工具每次接受不超过 15 秒的有效语音，请分段重试。")
        self.prepare_recognition(cancel)

        def decode(recognizer):
            stream = recognizer.create_stream()
            stream.accept_waveform(rate, data)
            recognizer.decode_stream(stream)
            self.check(cancel)
            return stream.result

        result = decode(self.asr)
        text = result.text.strip()
        if UNSUPPORTED_SCRIPT.search(text):
            raise ValueError("未能识别为普通话、粤语或英文，请确认翻译方向并靠近麦克风重说。")
        if not text or not any(char.isalnum() for char in text):
            raise ValueError("没有识别到有效的人声文字，请等待人声或换一段清晰语音重试。")
        event(
            "recognition",
            dict(
                automatic_language=None,
                language=source,
                language_detection=False,
                redirected=False,
                source=source,
            ),
        )
        return text

    def translate(self, text, source, cancel):
        self.check(cancel)
        if not text.strip() or len(text) > 120:
            raise ValueError("请提供 1–120 字的短句；较长内容请分句验证。")
        try:
            return self.translator.translate(text, cancel, source=source)
        except InferenceCancelled:
            raise Cancelled() from None

    def speak(self, text, target, number_mode, player, cancel, first_audio):
        if isinstance(player, AudioPlayer):
            player = player.output
        player.check(cancel)
        self.prepare_voice(target, cancel)
        player.check(cancel)
        spoken = self.converters[target].convert(text)
        if target == "zh" and number_mode != "original":
            spoken, _ = spoken_numbers(spoken, number_mode)
        if target == "zh":
            import sherpa_onnx

            config = sherpa_onnx.GenerationConfig()
            config.sid, config.speed = 0, 1.0
            audio = self.zh_tts.generate(spoken, config)
            player.check(cancel)
            if not len(audio.samples) or audio.sample_rate <= 0:
                raise RuntimeError("普通话译音生成失败。")
            first_audio()
            player.put(audio.samples, audio.sample_rate, cancel)
            return
        from canto_tts.backends.base import safe_prepare_text

        backend = self.yue_tts._backend
        runtime = backend._runtime
        runtime.manifest["generation_defaults"].update(
            max_new_frames=200,
            text_temperature=0.9,
            text_top_p=1.0,
            text_top_k=50,
            audio_temperature=0.9,
            audio_top_p=0.9,
            audio_top_k=25,
            audio_repetition_penalty=1.0,
        )
        rate = int(runtime.codec_meta["codec_config"]["sample_rate"])
        pending, emitted = [], False

        def emit():
            nonlocal emitted
            player.check(cancel)
            if not pending:
                return
            decoded = runtime.codec_streaming_session.run_frames(pending.copy())
            pending.clear()
            if decoded is None:
                return
            tensor, length = decoded
            if length > 0:
                if not emitted:
                    first_audio()
                    emitted = True
                player.put(tensor[0, :, :length].T, rate, cancel)

        def callback(frames, step, frame):
            player.check(cancel)
            pending.append(frame)
            if len(pending) >= 4:
                emit()

        for phrase in cantonese_phrases(spoken):
            player.check(cancel)
            runtime.rng = np.random.default_rng(1234)
            runtime.codec_streaming_session.reset()
            request = runtime.build_voice_clone_request_rows(
                backend._default_voice_codes,
                backend._encoder.encode(safe_prepare_text(backend.to_phoneme(phrase))),
            )
            frames = runtime.generate_audio_frames(request, on_frame=callback)
            emit()
            if len(frames) >= runtime.manifest["generation_defaults"]["max_new_frames"]:
                raise IncompleteSpeech("粤语译音达到单段时长上限，播报可能不完整。")
            if not frames:
                raise IncompleteSpeech("粤语合成没有读出当前分句，播报未完成。")
        if not emitted:
            raise RuntimeError("粤语译音生成失败。")

    def process(self, request, cancel, player, event):
        start = time.perf_counter()
        recognition_seconds = 0.0
        if request.kind == "speak":
            try:
                self.speak(
                    request.text,
                    request.source,
                    request.number_mode,
                    player,
                    cancel,
                    lambda: event("first_audio", time.perf_counter() - start),
                )
            except PlaybackUnavailable:
                pass  # The output worker already notified this request.
            return
        if request.kind == "file":
            import soundfile as sf

            info = sf.info(request.path)
            if info.duration > 15:
                raise ValueError("验证工具每次接受不超过 15 秒的音频，请分段重试。")
            samples, rate = sf.read(request.path, dtype="float32")
            text = self.recognize(samples, rate, cancel, request.source, event)
            recognition_seconds = time.perf_counter() - start
        elif request.kind == "audio":
            text = self.recognize(request.samples, request.rate, cancel, request.source, event)
            recognition_seconds = time.perf_counter() - start
        elif request.kind == "text":
            text = request.text.strip()
        else:
            raise ValueError("未知验证任务。")
        event("source", text)
        event("status", "正在翻译…")
        translation_start = time.perf_counter()
        translated = self.translate(text, request.source, cancel)
        translation_seconds = time.perf_counter() - translation_start
        target = "zh" if request.source == "yue" else "yue"
        event(
            "translation",
            dict(
                text=translated,
                target=target,
                seconds=time.perf_counter() - start,
                recognition_seconds=recognition_seconds,
                translation_seconds=translation_seconds,
            ),
        )
        if request.autoplay:
            event("status", "正在生成译音…")
            speak_translation(
                self,
                translated,
                target,
                request.number_mode,
                player,
                cancel,
                event,
                lambda: event("first_audio", time.perf_counter() - start),
            )


class SpeechSegmenter:
    """Native VAD with an actual duration ceiling, shared by both live inputs."""

    def __init__(self, segment, max_seconds=MAX_LIVE_SEGMENT_SECONDS):
        if not 0.5 <= max_seconds <= 10:
            raise ValueError("无效的连续语音分段上限。")
        self.segment = segment
        self.vad = make_vad()
        self.max_samples = round(max_seconds * 16000)
        self.samples_seen = 0
        self.active_start = None
        self.forced_cuts = 0

    def _drain(self):
        while not self.vad.empty():
            speech = np.array(self.vad.front.samples, dtype=np.float32, copy=True)
            self.vad.pop()
            self.active_start = None
            self.segment(speech)

    def feed(self, samples):
        data = np.asarray(samples, dtype=np.float32)
        if data.ndim != 1 or len(data) != 512 or not np.isfinite(data).all():
            raise ValueError("分段器需要 512 帧有效单声道音频。")
        self.vad.accept_waveform(data)
        self.samples_seen += len(data)
        self._drain()
        if self.vad.is_speech_detected():
            if self.active_start is None:
                self.active_start = self.vad.current_segment.start
            if self.samples_seen - self.active_start >= self.max_samples:
                self.vad.flush()
                self.forced_cuts += 1
                self._drain()
        else:
            self.active_start = None

    def flush(self):
        self.vad.flush()
        self._drain()


class PlaybackProcessor:
    """Device-rate PCM -> streaming 16 kHz mono -> bounded VAD segments."""

    def __init__(self, rate, channels, segment, segmenter_factory=None):
        if rate <= 0 or channels < 1:
            raise ValueError("设备音频格式无效。")
        self.rate, self.channels, self.segment = rate, channels, segment
        self.segmenter_factory = segmenter_factory
        self.segmenter = None
        self.input_frames = 0
        self.output_frames = 0
        self.tail_padding_frames = 0
        self.paused = False
        self._restart()

    def _restart(self):
        import soxr

        rate = self.rate
        self.resampler = soxr.ResampleStream(rate, 16000, 1, dtype="float32", quality="HQ")
        if self.segmenter_factory is None:
            self.segmenter = SpeechSegmenter(self.segment)
        elif self.segmenter is None:
            self.segmenter = self.segmenter_factory(self.segment)
        self.pending = np.empty(0, dtype=np.float32)
        self.paused = False

    def feed(self, samples):
        data = np.asarray(samples, dtype=np.float32)
        if data.ndim != 2 or data.shape[1] != self.channels or not np.isfinite(data).all():
            raise ValueError("设备音频数据无效。")
        if self.paused:
            self._restart()
        self.input_frames += len(data)
        mono = np.ascontiguousarray(data.mean(axis=1), dtype=np.float32)
        converted = self.resampler.resample_chunk(mono)
        self._accept_converted(converted)

    def _accept_converted(self, converted):
        self.output_frames += len(converted)
        self.pending = np.concatenate((self.pending, converted))
        while len(self.pending) >= 512:
            self.segmenter.feed(self.pending[:512])
            self.pending = self.pending[512:]

    def flush(self):
        """Finalize a real idle boundary once; never invent timed audio gaps."""
        if self.paused:
            return
        self._accept_converted(
            self.resampler.resample_chunk(np.empty(0, dtype=np.float32), last=True)
        )
        if len(self.pending):
            self.tail_padding_frames += 512 - len(self.pending)
            self.segmenter.feed(np.pad(self.pending, (0, 512 - len(self.pending))))
            self.pending = np.empty(0, dtype=np.float32)
        self.segmenter.flush()
        self.paused = True


def make_vad(*, live=False, sensitivity=DEFAULT_SENSITIVITY):
    import sherpa_onnx

    model_runtime.require_models("vad/silero_vad.onnx")
    profile = voice_profile(sensitivity)
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(ROOT / "models/vad/silero_vad.onnx")
    # RollingAudio already waits for the mode's pause. A second long VAD
    # hangover can join separate short replies and postpone their review.
    config.silero_vad.min_silence_duration = 0.15 if live else 0.65
    # The file gate's 250 ms onset can discard an entire one-syllable reply.
    # Live captions need a shorter onset; paragraph/flash pause rules still
    # belong to their existing RollingAudio configuration.
    config.silero_vad.min_speech_duration = profile.min_speech_seconds if live else 0.25
    if live:
        config.silero_vad.threshold = profile.threshold
    config.silero_vad.max_speech_duration = 4
    config.sample_rate = 16000
    return sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=15)


class Microphone(CaptureProcess):
    def __init__(self, segment, error, paragraph=False, segmenter_factory=None, *, started=None):
        super().__init__(
            "microphone",
            segment,
            error,
            started=started,
            paragraph=paragraph,
            segmenter_factory=segmenter_factory,
        )


class SystemAudio(CaptureProcess):
    def __init__(self, segment, error, started, paragraph=False, segmenter_factory=None):
        super().__init__(
            "system",
            segment,
            error,
            started=started,
            paragraph=paragraph,
            segmenter_factory=segmenter_factory,
        )
