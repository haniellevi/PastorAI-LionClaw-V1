-- ============================================================================
-- semente_dev.sql - passo 7 do espelho DEV = PROD (27/09/2026): dados de teste.
--
-- Só no DEV recriado (trava abaixo), numa transação única:
--   1. carrega os dados fictícios que as migrations do repositório criam num banco
--      vazio (0005 seed menos o que a 0007 remove, 0009, 0012, 0014, 20260730):
--      "Igreja Piloto PastorAI", "Pastor Piloto", planos, permissões, modelo do
--      orquestrador e configuração de cobrança. Gerados aplicando as 70 migrations
--      do ledger num Supabase 17.6 local descartável (pg_dump --data-only
--      --column-inserts). Carga sem gatilhos (session_replication_role = replica)
--      porque os gatilhos já rodaram quando esses dados nasceram; os vínculos
--      (FKs) são conferidos logo depois;
--   2. devolve à igreja fictícia os logins de teste guardados por
--      guardar_logins_dev.sql (o login com o id do Pastor Piloto é fundido a ele,
--      com os papéis que tinha no DEV) e apaga o schema temporário;
--   3. confere contagens e vínculos; qualquer divergência desfaz tudo.
-- Nenhum dado real além das contas de teste do proprietário que já estavam no DEV
-- (decisão "ok para A", 27/09). Não imprime nada além de contagens.
--
--   psql service=pastorai_dev -X -q -f semente_dev.sql
-- ============================================================================
\set ON_ERROR_STOP on
BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';
SET LOCAL search_path = pg_catalog, pg_temp;
SET LOCAL client_min_messages = warning;

-- TRAVA: só o DEV recriado igual ao PROD, ainda sem dados e com os logins guardados.
DO $trava$
DECLARE n bigint; m text;
BEGIN
  IF current_user <> 'postgres' THEN RAISE EXCEPTION 'conexão inesperada: %', current_user; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = to_regclass('public.schema_migrations')
                   AND attname = 'origem' AND attnum > 0 AND NOT attisdropped) THEN
    RAISE EXCEPTION 'ledger sem origem: o DEV ainda não foi recriado';
  END IF;
  SELECT count(*), md5(string_agg(name || ':' || origem, ',' ORDER BY name COLLATE "C")) INTO n, m
    FROM public.schema_migrations;
  IF n <> 70 OR m <> 'dd161e3863956b19baf220ca5f3cf991' THEN
    RAISE EXCEPTION 'ledger diferente do espelhado do PROD (% linhas, %)', n, m;
  END IF;
  IF EXISTS (SELECT 1 FROM public.igrejas) OR EXISTS (SELECT 1 FROM public.app_users)
     OR EXISTS (SELECT 1 FROM public.pessoas) THEN
    RAISE EXCEPTION 'o banco já tem dados (igrejas/app_users/pessoas): não é o DEV recém-recriado';
  END IF;
  IF to_regclass('pastorai_semente_tmp.logins') IS NULL THEN
    RAISE EXCEPTION 'logins guardados ausentes (pastorai_semente_tmp.logins)';
  END IF;
END
$trava$;

-- 1. DADOS FICTÍCIOS DAS MIGRATIONS (carga sem gatilhos nem checagem de FK).
SET LOCAL session_replication_role = replica;
--
-- Data for Name: igrejas; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.igrejas (id, nome, status, plano, created_at, dono_id, logo_path, setup_fee_override) VALUES ('00000000-0000-0000-0000-000000000001', 'Igreja Piloto PastorAI', 'ativa', 'ate_100', '2026-09-27 11:31:34.521989+00', '00000000-0000-0000-0000-0000000000a1', NULL, NULL);


--
-- Data for Name: agenda_alert_recipients; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: pessoas; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.pessoas (id, igreja_id, nome, telefone, email, genero, faixa_etaria, endereco, tipo, etapa, subetapa, presencas_celula, aceitou_jesus, acompanhamento, origem, primeiro_contato, celula_id, lider_id, consentimento, optout, apto_proxima_cd, created_at, sem_interesse, sem_interesse_motivo, apto_lider, arquivada_em, arquivada_por, arquivada_motivo) VALUES ('00000000-0000-0000-0000-0000000000b1', '00000000-0000-0000-0000-000000000001', 'Pastor Piloto', '+5511999990001', 'pastor@igrejapiloto.com', NULL, NULL, NULL, 'pastor', 'enviar', 'consolidado', 0, false, 'consolidado', NULL, NULL, NULL, NULL, false, false, false, '2026-09-27 11:31:34.521989+00', false, NULL, false, NULL, NULL, NULL);


