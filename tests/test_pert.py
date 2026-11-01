"""CPM em redes pequenas conferidas à mão."""

from boardgraph.pert import calibrate, schedule


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


def test_team_herdado_do_pai():
    inherit = _node("o/r#2", likely=2)
    inherit["team"] = None
    board = {
        "nodes": [inherit],
        "items": [
            {"key": "o/r#2", "team": None, "parent": "o/r#1"},
            {"key": "o/r#1", "team": "Back", "parent": None},
        ],
    }
    result = schedule(board, _graph())

    assert result["tasks"][0]["team"] == "Back"


def test_milestone_vai_como_dict_nao_como_titulo():
    node = _node("o/r#1", likely=1)
    node["milestone"] = {"repo": "o/r", "number": 3, "title": "M3", "due_on": "2026-02-01"}
    result = schedule({"nodes": [node]}, _graph())

    assert result["tasks"][0]["milestone"]["number"] == 3


def test_milestone_ausente_e_none_nao_dict():
    result = schedule({"nodes": [_node("o/r#1", likely=1)]}, _graph())

    assert result["tasks"][0]["milestone"] is None


def test_estimativas_e_prazo_vao_para_a_tarefa():
    node = _node("o/r#1", likely=1)
    node.update({"optimistic": 0.7, "pessimistic": 1.6, "deadline": "2026-02-01"})
    result = schedule({"nodes": [node]}, _graph())
    task = result["tasks"][0]

    assert (task["optimistic"], task["likely"], task["pessimistic"]) == (0.7, 1.0, 1.6)
    assert task["deadline"] == "2026-02-01"


def test_contrato_da_tarefa_e_ordenacao():
    board = {"nodes": [_node("o/r#2", likely=1), _node("o/r#1", likely=1)]}
    result = schedule(board, _graph())
    task = result["tasks"][0]

    assert set(task) == {
        "key", "title", "team", "milestone", "optimistic", "likely", "pessimistic",
        "deadline", "component", "anchor", "duration", "duration_source",
        "te", "sigma", "sigma_path", "es", "ef", "ls", "lf",
        "planned_start", "planned_end", "start", "finish", "late_start",
        "late_finish", "slack", "critical", "probability",
    }
    assert [t["key"] for t in result["tasks"]] == ["o/r#1", "o/r#2"]
    assert task["slack"] is None


def test_estimativa_quebrada_arredonda_para_cima():
    board = {"nodes": [_node("o/r#1", likely=2.1), _node("o/r#2", likely=0.4)]}
    result = schedule(board, _graph())
    by = _by_key(result)

    assert by["o/r#1"]["duration"] == 3
    assert by["o/r#2"]["duration"] == 1


def test_te_e_sigma_vem_das_tres_estimativas():
    node = _node("o/r#1", start="2026-01-01")
    node.update({"optimistic": 1, "likely": 3, "pessimistic": 5})
    result = schedule({"nodes": [node]}, _graph())
    task = result["tasks"][0]

    assert task["te"] == 3.0
    assert round(task["sigma"], 4) == 0.6667


def test_datas_usam_te_nao_a_mais_provavel():
    def est(key):
        n = _node(key, start="2026-01-01")
        n.update({"optimistic": 1, "likely": 3, "pessimistic": 5})
        return n

    result = schedule({"nodes": [est("o/r#1"), est("o/r#2")]}, _graph(("o/r#1", "o/r#2")))
    tasks = _by_key(result)

    assert (tasks["o/r#1"]["start"], tasks["o/r#1"]["finish"]) == ("2026-01-01", "2026-01-03")
    assert (tasks["o/r#2"]["start"], tasks["o/r#2"]["finish"]) == ("2026-01-04", "2026-01-06")
    assert round(tasks["o/r#2"]["sigma_path"], 4) == 0.9428


