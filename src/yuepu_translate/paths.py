"""One data directory shared by inference and model preparation."""

import os
from pathlib import Path


def data_dir():
    override = os.environ.get("YUEPU_DATA_DIR")
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError("YUEPU_DATA_DIR must be an absolute path")
        return path.resolve()
    # Retain existing multi-GB assets and the user's working environment.
    checkout = Path(__file__).resolve().parents[2]
    if (checkout / "pyproject.toml").is_file() and (checkout / "experiments/offline-poc").is_dir():
        return checkout / "experiments/offline-poc"
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "YuePuTranslate"


DATA_DIR = data_dir()
ASR_DIR = "models/song-asr-large"
ASR_MODEL = f"{ASR_DIR}/Qwen3-ASR-1.7B-Q8_0.gguf"
ASR_PROJECTOR = f"{ASR_DIR}/mmproj-Qwen3-ASR-1.7B-Q8_0.gguf"
MT_MODEL = "models/hymt2/Hy-MT2-1.8B-Q4_K_M.gguf"
