# PROD: ledger `public.schema_migrations` e deploy do backend — 2026-09-26

**Branch:** `docs/prod-sessao-a-b-20260926`  ·  **Base:** `main` `e6aafc2`  ·  **Deploy:** banco de PROD (ledger + migration S2) e backend (ver seção própria)

Sessão operacional em PROD conduzida pelo Claude Code com "ok" do Raniel antes de
cada passo que grava no PROD ou mexe na VPS. Segue o veredito da Sarah de 26/09
(NO-GO ao plano inicial → duas sessões: A = acesso, backup e ledger; B = deploy,
só com GO dela). Nenhum `.env`, URL de banco ou senha foi impresso.

## Estado de partida (diagnóstico de 26/09 + inspeção desta sessão)

- Release ativo: `/opt/pastorai-releases/c525d6a3897a12c6c287f9fc79a88b32b34cd452`
  (26/08); `pastorai-backend:latest` = `sha256:833d51b5ff40…` nos 4 processos
  (`backend`, `queue-worker`, `cron-worker`, `broadcast-worker`).
- `ALLOW_REAL_SENDS=true` nos 4 processos; `ASAAS_BILLING_ENABLED=false`,
  `BREVO_SEND_MODE=off`, `BROADCAST_ASYNC_ENABLED=false`;
  `WHATSAPP_PILOTO_IGREJA_IDS` ausente do `.env`.
- Banco: PostgreSQL 17.6, conexão `postgres` (BYPASSRLS, não superuser).
  `public.schema_migrations` **ausente**; ledger nativo do Supabase
  (`supabase_migrations.schema_migrations`) com 32 registros (0001–0014, o bloco
  de 05/08 a 10/08, recibos M06/M01 da V1 e as 4 de 22/08–26/08). Sem registro
  nativo: `0015`–`0017` e todo o bloco de 23/06 a 20/07.
- 56 tabelas em `public`, todas com RLS, nenhuma com `FORCE`, todas do `postgres`.
- Event trigger `ensure_rls` (`ddl_command_end`, ativo) chama
  `public.rls_auto_enable()` (md5 da definição `6998ea6b…`): só faz
  `ENABLE ROW LEVEL SECURITY` em tabela nova de `public`, sem `FORCE`.
- Default privileges de `postgres` e `supabase_admin` em `public` concedem
  `arwdDxtm` a `anon`, `authenticated` e `service_role` em toda tabela nova.

## Sessão A — o que foi feito

1. **Acesso.** Chave SSH temporária ed25519 `pastorai-tmp-2026-09-26`, gerada no
   scratchpad da sessão (fora de `~/.ssh`) e colada pelo Raniel no console da
   Hostinger com `expiry-time="202609280000"`. Host key conferida no console
   (`SHA256:Tpdy9QSGiJ9d71yqzCrt9mvU0kxPDOXHLIZFBCcRgeU`) antes da primeira
   conexão.
2. **Backup** com `/usr/local/sbin/pastorai-backup.sh` (SHA-256 igual ao
   `deploy/backup-production.sh` do repo; helper `prepare-database-service.py`
   com sidecar conferido). Disco antes: 24 GB livres.
   - Pacote `pastorai-backup-20260926T200839Z.tar.gz`, 28.187.244 bytes, 58 s.
   - SHA-256 `53ca04b6766e7fca5064347979f7e3bd6a43423cf7f84dfb6a7aebaf85a74488`:
     `sha256sum -c` OK e igual ao manifesto `backup-status.json` (`verified`).
   - Conteúdo: dump `public` do Supabase, 32 arquivos do Storage, dump e volumes
     da Evolution, volume do Redis, cópia restrita do `.env` e do Compose.
3. **Inspeção só leitura do banco.** SQL de prova com 243 checagens de catálogo
   para as 79 migrations do `main` (tabelas, colunas, índices, constraints,
   funções por trecho distintivo, policies, grants). Nenhuma leitura de linha de
   tabela da aplicação. O SQL foi validado antes em réplica PostgreSQL 17
   (PGlite, WASM, sem rede): tudo verdadeiro com as 77 migrations ativas,
   nenhuma checagem de migration datada verdadeira com só `0001`–`0017`, nada de
   22/08 em diante verdadeiro no corte da V1, e teste "deixa uma de fora" para
   achar checagens fracas.
   - Resultado em PROD: **todas as 71 migrations até `20260826_094317` sem
     nenhuma checagem falsa**; as 6 não aplicadas do diagnóstico e as 2 pausadas
     com **todas** as checagens falsas.
   - Compatibilidade do `main`: `celula_membro_evento`, `asaas_webhook_receipts`,
     `billing_*_operations`, `messages.agent_reply_state` (+ CHECK validado),
     `subscriptions.asaas_*_external_reference`, trigger append-only e
     `current_igreja_id()` com GUC presentes; `platform_jev_settings`,
     tabelas D2B2/D2B2b3/E4B, schema `agent_private` e role `agent_runtime`
     ausentes; `app_users.igreja_id` ainda NOT NULL; 0 instâncias WhatsApp
     duplicadas.
