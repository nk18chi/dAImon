import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import toml_emit  # noqa: E402


class TomlEmitTest(unittest.TestCase):
    def test_scalars(self):
        self.assertEqual(toml_emit.emit_value(True), "true")
        self.assertEqual(toml_emit.emit_value(False), "false")
        self.assertEqual(toml_emit.emit_value(7), "7")
        self.assertEqual(toml_emit.emit_value("hi"), '"hi"')

    def test_inline_table_and_array(self):
        self.assertEqual(toml_emit.emit_value({"interval": 60}), "{ interval = 60 }")
        self.assertEqual(toml_emit.emit_value([1, 2]), "[1, 2]")
        self.assertEqual(toml_emit.emit_value(["a", "b"]), '["a", "b"]')

    def test_dump_sections_roundtrips(self):
        sections = {
            "daemon": {"backend": "claude", "schedule": {"minutes": [8, 38]}, "danger": True},
            "inputs": {"repo": "me/x", "labels": ["a", "b"]},
        }
        text = toml_emit.dump_sections(sections)
        parsed = tomllib.loads(text)
        self.assertEqual(parsed["daemon"]["backend"], "claude")
        self.assertEqual(parsed["daemon"]["schedule"], {"minutes": [8, 38]})
        self.assertEqual(parsed["daemon"]["danger"], True)
        self.assertEqual(parsed["inputs"]["labels"], ["a", "b"])

    def test_strings_with_quotes_backslashes_and_newlines_roundtrip(self):
        tricky = {
            "marker": '"kind":"findings"',
            "regex": "\\*\\*0 findings",
            "json": '{"a": 1,\n  "b": "two"}\n',
            "unicode": "café 🤖",
        }
        parsed = tomllib.loads(toml_emit.dump_sections({"inputs": tricky}))
        self.assertEqual(parsed["inputs"], tricky)

    def test_empty_section_skipped(self):
        text = toml_emit.dump_sections({"daemon": {"x": 1}, "inputs": {}})
        self.assertNotIn("[inputs]", text)


class SetKeyTextTest(unittest.TestCase):
    def test_replaces_in_place_preserving_comments_and_other_tables(self):
        text = '[core]\nns = "d"\n\n[daemons]\n# keep me\ndisabled = []\n\n[budget]\ncap = 1\n'
        out = toml_emit.set_key_text(text, "daemons", "disabled", ["a", "b"])
        self.assertIn("# keep me", out)
        self.assertEqual(out.count("disabled ="), 1)
        data = tomllib.loads(out)
        self.assertEqual(
            data, {"core": {"ns": "d"}, "daemons": {"disabled": ["a", "b"]}, "budget": {"cap": 1}}
        )

    def test_replaces_a_multi_line_array(self):
        text = '[daemons]\ninstalled = [\n  "a", # a ] in a comment\n  "b",\n]\nafter = 1\n'
        out = toml_emit.set_key_text(text, "daemons", "installed", ["c"])
        self.assertEqual(tomllib.loads(out)["daemons"], {"installed": ["c"], "after": 1})

    def test_adds_the_key_at_the_end_of_its_table(self):
        text = "[daemons]\ndisabled = []\n\n[packs]\npaths = []\n"
        out = toml_emit.set_key_text(text, "daemons", "installed", ["a"])
        self.assertIn('disabled = []\ninstalled = ["a"]\n\n[packs]', out)

    def test_adds_the_table_when_absent(self):
        out = toml_emit.set_key_text('[core]\nns = "d"', "daemons", "installed", [])
        self.assertEqual(tomllib.loads(out), {"core": {"ns": "d"}, "daemons": {"installed": []}})
        self.assertTrue(out.endswith("\n"))

    def test_a_key_of_the_same_name_in_another_table_is_untouched(self):
        text = "[other]\ninstalled = 1\n[daemons]\n"
        out = toml_emit.set_key_text(text, "daemons", "installed", ["x"])
        self.assertEqual(
            tomllib.loads(out), {"other": {"installed": 1}, "daemons": {"installed": ["x"]}}
        )

    def test_a_long_list_is_written_one_item_per_line(self):
        slugs = [f"daemon-number-{n}" for n in range(8)]
        out = toml_emit.set_key_text("[daemons]\n", "daemons", "installed", slugs)
        self.assertIn('installed = [\n  "daemon-number-0",\n', out)
        self.assertEqual(tomllib.loads(out)["daemons"]["installed"], slugs)


if __name__ == "__main__":
    unittest.main()
