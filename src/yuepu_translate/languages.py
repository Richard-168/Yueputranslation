"""Shared language/script boundary for local and cloud recognition."""

import re

ASR_LANGUAGES = frozenset({"zh", "yue", "en"})
UNSUPPORTED_SCRIPT = re.compile(
    r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f"
    r"\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7ff]"
)
