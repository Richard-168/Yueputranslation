"""Create a private Android development model pack and its APK validation catalog."""

import argparse
import concurrent.futures
import json
import urllib.parse
import zipfile
from pathlib import Path

from artifacts import digest, fetch, get_json, valid

ROOT = Path(__file__).resolve().parents[1]
REPOS = {
    "asr": (
        "csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
        "2365baeacb507f821a0c8120fcee3d484dba7a07",
    ),
    "translation": ("tencent/Hy-MT2-1.8B-GGUF", "a0c709d9fac510f2c807aa3af52872340dc37a4a"),
    "tts-zh": ("csukuangfj/vits-melo-tts-zh_en", "a0d5c6a264c0ef92d70d8661d8cc502d79627cd6"),
    "tts-yue": (
        "csukuangfj/vits-cantonese-hf-xiaomaiiwn",
        "27e0da148bbe6c120107c0d6d01c218337f803e8",
    ),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--desktop-data", type=Path, default=ROOT.parent / "experiments/offline-poc"
    )
    parser.add_argument("--output", type=Path, default=ROOT.parent / "outputs/android-models")
    parser.add_argument("--no-pack", action="store_true")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    specs = []
    for component, (repo, revision) in REPOS.items():
        metadata = get_json(
            f"https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true"
        )
        if metadata["sha"] != revision:
            raise ValueError("Model revision mismatch")
        for entry in metadata["siblings"]:
            name = entry["rfilename"]
            wanted = (
                (component == "asr" and name in {"model.int8.onnx", "tokens.txt"})
                or (component == "translation" and name == "Hy-MT2-1.8B-Q4_K_M.gguf")
                or (
                    component == "tts-zh"
                    and (
                        name
                        in {
                            "model.int8.onnx",
                            "tokens.txt",
                            "lexicon.txt",
                            "date.fst",
                            "number.fst",
                            "phone.fst",
                        }
                        or (name.startswith("dict/") and name.endswith(".utf8"))
                    )
                )
                or (
                    component == "tts-yue"
                    and name
                    in {
                        "vits-cantonese-hf-xiaomaiiwn.onnx",
                        "tokens.txt",
                        "lexicon.txt",
                        "rule.fst",
                    }
                )
            )
            if not wanted:
                continue
            local_name = "model.gguf" if component == "translation" else name
            if component == "tts-yue" and name.endswith(".onnx"):
                local_name = "model.onnx"
            lfs = entry.get("lfs")
            specs.append(
                dict(
                    path=f"{component}/{local_name}",
                    size=entry["size"],
                    expected=lfs["sha256"] if lfs else entry["blobId"],
                    algorithm="sha256" if lfs else "git-sha1",
                    url=f"https://huggingface.co/{repo}/resolve/{revision}/{urllib.parse.quote(name)}",
                    desktop=(
                        "models/asr/" + name
                        if component == "asr"
                        else "models/hymt2/" + name
                        if component == "translation"
                        else ""
                    ),
                )
            )
    specs.append(
        dict(
            path="vad/silero_vad.onnx",
            size=643854,
            expected="9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6",
            algorithm="sha256",
            desktop="models/vad/silero_vad.onnx",
            url="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx",
        )
    )

    def prepare(spec):
        existing = args.desktop_data / spec["desktop"] if spec["desktop"] else None
        if existing and valid(existing, spec["size"], spec["expected"], spec["algorithm"]):
            path = existing
        else:
            path = fetch(
                spec["url"],
                ROOT / ".models" / spec["path"],
                spec["size"],
                spec["expected"],
                spec["algorithm"],
            )
        return spec, path, digest(path)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        prepared = list(pool.map(prepare, specs))
    catalog = dict(
        format=1,
        profile="android-offline-dev-v1",
        files=[dict(path=spec["path"], size=spec["size"], sha256=sha) for spec, _, sha in prepared],
        sources=REPOS,
        redistribution="Cantonese VITS voice license unverified; private development only",
    )
    text = json.dumps(catalog, ensure_ascii=False, indent=2)
    assets = ROOT / "app/src/main/assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "model-catalog.json").write_text(text, encoding="utf-8")
    (args.output / "model-catalog.json").write_text(text, encoding="utf-8")
    if not args.no_pack:
        target = args.output / "yuepu-android-models-dev.zip"
        partial = target.with_suffix(".zip.part")
        with zipfile.ZipFile(
            partial, "w", compression=zipfile.ZIP_STORED, allowZip64=True
        ) as archive:
            archive.writestr("manifest.json", text)
            for spec, path, _ in prepared:
                archive.write(path, spec["path"])
        partial.replace(target)
        print(f"Model pack ready: {target} ({target.stat().st_size // 1024 // 1024} MiB)")
    print(f"Verified {len(prepared)} files; no audio or credentials included")


if __name__ == "__main__":
    main()
