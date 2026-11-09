"""Cronograma/Gantt do Project, com os nomes dos responsáveis."""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from .people import PeopleIndex

MONTHS_PT = (
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
)
TEAM_ORDER = ("Back", "Front", "Infra", "Real", "Gerência", "(sem time)")
TEAM_COLORS = {
    "Back": "#0969da",
    "Front": "#8250df",
    "Infra": "#bf8700",
    "Real": "#0f766e",
    "Gerência": "#475569",
    "(sem time)": "#6e7781",
}
STATUS_COLORS = {
    "Done": "#2da44e",
    "In progress": "#0969da",
    "Todo": "#bf8700",
}
OVERDUE = "#cf222e"


class TimelineError(ValueError):
    """Período ou dados inválidos para o cronograma."""


@dataclass
class Row:
    kind: str
    label: str
    start: date | None = None
    end: date | None = None
    status: str = ""
    group: str = ""
    overdue: bool = False


@dataclass
class TimelineData:
    rows: list[Row]
    items: int
    undated: int
    done: int
    doing: int
    todo: int
    overdue: int
    teams: dict[str, tuple[int, int]] = field(default_factory=dict)
    start: date | None = None
    end: date | None = None


def parse_range(
    month: str | None,
    date_from: str | None,
    date_to: str | None,
) -> tuple[date | None, date | None]:
    if month:
        if date_from or date_to:
            raise TimelineError("use --month ou --from/--to, não ambos")
        try:
            base = datetime.strptime(month, "%Y-%m").date()
        except ValueError:
            raise TimelineError("--month deve ser YYYY-MM") from None
        last = calendar.monthrange(base.year, base.month)[1]
        return date(base.year, base.month, 1), date(base.year, base.month, last)

    if bool(date_from) != bool(date_to):
        raise TimelineError("informe --from e --to juntos")
    if date_from and date_to:
        try:
            start = date.fromisoformat(date_from)
            end = date.fromisoformat(date_to)
        except ValueError:
            raise TimelineError("datas devem ser YYYY-MM-DD") from None
        if start > end:
            raise TimelineError("--from não pode ser maior que --to")
        return start, end
    return None, None


def select_items(
    board: dict,
    date_from: date | None,
    date_to: date | None,
    teams: list[str] | None,
    status: str,
) -> tuple[list[dict], int]:
    selected: list[dict] = []
    undated = 0
    wanted = {t for t in teams or [] if t}

    for raw in board.get("items") or []:
        if raw.get("type") not in ("issue", "pull_request"):
            continue

        team = raw.get("team") or "(sem time)"
        if wanted and team not in wanted:
            continue

        current = raw.get("status") or ""
        if status == "done" and current != "Done":
            continue
        if status == "open" and current == "Done":
            continue

        start, end = _item_dates(raw)
        if not start and not end:
            undated += 1
            continue
        start = start or end
        end = end or start
        if start > end:
            start, end = end, start
        if date_from and end < date_from:
            continue
        if date_to and start > date_to:
            continue

        item = dict(raw)
        item["_start"] = start
        item["_end"] = end
        selected.append(item)

    return selected, undated


def build_rows(
    items: list[dict],
    *,
    group_by: str,
    split_assignees: bool,
    people: PeopleIndex | None,
    name_style: str,
    show_login: bool,
) -> list[Row]:
    if group_by == "assignee":
        return _rows_by_assignee(items, people, name_style, show_login)
    if group_by not in ("team", "milestone"):
        raise TimelineError(f"agrupamento inválido: {group_by}")

    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        key = _group_key(item, group_by)
        groups[key].append(item)

    rows: list[Row] = []
    for key in _group_order(groups, group_by):
        group_items = groups[key]
        rows.append(Row("group", f"{key} · {len(group_items)}", group=key))
        for item in sorted(group_items, key=_sort_key):
            assignees = _unique(item.get("assignees") or [])
            if split_assignees and len(assignees) > 1:
                for login in assignees:
                    rows.append(
                        _task_row(item, people, name_style, show_login, only_login=login)
                    )
            else:
                rows.append(_task_row(item, people, name_style, show_login))
    return rows


