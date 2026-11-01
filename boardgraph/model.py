"""Normalização, filtros e janelas de milestone.

Pipeline:

    payload --build_board--> board --filter_detail--> board --filter_team--> board
            --finalize--> board

`items` é a fonte de verdade completa e imutável; `nodes` é o conjunto de
trabalho que os filtros cortam. `milestones`, `counts` e `warnings` só são
calculados em `finalize`, depois de todos os filtros.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable

from .fields import (
    FIELD_OTIMISTA,
    FIELD_PESSIMISTA,
    FIELD_PRAZO,
    FIELD_PROVAVEL,
    field_map,
    to_date,
    to_iso,
)
from .team import UNASSIGNED, resolve_teams


def build_board(payload: dict) -> dict:
    """Normaliza o payload sem aplicar recorte.

    `nodes` começa como cópia de todos os itens. É `filter_detail` que decide
    o que vira nó (colapso, sub-issues e PR).
    """
    items = [_normalize(item) for item in payload.get("items") or []]
    items = [i for i in items if i["key"]]

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": payload.get("project") or {},
        "detail": None,
        "teams": None,
        "items": items,
        "nodes": [dict(i) for i in items],
        "absorbed": {},
        "milestones": [],
        "counts": {},
        "warnings": [],
    }


def filter_detail(board: dict, detail: str = "parents") -> dict:
    """Seleciona os nós conforme `parents`, `children` ou `all`."""
    if detail not in ("parents", "children", "all"):
        raise ValueError(f"detail inválido: {detail}")

    out = dict(board)
    if detail == "parents":
        nodes, absorbed = _collapse(board["items"])
        node_keys = {n["key"] for n in nodes}
        absorbed = {k: v for k, v in absorbed.items() if k in node_keys}
        nodes = [n for n in nodes if n["type"] == "issue"]
    else:
        allowed = {"issue"} | ({"pull_request"} if detail == "all" else set())
        nodes = [
            _node_copy(i)
            for i in board["items"]
            if i["type"] in allowed
        ]
        absorbed = {}

    nodes.sort(key=_node_order)
    out.update({"detail": detail, "nodes": nodes, "absorbed": absorbed})
    return out


def finalize(board: dict) -> dict:
    """Calcula uma única vez milestones, contagens e avisos."""
    out = dict(board)
    nodes = out.get("nodes") or []
    absorbed = out.get("absorbed") or {}
    milestones = _milestone_windows(nodes)

    out["milestones"] = milestones
    out["counts"] = {
        "items": len(out.get("items") or []),
        "nodes": len(nodes),
        "absorbed": sum(len(v) for v in absorbed.values()),
        "milestones": len(milestones),
    }
    out["warnings"] = _warnings(out, nodes, milestones, absorbed)
    return out


# ---------------------------------------------------------------- normalização


def _node_copy(item: dict) -> dict:
    node = dict(item)
    node["children"] = list(item.get("children") or [])
    return node


def _normalize(item: dict) -> dict:
    content = item.get("content") or {}
    repo = (content.get("repository") or {}).get("nameWithOwner")
    number = content.get("number")
    key = f"{repo}#{number}" if repo and number is not None else None

    fields = field_map(item)
    ms = content.get("milestone") or {}

    start = to_date(fields.get("Start date"))
    end = to_date(fields.get("Target date"))
    end_source = "issue_field" if end else None
    if not end:
        closed = to_date(content.get("closedAt"))
        if closed:
            end, end_source = closed, "closed_at"

    parent = content.get("parent") or {}
    parent_key = f"{repo}#{parent['number']}" if parent.get("number") and repo else None

    return {
        "key": key,
        "repo": repo,
        "number": number,
        "type": _type(content.get("__typename")),
        "title": content.get("title") or "",
        "url": content.get("url"),
        "state": content.get("state"),
        "status": fields.get("Status"),
        "team": fields.get("Team"),
        "duration": fields.get("Duration"),
        "optimistic": _number(fields.get(FIELD_OTIMISTA)),
        "likely": _number(fields.get(FIELD_PROVAVEL)),
        "pessimistic": _number(fields.get(FIELD_PESSIMISTA)),
        "deadline": to_iso(to_date(fields.get(FIELD_PRAZO))),
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "start_source": "issue_field" if start else None,
        "end_source": end_source,
        "milestone": {
            "repo": repo,
            "number": ms.get("number"),
            "title": ms.get("title"),
            "due_on": to_iso(to_date(ms.get("dueOn"))),
        }
        if ms.get("number")
        else None,
        "blocked_by": _keys(content.get("blockedBy")),
        "parent": parent_key,
        "children": [],
        "created_at": to_iso(to_date(content.get("createdAt"))),
        "closed_at": to_iso(to_date(content.get("closedAt"))),
        "absorbed_by": None,
    }


def _number(value) -> float | None:
    return float(value) if value is not None else None


def _type(typename: str | None) -> str:
    return {
        "Issue": "issue",
        "PullRequest": "pull_request",
        "DraftIssue": "draft",
    }.get(typename or "", "unknown")


def _keys(connection: dict | None) -> list[str]:
    out = []
    for node in (connection or {}).get("nodes") or []:
        repo = (node.get("repository") or {}).get("nameWithOwner")
        if repo and node.get("number") is not None:
            out.append(f"{repo}#{node['number']}")
    return sorted(set(out))


# ------------------------------------------------------------------- colapso


def _collapse(items: list[dict]) -> tuple[list[dict], dict[str, list[str]]]:
    """Absorve sub-issues no topo que está no board, sem mutar `items`."""
    by_key = {i["key"]: i for i in items}
    groups: dict[str, list[dict]] = defaultdict(list)

    for item in items:
        groups[_root(item, by_key)].append(item)

    nodes: list[dict] = []
    absorbed: dict[str, list[str]] = {}

    for root_key, group in groups.items():
        root = _node_copy(by_key[root_key])
        if len(group) > 1:
            absorbed[root_key] = sorted(i["key"] for i in group if i["key"] != root_key)
        root["children"] = absorbed.get(root_key, [])
        root.update(_union_window(group))
        root["blocked_by"] = _merge_blockers(group, root_key, by_key)
        nodes.append(root)

    nodes.sort(key=_node_order)
    return nodes, dict(absorbed)


def _node_order(node: dict) -> tuple:
    ms = node.get("milestone") or {}
    return (ms.get("number", 10**9), node["key"])


def _root(item: dict, by_key: dict[str, dict]) -> str:
    seen = {item["key"]}
    current = item
    while current.get("parent") in by_key:
        parent_key = current["parent"]
        if parent_key in seen:
            break
        seen.add(parent_key)
        current = by_key[parent_key]
    return current["key"]


def _union_window(group: Iterable[dict]) -> dict:
    group = list(group)
    starts = [i["start"] for i in group if i.get("start")]
    ends = [i["end"] for i in group if i.get("end")]
    start = min(starts) if starts else None
    end = max(ends) if ends else None
    sources = {i.get("start_source") for i in group if i.get("start")}
    return {
        "start": start,
        "end": end,
        "start_source": "union" if len(group) > 1 else next(iter(sources), None),
        "end_source": "union" if len(group) > 1 else next(
            (i.get("end_source") for i in group if i.get("end")), None
        ),
    }


def _merge_blockers(group: list[dict], root_key: str, by_key: dict[str, dict]) -> list[str]:
    merged: set[str] = set()
    own = {i["key"] for i in group}
    for item in group:
        for blocker in item.get("blocked_by") or []:
            target = _root(by_key[blocker], by_key) if blocker in by_key else blocker
            if target not in own and target != root_key:
                merged.add(target)
    return sorted(merged)


# ------------------------------------------------------------------- janelas


def _milestone_windows(nodes: list[dict]) -> list[dict]:
    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for node in nodes:
        ms = node.get("milestone")
        if ms and ms.get("number"):
            groups[(ms["repo"], ms["number"])].append(node)

    out = []
    for (repo, number), group in groups.items():
        starts = [n["start"] for n in group if n.get("start")]
        ends = [n["end"] for n in group if n.get("end")]
        start = min(starts) if starts else None
        end = max(ends) if ends else None
        due = group[0]["milestone"].get("due_on")

        delta = None
        status = "sem_due"
        if due and end:
            delta = (to_date(end) - to_date(due)).days
            status = "estourado" if delta > 0 else "ok"

        span = None
        if start and end:
            span = (to_date(end) - to_date(start)).days + 1

        out.append(
            {
                "repo": repo,
                "number": number,
                "title": group[0]["milestone"].get("title"),
                "nodes": len(group),
                "start": start,
                "end": end,
                "due_on": due,
                "delta_days": delta,
                "span_days": span,
                "status": status,
            }
        )

    out.sort(key=lambda m: (m["start"] or "9999", m["repo"], m["number"]))
    return out


# -------------------------------------------------------------------- avisos


def _warnings(
    board: dict,
    nodes: list[dict],
    milestones: list[dict],
    absorbed: dict[str, list[str]],
) -> list[str]:
    out: list[str] = []

    sem_data = [n["key"] for n in nodes if not n.get("start") or not n.get("end")]
    if sem_data:
        out.append(
            f"{len(sem_data)} nó(s) sem data completa: {', '.join(sem_data[:5])}"
            + (" ..." if len(sem_data) > 5 else "")
        )

    for m in milestones:
        if m["status"] == "estourado":
            out.append(
                f"milestone estourado: {m['title']} — fim real {m['end']} vs dueOn {m['due_on']} (+{m['delta_days']}d)"
            )

    for parent, children in absorbed.items():
        out.append(f"colapso: {parent} absorveu {len(children)} sub-issue(s)")

    if board.get("detail") != "all":
        node_keys = {n["key"] for n in nodes}
        prs = [i["key"] for i in board.get("items") or [] if i["type"] == "pull_request" and i["key"] not in node_keys]
        if prs:
            out.append(
                f"{len(prs)} pull request(s) fora do grafo (use --detail all): {', '.join(prs)}"
            )

    teams = board.get("teams")
    if teams is not None:
        out.extend(_team_warnings(board, nodes, teams))

    return out


def _team_warnings(board: dict, nodes: list[dict], teams: list[str]) -> list[str]:
    out: list[str] = []
    teams_map = resolve_teams(board)
    present = {teams_map.get(n["key"]) for n in nodes}

    for team in teams:
        if team not in present:
            out.append(f"time `{team}` não tem nenhum nó no board")

    touched: set[str] = set()
    for node in nodes:
        for blocker in node.get("blocked_by") or []:
            touched.add(node["key"])
            touched.add(blocker)

    for team in teams:
        group = {n["key"] for n in nodes if teams_map.get(n["key"]) == team}
        if group and not group & touched:
            out.append(f"time `{team}` não tem nenhuma dependência — o grafo vira lista")

    unassigned = [n for n in nodes if not teams_map.get(n["key"])]
    if unassigned:
        out.append(
            f"{len(unassigned)} tarefa(s) sem time incluída(s) em `{UNASSIGNED}`"
        )
    return out


# ------------------------------------------------------------------ terminal


def render_terminal(board: dict) -> str:
    counts = board["counts"]
    out = [
        f"{board['project'].get('title') or 'board'} · {counts['nodes']} nós "
        f"({counts['items']} itens, {counts['absorbed']} absorvidos) · "
        f"{counts['milestones']} milestones",
        "",
        f"{'Milestone':<40}{'nós':>4}  {'início':<11}{'fim':<11}{'dueOn':<11}{'Δ':>6}",
        "-" * 84,
    ]
    for m in board["milestones"]:
        delta = "—" if m["delta_days"] is None else f"{m['delta_days']:+d}d"
        out.append(
            f"{_clip(m['title'], 39):<40}{m['nodes']:>4}  "
            f"{m['start'] or '—':<11}{m['end'] or '—':<11}{m['due_on'] or '—':<11}{delta:>6}"
        )

    estourados = sum(1 for m in board["milestones"] if m["status"] == "estourado")
    sem_due = sum(1 for m in board["milestones"] if m["status"] == "sem_due")
    out += ["", f"estourados: {estourados} · sem dueOn: {sem_due}"]

    if board["warnings"]:
        out += ["", "avisos:"] + [f"  - {w}" for w in board["warnings"]]
    return "\n".join(out)


def _clip(text: str | None, size: int) -> str:
    text = text or "—"
    return text if len(text) <= size else text[: size - 1] + "…"
