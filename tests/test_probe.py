import unittest

from boardgraph.probe import build_report


def _item(number, start="2026-10-01", target="2026-10-05", ms=1, repo="org/repo", **extra):
    values = []
    for name, value in (("Start date", start), ("Target date", target), ("Status", "Todo")):
        if value is not None:
            values.append(
                {
                    "__typename": "ProjectV2ItemIssueFieldValue",
                    "issueFieldValue": {"value": value, "field": {"name": name}},
                }
            )
    content = {
        "__typename": "Issue",
        "number": number,
        "title": f"t{number}",
        "url": f"https://x/{number}",
        "state": "OPEN",
        "repository": {"nameWithOwner": repo},
        "milestone": {"number": ms, "title": f"M{ms}", "dueOn": "2026-10-10"} if ms else None,
        "labels": {"nodes": []},
        "assignees": {"nodes": []},
    }
    content.update(extra)
    return {"id": f"i{number}", "createdAt": "2026-10-01T00:00:00Z", "fieldValues": {"nodes": values}, "content": content}


def _payload(items):
    return {"project": {"title": "Board"}, "fields": [], "items": items}


class CoverageTests(unittest.TestCase):
    def test_full_board_has_no_warning(self):
        report = build_report(_payload([_item(1), _item(2)]))
        self.assertEqual(report["warnings"], [])
        self.assertEqual(report["total"], 2)

    def test_missing_required_date_warns(self):
        report = build_report(_payload([_item(1, start=None)]))
        self.assertTrue(any("Start date" in w for w in report["warnings"]))

    def test_sparse_optional_field_does_not_warn(self):
        report = build_report(_payload([_item(1, blockedBy={"totalCount": 0, "nodes": []})]))
        self.assertFalse(any("Blocked by" in w for w in report["warnings"]))

    def test_uncollected_body_is_not_an_error(self):
        report = build_report(_payload([_item(1)]))
        body = next(r for r in report["fields"] if r["name"] == "Body")
        self.assertFalse(body["collected"])
        self.assertFalse(any("Body" in w for w in report["warnings"]))

    def test_milestones_counted_per_repository(self):
        report = build_report(_payload([_item(1, ms=1, repo="a/b"), _item(2, ms=1, repo="c/d")]))
        self.assertEqual(report["milestones"]["total"], 2)


if __name__ == "__main__":
    unittest.main()
