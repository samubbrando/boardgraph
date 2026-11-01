# boardgraph — arquitetura

Ferramenta de linha de comando que lê um GitHub Project v2 e produz grafos de
dependência entre issues, agrupados por milestone e recortáveis por time.

Board de referência: `Projeto-ES-2026-2-G1/projects/1` ("Plannings"), usado na
disciplina de Engenharia de Software. Todos os números deste documento foram
medidos nesse board em 2026-10-29/30 e conferem com `out/board.json`.

Este documento descreve o código como ele está. O que existe apenas no plano
está marcado como alvo ou pendência, principalmente na seção
[Estado atual versus PLAN](#estado-atual-versus-plan).

## 1. Propósito e escopo

O boardgraph resolve quatro problemas:

1. **Snapshot confiável do board.** Uma consulta GraphQL paginada baixa itens,
   campos, datas, milestones, hierarquia (`parent`) e dependências
   (`blockedBy`) em um único arquivo JSON.
2. **Diagnóstico de preenchimento.** Um relatório mede a cobertura de cada
   campo antes de qualquer desenho. Campo obrigatório vazio vira aviso; campo
   esparso de propósito não vira erro.
3. **Modelo normalizado.** Datas viram janelas `[start, end]`, sub-issues são
   absorvidas pelo pai, milestones ganham janela real e comparação com
   `dueOn`.
4. **Grafo e desenho.** Arestas de dependência, detecção de ciclos, nós
   isolados, bloqueantes externos como fantasmas e emissão em Mermaid ou
   Graphviz (DOT, SVG, PDF).

O que a ferramenta **não** resolve, por decisão de escopo:

- Não escreve no GitHub. É somente leitura.
- Não corrige preenchimento do board. `Status` divergente entre pai e filha é
  reportado pelo `probe`, não reconciliado pelo modelo.
- Não infere dependência que não esteja em `blockedBy`.
- Não transforma PR em nó por padrão. PR não tem issue field de data.
- Não calcula cronograma a partir de `Duration`; a janela é sempre
  `Start date`/`Target date`.
- Não faz layout "bonito" garantido. O Graphviz decide; o projeto controla
  clusters, direção e estilo.
- Não trata board arquivado ou projeto de usuário (a query usa
  `organization(login:)`).

## 2. Pipeline

Fluxo nominal:

```
fetch ──> out/raw/latest.json ──> probe ──> out/report.{md,json}
                              └─> model ──> Board ──> detail ──> team ──> finalize
                                              ──> graph ──> render
```

Contratos entre estágios:

| Estágio | Entrada | Saída | Natureza |
|---|---|---|---|
| `fetch` | `FetchConfig` (owner, project, filtro, flags) | `FetchResult.payload`, `.meta`; grava `latest.json` e `latest.meta.json` | I/O (rede/subprocesso) |
| `probe` | payload cru | relatório `dict`; grava `report.md` e `report.json` | função pura + escrita |
| `model.build_board` | payload cru | `Board` cru (`items`, `nodes` = cópia dos itens, `absorbed` vazio) | função pura (só o timestamp é ambiental) |
| `model.filter_detail` | `Board` + `parents\|children\|all` | `Board` com `nodes` recortado e mapa `absorbed` | função pura |
| `team.filter_team` | `Board` + lista de times | `Board` com `nodes` recortado | função pura |
| `model.finalize` | `Board` filtrado | `Board` com `milestones`, `counts`, `warnings` | função pura |
| `graph` | `Board` filtrado | `graph` (`nodes`, `ghosts`, `edges`, `isolated`, `cycles`, `counts`) | função pura |
| `render` | `Board`/`graph` + `group_by` | texto Mermaid ou DOT; SVG/PDF via `dot -T…` | texto puro; subprocesso só em SVG/PDF |

Observações importantes sobre o fluxo real:

- **Os comandos da CLI são independentes.** `probe`, `model` e `render` leem
  `out/raw/latest.json` diretamente. `render` **não** lê `out/board.json`;
  ele chama `build_board` de novo. Portanto `board.json` é artefato de
  inspeção/consumo externo, não entrada do render.
- **`probe` não é obrigatório.** Ele é um diagnóstico; o render não bloqueia
  se o probe nunca rodou.
- **Filtros devolvem `Board`.** `filter_detail` e `filter_team` não montam
  shape próprio e não geram arestas. O grafo é sempre `build_graph(board)`,
  então ciclos e isolados são calculados com o mesmo código em qualquer
  recorte.
- **Ordem obrigatória:** `detail → team → finalize`. O colapso de sub-issues
  precisa vir antes do filtro por time porque é o colapso que resolve a
  herança de `Team`; `milestones`, `counts` e `warnings` são recalculados uma
  única vez depois de todos os cortes.

## 3. Modelo de dados

### 3.1 Payload cru (`out/raw/latest.json`)

```json
{
  "project": {"id": "...", "title": "Plannings", "url": "...", "number": 1, "owner": "..."},
  "fields": [ ... 17 campos do projeto ... ],
  "items": [ ... 45 itens ... ],
  "rateLimit": {"remaining": 0, "cost": 0, "resetAt": "..."}
}
```

Cada item cru tem `id`, `createdAt`, `updatedAt`, `fieldValues.nodes[]` e
`content` (Issue, PullRequest ou DraftIssue). Em Issue, `content` inclui
`repository`, `milestone`, `labels`, `assignees`, `blockedBy.nodes[]` e
`parent`. `body` é opcional (`--with-body`).

### 3.2 Item normalizado (`board["items"]`)

`items` guarda **tudo que veio do board**, inclusive o que não vira nó:

```json
{
  "key": "org/repo#12",
  "repo": "org/repo",
  "number": 12,
  "type": "issue | pull_request | draft | unknown",
  "title": "...",
  "url": "...",
  "state": "OPEN",
  "status": "Todo",
  "team": "Back",
  "duration": 2,
  "start": "2026-10-01",
  "end": "2026-10-05",
  "start_source": "issue_field | null",
  "end_source": "issue_field | closed_at | null",
  "milestone": {"repo": "org/repo", "number": 1, "title": "...", "due_on": "2026-10-10"},
  "blocked_by": ["org/repo#3"],
  "parent": "org/repo#9",
  "children": [],
  "created_at": "2026-10-01",
  "closed_at": null,
  "absorbed_by": null
}
```

- `key` é sempre `repo#number`, nunca só o número. Item sem repositório ou sem
  número é descartado na normalização (`if i["key"]`).
- `start` vem exclusivamente de `Start date`. `end` vem de `Target date`; se
  faltar, cai para `closedAt` e marca `end_source: "closed_at"`. `created_at`
  é coletado mas **não** é usado como fallback de início no código atual.
- `milestone` é `null` quando a issue não tem milestone.
- `type` traduz `__typename` (`Issue`, `PullRequest`, `DraftIssue`).

### 3.3 Nó (`board["nodes"]`)

Um nó é um item normalizado, com três diferenças possíveis:

1. Sub-issues absorvidas não aparecem como nós. O pai recebe
   `children: ["org/repo#32", ...]`.
2. A janela do nó colapsado é a **união** do grupo:
   `start = min(start)`, `end = max(end)`, com
   `start_source`/`end_source` iguais a `"union"`.
3. Os `blocked_by` das filhas são re-apontados para o nó raiz; bloqueante que
   cair dentro do próprio grupo é descartado.

O nó raiz continua com `absorbed_by: null`; as filhas ficam fora de `nodes`.
O mapa `parent → [filhas]` fica em `board["absorbed"]`. `_collapse` nunca
escreve em `items`: a lista original permanece intacta e é a fonte usada para
rotular fantasmas.

### 3.4 Milestones (`board["milestones"]`)

Derivado de `nodes`, nunca de `items`. Chave `(repo, number)`. Cada entrada:

```json
{
  "repo": "org/repo",
  "number": 2,
  "title": "Mllestone 1 - Identidade",
  "nodes": 4,
  "start": "2026-10-08",
  "end": "2026-11-01",
  "due_on": "2026-10-10",
  "delta_days": 22,
  "span_days": 25,
  "status": "estourado | ok | sem_due"
}
```

Dois contratos convivem:

- **Contrato A (`dueOn`)**: data-alvo declarada na milestone.
- **Contrato B (`start`/`end`)**: menor `start` e maior `end` dos nós do
  grupo.

`delta_days` só existe quando há `dueOn` e `end`. `status` é `sem_due` sem
`dueOn`, `estourado` com `delta_days > 0`, `ok` caso contrário. `span_days` é
inclusivo (`end - start + 1`). O board tem 13 milestones; só 4 têm `dueOn`.

### 3.5 Derivados e quando são calculados

| Derivado | Calculado em | Momento |
|---|---|---|
| `start`/`end`/`*_source` | `model._normalize` | normalização |
| união de janela e merge de blockers | `model._collapse` | `filter_detail(parents)` |
| `absorbed` | `model._collapse` | `filter_detail(parents)` |
| `teams_map` | `team.resolve_teams` | filtro/render/avisos |
| `milestones`, `counts`, `warnings` | `model.finalize` | uma vez, após `detail` e `team` |
| arestas, fantasmas, ciclos, isolados | `graph.build_graph` | render |
| ids Mermaid/DOT, labels, classes | `render`/`dot` | emissão |

## 4. Módulos

| Arquivo | Responsabilidade | Entrada → saída |
|---|---|---|
| `boardgraph/auth.py` | Resolve credencial: explícita > `GITHUB_TOKEN` > `GH_TOKEN` > `gh auth token`; detecta `gh`; mensagem de escopo `read:project`. | ambiente/args → token ou `AuthError` |
| `boardgraph/client.py` | Cliente GraphQL mínimo. Transporte `gh api graphql` ou HTTPS direto (`urllib`). `auto` escolhe `gh` se disponível. Converte `errors` em `GraphQLError` com dica de escopo. | query + variáveis → `data` |
| `boardgraph/queries.py` | Monta o documento GraphQL. Um único documento com paginação por cursor. Inclui os dois formatos de data: campos clássicos (`ProjectV2ItemFieldDateValue`) e issue fields (`ProjectV2ItemIssueFieldValue` → `IssueFieldDateValue`). `include_deps` e `include_body` são opcionais. | flags → string GraphQL |
| `boardgraph/fields.py` | **Toda** leitura de `fieldValues` passa aqui. `split_value` entende `issueFieldValue` e o formato clássico; `field_map` monta `{nome: valor}`; `item_key` gera chave estável. É a camada que impede `null` silencioso nas datas. | item cru → mapa de campos / chave |
| `boardgraph/fetch.py` | `fetch_board` executa a query, pagina até `max_pages`, tenta de novo sem `blockedBy/parent` se o GraphQL recusar dependências (`degraded`), grava `latest.json`/`latest.meta.json` e resume o meta. | `FetchConfig` → `FetchResult` + arquivos |
| `boardgraph/probe.py` | Relatório de cobertura. Linhas obrigatórias (`Status`, `Start date`, `Target date`, `Milestone`) geram aviso; informativas não. Detecta milestone por `(repo, number)`, `dueOn` ausente e divergência de `Status` pai/filha. | payload → relatório; grava `report.md/json` |
| `boardgraph/model.py` | Núcleo puro. `build_board` normaliza itens; `filter_detail` aplica `parents`/`children`/`all`; `finalize` calcula `milestones`, `counts` e `warnings` uma vez. Também formata a tabela de terminal. | payload → `Board`; `Board` + `detail` → `Board` |
| `boardgraph/graph.py` | Arestas `blocked_by` (dependência) e `parent` (hierarquia, só em `children`/`all`), fantasmas para bloqueantes fora do recorte (com time lido de `items`), Tarjan para ciclos, lista de isolados. | `Board` → grafo |
| `boardgraph/team.py` | `resolve_teams` herda `Team` do pai quando o nó não tem time; `filter_team` devolve `Board` filtrado, mantendo tarefas sem time. `team_from_items` rotula fantasmas. | `Board` + times → `Board` |
| `boardgraph/render.py` | Emissor Mermaid. `render_mermaid` agrupa por `group_by` (`milestone` ou `team`), desenha fantasmas, arestas sólidas/tracejadas, classes por `Status` e `click`. | `Board`/`graph` + `group_by` → texto `.mmd` |
| `boardgraph/dot.py` | Emissor Graphviz. Temas `light`/`dark`, clusters por `group_by`, cores por `Status`, `URL=` para abrir a issue. | `Board`/`graph` + `group_by` → DOT |
| `boardgraph/cli.py` | `argparse`, normalização de `--filter -status:Done`, dispatch dos subcomandos, escrita de artefatos e chamada de `dot -Tsvg|pdf`. Códigos de saída: 0 ok, 1 erro genérico/`--strict`, 2 auth, 3 GraphQL. | argv → arquivos + stdout |
| `boardgraph/__main__.py` | Permite `python -m boardgraph`. | — |
| `tests/` | 50 testes unitários offline. | — |

## 5. Decisões e evidência

### 5.1 Datas vêm de issue fields, não de campo clássico

O board usa `ProjectV2ItemIssueFieldValue` → `IssueFieldDateValue.value`.
Com o fragmento clássico `ProjectV2ItemFieldDateValue`, `Start date` e
`Target date` voltam `null` sem erro. Evidência: `out/report.md` mostra
44/45 em ambas as datas usando o fragmento de issue field; o PR
`backend#29` é a única exceção e ele realmente não tem data. O fragmento
clássico permanece em `queries.py` como fallback para outros boards.
`fields.py` centraliza a leitura para que nenhum outro módulo precise saber
qual dos dois formatos veio.

### 5.2 Um único passe GraphQL

`board_query` traz projeto, campos, itens, datas, milestone, `blockedBy` e
`parent` no mesmo documento. A paginação usa `cursor`/`after`, não uma segunda
query por item. Evidência: o board inteiro cabe em 1 página (45 itens,
`items(first:100)`), fetch completo em ~5,5 s, dominado pelo overhead do `gh`.
Duas passadas só aumentariam latência e risco de inconsistência entre leituras.

### 5.3 `Status` é decorativo

`Status` é lido, guardado e usado **apenas** para escolher cor/classe:
`STATUS_CLASS` em `render.py`, `STATUS_KEY` em `dot.py`. Nenhuma regra de
colapso, janela, ordenação, filtro, ciclo ou contagem consulta `Status`.
Evidência: `model.py` não tem regra de negócio sobre `status`; `graph.py` e
`team.py` também não. O `probe` só aponta divergência pai/filha como
observação, fora do `--strict`. O diagrama espelha o board; corrigir
preenchimento não é papel da ferramenta.

### 5.4 Colapsar sub-issues no pai

As filhas são absorvidas na camada `nodes`, mas continuam em `items`. A janela
do nó colapsado é a união (`min(start)`/`max(target)`), não o campo do pai.
Evidência: `backend#9` tem três filhas (`#32`, `#33`, `#34`) com Start e
Target; a união é `2026-10-13 → 2026-11-01`, exatamente a janela que o pai
deveria representar. Como as datas existem nas filhas, a união é calculada,
não estimada. A união também é o que não esconde atraso: usar só o pai
poderia esconder trabalho que termina depois.

Regras do colapso:

1. Sobe a cadeia de `parent` até o topo que está no board, com guarda contra
   ciclo.
2. Só colapsa se o pai está no board. Pai fora do board → filhas continuam
   como nós.
3. `blocked_by` das filhas é re-apontado para o topo; bloqueante interno ao
   grupo é descartado.
4. `absorbed_by` registra quem absorveu quem, e o aviso informa a contagem.
5. `Status` do nó colapsado é o do pai, sem reconciliação.

### 5.5 Chave de milestone é `(repo, number)`

Número de milestone colide entre repositórios: existe `.github#4` e
`backend#4` no mesmo board. Título também não serve como chave: há um
`"Mllestone 1 - Identidade"` com typo. Evidência: o probe conta 13 milestones
usando `(repo, number)`; contar só por número daria menos. A ordenação de
`milestones` usa `start`, depois `repo`, depois `number`.

### 5.6 PR não é nó

PR não tem issue fields de `Start date`/`Target date`; `backend#29` só tem
`closedAt`. Incluí-lo como nó exigiria inventar início. Portanto PR fica em
`items` e fora de `nodes`, exceto em `--detail all`. Evidência:
`out/board.json` tem 45 itens e 41 nós; a diferença é 3 sub-issues absorvidas
+ 1 PR.

### 5.7 Time: herança, `(sem time)` e fantasma

`resolve_teams` procura `Team` no nó; se vazio, sobe a cadeia de `parent` em
`items`; se não achar ancestral, devolve `None` e o nó cai em `(sem time)`.
Nó sem time nunca é descartado por filtro. Bloqueante fora do recorte vira
fantasma; o time vem de `items` quando o item existe, ou `fora do board`
quando realmente não está no board.

Evidência: 41/45 itens têm `Team`; as 3 sub-issues de `backend#9` herdam
`Back`, por isso `children --team Back` tem 16 nós. O fantasma é um único nó
(`backend#12`) com duas arestas para o Front, não dois nós. Times medidos:
Back 13, Front 9, Infra 4, Real 15. Arestas entre times: 12 `Back → Front` e
2 `fora do board → Front`. `Real` tem zero arestas e dispara aviso de "time
sem dependência".

### 5.8 Dois emissores, mesma informação

Mermaid é o formato de inspeção rápida e diff; Graphviz é o que gera SVG/PDF
com layout melhor. Os dois emissores repetem grupos, labels, cores e arestas
porque têm sintaxes incompatíveis. O custo aceito é duplicação; o risco é os
dois divergirem. Por isso ambos recebem o mesmo `group_by` e usam as mesmas
funções de agrupamento conceitual (`milestone` ou `team`).

### 5.9 Filtro server-side é opcional

`--filter` repassa a sintaxe de filtro do GitHub Projects para a query. Foi
validado no board real: `updated:>=2026-10-20` → 29 itens, `status:Done` → 19,
`-status:Done` → 26, `team:Back` → 13. O filtro reduz payload, mas muda o
snapshot: use-o para recortes, não para o `board.json` canônico.

## 6. Armadilhas conhecidas

### Issue field versus campo clássico

O erro mais caro do projeto. Usar `ProjectV2ItemFieldDateValue` devolve
`null` sem erro; o grafo sai sem datas e parece "board sem preenchimento".
Toda leitura de campo passa por `fields.split_value`. Se um board novo usar o
formato clássico, o fallback existe, mas o teste
`test_includes_issue_field_dates` garante que o fragmento de issue field não
suma da query.

### Número de milestone colidindo entre repositórios

Nunca use só `number`. `(repo, number)` é a chave em `model`, `probe`,
`render` e `dot`. O título também não é chave: há typo em "Mllestone 1".

### PR sem datas

PR não tem issue field. `backend#29` tem `closedAt` (usado como `end`) mas
`start` nulo. Em `--detail all` o nó aparece com janela incompleta e o aviso
de "nó sem data completa" dispara. Isso é esperado.

### Fantasma sem time e sem URL

Bloqueante fora do board não tem `team` nem `url`. No grafo completo ele vira
`external: true` com título `repo#n (fora do board)`; no recorte por time, o
título é `não adicionada ao board` e o time é `fora do board`. Não há `click`
para fantasma.

### `--filter -status:Done` quebrando o argparse

Valor começando com `-` é interpretado como opção. `_normalize_argv` junta
para `--filter=-status:Done` antes do parse. O teste
`test_negative_filter_is_joined` cobre isso.

### `--all` não era `detail=all`

`--all` (três views) foi removido na Fase 7. Hoje `--detail all` significa
"manter sub-issues e PR como nós". Não confunda os dois ao ler o histórico.

### Mutação de `items` no colapso

Resolvido na Fase 7: `_collapse` trabalha sobre cópias e grava o mapa de
absorção em `board["absorbed"]`. `items` permanece idêntico antes e depois dos
filtros, o que permite rotular fantasmas com o time de origem.

### Milestone sem `dueOn`

Só 4 das 13 milestones têm `dueOn`. As outras ficam `sem_due`, sem delta.
Não trate `sem_due` como "no prazo"; é ausência de contrato A.

### `organization` fixo na query

`queries.py` usa `organization(login: $owner)`. Projeto de usuário
(`user(login:)`) não funciona. O erro é "projeto não encontrado", não um erro
de GraphQL claro.

### `page_size` não usado

`FetchConfig.page_size` existe, mas a query fixa `items(first: 100)`. O
parâmetro é decorativo no código atual.

## 7. Como rodar

Pré-requisitos: Python ≥ 3.10, `gh` autenticado com escopo `read:project`
(`gh auth refresh -s read:project`) ou `GITHUB_TOKEN`/`GH_TOKEN`. Para
SVG/PDF: Graphviz (`dot`) no `PATH`.

A partir de `/home/samuel/dev/boardgraph`:

```bash
# 1. Baixar o board (I/O)
python -m boardgraph fetch \
  --owner Projeto-ES-2026-2-G1 \
  --project 1

# 2. Diagnóstico de cobertura (offline, lê out/raw/latest.json)
python -m boardgraph probe

# 3. Modelo normalizado (offline) -> out/board.json
python -m boardgraph model

# 4. Render Mermaid (padrão: detail parents, group-by milestone)
python -m boardgraph render
python -m boardgraph render --detail children
python -m boardgraph render --detail all

# 5. Render Graphviz
python -m boardgraph render --format dot
python -m boardgraph render --format svg
python -m boardgraph render --format pdf

# 6. Recorte por time e agrupamento
python -m boardgraph render --team Front --format pdf
python -m boardgraph render --detail children --team Back
python -m boardgraph render --group-by team
```

Opções úteis:

- `fetch --filter 'updated:>=2026-10-20'` — filtro server-side. Para valor
  negativo, use `--filter=-status:Done` (a CLI normaliza a forma separada).
- `fetch --no-deps` — não pede `blockedBy`/`parent`.
- `fetch --with-body` — inclui `body` (payload ~+20%).
- `render --detail parents|children|all` — define o conjunto de nós.
- `render --team NOME` (repetível) — recorta por time; tarefa sem time entra
  em `(sem time)` e nunca é descartada.
- `render --group-by milestone|team` — agrupamento visual; não altera nós nem
  arestas. Vale para Mermaid e Graphviz.
- `render --theme dark` — tema escuro no Graphviz.
- `render --print` — imprime o Mermaid no terminal.
- `probe --strict` — sai 1 se houver aviso.

Saídas em `out/`:

| Arquivo | Produzido por | Conteúdo |
|---|---|---|
| `out/raw/latest.json` | `fetch` | payload cru, 45 itens |
| `out/raw/latest.meta.json` | `fetch` | data, duração, páginas, contagens, `degraded`, avisos |
| `out/report.md` | `probe` | tabela de cobertura legível |
| `out/report.json` | `probe` | mesmo relatório em JSON |
| `out/board.json` | `model` | `Board` normalizado (`items`, `nodes`, `milestones`) |
| `out/graph-<detail>.mmd` | `render --format mmd` | Mermaid |
| `out/edges-<recorte>.json` | `render` | contagens, fantasmas, arestas, isolados, ciclos do recorte |
| `out/graph-<detail>.dot` | `render --format dot/svg/pdf` | Graphviz |
| `out/graph-<detail>.svg` | `render --format svg` | SVG via `dot` |
| `out/graph-<detail>.pdf` | `render --format pdf` | PDF via `dot` |
| `out/graph-<detail>-by-team.pdf` | `render --group-by team` | um cluster por time |
| `out/graph-<detail>-team-<time>.pdf` | `render --team …` | recorte por time |

Números atuais (board de referência, `parents`): 45 itens, 41 nós, 3
absorvidos, 13 milestones, 34 arestas de dependência, 1 fantasma
(`backend#12`) com 2 arestas, 19 isolados, 0 ciclos. `children` = 44 nós e 37
arestas (34 dependência + 3 hierarquia), 22 isolados. `all` = 45 nós, 23
isolados. Zero milestones misturam times.

## 8. Estado da suíte de testes

50 testes, todos offline, executados com:

```bash
python -m unittest discover -s tests -v
```

Resultado em 2026-10-31: `Ran 50 tests ... OK`.

| Arquivo | Testes | Cobre |
|---|---:|---|
| `tests/test_fetch.py` | 6 | Query contém `ProjectV2ItemIssueFieldValue`/`IssueFieldDateValue`; toggles de `blockedBy` e `body`; normalização de `--filter -status:Done`; resumo marca `DEGRADED`. |
| `tests/test_probe.py` | 5 | Board completo sem aviso; falta de `Start date` obrigatória gera aviso; campo opcional esparso não gera; `body` não coletado não é erro; milestone contada por repositório (mesmo número em repos diferentes). |
| `tests/test_model.py` | 13 | Colapso: filha absorvida, união de janela, blocker de filha re-apontado, blocker irmão descartado, pai fora do board não colapsa. `children` mantém nós; `all` inclui PR. `items` não é mutado; `detail`+`team` compõem; janela de milestone recalculada no subconjunto. |
| `tests/test_graph.py` | 13 | Aresta bloqueante→bloqueado; blocker externo vira fantasma; hierarquia só em `children`/`all`; ciclo via Tarjan; isolados; nó bloqueado não é isolado. Render: aspas, ids, `click`, fantasma com time de origem, `group_by=team` nos dois emissores. Lint Mermaid. |
| `tests/test_team.py` | 13 | Herança de time pela cadeia de pai; sem time permanece `None`; seleção; externo mantém time de origem; fora do board marcado; blocker interno não é externo; múltiplos times; `(sem time)` nunca descartado; time inexistente avisa; time sem dependência avisa; arestas só tocam nós mantidos. |

Lacunas de teste atuais: não há teste de temas do `dot.py` (light/dark,
escape, `URL=`), nem de `fetch_board` com cliente falso/paginação/degraded,
nem de `auth`/`client`. `test_graph` cobre agrupamento no Graphviz, mas não o
layout gerado.

## 9. Estado atual versus PLAN

Depois da Fase 7, `PLAN.md` e código estão alinhados nos pontos que antes
divergiam:

1. **`createdAt` não é fallback de início.** A doc foi corrigida: a janela usa
   só `Start date`; `createdAt` fica em `created_at` sem participar do
   cálculo.
2. **Fase 6 (SVG/PDF)** está marcada como concluída e `--format svg|pdf`
   funciona via `dot`.
3. **`items` é imutável.** `_collapse` não escreve mais em `items`; o mapa de
   absorção fica em `board["absorbed"]`.
4. **Filtros devolvem `Board`.** `filter_detail` e `filter_team` mantêm o
   schema; `TeamView` e `render_team_*` foram removidos.
5. **`--detail` e `--group-by` existem.** `--view` foi removido; o
   agrupamento é parâmetro do renderer.
6. **`--all` foi removido.** `--detail all` é o recorte que inclui PR.
7. **Fase 6 duplicada** foi removida do plano.

## 10. Pontos em aberto

1. **Layout de `parents` com 19 isolados vira tira vertical.**
   O problema: milestones sem nenhuma aresta são empilhadas; o desenho fica
   alto e pouco informativo. Por que ficou aberto: é escolha de layout, não
   de modelo; o Graphviz já recebe clusters corretos. Para resolver: decidir
   entre layout dedicado (ex.: `rank=same` por milestone, `packmode`) ou um
   cluster visual "sem dependência" separado, sem mudar o modelo. Medir antes
   e depois com um SVG/PDF do recorte `parents`.

2. **PDF consolidado com `pdfunite`.**
   Hoje cada recorte gera um PDF; juntar todos exigiria uma etapa externa.
   Por que ficou aberto: não há demanda confirmada e `pdfunite` adiciona
   dependência (`poppler-utils`). Para resolver: decidir se o caso de uso é
   "um PDF por time" ou "um PDF único"; se for único, criar subcomando
   `render --format pdf --merge` e documentar a dependência.

3. **`group_by=team` com muitos nós.**
   O Graphviz tende a aguentar centenas/milhares de nós com clusters, mas o
   layout fica lento e ilegível; o Mermaid não escala e pode travar o
   navegador. Por que ficou aberto: o board atual tem 41 nós e o problema não
   apareceu. Para resolver: definir limite prático (ex.: 200 nós), medir
   tempo de `dot` e decidir se Mermaid é permitido nesse modo ou se o modo
   team só emite DOT/SVG/PDF.

4. **View HTML com checkbox por time.**
   Foi o Passo 6 opcional da Fase 6 e ficou de fora. Por que ficou aberto:
   exige um terceiro emissor (HTML/JS) e um servidor ou arquivo autônomo; o
   retorno sobre Mermaid/PDF não foi justificado. Para resolver: gerar HTML
   único com os nós embutidos em JSON e alternar visibilidade por time sem
   re-render no servidor; decidir se links `click` continuam.

5. **`Duration` nunca confrontado com `target - start`.**
   `duration` é um issue field em horas (41/45), mas o modelo só usa datas de
   calendário. Por que ficou aberto: a comparação depende de dias úteis,
   feriados e jornada, que o board não declara; qualquer conta seria
   heurística. Para resolver: definir calendário e jornada, ou limitar a um
   aviso grosseiro (`duration` > `span_days * 24`) só no `probe`, sem entrar
   no grafo.

6. **`Labels` 4% e `Parent` 7% no probe.**
   O modelo hoje não usa labels; `parent` é usado só para colapso/herança.
   Se o grupo passar a usar labels para classificar tarefas, o modelo precisa
   de um campo derivado (lista de labels) e o probe precisa virar
   `required` para esse uso. Para resolver: decidir o contrato de labels
   antes de qualquer filtro por label; não assumir que 4% é suficiente.

7. **Reprodutibilidade: `board.json` não guarda a versão do código.**
   O payload tem `fetchedAt`, mas o board normalizado não registra commit,
   versão do pacote nem hash da query. Pior: o diretório não é um repositório
   Git hoje, então nem `git rev-parse` resolveria. Para resolver: incluir
   `toolVersion` e `codeRevision` no `meta`/`Board` (ou um `--revision`), e
   versionar o projeto. O `.gitignore` já ignora `out/`, então o snapshot não
   é versionado de propósito.

8. **Board de disciplina com prazo: o que acontece ao arquivar?**
   O board é de uma turma com data de entrega; projetos podem ser arquivados
   ou ficar inacessíveis. A query atual não trata `archived` nem projeto
   arquivado; o erro seria "projeto não encontrado". Para resolver: decidir
   se o snapshot `latest.json` é o artefato de longo prazo (recomendado) e
   documentar que o render é offline; opcionalmente detectar
   `projectV2.archived` e avisar.

9. **`organization` fixo e projeto de usuário.**
   A query só consulta `organization(login:)`. Se o board migrar para conta
   pessoal, o comando falha com mensagem genérica. Para resolver: detectar
   owner (tentar `organization`, cair para `user`) ou expor `--owner-type`,
   mantendo a mesma interface de dados.

10. **Recorte por time valida ciclos e isolados.**
    Resolvido na Fase 7: `filter_team` devolve `Board` e o render sempre
    chama `build_graph`, então ciclos e isolados usam o mesmo código do grafo
    completo.
