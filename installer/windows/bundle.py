"""Bundle a completed local Inno build with its data, instructions and notices."""

import argparse
import json
import re
import shutil
import zipfile
from pathlib import Path

from payload import ROOT, sha256


def bundle(directory, output, payload):
    directory, output, payload = directory.resolve(), output.resolve(), payload.resolve()
    if not directory.is_relative_to(ROOT / "outputs") or not payload.is_relative_to(
        ROOT / "outputs"
    ):
        raise ValueError("Installer and payload must be inside the project's outputs directory")
    if output.exists() or not output.is_relative_to(ROOT / "outputs"):
        raise ValueError("Use a new ZIP path inside the project's outputs directory")
    manifest = json.loads((payload / "payload-manifest.json").read_text(encoding="utf-8"))
    for name, record in manifest["files"].items():
        source = payload / name
        if not source.resolve().is_relative_to(payload) or source.is_symlink():
            raise ValueError("Invalid snapshot path")
        if source.stat().st_size != record["size"] or sha256(source) != record["sha256"]:
            raise ValueError("Payload changed after its accepted snapshot: " + name)
    settings = (ROOT / "installer/windows/YuePuTranslate.iss").read_text(encoding="utf-8")
    name = re.search(r"^OutputBaseFilename=(.+)$", settings, re.MULTILINE).group(1).strip()
    executable = directory / (name + ".exe")
    with executable.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError("Missing Windows installer")
    parts = sorted(
        path
        for path in directory.iterdir()
        if re.fullmatch(re.escape(name) + r"-\d+[a-z]?\.bin", path.name)
    )
    if not parts or any(part.stat().st_size == 0 for part in parts):
        raise ValueError("Missing Inno data files")
    instructions = (
        "Windows 完整离线开发预览\n\n"
        "请先完整解压本 ZIP，再运行 " + executable.name + "。\n"
        "EXE 与旁边的 .bin 数据文件须放在同一文件夹，不要只复制 EXE。\n"
        "安装本体约需 5.3 GB 空间，解压出来的安装文件另占约 4.3 GB。\n\n"
        "程序包含 Python 和离线模型，无需另装 Python。\n"
        "程序、模型、中文路径及字体检查通过；当前自动化环境拒绝安装器\n"
        "写入开始菜单／卸载登记，常规安装与卸载尚未完整验收。\n"
        "安装器已在失败时回滚，测试登记项已清理；运行验证使用独立目录，\n"
        "不能据此宣称全新 Windows 系统安装已通过。\n\n"
    )
    instructions += (ROOT / "installer/windows/使用说明.txt").read_text(encoding="utf-8")
    (directory / "使用说明.txt").write_text(instructions, encoding="utf-8")
    shutil.copyfile(
        ROOT / "installer/windows/ThirdPartyNotices.txt", directory / "ThirdPartyNotices.txt"
    )
    (directory / "licenses").mkdir(exist_ok=True)
    license_targets = []
    for name in ("GPL-2.0-only.txt", "GPL-3.0-only.txt", "LGPL-3.0-only.txt", "llama.cpp-MIT.txt"):
        target = directory / "licenses" / name
        shutil.copyfile(ROOT / "installer/windows/licenses" / name, target)
        license_targets.append(target)
    sources = [
        executable,
        *parts,
        directory / "使用说明.txt",
        directory / "ThirdPartyNotices.txt",
        *license_targets,
    ]
    inventory = {
        path.relative_to(directory).as_posix(): dict(size=path.stat().st_size, sha256=sha256(path))
        for path in sources
    }
    report = dict(
        format=1,
        files=inventory,
        payload_manifest_sha256=sha256(payload / "payload-manifest.json"),
        source_revision=manifest["source_revision"],
        scope="local development artifact only",
        installer_registration="unverified: automated environment denied writes; rolled back",
        runtime_evidence="Chinese-path model, font and launcher checks passed; synthetic muted audio",
        code_signing="unsigned",
    )
    report_file = directory / "verification.json"
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    sources.append(report_file)
    if any(path.is_symlink() for path in sources):
        raise ValueError("Symbolic links cannot be bundled")
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path in sources:
            archive.write(path, Path("YuePuTranslate-Windows-x64") / path.relative_to(directory))
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("Delivery archive CRC validation failed")
    digest = sha256(output)
    output.with_suffix(".zip.sha256").write_text(
        digest + "  " + output.name + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            dict(file=str(output), size=output.stat().st_size, sha256=digest), ensure_ascii=False
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer-dir", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    bundle(args.installer_dir, args.output, args.payload)
