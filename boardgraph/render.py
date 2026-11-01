"""Emissor Mermaid.

O recorte já vem no `Board`; aqui só se escolhe o agrupamento visual
(`milestone` ou `team`). `Status` continua sendo apenas cor de nó.
"""

from __future__ import annotations

from .team import OUTSIDE, UNASSIGNED, resolve_teams
from .viz import (
    TITLE_LIMIT,
    group_id,
    group_label,
    group_order,
    node_group,
    node_ids,
)

STATUS_CLASS = {
    "Todo": "todo",
    "In progress": "doing",
    "In Progress": "doing",
    "Done": "done",
}

CLASS_DEFS = {
    "todo": "fill:#1f2937,stroke:#4b5563,color:#e5e7eb,stroke-dasharray:4 3",
    "doing": "fill:#1e3a8a,stroke:#3b82f6,color:#dbeafe",
    "done": "fill:#14532d,stroke:#22c55e,color:#dcfce7",
    "ghost": "fill:transparent,stroke:#6b7280,color:#9ca3af,stroke-dasharray:2 4",
}


def render_mermaid(board: dict, graph: dict, group_by: str = "milestone") -> str:
    teams_map = resolve_teams(board) if group_by == "team" else {}
    node_id = node_ids([n["key"] for n in graph["nodes"]] + [g["key"] for g in graph["ghosts"]])

    order = group_order(board, group_by)
    groups: dict[tuple, list[dict]] = {}
    for node in graph["nodes"]:
        groups.setdefault(node_group(node, group_by, teams_map), []).append(node)

    lines = [_header(board, group_by), "flowchart LR"]

    for group, nodes in sorted(groups.items(), key=lambda kv: (order.get(kv[0], 10**6), str(kv[0]))):
        lines.append(f'  subgraph {group_id(group)}["{_esc(group_label(group, nodes))}"]')
        for node in sorted(nodes, key=lambda n: n["key"]):
            lines.append(f'    {node_id[node["key"]]}["{_label(node)}"]:::{_class(node)}')
        lines.append("  end")

    if graph["ghosts"]:
        lines.append(f'  subgraph externos["fora do recorte · {len(graph["ghosts"])}"]')
        for ghost in sorted(graph["ghosts"], key=lambda g: g["key"]):
            lines.append(f'    {node_id[ghost["key"]]}["{_ghost_label(ghost)}"]:::ghost')
        lines.append("  end")

    for edge in graph["edges"]:
        src, dst = node_id.get(edge["from"]), node_id.get(edge["to"])
        if not src or not dst:
            continue
        arrow = "-.->" if edge["kind"] == "hierarchy" else "-->"
        lines.append(f"  {src} {arrow} {dst}")

    for node in graph["nodes"]:
        if node.get("url"):
            lines.append(f'  click {node_id[node["key"]]} "{node["url"]}"')

    for name, style in CLASS_DEFS.items():
        lines.append(f"  classDef {name} {style}")

    return "\n".join(lines) + "\n"


def _header(board: dict, group_by: str) -> str:
    parts = [f"detail: {board.get('detail') or 'parents'}"]
    if board.get("teams") is not None:
        parts.append("teams: " + (", ".join(board["teams"]) or "—"))
    parts.append(f"group-by: {group_by}")
    return "%% " + " · ".join(parts)


def _class(node: dict) -> str:
    return STATUS_CLASS.get(node.get("status") or "", "todo")


def _label(node: dict) -> str:
    title = node.get("title") or ""
    short = title if len(title) <= TITLE_LIMIT else title[: TITLE_LIMIT - 1] + "…"
    number = node.get("number")
    head = f"#{number}" if number is not None else "?"
    label = f"{head} · {short}"
    children = node.get("children") or []
    if children:
        label += f"<br/>+{len(children)} sub-issue(s)"
    return _esc(label)


def _ghost_label(ghost: dict) -> str:
    title = ghost.get("title") or ""
    team = ghost.get("team")
    if team == OUTSIDE:
        return _esc(title)
    short = title if len(title) <= TITLE_LIMIT else title[: TITLE_LIMIT - 1] + "…"
    number = ghost.get("number")
    head = f"#{number}" if number is not None else "?"
    return _esc(f"{head} · {short}<br/>time: {team or UNASSIGNED}")


def _esc(text: str) -> str:
    text = text.replace('"', "'").replace("|", "/").replace("<br/>", "\x00")
    text = text.replace("<", "‹").replace(">", "›")
    return text.replace("\x00", "<br/>")