def test_probabilidade_da_tarefa_contra_o_prazo():
    node = _node("o/r#1", start="2026-01-01")
    node.update({"optimistic": 1, "likely": 3, "pessimistic": 5, "deadline": "2026-01-04"})
    result = schedule({"nodes": [node]}, _graph())
    task = result["tasks"][0]

    # margin = 3 − 2.0 = 1.0; Z = 1.0 / (2/3) = 1.5; Φ(1.5) = 0.9332
    assert round(task["probability"], 4) == 0.9332


def test_probabilidade_do_milestone_usa_due_on():
    def est(key):
        n = _node(key, start="2026-01-01")
        n.update({"optimistic": 1, "likely": 3, "pessimistic": 5})
        n["milestone"] = {"repo": "o/r", "number": 3, "title": "M3", "due_on": "2026-01-08"}
        return n

    result = schedule({"nodes": [est("o/r#1"), est("o/r#2")]}, _graph())
    ms = result["probabilities"]["milestones"][0]

    assert (ms["repo"], ms["number"]) == ("o/r", 3)
    assert ms["source"] == "due_on"
    assert ms["probability"] > 0.999


def test_probabilidade_do_milestone_cai_no_prazo_sem_due_on():
    node = _node("o/r#1", start="2026-01-01")
    node.update({"optimistic": 1, "likely": 3, "pessimistic": 5, "deadline": "2026-01-04"})
    node["milestone"] = {"repo": "o/r", "number": 3, "title": "M3", "due_on": None}
    result = schedule({"nodes": [node]}, _graph())
    ms = result["probabilities"]["milestones"][0]

    assert ms["source"] == "prazo"
    assert round(ms["probability"], 4) == 0.9332


def test_probabilidade_do_projeto_e_produto_dos_componentes():
    def est(key):
        n = _node(key, start="2026-01-01")
        n.update({"optimistic": 1, "likely": 3, "pessimistic": 5})
        return n

    result = schedule({"nodes": [est("o/r#1"), est("o/r#2")]}, _graph(), deadline="2026-01-04")
    project = result["probabilities"]["project"]

    # cada componente: Φ(1.5) = 0.9332; projeto = 0.9332² ≈ 0.8708
    assert round(project["probability"], 4) == 0.8708
    assert project["expected_finish"] == "2026-01-03"


def test_probabilidade_degenerada_sem_o_m_p():
    node = _node("o/r#1", likely=2, start="2026-01-01")
    node["deadline"] = "2026-01-05"
    result = schedule({"nodes": [node]}, _graph())
    task = result["tasks"][0]

    assert task["probability"] == 1.0
    assert any("sem O/M/P" in w for w in result["warnings"])


def test_calibracao_mediana_do_real_sobre_planejado():
    items = [
        {"key": "o/r#1", "type": "issue", "start": "2026-01-01", "end": "2026-01-05",
         "end_source": "issue_field", "closed_at": "2026-01-09"},   # 9/5 = 1.8
        {"key": "o/r#2", "type": "issue", "start": "2026-01-01", "end": "2026-01-04",
         "end_source": "issue_field", "closed_at": "2026-01-02"},   # 2/4 = 0.5
        {"key": "o/r#3", "type": "issue", "start": "2026-01-01", "end": "2026-01-02",
         "end_source": "issue_field", "closed_at": "2026-01-02"},   # 2/2 = 1.0
        {"key": "o/r#4", "type": "issue", "start": "2026-01-01", "end": "2026-01-02",
         "end_source": "issue_field", "closed_at": None},           # ignorada
    ]
    result = calibrate({"items": items})

    assert result["fator_realidade"] == 1.0
    assert len(result["amostra"]) == 3
    assert result["ignoradas"] == ["o/r#4"]


def test_calibracao_sem_amostra_avisa():
    result = calibrate({"items": [{"key": "o/r#1", "type": "issue"}]})

    assert result["fator_realidade"] is None
    assert any("nenhuma tarefa" in w for w in result["warnings"])
