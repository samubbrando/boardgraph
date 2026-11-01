# boardgraph — plano de execução

Ferramenta que lê um GitHub Project (v2) e gera um grafo de dependências
(Mermaid → SVG), com janelas de tempo por milestone.

Board alvo: `Projeto-ES-2026-2-G1/projects/1` ("Plannings").

## Decisões já fechadas

- **Single pass**: uma query GraphQL, `items(first:100)` paginado. Sem dois passes.
- **Datas vêm de issue fields**, não de campo de projeto clássico:
  `ProjectV2ItemIssueFieldValue` → `IssueFieldDateValue.value`.
  (O fragmento `ProjectV2ItemFieldDateValue` retorna `null` silencioso aqui.)
- **Dependência**: `Issue.blockedBy` (única fonte existente no board).
- **Milestone com dois contratos**: `dueOn` (contrato A) e
  `min(start)/max(target)` das issues (contrato B). Mostrar os dois + desvio.
- **Colapso de sub-issues** (`--detail parents`, padrão): na visualização, a
  filha não vira nó — é absorvida pelo pai. Justificado pelo board: as 3 filhas
  (`backend#32/#33/#34`) têm Start **e** Target, e a união delas é exatamente a
  janela do pai (`backend#9`, 10-13 → 11-01). Como as datas existem nas filhas,
  a janela do nó colapsado é calculável, não estimada. `items` continua
  guardando as filhas, sem mutação; só `nodes` colapsa e o mapa de absorção
  fica em `absorbed`.
- **`Status` é só visual**: nunca entra em cálculo — nem na janela de tempo,
  nem na decisão de colapso, nem na ordenação. No nó colapsado mostra o campo
  do pai como está; divergência com as filhas não é reconciliada. O diagrama
  espelha o board, não corrige preenchimento.
- **Agrupamento do diagrama**: por milestone (padrão) ou por time, chave de
  milestone `(repo, number)` — nem título (existe "Mllestone 1" com typo) nem
  só o número (colide entre repositórios).

## Fatos medidos no board (2026-10-29)

