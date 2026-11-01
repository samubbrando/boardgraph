import unittest

from boardgraph.graph import build_graph
from boardgraph.model import finalize
from boardgraph.team import OUTSIDE, filter_team, resolve_teams


def _node(key, team=None, blocked=(), parent=None, status="Todo"):
    repo, _, number = key.rpartition("#")
    return {
        "key": key,
        "repo": repo,
        "number": int(number),
        "type": "issue",
        "title": f"t{number}",
        "url": f"https://x/{number}",
        "status": status,
        "team": team,
        "start": "2026-10-01",
        "end": "2026-10-02",
        "milestone": None,
        "blocked_by": list(blocked),
        "parent": parent,
        "children": [],
        "absorbed_by": None,
    }


def _board(nodes, items=None, detail="children"):
    return {
        "project": {"title": "B"},
        "detail": detail,
        "teams": None,
        "items": items if items is not None else [dict(n) for n in nodes],
        "nodes": nodes,
        "absorbed": {},
    }


def _filtered(board, teams):
    return finalize(filter_team(board, teams))


class TeamResolutionTests(unittest.TestCase):
    def test_child_inherits_team_from_parent(self):
        board = _board(
            [_node("o/r#1", "Back"), _node("o/r#2", None, parent="o/r#1")]
        )
        self.assertEqual(resolve_teams(board)["o/r#2"], "Back")

    def test_grandchild_inherits_through_chain(self):
        board = _board(
            [_node("o/r#1", "Back"), _node("o/r#2", None, parent="o/r#1"), _node("o/r#3", None, parent="o/r#2")]
        )
        self.assertEqual(resolve_teams(board)["o/r#3"], "Back")

    def test_unassigned_stays_none(self):
        board = _board([_node("o/r#1", None)])
        self.assertIsNone(resolve_teams(board)["o/r#1"])


class FilterTests(unittest.TestCase):
    def test_selects_only_requested_team(self):
        board = _board([_node("o/r#1", "Back"), _node("o/r#2", "Front")])
        filtered = _filtered(board, ["Front"])
        self.assertEqual([n["key"] for n in filtered["nodes"]], ["o/r#2"])

    def test_external_blocker_keeps_its_team(self):
        board = _board([_node("o/r#1", "Back"), _node("o/r#2", "Front", blocked=["o/r#1"])])
        graph = build_graph(_filtered(board, ["Front"]))
        self.assertEqual(len(graph["ghosts"]), 1)
        self.assertEqual(graph["ghosts"][0]["team"], "Back")
        self.assertEqual(graph["ghosts"][0]["title"], "t1")

    def test_blocker_outside_board_is_marked(self):
        board = _board([_node("o/r#2", "Front", blocked=["o/r#99"])])
        graph = build_graph(_filtered(board, ["Front"]))
        self.assertEqual(graph["ghosts"][0]["team"], OUTSIDE)

    def test_blocker_inside_selection_is_not_external(self):
        board = _board([_node("o/r#1", "Back"), _node("o/r#2", "Back", blocked=["o/r#1"])])
        graph = build_graph(_filtered(board, ["Back"]))
        self.assertEqual(graph["ghosts"], [])

    def test_multiple_teams_are_kept_apart(self):
        board = _board([_node("o/r#1", "Back"), _node("o/r#2", "Front")])
        filtered = _filtered(board, ["Back", "Front"])
        self.assertEqual({n["key"] for n in filtered["nodes"]}, {"o/r#1", "o/r#2"})

    def test_unassigned_is_never_dropped(self):
        board = _board([_node("o/r#1", "Back"), _node("o/r#2", None)])
        filtered = _filtered(board, ["Back"])
        self.assertIn("o/r#2", [n["key"] for n in filtered["nodes"]])
        self.assertTrue(any("sem time" in w for w in filtered["warnings"]))

    def test_missing_team_warns(self):
        board = _board([_node("o/r#1", "Back")])
        filtered = _filtered(board, ["Mobile"])
        self.assertTrue(any("Mobile" in w for w in filtered["warnings"]))

    def test_team_without_dependencies_warns(self):
        board = _board([_node("o/r#1", "Real"), _node("o/r#2", "Real")])
        filtered = _filtered(board, ["Real"])
        self.assertTrue(any("nenhuma dependência" in w for w in filtered["warnings"]))

    def test_team_with_dependencies_does_not_warn(self):
        board = _board([_node("o/r#1", "Front"), _node("o/r#2", "Front", blocked=["o/r#99"])])
        filtered = _filtered(board, ["Front"])
        self.assertFalse(any("nenhuma dependência" in w for w in filtered["warnings"]))

    def test_edges_only_touch_kept_nodes(self):
        board = _board(
            [
                _node("o/r#1", "Back"),
                _node("o/r#2", "Front", blocked=["o/r#1"]),
                _node("o/r#3", "Infra"),
            ]
        )
        graph = build_graph(_filtered(board, ["Front"]))
        self.assertEqual(graph["edges"], [{"from": "o/r#1", "to": "o/r#2", "kind": "dependency", "external": True}])


if __name__ == "__main__":
    unittest.main()
