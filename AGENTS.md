# PastorAI - Contexto e Regras de Trabalho

SaaS de gestao pastoral para a jornada G12: ganhar, consolidar, discipular e
enviar. O produto usa WhatsApp, IA e billing, mas a tela principal deve ser
tratada como fila de trabalho pastoral e centro de decisoes, nao como BI
generico.

Esta frente usa Antigravity. Existe uma frente separada com Claude Code; nao
presuma contexto de conversa. Leia os documentos versionados antes de alterar
codigo.

## Stack

- Backend: FastAPI em `backend/`, entrada `backend/app/main.py`.
- Banco: PostgreSQL/Supabase com SQLAlchemy e RLS por `igreja_id`.
- Auth: Clerk.
- IA: LangGraph e credenciais BYO.
- WhatsApp: Evolution API.
- Billing: Asaas.
- Emails/convites: Brevo.
- Calendario: Google Calendar.
- Frontend: Next.js 14 App Router em `frontend/`, Clerk, PWA e mobile-first.

## Regras obrigatorias

1. Antes de qualquer feature, trabalhar em branch/worktree isolada.
2. Nunca trabalhar direto na `main`.
3. Nunca executar reset, checkout destrutivo, rebase, limpeza de arquivos ou
   delete recursivo sem autorizacao humana explicita.
4. Antes de editar, rode `git status --short --branch` e entenda arquivos
   modificados/nao rastreados.
5. Nunca commitar `.env` real, tokens, chaves, dumps ou credenciais.
6. Mudanca estrutural fora do PRD precisa atualizar PRD/SPEC ou registrar a
   decisao em docs.
7. Ao fechar sprint/bloco significativo, registrar em
   `docs/sprints/AAAA-MM-DD-titulo.md`.

## Seguranca multi-tenant

Todo endpoint e toda query de tenant devem respeitar `igreja_id`.

O role de conexao do Supabase pode ter `BYPASSRLS`, entao a seguranca depende de
aplicar corretamente o contexto de tenant:

- Requests autenticados usam `set_tenant_context` em `backend/app/db/rls.py`.
- Workers sem Clerk usam `set_tenant_context_for_igreja`.
- Ambos precisam cair em `SET LOCAL ROLE authenticated`.

Nao remover, contornar ou duplicar esse contrato sem plano e teste.

Excecao documentada: o console de plataforma usa `get_platform_admin` para
operacao cross-tenant via allowlist. Nao reutilizar esse caminho em endpoint
normal de igreja.

## Migrations

O historico `0001` a `0017` esta congelado. Novas migrations usam timestamp UTC:

```text
AAAAMMDD_HHMMSS_slug.sql
```

Aplicacao no Supabase e manual, em ordem alfabetica. Leia
`backend/migrations/README.md` antes de criar migration.

## Como explorar codigo

Este projeto possui `code-review-graph`. Quando disponivel, use o grafo antes
de grep/leitura ampla para entender impacto, dependencias e testes.

Se o grafo nao estiver indexado nesta worktree, registre isso e use busca
textual com cuidado.

## Fontes de verdade iniciais

Leia nesta ordem:

1. `AGENTS.md`
2. `docs/ANTIGRAVITY_HANDOFF.md`
3. `CLAUDE.md`
4. `SPEC_PROGRESS.md`
5. `SPEC.md`
6. `docs/Docs20260611_163530/PRD20260611_163530.md`
7. `docs/sprints/README.md`
8. Sprints recentes em `docs/sprints/`
9. `backend/migrations/README.md`

## Validacao minima

- Backend: rodar `pytest` dentro de `backend/`.
- Frontend: rodar `npm run typecheck` e `npm run build` dentro de `frontend/`.
- Auth/RLS/billing/WhatsApp exigem testes focados quando tocados.
- Mudanca visual precisa validacao em desktop e mobile.

## Antigravity

Antes de implementar qualquer feature, o Antigravity deve entregar relatorio de
entendimento e plano. Para tarefas grandes, usar artefato/plano revisavel antes
da execucao.