--
-- Data for Name: celulas; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: app_users; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.app_users (id, igreja_id, clerk_user_id, pessoa_id, nome, email, status, created_at, celula_pendente_id, chat_nome, password_changed_at) VALUES ('00000000-0000-0000-0000-0000000000a1', '00000000-0000-0000-0000-000000000001', 'user_seed_pastor_clerk_id', '00000000-0000-0000-0000-0000000000b1', 'Pastor Piloto', 'pastor@igrejapiloto.com', 'ativo', '2026-09-27 11:31:34.521989+00', NULL, NULL, NULL);


--
-- Data for Name: agent_config_requests; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: agent_configs; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.agent_configs (id, igreja_id, nome, tom, comportamento, publico_alvo, acessos, ativo, informacoes_publicas) VALUES ('24a15d17-b47c-4d4d-8327-6ae6f8a7b5b3', '00000000-0000-0000-0000-000000000001', 'Assistente PastorAI', 'acolhedor', 'Voce e o assistente pastoral da igreja. Acolhe novos contatos com carinho, coleta dados basicos (nome, telefone, endereco), convida para a celula mais proxima e nunca inicia conversas espontaneas. Sempre respeita consentimento (LGPD).', '{visitante,membro}', '{contatos,celulas,calendario}', true, '{}');


--
-- Data for Name: conversations; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: agent_conversation_logs; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: ai_usage_logs; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: asaas_webhook_receipts; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: subscriptions; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.subscriptions (id, igreja_id, plano, status, pessoas, limite, proxima_cobranca, asaas_customer_id, asaas_subscription_id, setup_pago, asaas_setup_charge_id, asaas_setup_reversed_payment_id, setup_fee_contracted, asaas_invoice_url, asaas_setup_invoice_url, asaas_invoice_payment_id, asaas_invoice_reversal, asaas_customer_external_reference, asaas_subscription_external_reference) VALUES ('5647ad52-a85b-4827-b3a0-eed9e7273d4c', '00000000-0000-0000-0000-000000000001', 'ate_100', 'ativa', 1, 100, NULL, NULL, NULL, true, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);


--
-- Data for Name: billing_payment_operations; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: billing_plan_change_operations; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: billing_settings; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.billing_settings (id, setup_fee_default, updated_at) VALUES (1, NULL, '2026-09-27 11:31:37.907547+00');


--
-- Data for Name: billing_subscription_operations; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: broadcasts; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: broadcast_execucoes; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: broadcast_entregas; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: calendar_oauth_flows; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: calendar_sync; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: cell_alerts; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: celula_aviso; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: celula_reuniao; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: celula_expectativa_visitante; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: celula_material; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: celula_membro; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: celula_membro_evento; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: celula_presenca; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: celula_reuniao_registro; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: celula_solicitacao; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: celula_solicitacao_evento; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: celula_visitante; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: consent_records; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: consolidacoes; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: consolidacao_etapas; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: crons; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: decisions; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: events; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: event_notify_targets; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: llm_credentials; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: messages; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: multiplicacoes; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: password_reset_tokens; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: pessoa_arquivamento_evento; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: planos; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.planos (id, codigo, nome, limite_pessoas, preco_mensal, ativo, ordem, created_at) VALUES ('5a065b04-c8e3-4e86-b932-041f57eb044e', 'ate_100', 'Até 100 membros', 100, 199.00, true, 1, '2026-09-27 11:31:35.020747+00');
INSERT INTO public.planos (id, codigo, nome, limite_pessoas, preco_mensal, ativo, ordem, created_at) VALUES ('ebf32c4c-93b9-4b03-8109-57e65e385b5a', 'acima_201', '201+ membros', NULL, 399.00, true, 3, '2026-09-27 11:31:35.020747+00');
INSERT INTO public.planos (id, codigo, nome, limite_pessoas, preco_mensal, ativo, ordem, created_at) VALUES ('521bfabd-f526-4ad8-80e5-dd12e7e68979', '101_200', '101–200 membros', 200, 299.00, true, 2, '2026-09-27 11:31:35.020747+00');


