\set ON_ERROR_STOP on
-- Sessão A (2026-09-26): cria o ledger public.schema_migrations do migrate.py e
-- registra a lista nominal aprovada. Uma única transação: qualquer divergência
-- aborta tudo (ROLLBACK implícito), sem estado parcial.
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

\echo == ANTES (dentro da transação) ==
SELECT current_user, current_setting('server_version') AS pg, to_regclass('public.schema_migrations') AS ledger_antes;
SELECT evtname, evtevent, evtenabled, evtfoid::regprocedure AS func FROM pg_event_trigger WHERE evtname = 'ensure_rls';
SELECT md5(pg_get_functiondef(to_regprocedure('public.rls_auto_enable()'))) AS rls_auto_enable_md5;
SELECT pg_get_userbyid(d.defaclrole) AS role, d.defaclobjtype AS tipo, d.defaclacl::text AS acl
  FROM pg_default_acl d JOIN pg_namespace n ON n.oid = d.defaclnamespace
 WHERE n.nspname = 'public' AND d.defaclobjtype = 'r' ORDER BY 1;

DO $guard$
BEGIN
  IF current_user <> 'postgres' THEN
    RAISE EXCEPTION 'conexao inesperada: %', current_user;
  END IF;
  IF to_regclass('public.schema_migrations') IS NOT NULL THEN
    RAISE EXCEPTION 'public.schema_migrations ja existe; nada foi feito';
  END IF;
  IF md5(pg_get_functiondef(to_regprocedure('public.rls_auto_enable()'))) IS DISTINCT FROM '6998ea6b4c2480f5d2e34b5dcf3f8d36' THEN
    RAISE EXCEPTION 'rls_auto_enable() mudou desde a inspecao';
  END IF;
END
$guard$;

CREATE TABLE public.schema_migrations (
  name       text        NOT NULL,
  applied_at timestamptz NOT NULL DEFAULT now(),
  origem     text        NOT NULL DEFAULT 'MIGRATE_PY',
  CONSTRAINT schema_migrations_pkey PRIMARY KEY (name),
  CONSTRAINT schema_migrations_origem_check
    CHECK (origem IN ('PROVA_OBJETO', 'BASELINE_V1_HISTORICO', 'MIGRATE_PY'))
);
-- O event trigger ensure_rls já faz ENABLE; explícito para não depender dele. Sem FORCE.
ALTER TABLE public.schema_migrations ENABLE ROW LEVEL SECURITY;
-- Default privileges do Supabase concedem ALL a anon/authenticated: revogar na MESMA transação.
REVOKE ALL ON TABLE public.schema_migrations FROM PUBLIC, anon, authenticated;
COMMENT ON TABLE public.schema_migrations IS
  'Ledger do backend/scripts/migrate.py (processo simples do MVP). Criado em 2026-09-26 (Sessao A) com registro nominal de 69 migrations: 63 PROVA_OBJETO e 6 BASELINE_V1_HISTORICO. Linhas novas do migrate.py recebem origem MIGRATE_PY. Evidencia: docs/sprints/2026-09-26-prod-sessao-a-ledger-e-deploy.md';
COMMENT ON COLUMN public.schema_migrations.applied_at IS
  'Nas linhas PROVA_OBJETO e BASELINE_V1_HISTORICO e a data do registro (2026-09-26), nao a da aplicacao original.';

