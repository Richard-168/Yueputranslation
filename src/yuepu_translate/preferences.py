"""Single owner of desktop defaults and configurable temporary/export directories."""

import tempfile
from dataclasses import dataclass, fields
from pathlib import Path

from PySide6.QtCore import QSettings

from .audio_profile import DEFAULT_SENSITIVITY, voice_profile


def settings_store():
    return QSettings(QSettings.IniFormat, QSettings.UserScope, "YuePuTranslate", "Desktop")


@dataclass(frozen=True)
class Preferences:
    mode: str = "pro"
    direction: str = "yue"
    audio_source: str = "microphone"
    sensitivity: str = DEFAULT_SENSITIVITY
    autoplay: bool = True
    font_size: int = 15
    smooth: bool = True
    number_mode: str = "original"
    vocals: bool = False
    cache_directory: str = ""
    export_directory: str = ""

    def validate(self):
        voice_profile(self.sensitivity)
        for name, allowed in (
            ("mode", {"flash", "pro"}),
            ("direction", {"yue", "zh"}),
            ("audio_source", {"microphone", "system"}),
            ("number_mode", {"original", "amount", "identifier"}),
        ):
            if getattr(self, name) not in allowed:
                raise ValueError("无效的首选项：" + name)
        if type(self.font_size) is not int or not 12 <= self.font_size <= 24:
            raise ValueError("字幕字号须在 12–24 之间。")
        if any(type(getattr(self, name)) is not bool for name in ("autoplay", "smooth", "vocals")):
            raise ValueError("无效的开关首选项。")
        for name in ("cache_directory", "export_directory"):
            value = getattr(self, name)
            if not isinstance(value, str) or (value and not Path(value).is_absolute()):
                raise ValueError("文件位置须为绝对路径，或留空使用默认位置。")
        return self


def load_preferences(settings=None):
    settings = settings if settings is not None else settings_store()
    defaults = Preferences()
    values = {}
    for field in fields(defaults):
        value = settings.value("defaults/" + field.name, getattr(defaults, field.name))
        if field.name == "mode" and value == "paragraph":
            value = "pro"
        if field.name in {"autoplay", "smooth", "vocals"}:
            if value in (True, "true", "1", 1):
                value = True
            elif value in (False, "false", "0", 0):
                value = False
            else:
                raise ValueError("已保存的首选项开关无效。")
        elif field.name == "font_size":
            value = int(value)
        values[field.name] = value
    return Preferences(**values).validate()


def save_preferences(preferences, settings=None):
    preferences.validate()
    # Probe only explicitly chosen locations. Never remove/move their existing files.
    for name in ("cache_directory", "export_directory"):
        if value := getattr(preferences, name):
            path = Path(value)
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=path):
                pass
    settings = settings if settings is not None else settings_store()
    for field in fields(preferences):
        settings.setValue("defaults/" + field.name, getattr(preferences, field.name))
    settings.sync()
    if settings.status() != QSettings.NoError:
        raise OSError("无法保存首选项，请检查本机目录权限。")


def default_cache_directory():
    # These files are short-lived prompts/templates, not installed model data.
    # The OS temporary directory is already selected for this process's write access.
    return Path(tempfile.gettempdir()) / "YuePuTranslate/cache"


def cache_directory():
    configured = load_preferences().cache_directory
    path = Path(configured) if configured else default_cache_directory()
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path):
            pass
    except OSError:
        raise RuntimeError(
            "临时缓存目录无法写入，请在“设置 → 文件位置”选择可写的缓存目录后重新加载模型。"
        ) from None
    return path


def export_directory(preferences):
    return (
        Path(preferences.export_directory)
        if preferences.export_directory
        else Path.home() / "Documents"
    )
