# Auditoria independente da V1 em produção — 2026-08-22

**Branch:** `codex/v1-production-audit-20260821` · **Deploy:** não; auditoria
read-only e documentação

## O que foi feito

- Revalidado GitHub: PRs #274/#275 integradas, tag anotada `v1.0.0` no SHA de
  código `281e69c2...` e GitHub Release público.
- Revalidado o monitor agendado `32544604262` e sondas públicas de `/health` e
  `/ready`.
- Revalidado Vercel: deployment de produção mais recente `READY`, três aliases
  no SHA de código, headers M06 presentes e zero erro agregado em 24 horas.
- Revalidado Supabase PROD: `ACTIVE_HEALTHY`, PostgreSQL 17, 53/53 tabelas com
  RLS, M06/M01 e ledger íntegros; um `WARN` aceito e 75 `INFO` de performance.
- Corrigida a evidência detalhada, que ainda se declarava
  `V1_RELEASE_READY`, e atualizado o mapa/runbook.
- Criado `docs/ops/POST-V1-MISSION-REGISTER.md` como memória operacional para
  as próximas missões.

## Decisões

- A V1 permanece `V1_ENCERRADA`; commits documentais posteriores não alteram
  o SHA imutável do release.
- O SSH temporário já revogado não foi recriado apenas para esta auditoria.
  Symlink, restart counters, flags e manifesto de backup continuam sustentados
  pela prova original de fechamento.
- A PR #257 é pós-V1 e precisa ser atualizada/revalidada antes de integração.
- O SHA histórico `05c0aad...` de Células não foi encontrado localmente nem no
  GitHub e deixou de ser tratado como artefato comprovado.

## Verificação

- Git remoto atualizado por `git fetch --prune --tags origin`.
- Frontend `app.`, `admin.` e `painel.`: HTTP 200 e headers de segurança.
- Backend: `/health = ok`; `/ready = ready`; database, Redis, Evolution e três
  workers em `ok`.
- Vercel: `gitCommitSha = 281e69c2...`, deployment `READY`.
- Supabase: 53 tabelas públicas, zero sem RLS, quatro policies M06 exatas,
  zero ACL exposta nas tabelas fechadas e zero autoupgrade `prepared` inválido.
- Changelog Supabase consultado; as breaking changes recentes de Management
  API de logs, pinning de extensões, Realtime e self-hosted não atingem os
  caminhos usados por esta auditoria.

## Pendente / próximo passo

Escolher uma missão do registro pós-V1 e abrir worktree próprio. Não misturar
ativação de flags, banco ou deploy com outra missão em andamento.