--
-- Data for Name: platform_admins; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: platform_audit_log; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: platform_orchestrator; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.platform_orchestrator (id, nome, tom, comportamento, updated_at) VALUES ('0a695df5-dcd2-404e-866f-1fbceb203c40', 'Assistente da Igreja', 'acolhedor e pastoral', 'Você é o agente da igreja no WhatsApp. Acolha cada pessoa com cuidado pastoral, entenda a necessidade dela, e conduza com simplicidade e respeito. Registre decisões, visitas e dados usando as ferramentas disponíveis — nunca invente informações nem prometa o que não pode cumprir. Quando não souber, ofereça encaminhar para um líder humano.', '2026-09-27 11:31:35.156626+00');


--
-- Data for Name: reports; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: role_permissions; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('3d02865a-e9e1-439b-b2cd-92decd789bc4', '00000000-0000-0000-0000-000000000001', 'pastor', 'dashboard');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('cfec7a09-a73f-485d-906a-49e1faf54838', '00000000-0000-0000-0000-000000000001', 'lider_g12', 'dashboard');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('63a2e21f-79d1-453a-969d-8c756060a13f', '00000000-0000-0000-0000-000000000001', 'lider_consol', 'dashboard');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('0d1d3aac-c110-4d18-a331-80061b3b9f71', '00000000-0000-0000-0000-000000000001', 'lider_celula', 'dashboard');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('f6451557-b142-469b-9e63-1700b1a3e56d', '00000000-0000-0000-0000-000000000001', 'lider_mult', 'dashboard');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('b1838e73-332f-48b6-b29e-c735c90add8c', '00000000-0000-0000-0000-000000000001', 'membro', 'dashboard');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('dcc6302e-7369-4aa4-be8b-23420f220c83', '00000000-0000-0000-0000-000000000001', 'lider_celula', 'ganhar');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('fdbcc7b3-ac0c-4cba-9a57-d18dd00cf607', '00000000-0000-0000-0000-000000000001', 'lider_celula', 'central-celula');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('42e12d68-d1ec-4d26-bf56-38330cd7d127', '00000000-0000-0000-0000-000000000001', 'lider_celula', 'g12');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('df94c1d1-ed01-4ae5-8e52-a090da317bba', '00000000-0000-0000-0000-000000000001', 'lider_consol', 'consolidar');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('570fe918-b723-4716-84cb-3254fef12a9c', '00000000-0000-0000-0000-000000000001', 'lider_consol', 'consol-individual');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('4f7afbfb-bd5d-4341-a8e8-117ed0d1fdce', '00000000-0000-0000-0000-000000000001', 'pastor', 'ganhar');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('b7cf94c7-0041-447a-941a-d802f590ed85', '00000000-0000-0000-0000-000000000001', 'pastor', 'consolidar');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('cce40c06-bf52-4db2-adfd-cafac503bd52', '00000000-0000-0000-0000-000000000001', 'pastor', 'consol-individual');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('6fdeecc5-2dfc-4016-9906-6246b6e85662', '00000000-0000-0000-0000-000000000001', 'pastor', 'g12');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('d999972a-19a3-4ea9-8067-d4916dd95157', '00000000-0000-0000-0000-000000000001', 'pastor', 'central-celula');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('ba34b6d1-57e1-40f7-9139-ccef205e743b', '00000000-0000-0000-0000-000000000001', 'pastor', 'enviar');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('a5c56d88-2dee-46c0-83eb-c849b5c0d880', '00000000-0000-0000-0000-000000000001', 'pastor', 'comunicados');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('23b7ccaf-e3d1-4775-a3cc-3311a122852e', '00000000-0000-0000-0000-000000000001', 'pastor', 'calendario');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('b25f00e2-b88a-48c0-8063-f185b2a19ee2', '00000000-0000-0000-0000-000000000001', 'pastor', 'relatorios');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('f88f889a-4243-42ad-ad17-09e5dba96daf', '00000000-0000-0000-0000-000000000001', 'lider_g12', 'g12');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('98c2a708-6afd-47ab-aac0-0b2ba5ce3f50', '00000000-0000-0000-0000-000000000001', 'lider_g12', 'central-celula');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('64ea692c-1eda-4ca2-abd7-2f6d38c28536', '00000000-0000-0000-0000-000000000001', 'lider_g12', 'ganhar');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('16037b3b-0c3d-49a4-8ead-a4d617835c03', '00000000-0000-0000-0000-000000000001', 'lider_g12', 'enviar');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('70db3daa-b14b-4746-a093-90cacdeeade6', '00000000-0000-0000-0000-000000000001', 'operador', 'dashboard');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('90070665-8e15-4ad0-98b6-65cb54a6a75d', '00000000-0000-0000-0000-000000000001', 'operador', 'inbox');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('7a298375-8e9b-4a06-95f6-ebddf7522eed', '00000000-0000-0000-0000-000000000001', 'operador', 'contatos');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('0ea4d763-34de-4cb1-a26a-80db6bac3174', '00000000-0000-0000-0000-000000000001', 'operador', 'ganhar');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('9fa7541f-75b5-46ff-b1f2-98ce8c3f67c5', '00000000-0000-0000-0000-000000000001', 'operador', 'celulas');
INSERT INTO public.role_permissions (id, igreja_id, papel, tela) VALUES ('8a20797a-bb54-4b54-8fba-b49e98abc82d', '00000000-0000-0000-0000-000000000001', 'operador', 'relatorios');


