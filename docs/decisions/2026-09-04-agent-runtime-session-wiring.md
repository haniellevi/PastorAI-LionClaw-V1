---
status: integrated-main-inactive
date: 2026-09-04
decision: dedicated-agent-runtime-session-boundary
---

# Fronteira de sessão dedicada do agente WhatsApp

## Contexto

O worker recebe mensagens do WhatsApp pela Evolution e pode chamar o runtime
LangGraph. A sessão genérica da aplicação é privilegiada demais para ser a
fronteira final do agente. A D2A já definiu uma role `agent_runtime`, mas não
provisionou login, grants, credencial ou acesso às tabelas de domínio.

## Decisão candidata

O worker passa a aceitar uma fábrica de sessão dedicada explicitamente. A
produção só constrói essa fábrica quando `AGENT_RUNTIME_DATABASE_URL` existe e
autentica como `agent_runtime`, em URL distinta de `DATABASE_URL`. A ausência
da configuração desabilita o turno automático, mantendo a ingestão do worker
disponível; nunca há fallback silencioso para a conexão principal.

Cada sessão dedicada precisa iniciar uma transação nova e provar, antes da
consulta de domínio:

- `session_user` e `current_user` iguais a `agent_runtime`;
- `NOINHERIT`, `NOBYPASSRLS`, sem superusuário, memberships ou privilégios de
  criação/replicação;
- `row_security=on` e `search_path=pg_catalog, agent_private`;
- `app.tenant_igreja_id` igual ao tenant derivado da mensagem persistida;
- `agent_private.current_tenant_id()` igual ao mesmo tenant.

O runtime repete a prova quando recebe uma sessão marcada como dedicada. O
pool rejeita conexões com GUC de tenant ou `search_path` persistidos de outro
turno. A rota de compatibilidade para testes e integrações antigas continua
separada e não é usada pelo entrypoint `main` quando a fábrica dedicada está
disponível.

## Limites

Esta decisão não cria grants, views, políticas RLS, role LOGIN, segredo ou
migration. Com o `search_path` privado atual, consultas ORM às tabelas em
`public` continuam deliberadamente indisponíveis até um contrato de acesso
explícito. Também não liga o LangGraph a memória, checkpointer, relatório de
célula, consentimento operacional, `AgentConfig`, outbox ou envio Evolution.

O próximo desenho deve escolher o menor conjunto de projeções/views e funções
de domínio necessárias ao primeiro fluxo textual, sem expor credenciais LLM,
mensagens gerais ou writers mutáveis ao role dedicada. A migration só pode ser
proposta depois de teste em PostgreSQL 17 descartável, com RLS cross-tenant,
pool reuse, rollback e aplicação idempotente.

## Evidência local

Commit candidato: `b832bab` (`feat: wire agent runtime to dedicated session`).
Os testes focalizados, `git diff --check`, compilação Python e validação estática
do compose passaram. A suíte offline ampla ainda possui falhas preexistentes de
layout/permissões dos entrypoints legados de captura e reconciliação; elas não
foram mascaradas nem corrigidas por esta decisão.

`operational_authorization=false` e `next_stage_authorized=false` permanecem
estritos. Nenhum banco, DEV, PROD, migration, runner, deploy ou mensagem foi
acessado.

## Integração em main (PR #368, 2026-09-04)

A decisão foi integrada pela PR #368 no merge
`ec0fee244088a2d0657cb5510ad8b5661f2b872b` (parent 1 `66f1cda`, parent 2
`fa08683`), cuja árvore coincide com a do head. Os 14 checks da PR e os 13
check-runs pós-merge concluíram com sucesso. O Vercel Production automático
decorrente prova somente o frontend Next.js.

Essa integração não alterou o limite funcional: a role continua sem login,
segredo, grants em `public`, views ou funções de domínio. A ausência de
`AGENT_RUNTIME_DATABASE_URL` continua desabilitando turnos automáticos sem
prejudicar a ingestão; a presença da URL não constitui atestação nem ativa o
agente. Nenhuma migration foi aplicada, nem houve acesso a banco, DEV, PROD,
caller, envio, `AgentConfig` ou flag.

## Próximo gate

`OWNER_AUTHORIZE_DESIGN_AGENT_RUNTIME_PROJECTION_CONTRACT` — contrato offline
de projeções e writers mínimos, com testes PostgreSQL 17 descartáveis. Não
autoriza provisionar credenciais, aplicar migration em ambiente compartilhado,
ativar o agente ou enviar mensagens.