| Métrica | Valor |
|---|---|
| Itens | 45 (44 issues, 1 PR) |
| Páginas | 1 |
| `Status` | 45/45 (Todo 20, In progress 6, Done 19) |
| `Team` | 41/45 (Front, Back, Infra, Real) |
| `Duration` | 41/45 |
| `Start date` / `Target date` | 44/45 |
| `milestone.dueOn` | 16/45 (4 de 13 milestones têm dueOn) |
| `blockedBy` ≥ 1 | 21/45 |
| Arestas | 34 (2 dangling: `backend#12` → frontend#1/#2) |
| Nós isolados | 23 |
| Ciclos | 0 |
| Sub-issues (`parent`) | 3/45 |

## Fases

- [x] **Fase 1 — fetch**: auth + client GraphQL + paginação + cache + meta.
      Entrega: `out/raw/latest.json`, `latest.meta.json`. ✔ 2026-10-29
- [x] **Fase 2 — probe**: relatório de cobertura dos campos.
      Entrega: `out/report.md`, `out/report.json`. ✔ 2026-10-29
- [x] **Fase 3 — model**: normalização + resolução de datas + janelas de
      milestone com os dois contratos.
      Emite `items` (tudo, imutável) e `nodes` (recortado pelos filtros).
      Entrega: `out/board.json` (normalizado), tabela no terminal. ✔ 2026-10-29
- [x] **Fase 4 — deps**: grafo, validação (dangling, isolados, ciclos) e
      arestas de hierarquia.
      Entrega: `out/edges-<recorte>.json` + avisos. ✔ 2026-10-29
- [x] **Fase 5 — render**: visualizações de detalhe, Mermaid.
      Entrega: `out/graph-<recorte>.mmd`. ✔ 2026-10-29
- [x] **Fase 6 — svg**: `mmdc` → SVG/PDF; emissor Graphviz. ✔ 2026-10-30
- [x] **Fase 7 — filtros e render**: `--detail`, `--team`, `--group-by`;
      filtro devolve `Board`; remoção de `--view`/`TeamView`. ✔ 2026-10-31
- [ ] **Fase 8 — PERT/CPM**: campos Otimista/Mais provável/Pessimista + Prazo, cálculo de caminho crítico,
      probabilidade e calibração pelo realizado. Entrega: `out/pert.md`,
      `out/pert.json`, `render --style critical`. Branch: `feat/pert-cpm`.

## Heurística de colapso (sub-issues)

1. Mapa `filha → pai` a partir de `content.parent` (mesmo repo, `parent.number`).
2. Colapsa só se o pai estiver no board e tiver ≥ 1 filha no board.
   Pai fora do board → filhas continuam como nós.
3. Janela do nó = `min(start)` / `max(target)` sobre **pai + filhas** (união,
   nunca só os campos do pai — a união é o que não esconde atraso).
4. Arestas `blockedBy` das filhas são re-apontadas pro pai; aresta que virar
   laço é descartada.
5. Hierarquia com mais de um nível sobe até o topo que está no board, com
   guarda contra ciclo.
6. O relatório informa quantos nós foram absorvidos (`board["absorbed"]`), para
   ninguém achar que sumiu issue.
7. Status não participa de nenhuma regra acima — só de cor no render. Se pai e
   filhas divergirem, isso é erro de preenchimento e o probe pode apontar; o
   modelo não tenta adivinhar qual está certo.

Estado atual do board: 1 família (`backend#9` ← 3 filhas). Nós: 45 itens
− 3 absorvidos − 1 PR = **41 nós**, e isolados caem de 23 para 19.

## Recortes de detalhe

Mesmo `latest.json`, três recortes. `detail` é resolvido antes dos demais
filtros, porque é o colapso que resolve a herança de `Team`.

| `--detail` | Conteúdo | Nós hoje |
|---|---|---|
| `parents` | sub-issues absorvidas no pai, badge `+N` | 41 |
| `children` | sub-issues viram nó próprio; hierarquia tracejada | 44 |
| `all` | `children` + PR (`backend#29`) | 45 |

Medido: `parents` 34 arestas / 19 isolados · `children` 37 (34 dep + 3 hier) /
22 isolados · `all` 37 / 23 isolados. O fantasma é **um** nó (`backend#12`)
com **duas** arestas, não dois nós.

## Fase 6 — recortes e agrupamento por time + PDF

- [x] **Passo 1** — `team.py`: filtro por time, bloqueantes externos com o time
      de origem, herança de `Team` pelo pai, tarefa sem time cai em "(sem time)".
- [x] **Passo 2** — `dot.py`: emissor Graphviz (cluster, cor por status, `URL=`).
- [x] **Passo 3** — `--format pdf` via `dot -Tpdf`.
- [x] **Passo 4** — `--group-by team`: um cluster por time, arestas cruzadas.
- [x] **Passo 5** — PDF por time.
- [ ] **Passo 6 (opcional)** — HTML com checkbox por time.

Decisões: sem `--team` = grafo completo. Tarefa sem time herda do pai; se
não houver pai, cai em `(sem time)` e aparece em todo recorte.

### Resultado medido (2026-10-30)

| Recorte | nós | externos | arestas |
|---|---|---|---|
| Back | 13 | 0 | 18 |
| Front | 9 | 6 (5 Back + `backend#12`) | 14 |
| Infra | 4 | 0 | 2 |
| Real | 15 | 0 | **0** |
| Back + Front | 22 | 1 | 32 |
| Todos | 41 | 1 | 34 |
| Sem `--team` | 41 | 1 | 34 |

`--detail children --team Back` = 16 nós: as 3 sub-issues herdam `Team` do pai.
`Real` dispara aviso de time sem dependência — o grafo vira lista.

Artefatos: `out/graph-<detail>.{mmd,dot,svg,pdf}`,
`out/graph-parents-by-team.pdf`, `out/graph-<detail>-team-<time>.pdf`.

Bug encontrado e corrigido no caminho: id de cluster montado a partir da tupla
`(repo, number)` gerava `cluster_('org/repo', 1)` e quebrava o `dot`.

## Regras de desenho

- Aresta de dependência: sólida (`-->`). Aresta de hierarquia: tracejada (`-.->`).
- Cor por `Status` (só visual): todo cinza tracejado, doing azul, done verde.
- Nó fantasma (blocker fora do board): borda tracejada, sem link.
- Agrupamento por milestone, chave `(repo, number)`.
- `click` no nó leva à issue no GitHub (exceto fantasma).
- Título truncado em 34 chars; `#número · título`.

## Regra do loop

Ao fim de cada fase: parar, mostrar o artefato gerado + resumo curto,
pedir ok antes de seguir. Nada de 6 fases numa tacada.

## Descobertas da Fase 1

- **`body` ficou opt-in** (`--with-body`): +20% de payload e nenhum consumidor
  hoje. Sem body o `latest.json` fica em 145 KB.
- **Filtro server-side funciona** (validado no board real):
  `updated:>=2026-10-20` → 29 · `status:Done` → 19 · `-status:Done` → 26 ·
  `team:Back` → 13 · `milestone:"Milestone 3 - API Financeira"` → 3.
- `--filter` com valor começando em `-` quebrava o argparse; normalizado para
  `--filter=-status:Done`.
- Fetch completo: ~5,5 s (overhead do `gh`), 1 página, 45 itens.
- `ProjectV2ItemIssueFieldValue` confirmado: 88 valores de issue field no board.
- PRs não têm issue fields → `backend#29` fica sem Start/Target (esperado).
- **Correção de medição anterior**: 4 milestones têm `dueOn`, não 5 — o número
  da milestone colide entre repositórios (`.github#4` e `backend#4`), então a
  chave correta é `(repo, number)`, nunca só o número. Isso também vale para a
  Fase 5.
- `durationMs` mantido no meta: serve para acompanhar o custo do fetch quando a
  paginação passar de uma página.

## Escopo do payload (o que a Fase 1 entrega)

| Bloco | Conteúdo | Consumidor |
|---|---|---|
| `project` | id, title, url, number, owner | metadados do diagrama |
| `fields[]` | 17 campos, tipos e opções de single select | fase 3 (ordem) / fase 5 (cores) |
| `items[].fieldValues` | Status, Team, Duration, Start/Target (issue fields) | fase 3 (datas) |
| `items[].content` | number, title, state, milestone, labels, body | fase 4/5 (nós e grupos) |
| `items[].content.blockedBy` | 34 arestas | fase 4 |
| `items[].createdAt` | data de entrada no board | não usado como início; a janela vem só de `Start date` |

Fora do payload, de propósito: `ghVersion`, `toolVersion` e snapshots com
timestamp (git já guarda histórico). Ficaram `durationMs` (custo do fetch),
`degraded` (flag de correção) e `warnings`.

## Descobertas da Fase 3

- **PR não é nó.** `backend#29` (PR mergeado) fica em `items` mas fora de
  `nodes`; incluí-lo exigiria data que PR não tem. Só entra com `--detail all`,
  e o aviso lista o que ficou de fora nos outros recortes.
- **Janela do nó colapsado é união** (`start_source: "union"`), não o campo do
  pai. Em `backend#9` os dois coincidem (10-13 → 11-01), então nada mudou.
- **`Status` do nó colapsado = campo do pai**, sem reconciliação. O `probe`
  aponta a divergência em `## Observações`, fora do `--strict`.
- **`items` é imutável.** O colapso grava o mapa `absorbed` no board, nunca
  `absorbed_by` nos itens.
- **`--since/--until` saíram.** Recorte temporal agora é responsabilidade de
  quem consome o snapshot; o pipeline só tem `detail` e `team`.
- **2 milestones estourados** confirmados: `Mllestone 1` (+22d) e
  `Milestone 2 - Domínio financeiro` (+29d).

## Pendências de feedback

- ~~Fase 1: manter `body`?~~ → não, opt-in via `--with-body`.
- ~~Fase 2: avisos viram erro de CI?~~ → `--strict` já implementado, sai 1.
- ~~Fase 3: `Duration` como conferência?~~ → exposto em `board.json`, sem aviso (aguardando uso real).
- ~~Fase 4: dangling vira fantasma?~~ → sim, em qualquer recorte (`--detail all`
  inclui o PR; fantasmas são bloqueantes fora do conjunto de nós).
- Fase 6: SVG/PNG (mmdc) ou ficar só em Mermaid? Isolados entram no desenho?

## Fase 7 — filtros e render

Implementada em 2026-10-31. O pipeline é
`payload → build_board → filter_detail → filter_team → finalize → build_graph
→ render`.

### Filtros (2)

- `--detail parents|children|all` (default `parents`)
- `--team` (lista, repetível)

`detail` define o conjunto de nós:

| `--detail` | Nós | O que faz |
|---|---|---|
| `parents` | 41 | sub-issues absorvidas no pai |
| `children` | 44 | sub-issues viram nó próprio, com aresta de hierarquia |
| `all` | 45 | inclui PR (`backend#29`) e blocker externo como fantasma |

### Render (não filtro)

- `--group-by milestone|team` (default `milestone`)
- `--format mmd|dot|svg|pdf`
- `--theme light|dark`
- `Status`: só cor.

`--group-by` é opção de desenho, não de seleção: não altera `nodes`, arestas,
`milestones` nem contagens. Vale para os dois emissores, Mermaid e Graphviz,
com o mesmo agrupamento nos dois.

### Arquitetura

- `items` imutável (fonte de verdade e rótulo de fantasma); `nodes` é o
  conjunto de trabalho que os filtros cortam; `milestones`, `counts` e
  `warnings` recalculados uma única vez em `finalize()`.
- Ordem obrigatória: `detail → team → finalize`. `detail` antes porque o
  colapso resolve a herança de `Team`.
- Filtro devolve `Board` (mesmo schema), nunca um shape próprio.
- Removidos: `render_team_mermaid`, `render_team_dot`, `TeamView`, e as flags
  `--view`, `--all`, `--include-prs`, `--no-collapse`, `--since`, `--until`.
- Mesmo `group_by` nos dois emissores (Mermaid e Graphviz).
- Fantasma carrega o time de origem lido de `items`; fora do board, o time é
  `fora do board`.

### Números esperados

| Combinação | Nós | Clusters |
|---|---:|---:|
| `--detail parents` (group-by milestone) | 41 | 13 |
| `--detail parents --group-by team` | 41 | 4 (Back, Front, Infra, Real) |
| `--detail children` | 44 | 13 por milestone |
| `--detail all` | 45 | 13 por milestone |
| `--detail parents --team Front` | 9 | 3 por milestone: Acesso, Cadastros, Dashboard |

`--detail parents --team Front` = 9 nós e 3 clusters por milestone
(`Milestone 4 - Acesso`, `Milestone 5 - Cadastros`, `Milestone 6 - Dashboard`).
Não há tarefa sem time no board atual; `(sem time)` continua existindo como
fallback e nunca é descartado.

### Consequências da migração

- `--since`/`--until` saíram da CLI. Quem quiser recorte temporal usa o
  snapshot filtrado ou uma transformação externa.
- `--include-prs` sumiu: PR entra só em `--detail all`.
- `--no-collapse` sumiu: colapso é o comportamento de `--detail parents`.
- `--all` (três views) sumiu; quem quiser os três recortes roda três comandos
  ou usa um script.
- `edges-<recorte>.json` é derivado do `Board` filtrado, com contagens,
  fantasmas, arestas, isolados e ciclos.

## Fase 8 — PERT/CPM (artefato de entrega)

Planejada em 2026-10-31, branch `feat/pert-cpm`. PERT probabilístico é
exigência da disciplina — não é opcional.

### Decisões travadas

| | Escolha |
|---|---|
| Unidade das estimativas | dias |
| Campos | `ProjectV2Field` NUMBER (Otimista, Mais provável, Pessimista) + DATE (Prazo) |
| Semente inicial | script (`O=0.7M`, `M=Target−Start+1`, `P=1.6M`), depois revisão humana |
| Calibração | mediana de `(closedAt−start)/(Target−start)` nas tarefas Done |
| Deadline | campo `Prazo` por tarefa + data global (`--deadline`) |
| Consumidor | professor e grupo |
| Capacidade real | 13 pessoas, 3 frentes simultâneas (fora do cálculo) |

### Campos novos no board

```
Otimista (dias)          NUMBER   estimativa otimista
Mais provável (dias)     NUMBER   estimativa mais provável
Pessimista (dias)        NUMBER   estimativa pessimista
Prazo                    DATE     compromisso de entrega da tarefa
```

Nomes por extenso e com unidade: o board é lido pelo grupo e pelo professor,
e `O`/`M`/`P` só fazem sentido para quem já conhece PERT. `Duration` (horas)
mede *esforço* e fica fora da conta e fora da tabela do PERT — é o único
sinal de esforço que a equipe preencheu (41/45), guardado como conferência
cruzada, não como duração de calendário. A data global do projeto não é
campo de board: é `--deadline`/config.

### Subfases

1. **Campos e semeadura** ✔ 2026-11-01 — `boardgraph/pertfields.py` + subcomando
   `boardgraph fields`; dry-run lista campos e sementes sem mutar; execução
   cria os 4 campos e semeia as tarefas (~135 mutações; exige escopo de
   escrita de project no `gh`).
2. **CPM** ✔ 2026-11-01 — `boardgraph/pert.py`: passe direto (ES/EF),
   regressivo (LS/LF), folga = LS − ES, crítico = menor folga do componente
   (caminho mais longo — com prazo folgado ninguém tem folga zero), por componente.
   Testes com rede pequena conferida à mão.
3. **PERT + calibração** — `TE=(O+4M+P)/6`, `σ=(P−O)/6`, `σ_caminho=√Σσ²`,
   `P(≤D)=Φ(...)` via `math.erf`; probabilidade por tarefa, milestone e
   projeto; fator de realidade das Done como cenário.
4. **Saídas** — `boardgraph schedule` → `out/pert.md` + `out/pert.json`;
   `render --style critical` nos dois emissores.
5. **Validação** — divergência real (`frontend#4/#5/#6` planejados 16 dias
   antes de `backend#18` terminar), suíte verde, documentação, merge.

### Limitações declaradas

- CPM ignora contenção de recursos: 13 pessoas/3 frentes não entram na conta.
- Nós isolados têm folga infinita; o caminho crítico é o do maior componente.
- `closedAt − start` inclui ociosidade → fator de realidade tende a otimismo.
- Tarefa sem estimativa cai para `M = Target − Start + 1` com aviso.

### Fora de escopo

Monte Carlo, nivelamento de recursos, issue fields, múltiplos deadlines.

### Regra do fluxo (branch `feat/pert-cpm`)

Cada subfase termina com: entregáveis visíveis → revisão com `@deslop` no
diff contra `main` → correções aplicadas → feedback do usuário antes da
próxima subfase.
