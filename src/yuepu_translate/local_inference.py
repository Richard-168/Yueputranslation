"""Owned, resident llama.cpp processes, bound and called only on loopback."""

import atexit
import base64
import errno
import io
import json
import os
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

from .inference_control import InferenceCancelled as InferenceCancelled
from .inference_control import check_cancel
from .paths import ASR_MODEL, ASR_PROJECTOR, DATA_DIR, MT_MODEL
from .preferences import cache_directory

SERVER = "runtime/llama-b12314/llama-server.exe"
COMPLETION = "runtime/llama-b12314/llama-completion.exe"


class LoopbackDenied(RuntimeError):
    """The OS explicitly denied a local socket operation."""


def check_loopback_permission(error):
    cause = getattr(error, "reason", error)
    if (
        isinstance(cause, PermissionError)
        or getattr(cause, "winerror", None) == 10013
        or getattr(cause, "errno", None) in (errno.EACCES, errno.EPERM, 10013)
    ):
        raise LoopbackDenied(
            "系统拒绝了本机推理服务的 127.0.0.1 连接。使用 flash 可通过本地进程完成识别和翻译。"
        ) from error


class LocalInference:
    """One serial inference slot. Cancellation terminates this owned process.

    Never invokes a shell, uses system proxies, logs audio/text, or downloads
    assets. The window owns the shared translator; each pro task owns its ASR.
    The owner closes its process after the last request has finished.
    """

    def __init__(self, role, source="yue", root=DATA_DIR, threads=4):
        if role not in {"asr", "translation"} or source not in {"yue", "zh"}:
            raise ValueError("不支持的本地推理配置。")
        self.role, self.source, self.root = role, source, Path(root)
        if not isinstance(threads, int) or not 1 <= threads <= 16:
            raise ValueError("推理线程数必须在 1–16 之间。")
        self.threads = threads
        self.child = self.temp = None
        self.using_completion = False
        self._generation_lock = threading.Lock()
        self.key = secrets.token_urlsafe(24)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def runtime_path(self, relative):
        path = self.root / relative
        bundled = os.environ.get("YUEPU_RUNTIME_DATA_DIR")
        if self.root == DATA_DIR and bundled and not path.is_file():
            return Path(bundled) / relative
        return path

    def check_files(self):
        required = [ASR_MODEL, ASR_PROJECTOR] if self.role == "asr" else [MT_MODEL]
        if not self.runtime_path(SERVER).is_file() or any(
            not (self.root / path).is_file() for path in required
        ):
            raise RuntimeError(
                "pro 段落模型不完整，请准备 song-asr-large 和本地推理程序；也可选择 flash。"
                if self.role == "asr"
                else "本地翻译模型不完整，请准备 hymt2 和本地推理程序。"
            )

    def start(self, cancel):
        check_cancel(cancel)
        if self.child is not None:
            if self.child.poll() is None:
                return
            self.close()
        self.check_files()
        try:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                self.port = probe.getsockname()[1]
        except OSError as exc:
            check_loopback_permission(exc)
            raise RuntimeError("无法为本机推理服务分配端口，请稍后重试。") from exc
        model = ASR_MODEL if self.role == "asr" else MT_MODEL
        command = [
            str(self.runtime_path(SERVER)),
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
            self.temp = tempfile.TemporaryDirectory(prefix="yuepu-asr-", dir=cache_directory())
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
            atexit.register(self.close)
            deadline = time.monotonic() + 60
            loading = False
            while time.monotonic() < deadline:
                check_cancel(cancel)
                if self.child.poll() is not None:
                    raise RuntimeError("本地推理程序启动失败，请检查固定版本和模型文件。")
                try:
                    with self.opener.open(self.url + "/health", timeout=0.3) as response:
                        if response.status == 200:
                            return
                except urllib.error.HTTPError as exc:
                    exc.close()
                    if exc.code != 503:
                        raise RuntimeError(
                            f"本机推理服务就绪检查失败（HTTP {exc.code}）。"
                        ) from exc
                    loading = True
                except OSError as exc:
                    check_loopback_permission(exc)
                cancel.wait(0.05)
            role = "复核识别" if self.role == "asr" else "翻译"
            detail = "仍在加载模型" if loading else "未能建立本机连接"
            raise TimeoutError(f"本地{role}服务在 60 秒内未就绪（{detail}）。")
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
                check_loopback_permission(cause)
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
        import soundfile as sf

        data = np.asarray(samples, dtype=np.float32)
        if data.ndim != 1 or not 0 < len(data) <= 30 * 16000 or not np.isfinite(data).all():
            raise ValueError("歌曲识别每次接受不超过 30 秒的有效单声道音频。")
        self.start(cancel)
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

    def translate(self, text, cancel, *, source=None):
        if not text.strip() or len(text) > 240:
            raise ValueError("本地翻译每段接受 1–240 字。")
        source = self.source if source is None else source
        if source not in {"zh", "yue"}:
            raise ValueError("请选择粤语或普通话作为翻译方向。")
        target = "中文" if source == "yue" else "粤语"
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
        while not self._generation_lock.acquire(timeout=0.05):
            check_cancel(cancel)
        try:
            if not self.using_completion:
                try:
                    self.start(cancel)
                    return self._generate(prompt, cancel)
                except LoopbackDenied:
                    if not self.runtime_path(COMPLETION).is_file():
                        raise
                    self.using_completion = True
            return self._complete_without_socket(prompt, cancel)
        finally:
            self._generation_lock.release()

    def _generate(self, prompt, cancel):
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
            raise RuntimeError("没有生成译文，请停止后重试。")
        return text

    def _complete_without_socket(self, prompt, cancel):
        check_cancel(cancel)
        # llama-completion reads the prompt from a file. Keep the user's text out
        # of process arguments and remove the temporary file on every exit path.
        with tempfile.TemporaryDirectory(prefix="yuepu-mt-", dir=cache_directory()) as directory:
            prompt_path = Path(directory) / "prompt.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
            command = [
                str(self.runtime_path(COMPLETION)),
                "-m",
                str(self.root / MT_MODEL),
                "--offline",
                "--no-conversation",
                "--no-display-prompt",
                "--simple-io",
                "--color",
                "off",
                "-c",
                "2048",
                "-t",
                str(self.threads),
                "-ngl",
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
                "384",
                "-f",
                str(prompt_path),
            ]
            self.child = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            child = self.child
            atexit.register(self.close)
            try:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    check_cancel(cancel)
                    try:
                        output, _ = child.communicate(timeout=0.1)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                else:
                    raise TimeoutError("本地逐句翻译超时，请缩短内容后重试。")
                check_cancel(cancel)
                text = output.decode("utf-8").strip()
                if child.returncode or not text.endswith("[end of text]"):
                    raise RuntimeError("本地逐句翻译未完整生成，请缩短内容后重试。")
                text = text.removesuffix("[end of text]").strip()
                if not text:
                    raise RuntimeError("本地逐句翻译未生成译文。")
                return text
            finally:
                self.close()
                child.communicate()

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
        self.child = None
        atexit.unregister(self.close)
        if self.temp is not None:
            self.temp.cleanup()
            self.temp = None
