"""Emissor Mermaid.

O recorte já vem no `Board`; aqui só se escolhe o agrupamento visual
(`milestone` ou `team`). `Status` continua sendo apenas cor de nó.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .team import OUTSIDE, UNASSIGNED, resolve_teams

if TYPE_CHECKING:
    from .people import PeopleIndex

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

TITLE_LIMIT = 34


def render_mermaid(
    board: dict,
    graph: dict,
    group_by: str = "milestone",
    people: "PeopleIndex | None" = None,
    show_assignees: bool = False,
    assignee_format: str = "both",
) -> str:
    teams_map = resolve_teams(board) if group_by == "team" else {}
    node_id = _ids([n["key"] for n in graph["nodes"]] + [g["key"] for g in graph["ghosts"]])

    order = _group_order(board, group_by)
    groups: dict[tuple, list[dict]] = {}
    for node in graph["nodes"]:
        groups.setdefault(_node_group(node, group_by, teams_map), []).append(node)

    lines = [_header(board, group_by), "flowchart LR"]

    for group, nodes in sorted(groups.items(), key=lambda kv: (order.get(kv[0], 10**6), str(kv[0]))):
        lines.append(f'  subgraph {_sid(group)}["{_group_label(group, nodes)}"]')
        for node in sorted(nodes, key=lambda n: n["key"]):
            label = _label(node, people, show_assignees, assignee_format)
            lines.append(
                f'    {node_id[node["key"]]}["{label}"]:::{_class(node)}'
            )
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


def _sid(group: tuple) -> str:
    if group[0] == "sem_milestone":
        return "m_sem_milestone"
    if group[0] == "team":
        return "t_" + (_slug(group[1]) or "sem_time")
    return f"m_{_slug(group[1].split('/')[-1])}_{group[2]}"


def _group_label(group: tuple, nodes: list[dict]) -> str:
    if group[0] == "sem_milestone":
        return "sem milestone"
    if group[0] == "team":
        return _esc(f"{group[1]} · {len(nodes)}")
    title = nodes[0]["milestone"].get("title") or f"milestone {group[2]}"
    return _esc(f"{title} · {len(nodes)}")


def _ids(keys: list[str]) -> dict[str, str]:
    """Ids curtos e estáveis: repo#12 → n_repo_12, com sufixo em caso de colisão."""
    out: dict[str, str] = {}
    used: set[str] = set()
    for key in keys:
        repo, _, number = key.rpartition("#")
        base = f"n_{_slug(repo.split('/')[-1])}_{number}"
        candidate, n = base, 2
        while candidate in used:
            candidate, n = f"{base}_{n}", n + 1
        used.add(candidate)
        out[key] = candidate
    return out


def _slug(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_")


def _class(node: dict) -> str:
    if node.get("external"):
        return "ghost"
    return STATUS_CLASS.get(node.get("status") or "", "todo")


def _label(
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
            label += f"<br/>Resp.: {resp}"
    children = node.get("children") or []
    if children:
        label += f"<br/>+{len(children)} sub-issue(s)"
    return _esc(label)


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
        return _esc(title)
    short = title if len(title) <= TITLE_LIMIT else title[: TITLE_LIMIT - 1] + "…"
    number = ghost.get("number")
    head = f"#{number}" if number is not None else "?"
    return _esc(f"{head} · {short}<br/>time: {team or UNASSIGNED}")


def _esc(text: str) -> str:
    text = text.replace('"', "'").replace("|", "/").replace("<br/>", "\x00")
    text = text.replace("<", "‹").replace(">", "›")
    return text.replace("\x00", "<br/>")
