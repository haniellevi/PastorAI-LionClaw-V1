# PastorAI — Contexto e Regras de Trabalho

SaaS de gestão pastoral (jornada G12: ganhar → consolidar → discipular → enviar) com WhatsApp, IA e billing. MVP gerado pelo pipeline `development-v2` do LionClaw (16 sprints). Repositório: https://github.com/haniellevi/PastorAI-LionClaw-V1

## Stack
- **Backend**: FastAPI (Python) em `backend/` — entry `app/main.py`. SQLAlchemy + PostgreSQL (Supabase), RLS por tenant (`igreja_id`). Auth Clerk. LangGraph (agente orquestrador). Migrations SQL em `backend/migrations/` — histórico `0001…0017` (numeração congelada); **novas migrations usam nome por timestamp** `AAAAMMDD_HHMMSS_slug.sql` (helper: `python scripts/new_migration.py "..."`), pra não colidir entre branches. Aplicação manual no Supabase, em ordem de nome. Ver `backend/migrations/README.md`.
- **Frontend**: Next.js 14 (App Router) em `frontend/` — Clerk, PWA, mobile-first.
- **Serviços externos**: Supabase, Clerk, Evolution API (WhatsApp), OpenAI, Asaas (billing), Brevo (e-mail de convite), Google Calendar.
- **Docs do pipeline**: `docs/Docs<id>/` (PRD, SPEC, sprints, design).

## Regras de Trabalho — SEGUIR SEMPRE

1. **Git é o seguro.** Antes de qualquer feature (manual ou pipeline), criar uma **branch nova**. Ao final, revisar `git diff` e commitar. Nunca trabalhar direto na `main` sem branch. Nada se perde, tudo é reversível.

2. **PRD x código alinhados.** Mudança **estrutural** fora do PRD → anotar no PRD/SPEC (`docs/Docs<id>/`). Ajuste **pequeno** (um botão, um CRUD) → não precisa. O PRD não pode virar ficção.

3. **Dividir por tamanho.** Pequeno/médio (CRUD, ajuste, correção) → **Claude Code direto** (nesta pasta). Módulo **grande/novo** → **pipeline** do LionClaw (ou Claude Code com um plano antes).

4. **Pipeline é incremental, nunca "regenerar do zero".** Cada feature nova = um pipeline novo, que **lê o código atual**. Nunca rodar o pipeline em modo reset/regenerar sobre código editado à mão — isso sobrescreve.

5. **PRD como checklist.** Usar o PRD (`docs/Docs<id>/PRD*.md`) como lista do que falta do MVP pra frente.

6. **Registrar o sprint.** Ao fechar um sprint/bloco de trabalho (ou quando o usuário disser "fecha o sprint"), gravar um resumo **versionado** em `docs/sprints/AAAA-MM-DD-titulo.md` (formato em `docs/sprints/README.md`) — além de atualizar a memória local. O grafo guarda "como o código é"; estes arquivos guardam "o que fizemos e por quê".

## Cuidados técnicos
- **RLS / multi-tenant**: todo endpoint e query respeita `igreja_id`. Nunca vazar dados entre igrejas. ⚠️ O role de conexão do Supabase (`postgres`) tem **BYPASSRLS**; por isso `set_tenant_context` (em `app/db/rls.py`) faz `SET LOCAL ROLE authenticated` — sem isso a RLS é ignorada e as queries vazam entre tenants. Não remover.
- **Backend `:8000`**: mudanças no backend só valem após reiniciar o uvicorn.
- **Testes**: rodar `pytest` (dentro de `backend/`, com o venv ativo) antes de commitar.
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
