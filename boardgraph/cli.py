"""CLI do boardgraph."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .auth import AuthError
from .client import GraphQLError, GraphQLClient
from .fields import to_date
from .fetch import FetchConfig, fetch_board, save, summarize
from .graph import build_graph, render_terminal as render_graph
from .model import build_board, filter_detail, finalize, render_terminal
from .render import render_mermaid
from .team import filter_team
from .dot import render_dot
from .pertfields import (
    apply_seed,
    create_missing,
    existing_fields,
    missing_fields,
    plan_seed,
    render_dryrun,
)
from .pert import calibrate as pert_calibrate
from .pert import render_markdown, schedule as pert_schedule
from .probe import build_report, write
from .probe import render_terminal as render_probe


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="boardgraph",
        description="Lê um GitHub Project v2 e gera um grafo de dependências.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="baixa os dados brutos do board")
    _common(fetch)
    fetch.add_argument("--filter", help='filter syntax do Projects, ex: \'updated:>=2026-10-01\'')
    fetch.add_argument("--no-deps", action="store_true", help="não pedir blockedBy/parent")
    fetch.add_argument("--with-body", action="store_true", help="incluir body das issues (payload +20%%)")
    fetch.add_argument("--max-pages", type=int, default=20)
    fetch.add_argument("--transport", choices=["auto", "gh", "http"], default="auto")
    fetch.add_argument("--token", help="token explícito (senão usa env ou `gh auth token`)")
    fetch.add_argument("--json", action="store_true", help="imprime o meta em JSON")

    probe = sub.add_parser("probe", help="relatório de cobertura dos campos (offline)")
    probe.add_argument("--out", type=Path, default=Path("out"), help="diretório de saída")
    probe.add_argument("--input", type=Path, help="payload alternativo (padrão: out/raw/latest.json)")
    probe.add_argument("--json", action="store_true", help="imprime o relatório em JSON")
    probe.add_argument("--strict", action="store_true", help="sai com código 1 se houver aviso")

    model = sub.add_parser("model", help="normaliza e filtra o board (offline)")
    model.add_argument("--out", type=Path, default=Path("out"), help="diretório de saída")
    model.add_argument("--input", type=Path, help="payload alternativo (padrão: out/raw/latest.json)")
    model.add_argument("--detail", choices=["parents", "children", "all"], default="parents")
    model.add_argument("--team", action="append", help="recorta por time (repetível)")
    model.add_argument("--json", action="store_true", help="imprime o board em JSON")

    render = sub.add_parser("render", help="gera o diagrama (offline)")
    render.add_argument("--out", type=Path, default=Path("out"), help="diretório de saída")
    render.add_argument("--input", type=Path, help="payload alternativo (padrão: out/raw/latest.json)")
    render.add_argument("--detail", choices=["parents", "children", "all"], default="parents")
    render.add_argument("--team", action="append", help="recorta por time (repetível)")
    render.add_argument("--group-by", choices=["milestone", "team"], default="milestone")
    render.add_argument("--format", choices=["mmd", "dot", "svg", "pdf"], default="mmd")
    render.add_argument("--theme", choices=["light", "dark"], default="light")
    render.add_argument("--style", choices=["normal", "critical"], default="normal",
                        help="destaca o caminho crítico (vermelho)")
    render.add_argument("--print", action="store_true", help="imprime o Mermaid no terminal")

    sched = sub.add_parser("schedule", help="PERT/CPM: pert.md + pert.json (offline)")
    sched.add_argument("--out", type=Path, default=Path("out"), help="diretório de saída")
    sched.add_argument("--input", type=Path, help="payload alternativo (padrão: out/raw/latest.json)")
    sched.add_argument("--detail", choices=["parents", "children", "all"], default="parents")
    sched.add_argument("--team", action="append", help="recorta por time (repetível)")
    sched.add_argument("--deadline", help="prazo global do projeto (AAAA-MM-DD)")
    sched.add_argument("--json", action="store_true", help="imprime o cronograma em JSON")

    fields = sub.add_parser(
        "fields",
        help="cria e semeia os campos de estimativa + Prazo (dry-run por padrão)",
    )
    fields.add_argument("--out", type=Path, default=Path("out"), help="diretório de saída")
    fields.add_argument("--input", type=Path, help="payload alternativo (padrão: out/raw/latest.json)")
    fields.add_argument("--execute", action="store_true", help="executa as mutações (padrão: só lista)")

    return parser


def _normalize_argv(argv: list[str]) -> list[str]:
    """`--filter -status:Done` chega como opção; junta em `--filter=-status:Done`."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--filter" and i + 1 < len(argv) and argv[i + 1].startswith("-"):
            out.append(f"--filter={argv[i + 1]}")
            i += 2
            continue
        out.append(argv[i])
        i += 1
    return out


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--owner", required=True, help="org ou usuário dono do projeto")
    parser.add_argument("--project", type=int, required=True, help="número do projeto")
    parser.add_argument("--out", type=Path, default=Path("out"), help="diretório de saída")