4. **Ledger** criado numa única transação (SQL ensaiado na réplica antes,
   SHA-256 `a30a48aa587baa5406cb0c47761f78e5b39af4242e694efeaf5c6eeaad5e8ad4`),
   às 2026-09-26 20:11:54 UTC:
   - guardas: ledger inexistente, conexão `postgres`, `rls_auto_enable()` igual
     à inspecionada;
   - `name text PRIMARY KEY`, `applied_at timestamptz NOT NULL DEFAULT now()`,
     `origem text NOT NULL DEFAULT 'MIGRATE_PY'` com CHECK em `PROVA_OBJETO`,
     `BASELINE_V1_HISTORICO` e `MIGRATE_PY`;
   - `ENABLE ROW LEVEL SECURITY`, **sem FORCE**; `REVOKE ALL` de `PUBLIC`,
     `anon` e `authenticated` **na mesma transação**;
   - 69 linhas; pós-condições antes do COMMIT (RLS sim, FORCE não, zero
     privilégio de `anon`/`authenticated`, zero policy, contagens 69/63/6 e md5
     do conteúdo `1a5c405f1a7efd47945ffab969fba706`).
   - Estado final lido depois: dono `postgres`; ACL
     `{postgres=arwdDxtm/postgres,service_role=arwdDxtm/postgres}`; default
     privileges e `ensure_rls` iguais a antes; 57 tabelas em `public`, todas
     com RLS e nenhuma com FORCE.

### Critério da lista nominal

- **PROVA_OBJETO** — todas as checagens de objeto da migration presentes hoje
  no catálogo de PROD (migrations mistas: parte de dados na mesma transação,
  não verificável).
- **BASELINE_V1_HISTORICO** — migration só de dados, presente na tag `v1.0.0`
  (`281e69c2`) **e** com registro histórico de aplicação em PROD: linha no
  ledger nativo do Supabase (`0005`, `0007`, `0009`, `20260808_014425`,
  `20260808_023500`) ou conferência PROD documentada
  (`20260708_164756`: `docs/sprints/DEPLOY-HANDOFF-2026-07-09.md:145`).
- Qualquer outra fica **fora**.

### Registradas em `public.schema_migrations` (69)

