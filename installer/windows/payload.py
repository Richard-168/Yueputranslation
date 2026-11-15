"""Build a bounded, application-local Windows runtime from installed distributions."""

import argparse
import hashlib
import importlib.metadata as metadata
import json
import shutil
import struct
import subprocess
import sys
import sysconfig
import tomllib
import zipfile
from pathlib import Path, PureWindowsPath

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from windows_host import patch_host

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from model_licenses import review, verify_artifacts, verify_payload  # noqa: E402, F401

MODEL_DIRS = (
    "asr-wenet",
    "canto",
    "hymt2",
    "vad",
    "tts-zh",
    "song-asr-large",
    "song-separator",
)


def dependency_closure(requirements, distributions):
    available = {}
    for distribution in distributions:
        available.setdefault(canonicalize_name(distribution.metadata["Name"]), distribution)
    pending = list(requirements)
    selected = {}
    environment = default_environment() | {"extra": ""}
    while pending:
        requirement = Requirement(pending.pop())
        if requirement.marker and not requirement.marker.evaluate(environment):
            continue
        if requirement.extras:
            raise ValueError("Package extras must be resolved explicitly")
        name = canonicalize_name(requirement.name)
        distribution = available.get(name)
        if distribution is None or not requirement.specifier.contains(distribution.version):
            raise ValueError(f"Missing or incompatible dependency: {requirement}")
        if name not in selected:
            selected[name] = distribution
            pending.extend(distribution.requires or ())
    return selected


