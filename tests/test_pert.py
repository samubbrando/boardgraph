"""CPM em redes pequenas conferidas à mão."""

from boardgraph.pert import schedule


def _node(key, start="2026-01-01", end=None, likely=None):
    return {
        "key": key,
        "title": key,
        "team": "T",
        "milestone": None,
        "start": start,
        "end": end,
        "likely": likely,
    }


def _graph(*edges, external=(), cycles=()):
    deps = [{"from": a, "to": b, "kind": "dependency"} for a, b in edges]
    deps += [
        {"from": a, "to": b, "kind": "dependency", "external": True}
        for a, b in external
    ]
    return {"edges": deps, "cycles": [list(c) for c in cycles]}


def _by_key(result):
    return {t["key"]: t for t in result["tasks"]}


def test_cadeia_simples_passa_direto_e_regressivo():
    board = {"nodes": [_node("A", likely=3), _node("B", likely=2), _node("C", likely=4)]}
    result = schedule(board, _graph(("A", "B"), ("B", "C")))
    tasks = _by_key(result)

    assert (tasks["A"]["start"], tasks["A"]["finish"]) == ("2026-01-01", "2026-01-03")
    assert (tasks["B"]["start"], tasks["B"]["finish"]) == ("2026-01-04", "2026-01-05")
    assert (tasks["C"]["start"], tasks["C"]["finish"]) == ("2026-01-06", "2026-01-09")
    assert [tasks[k]["slack"] for k in "ABC"] == [0, 0, 0]
    assert result["critical"] == ["A", "B", "C"]
    assert result["components"][0]["critical_path"] == ["A", "B", "C"]
    assert result["finish"] == "2026-01-09"


def test_cadeias_paralelas_ganham_folga():
    board = {"nodes": [
        _node("S", likely=1),
        _node("A", likely=3), _node("B", likely=2),
        _node("C", likely=1), _node("D", likely=3),
    ]}
    result = schedule(board, _graph(("S", "A"), ("S", "C"), ("A", "B"), ("C", "D")))
    tasks = _by_key(result)

    assert (tasks["A"]["start"], tasks["A"]["finish"]) == ("2026-01-02", "2026-01-04")
    assert (tasks["B"]["start"], tasks["B"]["finish"]) == ("2026-01-05", "2026-01-06")
    assert (tasks["C"]["start"], tasks["C"]["finish"]) == ("2026-01-02", "2026-01-02")
    assert (tasks["D"]["start"], tasks["D"]["finish"]) == ("2026-01-03", "2026-01-05")
    assert (tasks["C"]["slack"], tasks["D"]["slack"]) == (1, 1)
    assert result["critical"] == ["A", "B", "S"]
    assert result["components"][0]["critical_path"] == ["S", "A", "B"]


def test_isolado_nao_tem_folga_finita():
    board = {"nodes": [_node("X", likely=2)]}
    result = schedule(board, _graph())

    task = result["tasks"][0]
    assert (task["start"], task["finish"]) == ("2026-01-01", "2026-01-02")
    assert task["slack"] is None
    assert task["critical"] is False
    assert result["critical"] == []


def test_sem_estimativa_usa_janela():
    board = {"nodes": [_node("W", start="2026-01-01", end="2026-01-05")]}
    result = schedule(board, _graph())

    task = result["tasks"][0]
    assert task["duration"] == 5
    assert task["duration_source"] == "janela"
    assert task["finish"] == "2026-01-05"
    assert any("janela" in w for w in result["warnings"])


def test_sem_datas_nem_estimativa_vira_zero():
    board = {"nodes": [_node("Z", start=None)]}
    result = schedule(board, _graph())

    task = result["tasks"][0]
    assert task["duration"] == 0
    assert task["duration_source"] == "zero"
    assert task["start"] is None and task["finish"] is None
    assert any("nem estimativa" in w for w in result["warnings"])


def test_dependencia_externa_nao_restringe():
    board = {"nodes": [_node("X", likely=2)]}
    result = schedule(board, _graph(external=[("fora#1", "X")]))

    assert result["tasks"][0]["slack"] is None
    assert any("fora do board" in w for w in result["warnings"])


def test_deadline_define_folga():
    board = {"nodes": [_node("A", likely=3), _node("B", likely=2)]}
    result = schedule(board, _graph(("A", "B")), deadline="2026-01-08")
    tasks = _by_key(result)

    assert (tasks["B"]["late_start"], tasks["B"]["late_finish"]) == ("2026-01-07", "2026-01-08")
    assert (tasks["A"]["slack"], tasks["B"]["slack"]) == (3, 3)
    assert result["critical"] == ["A", "B"]


def test_deadline_impossivel_gera_folga_negativa():
    board = {"nodes": [_node("A", likely=3), _node("B", likely=2)]}
    result = schedule(board, _graph(("A", "B")), deadline="2026-01-04")
    tasks = _by_key(result)

    assert (tasks["A"]["slack"], tasks["B"]["slack"]) == (-1, -1)
    assert any("anterior ao fim calculado" in w for w in result["warnings"])


def test_nos_em_ciclo_ficam_fora():
    board = {"nodes": [_node("A", likely=1), _node("B", likely=1), _node("C", likely=2)]}
    result = schedule(board, _graph(("A", "B"), cycles=[("A", "B")]))

    assert [t["key"] for t in result["tasks"]] == ["C"]
    assert any("ciclo" in w for w in result["warnings"])