def timeline_data(
    board: dict,
    *,
    date_from: date | None,
    date_to: date | None,
    teams: list[str] | None,
    status: str,
    group_by: str,
    split_assignees: bool,
    people: PeopleIndex | None,
    name_style: str,
    show_login: bool,
) -> TimelineData:
    items, undated = select_items(board, date_from, date_to, teams, status)
    if not items:
        raise TimelineError("nenhum item com data no período e filtros escolhidos")

    rows = build_rows(
        items,
        group_by=group_by,
        split_assignees=split_assignees,
        people=people,
        name_style=name_style,
        show_login=show_login,
    )
    done = sum(1 for i in items if i.get("status") == "Done")
    doing = sum(1 for i in items if i.get("status") == "In progress")
    todo = len(items) - done - doing
    today = date.today()
    overdue = sum(
        1
        for i in items
        if i.get("status") != "Done" and i["_end"] < today
    )
    teams_count: dict[str, tuple[int, int]] = {}
    for item in items:
        team = item.get("team") or "(sem time)"
        done_n, total_n = teams_count.get(team, (0, 0))
        teams_count[team] = (
            done_n + (1 if item.get("status") == "Done" else 0),
            total_n + 1,
        )

    return TimelineData(
        rows=rows,
        items=len(items),
        undated=undated,
        done=done,
        doing=doing,
        todo=todo,
        overdue=overdue,
        teams=teams_count,
        start=min(i["_start"] for i in items),
        end=max(i["_end"] for i in items),
    )


