"""Owned, resident llama.cpp processes, bound and called only on loopback."""

import base64
import io
import json
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

from .paths import DATA_DIR

ASR_DIR = "models/song-asr-large"
ASR_MODEL = f"{ASR_DIR}/Qwen3-ASR-1.7B-Q8_0.gguf"
ASR_PROJECTOR = f"{ASR_DIR}/mmproj-Qwen3-ASR-1.7B-Q8_0.gguf"
MT_MODEL = "models/hymt2/Hy-MT2-1.8B-Q4_K_M.gguf"
SERVER = "runtime/llama-b12314/llama-server.exe"


class InferenceCancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel.is_set():
        raise InferenceCancelled()


class LocalInference:
    """One serial inference slot. Cancellation terminates this owned process.

    Never invokes a shell, uses system proxies, logs audio/text, or downloads
    assets. Call close() from the owner thread after each session or load error.
    """

    def __init__(self, role, source="yue", root=DATA_DIR, threads=4):
        if role not in {"asr", "translation"} or source not in {"yue", "zh"}:
            raise ValueError("不支持的本地推理配置。")
        self.role, self.source, self.root = role, source, Path(root)
        if not isinstance(threads, int) or not 1 <= threads <= 16:
            raise ValueError("推理线程数必须在 1–16 之间。")
        self.threads = threads
        self.child = self.temp = None
        self.key = secrets.token_urlsafe(24)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def start(self, cancel):
        check_cancel(cancel)
        required = [SERVER, ASR_MODEL, ASR_PROJECTOR] if self.role == "asr" else [SERVER, MT_MODEL]
        if any(not (self.root / path).is_file() for path in required):
            raise RuntimeError(
                "歌曲模型文件不完整，请按 docs/development.md 准备 Qwen3-ASR-1.7B 和本地推理程序。"
            )
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            self.port = probe.getsockname()[1]
        model = ASR_MODEL if self.role == "asr" else MT_MODEL
        command = [
            str(self.root / SERVER),
            "-m",
            str(self.root / model),
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--offline",
            "--api-key",
            self.key,
            "--cors-origins",
            "localhost",
            "-ngl",
            "0",
            "-t",
            str(self.threads),
            "-tb",
            str(self.threads),
            "-c",
            "4096" if self.role == "asr" else "2048",
            "--parallel",
            "1",
        ]
        if self.role == "asr":
            self.temp = tempfile.TemporaryDirectory(prefix="yuepu-asr-")
            template = Path(self.temp.name) / "language.jinja"
            language = "Cantonese" if self.source == "yue" else "Chinese"
            template.write_text(
                "{%- if messages and messages[0]['role'] != 'system' -%}"
                "{{- '<|im_start|>system\\n<|im_end|>\\n' -}}{%- endif -%}"
                "{%- for message in messages -%}"
                "{{- '<|im_start|>' + message['role'] + '\\n' + message['content'] "
                "+ '<|im_end|>\\n' -}}{%- endfor -%}"
                "{%- if add_generation_prompt -%}{{- '<|im_start|>assistant\\nlanguage "
                + language
                + "<asr_text>' -}}{%- endif -%}",
                encoding="utf-8",
            )
            command += [
                "--mmproj",
                str(self.root / ASR_PROJECTOR),
                "--no-mmproj-offload",
                "--jinja",
                "--chat-template-file",
                str(template),
            ]
        try:
            self.child = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                check_cancel(cancel)
                if self.child.poll() is not None:
                    raise RuntimeError("本地推理程序启动失败，请检查固定版本和模型文件。")
                try:
                    with self.opener.open(self.url + "/health", timeout=0.3) as response:
                        if response.status == 200:
                            return
                except (OSError, urllib.error.URLError):
                    pass
                cancel.wait(0.05)
            raise TimeoutError("歌曲模型加载超时，请停止后重试。")
        except BaseException:
            self.close()
            raise

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def request(self, route, payload, cancel, timeout=30):
        check_cancel(cancel)
        if self.child is None or self.child.poll() is not None:
            raise RuntimeError("本地推理进程已退出，请停止后重新开始。")
        result, failure = [], []
        request = urllib.request.Request(
            self.url + route,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.key},
        )

        def receive():
            try:
                with self.opener.open(request, timeout=timeout) as response:
                    raw = response.read(1024 * 1024 + 1)
                    if len(raw) > 1024 * 1024:
                        raise RuntimeError("本地推理响应超出容量。")
                    result.append(json.loads(raw))
            except Exception as exc:
                failure.append(exc)

        worker = threading.Thread(target=receive, daemon=True)
        worker.start()
        deadline = time.monotonic() + timeout
        try:
            while worker.is_alive():
                check_cancel(cancel)
                if time.monotonic() >= deadline:
                    raise TimeoutError("本段处理超时，请暂停播放后重试。")
                worker.join(0.05)
            check_cancel(cancel)
            if failure:
                # Do not expose response bodies, audio, text or the ephemeral key.
                cause = failure[0]
                reason = (
                    f"HTTP {cause.code}"
                    if isinstance(cause, urllib.error.HTTPError)
                    else ("超时" if isinstance(cause, TimeoutError) else "连接或响应异常")
                )
                role = "识别" if self.role == "asr" else "翻译"
                raise RuntimeError(f"本地{role}请求失败（{reason}），请停止后重试。") from cause
            return result[0]
        except BaseException:
            self.close()
            worker.join(2)
            raise

    def transcribe(self, samples, cancel):
        data = np.asarray(samples, dtype=np.float32)
        if data.ndim != 1 or not 0 < len(data) <= 30 * 16000 or not np.isfinite(data).all():
            raise ValueError("歌曲识别每次接受不超过 30 秒的有效单声道音频。")
        buffer = io.BytesIO()
        sf.write(buffer, data, 16000, format="WAV", subtype="PCM_16")
        result = self.request(
            "/v1/chat/completions",
            {
                "messages": [
                    {"role": "system", "content": ""},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {
                                    "data": base64.b64encode(buffer.getvalue()).decode("ascii"),
                                    "format": "wav",
                                },
                            }
                        ],
                    },
                ],
                "temperature": 0,
                "max_tokens": 256,
                "stream": False,
                "cache_prompt": False,
            },
            cancel,
        )
        choice = result["choices"][0]
        if choice.get("finish_reason") == "length":
            raise RuntimeError("本段识别超出输出上限，未作为确认字幕保留。")
        text = choice["message"]["content"].strip()
        if "<asr_text>" in text:
            text = text.split("<asr_text>", 1)[1].strip()
        return text

    def translate(self, text, cancel):
        if not text.strip() or len(text) > 240:
            raise ValueError("歌曲字幕每段接受 1–240 字。")
        target = "中文" if self.source == "yue" else "粤语"
        user = f"将以下文本翻译为{target}，注意只需要输出翻译后的结果，不要额外解释：\n\n" + text
        return self.generate(user, cancel)

    def punctuate(self, text, cancel):
        from .paragraphs import accept_punctuation

        if not text.strip() or len(text) > 240:
            raise ValueError("句末标点复核每次接受 1–240 字。")
        result = self.generate(
            "请只为以下文本补充正确的标点和断句，不增删或改动任何文字，只输出正文：\n\n" + text,
            cancel,
        )
        return accept_punctuation(text, result)

    def generate(self, user, cancel):
        prompt = "<｜hy_begin▁of▁sentence｜><｜hy_User｜>" + user + "<｜hy_Assistant｜>"
        result = self.request(
            "/completion",
            {
                "prompt": prompt,
                "temperature": 0.7,
                "top_k": 20,
                "top_p": 0.6,
                "repeat_penalty": 1.05,
                "seed": 42,
                "n_predict": 384,
                "stream": False,
                "cache_prompt": False,
            },
            cancel,
        )
        if result.get("stopped_limit") or result.get("truncated"):
            raise RuntimeError("本段译文未完整生成，请缩短内容后重试。")
        text = result.get("content", "").strip()
        if not text:
            raise RuntimeError("没有生成歌曲译文，请停止后重试。")
        return text

    def stop(self):
        if self.child is not None and self.child.poll() is None:
            self.child.terminate()

    def close(self):
        self.stop()
        if self.child is not None and self.child.poll() is None:
            try:
                self.child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=2)
        if self.temp is not None:
            self.temp.cleanup()
            self.temp = None
