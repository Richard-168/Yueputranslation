"""Prepare pinned Android AAR and llama.cpp source. SDK/NDK are installed separately."""

import argparse
import shutil
import zipfile
from pathlib import Path

from artifacts import fetch

ROOT = Path(__file__).resolve().parents[1]
LLAMA_COMMIT = "e1f7593c32e8dd782fc7addb908d0911260511ae"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path)
    args = parser.parse_args()
    target = ROOT / ".dependencies"
    target.mkdir(parents=True, exist_ok=True)
    specs = [
        (
            "sherpa-onnx-2.0.1.aar",
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/v2.0.1/sherpa-onnx-2.0.1.aar",
            49441341,
            "a8d09d1d32f3eb8520482c6d3d43fae674681c5b050385967c70a3c2c9bf0ee7",
        ),
        (
            "llama-source.zip",
            f"https://codeload.github.com/ggml-org/llama.cpp/zip/{LLAMA_COMMIT}",
            41363562,
            "265fe897e08b810546e451345e746afc31c342dbce86b75f1dd2c82c93f7d95d",
        ),
    ]
    for name, url, size, expected in specs:
        path = target / name
        if args.cache and (args.cache / name).is_file() and not path.exists():
            shutil.copyfile(args.cache / name, path)
        fetch(url, path, size, expected)
    # Exclude web/example trees; none are needed for the JNI library. This also
    # avoids Windows MAX_PATH issues in the upstream web application's sources.
    with zipfile.ZipFile(target / "llama-source.zip") as archive:
        for item in archive.infolist():
            prefix, _, relative = item.filename.partition("/")
            if prefix != f"llama.cpp-{LLAMA_COMMIT}":
                raise ValueError("Unexpected source revision")
            if item.is_dir() or not relative:
                continue
            if "/" in relative and relative.split("/")[0] not in {
                "src",
                "include",
                "ggml",
                "cmake",
                "common",
                "vendor",
                "licenses",
            }:
                continue
            path = (target / "llama.cpp" / relative).resolve()
            if not path.is_relative_to((target / "llama.cpp").resolve()):
                raise ValueError("Source archive path escapes its directory")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(item))
    print("Android dependencies ready: sherpa-onnx 2.0.1, llama.cpp b12314")


if __name__ == "__main__":
    main()
