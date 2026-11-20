"""Verify interrupted transfers and reject corrupt offline packages."""

import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from yuepu_translate.model_assets import Asset, partial_path
from yuepu_translate.model_worker import download, install

CONTENT = b"verified model bytes"
ASSET = Asset(
    "models/example/model.onnx",
    len(CONTENT),
    hashlib.sha256(CONTENT).hexdigest(),
    "https://example.test/model.onnx",
)


class ModelWorkerTests(unittest.TestCase):
    def test_download_resumes_from_partial_and_checks_returned_range(self):
        with tempfile.TemporaryDirectory() as directory:
            partial = Path(directory) / "model.part"
            partial.write_bytes(CONTENT[:4])
            response = io.BytesIO(CONTENT[4:])
            response.status = 206
            response.headers = {"Content-Range": "bytes 2-19/20"}
            opener = Mock()
            opener.open.return_value = response
            with self.assertRaisesRegex(ValueError, "续传"):
                download(opener, ASSET, partial, lambda count: None)
            self.assertEqual(partial.read_bytes(), CONTENT[:4])
            response = io.BytesIO(CONTENT[4:])
            response.status = 206
            response.headers = {"Content-Range": f"bytes 4-{ASSET.size - 1}/{ASSET.size}"}
            opener.open.return_value = response
            download(opener, ASSET, partial, lambda count: None)
            self.assertEqual(opener.open.call_args.args[0].get_header("Range"), "bytes=4-")
            self.assertEqual(partial.read_bytes(), CONTENT)

    def test_zip_import_validates_bytes_and_ignores_paths_outside_catalog(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("yuepu_translate.model_worker.report"),
        ):
            root = Path(directory) / "data"
            target = root / ASSET.name
            target.parent.mkdir(parents=True)
            target.write_bytes(b"keep old model")
            for data in (b"x" * ASSET.size, CONTENT):
                container = io.BytesIO()
                with zipfile.ZipFile(container, "w") as archive:
                    archive.writestr(ASSET.name, data)
                    archive.writestr("../untrusted.txt", "do not extract")
                with zipfile.ZipFile(container) as archive:
                    if data != CONTENT:
                        with self.assertRaisesRegex(ValueError, "校验失败"):
                            install(root, [ASSET], archive)
                        self.assertEqual(target.read_bytes(), b"keep old model")
                    else:
                        install(root, [ASSET], archive)
                        self.assertEqual(target.read_bytes(), CONTENT)
                self.assertFalse(partial_path(target, ASSET).exists())
                self.assertFalse((root.parent / "untrusted.txt").exists())
