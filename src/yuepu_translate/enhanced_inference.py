"""Session owner: cloud is opt-in, first provider failure latches local fallback."""

import os

from .cloud_client import CloudClient
from .cloud_protocol import CloudError
from .inference_control import check_cancel, speak_translation
from .languages import UNSUPPORTED_SCRIPT
from .paragraphs import accept_punctuation
from .translation_state import IncrementalTranslation


class SessionInference:
    def __init__(
        self, source, config, emit, local_factory=None, roles=("asr", "translation"), *, engine=None
    ):
        if local_factory is None:
            from .local_inference import LocalInference

            local_factory = LocalInference
        self.source = source
        self.shared_translation = engine.translator if engine is not None else None
        self.local = {}
        for role in roles:
            if role == "translation" and self.shared_translation is not None:
                self.local[role] = self.shared_translation
            else:
                self.local[role] = local_factory(role, source, threads=min(12, os.cpu_count() or 4))
        self.cloud = CloudClient(config, source) if config is not None else None
        self.online = self.cloud is not None
        self.emit = emit

    def start(self, cancel):
        check_cancel(cancel)
        if self.online:
            for inference in self.local.values():
                inference.check_files()
        elif "asr" in self.local:
            # Load the paragraph reviewer while the independent light ASR starts listening.
            self.local["asr"].start(cancel)
        self.state("cloud_pending" if self.online else "offline")

    def state(self, mode, reason=""):
        cloud = self.cloud
        self.emit(
            "network_state",
            dict(
                mode=mode,
                reason=reason,
                requests=cloud.requests if cloud else 0,
                audio_seconds=cloud.audio_seconds if cloud else 0,
                text_characters=cloud.text_characters if cloud else 0,
            ),
        )

    def call(self, method, value, cancel):
        check_cancel(cancel)
        if self.online:
            try:
                result = getattr(self.cloud, method)(value, cancel)
                if UNSUPPORTED_SCRIPT.search(result):
                    raise CloudError("response")
                self.state("cloud")
                return result
            except CloudError as exc:
                check_cancel(cancel)
                self.online = False
                self.cloud.close()
                self.state("fallback", str(exc))
        role = "asr" if method == "transcribe" else "translation"
        if role == "translation" and self.shared_translation is not None:
            return self.shared_translation.translate(value, cancel, source=self.source)
        return getattr(self.local[role], method)(value, cancel)

    def transcribe(self, samples, cancel):
        return self.call("transcribe", samples, cancel)

    def translate(self, text, cancel):
        return self.call("translate", text, cancel)

    def punctuate(self, text, cancel):
        check_cancel(cancel)
        if self.online:
            # Qwen-ASR already returns punctuation; Qwen-MT is not a punctuation model.
            # Keep the recognized words unchanged instead of paying a free-form LLM to rewrite them.
            return accept_punctuation(text, text)
        return self.local["translation"].punctuate(text, cancel)

    def close(self):
        if self.cloud:
            self.cloud.close()
        for inference in self.local.values():
            if inference is not self.shared_translation:
                inference.close()


def process_short_request(request, config, engine, player, cancel, emit):
    """Text and flash files share opt-in translation and the one-failure latch."""
    import time

    from .desktop_engine import Cancelled
    from .inference_control import InferenceCancelled

    inference = SessionInference(
        request.source, config, emit, roles=("translation",), engine=engine
    )
    try:
        emit("status", "正在准备联网翻译…")
        inference.start(cancel)
        text = request.text
        recognition_seconds = 0
        if request.kind == "file":
            import soundfile as sf

            start = time.perf_counter()
            info = sf.info(request.path)
            if (
                not 0 < info.duration <= 15
                or info.channels not in {1, 2}
                or not 8000 <= info.samplerate <= 192000
            ):
                raise ValueError("flash 文件仅支持不超过 15 秒的单声道或双声道音频。")
            samples, rate = sf.read(request.path, frames=info.samplerate * 15 + 1, dtype="float32")
            text = engine.recognize(samples, rate, cancel, request.source, emit)
            recognition_seconds = time.perf_counter() - start
        emit("source", text)
        start = time.perf_counter()
        translated = IncrementalTranslation().update(
            text, "", lambda part: inference.translate(part, cancel)
        )
        emit(
            "translation",
            dict(
                text=translated,
                recognition_seconds=recognition_seconds,
                translation_seconds=time.perf_counter() - start,
            ),
        )
        if request.autoplay:
            target = "zh" if request.source == "yue" else "yue"
            speak_translation(engine, translated, target, request.number_mode, player, cancel, emit)
    except InferenceCancelled:
        raise Cancelled() from None
    finally:
        inference.close()