```text
0001_extensions_and_enums.sql                                                                PROVA_OBJETO
0002_schema_tables.sql                                                                       PROVA_OBJETO
0003_rls_policies.sql                                                                        PROVA_OBJETO
0004_triggers.sql                                                                            PROVA_OBJETO
0005_seed.sql                                                                                BASELINE_V1_HISTORICO
0006_harden_function_search_path.sql                                                         PROVA_OBJETO
0007_remove_demo_data.sql                                                                    BASELINE_V1_HISTORICO
0008_add_operador_role.sql                                                                   PROVA_OBJETO
0009_unify_system_managers.sql                                                               BASELINE_V1_HISTORICO
0010_platform_admins.sql                                                                     PROVA_OBJETO
0011_app_users_celula_pendente.sql                                                           PROVA_OBJETO
0012_planos.sql                                                                              PROVA_OBJETO
0013_platform_audit_log.sql                                                                  PROVA_OBJETO
0014_platform_orchestrator.sql                                                               PROVA_OBJETO
0015_message_media.sql                                                                       PROVA_OBJETO
0016_message_author.sql                                                                      PROVA_OBJETO
0017_app_user_status_revogado.sql                                                            PROVA_OBJETO
20260623_103319_pessoa_sem_interesse_csim.sql                                                PROVA_OBJETO
20260623_122044_calendar_sync_oauth_por_igreja.sql                                           PROVA_OBJETO
20260623_154500_pessoa_tipo_add_contato.sql                                                  PROVA_OBJETO
20260623_170000_igreja_dono_assinatura.sql                                                   PROVA_OBJETO
20260624_003030_current_igreja_id_guc_worker.sql                                             PROVA_OBJETO
20260624_090102_current_igreja_id_guard_empty_claims.sql                                     PROVA_OBJETO
20260624_171110_agent_config_requests_fila_requisicao_admin_master.sql                       PROVA_OBJETO
20260629_222635_evt1_events_agenda_schema_status_tipo_origem_recorrencia_confirmacao.sql     PROVA_OBJETO
20260701_014654_evt6_google_event_dedup_index.sql                                            PROVA_OBJETO
20260701_164352_evt7_events_notificado_em_aviso_confirmacao.sql                              PROVA_OBJETO
20260701_193000_evt7_pr2_agenda_alert_recipients.sql                                         PROVA_OBJETO
20260703_123803_celula_schema_base_pr1.sql                                                   PROVA_OBJETO
20260704_100000_celula_pr2_reuniao_presenca_expectativa.sql                                  PROVA_OBJETO
20260705_120000_celula_pr3_reuniao_relatorio_campos.sql                                      PROVA_OBJETO
20260705_120100_celula_pr3_reuniao_registro.sql                                              PROVA_OBJETO
20260705_120200_celula_pr3_visitante.sql                                                     PROVA_OBJETO
20260705_120300_celula_pr3_solicitacao_evento.sql                                            PROVA_OBJETO
20260705_120400_celula_pr3_aviso.sql                                                         PROVA_OBJETO
20260705_120500_celula_pr3_material.sql                                                      PROVA_OBJETO
20260705_120600_celula_pr3_multiplicacoes_evolucao.sql                                       PROVA_OBJETO
20260706_221311_pessoas_apto_lider_e_converte_legado_tipo_lider.sql                          PROVA_OBJETO
20260706_230000_evt8_pr1_notify_config.sql                                                   PROVA_OBJETO
20260707_011455_igreja_logo_branding.sql                                                     PROVA_OBJETO
20260708_160128_sec3a_app_users_password_changed_at.sql                                      PROVA_OBJETO
20260708_164756_backfill_celula_membro_canonico.sql                                          BASELINE_V1_HISTORICO
20260708_172106_sec3b_password_reset_tokens_single_use.sql                                   PROVA_OBJETO
20260708_221808_igreja_dono_id_grant_update.sql                                              PROVA_OBJETO
20260709_204500_sec4_agent_event_idempotency_marker_uidx.sql                                 PROVA_OBJETO
20260711_224403_celula_solicitacao_e13_open_unique.sql                                       PROVA_OBJETO
20260713_013054_pessoa_arquivamento_schema.sql                                               PROVA_OBJETO
20260713_032015_pessoa_offboarding_preflight_arquivamento_evento.sql                         PROVA_OBJETO
20260715_204540_msg_idemp1_messages_inbound_provider_id_uidx.sql                             PROVA_OBJETO
20260715_204541_consolidacao_aberta_unica_por_pessoa.sql                                     PROVA_OBJETO
20260720_014832_pessoa_telefone_unico_por_tenant_ativa.sql                                   PROVA_OBJETO
20260720_191143_consent_records_ator_id_reoptin.sql                                          PROVA_OBJETO
20260730_205332_billing_setup_configuration.sql                                              PROVA_OBJETO
20260731_120000_calendar_oauth_flows_pkce.sql                                                PROVA_OBJETO
20260801_031500_calendar_account_identity_binding.sql                                        PROVA_OBJETO
20260805_105133_broadcast_delivery.sql                                                       PROVA_OBJETO
20260805_120000_calendar_fk_indexes.sql                                                      PROVA_OBJETO
20260805_153000_security_definer_execute_hardening.sql                                       PROVA_OBJETO
20260808_001059_billing_count_active_members.sql                                             PROVA_OBJETO
20260808_011500_messages_outbound_provider_id_uidx.sql                                       PROVA_OBJETO
20260808_014425_billing_member_plan_label_variants.sql                                       BASELINE_V1_HISTORICO
20260808_023500_billing_reconcile_prepared_member_upgrades.sql                               BASELINE_V1_HISTORICO
20260808_135841_llm_model_selection_per_tenant.sql                                           PROVA_OBJETO
20260810_031050_explicit_deny_policies_for_closed_tables.sql                                 PROVA_OBJETO
20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade.sql                     PROVA_OBJETO
20260822_225752_celula_membro_evento_audit_table.sql                                         PROVA_OBJETO
20260824_180000_asaas_formal_isolation.sql                                                   PROVA_OBJETO
20260826_030508_separar_estado_resposta_agente_de_autor_mensagem.sql                         PROVA_OBJETO
20260826_094317_harden_recovery_artifacts_retention.sql                                      PROVA_OBJETO
```

`applied_at` dessas 69 linhas é a data do registro (26/09), não a da aplicação
original (anotado no COMMENT da coluna).

