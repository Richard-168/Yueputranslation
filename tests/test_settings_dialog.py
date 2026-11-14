"""Exercise the actual Qt settings Save/Cancel controls using isolated settings."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()