def record_path(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or PureWindowsPath(str(relative)).drive or ".." in relative.parts:
        return None
    if "__pycache__" in relative.parts or relative.suffix in {
        ".pyc",
        ".pyo",
        ".key",
        ".pem",
        ".pfx",
        ".p12",
    }:
        return None
    if relative.name == ".env" or relative.name.startswith(".env."):
        return None
    result = root / relative
    return result if result.resolve().is_relative_to(root.resolve()) else None


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_file_list(output, names):
    lines = []
    for name in sorted(set(names)):
        path = record_path(output, name)
        if path is None or not path.is_file():
            raise ValueError("Unsafe or missing installer input")
        relative = PureWindowsPath(name)
        destination = "{app}" + ("\\" + str(relative.parent) if str(relative.parent) != "." else "")
        lines.append(
            f'Source: "{{#PayloadDir}}\\{relative}"; DestDir: "{destination}"; Flags: ignoreversion'
        )
    (output.parent / (output.name + "-files.iss")).write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def apply_runtime_patches(output):
    return [patch_host(output / "python" / name) for name in ("python.exe", "pythonw.exe")]


def build(output, data, *, private_development=False):
    model_licenses = review("windows", MODEL_DIRS, private_development=private_development)
    if sys.version_info[:2] != (3, 12) or struct.calcsize("P") != 8 or sys.platform != "win32":
        raise ValueError("Build with the tested Windows x64 Python 3.12 environment")
    output = output.resolve()
    if not output.is_relative_to(ROOT / "outputs"):
        raise ValueError("Staging must be inside this project's ignored outputs directory")
    output.mkdir(parents=True, exist_ok=False)
    files = {}

    def copy(source, relative):
        target = record_path(output, relative)
        if target is None or source.is_symlink():
            raise ValueError("Unsafe payload source or destination")
        key = target.relative_to(output).as_posix()
        digest = sha256(source)
        if key in files:
            if files[key]["sha256"] != digest:
                raise ValueError("Conflicting distribution records: " + key)
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        files[key] = dict(size=target.stat().st_size, sha256=digest)

    def tree(source, destination, allowed=None):
        if not source.is_dir():
            raise ValueError("Required directory is missing: " + str(source))
        for path in sorted(source.rglob("*")):
            relative = path.relative_to(source)
            if record_path(source, relative) is None or not path.is_file():
                continue
            if allowed is None or allowed(path):
                copy(path, Path(destination) / relative)

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    requirements = project["dependencies"] + project["optional-dependencies"]["offline"]
    roots = [Path(sysconfig.get_path("purelib")), Path(sys.base_prefix) / "Lib/site-packages"]
    distributions = [
        d for path in dict.fromkeys(roots) for d in metadata.distributions(path=[str(path)])
    ]
    selected = dependency_closure(requirements, distributions)
    packages = {}
    for name, distribution in sorted(selected.items()):
        origin = Path(distribution.locate_file("")).resolve()
        print("Collecting", name, distribution.version, flush=True)
        if not distribution.files:
            raise ValueError("Distribution has no installed file record: " + name)
        for relative in distribution.files:
            source = record_path(origin, relative)
            if source is not None and source.is_file():
                copy(source, Path("python/site-packages") / relative)
        packages[name] = distribution.version

    base = Path(sys.base_prefix)
    for name in (
        "python.exe",
        "pythonw.exe",
        "python3.dll",
        "python312.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "LICENSE.txt",
    ):
        copy(base / name, Path("python") / name)
    patches = apply_runtime_patches(output)
    for patch in patches:
        path = output / patch["path"]
        files[patch["path"]] = dict(size=path.stat().st_size, sha256=patch["patched_sha256"])
    tree(base / "DLLs", "python", lambda p: p.suffix in {".dll", ".pyd"})
    # An isolated path file blocks host registry, user site packages and PYTHONPATH.
    # Child '-m yuepu_translate.*' workers resolve exactly the same packaged modules.
    (output / "python/python312._pth").write_text(
        "python312.zip\n.\nsite-packages\n../app\n", encoding="utf-8"
    )
    library = output / "python/python312.zip"
    with zipfile.ZipFile(library, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((base / "Lib").rglob("*.py")):
            relative = path.relative_to(base / "Lib")
            if (
                relative.parts[0]
                not in {
                    "site-packages",
                    "test",
                    "tests",
                    "idlelib",
                    "tkinter",
                    "turtledemo",
                    "ensurepip",
                    "venv",
                }
                and "__pycache__" not in relative.parts
            ):
                archive.write(path, relative.as_posix())
    tree(ROOT / "src/yuepu_translate", "app/yuepu_translate", lambda p: p.suffix in {".py", ".svg"})
    copy(ROOT / "installer/windows/launcher.py", "launch.py")
    for name in MODEL_DIRS:
        print("Collecting model", name, flush=True)
        verify_artifacts(model_licenses["models"][name], data / "models" / name)
        tree(
            data / "models" / name,
            Path("data/models") / name,
            lambda p: p.suffix.lower() not in {".wav", ".mp3", ".mp4", ".flac", ".log"},
        )
    runtime = data / "runtime/llama-b12314"
    tree(
        runtime,
        "data/runtime/llama-b12314",
        lambda p: (
            p.suffix == ".dll"
            or p.name in {"llama-server.exe", "llama-completion.exe"}
            or p.name.startswith("LICENSE")
        ),
    )
    for name in ("LICENSE", "THIRD_PARTY.md", "README.md"):
        copy(ROOT / name, Path("docs") / name)
    tree(ROOT / "licenses", "docs/licenses")
    tree(ROOT / "installer/windows/licenses", "docs/licenses")
    copy(ROOT / "installer/windows/ThirdPartyNotices.txt", "docs/ThirdPartyNotices.txt")
    for name in ("windows.md", "online.md"):
        copy(ROOT / "docs" / name, Path("docs") / name)
    copy(ROOT / "installer/windows/使用说明.txt", "使用说明.txt")
    # Record generated runtime files and an exact allowlist; no user's settings,
    # secrets, recordings, exports, Android data or development cache are copied.
    for path in (library, output / "python/python312._pth"):
        files[path.relative_to(output).as_posix()] = dict(
            size=path.stat().st_size, sha256=sha256(path)
        )
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    record = dict(
        format=1,
        version=project["version"],
        source_revision=revision,
        scope="local Windows development installer; no public release approval",
        python=sys.version.split()[0],
        packages=packages,
        runtime_patches=patches,
        files=files,
        model_licenses=model_licenses,
    )
    (output / "payload-manifest.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_file_list(output, [*files, "payload-manifest.json"])
    print(
        "Payload ready:",
        len(files),
        "files,",
        sum(item["size"] for item in files.values()) // 2**20,
        "MiB",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data", type=Path, default=ROOT / "experiments/offline-poc")
    parser.add_argument(
        "--private-development",
        action="store_true",
        help="Local testing only; no public model rights",
    )
    parser.add_argument(
        "--check-licenses", action="store_true", help="Check model permissions without writing"
    )
    args = parser.parse_args()
    if args.check_licenses:
        print(
            json.dumps(review("windows", MODEL_DIRS, private_development=args.private_development))
        )
        raise SystemExit(0)
    build(args.output, args.data.resolve(), private_development=args.private_development)