### Fora do ledger (10) — pendente por falta de prova, NÃO aplicar em lote

| migration | motivo |
|---|---|
| `20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql` | PENDENTE POR FALTA DE PROVA: só dados, na tag v1.0.0, sem registro no ledger nativo nem registro de aplicação em PROD |
| `20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql` | PENDENTE POR FALTA DE PROVA: só dados, na tag v1.0.0, sem registro no ledger nativo nem registro de aplicação em PROD |
| `20260827_175634_d1a_tenant_runtime_integrity.sql` | NÃO APLICADA: 5 checagem(ns) de objeto ausente(s), 0 presente(s) |
| `20260827_230003_d2a_agent_runtime_private_context.sql` | NÃO APLICADA: 3 checagem(ns) de objeto ausente(s), 0 presente(s) |
| `20260828_045213_d2b2_consentimento_finalidade_evento.sql` | NÃO APLICADA: 6 checagem(ns) de objeto ausente(s), 0 presente(s) |
| `20260828_094914_d2b2b3_purpose_consent_governance_drafts.sql` | NÃO APLICADA: 4 checagem(ns) de objeto ausente(s), 0 presente(s) |
| `20260909_004005_consent_evidence_store_lab.sql` | PAUSADA (OPERATIONAL_AUTHORIZATION=BLOCKED; fora do migrate.py) |
| `20260910_142830_add_e4b_consent_persistence.sql` | PAUSADA (OPERATIONAL_AUTHORIZATION=BLOCKED; fora do migrate.py) |
| `20260925_183811_preserve_platform_admins_on_tenant_deletion.sql` | NÃO APLICADA: 4 checagem(ns) de objeto ausente(s), 0 presente(s) |
| `20260926_120446_platform_jev_settings.sql` | NÃO APLICADA: 3 checagem(ns) de objeto ausente(s), 0 presente(s) |

Com o ledger, `python scripts/migrate.py status` do `main` lista exatamente 8
pendentes (as 10 acima menos as 2 pausadas). **Nenhuma delas deve ser aplicada
em lote.** Cada uma tem gate próprio:

- `20260711_023515` e `20260711_152127`: só dados, idempotentes pelo cabeçalho,
  mas reexecutar hoje mudaria o `tipo` de pessoas com o estado atual. Antes de
  qualquer decisão, rodar só leitura a verificação de pós-condição do próprio
  arquivo (contagem esperada 0) e decidir registrar ou aplicar com revisão.
- `20260925_183811`, `20260926_120446`, d1a, d2a, d2b2, d2b2b3: gates próprios
  (Sessão B não aplica nenhuma).

## Decisões

- `origem` tem padrão `MIGRATE_PY` porque o `migrate.py` grava só `name`; o
  CHECK evita valor digitado errado.
- RLS explícito (o `ensure_rls` já faria) e sem FORCE; `service_role` mantém
  acesso, como nas demais tabelas fechadas.
- Critério rigoroso de baseline: os dois backfills de 11/07 ficaram fora por não
  haver prova (nem ledger nativo, nem conferência PROD; o registro de
  `2026-07-11-deploy-m7b-sec-prod.md` só mostra o arquivo no tarball).
- `20260624_003030` está registrada como PROVA_OBJETO, mas é **prova de efeito,
  não de execução**: a `20260624_090102` reemite o mesmo efeito (superset
  estrito, conferido pela Sarah). Registrar é o lado seguro, pois reaplicar a
  003030 regrediria `current_igreja_id()` e derrubaria a RLS de `pessoas`.
- O executor antigo `backend/scripts/apply_migrations.py` (pausado) exige
  exatamente `(name, applied_at)` e recusaria este ledger por causa de `origem`.
  O processo do MVP usa só o `migrate.py`.

## Observações

- A pausa do Redis no backup derruba o `queue-worker` (`TimeoutError`, exit 1);
  o Docker o reinicia em ~4 s. Acontece também no backup diário das 06:15 UTC
  (`RestartCount=4` no container). Candidato à causa de parte dos incidentes do
  monitor (Fase 4, B8).
- O log `/var/log/pastorai-backup.log` guarda erros antigos (antes de 23/09) de
  senha recusada pelo pooler; os backups de 23 a 26/09 estão OK.
- A nota do Maestri "PASSO A PASSO RANIEL" (roteiro com `reset_tudo` e
  reaplicação da `20260826_030508`) foi marcada como suspensa pelo Conselheiro;
  a `20260826_030508` já está aplicada em PROD.

