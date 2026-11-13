"""CLI entry; help and argument errors do not load models or open audio devices."""

import argparse


def main():
    parser = argparse.ArgumentParser(description="粤普双向离线翻译（Windows 实验版）")
    parser.add_argument("--muted", action="store_true", help="生成译音但不播放，用于本地验证")
    args = parser.parse_args()
    from .desktop_qt import main as run_window

    run_window(muted=args.muted)
