import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import agent_status  # noqa: E402

import config  # noqa: E402


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))


class AgentStatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.conf = self.root / "config" / "daimon.toml"
        self._write_config("")
        for slug in ("alpha", "beta", "gamma", "delta"):
            write(
                self.root / "catalog" / slug / "daemon.toml",
                f"""
                [daemon]
                schedule = {{ interval = 600 }}
                command = "/{slug}"
            """,
            )
        write(self.root / "catalog" / "beta" / "daemon.local.toml", '[daemon]\nrole = "triage"\n')
        os.environ["DAIMON_CONFIG"] = str(self.conf)
        self.cfg = config.Config.load()

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("DAIMON_CONFIG", None)

    def _write_config(self, status: str):
        write(
            self.conf,
            f"""
            [core]
            install_root = "{self.root}"
            state_dir = "{self.root}/state"
            namespace = "testns"
            [throttle]
            exempt = ["gamma"]
            [daemons]
            disabled = ["delta"]
            {status}
        """,
        )

    def _agents(self, loaded, running=(), level="off"):
        return agent_status.build(self.cfg, set(loaded), set(running), level)["agents"]

    def test_working_and_idle(self):
        agents = self._agents({"alpha", "gamma"}, running={"alpha"})
        self.assertEqual(
            agents,
            [{"name": "alpha", "state": "working"}, {"name": "gamma", "state": "idle"}],
        )

    def test_halt_blocks_idle_daemons_but_not_working_or_exempt_ones(self):
        agents = self._agents({"alpha", "beta", "gamma"}, running={"alpha"}, level="halt")
        by_name = {a["name"]: a for a in agents}
        self.assertEqual(by_name["alpha"], {"name": "alpha", "state": "working"})
        self.assertEqual(
            by_name["beta"],
            {"name": "beta", "state": "blocked", "role": "triage", "note": "throttled"},
        )
        self.assertEqual(by_name["gamma"], {"name": "gamma", "state": "idle"})

    def test_lesser_throttle_levels_do_not_block(self):
        for level in ("off", "moderate", "severe"):
            with self.subTest(level=level):
                self.assertEqual(self._agents({"alpha"}, level=level)[0]["state"], "idle")

    def test_role_included_only_when_set(self):
        agents = self._agents({"alpha", "beta"})
        self.assertNotIn("role", agents[0])
        self.assertEqual(agents[1]["role"], "triage")

    def test_unloaded_and_disabled_daemons_are_omitted(self):
        agents = self._agents({"alpha", "delta"}, running={"beta"})
        self.assertEqual([a["name"] for a in agents], ["alpha"])

    def test_caps_at_32_agents(self):
        for i in range(40):
            write(
                self.root / "catalog" / f"d{i:02d}" / "daemon.toml",
                "[daemon]\nschedule = { interval = 600 }\n",
            )
        cfg = config.Config.load()
        agents = agent_status.build(cfg, set(cfg.discover()), set(), "off")["agents"]
        self.assertEqual(len(agents), agent_status.MAX_AGENTS)

    def test_output_is_json_with_an_agents_list(self):
        doc = json.loads(json.dumps(agent_status.build(self.cfg, set(), set(), "off")))
        self.assertEqual(doc, {"agents": []})

    def test_loaded_slugs_from_launchctl_list(self):
        out = "PID\tStatus\tLabel\n-\t0\ttestns.alpha\n123\t0\tcom.testns.beta\n-\t0\tcom.other.gamma\n"
        self.assertEqual(
            agent_status.loaded_slugs(out, "testns", ["alpha", "beta", "gamma"]), {"beta"}
        )

    def test_running_slugs_from_session_names(self):
        sessions = ["testns-alpha", "testns-beta-codex", "testns-gamma-x", "other-delta"]
        self.assertEqual(
            agent_status.running_slugs(sessions, "testns", ["alpha", "beta", "gamma", "delta"]),
            {"alpha", "beta"},
        )

    def test_throttle_level_honors_expiry(self):
        path = self.root / "throttle.json"
        self.assertEqual(agent_status.throttle_level(path), "off")
        path.write_text(json.dumps({"level": "halt", "expires_at": 1000}))
        self.assertEqual(agent_status.throttle_level(path, now=999), "halt")
        self.assertEqual(agent_status.throttle_level(path, now=1001), "off")
        path.write_text(json.dumps({"level": "halt", "expires_at": 0}))
        self.assertEqual(agent_status.throttle_level(path, now=10**10), "halt")
        path.write_text(json.dumps({"level": "halt", "expires_at": "soon"}))
        self.assertEqual(agent_status.throttle_level(path, now=10**10), "halt")
        path.write_text("not json")
        self.assertEqual(agent_status.throttle_level(path), "off")

    def test_status_command_empty_by_default(self):
        self.assertEqual(config.status_command(self.cfg), "")

    def test_status_command_fills_in_seconds_shell_quoted(self):
        self._write_config('[status]\ncommand = "report --ttl {seconds}"')
        cfg = config.Config.load()
        self.assertEqual(config.status_command(cfg), "report --ttl 900")
        self.assertEqual(config.status_command(cfg, seconds=60), "report --ttl 60")
        self.assertEqual(cfg.status["command"], "report --ttl {seconds}")


if __name__ == "__main__":
    unittest.main()