def main(argv: list[str] | None = None) -> int:
    argv = _normalize_argv(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    try:
        if args.command == "fetch":
            return _cmd_fetch(args)
        if args.command == "probe":
            return _cmd_probe(args)
        if args.command == "model":
            return _cmd_model(args)
        if args.command == "render":
            return _cmd_render(args)
        if args.command == "fields":
            return _cmd_fields(args)
        if args.command == "schedule":
            return _cmd_schedule(args)
    except AuthError as exc:
        print(f"erro de autenticação: {exc}", file=sys.stderr)
        return 2
    except GraphQLError as exc:
        hint = ""
        if args.command == "fields":
            hint = "\ndica: mutação exige escopo de escrita (gh auth refresh -s project)"
        elif exc.hint_missing_scope:
            hint = "\ndica: token sem escopo `read:project` (gh auth refresh -s read:project)"
        print(f"erro GraphQL: {exc}{hint}", file=sys.stderr)
        return 3
    except (RuntimeError, FileNotFoundError, ValueError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 1


def _cmd_fetch(args: argparse.Namespace) -> int:
    cfg = FetchConfig(
        owner=args.owner,
        project_number=args.project,
        filter=args.filter,
        include_deps=not args.no_deps,
        include_body=args.with_body,
        max_pages=args.max_pages,
        transport=args.transport,
        token=args.token,
        out_dir=args.out,
    )
    result = fetch_board(cfg)
    paths = save(result, args.out)

    if args.json:
        print(json.dumps(result.meta, ensure_ascii=False, indent=2))
    else:
        print(f"ok · {summarize(result.meta)}")
        for warning in result.warnings:
            print(f"  aviso: {warning}")
        for name, path in paths.items():
            print(f"  {path}  ({name})")
    return 0


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


def _apply_filters(payload: dict, detail: str, teams: list[str] | None) -> dict:
    board = build_board(payload)
    board = filter_detail(board, detail)
    if teams:
        board = filter_team(board, teams)
    return finalize(board)


def _stem_label(detail: str, teams: list[str] | None, group_by: str) -> str:
    label = detail
    if teams:
        label += "-team-" + "-".join(_slug(t) for t in teams)
    if group_by == "team":
        label += "-by-team"
    return label


def _cmd_render(args: argparse.Namespace) -> int:
    source = args.input or (args.out / "raw" / "latest.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    board = _apply_filters(payload, args.detail, args.team)
    graph = build_graph(board)

    critical: set[str] = set()
    if args.style == "critical":
        critical = set(pert_schedule(board, graph)["critical"])

    label = _stem_label(args.detail, args.team, args.group_by)
    if args.style == "critical":
        label += "-critical"
    stem = args.out / f"graph-{label}"
    edges_path = args.out / f"edges-{label}.json"
    edges_path.parent.mkdir(parents=True, exist_ok=True)
    edges_path.write_text(
        json.dumps(
            {
                "view": graph["detail"],
                "detail": graph["detail"],
                "teams": board.get("teams"),
                "group_by": args.group_by,
                "counts": graph["counts"],
                "ghosts": graph["ghosts"],
                "edges": graph["edges"],
                "isolated": graph["isolated"],
                "cycles": graph["cycles"],
                "warnings": graph["warnings"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"{label:<9} {render_graph(graph)}")
    for warning in board["warnings"]:
        print(f"          aviso: {warning}")

    mermaid = render_mermaid(board, graph, args.group_by, critical or None)
    dot_src = render_dot(board, graph, args.group_by, args.theme, critical or None)

    for line in _emit(mermaid=mermaid, dot=dot_src, stem=stem, fmt=args.format):
        print(f"          {line}")
    print(f"          {edges_path}")
    if args.print:
        print(mermaid)
    return 0


def _emit(mermaid: str, dot: str, stem, fmt: str) -> list[str]:
    if fmt == "mmd":
        path = stem.with_suffix(".mmd")
        path.write_text(mermaid, encoding="utf-8")
        return [str(path)]

    dot_path = stem.with_suffix(".dot")
    dot_path.write_text(dot, encoding="utf-8")
    if fmt == "dot":
        return [str(dot_path)]

    out_path = stem.with_suffix(f".{fmt}")
    try:
        proc = subprocess.run(
            ["dot", f"-T{fmt}", "-o", str(out_path)],
            input=dot,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("graphviz não encontrado — instale com `apt install graphviz`") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"dot falhou: {proc.stderr.strip()[:300]}")
    return [str(dot_path), str(out_path)]


def _cmd_model(args: argparse.Namespace) -> int:
    source = args.input or (args.out / "raw" / "latest.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    board = _apply_filters(payload, args.detail, args.team)
    path = args.out / "board.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(board, ensure_ascii=False, indent=2))
    else:
        print(render_terminal(board))
        print(f"\n  {path}")
    return 0


def _cmd_schedule(args: argparse.Namespace) -> int:
    source = args.input or (args.out / "raw" / "latest.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    board = _apply_filters(payload, args.detail, args.team)
    graph = build_graph(board)
    result = pert_schedule(board, graph, deadline=args.deadline)
    calibration = pert_calibrate(board)

    args.out.mkdir(parents=True, exist_ok=True)
    md_path = args.out / "pert.md"
    json_path = args.out / "pert.json"
    md_path.write_text(render_markdown(board, result, calibration), encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "generatedAt": board.get("generatedAt"),
                "detail": board.get("detail"),
                "teams": board.get("teams"),
                "schedule": result,
                "calibration": calibration,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        project = result["probabilities"]["project"]
        print(
            f"schedule · fim {result['finish'] or '—'} · {len(result['critical'])} críticas"
            f" · {len(result['components'])} componentes"
        )
        if project and project["probability"] is not None:
            print(f"          P(projeto ≤ {project['deadline']}) = {project['probability']:.3f}")
        for warning in result["warnings"]:
            print(f"          aviso: {warning}")
        print(f"          {md_path}")
        print(f"          {json_path}")
    return 0


def _cmd_fields(args: argparse.Namespace) -> int:
    source = args.input or (args.out / "raw" / "latest.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    rows, skipped, filled = plan_seed(payload)
    missing = missing_fields(payload)
    print(render_dryrun(rows, skipped, filled, missing))

    if not args.execute:
        print("\ndry-run: nada foi alterado. Rode com --execute para aplicar.")
        return 0

    project_id = (payload.get("project") or {}).get("id")
    if not project_id:
        raise RuntimeError(f"payload sem project.id em {source}; rode `boardgraph fetch` de novo")

    client = GraphQLClient()
    created = create_missing(client, project_id, missing)
    fields = {**existing_fields(payload), **created}
    count = apply_seed(client, project_id, rows, fields)
    print(f"\nok · {len(created)} campos criados · {count} valores semeados ({len(rows)} itens)")
    return 0


def _cmd_probe(args: argparse.Namespace) -> int:
    source = args.input or (args.out / "raw" / "latest.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    report = build_report(payload, source=str(source))
    paths = write(report, args.out)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_probe(report))
        print()
        for name, path in paths.items():
            print(f"  {path}  ({name})")

    if args.strict and report["warnings"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
