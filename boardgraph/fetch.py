"""Fase 1 — obtenção de dados brutos do GitHub Project.

Responsabilidade única: config → JSON cru + metadados. Não normaliza, não
infere datas, não decide layout. Se algo der errado, o payload fica intacto
para inspeção.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .client import GraphQLClient, GraphQLError
from .queries import board_query


@dataclass
class FetchConfig:
    owner: str
    project_number: int
    filter: str | None = None
    page_size: int = 100
    max_pages: int = 20
    include_deps: bool = True
    include_body: bool = False
    transport: str = "auto"
    token: str | None = None
    out_dir: Path = Path("out")


@dataclass
class FetchResult:
    payload: dict
    meta: dict
    degraded: bool = False
    warnings: list[str] = field(default_factory=list)


def fetch_board(cfg: FetchConfig, client: GraphQLClient | None = None) -> FetchResult:
    client = client or GraphQLClient(transport=cfg.transport, token=cfg.token)

    started = time.monotonic()
    warnings: list[str] = []
    degraded = False
    include_deps = cfg.include_deps

    while True:
        try:
            payload = client.execute(
                board_query(include_deps=include_deps, include_body=cfg.include_body),
                {"owner": cfg.owner, "number": cfg.project_number, "cursor": None, "filter": cfg.filter},
            )
            break
        except GraphQLError as exc:
            if include_deps and _is_dependency_failure(exc):
                include_deps = False
                degraded = True
                warnings.append("campos de dependência (blockedBy/parent) indisponíveis — refeito sem eles")
                continue
            raise

    project = payload["organization"]["projectV2"]
    if project is None:
        raise RuntimeError(
            f"projeto {cfg.project_number} não encontrado em {cfg.owner} "
            "(confira owner/número e se o token enxerga o projeto)"
        )

    items = list(project["items"]["nodes"])
    page = 1
    info = project["items"]
    total = info["totalCount"]

    while info["pageInfo"]["hasNextPage"] and page < cfg.max_pages:
        page += 1
        payload = client.execute(
            board_query(include_deps=include_deps, include_body=cfg.include_body),
            {
                "owner": cfg.owner,
                "number": cfg.project_number,
                "cursor": info["pageInfo"]["endCursor"],
                "filter": cfg.filter,
            },
        )
        project = payload["organization"]["projectV2"]
        items.extend(project["items"]["nodes"])
        info = project["items"]

    if info["pageInfo"]["hasNextPage"]:
        warnings.append(f"parou em max_pages={cfg.max_pages}; ainda há páginas")

    rate = payload.get("rateLimit") or {}
    if isinstance(rate.get("remaining"), int) and rate["remaining"] < 100:
        warnings.append(f"rate limit baixo: {rate['remaining']} restantes")

    data = {
        "project": {
            "id": project.get("id"),
            "title": project.get("title"),
            "url": project.get("url"),
            "number": cfg.project_number,
            "owner": cfg.owner,
        },
        "fields": project["fields"]["nodes"],
        "items": items,
        "rateLimit": rate,
    }

    meta = {
        "fetchedAt": _now().isoformat(timespec="seconds"),
        "durationMs": int((time.monotonic() - started) * 1000),
        "owner": cfg.owner,
        "projectNumber": cfg.project_number,
        "projectTitle": project.get("title"),
        "filter": cfg.filter,
        "pages": page,
        "totalCount": total,
        "fetchedCount": len(items),
        "counts": _count_content(items),
        "degraded": degraded,
        "warnings": warnings,
    }

    return FetchResult(payload=data, meta=meta, degraded=degraded, warnings=warnings)


def save(result: FetchResult, out_dir: Path = Path("out")) -> dict[str, Path]:
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    paths = {"latest": raw_dir / "latest.json", "meta": raw_dir / "latest.meta.json"}
    paths["latest"].write_text(
        json.dumps(result.payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    paths["meta"].write_text(
        json.dumps(result.meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return paths


def load_latest(out_dir: Path = Path("out")) -> tuple[dict, dict]:
    raw_dir = out_dir / "raw"
    latest, meta = raw_dir / "latest.json", raw_dir / "latest.meta.json"
    if not latest.exists():
        raise FileNotFoundError(f"sem cache em {latest}; rode `boardgraph fetch` antes")
    return (
        json.loads(latest.read_text(encoding="utf-8")),
        json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {},
    )


def summarize(meta: dict) -> str:
    counts = meta.get("counts", {})
    parts = [f"{meta.get('fetchedCount', 0)} itens"]
    detail = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
    if detail:
        parts.append(f"({detail})")
    parts.append(f"páginas {meta.get('pages', '?')}/{meta.get('pages', '?')}")
    rate = (meta.get("rateLimit") or {}).get("remaining")
    if rate is not None:
        parts.append(f"rateLimit {rate}")
    if meta.get("degraded"):
        parts.append("[DEGRADED]")
    return " · ".join(parts)


def _count_content(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        content = item.get("content") or {}
        key = content.get("__typename") or "sem content"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _is_dependency_failure(exc: GraphQLError) -> bool:
    haystack = " ".join(str(e.get("path", "")) + e.get("message", "") for e in exc.errors)
    return any(token in haystack for token in ("blockedBy", "parent", "subIssues"))






def _now() -> datetime:
    return datetime.now(timezone.utc)
