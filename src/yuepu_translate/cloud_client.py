"""A cloud request never removes the parent interpreter's offline socket guard."""

import base64
import io
import json
import os
import subprocess
import sys
import threading
import time
import wave
from dataclasses import asdict
from pathlib import Path

from .cloud_protocol import MAX_INPUT, CloudError, payload
from .inference_control import check_cancel


class CloudClient:
    def __init__(self, config, source):
        self.config = config.validate()
        self.source = source
        self.child = None
        self.requests = 0
        self.audio_seconds = 0
        self.text_characters = 0

    def request(self, operation, content, cancel):
        check_cancel(cancel)
        payload(operation, self.source, content)  # Validate before creating a process.
        raw = json.dumps(
            dict(
                config=asdict(self.config), operation=operation, source=self.source, content=content
            )
        ).encode("utf-8")
        if len(raw) > MAX_INPUT:
            raise ValueError("联网请求超出容量。")
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
        for name in ("DASHSCOPE_API_KEY", "YUEPU_DASHSCOPE_API_KEY"):
            environment.pop(name, None)
        try:
            self.child = subprocess.Popen(
                [sys.executable, "-m", "yuepu_translate.cloud_worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=environment,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError:
            raise CloudError("worker") from None
        self.requests += 1
        if operation == "translation":
            self.text_characters += len(content)
        deadline = time.monotonic() + self.config.timeout
        completed = threading.Event()
        replies, errors = [], []

        def exchange():
            try:
                replies.append(self.child.communicate(raw)[0])
            except (OSError, ValueError) as exc:
                errors.append(exc)
            finally:
                completed.set()

        exchange_thread = threading.Thread(target=exchange, daemon=True)
        exchange_thread.start()
        try:
            while not completed.wait(0.05):
                check_cancel(cancel)
                if time.monotonic() >= deadline:
                    raise CloudError("timeout")
            check_cancel(cancel)
            if errors or not replies:
                raise CloudError("worker")
            try:
                value = json.loads(replies[0])
                if not isinstance(value, dict):
                    raise ValueError()
                if self.child.returncode != 0 or not isinstance(value.get("ok"), bool):
                    raise ValueError()
                if not value["ok"]:
                    raise CloudError(value.get("code"))
                text = value["text"]
                if not isinstance(text, str) or len(text) > 1000:
                    raise ValueError()
                return text
            except (TypeError, ValueError, KeyError):
                raise CloudError("worker") from None
        finally:
            self.close()
            exchange_thread.join(timeout=1)

    def transcribe(self, samples, cancel):
        import numpy as np

        data = np.asarray(samples, dtype=np.float32)
        if data.ndim != 1 or not 0 < len(data) <= 480000 or not np.isfinite(data).all():
            raise ValueError("联网识别每次接受最多 30 秒的有效单声道音频。")
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as audio:
            audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            audio.writeframes((np.clip(data, -1, 1) * 32767).astype("<i2").tobytes())
        self.audio_seconds += len(data) / 16000
        return self.request("asr", base64.b64encode(buffer.getvalue()).decode("ascii"), cancel)

    def translate(self, text, cancel):
        return self.request("translation", text, cancel)

    def close(self):
        if self.child is not None:
            if self.child.poll() is None:
                self.child.terminate()
                try:
                    self.child.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self.child.kill()
                    self.child.wait(timeout=1)
            for stream in (self.child.stdin, self.child.stdout):
                if stream:
                    stream.close()
