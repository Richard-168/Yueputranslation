"""Offline desktop audio and inference engine.

It reuses pinned, tested model assets. It is not the Android/product architecture.
Microphone and speakers are accessed only when their user-facing actions run.
"""

from __future__ import annotations

import queue
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import opencc
import sherpa_onnx
import sounddevice as sd
import soundfile as sf
from canto_tts.backends.base import safe_prepare_text

from . import model_runtime
from .audio_profile import DEFAULT_SENSITIVITY, voice_profile
from .capture_process import CaptureProcess
from .languages import ASR_LANGUAGES, UNSUPPORTED_SCRIPT
from .numbers import spoken_numbers
from .paths import DATA_DIR
from .preferences import cache_directory

ROOT = DATA_DIR
# The native 4s setting is a soft VAD heuristic, not a hard cut. Keep its
# normal edge context while bounding continuous BGM/singing segments.
MAX_LIVE_SEGMENT_SECONDS = 4.5


class Cancelled(Exception):
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


class AudioPlayer:
    def __init__(self, error, muted=False):
        self.error, self.muted = error, muted
        self.queue = queue.Queue(maxsize=48)
        self.closed = threading.Event()
        self.generation = 0
        self.chunks = []
        self.thread = None
        if not muted:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    @property
    def busy(self):
        # Includes the block currently being written, not just waiting blocks.
        return self.queue.unfinished_tasks > 0

    def put(self, samples, rate, cancel):
        if cancel.is_set():
            raise Cancelled()
        data = np.asarray(samples, dtype=np.float32)
        if data.ndim == 1:
            data = data[:, None]
        if self.muted:
            self.chunks.append((data.copy(), rate))
            return
        while not self.closed.is_set():
            if cancel.is_set():
                raise Cancelled()
            try:
                self.queue.put((self.generation, data.copy(), rate), timeout=0.05)
                return
            except queue.Full:
                continue
        raise Cancelled()

    def stop(self):
        self.generation += 1
        while True:
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except queue.Empty:
                break

    def _run(self):
        stream = None
        current_format = None
        try:
            while not self.closed.is_set():
                try:
                    generation, data, rate = self.queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    if generation != self.generation:
                        continue
                    fmt = (rate, data.shape[1])
                    if fmt != current_format:
                        if stream is not None:
                            stream.close()
                        stream = sd.OutputStream(
                            samplerate=rate, channels=data.shape[1], dtype="float32", blocksize=0
                        )
                        stream.start()
                        current_format = fmt
                    # Short writes bound Stop latency; no unbounded playback buffer.
                    size = max(1, int(rate * 0.05))
                    for start in range(0, len(data), size):
                        if generation != self.generation or self.closed.is_set():
                            break
                        stream.write(data[start : start + size])
                except Exception:
                    self.stop()
                    self.error("无法播放译音，请检查 Windows 默认输出设备后重试。")
                    if stream is not None:
                        stream.close()
                        stream = None
                        current_format = None
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


