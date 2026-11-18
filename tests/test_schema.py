import json
import sys
import tomllib
import unittest
from pathlib import Path

try:
    from jsonschema import Draft202012Validator

    HAVE_JSONSCHEMA = True
except ImportError:
    HAVE_JSONSCHEMA = False

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lib"))
import config  # noqa: E402

DAEMONS = ROOT / "catalog"


@unittest.skipUnless(HAVE_JSONSCHEMA, "jsonschema (dev dependency) not installed")
class SchemaValidationTest(unittest.TestCase):
    def setUp(self):
        self.schema = config.daemon_schema()
        self.validator = Draft202012Validator(self.schema)

    def test_schema_is_valid(self):
        Draft202012Validator.check_schema(self.schema)

    def test_every_repo_daemon_validates(self):
        tomls = sorted(DAEMONS.glob("*/daemon.toml"))
        self.assertTrue(tomls, "no daemons found")
        for path in tomls:
            with self.subTest(daemon=path.parent.name):
                doc = tomllib.loads(path.read_text())
                errors = [e.message for e in self.validator.iter_errors(doc)]
                self.assertEqual(errors, [])

    def test_rejects_command_without_leading_slash(self):
        doc = {"daemon": {"command": "pr-manager", "schedule": {"interval": 60}}}
        self.assertTrue(list(self.validator.iter_errors(doc)))

    def test_rejects_unknown_daemon_field(self):
        doc = {"daemon": {"command": "/x", "schedule": {"interval": 60}, "comand": "typo"}}
        self.assertTrue(list(self.validator.iter_errors(doc)))


class SchemaDriftTest(unittest.TestCase):
    def test_committed_schema_matches_generator(self):
        committed = (DAEMONS / "daemon.schema.json").read_text()
        self.assertEqual(
            committed,
            json.dumps(config.daemon_schema(), indent=2) + "\n",
            "catalog/daemon.schema.json is stale — run `daimon sync`",
        )


if __name__ == "__main__":
    unittest.main()
