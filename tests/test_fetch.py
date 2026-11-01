import unittest

from boardgraph.cli import _normalize_argv
from boardgraph.fetch import summarize
from boardgraph.queries import board_query


class QueryTests(unittest.TestCase):
    def test_includes_issue_field_dates(self):
        q = board_query()
        # sem este fragmento as datas do board voltam nulas
        self.assertIn("ProjectV2ItemIssueFieldValue", q)
        self.assertIn("IssueFieldDateValue", q)

    def test_deps_toggle(self):
        self.assertIn("blockedBy", board_query(include_deps=True))
        self.assertNotIn("blockedBy", board_query(include_deps=False))

    def test_body_toggle(self):
        self.assertIn("body", board_query(include_body=True))
        self.assertNotIn("body", board_query(include_body=False))


class CliTests(unittest.TestCase):
    def test_negative_filter_is_joined(self):
        argv = ["fetch", "--filter", "-status:Done", "--owner", "x"]
        self.assertIn("--filter=-status:Done", _normalize_argv(argv))

    def test_normal_filter_untouched(self):
        argv = ["fetch", "--filter", "status:Done"]
        self.assertEqual(_normalize_argv(argv), argv)


class SummaryTests(unittest.TestCase):
    def test_summary_marks_degraded(self):
        meta = {"fetchedCount": 3, "pages": 1, "counts": {"Issue": 3}, "degraded": True}
        self.assertIn("DEGRADED", summarize(meta))


if __name__ == "__main__":
    unittest.main()
