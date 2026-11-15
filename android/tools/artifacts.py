"""Bounded, digest-checked public artifact preparation; never imported by the app."""

import hashlib
import json
import time
import urllib.request
from pathlib import Path


def get_json(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("Metadata is too large")
    return json.loads(data)


def digest(path, algorithm="sha256"):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def valid(path, size, expected, algorithm="sha256"):
    path = Path(path)
    if not path.is_file() or path.stat().st_size != size:
        return False
    if algorithm == "git-sha1":
        value = hashlib.sha1(f"blob {size}\0".encode())
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                value.update(chunk)
        return value.hexdigest() == expected
    return digest(path, algorithm) == expected


def fetch(url, path, size, expected, algorithm="sha256"):
    path = Path(path)
    if valid(path, size, expected, algorithm):
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    cursor = partial.stat().st_size if partial.exists() else 0
    if cursor > size:
        raise ValueError("Cached partial exceeds the published size")
    started = time.monotonic()
    while cursor < size:
        if time.monotonic() - started > 900:
            raise TimeoutError("Artifact download deadline exceeded")
        end = min(cursor + 8 * 1024 * 1024 - 1, size - 1)
        request = urllib.request.Request(url, headers={"Range": f"bytes={cursor}-{end}"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=40) as response:
                    if cursor > 0 and (
                        response.status != 206
                        or not response.headers.get("Content-Range", "").startswith(
                            f"bytes {cursor}-"
                        )
                    ):
                        raise ValueError("Download server did not honor the range")
                    chunk = response.read(end - cursor + 1)
                if not chunk:
                    raise ValueError("Empty artifact response")
                break
            except (OSError, ValueError):
                if attempt == 2:
                    raise
        with partial.open("ab") as stream:
            stream.write(chunk)
        cursor += len(chunk)
    if not valid(partial, size, expected, algorithm):
        raise ValueError("Published artifact digest mismatch: " + path.name)
    partial.replace(path)
    print("verified " + path.name, flush=True)
    return path