INSERT INTO public.schema_migrations (name, origem) VALUES
  ('0001_extensions_and_enums.sql', 'PROVA_OBJETO'),
  ('0002_schema_tables.sql', 'PROVA_OBJETO'),
  ('0003_rls_policies.sql', 'PROVA_OBJETO'),
  ('0004_triggers.sql', 'PROVA_OBJETO'),
  ('0005_seed.sql', 'BASELINE_V1_HISTORICO'),
  ('0006_harden_function_search_path.sql', 'PROVA_OBJETO'),
  ('0007_remove_demo_data.sql', 'BASELINE_V1_HISTORICO'),
  ('0008_add_operador_role.sql', 'PROVA_OBJETO'),
  ('0009_unify_system_managers.sql', 'BASELINE_V1_HISTORICO'),
  ('0010_platform_admins.sql', 'PROVA_OBJETO'),
  ('0011_app_users_celula_pendente.sql', 'PROVA_OBJETO'),
  ('0012_planos.sql', 'PROVA_OBJETO'),
  ('0013_platform_audit_log.sql', 'PROVA_OBJETO'),
  ('0014_platform_orchestrator.sql', 'PROVA_OBJETO'),
  ('0015_message_media.sql', 'PROVA_OBJETO'),
  ('0016_message_author.sql', 'PROVA_OBJETO'),
  ('0017_app_user_status_revogado.sql', 'PROVA_OBJETO'),
  ('20260623_103319_pessoa_sem_interesse_csim.sql', 'PROVA_OBJETO'),
  ('20260623_122044_calendar_sync_oauth_por_igreja.sql', 'PROVA_OBJETO'),
  ('20260623_154500_pessoa_tipo_add_contato.sql', 'PROVA_OBJETO'),
  ('20260623_170000_igreja_dono_assinatura.sql', 'PROVA_OBJETO'),
  ('20260624_003030_current_igreja_id_guc_worker.sql', 'PROVA_OBJETO'),
  ('20260624_090102_current_igreja_id_guard_empty_claims.sql', 'PROVA_OBJETO'),
  ('20260624_171110_agent_config_requests_fila_requisicao_admin_master.sql', 'PROVA_OBJETO'),
  ('20260629_222635_evt1_events_agenda_schema_status_tipo_origem_recorrencia_confirmacao.sql', 'PROVA_OBJETO'),
  ('20260701_014654_evt6_google_event_dedup_index.sql', 'PROVA_OBJETO'),
  ('20260701_164352_evt7_events_notificado_em_aviso_confirmacao.sql', 'PROVA_OBJETO'),
  ('20260701_193000_evt7_pr2_agenda_alert_recipients.sql', 'PROVA_OBJETO'),
  ('20260703_123803_celula_schema_base_pr1.sql', 'PROVA_OBJETO'),
  ('20260704_100000_celula_pr2_reuniao_presenca_expectativa.sql', 'PROVA_OBJETO'),
  ('20260705_120000_celula_pr3_reuniao_relatorio_campos.sql', 'PROVA_OBJETO'),
  ('20260705_120100_celula_pr3_reuniao_registro.sql', 'PROVA_OBJETO'),
  ('20260705_120200_celula_pr3_visitante.sql', 'PROVA_OBJETO'),
  ('20260705_120300_celula_pr3_solicitacao_evento.sql', 'PROVA_OBJETO'),
  ('20260705_120400_celula_pr3_aviso.sql', 'PROVA_OBJETO'),
  ('20260705_120500_celula_pr3_material.sql', 'PROVA_OBJETO'),
  ('20260705_120600_celula_pr3_multiplicacoes_evolucao.sql', 'PROVA_OBJETO'),
  ('20260706_221311_pessoas_apto_lider_e_converte_legado_tipo_lider.sql', 'PROVA_OBJETO'),
  ('20260706_230000_evt8_pr1_notify_config.sql', 'PROVA_OBJETO'),
  ('20260707_011455_igreja_logo_branding.sql', 'PROVA_OBJETO'),
  ('20260708_160128_sec3a_app_users_password_changed_at.sql', 'PROVA_OBJETO'),
  ('20260708_164756_backfill_celula_membro_canonico.sql', 'BASELINE_V1_HISTORICO'),
  ('20260708_172106_sec3b_password_reset_tokens_single_use.sql', 'PROVA_OBJETO'),
  ('20260708_221808_igreja_dono_id_grant_update.sql', 'PROVA_OBJETO'),
  ('20260709_204500_sec4_agent_event_idempotency_marker_uidx.sql', 'PROVA_OBJETO'),
  ('20260711_224403_celula_solicitacao_e13_open_unique.sql', 'PROVA_OBJETO'),
  ('20260713_013054_pessoa_arquivamento_schema.sql', 'PROVA_OBJETO'),
  ('20260713_032015_pessoa_offboarding_preflight_arquivamento_evento.sql', 'PROVA_OBJETO'),
  ('20260715_204540_msg_idemp1_messages_inbound_provider_id_uidx.sql', 'PROVA_OBJETO'),
  ('20260715_204541_consolidacao_aberta_unica_por_pessoa.sql', 'PROVA_OBJETO'),
  ('20260720_014832_pessoa_telefone_unico_por_tenant_ativa.sql', 'PROVA_OBJETO'),
  ('20260720_191143_consent_records_ator_id_reoptin.sql', 'PROVA_OBJETO'),
  ('20260730_205332_billing_setup_configuration.sql', 'PROVA_OBJETO'),
  ('20260731_120000_calendar_oauth_flows_pkce.sql', 'PROVA_OBJETO'),
  ('20260801_031500_calendar_account_identity_binding.sql', 'PROVA_OBJETO'),
  ('20260805_105133_broadcast_delivery.sql', 'PROVA_OBJETO'),
  ('20260805_120000_calendar_fk_indexes.sql', 'PROVA_OBJETO'),
  ('20260805_153000_security_definer_execute_hardening.sql', 'PROVA_OBJETO'),
  ('20260808_001059_billing_count_active_members.sql', 'PROVA_OBJETO'),
  ('20260808_011500_messages_outbound_provider_id_uidx.sql', 'PROVA_OBJETO'),
  ('20260808_014425_billing_member_plan_label_variants.sql', 'BASELINE_V1_HISTORICO'),
  ('20260808_023500_billing_reconcile_prepared_member_upgrades.sql', 'BASELINE_V1_HISTORICO'),
  ('20260808_135841_llm_model_selection_per_tenant.sql', 'PROVA_OBJETO'),
  ('20260810_031050_explicit_deny_policies_for_closed_tables.sql', 'PROVA_OBJETO'),
  ('20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade.sql', 'PROVA_OBJETO'),
  ('20260822_225752_celula_membro_evento_audit_table.sql', 'PROVA_OBJETO'),
  ('20260824_180000_asaas_formal_isolation.sql', 'PROVA_OBJETO'),
  ('20260826_030508_separar_estado_resposta_agente_de_autor_mensagem.sql', 'PROVA_OBJETO'),
  ('20260826_094317_harden_recovery_artifacts_retention.sql', 'PROVA_OBJETO');

