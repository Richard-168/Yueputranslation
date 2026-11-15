import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from yuepu_translate.paths import data_dir


class EntryTests(unittest.TestCase):
    def test_default_asr_uses_the_licensed_wenet_model_for_both_directions(self):
        from yuepu_translate import model_runtime

        native = types.ModuleType("sherpa_onnx")
        native.OfflineRecognizer = types.SimpleNamespace(from_wenet_ctc=Mock())
        with patch.dict(sys.modules, {"sherpa_onnx": native}):
            for language in ("", "zh", "yue", "en"):
                model_runtime.recognizer(language)
                kwargs = native.OfflineRecognizer.from_wenet_ctc.call_args.kwargs
                self.assertTrue(
                    Path(kwargs["model"]).as_posix().endswith("asr-wenet/model.int8.onnx")
                )
                self.assertNotIn("language", kwargs)

    def test_absolute_data_directory_is_independent_of_working_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"YUEPU_DATA_DIR": folder}):
                self.assertEqual(data_dir(), Path(folder).resolve())

    def test_relative_override_is_rejected(self):
        with patch.dict(os.environ, {"YUEPU_DATA_DIR": "relative-models"}):
            with self.assertRaises(ValueError):
                data_dir()

    def test_help_entry_does_not_require_models_or_audio(self):
        result = subprocess.run(
            [sys.executable, "-m", "yuepu_translate", "--help"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--muted", result.stdout)

    def test_help_is_utf8_when_redirected_from_a_legacy_code_page(self):
        for encoding in ["cp1252", "ascii"]:
            with self.subTest(encoding=encoding):
                result = subprocess.run(
                    [sys.executable, "-m", "yuepu_translate", "--help"],
                    env=dict(os.environ, PYTHONIOENCODING=f"{encoding}:strict", PYTHONUTF8="0"),
                    capture_output=True,
                    encoding="utf-8",
                    timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("粤普双向翻译", result.stdout)
                self.assertIn("生成译音但不播放", result.stdout)

    def test_chinese_argument_error_is_utf8_on_a_legacy_code_page(self):
        result = subprocess.run(
            [sys.executable, "-m", "yuepu_translate", "--不存在的参数"],
            env=dict(os.environ, PYTHONIOENCODING="cp1252:strict", PYTHONUTF8="0"),
            capture_output=True,
            encoding="utf-8",
            timeout=15,
        )
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("--不存在的参数", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_gui_entry_accepts_missing_standard_streams(self):
        from yuepu_translate.cli import main

        window = types.ModuleType("yuepu_translate.desktop_qt")
        window.main = Mock()
        with (
            patch.dict(sys.modules, {window.__name__: window}),
            patch.object(sys, "stdout", None),
            patch.object(sys, "stderr", None),
            patch.object(sys, "argv", ["yuepu-translate", "--muted"]),
        ):
            main()
        window.main.assert_called_once_with(muted=True)

    def test_invalid_option_fails_before_loading_models(self):
        result = subprocess.run(
            [sys.executable, "-m", "yuepu_translate", "--nonexistent-option"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--nonexistent-option", result.stderr)

    def test_offline_guard_blocks_external_dns_without_network_access(self):
        # Use a separate interpreter because audit hooks cannot be unregistered.
        code = """
import socket
from yuepu_translate.offline import enable
enable()
enable()
try:
    socket.getaddrinfo("offline-test.invalid", 443)
except RuntimeError:
    print("blocked")
else:
    raise AssertionError("External DNS was allowed")
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "blocked")


if __name__ == "__main__":
    unittest.main()
