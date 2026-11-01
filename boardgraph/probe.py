"""Fase 2 — relatório de cobertura dos campos.

Não adivinha: mede o payload e denuncia o que está vazio. Roda antes do
diagrama para que "campo sumiu" vire aviso, e não um grafo errado.

Regras:
- Tabela mostra tudo que foi medido (inclusive campo esparso de propósito).
- Aviso só dispara para campo `required` — os outros são informativos.
- Campo que não foi pedido no fetch aparece como "não coletado", não como 0%.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .fields import field_map, item_key

MAX_EXAMPLES = 5


def _always(_item: dict) -> bool:
    return True


@dataclass
class Row:
    name: str
    kind: str
    getter: Callable[[dict], Any]
    applies: Callable[[dict], bool] = _always
    required: bool = False
    collect_key: str | None = None
    filled: int = 0
    total: int = 0
    missing: list[str] = field(default_factory=list)
    collected: bool = True

    @property
    def pct(self) -> float:
        return (self.filled / self.total * 100) if self.total else 0.0

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "required": self.required,
            "collected": self.collected,
            "filled": self.filled,
            "total": self.total,
            "pct": round(self.pct, 1),
            "missing": self.missing,
        }


def _is_issue(item: dict) -> bool:
    return (item.get("content") or {}).get("__typename") == "Issue"


def _content(item: dict) -> dict:
    return item.get("content") or {}


def _milestone(item: dict) -> dict:
    return _content(item).get("milestone") or {}


def _rows() -> list[Row]:
    return [
        # required: sem isso a janela de tempo do milestone não fecha
        Row("Status", "projeto · single select", lambda i: field_map(i).get("Status"), required=True),
        Row("Start date", "issue field · date", lambda i: field_map(i).get("Start date"), required=True),
        Row("Target date", "issue field · date", lambda i: field_map(i).get("Target date"), required=True),
        Row("Milestone", "issue · milestone", lambda i: _milestone(i).get("title"), required=True),
        # informativos
        Row("Team", "projeto · single select", lambda i: field_map(i).get("Team")),
        Row("Duration", "issue field · number", lambda i: field_map(i).get("Duration")),
        Row("milestone.dueOn", "issue · milestone", lambda i: _milestone(i).get("dueOn")),
        Row("closedAt", "issue · content", lambda i: _content(i).get("closedAt"), _is_issue),
        Row("Labels", "issue · content", lambda i: ((_content(i).get("labels") or {}).get("nodes") or None), _is_issue),
        Row("Assignee", "issue · content", lambda i: ((_content(i).get("assignees") or {}).get("nodes") or None), _is_issue),
        Row("Body", "issue · content", lambda i: (_content(i).get("body") or "").strip() or None, _is_issue, collect_key="body"),
        Row("Blocked by", "issue · dependência", lambda i: ((_content(i).get("blockedBy") or {}).get("totalCount") or None), _is_issue, collect_key="blockedBy"),
        Row("Parent (sub-issue)", "issue · hierarquia", lambda i: _content(i).get("parent"), _is_issue, collect_key="parent"),
    ]


def build_report(payload: dict, source: str = "out/raw/latest.json") -> dict:
    items = payload.get("items") or []
    rows = _rows()

    for row in rows:
        if row.collect_key:
            row.collected = any(row.collect_key in _content(i) for i in items if row.applies(i))
        if not row.collected:
            continue
        for item in items:
            if not row.applies(item):
                continue
            row.total += 1
            if row.getter(item) not in (None, "", [], 0):
                row.filled += 1
            elif len(row.missing) < MAX_EXAMPLES:
                row.missing.append(item_key(item))

    warnings, notes = _warnings(payload, rows)

    by_type: dict[str, int] = {}
    for item in items:
        key = _content(item).get("__typename") or "sem content"
        by_type[key] = by_type.get(key, 0) + 1

    milestones: dict[tuple[str, int], dict] = {}
    for item in items:
        ms = _milestone(item)
        if ms.get("number"):
            repo = (_content(item).get("repository") or {}).get("nameWithOwner", "")
            milestones[(repo, ms["number"])] = ms

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "project": (payload.get("project") or {}).get("title"),
        "total": len(items),
        "byType": by_type,
        "milestones": {
            "total": len(milestones),
            "semDueOn": sum(1 for m in milestones.values() if not m.get("dueOn")),
        },
        "fields": [row.as_dict() for row in rows],
        "schema": {
            "projectFields": len(payload.get("fields") or []),
            "singleSelects": {
                f["name"]: [o["name"] for o in f.get("options") or []]
                for f in payload.get("fields") or []
                if f.get("__typename") == "ProjectV2SingleSelectField"
            },
        },
        "warnings": warnings,
        "notes": notes,
    }


def _warnings(payload: dict, rows: list[Row]) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    notes: list[str] = []
    for row in rows:
        if row.required and row.collected and row.total and row.filled < row.total:
            detail = f" — ex: {', '.join(row.missing)}" if row.missing else ""
            warnings.append(f"{row.name}: {row.total - row.filled}/{row.total} sem valor{detail}")

    if not (payload.get("project") or {}).get("title"):
        warnings.append("payload sem título de projeto — confira o cache")

    titles: dict[str, set[int]] = {}
    for item in payload.get("items") or []:
        ms = _milestone(item)
        if ms.get("title") and ms.get("number"):
            titles.setdefault(ms["title"], set()).add(ms["number"])
    for title, numbers in titles.items():
        if len(numbers) > 1:
            warnings.append(f"título de milestone duplicado em números distintos: {title} → {sorted(numbers)}")

    notes += _status_divergences(payload)
    return warnings, notes


def _status_divergences(payload: dict) -> list[str]:
    """Status não calcula nada, mas pai e filha discordando é erro de preenchimento."""
    items = {}
    for item in payload.get("items") or []:
        content = _content(item)
        repo = (content.get("repository") or {}).get("nameWithOwner")
        number = content.get("number")
        if repo and number is not None:
            items[(repo, number)] = (item, content)

    notes: list[str] = []
    for (repo, number), (item, content) in items.items():
        parent = content.get("parent") or {}
        target = items.get((repo, parent.get("number")))
        if not target:
            continue
        status_child = field_map(item).get("Status")
        status_parent = field_map(target[0]).get("Status")
        if status_child and status_parent and status_child != status_parent:
            notes.append(
                f"status divergente entre pai e filha: "
                f"{repo}#{parent['number']} ({status_parent}) vs {repo}#{number} ({status_child})"
            )
    return notes


def render_markdown(report: dict) -> str:
    lines = [
        f"# Cobertura — {report.get('project') or 'board'}",
        "",
        f"Fonte: `{report['source']}` · {report['total']} itens "
        f"({', '.join(f'{v} {k}' for k, v in report['byType'].items())})",
        "",
        "| Campo | Tipo | Obrigatório | Preenchido | Cobertura |",
        "|---|---|---|---|---|",
    ]
    for row in report["fields"]:
        filled = "não coletado" if not row["collected"] else f"{row['filled']}/{row['total']}"
        bar = "—" if not row["collected"] else f"{_bar(row['pct'])} {row['pct']:.0f}%"
        required = "sim" if row["required"] else ""
        lines.append(f"| {row['name']} | {row['kind']} | {required} | {filled} | {bar} |")

    lines += [
        "",
        f"Milestones: {report['milestones']['total']} "
        f"({report['milestones']['semDueOn']} sem dueOn)",
        "",
    ]

    if report["warnings"]:
        lines += ["## Avisos", ""] + [f"- {w}" for w in report["warnings"]]
    else:
        lines += ["## Avisos", "", "nenhum."]

    if report.get("notes"):
        lines += ["", "## Observações", ""] + [f"- {n}" for n in report["notes"]]
    return "\n".join(lines) + "\n"


def render_terminal(report: dict) -> str:
    rows = report["fields"]
    width = max(len(r["name"]) for r in rows) + 2
    kinds = max(len(r["kind"]) for r in rows) + 2
    out = [
        f"{report.get('project') or 'board'} · {report['total']} itens · "
        f"{report['milestones']['total']} milestones ({report['milestones']['semDueOn']} sem dueOn)",
        "",
    ]
    for row in rows:
        if not row["collected"]:
            out.append(f"{row['name']:<{width}}{row['kind']:<{kinds}}{'—  não coletado':>12}")
            continue
        flag = "*" if row["required"] else " "
        out.append(
            f"{row['name']:<{width}}{row['kind']:<{kinds}}"
            f"{row['filled']:>3}/{row['total']:<3} {_bar(row['pct'])} {row['pct']:>4.0f}%{flag}"
        )
    out.append("")
    out.append("* obrigatório — a falta gera aviso")
    if report["warnings"]:
        out += ["", "avisos:"] + [f"  - {w}" for w in report["warnings"]]
    if report.get("notes"):
        out += ["", "observações:"] + [f"  - {n}" for n in report["notes"]]
    return "\n".join(out)


def _bar(pct: float, size: int = 10) -> str:
    filled = round(pct / 100 * size)
    return "█" * filled + "░" * (size - filled)


def write(report: dict, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md, js = out_dir / "report.md", out_dir / "report.json"
    md.write_text(render_markdown(report), encoding="utf-8")
    js.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"markdown": md, "json": js}
