"""Session owner: cloud is opt-in, first provider failure latches local fallback."""

import os

from .cloud_client import CloudClient
from .cloud_protocol import CloudError
from .inference_control import check_cancel
from .languages import UNSUPPORTED_SCRIPT
from .paragraphs import accept_punctuation


class SessionInference:
    def __init__(self, source, config, emit, local_factory=None, roles=("asr", "translation")):
        if local_factory is None:
            from .local_inference import LocalInference

            local_factory = LocalInference
        self.local = {
            role: local_factory(role, source, threads=min(12, os.cpu_count() or 4))
            for role in roles
        }
        self.cloud = CloudClient(config, source) if config is not None else None
        self.online = self.cloud is not None
        self.emit = emit

    def start(self, cancel):
        for inference in self.local.values():
            inference.start(cancel)
        # Fallback is ready before any upload; this warm-up never uses the cloud.
        self.local["translation"].translate("你好。", cancel)
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
            inference.stop()
        for inference in self.local.values():
            inference.close()


def process_text(request, config, engine, player, cancel, emit):
    """Text entry shares the same one-failure latch and stays within one UI job."""
    import time

    from .desktop_engine import Cancelled
    from .inference_control import InferenceCancelled

    inference = SessionInference(request.source, config, emit, roles=("translation",))
    try:
        emit("status", "正在准备联网翻译与本地回退…")
        inference.start(cancel)
        emit("source", request.text)
        start = time.perf_counter()
        translated = inference.translate(request.text, cancel)
        emit(
            "translation",
            dict(
                text=translated,
                recognition_seconds=0,
                translation_seconds=time.perf_counter() - start,
            ),
        )
        if request.autoplay:
            target = "zh" if request.source == "yue" else "yue"
            engine.speak(translated, target, request.number_mode, player, cancel, lambda: None)
    except InferenceCancelled:
        raise Cancelled() from None
    finally:
        inference.close()
