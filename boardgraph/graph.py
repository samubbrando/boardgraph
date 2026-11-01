"""Grafo e validação.

Monta arestas a partir de `blocked_by` (dependência) e `parent` (hierarquia),
resolve bloqueantes fora do recorte como fantasmas e detecta ciclos (Tarjan).
O recorte (`detail`) já vem resolvido no `Board`; `items` só é consultado para
rotular fantasmas com o time de origem.
"""

from __future__ import annotations

from .team import OUTSIDE, UNASSIGNED, team_from_items


def build_graph(board: dict) -> dict:
    detail = board.get("detail") or "parents"
    nodes = board.get("nodes") or []
    items = board.get("items") or []
    by_key = {n["key"]: n for n in nodes}

    edges: list[dict] = []
    ghosts: dict[str, dict] = {}

    for node in nodes:
        for blocker in node.get("blocked_by") or []:
            if blocker in by_key:
                edges.append({"from": blocker, "to": node["key"], "kind": "dependency"})
            else:
                ghosts.setdefault(blocker, _ghost(blocker, items))
                edges.append(
                    {"from": blocker, "to": node["key"], "kind": "dependency", "external": True}
                )

    if detail in ("children", "all"):
        for node in nodes:
            parent = node.get("parent")
            if parent and parent in by_key:
                edges.append({"from": parent, "to": node["key"], "kind": "hierarchy"})

    deps = [e for e in edges if e["kind"] == "dependency"]
    cycles = _cycles([n["key"] for n in nodes], deps)
    isolated = _isolated([n["key"] for n in nodes], deps)

    return {
        "detail": detail,
        "nodes": nodes,
        "ghosts": list(ghosts.values()),
        "edges": edges,
        "isolated": isolated,
        "cycles": cycles,
        "counts": {
            "nodes": len(nodes),
            "ghosts": len(ghosts),
            "edges": len(edges),
            "dependency": len(deps),
            "hierarchy": len(edges) - len(deps),
            "isolated": len(isolated),
            "cycles": len(cycles),
        },
        "warnings": _warnings(ghosts, isolated, cycles),
    }


def _ghost(key: str, items: list[dict]) -> dict:
    repo, _, number = key.rpartition("#")
    by_key = {i["key"]: i for i in items}
    item = by_key.get(key)
    if item:
        return {
            "key": key,
            "repo": repo,
            "number": int(number) if number.isdigit() else None,
            "title": item.get("title") or f"{repo}#{number}",
            "url": None,
            "team": team_from_items(items, key) or UNASSIGNED,
            "external": True,
        }
    return {
        "key": key,
        "repo": repo,
        "number": int(number) if number.isdigit() else None,
        "title": f"{repo.split('/')[-1]}#{number} (fora do board)",
        "url": None,
        "team": OUTSIDE,
        "external": True,
    }


def _adjacency(keys: list[str], deps: list[dict]) -> dict[str, list[str]]:
    adj: dict[str, list[str]] = {k: [] for k in keys}
    for edge in deps:
        adj.setdefault(edge["from"], []).append(edge["to"])
    return adj


def _cycles(keys: list[str], deps: list[dict]) -> list[list[str]]:
    adj = _adjacency(keys, deps)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    result: list[list[str]] = []
    counter = 0

    def strongconnect(node: str) -> None:
        nonlocal counter
        index[node] = low[node] = counter
        counter += 1
        stack.append(node)
        on_stack.add(node)

        for nxt in adj.get(node, []):
            if nxt not in index:
                strongconnect(nxt)
                low[node] = min(low[node], low[nxt])
            elif nxt in on_stack:
                low[node] = min(low[node], index[nxt])

        if low[node] == index[node]:
            component = []
            while True:
                item = stack.pop()
                on_stack.discard(item)
                component.append(item)
                if item == node:
                    break
            if len(component) > 1:
                result.append(sorted(component))

    for key in keys:
        if key not in index:
            strongconnect(key)
    return result


def _isolated(keys: list[str], deps: list[dict]) -> list[str]:
    touched = set()
    for edge in deps:
        touched.add(edge["from"])
        touched.add(edge["to"])
    return [k for k in keys if k not in touched]


def _warnings(ghosts: dict, isolated: list[str], cycles: list[list[str]]) -> list[str]:
    out: list[str] = []
    if ghosts:
        out.append(
            f"{len(ghosts)} blocker(s) fora do recorte: "
            + ", ".join(sorted(k.split('/')[-1] for k in ghosts))
        )
    if cycles:
        out.append(f"{len(cycles)} ciclo(s) de dependência: " + "; ".join(" → ".join(c) for c in cycles))
    if isolated:
        out.append(f"{len(isolated)} nó(s) sem nenhuma aresta de dependência")
    return out


def render_terminal(graph: dict) -> str:
    c = graph["counts"]
    return (
        f"detail={graph['detail']} · nós {c['nodes']} (+{c['ghosts']} fantasma) · "
        f"arestas {c['edges']} (dep {c['dependency']}, hier {c['hierarchy']}) · "
        f"isolados {c['isolated']} · ciclos {c['cycles']}"
    )
