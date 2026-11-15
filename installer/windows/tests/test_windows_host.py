import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from windows_host import patch_host, utf8_manifest  # noqa: E402


class WindowsHostTests(unittest.TestCase):
    def test_unknown_native_image_is_rejected_without_modification(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "python.exe"
            content = b"not a native image; must not change"
            path.write_bytes(content)
            with self.assertRaises((OSError, ValueError)):
                patch_host(path)
            self.assertEqual(content, path.read_bytes())

    def test_utf8_opt_in_preserves_low_privilege_and_long_path_settings(self):
        original = b"""<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
          <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>
            <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
          </requestedPrivileges></security></trustInfo>
          <application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings>
            <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
          </windowsSettings></application></assembly>"""
        root = ET.fromstring(utf8_manifest(original))
        self.assertEqual(
            "UTF-8",
            root.find(
                ".//{http://schemas.microsoft.com/SMI/2019/WindowsSettings}activeCodePage"
            ).text,
        )
        self.assertEqual(
            "asInvoker",
            root.find(".//{urn:schemas-microsoft-com:asm.v3}requestedExecutionLevel").get("level"),
        )
        self.assertEqual(
            "true",
            root.find(
                ".//{http://schemas.microsoft.com/SMI/2016/WindowsSettings}longPathAware"
            ).text,
        )

    def test_unrecognized_manifest_is_rejected_instead_of_changing_privileges(self):
        with self.assertRaises(ValueError):
            utf8_manifest(
                b'<assembly><requestedExecutionLevel level="requireAdministrator"/></assembly>'
            )
