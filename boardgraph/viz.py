"""Agrupamento compartilhado dos emissores.

`render.py` (Mermaid) e `dot.py` (Graphviz) desenham o mesmo `Board`; a
semântica de agrupamento — o que é um grupo, a ordem, o rótulo e o id estável
— vive aqui para os dois não divergirem. A sintaxe de cada linguagem fica no
emissor.
"""

from __future__ import annotations

import re

from .team import UNASSIGNED

TITLE_LIMIT = 34


def slug(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", str(text)).strip("_")


def node_ids(keys: list[str]) -> dict[str, str]:
    """Ids curtos e estáveis: repo#12 → n_repo_12, com sufixo em caso de colisão."""
    out: dict[str, str] = {}
    used: set[str] = set()
    for key in keys:
        repo, _, number = key.rpartition("#")
        base = f"n_{slug(repo.split('/')[-1]) or 'x'}_{number}"
        candidate, n = base, 2
        while candidate in used:
            candidate, n = f"{base}_{n}", n + 1
        used.add(candidate)
        out[key] = candidate
    return out


def node_group(node: dict, group_by: str, teams_map: dict[str, str | None]) -> tuple:
    if group_by == "team":
        return ("team", teams_map.get(node["key"]) or UNASSIGNED)
    ms = node.get("milestone")
    if not ms or not ms.get("number"):
        return ("sem_milestone",)
    return ("milestone", ms["repo"], ms["number"])


def group_order(board: dict, group_by: str) -> dict[tuple, int]:
    if group_by == "team":
        return {("team", team): i for i, team in enumerate(board.get("teams") or [])}
    return {
        ("milestone", m["repo"], m["number"]): i
        for i, m in enumerate(board.get("milestones") or [])
    }


def group_id(group: tuple) -> str:
    if group[0] == "sem_milestone":
        return "m_sem_milestone"
    if group[0] == "team":
        return "t_" + (slug(group[1]) or "sem_time")
    return f"m_{slug(group[1].split('/')[-1])}_{group[2]}"


def group_label(group: tuple, nodes: list[dict]) -> str:
    """Rótulo em texto puro; cada emissor escapa para a própria sintaxe."""
    if group[0] == "sem_milestone":
        return "sem milestone"
    if group[0] == "team":
        return f"{group[1]} · {len(nodes)}"
    ms = nodes[0]["milestone"]
    return f"{ms.get('title') or f'milestone {group[2]}'} · {len(nodes)}"
