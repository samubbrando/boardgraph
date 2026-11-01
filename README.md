# boardgraph

Lê um GitHub Project (v2) e gera grafos de dependência por milestone ou por
time, com janelas de tempo calculadas a partir das datas das próprias issues.

## Requisitos

- Python 3.10+
- [`gh`](https://cli.github.com/) autenticado com escopo `read:project`
- [Graphviz](https://graphviz.org/) apenas para `svg`/`pdf`

## Uso

```bash
python3 -m boardgraph fetch  --owner ORG --project 1
python3 -m boardgraph probe
python3 -m boardgraph model
python3 -m boardgraph render --detail parents --format pdf
python3 -m boardgraph fields            # dry-run dos campos de estimativa
```

`fields --execute` é o único comando que escreve no GitHub: cria os campos
`Otimista (dias)`/`Mais provável (dias)`/`Pessimista (dias)`/`Prazo` e semeia
estimativas iniciais. Exige escopo de escrita: `gh auth refresh -s project`.

Filtros: `--detail parents|children|all` e `--team` (repetível).
Render: `--group-by milestone|team`, `--format mmd|dot|svg|pdf`, `--theme light|dark`.

## Documentação

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — pipeline, modelo de dados, decisões e armadilhas.
- [`PLAN.md`](PLAN.md) — fases, achados medidos no board e pontos em aberto.

## Testes

```bash
uv run --group dev python3 -m pytest tests/ -q
```

Ou sem `uv`: `python3 -m pytest tests/ -q` (pytest instalado).