class Engine:
    def __init__(self):
        self.asr = self.zh_tts = self.yue_tts = None
        self.directed_asr = {}
        self.warmed = False
        self.converters = {"zh": opencc.OpenCC("t2s"), "yue": opencc.OpenCC("s2t")}

    @staticmethod
    def check(cancel):
        if cancel.is_set():
            raise Cancelled()

    def load(self, cancel, status):
        required = [
            "models/asr/model.int8.onnx",
            "models/asr/tokens.txt",
            "models/hymt2/Hy-MT2-1.8B-Q4_K_M.gguf",
            "models/canto/browser_poc_manifest.json",
            "models/vits-piper-zh_CN-huayan-medium/zh_CN-huayan-medium.onnx",
            "models/vad/silero_vad.onnx",
            "runtime/llama-b12314/llama-completion.exe",
            "runtime/llama-b12314/llama-server.exe",
        ]
        if any(not (ROOT / p).is_file() for p in required):
            raise RuntimeError("离线模型文件不完整，请先完成模型准备。")
        self.check(cancel)
        cache_directory()
        status("正在加载语音识别…")
        if self.asr is None:
            self.asr = model_runtime.recognizer()
        self.check(cancel)
        status("正在加载普通话译音…")
        if self.zh_tts is None:
            self.zh_tts = model_runtime.mandarin_engine()
        self.check(cancel)
        status("正在加载粤语译音，首次可能需要十几秒…")
        if self.yue_tts is None:
            self.yue_tts = model_runtime.canto_engine()
        self.check(cancel)
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
        if self.asr is None:
            raise RuntimeError("请先加载离线模型。")
        data = np.asarray(samples, dtype=np.float32)
        if data.ndim == 2:
            data = data.mean(axis=1)
        if not len(data) or len(data) / rate > 15 or not np.isfinite(data).all():
            raise ValueError("验证工具每次接受不超过 15 秒的有效语音，请分段重试。")

        def decode(recognizer):
            stream = recognizer.create_stream()
            stream.accept_waveform(rate, data)
            recognizer.decode_stream(stream)
            self.check(cancel)
            return stream.result

        def language(result):
            return result.lang.removeprefix("<|").removesuffix("|>")

        result = decode(self.asr)
        automatic_language = language(result)
        redirected = automatic_language not in ASR_LANGUAGES or bool(
            UNSUPPORTED_SCRIPT.search(result.text)
        )
        if redirected:
            # SenseVoice exposes auto or one forced language, not an allowlist.
            # Re-decode the original audio in the user's selected direction;
            # never translate or rewrite the rejected Japanese/Korean text.
            event("status", "识别语言超出范围，正按所选粤语／普通话方向重新识别…")
            self.check(cancel)
            if source not in self.directed_asr:
                self.directed_asr[source] = model_runtime.recognizer(language=source)
            self.check(cancel)
            result = decode(self.directed_asr[source])
        text = result.text.strip()
        if language(result) not in ASR_LANGUAGES or UNSUPPORTED_SCRIPT.search(text):
            raise ValueError("未能识别为普通话、粤语或英文，请确认翻译方向并靠近麦克风重说。")
        if not text or not any(char.isalnum() for char in text):
            raise ValueError("没有识别到有效的人声文字，请等待人声或换一段清晰语音重试。")
        event(
            "recognition",
            dict(
                automatic_language=automatic_language,
                language=language(result),
                redirected=redirected,
                source=source,
            ),
        )
        return text

    def translate(self, text, source, cancel):
        self.check(cancel)
        if not text.strip() or len(text) > 120:
            raise ValueError("请提供 1–120 字的短句；较长内容请分句验证。")
        target = "中文" if source == "yue" else "粤语"
        user = f"将以下文本翻译为{target}，注意只需要输出翻译后的结果，不要额外解释：\n\n{text}"
        prompt = f"<｜hy_begin▁of▁sentence｜><｜hy_User｜>{user}<｜hy_Assistant｜>"
        # Per-job text files are removed on success, cancellation and error.
        with tempfile.TemporaryDirectory(prefix="yuepu-", dir=cache_directory()) as directory:
            path = Path(directory) / "prompt.txt"
            path.write_text(prompt, encoding="utf-8")
            command = [
                str(ROOT / "runtime/llama-b12314/llama-completion.exe"),
                "-m",
                str(ROOT / "models/hymt2/Hy-MT2-1.8B-Q4_K_M.gguf"),
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
                "0.7",
                "--top-k",
                "20",
                "--top-p",
                "0.6",
                "--repeat-penalty",
                "1.05",
                "-n",
                "192",
                "-f",
                str(path),
            ]
            with (Path(directory) / "runtime.log").open("wb") as log:
                child = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                deadline = time.monotonic() + 30
                try:
                    while child.poll() is None:
                        self.check(cancel)
                        if time.monotonic() > deadline:
                            raise TimeoutError("本句翻译超时，请缩短句子后重试。")
                        cancel.wait(0.05)
                    output = child.stdout.read().decode("utf-8", errors="replace")
                    if child.returncode != 0:
                        raise RuntimeError("本地翻译未能完成，请停止后重试。")
                    if "[end of text]" not in output:
                        raise RuntimeError("本句译文没有完整生成，请缩短句子后重试。")
                    result = re.sub(r"\s*\[end of text\]\s*$", "", output).strip()
                    if not result:
                        raise RuntimeError("没有生成译文，请重试。")
                    self.check(cancel)
                    return result
                finally:
                    if child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait(timeout=2)
                    child.stdout.close()

    def speak(self, text, target, number_mode, player, cancel, first_audio):
        self.check(cancel)
        spoken = self.converters[target].convert(text)
        if target == "zh" and number_mode != "original":
            spoken, _ = spoken_numbers(spoken, number_mode)
        if target == "zh":
            from piper_phonemize import phonemize_espeak

            config = sherpa_onnx.GenerationConfig()
            config.sid, config.speed = 0, 1.0
            config.phoneme_codepoints = [
                [ord(c) for c in sentence]
                for sentence in phonemize_espeak(spoken, self.zh_tts.lang or "cmn")
            ]
            audio = self.zh_tts.generate("", config)
            self.check(cancel)
            if not len(audio.samples) or audio.sample_rate <= 0:
                raise RuntimeError("普通话译音生成失败。")
            first_audio()
            player.put(audio.samples, audio.sample_rate, cancel)
            return
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
        runtime.rng = np.random.default_rng(1234)
        runtime.codec_streaming_session.reset()
        request = runtime.build_voice_clone_request_rows(
            backend._default_voice_codes,
            backend._encoder.encode(safe_prepare_text(backend.to_phoneme(spoken))),
        )
        rate = int(runtime.codec_meta["codec_config"]["sample_rate"])
        pending, emitted = [], False

        def emit():
            nonlocal emitted
            self.check(cancel)
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
            self.check(cancel)
            pending.append(frame)
            if len(pending) >= 4:
                emit()

        runtime.generate_audio_frames(request, on_frame=callback)
        emit()
        if not emitted:
            raise RuntimeError("粤语译音生成失败。")

    def process(self, request, cancel, player, event):
        start = time.perf_counter()
        recognition_seconds = 0.0
        if request.kind == "speak":
            self.speak(
                request.text,
                request.source,
                request.number_mode,
                player,
                cancel,
                lambda: event("first_audio", time.perf_counter() - start),
            )
            return
        if request.kind == "file":
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
            self.speak(
                translated,
                target,
                request.number_mode,
                player,
                cancel,
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
    def __init__(self, segment, error, paragraph=False, segmenter_factory=None):
        super().__init__(
            "microphone", segment, error, paragraph=paragraph, segmenter_factory=segmenter_factory
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
