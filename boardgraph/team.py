"""Filtro por time e resolução de `Team`.

Regras:
- `Team` vem do nó; se vazio, herda do pai na cadeia de `items`.
- Tarefa sem time em nenhum ancestral entra em `(sem time)` e nunca é
  descartada por filtro.
- O filtro devolve outro `Board`; o time dos fantasmas é lido de `items`.
"""

from __future__ import annotations

UNASSIGNED = "(sem time)"
OUTSIDE = "fora do board"


def resolve_teams(board: dict) -> dict[str, str | None]:
    """Resolve o time de cada nó, com herança pelo pai."""
    nodes = {n["key"]: n for n in board.get("nodes") or []}
    items = {i["key"]: i for i in board.get("items") or []}
    cache: dict[str, str | None] = {}

    def team_of(key: str, seen: frozenset[str] = frozenset()) -> str | None:
        if key in cache:
            return cache[key]
        if key in seen:
            return None
        node = nodes.get(key)
        if node and node.get("team"):
            cache[key] = node["team"]
            return cache[key]
        item = items.get(key)
        if item:
            if item.get("team"):
                cache[key] = item["team"]
                return cache[key]
            parent = item.get("parent")
            if parent:
                cache[key] = team_of(parent, seen | {key})
                return cache[key]
        cache[key] = None
        return None

    for key in nodes:
        team_of(key)
    return cache


def team_from_items(items: list[dict], key: str) -> str | None:
    """Time de um item qualquer, inclusive fora do recorte, com herança."""
    by_key = {i["key"]: i for i in items}
    seen: set[str] = set()
    current = by_key.get(key)
    while current and current["key"] not in seen:
        if current.get("team"):
            return current["team"]
        seen.add(current["key"])
        parent = current.get("parent")
        current = by_key.get(parent) if parent else None
    return None


def filter_team(board: dict, teams: list[str]) -> dict:
    """Mantém os nós dos times pedidos e as tarefas sem time."""
    wanted: list[str] = []
    for team in teams:
        if team and team != UNASSIGNED and team not in wanted:
            wanted.append(team)

    if not wanted:
        return {**board, "teams": []}

    teams_map = resolve_teams(board)
    nodes = [
        n
        for n in board.get("nodes") or []
        if teams_map.get(n["key"]) in wanted or not teams_map.get(n["key"])
    ]

    return {**board, "nodes": nodes, "teams": wanted}
