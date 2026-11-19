"""Persistent defaults and safe file locations; isolated from user preferences."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QSettings

from yuepu_translate.paths import ASR_MODEL, ASR_PROJECTOR, MT_MODEL
from yuepu_translate.preferences import (
    Preferences,
    cache_directory,
    default_cache_directory,
    load_preferences,
    save_preferences,
)


class PreferencesTests(unittest.TestCase):
    def test_defaults_follow_installed_models_and_yield_to_saved_choices(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            settings = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)

            def install(relative):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            with patch("yuepu_translate.preferences.DATA_DIR", root):
                install(MT_MODEL)
                text = load_preferences(settings)
                self.assertEqual(text.mode, "flash")
                self.assertFalse(text.autoplay)
                install("models/tts-zh/model.int8.onnx")
                self.assertTrue(load_preferences(settings).autoplay)
                install(ASR_MODEL)
                install(ASR_PROJECTOR)
                self.assertEqual(load_preferences(settings).mode, "pro")
                settings.setValue("defaults/mode", "flash")
                settings.setValue("defaults/autoplay", False)
                saved = load_preferences(settings)
                self.assertEqual(saved.mode, "flash")
                self.assertFalse(saved.autoplay)

    def test_missing_sensitivity_defaults_to_standard_without_resetting_saved_options(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "preferences.ini"), QSettings.IniFormat)
            settings.setValue("defaults/mode", "flash")
            settings.setValue("defaults/direction", "zh")
            restored = load_preferences(settings)
            self.assertEqual(getattr(restored, "sensitivity", None), "standard")
            self.assertEqual(restored.mode, "flash")
            self.assertEqual(restored.direction, "zh")
            self.assertFalse(restored.mute_mic_during_playback)

    def test_invalid_saved_sensitivity_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "preferences.ini"), QSettings.IniFormat)
            settings.setValue("defaults/sensitivity", "unknown")
            with self.assertRaises(ValueError):
                load_preferences(settings)

    def test_previous_paragraph_preference_maps_to_pro_without_resetting_other_options(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "preferences.ini"), QSettings.IniFormat)
            settings.setValue("defaults/mode", "paragraph")
            settings.setValue("defaults/direction", "zh")
            restored = load_preferences(settings)
            self.assertEqual(restored.mode, "pro")
            self.assertEqual(restored.direction, "zh")

    def test_default_cache_uses_the_system_temporary_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("yuepu_translate.preferences.tempfile.gettempdir", return_value=folder):
                self.assertEqual(default_cache_directory(), Path(folder) / "YuePuTranslate/cache")

    def test_unwritable_cache_reports_how_to_change_location(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "preferences.ini"), QSettings.IniFormat)
            with (
                patch("yuepu_translate.preferences.settings_store", return_value=settings),
                patch(
                    "yuepu_translate.preferences.Path.mkdir", side_effect=PermissionError("denied")
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "设置.*文件位置"):
                    cache_directory()

    def test_defaults_and_round_trip_do_not_store_upload_consent_or_content(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "preferences.ini"), QSettings.IniFormat)
            self.assertEqual(load_preferences(settings).mode, "pro")
            preference = Preferences(
                mode="flash",
                direction="zh",
                audio_source="system",
                sensitivity="sensitive",
                autoplay=False,
                mute_mic_during_playback=True,
                font_size=20,
                smooth=False,
                number_mode="amount",
                vocals=True,
                cache_directory=str(Path(folder) / "cache"),
                export_directory=str(Path(folder) / "exports"),
            )
            save_preferences(preference, settings)
            self.assertEqual(load_preferences(settings), preference)
            self.assertNotIn("cloud_enabled", settings.allKeys())
            self.assertNotIn("api_key", settings.allKeys())
            self.assertFalse(list(Path(folder).rglob("*.wav")))

    def test_invalid_paths_and_mode_are_rejected_before_any_preference_is_written(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = QSettings(str(Path(folder) / "preferences.ini"), QSettings.IniFormat)
            for fields in (
                dict(mode="unknown"),
                dict(sensitivity="unknown"),
                dict(cache_directory="relative"),
                dict(export_directory="relative"),
                dict(font_size=40),
            ):
                with self.subTest(fields=fields), self.assertRaises(ValueError):
                    save_preferences(replace(Preferences(), **fields), settings)
                self.assertEqual(settings.allKeys(), [])

    def test_changing_locations_keeps_old_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old = root / "old-cache"
            old.mkdir()
            retained = old / "keep.txt"
            retained.write_text("existing user file", encoding="utf-8")
            settings = QSettings(str(root / "preferences.ini"), QSettings.IniFormat)
            save_preferences(Preferences(cache_directory=str(old)), settings)
            save_preferences(Preferences(cache_directory=str(root / "new-cache")), settings)
            self.assertEqual(retained.read_text(encoding="utf-8"), "existing user file")


if __name__ == "__main__":
    unittest.main()
