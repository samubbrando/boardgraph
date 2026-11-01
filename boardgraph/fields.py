"""Leitura de `fieldValues` — o board usa dois formatos.

1. Campo de projeto clássico: `{"date": ...|"number": ...|"name": ..., "field": {...}}`
2. Issue field (Start/Target date neste board):
   `{"issueFieldValue": {"value": ..., "field": {...}}}`

Quem só trata o formato 1 recebe `None` silencioso nas datas. Toda leitura
de campo passa por aqui.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

_VALUE_KEYS = ("date", "text", "number", "name", "title")


def to_date(value: object) -> date | None:
    """Parse tolerante: aceita date, datetime ou string ISO."""
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def to_iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def split_value(node: dict) -> tuple[str | None, Any]:
    """Devolve (nome do campo, valor) de um nó de `fieldValues`."""
    if "issueFieldValue" in node:
        inner = node.get("issueFieldValue") or {}
        field = inner.get("field") or {}
        return field.get("name"), inner.get("value")

    field = node.get("field") or {}
    for key in _VALUE_KEYS:
        if key in node and node[key] is not None:
            return field.get("name"), node[key]
    return field.get("name"), None


def field_map(item: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for node in ((item.get("fieldValues") or {}).get("nodes") or []):
        name, value = split_value(node)
        if name:
            out[name] = value
    return out


def item_key(item: dict) -> str:
    content = item.get("content") or {}
    repo = (content.get("repository") or {}).get("nameWithOwner")
    number = content.get("number")
    if repo and number is not None:
        return f"{repo}#{number}"
    if content.get("title"):
        return f"draft:{content['title'][:24]}"
    return f"item:{item.get('id', '?')[:12]}"
