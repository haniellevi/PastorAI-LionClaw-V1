# Evidência read-only de DEV

Status: `COLETA_CONCLUIDA / BLOCKED_LEDGER_DIVERGENCE`.

Resumo sanitizado fornecido por Raniel para execução em `Igreja12-dev`, às
`2026-09-14T23:18:03-03:00`. A execução usou o artefato no Git SHA
`5e2082e94db2b6af6b34cfe351d81cf54b85aa76`, cujo SHA-256 foi confirmado
localmente como
`a61954c3f65ed4ca938797009c1f6f8becd80f922ab133cbcfebe89177596565`.

Uma tentativa anterior em cliente incompatível retornou erro `42601` no
meta-comando `\set`, antes do preflight. Ela não produziu evidência sobre DEV
nem alteração e foi substituída pela execução bem-sucedida via `psql`.

## Resultado recebido

| Campo | Resultado sanitizado |
| --- | --- |
| PostgreSQL | `17.6` |
| TLS | ativo |
| Transação | `REPEATABLE READ / READ ONLY` |
| Row security | `ON` |
| Ledger público | `33` migrations |
| Ledger nativo | `6` migrations |
| Relações E4b | seis ausentes |
| Escopo | `LEDGER_METADATA_AND_PGCATALOG_ONLY` |
| Rollback final | concluído |
| Alterações | nenhuma |

Nenhuma migration foi aplicada. A coleta não acessou PROD e não abre gate de
banco, deploy, runtime, envio, billing, broadcast ou `AgentConfig.ativo`.

## Forma dos ledgers

`public.schema_migrations` está presente como tabela permanente, com RLS
habilitada e não forçada, zero triggers de usuário e zero rules. Suas colunas
são `name text NOT NULL` sem default e `applied_at timestamptz NOT NULL` com
default `now()`.

`supabase_migrations.schema_migrations` está presente como tabela permanente,
sem RLS forçada ou habilitada, zero triggers de usuário e zero rules. Possui
`version text NOT NULL`, mais `statements text[]`, `name text`,
`created_by text`, `idempotency_key text` e `rollback text[]`, todas estas
cinco anuláveis e sem default.

## Ledger público capturado

```text
00 0001_extensions_and_enums.sql
01 0002_schema_tables.sql
02 0003_rls_policies.sql
03 0004_triggers.sql
04 0005_seed.sql
05 0006_harden_function_search_path.sql
06 0007_remove_demo_data.sql
07 0008_add_operador_role.sql
08 0009_unify_system_managers.sql
09 0010_platform_admins.sql
10 0011_app_users_celula_pendente.sql
11 0012_planos.sql
12 0013_platform_audit_log.sql
13 0014_platform_orchestrator.sql
14 0015_message_media.sql
15 0016_message_author.sql
16 0017_app_user_status_revogado.sql
17 20260623_103319_pessoa_sem_interesse_csim.sql
18 20260623_122044_calendar_sync_oauth_por_igreja.sql
19 20260623_154500_pessoa_tipo_add_contato.sql
20 20260623_170000_igreja_dono_assinatura.sql
21 20260624_003030_current_igreja_id_guc_worker.sql
22 20260624_090102_current_igreja_id_guard_empty_claims.sql
23 20260624_171110_agent_config_requests_fila_requisicao_admin_master.sql
24 20260629_222635_evt1_events_agenda_schema_status_tipo_origem_recorrencia_confirmacao.sql
25 20260808_011500_messages_outbound_provider_id_uidx.sql
26 20260801_031500_calendar_account_identity_binding.sql
27 20260805_105133_broadcast_delivery.sql
28 20260805_120000_calendar_fk_indexes.sql
29 20260805_153000_security_definer_execute_hardening.sql
30 20260808_135841_llm_model_selection_per_tenant.sql
31 20260810_031050_explicit_deny_policies_for_closed_tables.sql
32 20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade.sql
```

## Ledger nativo capturado

```text
00 20260804152543
01 20260808014324
02 20260808014917
03 20260808110928
04 20260823032810
05 20260828011923
```

Os seis nomes nativos não foram associados a migrations públicas. O contrato
proíbe inferir equivalência por versão, posição ou semelhança temporal.

## Relações E4b

`e4b_consent_hold_events`, `e4b_consent_holds`,
`e4b_consent_operations`, `e4b_consent_receipts`,
`e4b_consent_retentions` e `e4b_consent_streams` retornaram `ABSENT`.

## Reconciliação local

Todos os 33 nomes públicos pertencem ao catálogo de 77 e não há nome
desconhecido. As posições `0` a `24` coincidem com o prefixo canônico. As oito
posições `25` a `32` divergem: a posição `25` aplicada é
`20260808_011500_messages_outbound_provider_id_uidx.sql`, enquanto o catálogo
espera `20260701_014654_evt6_google_event_dedup_index.sql`. O ledger não é um
prefixo do catálogo e 44 arquivos do catálogo não constam nele.

O último registro pela ordem `applied_at, name` é
`20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade.sql`, o
mesmo estado documentado na captura DEV de `2026-08-28`. Isso sustenta a
conclusão limitada de que o ledger público não recebeu entrada posterior; não
prova sozinho o schema físico de migrations ausentes.

A atribuição ao ambiente `Igreja12-dev` vem da confirmação humana de Raniel.
A transcrição foi sanitizada e não contém um identificador técnico do alvo;
portanto, ela não substitui o target binding exigido para operação futura.
