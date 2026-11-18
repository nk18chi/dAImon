import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import config  # noqa: E402


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))


class ProfileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        write(
            root / "config" / "daimon.toml",
            f"""
            [core]
            install_root = "{root}"
            state_dir = "{root}/state"
            namespace = "testns"
            [defaults]
            backend = "claude"
            stuck_after = 2700
            [daemons]
            disabled = []
        """,
        )
        write(
            root / "profiles" / "sc" / "profile.toml",
            """
            [profile]
            tool = "sc"
            [defaults]
            workspace = "ws-default"
            ready_label = "ai-ready"
            triage_state = "To Do"
        """,
        )
        write(
            root / "profiles" / "sc" / "reference.md", "REF-MARKER labels: {{inputs.ready_label}}"
        )
        write(
            root / "catalog" / "wq" / "daemon.toml",
            """
            [daemon]
            source = "sc"
            schedule = { interval = 1200 }
            command = "/wq"
            [inputs]
            base = "main"
            repos = []
        """,
        )
        write(
            root / "catalog" / "wq" / "skill" / "SKILL.md",
            "ready={{inputs.ready_label}} ws={{inputs.workspace}} repos={{inputs.repos}}\n",
        )
        os.environ["DAIMON_CONFIG"] = str(root / "config" / "daimon.toml")
        self.cfg = config.Config.load()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("DAIMON_CONFIG", None)

    def test_profile_defaults_merge_under_inputs(self):
        d = self.cfg.daemon("wq")
        self.assertEqual(d["inputs"]["workspace"], "ws-default")
        self.assertEqual(d["inputs"]["ready_label"], "ai-ready")
        self.assertEqual(d["inputs"]["base"], "main")

    def test_daemon_inputs_override_profile(self):
        write(
            self.root / "catalog" / "wq" / "daemon.toml",
            """
            [daemon]
            source = "sc"
            schedule = { interval = 1200 }
            command = "/wq"
            [inputs]
            ready_label = "ai-go"
        """,
        )
        self.assertEqual(config.Config.load().daemon("wq")["inputs"]["ready_label"], "ai-go")

    def test_profile_local_overrides_profile(self):
        write(
            self.root / "profiles" / "sc" / "profile.local.toml",
            '[defaults]\nworkspace = "ws-local"\n',
        )
        self.assertEqual(config.Config.load().daemon("wq")["inputs"]["workspace"], "ws-local")

    def test_daemon_local_overrides_committed(self):
        write(
            self.root / "catalog" / "wq" / "daemon.local.toml",
            '[daemon]\nworking_dir = "~/x"\n[inputs]\nrepos = ["hub"]\n',
        )
        d = config.Config.load().daemon("wq")
        self.assertTrue(d["working_dir"].endswith("/x"))
        self.assertEqual(d["inputs"]["repos"], ["hub"])

    def test_update_local_does_not_touch_committed(self):
        committed = self.root / "catalog" / "wq" / "daemon.toml"
        before = committed.read_text()
        self.cfg.update_local("wq", {"stuck_after": 999}, None)
        self.assertEqual(committed.read_text(), before)
        local = self.root / "config" / "daemons" / "wq.toml"
        self.assertIn("999", local.read_text())
        self.assertFalse((self.root / "catalog" / "wq" / "daemon.local.toml").exists())
        self.assertEqual(config.Config.load().daemon("wq")["stuck_after"], 999)

    def test_render_appends_reference_and_joins_lists(self):
        write(self.root / "catalog" / "wq" / "daemon.local.toml", '[inputs]\nrepos = ["a", "b"]\n')
        out = config.render_skill(config.Config.load(), "wq")
        self.assertIn("REF-MARKER", out)
        self.assertIn("repos=a, b", out)
        self.assertNotIn("{{", out)

    def test_source_string_is_back_compat_single_source(self):
        self.assertEqual(self.cfg.daemon("wq")["sources"], ["sc"])

    def test_write_source_appends_write_reference(self):
        write(self.root / "profiles" / "sc" / "reference.write.md", "WRITE-MARKER")
        write(
            self.root / "catalog" / "wq" / "daemon.toml",
            """
            [daemon]
            sources = [{ name = "sc", write = true }]
            schedule = { interval = 1200 }
            command = "/wq"
            [inputs]
            repos = []
        """,
        )
        d = config.Config.load().daemon("wq")
        self.assertEqual(d["write_sources"], ["sc"])
        out = config.render_skill(config.Config.load(), "wq")
        self.assertIn("REF-MARKER", out)
        self.assertIn("WRITE-MARKER", out)

    def test_read_only_source_omits_write_reference(self):
        write(self.root / "profiles" / "sc" / "reference.write.md", "WRITE-MARKER")
        d = self.cfg.daemon("wq")
        self.assertEqual(d["write_sources"], [])
        out = config.render_skill(self.cfg, "wq")
        self.assertIn("REF-MARKER", out)
        self.assertNotIn("WRITE-MARKER", out)

    def test_multiple_sources_merge_defaults_and_append_each_reference(self):
        write(
            self.root / "profiles" / "gh" / "profile.toml",
            """
            [profile]
            tool = "gh"
            [defaults]
            workspace = "ws-gh"
            base = "trunk"
        """,
        )
        write(self.root / "profiles" / "gh" / "reference.md", "GH-MARKER base {{inputs.base}}")
        write(
            self.root / "catalog" / "wq" / "daemon.toml",
            """
            [daemon]
            sources = ["sc", "gh"]
            schedule = { interval = 1200 }
            command = "/wq"
            [inputs]
            repos = []
        """,
        )
        d = config.Config.load().daemon("wq")
        self.assertEqual(d["sources"], ["sc", "gh"])
        self.assertEqual(d["inputs"]["workspace"], "ws-gh")
        self.assertEqual(d["inputs"]["ready_label"], "ai-ready")
        self.assertEqual(d["inputs"]["base"], "trunk")
        out = config.render_skill(config.Config.load(), "wq")
        self.assertIn("REF-MARKER", out)
        self.assertIn("GH-MARKER", out)

    def test_validate_flags_unknown_among_multiple_sources(self):
        write(
            self.root / "catalog" / "wq" / "daemon.toml",
            """
            [daemon]
            sources = ["sc", "nope"]
            schedule = { interval = 1200 }
            command = "/wq"
        """,
        )
        errs = config.validate(config.Config.load())
        self.assertTrue(any("unknown source profile 'nope'" in e for e in errs))

    def test_validate_unknown_profile(self):
        write(
            self.root / "catalog" / "wq" / "daemon.toml",
            """
            [daemon]
            source = "nope"
            schedule = { interval = 1200 }
            command = "/wq"
        """,
        )
        errs = config.validate(config.Config.load())
        self.assertTrue(any("unknown source profile" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
