"""Bounded provider contracts; no SDK, file upload service or request logging."""

import base64
import io
import json
import wave

from .cloud_config import CloudConfig

MAX_INPUT = 1400000
MAX_RESPONSE = 65536
ASR_MODEL = "qwen3-asr-flash"
MT_MODEL = "qwen-mt-flash"

ERRORS = {
    "auth": "密钥无效或没有模型权限，请检查密钥与地域",
    "quota": "额度不足或请求受限，请检查百炼账户",
    "timeout": "联网请求超时",
    "network": "无法连接云端，请检查网络",
    "redirect": "云端返回重定向，已拒绝转发密钥",
    "response": "云端返回无效、过长或不完整的结果",
    "request": "云端不接受当前请求，请检查模型服务配置",
    "server": "云端服务暂时不可用",
    "worker": "联网请求进程未正常完成",
}


class CloudError(RuntimeError):
    def __init__(self, code):
        self.code = code if code in ERRORS else "response"
        super().__init__(ERRORS[self.code])


def payload(operation, source, content):
    if source not in {"zh", "yue"}:
        raise ValueError("请选择粤语或普通话方向。")
    if operation == "asr":
        try:
            raw = base64.b64decode(content, validate=True)
            if len(raw) > 960044:
                raise ValueError()
            with wave.open(io.BytesIO(raw)) as audio:
                if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (
                    1,
                    2,
                    16000,
                ):
                    raise ValueError()
                frames = audio.getnframes()
                if not 0 < frames <= 480000 or len(audio.readframes(frames)) != frames * 2:
                    raise ValueError()
        except (ValueError, TypeError, EOFError, wave.Error):
            raise ValueError("联网识别仅接受最多 30 秒的 16 kHz 单声道 PCM16 WAV。") from None
        return dict(
            model=ASR_MODEL,
            messages=[
                dict(
                    role="user",
                    content=[
                        dict(
                            type="input_audio",
                            input_audio=dict(data="data:audio/wav;base64," + content),
                        )
                    ],
                )
            ],
            asr_options=dict(language=source, enable_itn=False),
            stream=False,
        )
    if operation == "translation" and isinstance(content, str) and 0 < len(content.strip()) <= 240:
        return dict(
            model=MT_MODEL,
            messages=[dict(role="user", content=content)],
            translation_options=dict(
                source_lang="auto", target_lang="Chinese" if source == "yue" else "Cantonese"
            ),
            stream=False,
            max_tokens=512,
        )
    raise ValueError("联网翻译每次接受 1–240 字。")


def decode_request(raw):
    if len(raw) > MAX_INPUT:
        raise ValueError("联网请求超出容量。")
    value = json.loads(raw)
    config = CloudConfig(**value["config"]).validate()
    return config, payload(value["operation"], value["source"], value["content"])


def response_text(raw, operation):
    try:
        if len(raw) > MAX_RESPONSE:
            raise ValueError()
        value = json.loads(raw)
        choice = value["choices"][0]
        if not isinstance(choice, dict):
            raise ValueError()
        if choice.get("finish_reason") not in {None, "stop"}:
            raise ValueError()
        text = choice["message"]["content"]
        if not isinstance(text, str) or len(text) > 1000:
            raise ValueError()
        if operation == "translation" and not text.strip():
            raise ValueError()
        return text.strip()
    except (ValueError, KeyError, IndexError, TypeError):
        raise CloudError("response") from None
