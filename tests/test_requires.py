"""[daemon].requires: the MCP servers, CLIs and secrets a daemon needs on this
machine. Checked without starting anything, refused at registration, reported
by `daimon add` and `daimon doctor`."""

import io
import json
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from test_catalog import CatalogBase, write

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tui"))
import ops  # noqa: E402
import requires  # noqa: E402

import config  # noqa: E402
from daimon import catalog  # noqa: E402

NOPE = "no-such-cli-for-daimon-tests"


class RequiresBase(CatalogBase):
    def setUp(self):
        super().setUp()
        self.wd = self.home / "code" / "repo"
        self.wd.mkdir(parents=True)
        self.write_config('installed = ["alpha", "beta"]')

    def declare(self, requires_toml: str, slug="alpha", inputs='q = "base"', daemon=""):
        write(
            self.root / "catalog" / slug / "daemon.toml",
            f'[daemon]\nschedule = {{ interval = 600 }}\ncommand = "/{slug}"\n{daemon}\n'
            f"[daemon.requires]\n{requires_toml}\n[inputs]\n{inputs}\n",
        )
        write(
            self.conf.parent / "daemons" / f"{slug}.toml",
            f'[daemon]\nworking_dir = "{self.wd}"\n',
        )

    def claude_json(self, data: dict):
        write(self.home / ".claude.json", json.dumps(data))

    def missing(self, slug="alpha") -> list[str]:
        return requires.check(self.cfg(), slug)


class McpTest(RequiresBase):
    def setUp(self):
        super().setUp()
        self.declare('mcp = ["datadog"]')

    def test_found_at_user_scope(self):
        self.claude_json({"mcpServers": {"datadog": {"command": "x"}}})
        self.assertEqual(self.missing(), [])

    def test_found_at_local_scope_for_the_working_dir(self):
        self.claude_json({"projects": {str(self.wd): {"mcpServers": {"datadog": {}}}}})
        self.assertEqual(self.missing(), [])

    def test_local_scope_of_another_folder_does_not_count(self):
        self.claude_json({"projects": {str(self.home): {"mcpServers": {"datadog": {}}}}})
        self.assertEqual(len(self.missing()), 1)

    def test_local_scope_keyed_by_the_git_root(self):
        (self.wd / ".git").mkdir()
        sub = self.wd / "api"
        sub.mkdir()
        write(self.conf.parent / "daemons" / "alpha.toml", f'[daemon]\nworking_dir = "{sub}"\n')
        self.claude_json({"projects": {str(self.wd): {"mcpServers": {"datadog": {}}}}})
        self.assertEqual(self.missing(), [])

    def test_found_at_project_scope_in_the_folder_or_a_parent(self):
        write(self.wd.parent / ".mcp.json", json.dumps({"mcpServers": {"datadog": {}}}))
        self.assertEqual(self.missing(), [])

    def test_a_project_server_rejected_for_the_folder_does_not_count(self):
        write(self.wd / ".mcp.json", json.dumps({"mcpServers": {"datadog": {}}}))
        self.claude_json({"projects": {str(self.wd): {"disabledMcpjsonServers": ["datadog"]}}})
        self.assertEqual(len(self.missing()), 1)

    def test_missing_names_the_folder_and_how_to_add_it(self):
        self.claude_json({"mcpServers": {"other": {}}})
        [line] = self.missing()
        self.assertIn(f"MCP server 'datadog' is not configured for {self.wd}", line)
        self.assertIn("claude mcp add --scope user datadog", line)

    def test_a_server_switched_off_with_slash_mcp_is_missing(self):
        self.claude_json(
            {
                "mcpServers": {"datadog": {}},
                "projects": {str(self.wd): {"disabledMcpServers": ["datadog"]}},
            }
        )
        [line] = self.missing()
        self.assertIn("is disabled for", line)

    def test_unset_working_dir_is_named_as_the_cause(self):
        (self.conf.parent / "daemons" / "alpha.toml").unlink()
        [line] = self.missing()
        self.assertIn("working_dir is not set", line)

    def test_daimon_attached_servers_are_the_only_ones_with_strict_mcp_config(self):
        self.declare('mcp = ["datadog"]', daemon='mcp = ["codex"]')
        self.claude_json({"mcpServers": {"datadog": {}}})
        [line] = self.missing()
        self.assertIn("--strict-mcp-config", line)
        self.declare('mcp = ["codex"]', daemon='mcp = ["codex"]')
        self.assertEqual(self.missing(), [])

    def test_a_tools_daemon_gets_only_user_scope_servers_its_rules_name(self):
        tools = 'tools = ["mcp__datadog__search_logs"]'
        self.declare('mcp = ["datadog"]', daemon=tools)
        self.claude_json({"projects": {str(self.wd): {"mcpServers": {"datadog": {}}}}})
        [line] = self.missing()
        self.assertIn("[daemon].tools", line)
        self.assertIn("claude mcp add --scope user datadog", line)
        self.assertNotIn("name it in", line)

        self.claude_json({"mcpServers": {"datadog": {}}})
        self.assertEqual(self.missing(), [])

        self.declare('mcp = ["datadog"]', daemon='tools = ["Read"]')
        [line] = self.missing()
        self.assertIn("name it in [daemon].tools: mcp__datadog__<tool>", line)
        self.assertNotIn("claude mcp add", line)

    def test_a_tools_daemon_never_gets_a_plugin_server(self):
        self.declare('mcp = ["plugin:slack:slack"]', daemon='tools = ["Read"]')
        write(
            self.home / ".claude" / "settings.json",
            json.dumps({"enabledPlugins": {"slack@claude-plugins-official": True}}),
        )
        [line] = self.missing()
        self.assertIn("never a plugin's", line)

    def test_a_codex_daemon_reads_codex_config(self):
        self.declare('mcp = ["datadog"]', daemon='backend = "codex"')
        codex = self.home / "codex"
        with patch.dict(os.environ, {"CODEX_HOME": str(codex)}):
            self.assertIn("codex mcp add datadog", self.missing()[0])
            write(codex / "config.toml", '[mcp_servers.datadog]\ncommand = "x"\n')
            self.assertEqual(self.missing(), [])
            write(codex / "config.toml", "[mcp_servers.datadog]\nenabled = false\n")
            self.assertEqual(len(self.missing()), 1)

    def test_a_plugin_server_needs_the_plugin_enabled(self):
        self.declare('mcp = ["plugin:slack:slack"]')
        self.assertIn("claude plugin install slack@", self.missing()[0])
        write(
            self.home / ".claude" / "settings.json",
            json.dumps({"enabledPlugins": {"slack@claude-plugins-official": True}}),
        )
        self.assertEqual(self.missing(), [])
        write(
            self.wd / ".claude" / "settings.local.json",
            json.dumps({"enabledPlugins": {"slack@claude-plugins-official": False}}),
        )
        self.assertEqual(len(self.missing()), 1)


