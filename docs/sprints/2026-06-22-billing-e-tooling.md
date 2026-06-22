# Correção de billing + ferramentas de contexto — 2026-06-22

**Branch:** `feat/master-console`  ·  **Commit:** `9ae36f4`  ·  **Deploy:** sim (backend VPS + frontend Vercel)

## O que foi feito
- **Correção de preço dos planos** (alinhamento ao catálogo `planos`/PRD):
  - `backend/app/domain/billing.py` `PLAN_PRICE` e `frontend/src/lib/subscription-api.ts` `PLAN_CATALOG`
    corrigidos de **97/197/397 → 199/299/399** (era o valor que o Asaas cobrava errado).
  - Deixado `TODO` no `billing.py` para futuramente ler da tabela `planos` (resolver direto com Asaas).
- **Deploy verificado em produção:** backend via tar→VPS (`docker compose up -d --build`),
  smoke `plan_price` retornou **`199.0 399.0`**; frontend `vercel --prod` aliased `app.igreja12.com.br`.
- **Sistema de registro de sprint** criado: esta pasta `docs/sprints/` + hook `PreCompact` de lembrete
  + convenção no `CLAUDE.md`.

## Decisões
- **Billing:** por ora só trocar os números; ler de `planos` no checkout fica para depois (mexe no Asaas).
- **Ferramentas de contexto** (graphify × CRG): papéis separados —
  - **CRG (code-review-graph)** = motor sempre-ligado para navegação de código (grafo barato,
    auto-atualizado por hook, sem LLM). É o que mais economiza token no dia a dia.
  - **graphify** = snapshot amplo periódico (código + PRD/docs), via LLM, manual — nunca automático.
- **CRG MCP estava `Pending approval`** → habilitado via `enabledMcpjsonServers` no `.claude/settings.json`
  (precisa reiniciar o Claude Code para os tools aparecerem).

## Pendente / próximo passo
- **Reiniciar o Claude Code** para o servidor MCP `code-review-graph` carregar (tools `query_graph`,
  `semantic_search_nodes`, etc.) — aí a regra do `CLAUDE.md` ("usar o grafo antes de Grep/Read") passa a valer.
- **graphify:** rodar o snapshot inicial (código + docs/PRD) — em andamento nesta sessão.
- Billing: ler de `planos` no checkout (slice à parte, toca o Asaas).
- Tela de Assinatura do tenant ainda usa catálogo fixo — religar para ler `planos`.

## Verificação
- `pytest tests/test_billing_domain.py tests/test_platform_admin.py` verde.
- `tsc --noEmit` (frontend) limpo.
- Smoke produção: `plan_price('ate_100')=199.0`, `plan_price('acima_201')=399.0`.
