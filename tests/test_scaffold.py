"""daimon scaffold: an inert skeleton that works in dAImon's daemons/ or a pack's."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lib"))
import config  # noqa: E402
from daimon import scaffold  # noqa: E402


class ScaffoldTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.root, self.pack, self.other = base / "install", base / "team", base / "other"
        for d in (self.root / "daemons", self.pack, self.other):
            d.mkdir(parents=True)
        (self.root / "lib").symlink_to(ROOT / "lib")
        (self.root / "profiles").symlink_to(ROOT / "profiles")
        self.config = base / "daimon.toml"
        self.write_config([self.pack])

    def write_config(self, packs):
        paths = ", ".join(f'"{p}"' for p in packs)
        self.config.write_text(
            f'[core]\ninstall_root = "{self.root}"\nstate_dir = "{self.root}/state"\n'
            f"[packs]\npaths = [{paths}]\n"
        )
        os.environ["DAIMON_CONFIG"] = str(self.config)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("DAIMON_CONFIG", None)

    def cfg(self):
        return config.Config.load()

    def test_install_root_by_default(self):
        folder = scaffold.scaffold(self.cfg(), "triage-issues")
        self.assertEqual(folder, self.root / "daemons" / "triage-issues")
        self.assertTrue(os.access(folder / "discover.sh", os.X_OK))

    def test_bare_pack_flag_means_the_first_pack(self):
        folder = scaffold.scaffold(self.cfg(), "ops-watch", "")
        self.assertEqual(folder, self.pack / "daemons" / "ops-watch")

    def test_named_pack_must_be_configured(self):
        self.write_config([self.pack, self.other])
        self.assertEqual(
            scaffold.scaffold(self.cfg(), "x", str(self.other)), self.other / "daemons" / "x"
        )
        with self.assertRaisesRegex(ValueError, "not in \\[packs\\].paths"):
            scaffold.scaffold(self.cfg(), "y", "/nowhere")

    def test_pack_flag_without_packs(self):
        self.write_config([])
        with self.assertRaisesRegex(ValueError, "no packs configured"):
            scaffold.scaffold(self.cfg(), "x", "")

    def test_rejects_bad_and_taken_slugs(self):
        with self.assertRaisesRegex(ValueError, "lowercase words"):
            scaffold.scaffold(self.cfg(), "Bad_Slug")
        scaffold.scaffold(self.cfg(), "taken", "")
        with self.assertRaisesRegex(ValueError, "taken already exists"):
            scaffold.scaffold(self.cfg(), "taken")

    def test_skeleton_validates_renders_and_its_gate_skips(self):
        folder = scaffold.scaffold(self.cfg(), "ops-watch", "")
        cfg = self.cfg()
        self.assertEqual(config.validate(cfg), [])
        self.assertIn("# ops-watch", config.render_skill(cfg, "ops-watch"))
        gate = subprocess.run(
            ["bash", str(folder / "discover.sh")],
            env={**os.environ, "DAIMON_INSTALL_ROOT": str(self.root)},
            capture_output=True,
            text=True,
        )
        self.assertEqual((gate.returncode, gate.stderr), (1, ""))

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck not installed")
    def test_gate_template_passes_shellcheck(self):
        folder = scaffold.scaffold(self.cfg(), "ops-watch")
        r = subprocess.run(["shellcheck", str(folder / "discover.sh")], capture_output=True)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_main_reports_errors_and_parses_bare_pack(self):
        self.assertEqual(scaffold.main(["Bad"]), 1)
        self.assertEqual(scaffold.main(["ops-watch", "--pack"]), 0)
        self.assertTrue((self.pack / "daemons" / "ops-watch" / "daemon.toml").exists())


if __name__ == "__main__":
    unittest.main()
