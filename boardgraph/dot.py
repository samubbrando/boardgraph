"""Emissor Graphviz — base de SVG/PDF.

O recorte já vem no `Board`; `group_by` escolhe cluster por milestone ou por
time. `Status` continua sendo apenas cor de nó.
"""

from __future__ import annotations

from .team import OUTSIDE, UNASSIGNED, resolve_teams
from .viz import (
    CRIT_COLOR,
    TITLE_LIMIT,
    group_id,
    group_label,
    group_order,
    node_group,
    node_ids,
)

THEMES = {
    "light": {
        "bg": "#ffffff",
        "graph_font": "#334155",
        "cluster_border": "#cbd5e1",
        "cluster_font": "#475569",
        "edge": "#94a3b8",
        "todo": ("#f1f5f9", "#64748b", "#0f172a"),
        "doing": ("#dbeafe", "#3b82f6", "#1e3a8a"),
        "done": ("#dcfce7", "#22c55e", "#14532d"),
        "external": ("#fef3c7", "#f59e0b", "#78350f"),
    },
    "dark": {
        "bg": "#0f172a",
        "graph_font": "#94a3b8",
        "cluster_border": "#334155",
        "cluster_font": "#94a3b8",
        "edge": "#64748b",
        "todo": ("#1f2937", "#4b5563", "#e5e7eb"),
        "doing": ("#1e3a8a", "#3b82f6", "#dbeafe"),
        "done": ("#14532d", "#22c55e", "#dcfce7"),
        "external": ("#111827", "#f59e0b", "#fcd34d"),
    },
}

STATUS_KEY = {"Todo": "todo", "In progress": "doing", "In Progress": "doing", "Done": "done"}


def render_dot(
    board: dict,
    graph: dict,
    group_by: str = "milestone",
    theme: str = "light",
    critical: set[str] | None = None,
) -> str:
    critical = critical or set()
    t = THEMES[theme]
    teams_map = resolve_teams(board) if group_by == "team" else {}
    ids = node_ids([n["key"] for n in graph["nodes"]] + [g["key"] for g in graph["ghosts"]])

    out = [_header(board, group_by), "digraph board {", _graph_attrs(t)]

    order = group_order(board, group_by)
    groups: dict[tuple, list[dict]] = {}
    for node in graph["nodes"]:
        groups.setdefault(node_group(node, group_by, teams_map), []).append(node)

    for group, nodes in sorted(groups.items(), key=lambda kv: (order.get(kv[0], 10**6), str(kv[0]))):
        out.append(f"  subgraph cluster_{group_id(group)} {{")
        out.append(f'    label="{_esc(group_label(group, nodes))}";')
        out.append(f'    labeljust="l"; style="rounded,dashed"; color="{t["cluster_border"]}"; fontcolor="{t["cluster_font"]}"; fontsize=11;')
        for node in sorted(nodes, key=lambda n: n["key"]):
            out.append(f"    {ids[node['key']]} [{_attrs(node, t, node['key'] in critical)}];")
        out.append("  }")

    if graph["ghosts"]:
        out.append("  subgraph cluster_externos {")
        out.append(f'    label="fora do recorte · {len(graph["ghosts"])}"; labeljust="l"; style="rounded,dashed";')
        out.append(f'    color="{t["cluster_border"]}"; fontcolor="{t["cluster_font"]}"; fontsize=11;')
        for ghost in sorted(graph["ghosts"], key=lambda g: g["key"]):
            out.append(
                f'    {ids[ghost["key"]]} [label="{_esc(_ghost_label(ghost))}", '
                f'fillcolor="{t["external"][0]}", color="{t["external"][1]}", '
                f'fontcolor="{t["external"][2]}"];'
            )
        out.append("  }")

    for edge in graph["edges"]:
        src, dst = ids.get(edge["from"]), ids.get(edge["to"])
        if not src or not dst:
            continue
        if edge["from"] in critical and edge["to"] in critical:
            style = f'color="{CRIT_COLOR}", penwidth=2'
        else:
            style = 'style="dashed"' if edge["kind"] == "hierarchy" else f'color="{t["edge"]}"'
        out.append(f"  {src} -> {dst} [{style}, arrowsize=0.7];")

    out.append("}")
    return "\n".join(out) + "\n"


def _header(board: dict, group_by: str) -> str:
    parts = [f"detail: {board.get('detail') or 'parents'}"]
    if board.get("teams") is not None:
        parts.append("teams: " + (", ".join(board["teams"]) or "—"))
    parts.append(f"group-by: {group_by}")
    return "// " + " · ".join(parts)


def _graph_attrs(t: dict) -> str:
    return (
        f'  graph [rankdir=LR, bgcolor="{t["bg"]}", pad=0.4, nodesep=0.35, ranksep=0.9, '
        f'splines=true, fontname="Helvetica", fontcolor="{t["graph_font"]}"];\n'
        f'  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10, '
        f'penwidth=1.2, margin="0.14,0.08"];\n'
        f'  edge [fontname="Helvetica", fontsize=9, arrowsize=0.7, color="{t["edge"]}"];'
    )


def _attrs(node: dict, t: dict, critical: bool = False) -> str:
    key = STATUS_KEY.get(node.get("status") or "", "todo")
    fill, border, font = t[key]
    style = '"rounded,filled' + (",dashed" if key == "todo" else "") + '"'
    penwidth = ", penwidth=2.6" if critical else ""
    if critical:
        border = CRIT_COLOR
    return (
        f'label="{_esc(_node_label(node))}", fillcolor="{fill}", color="{border}", '
        f'fontcolor="{font}", style={style}{penwidth}{_url(node)}'
    )


def _node_label(node: dict) -> str:
    title = node.get("title") or ""
    short = title if len(title) <= TITLE_LIMIT else title[: TITLE_LIMIT - 1] + "…"
    number = node.get("number")
    head = f"#{number}" if number is not None else "?"
    label = f"{head} · {short}"
    children = node.get("children") or []
    if children:
        label += f"\n+{len(children)} sub-issue(s)"
    return label


def _ghost_label(ghost: dict) -> str:
    title = ghost.get("title") or ""
    team = ghost.get("team")
    if team == OUTSIDE:
        return title
    short = title if len(title) <= TITLE_LIMIT else title[: TITLE_LIMIT - 1] + "…"
    number = ghost.get("number")
    head = f"#{number}" if number is not None else "?"
    return f"{head} · {short}\ntime: {team or UNASSIGNED}"


def _url(node: dict) -> str:
    url = node.get("url")
    return f', URL="{url}", target="_blank"' if url else ""


def _esc(text: str) -> str:
    return str(text).replace('"', "'").replace("\n", "\\n")
