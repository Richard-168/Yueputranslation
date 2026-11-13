import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yuepu_translate.paths import data_dir


class EntryTests(unittest.TestCase):
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
