"""App-local launcher: keep Python worker pipes and installed assets relocatable."""

import ctypes
import os
import sys
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    os.environ.setdefault("YUEPU_DATA_DIR", str(root / "data"))
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    # GUI launches through pythonw; owned capture/cloud helpers need normal
    # standard streams and are already created with CREATE_NO_WINDOW.
    sys.executable = str(root / "python/python.exe")
    try:
        from yuepu_translate.cli import main as run

        run()
    except Exception:
        ctypes.windll.user32.MessageBoxW(
            None,
            "启动未完成。请确认安装文件完整，或运行安装包重新安装。\n已有设置和导出文件不会被删除。",
            "粤普同传",
            0x10,
        )
        raise


if __name__ == "__main__":
    main()
