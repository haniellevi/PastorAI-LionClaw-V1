# 2026-10-14 - Endurecimento das migrations pendentes e ensaio em cópia

Escopo: preparar a aplicação em PROD de `d1a` + 7 migrations do WhatsApp
(S3, V1a, V1b, V2b, V3, `20260927_120000`, `20261002_173000`). Nada foi aplicado em PROD
**no momento da preparação**; a aplicação ocorreu depois, ver "Aplicação em PROD" abaixo.
As seções anteriores a ela são o estado histórico da preparação.

## Correções (revisão independente da Sarah)

- M2: S3, V1a, V1b e V2b passam a `revoke all privileges ... from authenticated`
  antes dos grants (antes só `revoke delete`, ou nada na S3).
- M1: V3 `fn_decision_opens_consolidation` com `set search_path = public, pg_temp`
  (o `create or replace` descartava o ajuste da 0006).
- B5: rollback em SQL comentado em V3, V2b e d1a.
- Teste `test_s3_migration_exact_pg.py`: hash da S3 atualizado.

Na época da edição, as migrations ainda não estavam aplicadas em PROD, então a edição
não violava a regra de não alterar migration aplicada. **Agora estão aplicadas: não
editar mais esses arquivos; qualquer ajuste vira migration nova.**

## Evidências (executadas)

- 80 testes `*_pg` (S3, V1a, V1b, V2b, V3) passaram em Postgres 17 descartável.
- Ensaio em cópia do backup de PROD de 14/10 (schema `public`, sem ACL real), banco
  temporário na VPS: d1a + 7 aplicadas uma a uma, ledger 70 -> 78. Na cópia,
  `authenticated` ficou só com SELECT/INSERT/UPDATE nas 8 tabelas conferidas e a
  função do V3 com `search_path` fixo.
- d1a levou 1,165 s (cópia: `messages` 208 linhas, `conversations` 9, `pessoas` 28).
- Cópia, dump e túnel removidos ao final.

## Achado

- A S3 depende da d1a (`conversations_igreja_id_id_key`). O release de PROD
  precisa incluir a d1a (migration de segurança/RLS).
- Pendentes que ficam de fora de propósito: `20260711_023515`, `20260711_152127`
  (só dados), `20260925_183811`, `20260926_120446` (gates próprios).

## Não provado

ACLs reais de PROD, tempo sob tráfego e no hardware do Supabase, comportamento do
app sobre o schema novo, `test_d1a_tenant_runtime_integrity_migration.py` (não rodado).

## Próximo gate (histórico; cumprido em "Aplicação em PROD")

Aplicação em PROD: backup novo, plano de volta e autorização nominal.

## Aplicação em PROD (14/10/2026, autorização nominal do usuário)

- Backup antes: `pastorai-backup-20261014T201932Z.tar.gz` (sha256 conferido). Ponto de retorno.
- `migrate.py apply` uma a uma, na ordem: `20260927_120000`, d1a, `_170000`, `_190000`,
  `_210000`, `_220000`, `20260928_080000`, `20261002_173000`. Todas `aplicada`, sem falha.
- Ledger 70 -> 78 (82 arquivos, 4 pendentes de propósito: `20260711_023515`,
  `20260711_152127`, `20260925_183811`, `20260926_120446`).
- Conferência pós (só leitura): `/ready` 200 (database, redis, evolution, billing_operations,
  queue/cron/broadcast workers ok). `authenticated` sem DELETE/TRUNCATE/REFERENCES/TRIGGER nas
  4 tabelas do agente e na `notification_outbox`; `fn_decision_opens_consolidation` com
  `search_path=public, pg_temp`.
- Não provado: tempo sob tráfego; comportamento do app sobre o schema novo além do `/ready`;
  ACLs das demais tabelas e do schema `auth`.
- **Cutover V2b (`_220000`) sem registro de pré-condições.** Este documento não registra o
  resultado das verificações obrigatórias de `docs/ops/v2b-agenda-20260927/README.md`
  (sequência da release, passos 0–2): contagem de `app_users.status` com visibilidade
  integral (`current_user = 'postgres'`, `sem_status = 0`), parada de produtores/consumidores
  antigos incluindo EVT-7 em andamento, identificação de claims em voo e espera do lease
  efetivo. Sem esse registro, a virada **não está comprovada como conforme**. A `_220000`
  termina lembretes pendentes e isola escritas EVT-7 legadas; se houve worker ou HTTP de
  envio ativo, pode existir entrega ambígua não contabilizada. Pendente: o responsável pela
  aplicação registrar aqui o que foi feito e observado, ou reconciliar como não conforme.
