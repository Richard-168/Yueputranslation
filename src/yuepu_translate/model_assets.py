"""Shared model groups and disk status. Importing this module never connects."""

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .model_catalog import FILES, SOURCES
from .paths import DATA_DIR

GROUPS = {
    "base": ("基础模型", ("asr-wenet", "hymt2", "vad", "tts-zh", "canto")),
    "pro": ("pro 复核", ("song-asr-large",)),
    "vocals": ("文件人声分离", ("song-separator",)),
}


@dataclass(frozen=True)
class Asset:
    name: str
    size: int
    digest: str
    url: str


def assets(folders):
    return [
        Asset(f"models/{folder}/{name}", size, digest, SOURCES[folder] + quote(name))
        for folder in folders
        for name, size, digest in FILES[folder]
    ]


def model_path(root, asset):
    path = root / asset.name
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("模型文件路径指向数据目录以外。")
    return path


def has_size(path: Path, size: int):
    return path.is_file() and path.stat().st_size == size


def partial_path(path, asset):
    partial = path.with_name(f"{path.name}.{asset.digest[:16]}.part")
    if partial.is_symlink():
        raise ValueError("模型临时文件路径无效。")
    return partial


def ready(folders, root=DATA_DIR):
    try:
        return all(has_size(model_path(root, asset), asset.size) for asset in assets(folders))
    except (ValueError, OSError):
        return False


def format_size(size):
    if size >= 1024**3:
        return f"{size / 1024**3:.2f} GiB"
    return f"{size / 1024**2:.0f} MiB"
