"""Compatibility entry for existing local experiments; implementation lives in src."""

import _bootstrap  # noqa: F401

from yuepu_translate.desktop_engine import (
    ASR_LANGUAGES,
    MAX_LIVE_SEGMENT_SECONDS,
    UNSUPPORTED_SCRIPT,
    AudioPlayer,
    Cancelled,
    Engine,
    Microphone,
    PlaybackProcessor,
    Request,
    SpeechSegmenter,
    SystemAudio,
    make_vad,
)

__all__ = [
    "ASR_LANGUAGES",
    "UNSUPPORTED_SCRIPT",
    "MAX_LIVE_SEGMENT_SECONDS",
    "AudioPlayer",
    "Cancelled",
    "Engine",
    "Microphone",
    "PlaybackProcessor",
    "Request",
    "SpeechSegmenter",
    "SystemAudio",
    "make_vad",
]
