import io
import os
import shlex
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import config  # noqa: E402


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))


class ConfigTest(unittest.TestCase):
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
            model = "opus"
            danger = true
            stuck_after = 2700
            ready_timeout = 20
            [throttle]
            exempt = ["alpha"]
            moderate_mod = 2
            severe_mod = 4
            severe_critical = ["beta"]
            [budget]
            hourly_cap = 12
            defer_at_pct = 80
            [daemons]
            disabled = ["delta"]
        """,
        )
        write(
            root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            schedule = { interval = 1200 }
            command = "/alpha"
            stuck_after = 600
            [inputs]
            repo = "me/alpha"
            filter = "is:open"
        """,
        )
        write(
            root / "daemons" / "alpha" / "skill" / "SKILL.md",
            "---\nname: alpha\ndescription: a\n---\nRepo {{inputs.repo}} filter {{inputs.filter}}.\n",
        )
        write(
            root / "daemons" / "beta" / "daemon.toml",
            """
            [daemon]
            backend = "claude"
            model = { claude = "opus", default = "sonnet" }
            schedule = { minutes = [17, 47] }
            command = "/beta"
        """,
        )
        write(
            root / "daemons" / "beta" / "skill" / "SKILL.md",
            "---\nname: beta\ndescription: b\n---\nHi.\n",
        )
        write(
            root / "daemons" / "gamma" / "daemon.toml",
            """
            [daemon]
            schedule = { daily = "13:02", tz = "UTC" }
            command = "/gamma"
        """,
        )
        write(
            root / "daemons" / "gamma" / "skill" / "SKILL.md",
            "---\nname: gamma\ndescription: c\n---\nHi.\n",
        )
        write(
            root / "daemons" / "delta" / "daemon.toml",
            """
            [daemon]
            schedule = { interval = 900 }
            command = "/delta"
        """,
        )
        write(
            root / "daemons" / "delta" / "skill" / "SKILL.md",
            "---\nname: delta\ndescription: d\n---\nHi.\n",
        )
        os.environ["DAIMON_CONFIG"] = str(root / "config" / "daimon.toml")
        self.cfg = config.Config.load()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("DAIMON_CONFIG", None)

    def test_discovery_excludes_disabled(self):
        self.assertEqual(set(self.cfg.discover()), {"alpha", "beta", "gamma"})

    def test_defaults_inherited(self):
        self.assertEqual(self.cfg.daemon("beta")["danger"], True)
        self.assertEqual(self.cfg.daemon("beta")["stuck_after"], 2700)

    def test_per_daemon_override(self):
        self.assertEqual(self.cfg.daemon("alpha")["stuck_after"], 600)

    def test_working_dir_unset_falls_back_but_is_not_configured(self):
        daemon = self.cfg.daemon("alpha")
        self.assertEqual(daemon["working_dir"], str(self.root.resolve()))
        self.assertFalse(daemon["working_dir_configured"])

    def test_working_dir_placeholder_is_not_configured(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.local.toml",
            """
            [daemon]
            working_dir = "~/code/your-repo"
            """,
        )
        daemon = config.Config.load().daemon("alpha")
        self.assertFalse(daemon["working_dir_configured"])

    def test_explicit_install_root_working_dir_is_configured(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.local.toml",
            f"""
            [daemon]
            working_dir = "{self.root}"
            """,
        )
        daemon = config.Config.load().daemon("alpha")
        self.assertEqual(daemon["working_dir"], str(self.root.resolve()))
        self.assertTrue(daemon["working_dir_configured"])

    def _make_sourced_daemon(self):
        write(
            self.root / "profiles" / "sc" / "profile.toml",
            """
            [profile]
            tool = "sc"
            [defaults]
            owner = "me"
            team = "t"
            """,
        )
        write(
            self.root / "daemons" / "epsilon" / "daemon.toml",
            """
            [daemon]
            sources = ["sc"]
            schedule = { interval = 900 }
            command = "/epsilon"
            [inputs]
            filter = "x"
            owner = "override-me"
            """,
        )
        write(
            self.root / "daemons" / "epsilon" / "skill" / "SKILL.md",
            "---\nname: epsilon\ndescription: e\n---\nHi.\n",
        )
        return config.Config.load()

    def test_input_provenance_splits_daemon_and_profile(self):
        cfg = self._make_sourced_daemon()
        prov = cfg.input_provenance("epsilon")
        # daemon owns its own inputs, including a key that overrides a profile default
        self.assertEqual(prov["daemon"], {"filter": "x", "owner": "override-me"})
        # profile contributes only non-overridden defaults
        self.assertEqual(prov["profiles"], {"sc": {"team": "t"}})

    def test_update_profile_local_is_shared_and_not_daemon_local(self):
        cfg = self._make_sourced_daemon()
        cfg.update_profile_local("sc", {"team": "t2"})
        fresh = config.Config.load()
        self.assertEqual(fresh.input_provenance("epsilon")["profiles"]["sc"]["team"], "t2")
        self.assertNotIn("team", fresh.raw_daemon("epsilon")["inputs"])

    def test_backends(self):
        self.assertEqual(self.cfg.backends("alpha"), ["claude"])
        self.assertEqual(self.cfg.backends("beta"), ["claude"])

    def test_backends_appends_optional_fallback(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            backend = "claude"
            fallback_backend = "codex"
            model = { claude = "opus", codex = "gpt-5.3-codex" }
            schedule = { interval = 1200 }
            command = "/alpha"
            """,
        )
        cfg = config.Config.load()
        self.assertEqual(cfg.backends("alpha"), ["claude", "codex"])
        self.assertEqual(cfg.model_for("alpha", "codex"), "gpt-5.3-codex")

    def test_backends_all_lists_every_known_backend(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            config.main(["backends-all"])
        self.assertEqual(buf.getvalue().split(), list(config.BACKENDS))

    def test_model_scalar_and_table(self):
        self.assertEqual(self.cfg.model_for("alpha", "claude"), "opus")
        self.assertEqual(self.cfg.model_for("beta", "claude"), "opus")
        self.assertEqual(self.cfg.model_for("beta", "other"), "sonnet")

    def test_env_shell_quotes_spaced_values(self):
        # `cfg env` output is eval'd by run.sh, so values with spaces (e.g. a
        # Shortcut state "In Progress") must be shell-quoted or the eval breaks
        # and later DAIMON_INPUT_* vars never get exported.
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            schedule = { interval = 1200 }
            command = "/alpha"
            [inputs]
            in_progress_state = "In Progress"
            ready_label = "auto-ready"
        """,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            config.main(["env", "alpha"])
        env = self._parse_env_output(buf.getvalue())
        self.assertEqual(env["DAIMON_INPUT_IN_PROGRESS_STATE"], "In Progress")
        self.assertEqual(env["DAIMON_INPUT_READY_LABEL"], "auto-ready")

    def test_daemon_env_bundles_all_launch_fields(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            config.main(["daemon-env", "alpha"])
        env = self._parse_env_output(buf.getvalue())
        d = self.cfg.daemon("alpha")
        self.assertEqual(env["DAIMON_D_COMMAND"], d["command"])
        self.assertEqual(env["DAIMON_D_DANGER"], "1")
        self.assertEqual(env["DAIMON_D_STUCK_AFTER"], str(d["stuck_after"]))
        self.assertEqual(env["DAIMON_D_WORKING_DIR"], d["working_dir"])
        self.assertEqual(env["DAIMON_D_BACKENDS"], "claude")
        self.assertEqual(env["DAIMON_READY_TIMEOUT"], "20")
        self.assertEqual(env["DAIMON_D_MODEL_CLAUDE"], self.cfg.model_for("alpha", "claude"))

    def test_daemon_env_bundles_fallback_model(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            fallback_backend = "codex"
            model = { claude = "opus", codex = "gpt-5.3-codex" }
            schedule = { interval = 1200 }
            command = "/alpha"
            """,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            config.main(["daemon-env", "alpha"])
        env = self._parse_env_output(buf.getvalue())
        self.assertEqual(env["DAIMON_D_BACKENDS"], "claude codex")
        self.assertEqual(env["DAIMON_D_MODEL_CODEX"], "gpt-5.3-codex")

    def test_mcp_absent_by_default(self):
        self.assertEqual(self.cfg.daemon("alpha")["mcp"], [])
        self.assertEqual(self.cfg.mcp_config("alpha"), {})
        buf = io.StringIO()
        with redirect_stdout(buf):
            config.main(["daemon-env", "alpha"])
        env = self._parse_env_output(buf.getvalue())
        self.assertEqual(env["DAIMON_D_MCP"], "")

    def test_mcp_opt_in_exports_and_renders_config(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            schedule = { interval = 1200 }
            command = "/alpha"
            mcp = ["codex"]
        """,
        )
        cfg = config.Config.load()
        self.assertEqual(cfg.daemon("alpha")["mcp"], ["codex"])
        self.assertEqual(
            cfg.mcp_config("alpha"),
            {"mcpServers": {"codex": config.MCP_SERVERS["codex"]}},
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            config.main(["daemon-env", "alpha"])
        self.assertEqual(self._parse_env_output(buf.getvalue())["DAIMON_D_MCP"], "codex")

    def test_mcp_inherited_from_defaults(self):
        write(
            self.root / "config" / "daimon.toml",
            f"""
            [core]
            install_root = "{self.root}"
            state_dir = "{self.root}/state"
            namespace = "testns"
            [defaults]
            mcp = ["codex"]
        """,
        )
        self.assertEqual(config.Config.load().daemon("alpha")["mcp"], ["codex"])

    def test_tools_absent_by_default(self):
        self.assertEqual(self.cfg.daemon("alpha")["tools"], [])
        buf = io.StringIO()
        with redirect_stdout(buf):
            config.main(["daemon-env", "alpha"])
        self.assertEqual(self._parse_env_output(buf.getvalue())["DAIMON_D_TOOLS"], "")

    def test_tools_exported_as_shell_words(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            schedule = { interval = 1200 }
            command = "/alpha"
            tools = ["Read", "Bash(git log:*)"]
        """,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            config.main(["daemon-env", "alpha"])
        words = self._parse_env_output(buf.getvalue())["DAIMON_D_TOOLS"]
        self.assertEqual(shlex.split(words), ["Read", "Bash(git log:*)"])

    def test_validate_rejects_tools_with_codex(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            fallback_backend = "codex"
            schedule = { interval = 1200 }
            command = "/alpha"
            tools = ["Read"]
        """,
        )
        errs = config.validate(config.Config.load())
        self.assertTrue(any("tools allowlist is claude-only" in e for e in errs))

    def test_discover_memoized_and_invalidated_on_write(self):
        first = self.cfg.discover()
        self.assertIs(first, self.cfg.discover())
        self.cfg.update_daemon_field("alpha", "command", "/alpha2")
        self.assertIsNot(first, self.cfg.discover())
        self.assertEqual(self.cfg.daemon("alpha")["command"], "/alpha2")

    def test_validate_inputs_flags_empty_required(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            schedule = { interval = 1200 }
            command = "/alpha"
            required_inputs = ["ready_label", "skip_label"]
            [inputs]
            ready_label = "auto-ready"
            skip_label = "   "
        """,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = config.main(["validate-inputs", "alpha"])
        self.assertEqual(rc, 1)
        self.assertEqual(buf.getvalue().strip(), "skip_label")

    def test_validate_inputs_passes_when_all_present(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            schedule = { interval = 1200 }
            command = "/alpha"
            required_inputs = ["ready_label"]
            [inputs]
            ready_label = "auto-ready"
        """,
        )
        self.assertEqual(config.main(["validate-inputs", "alpha"]), 0)

    def _parse_env_output(self, output):
        # Mimic run.sh's eval: each line must be a single shell token (a
        # well-formed VAR=value), or word-splitting on a spaced value would
        # break the eval and drop later assignments.
        env = {}
        for line in filter(None, output.splitlines()):
            tokens = shlex.split(line)
            self.assertEqual(len(tokens), 1, f"line not shell-safe: {line!r}")
            key, _, value = tokens[0].partition("=")
            env[key] = value
        return env

    def test_render_skill_substitutes_inputs(self):
        out = config.render_skill(self.cfg, "alpha")
        self.assertIn("Repo me/alpha filter is:open.", out)
        self.assertNotIn("{{inputs", out)

    def test_render_skill_appends_learning_protocol(self):
        write(self.root / "references" / "learning.md", "LEARNING PROTOCOL BODY\n")
        out = config.render_skill(self.cfg, "alpha")
        self.assertIn("LEARNING PROTOCOL BODY", out)

    def test_render_skill_learning_opt_out(self):
        write(self.root / "references" / "learning.md", "LEARNING PROTOCOL BODY\n")
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            schedule = { interval = 1200 }
            command = "/alpha"
            learning = false
            [inputs]
            repo = "me/alpha"
        """,
        )
        out = config.render_skill(config.Config.load(), "alpha")
        self.assertNotIn("LEARNING PROTOCOL BODY", out)

    def test_codex_review_ref_appended_when_mcp_enabled(self):
        write(self.root / "references" / "codex-review.md", "CODEX SECOND OPINION BODY\n")
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            schedule = { interval = 1200 }
            command = "/alpha"
            mcp = ["codex"]
            [inputs]
            repo = "me/alpha"
        """,
        )
        out = config.render_skill(config.Config.load(), "alpha")
        self.assertIn("CODEX SECOND OPINION BODY", out)

    def test_codex_review_ref_skipped_without_mcp(self):
        write(self.root / "references" / "codex-review.md", "CODEX SECOND OPINION BODY\n")
        out = config.render_skill(self.cfg, "alpha")
        self.assertNotIn("CODEX SECOND OPINION BODY", out)

    def test_conventions_appended_for_bot_marker_daemons(self):
        write(self.root / "references" / "skill-conventions.md", "PREFIX {{inputs.bot_marker}}\n")
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            schedule = { interval = 1200 }
            command = "/alpha"
            [inputs]
            bot_marker = "BOT"
        """,
        )
        out = config.render_skill(config.Config.load(), "alpha")
        self.assertIn("PREFIX BOT", out)

    def test_conventions_skipped_without_bot_marker(self):
        write(self.root / "references" / "skill-conventions.md", "CONVENTIONS BODY\n")
        out = config.render_skill(self.cfg, "gamma")
        self.assertNotIn("CONVENTIONS BODY", out)

    def test_render_plist_contains_label_and_slug(self):
        xml = config.render_plist(self.cfg, "alpha")
        self.assertIn("<string>com.testns.alpha</string>", xml)
        self.assertIn("<string>alpha</string>", xml)
        self.assertIn("StartInterval", xml)

    def test_validate_clean(self):
        self.assertEqual(config.validate(self.cfg), [])

    def test_validate_catches_bad_backend(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            backend = "gpt"
            schedule = { interval = 1200 }
            command = "/alpha"
        """,
        )
        errs = config.validate(config.Config.load())
        self.assertTrue(any("backend must be one of" in e for e in errs))

    def test_validate_catches_bad_fallback_backend(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            fallback_backend = "gpt"
            schedule = { interval = 1200 }
            command = "/alpha"
            """,
        )
        errs = config.validate(config.Config.load())
        self.assertTrue(any("fallback_backend must be one of" in e for e in errs))

    def test_validate_catches_fallback_matching_primary(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            backend = "claude"
            fallback_backend = "claude"
            schedule = { interval = 1200 }
            command = "/alpha"
            """,
        )
        errs = config.validate(config.Config.load())
        self.assertTrue(any("fallback_backend must differ" in e for e in errs))

    def test_validate_catches_empty_required_input(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            schedule = { interval = 1200 }
            command = "/alpha"
            required_inputs = ["repo", "token"]
            [inputs]
            repo = "me/alpha"
            token = ""
        """,
        )
        errs = config.validate(config.Config.load())
        self.assertTrue(any("required input 'token'" in e for e in errs))
        self.assertFalse(any("required input 'repo'" in e for e in errs))

    def test_validate_catches_missing_command(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            schedule = { interval = 1200 }
        """,
        )
        errs = config.validate(config.Config.load())
        self.assertTrue(any("command" in e for e in errs))

    def test_codex_backend_validates_and_resolves_model(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            backend = "codex"
            model = { codex = "gpt-5.3-codex", default = "opus" }
            schedule = { interval = 1200 }
            command = "/alpha"
            [inputs]
            repo = "me/alpha"
        """,
        )
        cfg = config.Config.load()
        self.assertEqual(config.validate(cfg), [])
        self.assertEqual(cfg.backends("alpha"), ["codex"])
        self.assertEqual(cfg.model_for("alpha", "codex"), "gpt-5.3-codex")

    def test_validate_catches_unknown_mcp_server(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            schedule = { interval = 1200 }
            command = "/alpha"
            mcp = ["nope"]
        """,
        )
        errs = config.validate(config.Config.load())
        self.assertTrue(any("unknown mcp server 'nope'" in e for e in errs))

    def test_validate_catches_mcp_without_danger(self):
        write(
            self.root / "daemons" / "alpha" / "daemon.toml",
            """
            [daemon]
            schedule = { interval = 1200 }
            command = "/alpha"
            danger = false
            mcp = ["codex"]
        """,
        )
        errs = config.validate(config.Config.load())
        self.assertTrue(any("mcp requires danger=true" in e for e in errs))


if __name__ == "__main__":
    unittest.main()
