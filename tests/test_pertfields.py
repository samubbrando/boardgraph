"""Semente O/M/P: dias inclusivos, pulos e não-sobrescrita."""

from boardgraph.pertfields import missing_fields, plan_seed, render_dryrun


def _value(name, value):
    return {"issueFieldValue": {"value": value, "field": {"name": name}}}


def _item(number, values=None, typename="Issue", **content):
    content = {
        "__typename": typename,
        "number": number,
        "title": f"t{number}",
        "repository": {"nameWithOwner": "org/repo"},
        **content,
    }
    return {"id": f"i{number}", "fieldValues": {"nodes": values or []}, "content": content}


def _payload(*items):
    return {"project": {"id": "PVT_1"}, "fields": [], "items": list(items)}


def test_semeadura_usa_dias_inclusivos():
    item = _item(1, [_value("Start date", "2026-10-05"), _value("Target date", "2026-10-07")])
    rows, skipped, filled = plan_seed(_payload(item))

    row = rows[0]
    assert row.days == 3
    assert row.values == {"O": 2.1, "M": 3.0, "P": 4.8}
    assert row.item_id == "i1"


def test_tarefa_de_um_dia():
    item = _item(1, [_value("Start date", "2026-10-05"), _value("Target date", "2026-10-05")])
    rows, _, _ = plan_seed(_payload(item))

    assert rows[0].days == 1


def test_sem_datas_nao_semeia():
    rows, skipped, _ = plan_seed(_payload(_item(1)))

    assert rows == []
    assert skipped == ["org/repo#1 (sem Start/Target)"]


def test_target_antes_de_start_nao_semeia():
    values = [_value("Start date", "2026-10-07"), _value("Target date", "2026-10-05")]
    rows, skipped, _ = plan_seed(_payload(_item(1, values)))

    assert rows == []
    assert skipped == ["org/repo#1 (Target antes de Start)"]


def test_valor_humano_nao_e_sobrescrito():
    values = [
        _value("Start date", "2026-10-05"),
        _value("Target date", "2026-10-07"),
        _value("O", 2.0),
    ]
    rows, skipped, filled = plan_seed(_payload(_item(1, values)))

    assert rows == [] and skipped == []
    assert filled == ["org/repo#1"]


def test_prs_e_drafts_ficam_de_fora():
    pr = _item(2, typename="PullRequest")
    draft = _item(3, typename="DraftIssue")
    rows, skipped, filled = plan_seed(_payload(pr, draft))

    assert (rows, skipped, filled) == ([], [], [])


def test_campos_a_criar():
    payload = {"fields": [{"name": "O", "id": "f1", "dataType": "NUMBER"}]}

    assert missing_fields(payload) == [
        ("M", "NUMBER"),
        ("P", "NUMBER"),
        ("Prazo", "DATE"),
    ]


def test_dryrun_mostra_resumo():
    item = _item(1, [_value("Start date", "2026-10-05"), _value("Target date", "2026-10-07")])
    rows, skipped, filled = plan_seed(_payload(item))
    out = render_dryrun(rows, skipped, filled, [("O", "NUMBER")])

    assert "O" in out and "NUMBER" in out
    assert "org/repo#1" in out and "semeadura" in out
