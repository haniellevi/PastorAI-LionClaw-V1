# PastorAI — Contexto e Regras de Trabalho

SaaS de gestão pastoral (jornada G12: ganhar → consolidar → discipular → enviar) com WhatsApp, IA e billing. MVP gerado pelo pipeline `development-v2` do LionClaw (16 sprints). Repositório: https://github.com/haniellevi/PastorAI-LionClaw-V1

## Stack
- **Backend**: FastAPI (Python) em `backend/` — entry `app/main.py`. SQLAlchemy + PostgreSQL (Supabase), RLS por tenant (`igreja_id`). Auth Clerk. LangGraph (agente orquestrador). Migrations SQL em `backend/migrations/` (0001…0009).
- **Frontend**: Next.js 14 (App Router) em `frontend/` — Clerk, PWA, mobile-first.
- **Serviços externos**: Supabase, Clerk, Evolution API (WhatsApp), OpenAI, Asaas (billing), Brevo (e-mail de convite), Google Calendar.
- **Docs do pipeline**: `docs/Docs<id>/` (PRD, SPEC, sprints, design).

## Regras de Trabalho — SEGUIR SEMPRE

1. **Git é o seguro.** Antes de qualquer feature (manual ou pipeline), criar uma **branch nova**. Ao final, revisar `git diff` e commitar. Nunca trabalhar direto na `main` sem branch. Nada se perde, tudo é reversível.

2. **PRD x código alinhados.** Mudança **estrutural** fora do PRD → anotar no PRD/SPEC (`docs/Docs<id>/`). Ajuste **pequeno** (um botão, um CRUD) → não precisa. O PRD não pode virar ficção.

3. **Dividir por tamanho.** Pequeno/médio (CRUD, ajuste, correção) → **Claude Code direto** (nesta pasta). Módulo **grande/novo** → **pipeline** do LionClaw (ou Claude Code com um plano antes).

4. **Pipeline é incremental, nunca "regenerar do zero".** Cada feature nova = um pipeline novo, que **lê o código atual**. Nunca rodar o pipeline em modo reset/regenerar sobre código editado à mão — isso sobrescreve.

5. **PRD como checklist.** Usar o PRD (`docs/Docs<id>/PRD*.md`) como lista do que falta do MVP pra frente.

## Cuidados técnicos
- **RLS / multi-tenant**: todo endpoint e query respeita `igreja_id`. Nunca vazar dados entre igrejas. ⚠️ O role de conexão do Supabase (`postgres`) tem **BYPASSRLS**; por isso `set_tenant_context` (em `app/db/rls.py`) faz `SET LOCAL ROLE authenticated` — sem isso a RLS é ignorada e as queries vazam entre tenants. Não remover.
- **Backend `:8000`**: mudanças no backend só valem após reiniciar o uvicorn.
- **Testes**: rodar `pytest` (dentro de `backend/`, com o venv ativo) antes de commitar.
- **Segredos**: nunca commitar `.env` real — só `.env.example`. O `.gitignore` já protege.

## Onde trabalhar
Mudanças no PastorAI são feitas **nesta pasta** (esta conversa do Claude Code). O LionClaw é outra ferramenta (o app que gera/orquestra pipelines) — não editar o PastorAI de lá.

> Para um mapa de arquitetura mais completo, rode `/init` ou peça uma expansão deste arquivo.
