"""Compatibility entry for existing local experiments; implementation lives in src."""

import _bootstrap  # noqa: F401

from yuepu_translate.desktop_qt import STYLE, PairDelegate, Window

__all__ = ["STYLE", "PairDelegate", "Window"]

if __name__ == "__main__":
    from yuepu_translate.cli import main

    main()