## Revisões da Sarah e decisões do proprietário

- **Sessão A:** evidência aprovada (backup antes da escrita, ledger numa
  transação, 243 checagens com quatro controles de discriminação e
  leave-one-out, nenhuma migration meio aplicada em PROD). P1-A: o critério
  BASELINE contrariava o §4 do runbook → decisão (a) abaixo e §4 corrigido.
- **Estrutura do plano de deploy:** aprovada, com P1-B (`unset
  PASTORAI_ENV_FILE`) e P2-B…G aplicados.
- **Método da migration S2:** NO-GO na v1 (P0: `SET` de sessão podia se perder
  nos commits do `cmd_apply` através do pooler; P1: faltava pré-imagem de
  ACL/policy e o container recebia o `.env` inteiro) → GO na v2 (P0=0, P1=0),
  condicionado a backup novo e "ok" do proprietário.
- Mudança de plano do proprietário: a S2 (PR #423) foi autorizada e o deploy
  virou **um só**, do `main` pós-#423 (`e6aafc2`), em vez de `a5244ca`.

Decisões do Raniel, coladas por ele no chat (texto redigido a pedido dele,
depois de explicação em linguagem simples):

> Decisões do Raniel (26/09/2026):
> (a) Aceito a exceção BASELINE_V1_HISTORICO para as 6 migrations só de dados
> (0005_seed, 0007_remove_demo_data, 0009_unify_system_managers,
> 20260708_164756, 20260808_014425 e 20260808_023500). Elas ficam registradas
> como aplicadas e o migrate.py nunca vai reaplicá-las. Daqui em diante, o
> public.schema_migrations é o único registro oficial de migrations; pode
> corrigir o §4 do runbook.
> (b) Dispenso o "DEV primeiro" somente para a migration S2 (20260926_191500),
> como exceção única, pelos controles compensatórios já aplicados. A próxima
> migration só vai para produção depois de o DEV ser reconciliado.
> (c) Estou ciente de que, depois do deploy, o robô do WhatsApp para de
> responder e os envios pelo painel ficam bloqueados até eu autorizar a
> reabertura em uma etapa própria.

## Migration S2 — `20260926_191500_agent_public_profile.sql`

- Antes (só leitura): `agent_configs` com RLS e sem FORCE, coluna e CHECK
  ausentes, policy `tenant_isolation` presente, 1 linha, **0 linhas com o bloco
  legado `[informacoes_publicas]`** (nenhum dado a redigitar). O pooler ignora
  `PGOPTIONS` (`SHOW lock_timeout` = 0), então o limite de 2 s foi posto por
  SQL. Fingerprint de referência de `agent_configs` (dono, RLS/FORCE, ACL da
  tabela e colunas, policies com expressões, constraints, triggers):
  `702ca5fe4df1772d21c6755d47c55915`, idêntico ao da réplica.
- Backup imediatamente antes: `pastorai-backup-20260926T210416Z.tar.gz`,
  SHA-256 `fef2c10d2025ff760ad7996f658eee9b5da1d9ba04c2a12ca7f16065c3a35bb4`
  (`sha256sum -c` OK, manifesto `verified`).
- Aplicação às 21:06:11 UTC, a partir do head `d7d02dbc0` da PR #423 (arquivo
  SHA-256 `3d891a54…5a4`, blob idêntico no merge `e6aafc2`), por
  `apply_s2_v2.py` (SHA-256 `d502b79d…38ce`, uso único, não versionado): importa
  as funções do `migrate.py` e reproduz o `cmd_apply` numa transação única com
  `SET LOCAL lock_timeout = '2s'` conferido antes e depois do DDL, fingerprint
  antes = referência e depois = antes, e ledger na mesma transação. Conexão
  pelo `pg_service.conf` efêmero do helper do backup (sem `.env` no container).
  Resultado: `COMMIT`; coluna `jsonb NOT NULL DEFAULT '{}'`, CHECK validado,
  ledger 69 → 70 (`origem = MIGRATE_PY`); fingerprint pós-commit `702ca5fe…`;
  backend `c525d6a` seguiu `ready`.
- Ensaio antes, na réplica: caminho feliz, referência divergente (rollback antes
  do DDL), arquivo adulterado com `REVOKE` e primeira guarda subvertida
  (rollback pela segunda guarda) e repetição recusada.
- Pendências da revisão (P2, não bloqueantes): `--lock-timeout` no `migrate.py`
  (PR de follow-up, para a próxima migration usar o CLI); conferir o hash do
  `migrate.py` e o digest da imagem dentro do wrapper; ampliar o fingerprint
  (tipos, nulidade e índices); paridade da redação de erros.

