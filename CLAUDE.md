# PastorAI — Contexto e Regras de Trabalho

SaaS de gestão pastoral (jornada G12: ganhar → consolidar → discipular → enviar) com WhatsApp, IA e billing. MVP gerado pelo pipeline `development-v2` do LionClaw (16 sprints). Repositório: https://github.com/haniellevi/PastorAI-LionClaw-V1

## Stack
- **Backend**: FastAPI (Python) em `backend/` — entry `app/main.py`. SQLAlchemy + PostgreSQL (Supabase), RLS por tenant (`igreja_id`). Auth Clerk. LangGraph (agente orquestrador). Migrations SQL em `backend/migrations/` — nome `AAAAMMDD_HHMMSS_slug.sql`, aplicadas uma a uma com `python scripts/migrate.py` (DEV primeiro; PROD com backup antes). Ver `backend/migrations/README.md`.
- **Frontend**: Next.js 15.5.25 (App Router) em `frontend/` — Clerk, PWA, mobile-first.
- **Serviços externos**: Supabase, Clerk, Evolution API (WhatsApp), OpenAI, Asaas (billing), Brevo (e-mail de convite), Google Calendar.
- **Docs do pipeline**: `docs/Docs<id>/` (PRD, SPEC, sprints, design).

## Regras de Trabalho — SEGUIR SEMPRE

### Guia operacional: MVP enxuto

A fonte de verdade para prioridade, fases e regras é
`docs/ops/MVP-PLANO-SIMPLIFICACAO.md`. Leia antes de começar qualquer trabalho.
`docs/ops/V1-FINALIZATION-MAP.md` e a governança de migration/consentimento
(E4B, D3, D6, D2A, atestações, catálogo) são **históricos e pausados**
(branch `archive/governanca-2026-09`): não abra missão nova nessas frentes
antes da Fase 5 do plano.

Regras do MVP:
- **Uma fatia vertical por vez**, na ordem do plano; cada fatia termina em algo
  que um pastor ou contato usa, testado de ponta a ponta (mensagem real no
  número de teste quando envolver WhatsApp).
- **PR pequeno, merge rápido, `main` sempre implantável.** CI obrigatório:
  `backend-tests`, `frontend-ci`, `e2e-critical`, `rls-integration`.
- **Sem testes que congelam hash de arquivo ou leem texto de documento.**
- **Documentação mínima:** atualizar o plano e registrar a fatia em
  `docs/sprints/`. Sem ADR por fatia.
- **Revisão independente (Sarah) só** para migration em PROD e mudanças de
  RLS/autenticação.
- Travas que ficam: RLS por `igreja_id`, segredos fora do git, opt-out,
  `ALLOW_REAL_SENDS` + lista de igrejas piloto, `AgentConfig.ativo`, backup
  antes de migration em PROD, termo LGPD na primeira conversa.

Use o code-review-graph antes de Grep/Read quando ele estiver no commit atual.

1. **Git é o seguro.** Antes de qualquer feature (manual ou pipeline), criar uma **branch nova**. Ao final, revisar `git diff` e commitar. Nunca trabalhar direto na `main` sem branch. Nada se perde, tudo é reversível.

2. **PRD x código alinhados.** Mudança **estrutural** fora do PRD → anotar no PRD/SPEC (`docs/Docs<id>/`). Ajuste **pequeno** (um botão, um CRUD) → não precisa. O PRD não pode virar ficção.

3. **Dividir por tamanho.** Pequeno/médio (CRUD, ajuste, correção) → **Claude Code direto** (nesta pasta). Módulo **grande/novo** → **pipeline** do LionClaw (ou Claude Code com um plano antes).

4. **Pipeline é incremental, nunca "regenerar do zero".** Cada feature nova = um pipeline novo, que **lê o código atual**. Nunca rodar o pipeline em modo reset/regenerar sobre código editado à mão — isso sobrescreve.

5. **PRD como checklist.** Usar o PRD (`docs/Docs<id>/PRD*.md`) como lista do que falta do MVP pra frente.

6. **Registrar o sprint.** Ao fechar um sprint/bloco de trabalho (ou quando o usuário disser "fecha o sprint"), gravar um resumo **versionado** em `docs/sprints/AAAA-MM-DD-titulo.md` (formato em `docs/sprints/README.md`) — além de atualizar a memória local. O grafo guarda "como o código é"; estes arquivos guardam "o que fizemos e por quê".

## Cuidados técnicos
- **RLS / multi-tenant**: todo endpoint e query respeita `igreja_id`. Nunca vazar dados entre igrejas. ⚠️ O role de conexão do Supabase (`postgres`) tem **BYPASSRLS**; por isso `set_tenant_context` (em `app/db/rls.py`) faz `SET LOCAL ROLE authenticated` — sem isso a RLS é ignorada e as queries vazam entre tenants. Não remover.
- **Backend `:8000`**: mudanças no backend só valem após reiniciar o uvicorn.
- **Testes**: rodar `./test-local.sh` (raiz) antes de commitar — usa Python 3.13 (`backend/.venv-runtime`), Node 24 (`.nvmrc`) e `umask 022`, iguais ao CI. O `backend/.venv` antigo (3.12) e o Node global (26) geram falhas falsas.
- **Segredos**: nunca commitar `.env` real — só `.env.example`. O `.gitignore` já protege.

## Onde trabalhar
Mudanças no PastorAI são feitas **nesta pasta** (esta conversa do Claude Code). O LionClaw é outra ferramenta (o app que gera/orquestra pipelines) — não editar o PastorAI de lá.

> Para um mapa de arquitetura mais completo, rode `/init` ou peça uma expansão deste arquivo.

<!-- code-review-graph MCP tools -->
## MCP Tools: code-review-graph

**IMPORTANT: This project has a knowledge graph. ALWAYS use the
code-review-graph MCP tools BEFORE using Grep/Glob/Read to explore
the codebase.** The graph is faster, cheaper (fewer tokens), and gives
you structural context (callers, dependents, test coverage) that file
scanning cannot.

### When to use graph tools FIRST

- **Exploring code**: `semantic_search_nodes` or `query_graph` instead of Grep
- **Understanding impact**: `get_impact_radius` instead of manually tracing imports
- **Code review**: `detect_changes` + `get_review_context` instead of reading entire files
- **Finding relationships**: `query_graph` with callers_of/callees_of/imports_of/tests_for
- **Architecture questions**: `get_architecture_overview` + `list_communities`

Fall back to Grep/Glob/Read **only** when the graph doesn't cover what you need.

### Key Tools

| Tool | Use when |
| ------ | ---------- |
| `detect_changes` | Reviewing code changes — gives risk-scored analysis |
| `get_review_context` | Need source snippets for review — token-efficient |
| `get_impact_radius` | Understanding blast radius of a change |
| `get_affected_flows` | Finding which execution paths are impacted |
| `query_graph` | Tracing callers, callees, imports, tests, dependencies |
| `semantic_search_nodes` | Finding functions/classes by name or keyword |
| `get_architecture_overview` | Understanding high-level codebase structure |
| `refactor_tool` | Planning renames, finding dead code |

### Workflow

1. The graph auto-updates on file changes (via hooks).
2. Use `detect_changes` for code review.
3. Use `get_affected_flows` to understand impact.
4. Use `query_graph` pattern="tests_for" to check coverage.
