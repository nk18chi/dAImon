import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load():
    spec = importlib.util.spec_from_file_location("daimon_init", ROOT / "daimon" / "init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


init = _load()


class ParseChoiceTest(unittest.TestCase):
    OFFERED = ["alpha", "beta", "gamma"]

    def test_blank_keeps_the_current_set(self):
        self.assertEqual(init._parse_choice("", self.OFFERED, ["beta"]), ["beta"])

    def test_numbers_and_names_mix(self):
        self.assertEqual(init._parse_choice("3, alpha 3", self.OFFERED, []), ["gamma", "alpha"])

    def test_all_and_none(self):
        self.assertEqual(init._parse_choice("all", self.OFFERED, []), self.OFFERED)
        self.assertEqual(init._parse_choice("none", self.OFFERED, ["alpha"]), [])

    def test_unknown_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "delta"):
            init._parse_choice("delta", self.OFFERED, [])
        with self.assertRaisesRegex(ValueError, "4"):
            init._parse_choice("4", self.OFFERED, [])


class SetWorkingDirTest(unittest.TestCase):
    def test_replaces_in_daemon_section(self):
        text = '[daemon]\nworking_dir = "~/code/your-repo"   # keep comment\n\n[inputs]\nbase = "main"\n'
        out = init.set_working_dir_text(text, "/tmp/repo")
        self.assertIn('working_dir = "/tmp/repo" # keep comment', out)
        self.assertIn('[inputs]\nbase = "main"', out)
        self.assertEqual(out.count("working_dir ="), 1)

    def test_adds_to_existing_daemon_section(self):
        text = '[daemon]\ncommand = "/review-prs"\n'
        out = init.set_working_dir_text(text, "/tmp/repo")
        self.assertIn('command = "/review-prs"', out)
        self.assertIn('working_dir = "/tmp/repo"', out)

    def test_adds_daemon_section_when_absent(self):
        text = '[inputs]\nbase = "main"\n'
        out = init.set_working_dir_text(text, "/tmp/repo")
        self.assertIn("[daemon]", out)
        self.assertIn('working_dir = "/tmp/repo"', out)

    def test_escapes_toml_string(self):
        out = init.set_working_dir_text("[daemon]\n", '/tmp/repo "quoted"')
        self.assertIn('working_dir = "/tmp/repo \\"quoted\\""', out)


class ConfigureWorkingDirsTest(unittest.TestCase):
    def test_prompts_once_and_sets_all_placeholders(self):
        old_root = init.INSTALL_ROOT
        old_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init.INSTALL_ROOT = root
            first = root / "one" / "daemon.local.toml"
            second = root / "two" / "daemon.local.toml"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_text('[daemon]\nworking_dir = "~/code/your-repo"\n')
            second.write_text('[daemon]\nworking_dir = "~/code"\n')
            os.chdir(root)
            try:
                with patch("builtins.input", return_value="/tmp/target") as prompt:
                    init._configure_working_dirs([first, second], "", True)
                first_text = first.read_text()
                second_text = second.read_text()
            finally:
                os.chdir(old_cwd)
                init.INSTALL_ROOT = old_root
        self.assertEqual(prompt.call_count, 1)
        expected = Path("/tmp/target").resolve()
        self.assertIn(f'working_dir = "{expected}"', first_text)
        self.assertIn(f'working_dir = "{expected}"', second_text)

    def test_blank_prompt_uses_current_directory_for_all(self):
        old_root = init.INSTALL_ROOT
        old_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "target"
            target.mkdir()
            init.INSTALL_ROOT = root / "daimon"
            local = init.INSTALL_ROOT / "one" / "daemon.local.toml"
            local.parent.mkdir(parents=True)
            local.write_text('[daemon]\nworking_dir = "~/code/your-repo"\n')
            os.chdir(target)
            try:
                with patch("builtins.input", return_value=""):
                    init._configure_working_dirs([local], "", True)
                local_text = local.read_text()
            finally:
                os.chdir(old_cwd)
                init.INSTALL_ROOT = old_root
        self.assertIn(f'working_dir = "{target.resolve()}"', local_text)

    def test_blank_prompt_sets_install_root_without_extra_opt_in(self):
        old_root = init.INSTALL_ROOT
        old_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init.INSTALL_ROOT = root
            local = root / "one" / "daemon.local.toml"
            local.parent.mkdir()
            local.write_text('[daemon]\nworking_dir = "~/code/your-repo"\n')
            os.chdir(root)
            try:
                with patch("builtins.input", return_value=""):
                    init._configure_working_dirs([local], "", True)
                local_text = local.read_text()
            finally:
                os.chdir(old_cwd)
                init.INSTALL_ROOT = old_root
        self.assertIn(f'working_dir = "{root.resolve()}"', local_text)
        self.assertNotIn("allow_install_root_working_dir", local_text)

    def test_explicit_install_root_value_does_not_need_working_dir(self):
        old_root = init.INSTALL_ROOT
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init.INSTALL_ROOT = root
            local = root / "one" / "daemon.local.toml"
            local.parent.mkdir()
            local.write_text(f'[daemon]\nworking_dir = "{root}"\n')
            try:
                self.assertFalse(init._needs_working_dir(local))
            finally:
                init.INSTALL_ROOT = old_root


if __name__ == "__main__":
    unittest.main()