def render_timeline(
    board: dict,
    *,
    date_from: date | None,
    date_to: date | None,
    teams: list[str] | None,
    status: str,
    group_by: str,
    split_assignees: bool,
    people: PeopleIndex | None,
    name_style: str,
    show_login: bool,
    output: Path | None,
    fmt: str,
    title: str | None,
    out_dir: Path | None = None,
) -> dict:
    data = timeline_data(
        board,
        date_from=date_from,
        date_to=date_to,
        teams=teams,
        status=status,
        group_by=group_by,
        split_assignees=split_assignees,
        people=people,
        name_style=name_style,
        show_login=show_login,
    )

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.patches as mpatches
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
    except ImportError:
        raise TimelineError(
            "matplotlib não instalado; instale com `pip install matplotlib`"
        ) from None

    axis_from = date_from or data.start
    if date_to:
        axis_to = max(date_to, data.end or date_to)
        axis_to = min(axis_to, date_to + timedelta(days=7))
    else:
        axis_to = data.end
    if not axis_from or not axis_to:
        raise TimelineError("não foi possível determinar o período")
    crosses = bool(
        date_from and date_to
        and (data.start < date_from or data.end > date_to)
    )
    axis_from -= timedelta(days=1)
    axis_to += timedelta(days=1)

    rows = data.rows
    n = len(rows)
    row_h = 0.36 if n <= 70 else 0.30
    height = max(7.5, 3.4 + n * row_h)
    width = 18.0
    fig = plt.figure(figsize=(width, height), facecolor="white")
    ax = fig.add_axes([0.34, 0.07, 0.63, 0.80])
    ax.set_facecolor("white")

    label = title or _default_title(date_from, date_to, data)
    project = (board.get("project") or {}).get("title") or "Project"
    fig.text(
        0.03, 0.975, label,
        fontsize=20, fontweight="bold", color="#0f172a", va="top",
    )
    subtitle = (
        f"Fonte: {project} · {axis_from + timedelta(days=1):%d/%m/%Y} a "
        f"{axis_to - timedelta(days=1):%d/%m/%Y} · gerado em {date.today():%d/%m/%Y}"
    )
    if crosses:
        subtitle += " · inclui itens que cruzam o mês"
    fig.text(0.03, 0.944, subtitle, fontsize=9, color="#475569", va="top")
    fig.text(
        0.03, 0.917,
        f"Total {data.items} · Done {data.done} · In progress {data.doing} · "
        f"Todo {data.todo} · Atrasados {data.overdue} · Sem data {data.undated}",
        fontsize=9.5, color="#334155", va="top",
    )
    team_line = " · ".join(
        f"{team} {done}/{total}"
        for team, (done, total) in _ordered_teams(data.teams)
    )
    fig.text(0.03, 0.894, team_line, fontsize=8.5, color="#64748b", va="top")

    y_positions = list(range(n - 1, -1, -1))
    for y, row in zip(y_positions, rows):
        if row.kind == "group":
            color = TEAM_COLORS.get(row.group, "#94a3b8")
            ax.axhspan(y - 0.5, y + 0.5, color=color, alpha=0.09, zorder=0)
            continue
        start = mdates.date2num(row.start)
        end = mdates.date2num(row.end)
        width_days = max(end - start, 0.5)
        color = STATUS_COLORS.get(row.status or "", "#94a3b8")
        edge = OVERDUE if row.overdue else color
        ax.barh(
            y,
            width_days,
            left=start,
            height=0.55,
            color=color,
            edgecolor=edge,
            linewidth=1.1 if row.overdue else 0.6,
            hatch="//" if row.overdue else None,
            zorder=3,
        )

    ax.set_yticks(y_positions)
    ax.set_yticklabels([row.label for row in rows], fontsize=8, color="#0f172a")
    for tick, row in zip(ax.get_yticklabels(), rows):
        if row.kind == "group":
            tick.set_fontweight("bold")
            tick.set_fontsize(9)
            tick.set_color(TEAM_COLORS.get(row.group, "#334155"))
    ax.set_ylim(-0.6, n - 0.4)
    ax.set_xlim(mdates.date2num(axis_from), mdates.date2num(axis_to))
    ax.xaxis_date()
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    ax.xaxis.set_minor_locator(mdates.DayLocator())
    ax.grid(axis="x", which="major", color="#cbd5e1", linewidth=0.8, alpha=0.8, zorder=0)
    ax.grid(axis="x", which="minor", color="#e2e8f0", linewidth=0.35, alpha=0.6, zorder=0)
    ax.tick_params(axis="x", labelsize=8, colors="#475569")
    ax.tick_params(axis="y", length=0, pad=8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#cbd5e1")

    milestones_in_range: list[date] = []
    for milestone in board.get("milestones") or []:
        due = _date(milestone.get("due_on"))
        if not due or not (axis_from <= due <= axis_to):
            continue
        x = mdates.date2num(due)
        ax.axvline(
            x, color="#bf8700", linestyle=(0, (4, 3)),
            linewidth=1.0, alpha=0.85, zorder=2,
        )
        milestones_in_range.append(due)

    if milestones_in_range:
        milestones_in_range.sort()
        shown = milestones_in_range[:6]
        text = "Marcos: " + " · ".join(f"{due:%d/%m}" for due in shown)
        if len(milestones_in_range) > len(shown):
            text += f" +{len(milestones_in_range) - len(shown)}"
        fig.text(
            0.98, 0.018, text, ha="right", va="bottom",
            fontsize=7.5, color="#92400e",
        )

    handles = [
        mpatches.Patch(color=STATUS_COLORS["Done"], label="Done"),
        mpatches.Patch(color=STATUS_COLORS["In progress"], label="In progress"),
        mpatches.Patch(color=STATUS_COLORS["Todo"], label="Todo"),
        mpatches.Patch(
            facecolor="white", edgecolor=OVERDUE, hatch="//", label="Atrasado",
        ),
        Line2D(
            [0], [0], color="#bf8700", linestyle=(0, (4, 3)), label="Milestone",
        ),
    ]
    fig.legend(
        handles=handles, loc="lower left", bbox_to_anchor=(0.34, 0.005),
        ncol=5, frameon=False, fontsize=8,
    )

    output = Path(output) if output else (Path(out_dir) if out_dir else Path("out")) / f"timeline-{_slug(date_from, date_to)}"
    output.parent.mkdir(parents=True, exist_ok=True)
    formats = ["png", "svg", "pdf"] if fmt == "all" else [fmt]
    paths: list[str] = []
    for current in formats:
        target = output if output.suffix == f".{current}" else output.with_suffix(f".{current}")
        fig.savefig(target, dpi=160, bbox_inches="tight", facecolor="white")
        paths.append(str(target))
    plt.close(fig)

    return {
        "paths": paths,
        "data": data,
        "label": label,
        "axis_from": axis_from + timedelta(days=1),
        "axis_to": axis_to - timedelta(days=1),
    }


def _item_dates(item: dict) -> tuple[date | None, date | None]:
    start = _date(item.get("start")) or _date(item.get("created_at"))
    end = _date(item.get("end")) or _date(item.get("closed_at"))
    return start, end


def _date(value) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _group_key(item: dict, group_by: str) -> str:
    if group_by == "team":
        return item.get("team") or "(sem time)"
    ms = item.get("milestone") or {}
    return ms.get("title") or "(sem milestone)"


def _group_order(groups: dict[str, list[dict]], group_by: str) -> list[str]:
    if group_by == "team":
        known = [team for team in TEAM_ORDER if team in groups]
        extra = sorted(team for team in groups if team not in TEAM_ORDER)
        return known + extra
    return sorted(groups, key=str.lower)


def _rows_by_assignee(
    items: list[dict],
    people: PeopleIndex | None,
    name_style: str,
    show_login: bool,
) -> list[Row]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        assignees = _unique(item.get("assignees") or [])
        if not assignees:
            groups["__none__"].append(item)
        else:
            for login in assignees:
                groups[login.lower()].append(item)

    rows: list[Row] = []
    labels = {
        key: ("Sem responsável" if key == "__none__"
              else _person_label(key, people, name_style, show_login))
        for key in groups
    }
    for key in sorted(groups, key=lambda value: labels[value].lower()):
        rows.append(Row("group", f"{labels[key]} · {len(groups[key])}", group=labels[key]))
        for item in sorted(groups[key], key=_sort_key):
            only = None if key == "__none__" else key
            rows.append(
                _task_row(
                    item, people, name_style, show_login,
                    only_login=only, include_names=False,
                )
            )
    return rows


def _task_row(
    item: dict,
    people: PeopleIndex | None,
    name_style: str,
    show_login: bool,
    only_login: str | None = None,
    include_names: bool = True,
) -> Row:
    title = _clip(item.get("title") or "", 78)
    names = ""
    if include_names:
        logins = [only_login] if only_login else _unique(item.get("assignees") or [])
        names = format_names(logins, people, name_style, show_login)
    label = f"{title}\n{names}" if names else title
    end = item["_end"]
    status = item.get("status") or ""
    return Row(
        kind="task",
        label=label,
        start=item["_start"],
        end=end,
        status=status,
        group="",
        overdue=status != "Done" and end < date.today(),
    )


def format_names(
    logins,
    people: PeopleIndex | None,
    style: str,
    show_login: bool,
    limit: int = 2,
) -> str:
    seen: set[str] = set()
    names: list[str] = []
    for login in logins or ():
        key = str(login).strip().lstrip("@").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        person = people.resolve(login) if people is not None else None
        if person is None:
            names.append(f"@{str(login).lstrip('@')}")
            continue
        name = person.name if style == "full" else (person.short or person.name)
        if show_login:
            name = f"{name} (@{person.login})"
        names.append(name)
    if not names:
        return "Sem responsável"
    if len(names) <= limit:
        return ", ".join(names)
    return ", ".join(names[:limit]) + f" +{len(names) - limit}"


def _person_label(
    login: str,
    people: PeopleIndex | None,
    style: str,
    show_login: bool,
) -> str:
    person = people.resolve(login) if people is not None else None
    if person is None:
        return f"@{login}"
    name = person.name if style == "full" else (person.short or person.name)
    return f"{name} (@{person.login})" if show_login else name


def _unique(values) -> list[str]:
    return list(dict.fromkeys(str(v) for v in values or () if v))


def _sort_key(item: dict) -> tuple:
    return (item["_start"], item.get("title") or "")


def _ordered_teams(teams: dict[str, tuple[int, int]]) -> list[tuple[str, tuple[int, int]]]:
    known = [(team, teams[team]) for team in TEAM_ORDER if team in teams]
    extra = sorted((team, value) for team, value in teams.items() if team not in TEAM_ORDER)
    return known + extra


def _default_title(
    date_from: date | None,
    date_to: date | None,
    data: TimelineData,
) -> str:
    if date_from and date_to and (date_from.year, date_from.month) == (date_to.year, date_to.month):
        return f"Cronograma — {MONTHS_PT[date_from.month - 1]}/{date_from.year}"
    start = date_from or data.start
    end = date_to or data.end
    if start and end:
        return f"Cronograma — {start:%d/%m/%Y} a {end:%d/%m/%Y}"
    return "Cronograma"


def _slug(date_from: date | None, date_to: date | None) -> str:
    if date_from and date_to and (date_from.year, date_from.month) == (date_to.year, date_to.month):
        return f"{date_from.year:04d}-{date_from.month:02d}"
    if date_from and date_to:
        return f"{date_from.isoformat()}--{date_to.isoformat()}"
    return "periodo"


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