DO $post$
DECLARE
  rel oid := to_regclass('public.schema_migrations');
  r text;
BEGIN
  IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid = rel) THEN
    RAISE EXCEPTION 'RLS nao habilitado no ledger';
  END IF;
  IF (SELECT relforcerowsecurity FROM pg_class WHERE oid = rel) THEN
    RAISE EXCEPTION 'FORCE RLS inesperado no ledger';
  END IF;
  IF (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = rel) <> 'postgres' THEN
    RAISE EXCEPTION 'dono inesperado do ledger';
  END IF;
  FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
    IF has_table_privilege(r, rel, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER,MAINTAIN')
       OR has_any_column_privilege(r, rel, 'SELECT,INSERT,UPDATE,REFERENCES') THEN
      RAISE EXCEPTION 'role % ainda tem privilegio no ledger', r;
    END IF;
  END LOOP;
  IF EXISTS (SELECT 1 FROM pg_policy WHERE polrelid = rel) THEN
    RAISE EXCEPTION 'policy inesperada no ledger';
  END IF;
  IF (SELECT count(*) FROM public.schema_migrations) <> 69
     OR (SELECT count(*) FROM public.schema_migrations WHERE origem = 'PROVA_OBJETO') <> 63
     OR (SELECT count(*) FROM public.schema_migrations WHERE origem = 'BASELINE_V1_HISTORICO') <> 6 THEN
    RAISE EXCEPTION 'contagem do ledger divergente';
  END IF;
  IF (SELECT md5(string_agg(name || ':' || origem, ',' ORDER BY name COLLATE "C")) FROM public.schema_migrations) <> '1a5c405f1a7efd47945ffab969fba706' THEN
    RAISE EXCEPTION 'conteudo do ledger divergente da lista aprovada';
  END IF;
END
$post$;

COMMIT;
