"""Compatibility entry for existing local experiments; implementation lives in src."""

import _bootstrap  # noqa: F401

from yuepu_translate.transcript_model import TranscriptEntry, TranscriptModel

__all__ = ["TranscriptEntry", "TranscriptModel"]