## Deploy do backend — `e6aafc2` (main pós-#423)

- GO da Sarah sobre o delta `a5244ca..e6aafc2` (P0=0, P1=0, P2=6) com três
  condições: CI reconferido verde no `e6aafc2` (`backend-tests`, `e2e-critical`,
  `frontend-ci`, `rls-integration` = success); B1 e B2 na mesma janela com o
  proprietário presente; confirmação dele, com as próprias palavras, de que o
  robô para. Resposta dele: "ok, entendi, pode fazer b2, corrija logo e quando
  terminar liga o robo, nao precisa avisar filadelfia".
- Artefato: `git archive` do `e6aafc2` (`backend` + `deploy`, sem testes e sem
  `.env*`), SHA-256 `df0dd470051253c37edf4639516fb75e939dad63eec13a843942bdce5d2a7632`,
  306 arquivos (os 305 do `a5244ca` + a migration S2), reproduzível. A mesma
  receita aplicada ao `c525d6a` reproduz byte a byte os 211 arquivos do release
  que estava ativo.
- B1 (22:05 UTC): release em `/opt/pastorai-releases/e6aafc2…`; `.env` copiado sem
  imprimir, única chave alterada `ALLOW_REAL_SENDS=false`; imagem anterior
  etiquetada `pastorai-backend:c525d6a` (`833d51b5ff40`, rollback) e nova
  `pastorai-backend:e6aafc2` (`439b42dff0e0`); prévia: só os 4 processos do app.
- B2 (22:07 UTC): os 4 processos recriados, travas fechadas nos 4. A checagem de
  `/health` rodou no mesmo instante do start e deu falso negativo (connection
  reset): symlink não trocado e nada revertido. Diagnóstico só leitura: 4 processos
  `healthy` sem reinício, `/ready` verde, Evolution/Redis intocados, nenhum erro nos
  logs. Com "ok" do proprietário, o fechamento (01:06 UTC de 27/09) repetiu todas
  as provas com espera e trocou o symlink. Correção para o roteiro: esperar o
  `/health` como já se esperava o `/ready`.
- B3 (só leitura): symlink → `e6aafc2`; portas 8000/8080 só em `127.0.0.1` e
  recusadas de fora; `/health` 200 e `/ready` ready (local e público);
  `/admin/jev` e `/agent/public-profile` sem login = **401**; CORS do painel ok;
  `app.`, `admin.` e `painel.` = 200; `migrate.py status` = `aplicadas: 70
  arquivos: 78  pendentes: 8`, igual ao declarado antes; cron do backup e último
  pacote `verified`; timer do monitor ativo.
- Frontend: publicado pela Vercel no merge da #423; a seção de perfil público
  mostrou erro entre o merge e o B2 (janela aceita pelo proprietário).

## Reabertura do robô — Filadélfia (27/09, 01:18 UTC)

- Pedido do proprietário ("quando terminar liga o robô"). Consequências
  apresentadas antes; resposta: "sim, pode ligar", aceitando o risco de a
  detecção de crise ser fraca (o robô responde qualquer pessoa que escrever para o
  número da igreja).
- Pré-checagem só leitura: Filadélfia `228ebda0-92c1-422c-8ab4-78fdc06c1b8e`,
  agente ativo, 1 credencial OpenAI ativa e validada, WhatsApp `online` no banco
  (última sincronização registrada em 07/08; conferir no painel), informações
  públicas vazias, 0 avisos de upgrade pendentes. Mensagens recebidas com o robô
  desligado ficam só ingeridas e não são respondidas depois.
- `.env` do release: `WHATSAPP_PILOTO_IGREJA_IDS=` Filadélfia,
  `ALLOW_REAL_SENDS=true`, `WHATSAPP_SLA_ENABLED=false`; Asaas, Brevo, broadcast,
  agenda e Jev seguem desligados. Cópia anterior em
  `/root/pastorai-env-bak/e6aafc2.env.pre-reabertura-20260927T011755Z`. 4 processos
  recriados e conferidos, Evolution/Redis intocados, `/ready` verde.
- O roteiro "LIGAR O PILOTO" do Maestri (passo 2) foi coberto por esta sessão; o
  Conselheiro foi avisado para não repetir. Pendente: teste com celular da equipe
  interna (passo 3 do roteiro). O piloto continua só interno, sem divulgar o
  número. Desligar rápido: agente inativo no painel, ou `ALLOW_REAL_SENDS=false`
  e recriar os 4 processos.
