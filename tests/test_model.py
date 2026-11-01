import copy
import unittest

from boardgraph.model import build_board, filter_detail, finalize
from boardgraph.team import filter_team


def _item(number, start, end, ms=1, parent=None, blocks=(), kind="Issue", repo="o/r", team=None):
    content = {
        "__typename": kind,
        "number": number,
        "title": f"t{number}",
        "url": f"https://x/{number}",
        "state": "OPEN",
        "repository": {"nameWithOwner": repo},
        "milestone": {"number": ms, "title": f"M{ms}", "dueOn": "2026-10-10T00:00:00Z"} if ms else None,
        "blockedBy": {
            "totalCount": len(blocks),
            "nodes": [{"number": b, "repository": {"nameWithOwner": repo}} for b in blocks],
        },
        "parent": {"number": parent, "title": f"t{parent}"} if parent else None,
    }
    values = []
    for name, value in (
        ("Status", "Todo"),
        ("Start date", start),
        ("Target date", end),
        ("Team", team),
    ):
        if value:
            values.append(
                {
                    "__typename": "ProjectV2ItemIssueFieldValue",
                    "issueFieldValue": {"value": value, "field": {"name": name}},
                }
            )
    return {"id": f"i{number}", "fieldValues": {"nodes": values}, "content": content}


def _payload(items):
    return {"project": {"title": "B"}, "fields": [], "items": items}


def _board(items, detail="parents", teams=None):
    board = filter_detail(build_board(_payload(items)), detail)
    if teams:
        board = filter_team(board, teams)
    return finalize(board)


class EstimateTests(unittest.TestCase):
    def test_pert_fields_are_normalized(self):
        item = _item(1, "2026-10-05", "2026-10-07")
        item["fieldValues"]["nodes"] += [
            {"issueFieldValue": {"value": value, "field": {"name": name}}}
            for name, value in (
                ("Otimista (dias)", 2.1),
                ("Mais provável (dias)", 3.0),
                ("Pessimista (dias)", 4.8),
                ("Prazo", "2026-10-08"),
            )
        ]

        node = _board([item])["nodes"][0]

        self.assertEqual(node["optimistic"], 2.1)
        self.assertEqual(node["likely"], 3.0)
        self.assertEqual(node["pessimistic"], 4.8)
        self.assertEqual(node["deadline"], "2026-10-08")


class CollapseTests(unittest.TestCase):
    def test_child_is_absorbed_and_window_is_union(self):
        board = _board(
            [
                _item(1, "2026-10-01", "2026-10-05"),
                _item(2, "2026-10-10", "2026-10-20", parent=1),
                _item(3, "2026-10-21", "2026-10-31", parent=1),
            ]
        )
        nodes = board["nodes"]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["start"], "2026-10-01")
        self.assertEqual(nodes[0]["end"], "2026-10-31")
        self.assertEqual(len(nodes[0]["children"]), 2)
        self.assertEqual(board["absorbed"], {"o/r#1": ["o/r#2", "o/r#3"]})

    def test_children_detail_keeps_every_node(self):
        board = _board(
            [_item(1, "2026-10-01", "2026-10-05"), _item(2, "2026-10-06", "2026-10-09", parent=1)],
            detail="children",
        )
        self.assertEqual(len(board["nodes"]), 2)

    def test_blocker_of_child_is_repointed_to_parent(self):
        board = _board(
            [
                _item(1, "2026-10-01", "2026-10-05"),
                _item(2, "2026-10-10", "2026-10-20", parent=1, blocks=[9]),
                _item(9, "2026-10-21", "2026-10-25"),
            ]
        )
        parent = next(n for n in board["nodes"] if n["number"] == 1)
        self.assertIn("o/r#9", parent["blocked_by"])

    def test_sibling_blocker_becomes_self_and_is_dropped(self):
        board = _board(
            [
                _item(1, "2026-10-01", "2026-10-05"),
                _item(2, "2026-10-10", "2026-10-15", parent=1, blocks=[3]),
                _item(3, "2026-10-16", "2026-10-20", parent=1),
            ]
        )
        parent = next(n for n in board["nodes"] if n["number"] == 1)
        self.assertEqual(parent["blocked_by"], [])

    def test_parent_outside_board_is_not_collapsed(self):
        board = _board([_item(2, "2026-10-10", "2026-10-20", parent=99)])
        self.assertEqual(len(board["nodes"]), 1)
        self.assertIsNone(board["nodes"][0]["absorbed_by"])


class TypeTests(unittest.TestCase):
    def test_pull_requests_are_not_nodes_by_default(self):
        board = _board([_item(1, None, None, kind="PullRequest")])
        self.assertEqual(board["nodes"], [])
        self.assertTrue(board["warnings"])

    def test_detail_all_includes_pull_requests(self):
        board = _board([_item(1, "2026-10-01", "2026-10-02", kind="PullRequest")], detail="all")
        self.assertEqual(len(board["nodes"]), 1)
        self.assertEqual(board["nodes"][0]["type"], "pull_request")


class MilestoneTests(unittest.TestCase):
    def test_window_uses_min_start_and_max_end(self):
        board = _board([_item(1, "2026-10-05", "2026-10-08"), _item(2, "2026-10-01", "2026-10-20")])
        ms = board["milestones"][0]
        self.assertEqual((ms["start"], ms["end"]), ("2026-10-01", "2026-10-20"))

    def test_due_date_overrun_is_positive(self):
        board = _board([_item(1, "2026-10-01", "2026-10-20")])
        ms = board["milestones"][0]
        self.assertEqual(ms["delta_days"], 10)
        self.assertEqual(ms["status"], "estourado")

    def test_missing_due_date_is_flagged(self):
        board = _board([_item(1, "2026-10-01", "2026-10-02", ms=None)])
        self.assertEqual(board["milestones"], [])

    def test_window_is_recalculated_on_filtered_subset(self):
        items = [
            _item(1, "2026-10-01", "2026-10-30", team="Back"),
            _item(2, "2026-10-10", "2026-10-15", team="Front"),
        ]
        board = _board(items, detail="children", teams=["Front"])
        ms = board["milestones"][0]
        self.assertEqual(ms["nodes"], 1)
        self.assertEqual((ms["start"], ms["end"]), ("2026-10-10", "2026-10-15"))


class ImmutabilityTests(unittest.TestCase):
    def test_items_are_not_mutated_by_detail_filter(self):
        payload = _payload(
            [
                _item(1, "2026-10-01", "2026-10-05"),
                _item(2, "2026-10-10", "2026-10-20", parent=1),
            ]
        )
        board = build_board(payload)
        before = copy.deepcopy(board["items"])
        filtered = filter_detail(board, "parents")
        self.assertEqual(filtered["items"], before)
        self.assertEqual([i["absorbed_by"] for i in filtered["items"]], [None, None])

    def test_detail_and_team_compose(self):
        items = [
            _item(1, "2026-10-01", "2026-10-05", team="Back"),
            _item(2, "2026-10-10", "2026-10-20", parent=1),
        ]
        parents = _board(items, detail="parents", teams=["Back"])
        children = _board(items, detail="children", teams=["Back"])
        self.assertEqual([n["key"] for n in parents["nodes"]], ["o/r#1"])
        self.assertEqual([n["key"] for n in children["nodes"]], ["o/r#1", "o/r#2"])


if __name__ == "__main__":
    unittest.main()
