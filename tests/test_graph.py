import unittest

from boardgraph.dot import render_dot
from boardgraph.graph import build_graph
from boardgraph.render import render_mermaid


def _node(key, status="Todo", blocked=(), parent=None, children=None, team=None, **extra):
    repo, _, number = key.rpartition("#")
    node = {
        "key": key,
        "repo": repo,
        "number": int(number),
        "type": "issue",
        "title": f"tarefa {number}",
        "url": f"https://x/{number}",
        "status": status,
        "team": team,
        "blocked_by": list(blocked),
        "parent": parent,
        "children": children or [],
        "milestone": None,
    }
    node.update(extra)
    return node


def _board(nodes, detail="parents", items=None):
    return {
        "project": {"title": "B"},
        "detail": detail,
        "teams": None,
        "items": items if items is not None else [dict(n) for n in nodes],
        "nodes": nodes,
        "milestones": [],
        "absorbed": {},
    }


class GraphTests(unittest.TestCase):
    def test_dependency_edge_points_blocker_to_blocked(self):
        graph = build_graph(_board([_node("o/r#1"), _node("o/r#2", blocked=["o/r#1"])]))
        self.assertEqual(graph["edges"], [{"from": "o/r#1", "to": "o/r#2", "kind": "dependency"}])

    def test_external_blocker_becomes_ghost(self):
        graph = build_graph(_board([_node("o/r#2", blocked=["o/r#99"])]))
        self.assertEqual([g["key"] for g in graph["ghosts"]], ["o/r#99"])
        self.assertTrue(graph["edges"][0]["external"])

    def test_hierarchy_edges_only_in_children_detail(self):
        nodes = [_node("o/r#1", children=["o/r#2"]), _node("o/r#2", parent="o/r#1")]
        self.assertFalse(any(e["kind"] == "hierarchy" for e in build_graph(_board(nodes, "parents"))["edges"]))
        self.assertTrue(any(e["kind"] == "hierarchy" for e in build_graph(_board(nodes, "children"))["edges"]))

    def test_cycle_is_reported(self):
        graph = build_graph(_board([_node("o/r#1", blocked=["o/r#2"]), _node("o/r#2", blocked=["o/r#1"])]))
        self.assertEqual(len(graph["cycles"]), 1)

    def test_isolated_node(self):
        graph = build_graph(_board([_node("o/r#1"), _node("o/r#2")]))
        self.assertEqual(sorted(graph["isolated"]), ["o/r#1", "o/r#2"])

    def test_blocked_node_is_not_isolated(self):
        graph = build_graph(_board([_node("o/r#1"), _node("o/r#2", blocked=["o/r#1"])]))
        self.assertEqual(graph["isolated"], [])


class RenderTests(unittest.TestCase):
    def test_quotes_in_title_do_not_break_label(self):
        node = _node("o/r#1")
        node["title"] = 'diz "oi" aqui'
        board = _board([node])
        text = render_mermaid(board, build_graph(board), "milestone")
        self.assertNotIn('"oi"', text)
        self.assertIn("'oi'", text)

    def test_node_ids_are_short_and_unique(self):
        nodes = [_node("org/backend#1"), _node("org/other#1")]
        board = _board(nodes)
        text = render_mermaid(board, build_graph(board), "milestone")
        self.assertIn("n_backend_1[", text)
        self.assertIn("n_other_1[", text)

    def test_click_only_for_nodes_with_url(self):
        nodes = [_node("o/r#1"), _node("o/r#2", blocked=["o/r#99"])]
        board = _board(nodes)
        text = render_mermaid(board, build_graph(board), "milestone")
        self.assertEqual(text.count("click"), 2)

    def test_ghost_carries_team_from_items(self):
        blocker = _node("o/r#1", team="Back")
        node = _node("o/r#2", team="Front", blocked=["o/r#1"])
        board = _board([node], items=[blocker, node])
        graph = build_graph(board)
        self.assertEqual(graph["ghosts"][0]["team"], "Back")
        text = render_mermaid(board, graph, "team")
        self.assertIn("time: Back", text)

    def test_group_by_team_creates_one_cluster_per_team(self):
        nodes = [
            _node("o/r#1", team="Back"),
            _node("o/r#2", team="Back"),
            _node("o/r#3", team="Front"),
        ]
        board = _board(nodes)
        graph = build_graph(board)
        mermaid = render_mermaid(board, graph, "team")
        dot = render_dot(board, graph, "team")
        self.assertIn("subgraph t_Back", mermaid)
        self.assertIn("subgraph t_Front", mermaid)
        self.assertIn("Back · 2", mermaid)
        self.assertIn("cluster_t_Back", dot)
        self.assertIn("cluster_t_Front", dot)


class MermaidLintTests(unittest.TestCase):
    def test_every_edge_endpoint_is_declared(self):
        nodes = [_node("o/r#1"), _node("o/r#2", blocked=["o/r#1", "o/r#99"])]
        board = _board(nodes)
        text = render_mermaid(board, build_graph(board), "milestone")
        declared = set()
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("n_") and "[" in line:
                declared.add(line.split("[")[0])
        for line in text.splitlines():
            line = line.strip()
            if "-->" in line or "-.->" in line:
                src, _, rest = line.partition(" " + ("-.->" if "-.->" in line else "-->") + " ")
                dst = rest.split()[0]
                self.assertIn(src, declared)
                self.assertIn(dst, declared)

    def test_subgraphs_are_balanced(self):
        nodes = [_node("o/r#1"), _node("o/r#2", blocked=["o/r#1"])]
        board = _board(nodes)
        text = render_mermaid(board, build_graph(board), "milestone")
        self.assertEqual(text.count("subgraph"), text.count("end"))
        self.assertTrue(text.startswith("%% detail:"))
        self.assertIn("flowchart LR", text)


if __name__ == "__main__":
    unittest.main()




if __name__ == "__main__":
    unittest.main()


class CriticalStyleTests(unittest.TestCase):
    def _setup(self):
        nodes = [_node("o/backend#1"), _node("o/frontend#2", blocked=["o/backend#1"])]
        board = _board(nodes)
        return board, build_graph(board)

    def test_mermaid_marks_critical_nodes_and_edges(self):
        board, graph = self._setup()
        text = render_mermaid(board, graph, critical={"o/backend#1", "o/frontend#2"})

        self.assertIn("classDef crit", text)
        self.assertIn("class n_backend_1 crit;", text)
        self.assertIn("n_backend_1 ==> n_frontend_2", text)

    def test_mermaid_without_critical_is_unchanged(self):
        board, graph = self._setup()
        text = render_mermaid(board, graph)

        self.assertNotIn("classDef crit", text)
        self.assertIn("n_backend_1 --> n_frontend_2", text)

    def test_dot_marks_critical_nodes_and_edges(self):
        board, graph = self._setup()
        text = render_dot(board, graph, critical={"o/backend#1", "o/frontend#2"})

        self.assertIn("penwidth=2.6", text)
        self.assertIn('color="#dc2626", penwidth=2', text)

    def test_dot_without_critical_is_unchanged(self):
        board, graph = self._setup()
        text = render_dot(board, graph)

        self.assertNotIn("dc2626", text)
