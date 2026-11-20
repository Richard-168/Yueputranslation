"""Download and import verified assets in a process separate from inference."""

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path

from .model_assets import GROUPS, assets, format_size, has_size, model_path, partial_path
from .paths import DATA_DIR

CHUNK = 2**20


def report(done, total, message):
    print(json.dumps(dict(done=done, total=total, message=message)), flush=True)


@contextmanager
def model_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".yuepu-models.lock"
    if path.is_symlink():
        raise ValueError("模型目录锁路径无效。")
    with path.open("a+b") as lock:
        try:
            if os.name == "nt":
                import msvcrt

                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("另一个窗口正在管理模型，请稍后重试。") from exc
        yield


class HTTPSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise ValueError("模型来源重定向到了非 HTTPS 地址。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def matches(path, asset):
    if not has_size(path, asset.size):
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() == asset.digest


def copy_bounded(reader, partial, asset, offset, progress):
    last_update = 0
    with partial.open("ab" if offset else "wb") as output:
        while chunk := reader.read(CHUNK):
            offset += len(chunk)
            if offset > asset.size:
                raise ValueError("模型文件超过预期大小。")
            output.write(chunk)
            now = time.monotonic()
            if now - last_update > 0.2:
                progress(offset)
                last_update = now
    if offset != asset.size:
        raise RuntimeError("模型传输中断，可重试下载。")


def download(opener, asset, partial, progress):
    if not asset.url.startswith("https://"):
        raise ValueError("模型下载需要 HTTPS。")
    offset = partial.stat().st_size if partial.exists() else 0
    if offset >= asset.size:
        if matches(partial, asset):
            return
        partial.unlink()
        offset = 0
    request = urllib.request.Request(
        asset.url, headers={"Range": f"bytes={offset}-"} if offset else {}
    )
    with opener.open(request, timeout=30) as response:
        if response.status == 206:
            expected = f"bytes {offset}-{asset.size - 1}/{asset.size}"
            if response.headers.get("Content-Range") != expected:
                raise ValueError("服务器返回了与续传请求不符的范围。")
        elif response.status == 200:
            offset = 0
        else:
            raise ValueError("服务器返回了意外的下载状态。")
        copy_bounded(response, partial, asset, offset, progress)


def install(root, selected, archive=None):
    total = sum(asset.size for asset in selected)
    paths = [(asset, model_path(root, asset)) for asset in selected]
    if archive is not None:
        entries = {}
        names = {asset.name for asset in selected}
        for entry in archive.infolist():
            if entry.filename in names:
                if entry.filename in entries:
                    raise ValueError("模型包内有重复的模型文件。")
                entries[entry.filename] = entry
        if any(
            asset.name not in entries or entries[asset.name].file_size != asset.size
            for asset in selected
        ):
            raise ValueError("模型包缺少所选组的文件，或文件版本不符。")
    opener = urllib.request.build_opener(HTTPSRedirect()) if archive is None else None
    done = 0
    for asset, path in paths:
        report(done, total, f"正在检查 {path.name}")
        if not matches(path, asset):
            path.parent.mkdir(parents=True, exist_ok=True)
            partial = partial_path(path, asset)
            # Allow for servers that ignore Range and send the full file.
            reusable = min(asset.size, partial.stat().st_size) if partial.exists() else 0
            if shutil.disk_usage(path.parent).free < asset.size - reusable:
                raise RuntimeError(f"磁盘空间不足，当前文件需要 {format_size(asset.size)}。")

            def progress(count):
                report(done + count, total, f"正在传输 {path.name}")

            if archive is None:
                download(opener, asset, partial, progress)
            else:
                with archive.open(entries[asset.name]) as stream:
                    copy_bounded(stream, partial, asset, 0, progress)
            report(done + asset.size, total, f"正在校验 {path.name}")
            if not matches(partial, asset):
                partial.unlink()
                raise ValueError(f"模型校验失败（{path.name}），请重新下载或更换模型包。")
            partial.replace(path)
        done += asset.size
    report(total, total, "模型已就绪。")


def remove(root, selected):
    for asset in selected:
        path = model_path(root, asset)
        partial_path(path, asset).unlink(missing_ok=True)
        path.unlink(missing_ok=True)
    report(1, 1, "已删除所选模型。")


def export(root, selected, destination):
    paths = [(asset, model_path(root, asset)) for asset in selected]
    if not all(matches(path, asset) for asset, path in paths):
        raise ValueError("模型组不完整或校验失败，请先下载或修复。")
    with destination.open("xb") as output:
        try:
            with zipfile.ZipFile(output, "w") as archive:
                for asset, path in paths:
                    archive.write(path, asset.name)
        except Exception:
            output.close()
            destination.unlink()
            raise
    report(1, 1, "离线模型包已生成。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["download", "import", "delete", "export"])
    parser.add_argument("group", choices=GROUPS)
    parser.add_argument("archive", type=Path, nargs="?")
    args = parser.parse_args()
    if (args.action in {"import", "export"}) != (args.archive is not None):
        parser.error("Specify a ZIP path for import or export.")
    selected = assets(GROUPS[args.group][1])
    try:
        if args.action != "export" and os.environ.get("YUEPU_BUNDLED_DATA_DIR") == str(DATA_DIR):
            raise ValueError("完整安装包的模型由 Windows 安装程序管理。")
        with model_lock(DATA_DIR):
            if args.action == "download":
                install(DATA_DIR, selected)
            elif args.action == "import":
                with zipfile.ZipFile(args.archive) as archive:
                    install(DATA_DIR, selected, archive)
            elif args.action == "delete":
                remove(DATA_DIR, selected)
            else:
                export(DATA_DIR, selected, args.archive)
    except urllib.error.URLError:
        report(0, 0, "操作未完成。无法从模型来源下载，请检查网络后重试，或导入离线模型包。")
        return 1
    except (ValueError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
        report(0, 0, f"操作未完成。{exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
