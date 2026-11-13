"""Explicit cloud opt-in and optional current-Windows-user encrypted credentials."""

import base64
import ctypes
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

REGIONS = {"beijing": "cn-beijing", "singapore": "ap-southeast-1"}


@dataclass(frozen=True)
class CloudConfig:
    api_key: str = field(default="", repr=False)
    region: str = "beijing"
    workspace: str = ""
    timeout: int = 8

    def validate(self):
        if self.region not in REGIONS:
            raise ValueError("请选择北京或新加坡服务地域。")
        if self.workspace and not re.fullmatch(r"[A-Za-z0-9-]{1,64}", self.workspace):
            raise ValueError("业务空间 ID 只能包含英文字母、数字和连字符，最多 64 位。")
        if not isinstance(self.timeout, int) or not 3 <= self.timeout <= 30:
            raise ValueError("联网超时须为 3–30 秒。")
        if not re.fullmatch(r"[\x21-\x7e]{8,512}", self.api_key):
            raise ValueError("请填写有效的百炼 API Key，不要包含空格或换行。")
        return self

    @property
    def endpoint(self):
        self.validate()
        if self.workspace:
            host = f"{self.workspace}.{REGIONS[self.region]}.maas.aliyuncs.com"
        else:
            host = (
                "dashscope.aliyuncs.com"
                if self.region == "beijing"
                else "dashscope-intl.aliyuncs.com"
            )
        return f"https://{host}/compatible-mode/v1/chat/completions"


def settings_path():
    return (
        Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share"))
        / "YuePuTranslate"
        / "cloud.json"
    )


def protect(data, decrypt=False):
    """DPAPI binds secrets to this Windows login; it is not portable encryption."""
    if os.name != "nt":
        raise RuntimeError("仅 Windows 支持加密记住密钥；可改用仅本次运行。")

    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    raw = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(raw, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        ok = crypt.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)
        )
    else:
        ok = crypt.CryptProtectData(
            ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)
        )
    if not ok:
        raise RuntimeError("Windows 无法保护或读取密钥，请重新输入，或选择仅本次运行。")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def save_settings(config, remember=False, path=None):
    """Never persists the enabled/upload consent; every app start is offline."""
    path = Path(path) if path is not None else settings_path()
    if not remember:
        path.unlink(missing_ok=True)
        return
    config.validate()
    secret = base64.b64encode(protect(config.api_key.encode("ascii"))).decode("ascii")
    value = dict(
        version=1,
        key_dpapi=secret,
        region=config.region,
        workspace=config.workspace,
        timeout=config.timeout,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    try:
        temp.write_text(json.dumps(value), encoding="utf-8")
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def load_settings(path=None):
    path = Path(path) if path is not None else settings_path()
    if not path.exists():
        return CloudConfig(), False
    try:
        if path.stat().st_size > 16384:
            raise ValueError()
        value = json.loads(path.read_text(encoding="utf-8"))
        if value["version"] != 1:
            raise ValueError()
        key = protect(base64.b64decode(value["key_dpapi"], validate=True), decrypt=True).decode(
            "ascii"
        )
        config = CloudConfig(key, value["region"], value["workspace"], value["timeout"]).validate()
        return config, True
    except (KeyError, TypeError, ValueError, OSError, RuntimeError):
        raise RuntimeError(
            "已保存的联网配置无法读取，本次仍为离线模式；请在设置中重新输入或清除。"
        ) from None