--
-- Data for Name: system_managers; Type: TABLE DATA; Schema: public; Owner: postgres
--



--
-- Data for Name: user_roles; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.user_roles (id, igreja_id, user_id, papel) VALUES ('44bee73a-c8fe-45ce-bb66-a77f2b5bdc92', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000a1', 'admin');
INSERT INTO public.user_roles (id, igreja_id, user_id, papel) VALUES ('2e0f130f-b63a-4f62-8a4a-962ef84f303c', '00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000a1', 'pastor');


--
-- Data for Name: whatsapp_connections; Type: TABLE DATA; Schema: public; Owner: postgres
--

INSERT INTO public.whatsapp_connections (id, igreja_id, numero, status, instance, ultima_sync) VALUES ('89c22caf-4ea6-4243-a0df-79f68e29bf92', '00000000-0000-0000-0000-000000000001', NULL, 'offline', NULL, NULL);


--
-- Data for Name: work_queue_items; Type: TABLE DATA; Schema: public; Owner: postgres
--
SET LOCAL session_replication_role = origin;

-- Vínculos: toda FK de public satisfeita pelas linhas carregadas.
DO $fks$
DECLARE r record; orfas bigint;
BEGIN
  FOR r IN
    SELECT c.conname, c.conrelid::regclass AS filha, c.confrelid::regclass AS mae,
           (SELECT string_agg(format('f.%I = m.%I', fa.attname, ma.attname), ' AND ' ORDER BY k.i)
              FROM unnest(c.conkey, c.confkey) WITH ORDINALITY AS k(fcol, mcol, i)
              JOIN pg_attribute AS fa ON fa.attrelid = c.conrelid AND fa.attnum = k.fcol
              JOIN pg_attribute AS ma ON ma.attrelid = c.confrelid AND ma.attnum = k.mcol) AS junta,
           (SELECT string_agg(format('f.%I IS NOT NULL', fa.attname), ' AND ' ORDER BY k.i)
              FROM unnest(c.conkey) WITH ORDINALITY AS k(fcol, i)
              JOIN pg_attribute AS fa ON fa.attrelid = c.conrelid AND fa.attnum = k.fcol) AS preenchida
      FROM pg_constraint AS c
     WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace
  LOOP
    EXECUTE format('SELECT count(*) FROM %s AS f WHERE %s AND NOT EXISTS (SELECT 1 FROM %s AS m WHERE %s)',
                   r.filha, r.preenchida, r.mae, r.junta) INTO orfas;
    IF orfas > 0 THEN
      RAISE EXCEPTION 'vínculo quebrado na FK % (% linha(s) de % sem %)', r.conname, orfas, r.filha, r.mae;
    END IF;
  END LOOP;
END
$fks$;

-- 2. LOGINS DE TESTE GUARDADOS -> "Igreja Piloto PastorAI".
-- O login com o mesmo id de um app_user da semente (o Pastor Piloto) é fundido a ele.
UPDATE public.app_users AS u
   SET clerk_user_id = l.clerk_user_id, nome = l.nome, email = l.email,
       status = l.status::public.app_user_status, chat_nome = l.chat_nome
  FROM pastorai_semente_tmp.logins AS l
 WHERE u.id = l.app_user_id;
INSERT INTO public.app_users (id, igreja_id, clerk_user_id, nome, email, status, chat_nome)
SELECT l.app_user_id, '00000000-0000-0000-0000-000000000001', l.clerk_user_id, l.nome, l.email,
       l.status::public.app_user_status, l.chat_nome
  FROM pastorai_semente_tmp.logins AS l
 WHERE NOT EXISTS (SELECT 1 FROM public.app_users AS u WHERE u.id = l.app_user_id);
-- Papéis: exatamente os que cada login tinha no DEV (substituem os da semente).
DELETE FROM public.user_roles AS r USING pastorai_semente_tmp.logins AS l WHERE r.user_id = l.app_user_id;
INSERT INTO public.user_roles (igreja_id, user_id, papel)
SELECT '00000000-0000-0000-0000-000000000001', l.app_user_id, p.papel::public.user_role_papel
  FROM pastorai_semente_tmp.logins AS l CROSS JOIN LATERAL unnest(l.papeis) AS p(papel);
INSERT INTO public.platform_admins (app_user_id, email)
SELECT l.app_user_id, l.email FROM pastorai_semente_tmp.logins AS l WHERE l.admin_plataforma;

-- 3. CONFERÊNCIA antes do COMMIT.
DO $confere$
DECLARE t record; n bigint;
BEGIN
  FOR t IN SELECT * FROM (VALUES ('agent_configs', 1), ('app_users', 1), ('billing_settings', 1), ('igrejas', 1), ('pessoas', 1), ('planos', 3), ('platform_orchestrator', 1), ('role_permissions', 30), ('subscriptions', 1), ('user_roles', 2), ('whatsapp_connections', 1)) AS e(tabela, linhas)
            WHERE tabela NOT IN ('app_users', 'user_roles') LOOP
    EXECUTE format('SELECT count(*) FROM public.%I', t.tabela) INTO n;
    IF n <> t.linhas THEN RAISE EXCEPTION 'public.% com % linhas (esperado %)', t.tabela, n, t.linhas; END IF;
  END LOOP;
  -- app_users = logins guardados + os da semente que não foram fundidos (o Pastor Piloto, se não houve fusão)
  IF (SELECT count(*) FROM public.app_users) <>
     (SELECT count(*) FROM pastorai_semente_tmp.logins)
     + (SELECT count(*) FROM (VALUES ('00000000-0000-0000-0000-0000000000a1'::uuid)) AS s(id)
         WHERE NOT EXISTS (SELECT 1 FROM pastorai_semente_tmp.logins AS l WHERE l.app_user_id = s.id)) THEN
    RAISE EXCEPTION 'app_users com contagem inesperada';
  END IF;
  IF EXISTS (SELECT 1 FROM pastorai_semente_tmp.logins AS l
              WHERE NOT EXISTS (SELECT 1 FROM public.app_users AS u
                                 WHERE u.id = l.app_user_id AND u.clerk_user_id IS NOT DISTINCT FROM l.clerk_user_id
                                   AND u.igreja_id = '00000000-0000-0000-0000-000000000001')) THEN
    RAISE EXCEPTION 'algum login guardado não voltou para a igreja fictícia';
  END IF;
  IF (SELECT count(*) FROM public.user_roles AS r JOIN pastorai_semente_tmp.logins AS l ON l.app_user_id = r.user_id)
     <> (SELECT coalesce(sum(cardinality(papeis)), 0) FROM pastorai_semente_tmp.logins) THEN
    RAISE EXCEPTION 'papéis dos logins guardados divergentes';
  END IF;
  IF (SELECT count(*) FROM public.platform_admins)
     <> (SELECT count(*) FROM pastorai_semente_tmp.logins WHERE admin_plataforma) THEN
    RAISE EXCEPTION 'admins de plataforma divergentes';
  END IF;
  IF EXISTS (SELECT 1 FROM public.app_users WHERE igreja_id <> '00000000-0000-0000-0000-000000000001') THEN
    RAISE EXCEPTION 'app_user fora da igreja fictícia';
  END IF;
END
$confere$;

SELECT (SELECT count(*) FROM public.igrejas) AS igrejas, (SELECT count(*) FROM public.app_users) AS logins,
       (SELECT count(*) FROM public.user_roles) AS papeis, (SELECT count(*) FROM public.platform_admins) AS admins_plataforma,
       (SELECT count(*) FROM public.planos) AS planos, (SELECT count(*) FROM public.role_permissions) AS permissoes;
DROP SCHEMA pastorai_semente_tmp CASCADE;
COMMIT;