class CliTest(RequiresBase):
    def test_a_command_on_path_is_met(self):
        self.declare('cli = ["sh"]')
        self.assertEqual(self.missing(), [])

    def test_a_command_not_on_path_is_missing(self):
        self.declare(f'cli = ["{NOPE}"]')
        self.assertEqual(self.missing(), [f"command '{NOPE}' is not on PATH — install it"])

    def test_a_failing_check_is_missing_with_its_fix(self):
        self.declare('cli = [{ name = "sh", check = "exit 3", fix = "run: sh login" }]')
        self.assertEqual(self.missing(), ["`exit 3` failed (exit 3) — run: sh login"])

    def test_the_check_sees_the_daemons_inputs_and_runs_in_its_working_dir(self):
        check = 'test "$DAIMON_INPUT_Q" = base && test "$PWD" = "$(cd ~/code/repo && pwd -P)"'
        self.declare(f"cli = [{{ name = \"sh\", check = '{check}' }}]")
        self.assertEqual(self.missing(), [])


class CommandsTest(RequiresBase):
    def declare_token(self, command: str):
        self.declare('commands = ["token_command"]', inputs=f"token_command = '{command}'")

    def test_a_command_that_prints_is_met(self):
        self.declare_token("echo xoxb-1")
        self.assertEqual(self.missing(), [])

    def test_an_empty_input_is_missing(self):
        self.declare_token("")
        [line] = self.missing()
        self.assertIn("input 'token_command' is empty", line)
        self.assertIn("daemons/alpha.toml", line)

    def test_a_command_that_prints_nothing_is_missing(self):
        self.declare_token("true")
        self.assertIn("printed nothing", self.missing()[0])

    def test_a_failing_command_is_missing_and_its_output_never_shown(self):
        self.declare_token("echo xoxb-secret; exit 4")
        [line] = self.missing()
        self.assertIn("command failed (exit 4)", line)
        self.assertNotIn("xoxb", line)


