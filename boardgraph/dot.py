"""Emissor Graphviz — base de SVG/PDF.

O recorte já vem no `Board`; `group_by` escolhe cluster por milestone ou por
time. `Status` continua sendo apenas cor de nó.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .team import OUTSIDE, UNASSIGNED, resolve_teams

if TYPE_CHECKING:
    from .people import PeopleIndex

TITLE_LIMIT = 34

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
    people: "PeopleIndex | None" = None,
    show_assignees: bool = False,
    assignee_format: str = "both",
) -> str:
    t = THEMES[theme]
    teams_map = resolve_teams(board) if group_by == "team" else {}
    ids = {n["key"]: _nid(n["key"]) for n in graph["nodes"]}
    for ghost in graph["ghosts"]:
        ids[ghost["key"]] = _nid(ghost["key"])

    out = [_header(board, group_by), "digraph board {", _graph_attrs(t)]

    order = _group_order(board, group_by)
    groups: dict[tuple, list[dict]] = {}
    for node in graph["nodes"]:
        groups.setdefault(_node_group(node, group_by, teams_map), []).append(node)

    for group, nodes in sorted(groups.items(), key=lambda kv: (order.get(kv[0], 10**6), str(kv[0]))):
        out.append(f"  subgraph cluster_{_sid(group)} {{")
        out.append(f'    label="{_esc(_group_label(group, nodes))}";')
        out.append(f'    labeljust="l"; style="rounded,dashed"; color="{t["cluster_border"]}"; fontcolor="{t["cluster_font"]}"; fontsize=11;')
        for node in sorted(nodes, key=lambda n: n["key"]):
            out.append(
                f"    {ids[node['key']]} "
                f"[{_attrs(node, t, people, show_assignees, assignee_format)}];"
            )
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


def _attrs(
    node: dict,
    t: dict,
    people: "PeopleIndex | None" = None,
    show_assignees: bool = False,
    assignee_format: str = "both",
) -> str:
    key = STATUS_KEY.get(node.get("status") or "", "todo")
    fill, border, font = t[key]
    style = '"rounded,filled' + (",dashed" if key == "todo" else "") + '"'
    label = _node_label(node, people, show_assignees, assignee_format)
    return (
        f'label="{_esc(label)}", fillcolor="{fill}", color="{border}", '
        f'fontcolor="{font}", style={style}{_url(node)}'
    )


def _node_label(
    node: dict,
    people: "PeopleIndex | None" = None,
    show_assignees: bool = False,
    assignee_format: str = "both",
) -> str:
    title = node.get("title") or ""
    short = title if len(title) <= TITLE_LIMIT else title[: TITLE_LIMIT - 1] + "…"
    number = node.get("number")
    head = f"#{number}" if number is not None else "?"
    label = f"{head} · {short}"
    if show_assignees:
        resp = _assignee_text(node, people, assignee_format)
        if resp:
            label += f"\nResp.: {resp}"
    children = node.get("children") or []
    if children:
        label += f"\n+{len(children)} sub-issue(s)"
    return label


def _assignee_text(
    node: dict,
    people: "PeopleIndex | None",
    assignee_format: str,
    limit: int = 2,
) -> str:
    assignees = tuple(dict.fromkeys(node.get("assignees") or ()))
    if not assignees:
        return ""
    if people is not None:
        return people.format_many(assignees, mode=assignee_format, limit=limit)
    shown = ", ".join(f"@{login}" for login in assignees[:limit])
    if len(assignees) > limit:
        shown += f" +{len(assignees) - limit}"
    return shown


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


def _node_group(node: dict, group_by: str, teams_map: dict[str, str | None]) -> tuple:
    if group_by == "team":
        return ("team", teams_map.get(node["key"]) or UNASSIGNED)
    ms = node.get("milestone")
    if not ms or not ms.get("number"):
        return ("sem_milestone",)
    return ("milestone", ms["repo"], ms["number"])


def _group_order(board: dict, group_by: str) -> dict[tuple, int]:
    if group_by == "team":
        return {("team", team): i for i, team in enumerate(board.get("teams") or [])}
    return {
        ("milestone", m["repo"], m["number"]): i
        for i, m in enumerate(board.get("milestones") or [])
    }


def _group_label(group: tuple, nodes: list[dict]) -> str:
    if group[0] == "sem_milestone":
        return "sem milestone"
    if group[0] == "team":
        return f"{group[1]} · {len(nodes)}"
    ms = nodes[0]["milestone"]
    return f"{ms.get('title') or group[2]} · {len(nodes)}"


def _sid(value) -> str:
    if value[0] == "sem_milestone":
        return "sem_milestone"
    if value[0] == "team":
        return "t_" + (_slug(value[1]) or "sem_time")
    return f"m_{_slug(value[1].split('/')[-1])}_{value[2]}"


def _nid(key: str) -> str:
    if "#" not in key:
        return f"n_{_slug(key)}"
    repo, _, number = key.rpartition("#")
    return f"n_{_slug(repo.split('/')[-1])}_{number}"


def _slug(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", str(text)).strip("_") or "x"


def _esc(text: str) -> str:
    return str(text).replace('"', "'").replace("\n", "\\n")
