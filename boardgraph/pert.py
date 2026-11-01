"""CPM: caminho crítico por componente de dependência.

`schedule` é puro: recebe o Board já filtrado e o grafo, devolve cada tarefa
com ES/EF/LS/LF, folga e marcação de crítica. A unidade é dia de calendário
inclusive, igual ao resto do pipeline; `Duration` (horas de esforço) não entra.

Arestas de hierarquia e dependências de fora do board (fantasmas) não
restringem o cronograma. Duração 0 ocupa o dia da própria âncora (marco), em
vez de consumir dia algum — mantém start ≤ finish sem inverter datas. Sem
`deadline`, cada componente termina no seu próprio EF; nó sem dependência
interna não tem folga finita (`slack=None`) e não é crítico.

Contratos:
- `duration` (int, dias) é a duração do passe; estimativas e `te`/`sigma`,
  quando existirem, são estatística e não substituem a duração.
- `milestone` é o dict do nó ou `None` — a chave do projeto é `(repo, number)`,
  nunca o título.
- `team` passa pela herança (`resolve_teams`), igual a `graph`/`render`.
- Crítico = menor folga do componente (caminho mais longo), não folga zero:
  com prazo folgado todos têm folga positiva e ainda há caminho crítico.
- `Prazo` por tarefa não entra no cálculo do CPM.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from .fields import to_date, to_iso
from .team import UNASSIGNED, resolve_teams


def schedule(board: dict, graph: dict, deadline: str | date | None = None) -> dict:
    nodes = [n for n in board.get("nodes") or [] if n.get("key")]
    by_key = {n["key"]: n for n in nodes}
    warnings: list[str] = []

    cycled = {k for cycle in graph.get("cycles") or [] for k in cycle}
    if cycled:
        warnings.append(f"{len(cycled)} nó(s) em ciclo ficam fora do cronograma")

    durations: dict[str, int] = {}
    sources: dict[str, str] = {}
    zero: list[str] = []
    window: list[str] = []
    for node in nodes:
        if node["key"] in cycled:
            continue
        days, source = _duration(node)
        durations[node["key"]] = days
        sources[node["key"]] = source
        if source == "zero":
            zero.append(node["key"])
        elif source == "janela":
            window.append(node["key"])
    if zero:
        warnings.append(f"{len(zero)} tarefa(s) sem janela completa nem estimativa: {', '.join(sorted(zero))}")
    if window:
        warnings.append(f"{len(window)} tarefa(s) usando a janela como duração: {', '.join(sorted(window))}")

    edges = [
        e for e in graph.get("edges") or []
        if e["kind"] == "dependency"
        and e["from"] in durations and e["to"] in durations
        and e["from"] != e["to"]
    ]
    external = [
        e for e in graph.get("edges") or []
        if e.get("external") and e["kind"] == "dependency"
    ]
    if external:
        pairs = ", ".join(f"{e['from']} → {e['to']}" for e in external)
        warnings.append(f"{len(external)} dependência(s) de fora do board ignorada(s): {pairs}")

    teams = resolve_teams(board)
    deadline_date = to_date(deadline)
    if deadline is not None and deadline_date is None:
        raise ValueError(f"deadline inválido: {deadline!r}")

    succ: dict[str, list[str]] = defaultdict(list)
    pred: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        succ[edge["from"]].append(edge["to"])
        pred[edge["to"]].append(edge["from"])

    fallback = _min_start(nodes)
    tasks: list[dict] = []
    components: list[dict] = []

    for index, comp in enumerate(_components(list(durations), edges)):
        anchor = _min_start([by_key[k] for k in comp]) or fallback
        order = _topo(comp, pred, succ)
        es, ef = _forward(order, pred, durations)
        limit = _limit(anchor, max(ef.values()), deadline_date)
        ls, lf = _backward(order, succ, durations, limit)

        slacks = {
            k: None if not pred[k] and not succ[k] else ls[k] - es[k]
            for k in comp
        }
        finite = [v for v in slacks.values() if v is not None]
        floor = min(finite, default=0)
        critical = {k for k, v in slacks.items() if v is not None and v == floor}
        path = _critical_path(comp, pred, succ, ef, critical)

        for key in comp:
            node = by_key[key]
            tasks.append({
                "key": key,
                "title": node.get("title"),
                "team": teams.get(key) or UNASSIGNED,
                "milestone": node.get("milestone"),
                "optimistic": node.get("optimistic"),
                "likely": node.get("likely"),
                "pessimistic": node.get("pessimistic"),
                "deadline": node.get("deadline"),
                "component": index,
                "anchor": to_iso(anchor),
                "duration": durations[key],
                "duration_source": sources[key],
                "planned_start": node.get("start"),
                "planned_end": node.get("end"),
                "start": _add(anchor, es[key]),
                "finish": _add(anchor, ef[key]),
                "late_start": _add(anchor, ls[key]),
                "late_finish": _add(anchor, lf[key]),
                "slack": slacks[key],
                "critical": key in critical,
            })

        components.append({
            "index": index,
            "anchor": to_iso(anchor),
            "finish": _add(anchor, max(ef.values())),
            "task_count": len(comp),
            "critical_path": path,
        })

    tasks.sort(key=lambda t: t["key"])
    finish = max((t["finish"] for t in tasks if t["finish"]), default=None)
    if deadline_date and finish and deadline_date < to_date(finish):
        warnings.append(f"prazo {deadline_date.isoformat()} é anterior ao fim calculado {finish}")

    return {
        "deadline": to_iso(deadline_date),
        "finish": finish,
        "tasks": tasks,
        "critical": sorted(t["key"] for t in tasks if t["critical"]),
        "components": components,
        "warnings": warnings,
    }


def _duration(node: dict) -> tuple[int, str]:
    """Duração em dias; estimativa primeiro, janela planejada como reserva."""
    likely = node.get("likely")
    if likely is not None:
        return max(0, math.ceil(likely)), "estimativa"

    start, end = to_date(node.get("start")), to_date(node.get("end"))
    if start and end and end >= start:
        return (end - start).days + 1, "janela"
    return 0, "zero"


def _components(keys: list[str], edges: list[dict]) -> list[list[str]]:
    adj: dict[str, set[str]] = {k: set() for k in keys}
    for edge in edges:
        adj[edge["from"]].add(edge["to"])
        adj[edge["to"]].add(edge["from"])

    seen: set[str] = set()
    out: list[list[str]] = []
    for key in sorted(keys):
        if key in seen:
            continue
        stack, comp = [key], []
        seen.add(key)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nxt in sorted(adj[cur]):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        out.append(sorted(comp))
    return out


def _topo(comp: list[str], pred: dict, succ: dict) -> list[str]:
    indeg = {k: len(pred[k]) for k in comp}
    ready = [k for k in comp if indeg[k] == 0]
    order: list[str] = []
    while ready:
        key = ready.pop(0)
        order.append(key)
        for nxt in succ[key]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
    return order


def _forward(order: list[str], pred: dict, durations: dict[str, int]) -> tuple[dict, dict]:
    es, ef = {}, {}
    for key in order:
        es[key] = max((ef[p] + 1 for p in pred[key]), default=0)
        ef[key] = es[key] + durations[key] - 1 if durations[key] > 0 else es[key]
    return es, ef


def _backward(order: list[str], succ: dict, durations: dict[str, int], limit: int) -> tuple[dict, dict]:
    ls, lf = {}, {}
    for key in reversed(order):
        lf[key] = min((ls[s] - 1 for s in succ[key]), default=limit)
        ls[key] = lf[key] - durations[key] + 1 if durations[key] > 0 else lf[key]
    return ls, lf


def _limit(anchor: date | None, comp_end: int, deadline: date | None) -> int:
    if deadline is None or anchor is None:
        return comp_end
    return (deadline - anchor).days


def _critical_path(comp: list[str], pred: dict, succ: dict, ef: dict, critical: set[str]) -> list[str]:
    terminals = [k for k in comp if not succ[k] and k in critical]
    if not terminals:
        return []
    current = max(terminals, key=lambda k: (ef[k], k))
    path: list[str] = []
    while current is not None:
        path.append(current)
        options = [p for p in pred[current] if p in critical]
        current = max(options, key=lambda k: (ef[k], k)) if options else None
    return list(reversed(path))


def _min_start(nodes: list[dict]) -> date | None:
    dates = [to_date(n.get("start")) for n in nodes]
    dates = [d for d in dates if d is not None]
    return min(dates) if dates else None


def _add(anchor: date | None, offset: int) -> str | None:
    return (anchor + timedelta(days=offset)).isoformat() if anchor else None


