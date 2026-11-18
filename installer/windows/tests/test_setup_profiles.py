"""Exercise Windows setup selection without network, model downloads or user settings."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SETUP = Path(__file__).resolve().parents[3] / "Initialize-YuePu.cmd"


@unittest.skipUnless(os.name == "nt", "Windows batch entry")
class SetupProfileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "project with spaces"
        self.root.mkdir()
        shutil.copyfile(SETUP, self.root / SETUP.name)

    def invoke(self, *args):
        return subprocess.run(
            [os.environ["COMSPEC"], "/d", "/c", SETUP.name, *args],
            cwd=self.root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_plans_run_before_environment_setup(self):
        base = "asr canto hymt2 runtime mandarin vad"
        for args, groups in (
            (["text"], ["hymt2 runtime"]),
            (["FLASH"], [base]),
            (["pro"], [base, "song-asr-large"]),
            ([], [base, "song-asr-large"]),
        ):
            with self.subTest(args=args):
                result = self.invoke("--plan", *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(
                    [
                        line.removeprefix("Model components: ")
                        for line in result.stdout.splitlines()
                        if line.startswith("Model components: ")
                    ],
                    groups,
                )
        self.assertEqual({p.name for p in self.root.iterdir()}, {SETUP.name})
        self.assertNotEqual(self.invoke("--plan", "bogus").returncode, 0)
        self.assertNotEqual(self.invoke("text", "extra").returncode, 0)

    def test_noninteractive_dispatch_runs_only_selected_model_groups(self):
        if sys.version_info[:2] != (3, 12) or sys.maxsize <= 2**32:
            self.skipTest("Setup requires an x64 3.12 interpreter")
        subprocess.run(
            [sys.executable, "-m", "venv", "--without-pip", self.root / ".venv"], check=True
        )
        # Keep the real batch entry and interpreter; stub only the installers.
        (self.root / "pip.py").write_text("pass\n", encoding="ascii")
        prepare = self.root / "experiments" / "offline-poc" / "prepare_models.py"
        prepare.parent.mkdir(parents=True)
        prepare.write_text(
            "from pathlib import Path\nimport sys\n"
            "with Path('calls.txt').open('a', encoding='ascii') as out:\n"
            "    print(' '.join(sys.argv[1:]), file=out)\n",
            encoding="ascii",
        )
        calls = self.root / "calls.txt"
        base = "asr canto hymt2 runtime mandarin vad"
        for profile, groups in (
            ("text", ["hymt2 runtime"]),
            ("flash", [base]),
            ("pro", [base, "song-asr-large"]),
        ):
            with self.subTest(profile=profile):
                result = self.invoke(profile)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(calls.read_text(encoding="ascii").splitlines(), groups)
                calls.unlink()
