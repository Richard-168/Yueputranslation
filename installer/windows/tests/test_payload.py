import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import payload  # noqa: E402
from payload import dependency_closure, record_path, write_file_list  # noqa: E402


class FakeDistribution:
    def __init__(self, name, version, requires=()):
        self.metadata = {"Name": name}
        self.version = version
        self.requires = list(requires)


class PayloadBoundaryTests(unittest.TestCase):
    def test_widgets_package_keeps_runtime_but_excludes_unused_qt_modules(self):
        for name in (
            "PySide6/QtWidgets.pyd",
            "PySide6/Qt6Gui.dll",
            "PySide6/Qt6Svg.dll",
            "PySide6/plugins/platforms/qwindows.dll",
            "PySide6/plugins/platforms/qoffscreen.dll",
            "PySide6/plugins/iconengines/qsvgicon.dll",
            "PySide6/support/__init__.py",
            "PySide6_Essentials-6.8.3.dist-info/METADATA",
        ):
            self.assertTrue(payload.distribution_file_allowed("pyside6-essentials", name), name)
        for name in (
            "PySide6/QtQml.pyd",
            "PySide6/Qt6Quick.dll",
            "PySide6/Qt6VirtualKeyboard.dll",
            "PySide6/qml/QtQuick/VirtualKeyboard/qtvirtualkeyboardplugin.dll",
            "PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
            "PySide6/plugins/imageformats/qpdf.dll",
            "PySide6/plugins/imageformats/qwebp.dll",
            "PySide6/designer.exe",
        ):
            self.assertFalse(payload.distribution_file_allowed("pyside6-essentials", name), name)
        self.assertTrue(payload.distribution_file_allowed("shiboken6", "shiboken6/Shiboken.pyd"))

    def test_installer_input_list_excludes_files_added_after_the_payload_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "program.py").write_text("print('synthetic')")
            (root / ".env").write_text("PRIVATE_SYNTHETIC_FIXTURE")
            write_file_list(root, ["program.py"])
            text = (root.parent / (root.name + "-files.iss")).read_text(encoding="utf-8")
            self.assertIn("program.py", text)
            self.assertNotIn(".env", text)
            self.assertNotIn('\\*"', text)
            (root.parent / (root.name + "-files.iss")).unlink()

    def test_closure_uses_selected_versions_and_skips_unrequested_extras(self):
        local = FakeDistribution("runtime", "1.2", ["base>=2", 'secret-tool; extra == "dev"'])
        base = FakeDistribution("base", "2.5")
        selected = dependency_closure(["runtime==1.2"], [local, base])
        self.assertEqual({"runtime", "base"}, set(selected))
        self.assertRaises(ValueError, dependency_closure, ["runtime==3"], [local, base])
        self.assertRaises(ValueError, dependency_closure, ["missing"], [local, base])

    def test_first_distribution_wins_and_dependency_mismatch_is_rejected(self):
        first = FakeDistribution("Qt", "6.8.3", ["binding==6.8.3"])
        later = FakeDistribution("Qt", "6.11.2")
        good = FakeDistribution("binding", "6.8.3")
        self.assertEqual(
            "6.8.3", dependency_closure(["qt==6.8.3"], [first, later, good])["qt"].version
        )
        self.assertRaises(
            ValueError, dependency_closure, ["qt"], [first, FakeDistribution("binding", "6.11.2")]
        )

    def test_record_cannot_escape_package_root_or_copy_private_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(root / "module/file.py", record_path(root, "module/file.py"))
            for name in (
                "../../../Scripts/tool.exe",
                "../.env",
                "module/../../secret.key",
                "/etc/passwd",
                "C:/private.txt",
            ):
                self.assertIsNone(record_path(root, name), name)
            self.assertIsNone(record_path(root, "module/__pycache__/file.pyc"))
            self.assertIsNone(record_path(root, "module/.env"))
            self.assertIsNone(record_path(root, "module/credential.key"))


if __name__ == "__main__":
    unittest.main()
