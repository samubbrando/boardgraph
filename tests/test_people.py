import json
import tempfile
import unittest
from pathlib import Path

from boardgraph.people import PeopleError, load


EXAMPLE = Path(__file__).resolve().parents[1] / "people-names.example.json"


def _write(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class ExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = load(EXAMPLE)

    def test_example_resolves_login_case_insensitively(self):
        person = self.index.resolve("FULANO")
        self.assertIsNotNone(person)
        self.assertEqual(person.name, "Fulano de Tal")

    def test_alias_resolves_to_same_person(self):
        person = self.index.resolve("fulano-antigo")
        self.assertIsNotNone(person)
        self.assertEqual(person.login, "fulano")

    def test_bot_and_inactive_flags(self):
        self.assertTrue(self.index.resolve("dependabot[bot]").bot)
        self.assertFalse(self.index.resolve("ciclano").active)

    def test_display_modes(self):
        self.assertEqual(self.index.format("fulano", "name"), "Fulano")
        self.assertEqual(self.index.format("fulano", "login"), "@fulano")
        self.assertEqual(self.index.format("fulano", "both"), "Fulano (@fulano)")

    def test_format_many_limits_and_deduplicates(self):
        text = self.index.format_many(["fulano", "beltrano", "ciclano"], limit=2)
        self.assertEqual(text, "Fulano, Beltrano +1")
        self.assertEqual(
            self.index.format_many(["fulano", "FULANO", "fulano-antigo"]),
            "Fulano",
        )

    def test_unknown_and_ghost(self):
        self.assertEqual(self.index.format("nao-existe"), "@nao-existe")
        self.assertEqual(self.index.format("ghost"), "Conta removida")
        self.assertEqual(self.index.format(None), "—")

    def test_manager_warning_for_unknown_manager(self):
        self.assertEqual(self.index.warnings, [])


class ValidationTests(unittest.TestCase):
    def _base(self, people: dict) -> dict:
        return {"schema_version": 1, "people": people}

    def test_duplicate_alias_is_rejected(self):
        data = self._base(
            {
                "a": {"name": "A", "aliases": ["antigo"]},
                "b": {"name": "B", "aliases": ["antigo"]},
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp) / "people.json", data)
            with self.assertRaises(PeopleError):
                load(path)

    def test_alias_conflicting_with_login_is_rejected(self):
        data = self._base(
            {
                "a": {"name": "A", "aliases": ["b"]},
                "b": {"name": "B"},
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp) / "people.json", data)
            with self.assertRaises(PeopleError):
                load(path)

    def test_duplicate_login_case_insensitive_is_rejected(self):
        data = self._base(
            {
                "Fulano": {"name": "Fulano"},
                "fulano": {"name": "Fulano 2"},
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp) / "people.json", data)
            with self.assertRaises(PeopleError):
                load(path)

    def test_missing_name_is_rejected(self):
        data = self._base({"a": {"short": "A"}})
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp) / "people.json", data)
            with self.assertRaises(PeopleError):
                load(path)

    def test_missing_file_mentions_example(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PeopleError) as ctx:
                load(Path(tmp) / "nao-existe.json")
        self.assertIn("people-names.example.json", str(ctx.exception))

    def test_unknown_manager_is_a_warning(self):
        data = self._base(
            {
                "a": {"name": "A", "manager": "fantasma"},
                "b": {"name": "B"},
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = _write(Path(tmp) / "people.json", data)
            index = load(path)
        self.assertTrue(index.warnings)
        self.assertIn("fantasma", index.warnings[0])


if __name__ == "__main__":
    unittest.main()
