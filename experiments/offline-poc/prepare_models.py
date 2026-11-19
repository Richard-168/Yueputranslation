"""Bounded, public-source downloads for a disposable Windows offline probe."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import _bootstrap  # noqa: F401

from yuepu_translate.paths import DATA_DIR

ROOT = DATA_DIR
SOURCES = {
    "song-asr-large": ("ggml-org/Qwen3-ASR-1.7B-GGUF", "36a678687ba7d07a74ca70ccb0e36902e005fb80"),
    "song-asr": ("ggml-org/Qwen3-ASR-0.6B-GGUF", "928ab958557df9aa2ef1c93e0e83c7ad0933fae2"),
    "asr": (
        "csukuangfj/sherpa-onnx-wenetspeech-yue-u2pp-conformer-ctc-zh-en-cantonese-int8-2025-09-10",
        "c911764e8227cf372ee60adc75f7f407e5b8c905",
    ),
    "canto": ("typangaa/canto-tts-nano", "fe17418a293d9be85685ddf750b0cfef9c88abb4"),
    "llm": ("Qwen/Qwen3-1.7B-GGUF", "90862c4b9d2787eaed51d12237eafdfe7c5f6077"),
    "hymt": ("tencent/HY-MT1.5-1.8B-GGUF", "265b2e615a7dc9b06c435dc878829ad99a512ba2"),
    "hymt2": ("tencent/Hy-MT2-1.8B-GGUF", "a0c709d9fac510f2c807aa3af52872340dc37a4a"),
    "mandarin": ("csukuangfj/vits-melo-tts-zh_en", "a0d5c6a264c0ef92d70d8661d8cc502d79627cd6"),
}


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def valid(path: Path, spec: dict) -> bool:
    if not path.is_file() or path.stat().st_size != spec["size"]:
        return False
    if spec.get("sha256"):
        return sha256(path) == spec["sha256"]
    if spec.get("git_sha1"):
        digest = hashlib.sha1(f"blob {spec['size']}\0".encode())
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(2**20), b""):
                digest.update(chunk)
        return digest.hexdigest() == spec["git_sha1"]
    return True


def download(spec: dict) -> dict:
    path = ROOT / spec["local_path"]
    if not path.resolve().is_relative_to(ROOT):
        raise ValueError(f"Download destination escapes experiment: {path!s} -> {path.resolve()!s}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if valid(path, spec):
        return {**spec, "observed_sha256": sha256(path), "cached": True}
    partial = path.with_name(path.name + ".part")
    started = time.monotonic()
    received = 0
    last_log = started
    print(f"download {spec['local_path']} ({spec['size'] / 2**20:.1f} MiB)", flush=True)
    try:
        with (
            urllib.request.urlopen(spec["url"], timeout=30) as response,
            partial.open("wb") as output,
        ):
            while chunk := response.read(2**20):
                received += len(chunk)
                if received > spec["size"] or time.monotonic() - started > 600:
                    raise RuntimeError("Download size/deadline limit exceeded")
                output.write(chunk)
                if time.monotonic() - last_log > 10:
                    print(f"progress {path.name}: {received / 2**20:.0f} MiB", flush=True)
                    last_log = time.monotonic()
        if not valid(partial, spec):
            raise RuntimeError(f"Source digest or size mismatch: {path.name}")
        partial.replace(path)
    except Exception:
        # A bounded partial from this run may be inspected or retried, never used for inference.
        raise
    print(f"ready {spec['local_path']} in {time.monotonic() - started:.1f}s", flush=True)
    return {**spec, "observed_sha256": sha256(path), "cached": False}


def hf_specs(component: str) -> list[dict]:
    repo, revision = SOURCES[component]
    metadata = get_json(f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true")
    if metadata["sha"] != revision:
        raise RuntimeError("Repository revision mismatch")
    result = []
    for item in metadata["siblings"]:
        name = item["rfilename"]
        if component == "mandarin" and not (
            name
            in {
                "model.int8.onnx",
                "tokens.txt",
                "lexicon.txt",
                "date.fst",
                "number.fst",
                "phone.fst",
                "LICENSE",
                "README.md",
                "dict/README.md",
            }
            or (name.startswith("dict/") and name.endswith(".utf8"))
        ):
            continue
        if component == "song-asr-large" and name not in {
            "Qwen3-ASR-1.7B-Q8_0.gguf",
            "mmproj-Qwen3-ASR-1.7B-Q8_0.gguf",
            "README.md",
        }:
            continue
        if component == "song-asr" and name not in {
            "Qwen3-ASR-0.6B-Q8_0.gguf",
            "mmproj-Qwen3-ASR-0.6B-Q8_0.gguf",
            "README.md",
        }:
            continue
        if component == "hymt" and name not in {
            "HY-MT1.5-1.8B-Q4_K_M.gguf",
            "License.txt",
            "README.md",
        }:
            continue
        if component == "hymt2" and name not in {
            "Hy-MT2-1.8B-Q4_K_M.gguf",
            "LICENSE.txt",
            "README.md",
            "README_CN.md",
        }:
            continue
        if component == "asr" and name not in {
            "model.int8.onnx",
            "tokens.txt",
            "LICENSE",
            "README.md",
            "test_wavs/yue-0.wav",
            "test_wavs/yue-1.wav",
            "test_wavs/zh.wav",
            "test_wavs/en.wav",
        }:
            continue
        if name.endswith(".gitattributes"):
            continue
        local_name = (
            "test_wavs/yue.wav" if component == "asr" and name == "test_wavs/yue-0.wav" else name
        )
        result.append(
            {
                "component": component,
                "repo": repo,
                "revision": revision,
                "url": f"https://huggingface.co/{repo}/resolve/{revision}/{urllib.parse.quote(name)}",
                "local_path": f"models/{'tts-zh' if component == 'mandarin' else 'asr-wenet' if component == 'asr' else component}/{local_name}",
                "size": item["size"],
                "sha256": item.get("lfs", {}).get("sha256"),
                "git_sha1": item.get("blobId"),
            }
        )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "components", nargs="+", choices=[*SOURCES, "runtime", "vad", "song-separator"]
    )
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    specs = []
    for component in args.components:
        if component == "song-separator":
            specs.append(
                {
                    "component": component,
                    "revision": "sha256 pinned; upstream asset 108817997",
                    "url": "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/Kim_Vocal_2.onnx",
                    "local_path": "models/song-separator/Kim_Vocal_2.onnx",
                    "size": 66759214,
                    "sha256": "ce74ef3b6a6024ce44211a07be9cf8bc6d87728cc852a68ab34eb8e58cde9c8b",
                }
            )
            continue
        if component == "vad":
            specs.append(
                {
                    "component": "vad",
                    "revision": "sha256 pinned",
                    "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx",
                    "local_path": "models/vad/silero_vad.onnx",
                    "size": 643854,
                    "sha256": "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6",
                }
            )
            continue
        if component != "runtime":
            specs.extend(hf_specs(component))
            continue
        release = get_json("https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/b12314")
        asset = next(
            x for x in release["assets"] if x["name"] == "llama-b12314-bin-win-cpu-x64.zip"
        )
        digest = asset.get("digest") or ""
        specs.append(
            {
                "component": "runtime",
                "revision": release["tag_name"],
                "url": asset["browser_download_url"],
                "local_path": "downloads/llama-b12314-bin-win-cpu-x64.zip",
                "size": asset["size"],
                "sha256": digest.removeprefix("sha256:") if digest.startswith("sha256:") else None,
            }
        )
    total = sum(x["size"] for x in specs)
    if total > 4 * 2**30:
        parser.error(
            f"Requested assets total {total / 2**30:.2f} GiB, above the 4 GiB per-run limit. "
            "Run the base components and song-asr-large separately as shown in README.md."
        )
    print(
        f"Public model/runtime download plan: {len(specs)} files, {total / 2**30:.2f} GiB",
        flush=True,
    )
    # Materialize parents serially before concurrent Path.resolve/open calls.
    # Windows path resolution in this environment intermittently rejected a
    # missing README while another worker was creating its parent directory.
    for spec in specs:
        relative = Path(spec["local_path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid relative asset path")
        parent = ROOT
        for part in relative.parent.parts:
            parent = parent / part
            if parent.exists() and not parent.resolve().is_relative_to(ROOT):
                raise ValueError("Asset parent resolves outside experiment")
            parent.mkdir(exist_ok=True)
            if not parent.resolve().is_relative_to(ROOT):
                raise ValueError("Created asset parent resolves outside experiment")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(download, specs))
    output_dir = ROOT / "outputs"
    output_dir.mkdir(exist_ok=True)
    (output_dir / ("assets-" + "-".join(args.components) + ".json")).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if "runtime" in args.components:
        target = (ROOT / "runtime" / "llama-b12314").resolve()
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(ROOT / "downloads/llama-b12314-bin-win-cpu-x64.zip") as archive:
            for item in archive.infolist():
                if not (target / item.filename).resolve().is_relative_to(target):
                    raise RuntimeError("Archive path escapes runtime directory")
            archive.extractall(target)
    print("Prepared and verified requested assets.", flush=True)


if __name__ == "__main__":
    main()