class OneOfTest(RequiresBase):
    def test_any_one_alternative_is_enough(self):
        self.declare('one_of = [{ mcp = ["datadog"], cli = ["sh"] }]')
        self.assertEqual(self.missing(), [])

    def test_none_present_is_one_line_naming_every_alternative(self):
        self.declare(f'cli = ["sh"]\none_of = [{{ mcp = ["datadog"], cli = ["{NOPE}"] }}]')
        [line] = self.missing()
        self.assertTrue(
            line.startswith(f"one of MCP server 'datadog' or command '{NOPE}' is needed: "), line
        )
        self.assertIn("not on PATH", line)


class CommandLineTest(RequiresBase):
    def run_main(self, slug="alpha") -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            rc = requires.main([slug])
        return rc, out.getvalue()

    def test_met_prints_a_summary(self):
        self.declare('cli = ["sh"]\none_of = [{ mcp = ["datadog"], cli = ["bash"] }]')
        self.assertEqual(
            self.run_main(),
            (0, "requirements met: command 'sh', one of MCP server 'datadog' / command 'bash'\n"),
        )

    def test_nothing_declared_prints_nothing(self):
        self.assertEqual(self.run_main("beta"), (0, ""))

    def test_missing_is_exit_1_one_line_each(self):
        self.declare(f'cli = ["{NOPE}"]\nmcp = ["datadog"]')
        rc, out = self.run_main()
        self.assertEqual(rc, 1)
        self.assertEqual(len(out.splitlines()), 2)


class ValidationTest(RequiresBase):
    def errors(self) -> list[str]:
        return [e for e in config.validate(self.cfg()) if "requires" in e]

    def test_a_full_declaration_is_valid(self):
        self.declare(
            'mcp = ["mongodb"]\ncli = ["pup", { name = "gh", check = "gh auth status", fix = "gh auth login" }]\n'
            'commands = ["token_command"]\none_of = [{ mcp = ["datadog"], cli = ["pup"] }]',
            inputs='token_command = ""',
        )
        self.assertEqual(config.validate(self.cfg()), [])

    def test_malformed_entries_are_rejected(self):
        cases = {
            'mcp = "datadog"': "[daemon].requires.mcp must be a list",
            'mcp = [""]': "entries must be non-empty strings",
            'clis = ["pup"]': "unknown key 'clis'",
            'cli = [{ nam = "pup" }]': "must be a name or",
            "cli = [{ name = 1 }]": "must be a name or",
            'commands = ["nope"]': "'nope' is not one of the daemon's [inputs]",
            'one_of = [{ cli = ["pup"] }]': "one_of[0] needs at least two alternatives",
            'one_of = ["pup"]': "one_of[0] must be a table",
            'one_of = [{ one_of = [] , cli = ["a", "b"] }]': "one_of[0]: unknown key 'one_of'",
        }
        for toml, expected in cases.items():
            with self.subTest(toml=toml):
                self.declare(toml)
                errors = self.errors()
                self.assertTrue(any(expected in e for e in errors), errors)


class EnforcementTest(RequiresBase):
    def test_add_prints_what_is_missing(self):
        self.write_config("installed = []")
        self.declare(f'cli = ["{NOPE}"]')
        out = io.StringIO()
        with patch.object(catalog, "_sync", return_value=True), redirect_stdout(out):
            rc = catalog.main(["add", "alpha"])
        self.assertEqual(rc, 0)
        self.assertIn("alpha can't be registered until this machine has:", out.getvalue())
        self.assertIn(f"command '{NOPE}' is not on PATH", out.getvalue())

    def test_tui_register_is_refused_and_writes_nothing(self):
        self.declare(f'cli = ["{NOPE}"]')
        plist = self.home / "Library" / "LaunchAgents" / "com.daimon.alpha.plist"
        with patch.object(ops.subprocess, "run") as run:
            err = ops.register(self.cfg(), "alpha")
        self.assertEqual(
            err, f"alpha not registered — missing:\ncommand '{NOPE}' is not on PATH — install it"
        )
        run.assert_not_called()
        self.assertFalse(plist.exists())

    def test_tui_register_goes_ahead_when_met(self):
        self.declare('cli = ["sh"]')
        plist = self.home / "Library" / "LaunchAgents" / "com.daimon.alpha.plist"
        plist.parent.mkdir(parents=True)
        with patch.object(ops.subprocess, "run") as run:
            self.assertIsNone(ops.register(self.cfg(), "alpha"))
        self.assertTrue(plist.exists())
        self.assertEqual(run.call_args.args[0][:2], ["launchctl", "bootstrap"])
