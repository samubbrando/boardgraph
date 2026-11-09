# boardgraph

Lê um GitHub Project (v2) e gera grafos de dependência por milestone ou por
time, com janelas de tempo calculadas a partir das datas das próprias issues.

## Requisitos

- Python 3.10+
- [`gh`](https://cli.github.com/) autenticado com escopo `read:project`
- [Graphviz](https://graphviz.org/) apenas para `svg`/`pdf`
- `matplotlib` apenas para `timeline` (`pip install matplotlib`)

## Uso

```bash
python3 -m boardgraph fetch  --owner ORG --project 1
python3 -m boardgraph probe
python3 -m boardgraph model
python3 -m boardgraph render --detail parents --format pdf
```

Filtros: `--detail parents|children|all` e `--team` (repetível).
Render: `--group-by milestone|team`, `--format mmd|dot|svg|pdf`, `--theme light|dark`.

## Nomes dos responsáveis

O render pode mostrar o responsável de cada nó. Para isso, crie o arquivo
local `people-names.json` a partir do exemplo:

```bash
cp people-names.example.json people-names.json
```

Preencha `name`, `short`, `aliases` e, opcionalmente, `role`, `team` e
`manager`. O `people-names.json` é **ignorado pelo Git**; o exemplo versionado
é `people-names.example.json`.

```bash
python3 -m boardgraph render --show-assignees --assignee-format both --format pdf
```

- `--people PATH` aponta para outro arquivo.
- `--assignee-format name|login|both` escolhe o rótulo (padrão: `both`).
- `--strict-people` falha se algum assignee não estiver no arquivo.
- Login desconhecido aparece como `@login` e gera aviso.

## Cronograma/Gantt

O comando `timeline` gera um Gantt por mês ou intervalo, com os nomes
completos dos responsáveis e barras coloridas por status.

```bash
python3 -m boardgraph timeline --month 2026-10 --name-style full --format all
python3 -m boardgraph timeline --month 2026-11 --group-by assignee --format png
```

- `--month YYYY-MM` ou `--from/--to`
- `--team` (repetível), `--status all|open|done`
- `--group-by team|assignee|milestone`
- `--name-style full|short`, `--show-login`
- `--split-assignees` (uma linha por pessoa)
- `--people PATH` (padrão: `people-names.json`)
- `--format png|svg|pdf|all`
- Saída padrão: `out/timeline-YYYY-MM.png` (ou `.svg`/`.pdf`)

Itens que começam ou terminam fora do mês aparecem com até 7 dias de
extensão no eixo e um aviso no subtítulo.

## Documentação

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — pipeline, modelo de dados, decisões e armadilhas.
- [`PLAN.md`](PLAN.md) — fases, achados medidos no board e pontos em aberto.

## Testes

```bash
python3 -m unittest discover -s tests -t .
```
