"""PERT/CPM: cronograma por componente de dependência.

`schedule` é puro: recebe o Board já filtrado e o grafo, devolve cada tarefa
com ES/EF/LS/LF, folga, crítica e probabilidade. A unidade é dia de calendário
inclusive, igual ao resto do pipeline; `Duration` (horas de esforço) não entra.

A duração do passe é o **TE do PERT** — `(O + 4M + P)/6` quando as três
estimativas existem; sem elas, cai na mais provável, depois na janela
planejada, e `sigma` fica 0 (probabilidade degenerada). Datas de exibição:
`start = âncora + floor(es)`, `finish = âncora + ceil(ef)`.

Arestas de hierarquia e dependências de fora do board (fantasmas) não
restringem o cronograma. Duração 0 ocupa o dia da própria âncora (marco), em
vez de consumir dia algum — mantém start ≤ finish sem inverter datas. Sem
`deadline`, cada componente termina no seu próprio EF; nó sem dependência
interna não tem folga finita (`slack=None`) e não é crítico.

Contratos:
- `duration` (int) é `te` arredondado para cima — a exibição em dias inteiros.
- `milestone` é o dict do nó ou `None` — a chave do projeto é `(repo, number)`,
  nunca o título.
- `team` passa pela herança (`resolve_teams`), igual a `graph`/`render`.
- Crítico = menor folga do componente (caminho mais longo), não folga zero:
  com prazo folgado todos têm folga positiva e ainda há caminho crítico.
- `Prazo` por tarefa não entra no cálculo do CPM; é alvo de comparação.
- Variância segue o caminho mais longo até a tarefa (`sigma_path`); a
  probabilidade assume normal, dominância do caminho mais longo e
  componentes independentes entre si.
- Datas de exibição arredondam para fora (`floor`/`ceil`); com TE fracionário,
  tarefas encadeadas podem compartilhar o dia de fronteira — os offsets
  `es/ef/ls/lf` guardam a precisão real.
- Probabilidade: tarefa só contra o próprio `Prazo`; milestone contra `due_on`
  ou `max(Prazo)` dos membros; projeto contra o `deadline` global, como
  produto dos componentes. `probability: null` = sem prazo; `0` ou `1` =
  degenerada (σ = 0).
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, timedelta

from .fields import to_date, to_iso
from .team import UNASSIGNED, resolve_teams

EPS = 1e-9


def schedule(board: dict, graph: dict, deadline: str | date | None = None) -> dict:
    nodes = [n for n in board.get("nodes") or [] if n.get("key")]
    by_key = {n["key"]: n for n in nodes}
    warnings: list[str] = []

    cycled = {k for cycle in graph.get("cycles") or [] for k in cycle}
    if cycled:
        warnings.append(f"{len(cycled)} nó(s) em ciclo ficam fora do cronograma")

    durations: dict[str, int] = {}
    sources: dict[str, str] = {}
    tes: dict[str, float] = {}
    sigmas: dict[str, float] = {}
    zero: list[str] = []
    window: list[str] = []
    no_estimate: list[str] = []
    inverted: list[str] = []
    for node in nodes:
        if node["key"] in cycled:
            continue
        days, te, sigma, source = _estimate(node)
        durations[node["key"]] = days
        sources[node["key"]] = source
        tes[node["key"]] = te
        sigmas[node["key"]] = sigma
        if source == "zero":
            zero.append(node["key"])
        elif source == "janela":
            window.append(node["key"])
        if sigma == 0 and node.get("deadline"):
            no_estimate.append(node["key"])
        o, p = node.get("optimistic"), node.get("pessimistic")
        if o is not None and p is not None and p < o:
            inverted.append(node["key"])
    if zero:
        warnings.append(f"{len(zero)} tarefa(s) sem janela completa nem estimativa: {', '.join(sorted(zero))}")
    if window:
        warnings.append(f"{len(window)} tarefa(s) usando a janela como duração: {', '.join(sorted(window))}")
    if no_estimate:
        warnings.append(
            f"{len(no_estimate)} tarefa(s) com Prazo e sem desvio (σ = 0): probabilidade degenerada"
        )
    if inverted:
        warnings.append(
            f"{len(inverted)} tarefa(s) com Pessimista < Otimista: σ = 0 e aviso de estimativa invertida"
        )

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
        es, ef, var = _forward(order, pred, tes, sigmas)
        limit = _limit(anchor, max(ef.values()), deadline_date)
        ls, lf = _backward(order, succ, tes, limit)

        slacks = {
            k: None if not pred[k] and not succ[k] else ls[k] - es[k]
            for k in comp
        }
        finite = [v for v in slacks.values() if v is not None]
        floor = min(finite, default=0.0)
        critical = {k for k, v in slacks.items() if v is not None and abs(v - floor) < EPS}
        path = _critical_path(comp, pred, succ, ef, critical)
        terminals = [k for k in comp if not succ[k]]
        head = max(terminals, key=lambda k: (ef[k], k))

        sigma_head = math.sqrt(var[head])
        comp_proba = None
        if deadline_date and anchor is not None:
            comp_proba = _z_probability(_margin(to_iso(anchor), ef[head], deadline_date), sigma_head)

        for key in comp:
            node = by_key[key]
            sigma_path = math.sqrt(var[key])
            task = {
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
                "te": tes[key],
                "sigma": sigmas[key],
                "sigma_path": sigma_path,
                "es": es[key],
                "ef": ef[key],
                "ls": ls[key],
                "lf": lf[key],
                "planned_start": node.get("start"),
                "planned_end": node.get("end"),
                "start": _date_at(anchor, es[key]),
                "finish": _date_at(anchor, ef[key], end=True),
                "late_start": _date_at(anchor, ls[key]),
                "late_finish": _date_at(anchor, lf[key], end=True),
                "slack": slacks[key],
                "critical": key in critical,
                "probability": None,
            }
            if task["deadline"]:
                task["probability"] = _probability(task, task["deadline"])
            tasks.append(task)

        components.append({
            "index": index,
            "anchor": to_iso(anchor),
            "task_count": len(comp),
            "critical_path": path,
            "expected_finish": _date_at(anchor, ef[head], end=True),
            "sigma_path": sigma_head,
            "probability": comp_proba,
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
        "probabilities": {
            "project": _project_probability(components, deadline_date),
            "milestones": _milestone_probabilities(tasks),
        },
        "warnings": warnings,
    }


def calibrate(board: dict) -> dict:
    """Fator de realidade: mediana de real/planejado nas tarefas concluídas."""
    samples: list[dict] = []
    skipped: list[str] = []

    for item in board.get("items") or []:
        key = item.get("key")
        start = to_date(item.get("start"))
        closed = to_date(item.get("closed_at"))
        planned_end = to_date(item.get("end")) if item.get("end_source") == "issue_field" else None
        if not (start and closed and planned_end):
            skipped.append(key)
            continue
        planned = (planned_end - start).days + 1
        real = (closed - start).days + 1
        if planned < 1 or real < 1:
            skipped.append(key)
            continue
        samples.append({
            "key": key,
            "planned_days": planned,
            "real_days": real,
            "ratio": round(real / planned, 3),
        })

    samples.sort(key=lambda s: s["key"])
    ratios = [s["ratio"] for s in samples]
    return {
        "reality_factor": statistics.median(ratios) if ratios else None,
        "sample": samples,
        "skipped": sorted(k for k in skipped if k),
        "warnings": [] if samples else ["nenhuma tarefa concluída com Start/Target/closedAt"],
    }


# ---------------------------------------------------------------- apresentação


def render_markdown(board: dict, result: dict, calibration: dict) -> str:
    """Tabela de entrega do PERT/CPM em Markdown."""
    probs = result["probabilities"]
    lines = [
        "# PERT/CPM",
        "",
        _meta_line(board, result),
        "",
        f"- fim esperado do cronograma: **{result['finish'] or '—'}**",
    ]
    project = probs["project"]
    if project:
        lines.append(
            f"- P(projeto ≤ {project['deadline']}) = **{_pct(project['probability'])}**"
        )
    lines.append("")

    if probs["milestones"]:
        lines += [
            "## Probabilidade por milestone",
            "",
            "| milestone | tarefas | prazo | origem | fim esperado | σ | P(≤ prazo) |",
            "|---|---:|---|---|---|---:|---:|",
        ]
        for ms in probs["milestones"]:
            label = ms["title"] or f"{ms['repo']}#{ms['number']}"
            lines.append(
                f"| {label} | {ms['tasks']} | {ms['deadline'] or '—'} "
                f"| {ms['source'] or '—'} | {ms['expected_finish'] or '—'} "
                f"| {ms['sigma_path']:.2f} | {_pct(ms['probability'])} |"
            )
        lines.append("")

    lines += [
        "## Tabela PERT (ES/EF/LS/LF em dias desde a âncora do componente)",
        "",
        "| tarefa | O | M | P | TE | σ | ES | EF | LS | LF | folga | crítica |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|",
    ]
    for t in sorted(result["tasks"], key=lambda t: (t["component"], t["es"], t["key"])):
        late = "— | —" if t["slack"] is None else f"{t['ls']:g} | {t['lf']:g}"
        lines.append(
            f"| {_short(t['key'])} | {_num(t['optimistic'])} | {_num(t['likely'])} "
            f"| {_num(t['pessimistic'])} | {t['te']:.2f} | {t['sigma']:.2f} "
            f"| {t['es']:g} | {t['ef']:g} | {late} "
            f"| {_slack(t['slack'])} | {'★' if t['critical'] else ''} |"
        )
    lines += [
        "",
        "folga = LS − ES (contra o prazo global, quando definido). Tarefa sem "
        "restrição interna não tem folga finita nem LS/LF — é uma frente livre. "
        "★ = menor folga do componente (caminho mais longo).",
    ]
    lines.append("")

    lines += [
        "## Calendário",
        "",
        "| tarefa | time | planejado | calculado | Prazo | P(≤ Prazo) |",
        "|---|---|---|---|---|---:|",
    ]
    for t in sorted(result["tasks"], key=lambda t: (t["component"], t["es"], t["key"])):
        lines.append(
            f"| {_short(t['key'])} | {t['team']} "
            f"| {_span(t['planned_start'], t['planned_end'])} "
            f"| {_span(t['start'], t['finish'])} | {t['deadline'] or '—'} "
            f"| {_pct(t['probability'])} |"
        )
    lines.append("")

    factor = calibration["reality_factor"]
    lines.append("## Calibração pelo realizado")
    lines.append("")
    if factor is None:
        lines.append("sem tarefas concluídas com Start/Target/closedAt para calibrar.")
    else:
        lines += [
            f"fator de realidade (mediana real/planejado): **{factor:.2f}** "
            f"· n = {len(calibration['sample'])} · ignoradas: {len(calibration['skipped'])}",
            "",
            "| tarefa | planejado | real | ratio |",
            "|---|---:|---:|---:|",
        ]
        for s in calibration["sample"]:
            lines.append(
                f"| {_short(s['key'])} | {s['planned_days']}d | {s['real_days']}d | {s['ratio']:.2f} |"
            )
    lines.append("")

    warnings = list(result["warnings"]) + list(calibration["warnings"])
    if warnings:
        lines.append("## Observações")
        lines.append("")
        lines += [f"- {w}" for w in warnings]
        lines.append("")
    return "\n".join(lines)


def _meta_line(board: dict, result: dict) -> str:
    parts = [f"gerado em {board.get('generatedAt')}", f"recorte: {board.get('detail') or 'parents'}"]
    if board.get("teams"):
        parts.append("times: " + ", ".join(board["teams"]))
    if result.get("deadline"):
        parts.append(f"prazo global: {result['deadline']}")
    return " · ".join(parts)


def _short(key: str) -> str:
    return key.rsplit("/", 1)[-1]


def _num(value: float | None) -> str:
    return f"{value:g}" if value is not None else "—"


def _slack(value: float | None) -> str:
    return f"{value:g}" if value is not None else "∞"


def _pct(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "—"


def _span(start: str | None, end: str | None) -> str:
    return f"{start}..{end}" if start and end else "—"


# ------------------------------------------------------------------- cálculo


def _estimate(node: dict) -> tuple[int, float, float, str]:
    """(duração exibida, te, sigma, fonte). TE é a duração do passe."""
    o, m, p = node.get("optimistic"), node.get("likely"), node.get("pessimistic")
    if o is not None and m is not None and p is not None:
        te = (o + 4 * m + p) / 6
        return max(0, math.ceil(te)), te, max(0.0, (p - o) / 6), "estimativa"
    if m is not None:
        return max(0, math.ceil(m)), float(m), 0.0, "estimativa"

    start, end = to_date(node.get("start")), to_date(node.get("end"))
    if start and end and end >= start:
        te = float((end - start).days + 1)
        return int(te), te, 0.0, "janela"
    return 0, 0.0, 0.0, "zero"


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


def _forward(order: list[str], pred: dict, tes: dict[str, float], sigmas: dict[str, float]):
    es, ef, var = {}, {}, {}
    for key in order:
        best = max(pred[key], key=lambda p: (ef[p], p), default=None)
        es[key] = ef[best] + 1 if best is not None else 0.0
        ef[key] = es[key] + tes[key] - 1 if tes[key] > 0 else es[key]
        var[key] = (var[best] if best is not None else 0.0) + sigmas[key] ** 2
    return es, ef, var


def _backward(order: list[str], succ: dict, tes: dict[str, float], limit: float):
    ls, lf = {}, {}
    for key in reversed(order):
        lf[key] = min((ls[s] - 1 for s in succ[key]), default=limit)
        ls[key] = lf[key] - tes[key] + 1 if tes[key] > 0 else lf[key]
    return ls, lf


def _limit(anchor: date | None, comp_end: float, deadline: date | None) -> float:
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


def _probability(task: dict, deadline: str | date) -> float:
    return _z_probability(_margin(task["anchor"], task["ef"], deadline), task["sigma_path"])


def _margin(anchor: str | None, ef: float, deadline: str | date) -> float:
    return (to_date(deadline) - to_date(anchor)).days - ef


def _z_probability(margin: float, sigma_path: float) -> float:
    """P(fim ≤ prazo) com normal; degenerada (0 ou 1) quando sigma_path = 0."""
    if sigma_path > 0:
        return 0.5 * (1 + math.erf(margin / sigma_path / math.sqrt(2)))
    return 1.0 if margin >= 0 else 0.0


def _milestone_probabilities(tasks: list[dict]) -> list[dict]:
    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for task in tasks:
        ms = task["milestone"]
        if ms and ms.get("number"):
            groups[(ms["repo"], ms["number"])].append(task)

    out = []
    for (repo, number), members in sorted(groups.items()):
        head = max(members, key=lambda t: (t["finish"] or "", t["key"]))
        due = head["milestone"].get("due_on")
        deadline = due or max((m["deadline"] for m in members if m["deadline"]), default=None)
        out.append({
            "repo": repo,
            "number": number,
            "title": head["milestone"].get("title"),
            "deadline": deadline,
            "source": "due_on" if due else ("prazo" if deadline else None),
            "expected_finish": head["finish"],
            "sigma_path": head["sigma_path"],
            "probability": _probability(head, deadline) if deadline else None,
            "tasks": len(members),
        })
    return out


def _project_probability(components: list[dict], deadline: date | None) -> dict | None:
    """Componentes são independentes: P(projeto ≤ prazo) é o produto."""
    if deadline is None or not components:
        return None
    probas = [c["probability"] for c in components if c["probability"] is not None]
    finishes = [c["expected_finish"] for c in components if c["expected_finish"]]
    return {
        "deadline": deadline.isoformat(),
        "expected_finish": max(finishes, default=None),
        "probability": math.prod(probas) if probas else None,
    }


def _date_at(anchor: date | None, offset: float, end: bool = False) -> str | None:
    if anchor is None:
        return None
    shift = math.ceil(offset) if end else math.floor(offset)
    return (anchor + timedelta(days=shift)).isoformat()


def _min_start(nodes: list[dict]) -> date | None:
    dates = [to_date(n.get("start")) for n in nodes]
    dates = [d for d in dates if d is not None]
    return min(dates) if dates else None