- Evidência de apoio: `docs/ops/prod-ledger-20260926/` (kit de conferência).

## 27/09 — WhatsApp "Online" sem receber: diagnóstico, reconexão e teste

Sintoma relatado pelo proprietário (07:13 BRT): o painel mostrava o número
"Online", mas nada chegava, o "Desconectar" falhava e o sistema estava lento.

Diagnóstico (só leitura):

- A conexão da Evolution com o WhatsApp morreu em **03/09, às 21:05 BRT**
  (`error in sending keep alive` seguido de erro do Prisma no
  `ChannelStartupService`), mas ficou marcada `open` em memória e no banco da
  Evolution. Foi uma conexão "zumbi": a Evolution não gravou nenhum log de 04/09
  até 27/09.
  - Última mensagem guardada na Evolution: 03/09 20:24. No banco do app, a última
    é de 01/09 00:42: as recebidas entre 01 e 03/09 não chegaram ao app, porque os
    webhooks falharam na época.
- O "Desconectar" chama `DELETE /instance/logout`, que falha com a conexão morta.
  O painel recebeu 502 (`Evolution logout failed: HTTPStatusError`) duas vezes, às
  10:13 UTC.
- O caminho Evolution → backend estava íntegro:
  - token do webhook igual ao segredo do backend, tanto na instância quanto no
    global;
  - mesma rede Docker;
  - `GET http://backend:8000/health` = 200 a partir da Evolution.
- Lentidão: o servidor estava ocioso (load 0,3 em 1 vCPU, 2,6 GB livres). A causa
  é a distância: o Supabase está em **us-west-2** e a VPS no Brasil, com 185–190 ms
  por ida e volta.
  - O custo mínimo de uma requisição do backend é ≈1,3 s: pre-ping, três comandos
    de contexto de tenant, a consulta e o fim da transação.
  - `/ready` leva ≈1,7 s.
  - Tarefa própria aberta: "Reduzir a lentidão: banco longe do servidor".
- O `queue-worker` caiu às 06:15:57 UTC com `redis.exceptions.TimeoutError` e o
  Docker o religou em 8 s. Tarefa própria aberta.
- Salvar a configuração do Jev no Console responde 409, porque a
  `20260926_120446_platform_jev_settings` não está aplicada. É o esperado; a chave
  da TypeSafe digitada não foi salva.

Correção, com "ok" do proprietário:

1. Resposta automática do robô desligada (`WHATSAPP_PILOTO_IGREJA_IDS=` vazio) e
   reinício **só** do container da Evolution.
   - `ALLOW_REAL_SENDS=true` ficou ligado, porque o painel precisa dele para
     gerir a conexão.
   - Motivo: não responder, semanas depois, o que o WhatsApp entregasse acumulado.
   - O classificador automático do Claude Code bloqueou a execução mesmo com o
     "ok". O proprietário rodou a linha equivalente no console da Hostinger às
     10:53 UTC.
   - Cópia do `.env`:
     `/root/pastorai-env-bak/e6aafc2.env.pre-reconexao-20260927T105319Z`.
2. A Evolution reconectou com a sessão existente (`connecting` → `open`,
   statusReason 200), sem QR. O WhatsApp entregou o acumulado:
   - mensagens de grupo, ignoradas pelo parser;
   - 3 mensagens diretas de 04–08/09, ingeridas sem resposta;
   - uma sincronização de ~3.100 eventos de contato em 2 minutos, ignorados; a
     fila acompanhou.
3. Robô religado só para a Filadélfia às 11:10 UTC (`REABERTURA_OK`).
   - Cópia do `.env`: `…pre-reabertura-20260927T111031Z`.
   - SLA, Asaas, Brevo, broadcast, agenda e Jev seguem desligados.

Teste com celular da equipe interna:

- **1ª tentativa:** a resposta foi gerada em 3 s, mas alguém clicou em
  "Assumir (pausar IA)" no painel antes do envio. A cerca de handoff suprimiu a
  resposta (`ia_suprimida`), comportamento esperado. Para testar de novo, é
  preciso "Devolver para a IA".
- **Entregas atrasadas:** mensagens antigas seguiram chegando com atraso de
  dezenas de minutos, com avisos `No session found to decrypt message` e
  `Decrypted message with closed session` (sessões de criptografia velhas se
  refazendo).
  - Uma mensagem de 26/09 22:26 chegou às 08:21 de 27/09 e foi respondida pelo
    robô.
  - Uma de 08:12 chegou às 08:22.
