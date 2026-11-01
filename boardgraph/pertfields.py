"""Campos de estimativa (O/M/P) e Prazo: criação e semeadura.

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
from .fields import field_map, item_key, to_date

FIELD_SPECS = (("O", "NUMBER"), ("M", "NUMBER"), ("P", "NUMBER"), ("Prazo", "DATE"))
SEED_FACTORS = {"O": 0.7, "M": 1.0, "P": 1.6}
SEED_FIELDS = tuple(SEED_FACTORS)

CREATE_FIELD = """
mutation($projectId: ID!, $name: String!, $dataType: ProjectV2CustomFieldType!) {
  createProjectV2Field(input: {projectId: $projectId, name: $name, dataType: $dataType}) {
    projectV2Field { ... on ProjectV2FieldCommon { id name dataType } }
  }
}
"""

SET_VALUE = """
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $value: ProjectV2FieldValue!) {
  updateProjectV2ItemFieldValue(
    input: {projectId: $projectId, itemId: $itemId, fieldId: $fieldId, value: $value}
  ) { projectV2Item { id } }
}
"""


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
    campos. Item com qualquer um de O/M/P preenchido é respeitado e pulado.
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
        if isinstance(span, str):
            skipped.append(f"{key} ({span})")
            continue

        days, start, end = span
        rows.append(SeedRow(
            item_id=item.get("id") or "",
            key=key,
            start=start,
            end=end,
            days=days,
            values={name: round(days * factor, 1) for name, factor in SEED_FACTORS.items()},
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
    lines.append(f"  {'key':<{width}} {'start':<11} {'end':<11} {'M':>4} {'O':>5} {'P':>5}")
    for row in rows:
        lines.append(
            f"  {row.key:<{width}} {row.start:<11} {row.end:<11} "
            f"{row.days:>4} {row.values['O']:>5} {row.values['P']:>5}"
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
        data = client.execute(CREATE_FIELD, {
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
    """Semeia O/M/P em cada linha; devolve a quantidade de mutações."""
    count = 0
    for row in rows:
        for name in SEED_FIELDS:
            client.execute(SET_VALUE, {
                "projectId": project_id,
                "itemId": row.item_id,
                "fieldId": fields[name]["id"],
                "value": {"number": row.values[name]},
            })
            count += 1
    return count


def _span(start: object, end: object) -> tuple[int, str, str] | str:
    """(dias, start, end) ou o motivo de pular a semente."""
    s, e = to_date(start), to_date(end)
    if s is None or e is None:
        return "sem Start/Target"
    if e < s:
        return "Target antes de Start"
    return (e - s).days + 1, s.isoformat(), e.isoformat()
