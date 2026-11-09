import tempfile
import unittest
from datetime import date
from pathlib import Path

from boardgraph.people import load
from boardgraph.timeline import (
    TimelineError,
    build_rows,
    format_names,
    parse_range,
    render_timeline,
    select_items,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "people-names.example.json"

try:
    import matplotlib  # noqa: F401
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


def _board():
    return {
        "project": {"title": "Plannings"},
        "items": [
            {
                "type": "issue",
                "number": 1,
                "repo": "o/r",
                "title": "F1 - Login",
                "status": "Done",
                "team": "Front",
                "start": "2026-10-01",
                "end": "2026-10-05",
                "created_at": "2026-09-30",
                "closed_at": "2026-10-05",
                "assignees": ["fulano"],
                "milestone": {"number": 4, "title": "Milestone 4"},
            },
            {
                "type": "issue",
                "number": 2,
                "repo": "o/r",
                "title": "F5 - Histórico",
                "status": "In progress",
                "team": "Front",
                "start": "2026-10-10",
                "end": "2026-10-15",
                "created_at": "2026-10-09",
                "closed_at": None,
                "assignees": ["fulano", "beltrano"],
                "milestone": {"number": 5, "title": "Milestone 5"},
            },
            {
                "type": "issue",
                "number": 3,
                "repo": "o/r",
                "title": "I3 - Observabilidade",
                "status": "Todo",
                "team": "Infra",
                "start": "2026-11-01",
                "end": "2026-11-05",
                "created_at": "2026-10-31",
                "closed_at": None,
                "assignees": [],
                "milestone": {"number": 6, "title": "Milestone 6"},
            },
            {
                "type": "pull_request",
                "number": 4,
                "repo": "o/r",
                "title": "PR sem data",
                "status": "Done",
                "team": "Back",
                "start": None,
                "end": None,
                "created_at": None,
                "closed_at": None,
                "assignees": [],
                "milestone": None,
            },
        ],
        "milestones": [
            {
                "repo": "o/r",
                "number": 4,
                "title": "Milestone 4",
                "start": "2026-10-01",
                "end": "2026-10-31",
                "due_on": "2026-10-10",
                "status": "ok",
            }
        ],
    }


class RangeTests(unittest.TestCase):
    def test_month_range(self):
        start, end = parse_range("2026-10", None, None)
        self.assertEqual((start, end), (date(2026, 10, 1), date(2026, 10, 31)))

    def test_from_to_range(self):
        start, end = parse_range(None, "2026-10-02", "2026-10-20")
        self.assertEqual((start, end), (date(2026, 10, 2), date(2026, 10, 20)))

    def test_month_and_dates_are_mutually_exclusive(self):
        with self.assertRaises(TimelineError):
            parse_range("2026-10", "2026-10-01", None)

    def test_one_sided_range_is_invalid(self):
        with self.assertRaises(TimelineError):
            parse_range(None, "2026-10-01", None)


class SelectionTests(unittest.TestCase):
    def test_month_filters_and_counts_undated(self):
        items, undated = select_items(
            _board(), date(2026, 10, 1), date(2026, 10, 31), None, "all"
        )
        self.assertEqual([i["number"] for i in items], [1, 2])
        self.assertEqual(undated, 1)

    def test_status_and_team_filters(self):
        done, _ = select_items(
            _board(), date(2026, 10, 1), date(2026, 10, 31), None, "done"
        )
        self.assertEqual([i["number"] for i in done], [1])

        front, _ = select_items(
            _board(), date(2026, 10, 1), date(2026, 10, 31), ["Front"], "all"
        )
        self.assertEqual([i["number"] for i in front], [1, 2])


class RowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.people = load(EXAMPLE)

    def _items(self):
        items, _ = select_items(
            _board(), date(2026, 10, 1), date(2026, 10, 31), None, "all"
        )
        return items

    def test_team_group_uses_full_names(self):
        rows = build_rows(
            self._items(), group_by="team", split_assignees=False,
            people=self.people, name_style="full", show_login=False,
        )
        self.assertEqual(rows[0].kind, "group")
        self.assertIn("Front", rows[0].label)
        labels = [r.label for r in rows if r.kind == "task"]
        self.assertTrue(any("Fulano de Tal" in label for label in labels))
        self.assertTrue(any("Beltrano de Souza" in label for label in labels))

    def test_split_assignees_creates_one_row_per_person(self):
        rows = build_rows(
            self._items(), group_by="team", split_assignees=True,
            people=self.people, name_style="short", show_login=False,
        )
        tasks = [r for r in rows if r.kind == "task"]
        self.assertEqual(len(tasks), 3)
        self.assertTrue(any("Fulano" in r.label for r in tasks))
        self.assertTrue(any("Beltrano" in r.label for r in tasks))

    def test_group_by_assignee_creates_person_groups(self):
        rows = build_rows(
            self._items(), group_by="assignee", split_assignees=False,
            people=self.people, name_style="full", show_login=False,
        )
        groups = [r.label for r in rows if r.kind == "group"]
        self.assertTrue(any("Fulano de Tal" in g for g in groups))
        self.assertTrue(any("Beltrano de Souza" in g for g in groups))

    def test_format_names_falls_back_and_limits(self):
        self.assertEqual(
            format_names(["fulano", "beltrano", "ciclano"], self.people, "full", False),
            "Fulano de Tal, Beltrano de Souza +1",
        )
        self.assertEqual(format_names([], self.people, "full", False), "Sem responsável")
        self.assertEqual(format_names(["nao-existe"], self.people, "full", False), "@nao-existe")


@unittest.skipUnless(HAS_MPL, "matplotlib não instalado")
class RenderTests(unittest.TestCase):
    def test_render_png(self):
        people = load(EXAMPLE)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "timeline.png"
            result = render_timeline(
                _board(),
                date_from=date(2026, 10, 1),
                date_to=date(2026, 10, 31),
                teams=None,
                status="all",
                group_by="team",
                split_assignees=False,
                people=people,
                name_style="full",
                show_login=False,
                output=output,
                fmt="png",
                title="Teste",
                out_dir=Path(tmp),
            )
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 1000)
            self.assertEqual(result["data"].items, 2)
            self.assertEqual(result["paths"], [str(output)])


if __name__ == "__main__":
    unittest.main()