- **2ª tentativa (08:30 BRT):** as mensagens chegaram na hora.
  - Resposta enviada em 27–28 s: ≈15 s até o LLM responder, mais ≈13 s de
    trabalho de banco até o `sendText` (201).
  - O WhatsApp confirmou a entrega (`DELIVERY_ACK`) e o proprietário confirmou o
    recebimento no celular.
  - O critério do plano, resposta em menos de 10 s, **não foi atingido**.

Estado final (11:40 UTC):

- release `e6aafc2`;
- robô ligado só para a Filadélfia; SLA, Asaas, Brevo, broadcast, agenda e Jev
  desligados;
- os 4 processos `healthy` e `/ready` verde;
- filas zeradas e Evolution `open`.

Achados para depois:

- Não há limite de idade para responder: mensagem entregue atrasada é tratada como
  nova. Avaliar um limite pelo `messageTimestamp` antes do turno do agente.
- `parse_message_event` não extrai texto de `templateMessage`: a mensagem chega com
  texto vazio e o agente responde assim mesmo.
- Cada evento chega duas vezes, pelo webhook da instância e pelo global, e a
  Evolution processa grupos (`groupsIgnore=false`). O dedupe segura, mas a carga
  dobra. Considerar desligar o webhook global ou filtrar eventos, e usar
  `groupsIgnore=true`.
- Remetentes chegam como `@lid`, com `remoteJidAlt` de telefone. O payload do
  webhook trouxe o telefone e casou com contatos existentes, mas o código não trata
  `@lid` explicitamente. Há 5 pessoas com 14–15 dígitos, prováveis LIDs, criadas em
  jun–jul.
- Segredos em logs da VPS (só root, mas convém filtrar):
  - o access log do uvicorn grava a query string do webhook (`?token=`);
  - os dumps de erro da Evolution incluem a `apikey`.
- A Evolution não percebe conexão morta. Criar alerta, por exemplo: nenhuma
  mensagem recebida há N horas em horário comercial.
- A VPS pede reinício (kernel e libc atualizados); agendar em horário calmo.
- Scripts da sessão: `! grep` não abortava sob `set -e` no script da reabertura.
  As checagens seguintes, dentro dos containers, cobriram; o script foi corrigido
  para `if grep …; then exit 1; fi`.

## Pendente / próximo passo

- Preencher as informações públicas no painel.
- Tempo de resposta do robô (~28 s, meta < 10 s): tarefa "Reduzir a lentidão"
  (banco em us-west-2), além dos achados acima (limite de idade, `templateMessage`,
  webhook duplicado, grupos).
- `queue-worker` tolerar timeout do Redis (tarefa própria).
- Cópias do `.env` em `/root/pastorai-env-bak/` (3 arquivos, modo 600, contêm
  segredos): apagar após uma semana estável.
- Correções do roteiro de deploy: esperar o `/health` no B2; P2 da Sarah no wrapper
  de migration (hash do `migrate.py`, digest da imagem, fingerprint mais amplo).
- **DEV confiável** antes da próxima migration em PROD: recriar o DEV a partir
  do schema de PROD (sem dados reais), com o mesmo ledger, e conferir com as
  mesmas 243 checagens; depois `--lock-timeout` no `migrate.py`.
- Gates próprios: `20260925_183811`; `20260926_120446`; d1a/d2a/d2b2/d2b2b3;
  os dois backfills de 11/07; reabrir envios (`ALLOW_REAL_SENDS=true` e
  `WHATSAPP_PILOTO_IGREJA_IDS`, piloto interno); exclusão de igreja só depois
  do gate da `20260925_183811`.
- Pré-existente, fora deste escopo: `anon` tem SELECT/UPDATE em
  `public.app_users` (default privileges); a RLS é a única barreira; a
  `20260925_183811` corrige no gate dela.
- Encerramento (27/09, ~11:50 UTC): o proprietário removeu a chave temporária da VPS
  e o pacote `pastorai-e6aafc2….tar` pelo console da Hostinger (`ACESSO_REMOVIDO`).
  A conexão com a chave passou a ser recusada (`Permission denied`) e a cópia local
  da chave foi apagada. Uma primeira colagem levou junto texto antigo da tela; cada
  linha falhou como "command not found" e nada foi executado (conferido: `.env`,
  horários de início dos containers e cópias do `.env` inalterados).

## Verificação

- Backup: `sha256sum -c` OK e igual ao manifesto (acima).
- Ledger: saída das pós-condições e da leitura final (acima); md5 do conteúdo
  igual ao da lista aprovada.
- `migrate.py status` simulado com o código do `main`: `aplicadas: 69
  arquivos: 77 pendentes: 8`.
