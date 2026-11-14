"""Shared live-input sensitivity choices; file detection uses its own unchanged gate."""

from dataclasses import dataclass

DEFAULT_SENSITIVITY = "standard"


@dataclass(frozen=True)
class VoiceProfile:
    label: str
    description: str
    threshold: float
    min_speech_seconds: float
    max_gain: float


VOICE_PROFILES = {
    "standard": VoiceProfile(
        "标准",
        "适合嘈杂环境，减少轻微背景触发；较轻的短句可能漏听。",
        0.5,
        0.128,
        1.0,
    ),
    "sensitive": VoiceProfile(
        "灵敏",
        "适合手机外放、轻声和短句；更容易收到背景音乐或旁人讲话。",
        0.35,
        0.096,
        8.0,
    ),
}


def voice_profile(value):
    if not isinstance(value, str) or value not in VOICE_PROFILES:
        raise ValueError("收音灵敏度须为标准或灵敏。")
    return VOICE_PROFILES[value]
