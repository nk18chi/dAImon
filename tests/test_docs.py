import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load():
    spec = importlib.util.spec_from_file_location(
        "daimon_gen_docs", ROOT / "daimon" / "gen_docs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen_docs = _load()


class DocsTest(unittest.TestCase):
    def test_daemon_readmes_are_up_to_date(self):
        for path, content in gen_docs._targets(gen_docs.INSTALL_ROOT):
            rel = path.relative_to(gen_docs.INSTALL_ROOT)
            with self.subTest(doc=str(rel)):
                self.assertTrue(path.exists(), f"{rel} missing — run `make docs`")
                self.assertEqual(path.read_text(), content, f"{rel} is stale — run `make docs`")


class IgnoredDaemonsTest(unittest.TestCase):
    """A personal daemon excluded from git must not reach the tracked index, or
    generating docs dirties a committed file that can never be made clean."""

    def _repo(self, tmp: Path, excluded: str | None) -> list[Path]:
        subprocess.run(["git", "init", "-q", str(tmp)], check=True)
        dirs = []
        for name in ("alpha", "beta"):
            d = tmp / "daemons" / name
            d.mkdir(parents=True)
            (d / "daemon.toml").write_text("[daemon]\n")
            dirs.append(d)
        if excluded:
            info = tmp / ".git" / "info"
            info.mkdir(parents=True, exist_ok=True)
            (info / "exclude").write_text(f"daemons/{excluded}/\n")
        return dirs

    def test_excluded_daemon_is_reported_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            dirs = self._repo(tmp, excluded="beta")
            ignored = gen_docs._ignored(tmp, dirs)
            self.assertEqual({p.name for p in ignored}, {"beta"})

    def test_nothing_ignored_when_no_exclude(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            dirs = self._repo(tmp, excluded=None)
            self.assertEqual(gen_docs._ignored(tmp, dirs), set())

    def test_outside_a_git_repo_ignores_nothing(self):
        """Fails open: a non-repo checkout must document everything, not nothing."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            d = tmp / "daemons" / "alpha"
            d.mkdir(parents=True)
            self.assertEqual(gen_docs._ignored(tmp, [d]), set())

    def test_no_daemons_is_not_a_git_call(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(gen_docs._ignored(Path(td), []), set())


if __name__ == "__main__":
    unittest.main()
