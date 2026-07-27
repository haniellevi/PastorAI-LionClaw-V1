# Igreja 12 — fonte de verdade de produto e código

**Data-base:** 2026-07-27
**Commit auditado (baseline real):** `4e71c47c5e8a6804bf57b59c35d90898e8fd5459` (`origin/main`, pós PR#210)
**Missão:** SOURCE-TRUTH-1 — reconciliação documental antes do Discovery mestre / VIS-2.
**Escopo desta missão:** somente documentação. Nenhum código, dependência, ambiente,
migration, deploy ou worktree existente foi tocado.

**Substitui como referência operacional:** `docs/audits/2026-07-18-project-source-of-truth.md`
(baseline `ceef64d`), que por sua vez substituiu `docs/audits/2026-07-10-project-source-of-truth.md`
(baseline `ac6f706`). **Os documentos anteriores permanecem versionados como histórico** —
não foram apagados nem editados. Este é o documento a ler no bootstrap; os anteriores
respondem "como estava em julho", não "como está agora".

---

## 1. Como usar esta fonte

Ordem de confiança, da maior para a menor:

1. `origin/main` e o código executável.
2. Este documento — estado funcional, insumos disponíveis e ordem das próximas missões.
3. `code-review-graph` — estrutura, impacto, callers e testes do código atual.
4. `graphify-out/graph.json` — arquitetura ampla, código e documentos.
5. Smokes em DEV/PROD comprovam ativação operacional. **Merge não comprova deploy.**

Antes de implementar, a conversa deve confirmar que o commit-base do grafo e o commit do
worktree são iguais. Se divergirem, o código vence e o grafo deve ser reconstruído.

**Regra que originou esta missão:** um documento só é fonte de verdade se estiver
versionado em `origin/main`. Insumo que vive apenas no checkout local de uma máquina não
é fonte de verdade — é material em risco de perda. A seção 3 corrige isso para os quatro
insumos que ainda estavam fora.

---

## 2. Fonte canônica (versionada em `origin/main`)

### 2.1 Produto e design — já versionados

Estes arquivos **já estão em `origin/main`** e são canônicos. Se aparecerem como
"untracked" em algum checkout, isso indica que aquele checkout está num commit antigo —
não que o arquivo esteja fora do Git.

| Arquivo | Papel |
|---|---|
| `PRODUCT.md` | Porta de entrada de produto; aponta o PRD consolidado |
| `DESIGN.md` | Contrato visual e identidade "Diamante Lapidado" |
| `SPEC.md` / `SPEC_PROGRESS.md` | Contrato técnico e cronologia |
| `docs/design/` (20 arquivos na baseline `4e71c47`) | Auditoria UX/UI, identidade visual, plano mestre de refatoração, PRDs de célula, contratos de UX, protótipo standalone. Esta missão soma mais 3 — ver seção 3 |
| `docs/decisions/` | Decisões de fechamento do MVP (18/07) e diretrizes pós-MVP (20/07) |
| `docs/audits/` | Esta fonte e as anteriores (10/07, 18/07) |
| `docs/security/` | Plano de remediação, revalidação BAIXO, aceitação de risco dev-only |
| `docs/sprints/` | História operacional: merge, deploy, migration, smoke |
| `docs/ops/PROD-ENV-RUNBOOK.md` | Runbook de ambiente de produção |

**PRD canônico:** `docs/Docs20260611_163530/PRD20260611_163530.md` (RF-01..49, US-01..43,
RNF-01..25), apontado por `PRODUCT.md`. Os PRDs em `docs/Docs20260704_*` são recortes
posteriores, menos completos — não usar como checklist do MVP.

### 2.2 Stack real na baseline

Confirmado em `frontend/package.json` no commit `4e71c47`:

- **Next.js `15.5.22`** (dist-tag `backport`) — **não é mais Next 14**.
- React / React-DOM `19.2.7`.
- `@clerk/nextjs` `6.39.6`.
- Overrides sobre `next`: `postcss` `8.5.23`, `sharp` `0.35.3`.

Backend segue FastAPI + SQLAlchemy + PostgreSQL (Supabase) com RLS por `igreja_id`.

### 2.3 Estado funcional confirmado

**MVP concluído e em produção.** O veredito M10
(`docs/sprints/2026-07-20-fechamento-mvp.md`, baseline `37e4cd3`) fecha os 49 requisitos
funcionais e as 43 user stories do PRD consolidado. Nenhum requisito do PRD ficou
descoberto. **FECH-2** (OPTIN-1, REATIVAR-1, ROTULO-1, AGENDA-ORD-1) foi concluído em
código, com migration aplicada em DEV/PROD e deploy de backend e frontend.

### 2.4 Delta entre 2026-07-18 (`ceef64d`) e esta baseline (`4e71c47`)

49 commits, 20 merges. O que importa para as próximas missões:

| Bloco | PRs | Estado |
|---|---|---|
| Docs retroativos de release de frontend, sync SPEC/SoT, revalidação SEC BAIXO | #192, #193, #194 | Mergeados |
| UNIQ-PESSOA-1 (unicidade de telefone por igreja) | #195 | Mergeado + deployado |
| Veredito M10 do fechamento do MVP | #196 | Mergeado |
| Diretrizes pós-MVP do dono (9 diretrizes) | #197 | Mergeado |
| FECH-2 (4 refinamentos) + release record | #198, #199, #200 | Mergeado + deployado |
| SEC-DEP-2 — Next 14.2.35 (série 14, depois superada) | #201, #202 | Mergeado |
| SEC-DEP-3A — Next 15.5.20 + React 19.2.7 | #203 | Mergeado |
| SEC-DEP-3B — Clerk 6.39.6 | #204 | Mergeado |
| SEC-DEP-3C — PostCSS 8.5.10 | #205 | Mergeado |
| SEC-DEP-3D — override `sharp` 0.35.3 (GHSA-f88m-g3jw-g9cj) | #206 | Mergeado |
| SEC-DEP-3E — Next 15.5.22 + PostCSS 8.5.23 (**dependências/código**) | #207 | Mergeado + **publicado em PROD 2026-07-27** (`0a011fb`, deployment `dpl_GYpYmkyv78u6vjrC1AhYyEtnkARU`, READY) |
| SEC-DEP-3EF-REL-1 — registro da release `0a011fb` em `docs/sprints/` (**documental**) | #208 | Mergeado (`2cfcc02`); não altera runtime |
| META-TITLE-1 — título do Console da plataforma | #209 | Mergeado + **deployado em PROD 2026-07-27** (`0de9da9`) |
| SEC-DEP-4A — atualizações dev-only (js-yaml, brace-expansion, @types/node) | #210 | Mergeado (`4e71c47`); **deploy não autorizado** |

**Ponto de atenção operacional:** o deploy de 27/07 do frontend entregou de uma vez o
conteúdo de #205, #206 e #207 — nenhum deles havia sido publicado isoladamente antes.
`docs/sprints/2026-07-27-release-sec-dep-3ef-0a011fb.md` registra o detalhe, incluindo o
risco residual do smoke de `sharp` em Linux.

**Lacuna documental conhecida:** PR#209 e PR#210 ainda não têm registro em `docs/sprints/`.
Não bloqueia o Discovery; é dívida de evidência.

---

## 3. Insumos de design — reconciliados nesta missão

Quatro arquivos úteis viviam **apenas no checkout principal local**, fora do Git. Esta
missão os trouxe para `origin/main` **copiando** — as fontes no checkout principal não
foram editadas nem removidas.

| Destino versionado | Origem | Natureza |
|---|---|---|
| `docs/design/pontos-melhoria.md` | `pontos-melhoria.md` (raiz do checkout principal) | Backlog levantado durante a auditoria visual |
| `docs/design/PROMPT-CLAUDE-CODE-FABLE-REFATORACAO-VISUAL.md` | mesmo caminho | Prompt executor do Gate 4 da refatoração visual |
| `docs/ops/DEV-SMOKE-USERS.md` | mesmo caminho | Regra de uso das contas de smoke DEV |
| `docs/design/prototypes/igreja12-quiet-operations/index.html` | mesmo caminho | Protótipo visual autocontido (67.825 bytes) |

### 3.1 `pontos-melhoria.md` é insumo, não decisão canônica

O documento lista 15 oportunidades (4 P1, 8 P2, 3 P3) encontradas durante a auditoria visual:
onboarding real, dependência célula-antes-de-convite, governança do agente, estado de
módulo desativado por flag, busca global, atalhos, rascunho de formulário, ações em lote,
histórico de atividade, ajuda contextual, persistência de posição na Jornada,
notificações, personalização por igreja, telemetria e importação de Pessoas.

**Nada ali é requisito aprovado.** O próprio documento declara que cada item exige
discovery, decisão de produto e validação própria antes de implementação. Ele **não**
altera o PRD, **não** reabre o veredito M10 e **não** entra em VIS-2. Serve como pauta
para um ciclo de produto posterior — depois de entrevistas com pastor, administrador
recém-chegado e líder de célula mobile, conforme o próprio doc recomenda.

### 3.2 `DEV-SMOKE-USERS.md` — generalização aplicada

O arquivo original citava um caminho absoluto de máquina
(`C:\Users\...\usuario-dev.md`). A versão versionada aponta para
`<raiz-do-checkout-principal>/usuario-dev.md`. **Nenhuma credencial foi copiada** —
`usuario-dev.md` continua fora do Git e fora deste worktree, como sempre foi.

### 3.3 `PROMPT-CLAUDE-CODE-FABLE-...` é **insumo histórico**, não roteiro de execução

O prompt foi versionado para preservar a direção criativa aprovada pelo dono — a estrutura
`Quiet Pastoral Operations` e a camada de identidade `Diamante Lapidado`. **Essa parte
continua válida e é o que VIS-2 deve consumir.**

O que **não** vale mais são as duas instruções de processo, ambas escritas quando os
documentos de design ainda não estavam no Git:

| Onde | O que manda fazer | Por que não vale |
|---|---|---|
| Linha 3 | "continuar na **MESMA CONVERSA** do Claude Code que concluiu os Gates 1–3"; não abrir conversa nova | Aquela conversa não existe mais como contexto recuperável. O protocolo desta fonte (seção 6) exige **conversa nova por missão independente** |
| Linha 72 | Se as fontes não existirem no worktree, lê-las "pelo caminho absoluto do checkout principal" | As fontes citadas (`DESIGN.md`, `docs/design/IDENTIDADE-VISUAL-DIAMANTE-LAPIDADO-IGREJA12.md` e as demais) **já estão em `origin/main`**, junto dos quatro insumos da seção 3. Seguir a linha 72 levaria o executor ao checkout principal detached em `9121abb` — o antipadrão que este documento combate |

**Como VIS-2 deve rodar, sobrepondo o prompt:** conversa nova, worktree limpo criado de
`origin/main`, e **todas as fontes lidas do próprio worktree**. O prompt entra como
referência de direção visual e de critérios de gate — não como instrução de processo.

O texto do prompt não foi reescrito: alterá-lo estava fora do escopo desta missão e o
insumo tem valor justamente por registrar a decisão como o dono a formulou. Esta seção é
o registro canônico da ressalva.

**Única diferença em relação à fonte no checkout principal:** a linha 3 teve o whitespace
final removido — normalização não semântica, para que `git diff --check` passe. Nenhum
caractere de conteúdo foi alterado em nenhuma linha do arquivo.

### 3.4 PNGs de referência — deliberadamente fora do Git

A pasta `docs/design/prototypes/igreja12-quiet-operations/` contém, no checkout
principal, quatro capturas de referência somando **4.974.251 bytes** (~4,7 MiB):

- `reference-dashboard-desktop.png` — 1.240.994 bytes
- `reference-dashboard-mobile.png` — 1.085.748 bytes
- `reference-conversas-desktop.png` — 1.188.524 bytes
- `reference-central-desktop.png` — 1.458.985 bytes

**Decisão: ficam fora do Git.** Razões verificadas nesta baseline:

1. **O `index.html` não os usa.** Grep por `.png`, `<img>` e `url(` no protótipo não
   retorna nenhuma referência a arquivo de imagem. O único `background-image` (linha 83)
   é composto por `radial-gradient` e `linear-gradient` — CSS puro. O protótipo abre e
   renderiza completo sem os PNGs.
2. **Não há Git LFS configurado no repositório.** Versionar ~4,7 MiB de binário entraria
   direto no histórico, permanentemente, sem ganho funcional.
3. **Não bloqueiam o Discovery.** São capturas de apoio à conversa de design; a direção
   visual canônica está em `DESIGN.md`,
   `docs/design/IDENTIDADE-VISUAL-DIAMANTE-LAPIDADO-IGREJA12.md` e
   `docs/design/PLANO-MESTRE-REFATORACAO-VISUAL-IGREJA12.md` — todos já versionados.

Quem precisar das capturas as encontra no checkout principal local. **Ausência de PNG não
é motivo para adiar VIS-2 nem o Discovery mestre.**

---

## 4. Pendências de produto (backlog aberto)

Fonte: `docs/decisions/2026-07-20-diretrizes-pos-mvp-paineis-papeis-visual.md` e o veredito
M10. Nada aqui reabre o MVP — tudo é evolução.

| Pacote | Diretrizes | Tamanho / via | Estado |
|---|---|---|---|
| **VIS-2** | 2 (Minha Célula), 3 (Agenda), 4 (espaçamentos/botões globais) | Missões Claude Code diretas, padrão W-series, com validação visual do dono antes do merge | **Discovery pronto e agora integralmente versionado** (seção 3) |
| **PAPEL-1** | 1, 5, 6 — painéis por papel, visibilidade por escopo, "liderança do Ganhar" | Módulo grande → design + decisões do dono → pipeline novo | **Bloqueado por 3 decisões do dono** (abaixo) |
| **EDU-1** | 9 — telas restritas em modo educativo | Médio; depende do mapa de acessos do PAPEL-1 | Depois ou junto do PAPEL-1 |
| **ARVORE-1** | 7 — árvore ascendente/descendente com privacidade por direção | Roadmap | Especificar quando abrir |
| **CAPDESTINO-1** | 8 — Capacitação Destino / Universidade da Vida por papel | Roadmap; maior módulo novo | Telas hoje `locked-em-breve` |

**Regra transversal já decidida pelo dono:** área restrita sem ensinamento possível →
esconder do papel sem privilégio; área restrita com conteúdo pedagógico → mostrar em modo
educativo.

**Decisões do dono que bloqueiam a spec do PAPEL-1:**

1. Quem é a "liderança do Ganhar" — papel novo ou atribuição a papel existente?
2. Membro comum passa a acessar o painel web (muda a persona do PRD)? Já no PAPEL-1 ou
   começa por líderes?
3. Quais detalhes a participação na Universidade da Vida libera na consolidação?

**Dívidas de evidência (não são funcionalidade):**

- Smoke funcional pendente de OPTIN-1 e REATIVAR-1 (FECH-2 deployado; 2 smokes BLOCKED por
  ausência de dados elegíveis).
- Billing (cobrança real Asaas) em produção sem smoke autenticado versionado.
- Registro de sprint ausente para PR#209 e PR#210.
- Risco residual aceito: `GHSA-mh99-v99m-4gvg` dev-only
  (`docs/security/2026-07-27-sec-dep-4a-dev-only-risk-acceptance.md`); BAIXO-002 (FORCE RLS
  ausente) e BAIXO-010 (JWT em localStorage) aceitos pós-MVP.

---

## 5. Resíduos da raiz antiga (fora do Git)

O checkout principal (`C:\...\workspace\PastorAi-1.0`) está num commit antigo e detached
(`9121abb`) e acumulou artefatos de um pipeline v1 que travou em 2026-07-17. **Nenhum
deles é fonte de verdade.** Estão listados aqui para que ninguém os confunda com
documentação viva:

| Resíduo | Por que é resíduo |
|---|---|
| `PRD.md`, `PRD-LOTE-1.md`, `DISCOVERY-LOTE-1.md`, `stories-requisitos.md`, `discovery-notes.md` | Saída do pipeline v1 travado; o conteúdo (W5A + dedupe por tenant) **já foi entregue** por FECH-1/M5 |
| `.prd-validation-report.md`, `validation-report.md` | Relatórios do mesmo pipeline travado |
| `before.png` (13 KB, raiz) | Captura solta de uma missão visual antiga |
| `output/pdf/Igreja12-visao-geral-2026-07-16.pdf` | Artefato gerado, não fonte |
| `.codex/`, `.playwright-mcp/` | Diretórios de ferramenta local |

**Atenção ao ler o checkout principal:** por estar em `9121abb`, arquivos que **já são
canônicos em `origin/main`** aparecem lá como untracked — `PRODUCT.md`, `DESIGN.md`,
`docs/design/AUDITORIA-UX-UI-IGREJA12-2026-07-11.md`,
`docs/design/IDENTIDADE-VISUAL-DIAMANTE-LAPIDADO-IGREJA12.md`,
`docs/design/PLANO-MESTRE-REFATORACAO-VISUAL-IGREJA12.md`. Isso é artefato do commit
antigo, **não** ausência no Git. Ver seção 2.1.

### 5.1 Plano LionClaw antigo — permanece fora do Git

`docs/plans/2026-07-21-plano-conclusao-prd-pipeline-lionclaw.md` (17 KB, no checkout
principal) **não é trazido para `origin/main`.** Motivos:

- **Desatualizado.** Declara `origin/main` = `504d702` e trata PR2 Clerk e PR3 PostCSS como
  pendentes. Ambos foram mergeados (#204, #205), e a cadeia seguiu até #210 — a baseline
  do plano está sete PRs atrás.
- **Contraditório.** Descreve os insumos de design como "untracked na raiz" e o plano de
  execução como se a decisão do dono ainda estivesse aberta, enquanto a memória de trabalho
  e o chat registram a decisão posterior (2026-07-21, **PASS COM AJUSTES**, com seis ajustes
  no prompt do Discovery e ordem de execução própria). Versioná-lo criaria duas verdades
  concorrentes sobre o mesmo assunto.

Ele continua legível no checkout principal para consulta histórica. **Não usar como plano
de execução.** A ordem válida das próximas missões é a da seção 4 deste documento.

### 5.2 Limpeza da raiz antiga é missão separada

Esta missão **não** removeu, moveu nem editou nada no checkout principal — por decisão de
escopo.

**Estado do housekeeping de worktrees:** já avançou. O inventário de 2026-07-20 era
read-only, mas **HOUSEKEEPING-7A executou depois**: removeu os **worktrees** classificados
`SAFE_REMOVE` que estavam autorizados e fez prune dos registros autorizados.

**Quantos worktrees existem agora é estado operacional, não fato documental.** Muda a cada
worktree criado ou removido, inclusive por conversas paralelas. Este documento
deliberadamente não fixa esse número — **consulte sempre ao vivo**:

```bash
git worktree list
```

**Branches não foram tocadas.** O HOUSEKEEPING-7A **não removeu nenhuma branch**, local ou
remota. A limpeza de branches continua sendo **missão separada**, com auditoria e
autorização próprias — não deriva da autorização dada ao 7A nem pode ser executada de
carona nela.

O inventário de 20/07 preservava explicitamente `wip/antigravity-resgate` como `KEEP`, por
conter a única cópia de Dockerfile e do `.env.example` de deploy. Nenhum documento de
housekeeping está versionado no repositório; o histórico dessa trilha vive na memória de
trabalho, não em `docs/`.

**O que continua pendente é outra coisa:** a limpeza dos **resíduos da raiz antiga**
listados na seção 5 (artefatos do pipeline v1 travado, `before.png`, `output/`,
diretórios de ferramenta) e a decisão sobre o **próprio checkout principal**, hoje detached
em `9121abb`. Isso não foi tocado pelo HOUSEKEEPING-7A e exige conferência item a item com
o dono, porque parte do material pode ser cópia local única.

**Abrir como missão própria** (sugestão de rótulo: `HOUSEKEEPING-2`), depois do Discovery
mestre. Nada aqui bloqueia VIS-2 nem o Discovery.

---

## 6. Protocolo para novas conversas Claude Code

1. Abrir conversa nova por missão independente.
2. `git fetch origin --prune`.
3. Criar worktree limpo de `origin/main`; nunca reutilizar checkout antigo — em especial,
   **não usar o checkout principal**, que está detached em commit antigo.
4. Ler **este documento** (27/07) e o documento específico da missão.
5. Rodar `code-review-graph status`; o commit deve corresponder ao worktree.
6. Consultar CRG antes de Grep/Read. Usar Graphify para arquitetura e documentação.
7. Explicar contrato e escopo antes de editar.
8. Implementar em PR draft atômico; sem ready/merge/deploy sem autorização.
9. Revisão separada: implementador → revisor limpo → gate externo.
10. Relatar `PASS / FAIL / BLOCKED / SKIP` e sempre indicar o papel usado no smoke.

## 7. Cadência dos grafos

- **CRG:** rebuild no início de cada worktree importante; update depois dos edits.
- **Graphify estrutural:** `graphify update . --force` após blocos relevantes.
- **Graphify semântico:** rebuild periódico quando docs/PRD mudarem bastante.
- **Fechamento:** registrar merge/deploy/smoke em `docs/sprints/`. O grafo guarda "como o
  código é"; `docs/sprints/` guarda "o que fizemos e por quê". Um não substitui o outro.
