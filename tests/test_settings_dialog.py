"""Exercise the actual Qt settings Save/Cancel controls using isolated settings."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox  # noqa: E402

from yuepu_translate.cloud_config import CloudConfig, load_settings  # noqa: E402
from yuepu_translate.cloud_dialog import CloudDialog  # noqa: E402
from yuepu_translate.preferences import Preferences, load_preferences  # noqa: E402
from yuepu_translate.settings_dialog import SettingsDialog  # noqa: E402


class SettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_save_validates_paths_and_restart_reads_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "preferences.ini")
            settings = QSettings(path, QSettings.IniFormat)
            dialog = SettingsDialog(Preferences(), settings)
            dialog.show()
            self.app.processEvents()
            dialog.cache.setText("relative-path")
            QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.Save), Qt.LeftButton)
            self.assertTrue(dialog.isVisible())
            self.assertIn("绝对路径", dialog.feedback.text())
            self.assertEqual(settings.allKeys(), [])
            dialog.cache.setText(str(Path(folder) / "cache"))
            dialog.exports.setText(str(Path(folder) / "exports"))
            dialog.mode.setCurrentIndex(dialog.mode.findData("flash"))
            dialog.autoplay.setChecked(False)
            QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.Save), Qt.LeftButton)
            self.assertEqual(dialog.result(), QDialog.Accepted)
            restored = load_preferences(QSettings(path, QSettings.IniFormat))
            self.assertEqual(restored.mode, "flash")
            self.assertFalse(restored.autoplay)
            self.assertEqual(restored.cache_directory, str(Path(folder) / "cache"))
            self.assertEqual(restored.export_directory, str(Path(folder) / "exports"))

    def test_keyboard_cancel_does_not_save_edited_preferences(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "preferences.ini"), QSettings.IniFormat)
            dialog = SettingsDialog(Preferences(), settings)
            dialog.show()
            self.app.processEvents()
            dialog.mode.setCurrentIndex(dialog.mode.findData("flash"))
            QTest.keyClick(dialog, Qt.Key_Escape)
            self.assertEqual(dialog.result(), QDialog.Rejected)
            self.assertEqual(settings.allKeys(), [])

    def test_cloud_remember_failure_can_be_recovered_using_memory_only(self):
        key = "synthetic-test-key-only"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cloud.json"
            with patch("yuepu_translate.cloud_config.settings_path", return_value=path):
                dialog = CloudDialog(CloudConfig(key), enabled=True, remember=True)
                dialog.show()
                self.app.processEvents()
                with patch(
                    "yuepu_translate.cloud_dialog.save_settings",
                    side_effect=PermissionError("blocked " + key),
                ):
                    QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.Save), Qt.LeftButton)
                self.assertTrue(dialog.isVisible())
                self.assertIn("取消勾选", dialog.feedback.text())
                self.assertNotIn(key, dialog.feedback.text())
                self.assertTrue(dialog.remember_box.isChecked())
                self.assertFalse(path.exists())
                dialog.remember_box.setChecked(False)
                QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.Save), Qt.LeftButton)
                self.assertEqual(dialog.result(), QDialog.Accepted)
                self.assertTrue(dialog.enabled)
                self.assertFalse(dialog.remember)
                self.assertEqual(dialog.config.api_key, key)
                self.assertFalse(path.exists())

    def test_cloud_forget_failure_does_not_claim_saved_key_was_removed(self):
        dialog = CloudDialog(CloudConfig("synthetic-test-key-only"), enabled=True)
        dialog.show()
        self.app.processEvents()
        try:
            with patch("yuepu_translate.cloud_dialog.save_settings", side_effect=PermissionError()):
                QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.Save), Qt.LeftButton)
            self.assertTrue(dialog.isVisible())
            self.assertIn("无法清除", dialog.feedback.text())
            self.assertIn("仍可能保留", dialog.feedback.text())
        finally:
            dialog.reject()

    @unittest.skipUnless(os.name == "nt", "Windows current-user DPAPI")
    def test_cloud_save_button_encrypts_key_and_restores_on_reopen(self):
        config = CloudConfig("synthetic-test-key-only", "singapore", "12345", 12)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "YuePuTranslate" / "cloud.json"
            with patch("yuepu_translate.cloud_config.settings_path", return_value=path):
                dialog = CloudDialog(config, enabled=True, remember=True)
                dialog.show()
                self.app.processEvents()
                QTest.mouseClick(dialog.buttons.button(QDialogButtonBox.Save), Qt.LeftButton)
                self.assertEqual(dialog.result(), QDialog.Accepted)
                self.assertNotIn(config.api_key, path.read_text(encoding="utf-8"))
                restored, remember = load_settings()
                reopened = CloudDialog(restored, remember=remember)
                try:
                    self.assertEqual(reopened.candidate(), config)
                    self.assertTrue(reopened.remember_box.isChecked())
                    self.assertFalse(reopened.enable_box.isChecked())
                finally:
                    reopened.reject()


if __name__ == "__main__":
    unittest.main()
