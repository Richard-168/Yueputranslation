"""Allow existing experiment commands to use the canonical source checkout."""

import sys
from pathlib import Path

source = str(Path(__file__).resolve().parents[2] / "src")
if source not in sys.path:
    sys.path.insert(0, source)
