import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
import model_licenses  # noqa: E402


class ModelLicenseTests(unittest.TestCase):
    def fixture(self, root, status="approved"):
        notice = root / "notice.txt"
        notice.write_text("Synthetic permission notice", encoding="utf-8")
        registry = root / "registry.json"
        registry.write_text(
            json.dumps(
                dict(
                    format=1,
                    profiles={"synthetic": ["voice"]},
                    models={
                        "voice": dict(
                            status=status,
                            license="MIT",
                            reason="Synthetic test only",
                            evidence=[
                                dict(
                                    file="notice.txt",
                                    sha256=hashlib.sha256(notice.read_bytes()).hexdigest(),
                                )
                            ],
                        )
                    },
                )
            ),
            encoding="utf-8",
        )
        return registry, notice

    def test_release_requires_approved_models_and_unchanged_permission_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            registry, notice = self.fixture(Path(folder))
            with patch.object(model_licenses, "REGISTRY_PATH", registry):
                report = model_licenses.review("synthetic", ["voice"])
                self.assertTrue(report["public_redistribution"])
                notice.write_text("changed", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "evidence"):
                    model_licenses.review("synthetic", ["voice"])

    def test_unresolved_model_blocks_release_but_private_mode_never_grants_permission(self):
        with tempfile.TemporaryDirectory() as folder:
            registry, _ = self.fixture(Path(folder), "unresolved")
            with patch.object(model_licenses, "REGISTRY_PATH", registry):
                with self.assertRaisesRegex(ValueError, "voice"):
                    model_licenses.review("synthetic", ["voice"])
                report = model_licenses.review("synthetic", ["voice"], private_development=True)
                self.assertFalse(report["public_redistribution"])
                self.assertEqual(report["mode"], "private-development")

    def test_unregistered_model_or_profile_cannot_reuse_another_models_permission(self):
        with tempfile.TemporaryDirectory() as folder:
            registry, _ = self.fixture(Path(folder))
            with patch.object(model_licenses, "REGISTRY_PATH", registry):
                for profile, names in [("missing", ["voice"]), ("synthetic", ["other"])]:
                    with self.assertRaises(ValueError):
                        model_licenses.review(profile, names)

    def test_reviewed_weights_cannot_be_replaced_by_another_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            asset = root / "model.bin"
            asset.write_bytes(b"synthetic-reviewed-model")
            model = dict(
                artifact_sha256={"model.bin": hashlib.sha256(asset.read_bytes()).hexdigest()}
            )
            model_licenses.verify_artifacts(model, root)
            asset.write_bytes(b"synthetic-other-model")
            with self.assertRaisesRegex(ValueError, "artifact"):
                model_licenses.verify_artifacts(model, root)

    def test_bundle_cannot_upgrade_private_or_legacy_payload_to_public_release(self):
        with tempfile.TemporaryDirectory() as folder:
            registry, _ = self.fixture(Path(folder), "unresolved")
            with patch.object(model_licenses, "REGISTRY_PATH", registry):
                report = model_licenses.review("synthetic", ["voice"], private_development=True)
                for record in ({}, {"model_licenses": report}):
                    with self.assertRaises(ValueError):
                        model_licenses.verify_payload(record, "synthetic", ["voice"])
                model_licenses.verify_payload(
                    {"model_licenses": report}, "synthetic", ["voice"], private_development=True
                )
                report["registry_sha256"] = "0" * 64
                with self.assertRaises(ValueError):
                    model_licenses.verify_payload(
                        {"model_licenses": report},
                        "synthetic",
                        ["voice"],
                        private_development=True,
                    )

    def test_even_approved_models_require_a_fresh_public_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            registry, _ = self.fixture(Path(folder))
            with patch.object(model_licenses, "REGISTRY_PATH", registry):
                private = model_licenses.review("synthetic", ["voice"], private_development=True)
                with self.assertRaisesRegex(ValueError, "Private payload"):
                    model_licenses.verify_payload(
                        {"model_licenses": private}, "synthetic", ["voice"]
                    )
                public = model_licenses.review("synthetic", ["voice"])
                model_licenses.verify_payload({"model_licenses": public}, "synthetic", ["voice"])

    def test_current_profiles_have_public_model_permission_evidence_at_cli(self):
        for profile in ("windows", "android"):
            result = subprocess.run(
                [sys.executable, "-B", str(ROOT / "tools/model_licenses.py"), profile],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["public_redistribution"])
            self.assertNotIn("asr", report["models"])
            self.assertNotIn("tts-yue", report["models"])

    def test_packaging_permission_checks_do_not_create_output_or_download(self):
        output = ROOT / "outputs" / "license-test-must-not-be-created"
        self.assertFalse(output.exists())
        commands = [
            [str(ROOT / "installer/windows/payload.py"), "--output", str(output)],
            [str(ROOT / "android/tools/prepare_models.py"), "--output", str(output)],
            [
                str(ROOT / "installer/windows/bundle.py"),
                "--installer-dir",
                str(output),
                "--payload",
                str(output),
                "--output",
                str(output / "private.zip"),
            ],
        ]
        for command in commands:
            result = subprocess.run(
                [sys.executable, "-B", *command, "--check-licenses"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=15,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["public_redistribution"])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
