"""CLI entry; help and argument errors do not load models or open audio devices."""

import argparse
import io
import sys


def main():
    # Redirected Windows streams use the locale encoding; pythonw may have none.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors=stream.errors)
    parser = argparse.ArgumentParser(
        description="粤普双向翻译（Windows 实验版，默认离线，可选联网增强）"
    )
    parser.add_argument("--muted", action="store_true", help="生成译音但不播放，用于本地验证")
    args = parser.parse_args()
    from .desktop_qt import main as run_window

    run_window(muted=args.muted)
