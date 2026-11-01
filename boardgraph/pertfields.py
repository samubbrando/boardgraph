"""Campos de estimativa (Otimista, Mais provável, Pessimista) e Prazo.

O PERT precisa de três estimativas por tarefa e elas não existem no board.
Este módulo cria os campos e semeia valores iniciais a partir do prazo
planejado:

    M = Target − Start + 1   (dias corridos, inclusivo)
    O = 0.7 × M
    P = 1.6 × M

A semente é um chute conservador para o grupo revisar — quem decide é o
humano. Valores já preenchidos nunca são sobrescritos. `Prazo` (DATE) é
compromisso e não recebe semente.
"""

from __future__ import annotations

from dataclasses import dataclass

from .client import GraphQLClient
from .fields import (
    FIELD_OTIMISTA,
    FIELD_PESSIMISTA,
    FIELD_PRAZO,
    FIELD_PROVAVEL,
    field_map,
    item_key,
    to_date,
)
from .queries import CREATE_PROJECT_FIELD, SET_ITEM_FIELD_VALUE

FIELD_SPECS = (
    (FIELD_OTIMISTA, "NUMBER"),
    (FIELD_PROVAVEL, "NUMBER"),
    (FIELD_PESSIMISTA, "NUMBER"),
    (FIELD_PRAZO, "DATE"),
)
SEED_FACTORS = {FIELD_OTIMISTA: 0.7, FIELD_PROVAVEL: 1.0, FIELD_PESSIMISTA: 1.6}
SEED_FIELDS = tuple(SEED_FACTORS)


@dataclass
class Span:
    days: int
    start: str
    end: str
    reason: str | None


@dataclass
class SeedRow:
    item_id: str
    key: str
    start: str
    end: str
    days: int
    values: dict[str, float]


def existing_fields(payload: dict) -> dict[str, dict]:
    """nome → {id, dataType} dos campos de projeto já existentes."""
    out: dict[str, dict] = {}
    for field in payload.get("fields") or []:
        name = field.get("name")
        if name:
            out[name] = {"id": field.get("id"), "dataType": field.get("dataType")}
    return out


def missing_fields(payload: dict) -> list[tuple[str, str]]:
    have = existing_fields(payload)
    return [(name, data_type) for name, data_type in FIELD_SPECS if name not in have]


def plan_seed(payload: dict) -> tuple[list[SeedRow], list[str], list[str]]:
    """(linhas a semear, sem semente, já preenchidos). Não muta nada.

    Só entram issues com Start e Target válidos. PRs e drafts não têm esses
    campos. Item com qualquer uma das três estimativas preenchida é pulado.
    """
    rows: list[SeedRow] = []
    skipped: list[str] = []
    filled: list[str] = []

    for item in payload.get("items") or []:
        content = item.get("content") or {}
        if content.get("__typename") != "Issue":
            continue
        key = item_key(item)
        current = field_map(item)
        if any(current.get(name) is not None for name in SEED_FIELDS):
            filled.append(key)
            continue

        span = _span(current.get("Start date"), current.get("Target date"))
        if span.reason:
            skipped.append(f"{key} ({span.reason})")
            continue

        rows.append(SeedRow(
            item_id=item.get("id") or "",
            key=key,
            start=span.start,
            end=span.end,
            days=span.days,
            values={name: round(span.days * factor, 1) for name, factor in SEED_FACTORS.items()},
        ))

    rows.sort(key=lambda r: r.key)
    return rows, skipped, filled


def render_dryrun(
    rows: list[SeedRow],
    skipped: list[str],
    filled: list[str],
    missing: list[tuple[str, str]],
) -> str:
    lines = ["campos a criar:" if missing else "campos: nada a criar"]
    lines += [f"  {name:<7} {data_type}" for name, data_type in missing]
    lines.append("")
    lines.append(f"semeadura (M=Target−Start+1, O=0.7M, P=1.6M) — {len(rows)} itens:")
    width = max((len(row.key) for row in rows), default=20)
    lines.append(
        f"  {'chave':<{width}} {'início':<11} {'fim':<11} {'dias':>4} {'otimista':>9} {'pessimista':>10}"
    )
    for row in rows:
        lines.append(
            f"  {row.key:<{width}} {row.start:<11} {row.end:<11} "
            f"{row.days:>4} {row.values[FIELD_OTIMISTA]:>9} {row.values[FIELD_PESSIMISTA]:>10}"
        )
    if filled:
        lines.append(f"\njá preenchidos, não sobrescreve: {len(filled)}")
        lines.append(f"  {', '.join(filled)}")
    if skipped:
        lines.append(f"\nsem semente: {len(skipped)}")
        lines.extend("  " + s for s in skipped)
    return "\n".join(lines)


def create_missing(
    client: GraphQLClient, project_id: str, missing: list[tuple[str, str]]
) -> dict[str, dict]:
    """Cria os campos ausentes e devolve nome → {id, dataType}."""
    created: dict[str, dict] = {}
    for name, data_type in missing:
        data = client.execute(CREATE_PROJECT_FIELD, {
            "projectId": project_id,
            "name": name,
            "dataType": data_type,
        })
        field = (data.get("createProjectV2Field") or {}).get("projectV2Field") or {}
        created[name] = {"id": field.get("id"), "dataType": field.get("dataType")}
    return created


def apply_seed(
    client: GraphQLClient, project_id: str, rows: list[SeedRow], fields: dict[str, dict]
) -> int:
    """Semeia as três estimativas em cada linha; devolve a quantidade de mutações."""
    count = 0
    for row in rows:
        for name in SEED_FIELDS:
            client.execute(SET_ITEM_FIELD_VALUE, {
                "projectId": project_id,
                "itemId": row.item_id,
                "fieldId": fields[name]["id"],
                "value": {"number": row.values[name]},
            })
            count += 1
    return count


def _span(start: object, end: object) -> Span:
    """Span válido ou, no campo `reason`, o motivo de pular a semente."""
    s, e = to_date(start), to_date(end)
    if s is None or e is None:
        return Span(0, "", "", "sem Start/Target")
    if e < s:
        return Span(0, "", "", "Target antes de Start")
    return Span((e - s).days + 1, s.isoformat(), e.isoformat(), None)
