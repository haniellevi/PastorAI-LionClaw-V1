-- ============================================================================
-- PastorAI 1.0 — Migration 0005: Seed da igreja piloto
-- SPEC secao 2.4. Deve ser executado com service role (bypassa RLS).
-- Idempotente via UUIDs fixos + ON CONFLICT DO NOTHING.
--
-- A igreja piloto e apenas o 1o registro de igrejas (F1).
-- ============================================================================

begin;

-- ----------------------------------------------------------------------------
-- UUIDs fixos do seed (deterministicos)
-- ----------------------------------------------------------------------------
-- igreja .................. 00000000-0000-0000-0000-000000000001
-- app_user admin/pastor ... 00000000-0000-0000-0000-0000000000a1
-- pessoa pastor ........... 00000000-0000-0000-0000-0000000000b1
-- celula piloto ........... 00000000-0000-0000-0000-0000000000c1

-- ----------------------------------------------------------------------------
-- 1) Igreja piloto (status ativa, plano ate_100) — primeiro registro
-- ----------------------------------------------------------------------------
insert into igrejas (id, nome, status, plano)
values ('00000000-0000-0000-0000-000000000001', 'Igreja Piloto PastorAI', 'ativa', 'ate_100')
on conflict (id) do nothing;

-- ----------------------------------------------------------------------------
-- 2) Subscription piloto (ativa, limite 100) — antes de pessoas (autoupgrade)
-- ----------------------------------------------------------------------------
insert into subscriptions (igreja_id, plano, status, pessoas, limite, setup_pago)
values ('00000000-0000-0000-0000-000000000001', 'ate_100', 'ativa', 0, 100, true)
on conflict (igreja_id) do nothing;

-- ----------------------------------------------------------------------------
-- 3) Conexao WhatsApp default (offline)
-- ----------------------------------------------------------------------------
insert into whatsapp_connections (igreja_id, numero, status)
values ('00000000-0000-0000-0000-000000000001', null, 'offline')
on conflict (igreja_id) do nothing;

-- ----------------------------------------------------------------------------
-- 4) Agent config default (comportamento/prompt base)
-- ----------------------------------------------------------------------------
insert into agent_configs (igreja_id, nome, tom, comportamento, publico_alvo, acessos, ativo)
values (
  '00000000-0000-0000-0000-000000000001',
  'Assistente PastorAI',
  'acolhedor',
  'Voce e o assistente pastoral da igreja. Acolhe novos contatos com carinho, '
  || 'coleta dados basicos (nome, telefone, endereco), convida para a celula mais '
  || 'proxima e nunca inicia conversas espontaneas. Sempre respeita consentimento (LGPD).',
  array['visitante', 'membro'],
  array['contatos', 'celulas', 'calendario'],
  true
)
on conflict (igreja_id) do nothing;

-- ----------------------------------------------------------------------------
-- 5) Pessoa do pastor (modelo unificado — F6) + app_user admin
-- ----------------------------------------------------------------------------
insert into pessoas (id, igreja_id, nome, telefone, email, tipo, etapa, subetapa, acompanhamento)
values (
  '00000000-0000-0000-0000-0000000000b1',
  '00000000-0000-0000-0000-000000000001',
  'Pastor Piloto', '+5511999990001', 'pastor@igrejapiloto.com',
  'pastor', 'enviar', 'consolidado', 'consolidado'
)
on conflict (id) do nothing;

insert into app_users (id, igreja_id, clerk_user_id, pessoa_id, nome, email, status)
values (
  '00000000-0000-0000-0000-0000000000a1',
  '00000000-0000-0000-0000-000000000001',
  'user_seed_pastor_clerk_id',                 -- TODO: substituir pelo Clerk user id real do pastor
  '00000000-0000-0000-0000-0000000000b1',
  'Pastor Piloto', 'pastor@igrejapiloto.com', 'ativo'
)
on conflict (id) do nothing;

-- 5.1) user_roles do admin: {admin, pastor} (papeis acumulados — F3)
insert into user_roles (igreja_id, user_id, papel) values
  ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000a1', 'admin'),
  ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000a1', 'pastor')
on conflict (user_id, papel) do nothing;

-- ----------------------------------------------------------------------------
-- 6) role_permissions default (delta-010)
--    - dashboard liberado a TODOS os papeis (admin tem acesso implicito)
--    - lider_celula: ganhar / central-celula / g12
--    - lider_consol: consolidar / consol-individual
--    - pastor / lider_g12: acessos amplos do ciclo G12
-- ----------------------------------------------------------------------------
insert into role_permissions (igreja_id, papel, tela) values
  -- dashboard para todos os papeis
  ('00000000-0000-0000-0000-000000000001', 'pastor',       'dashboard'),
  ('00000000-0000-0000-0000-000000000001', 'lider_g12',    'dashboard'),
  ('00000000-0000-0000-0000-000000000001', 'lider_consol', 'dashboard'),
  ('00000000-0000-0000-0000-000000000001', 'lider_celula', 'dashboard'),
  ('00000000-0000-0000-0000-000000000001', 'lider_mult',   'dashboard'),
  ('00000000-0000-0000-0000-000000000001', 'membro',       'dashboard'),
  -- lider_celula
  ('00000000-0000-0000-0000-000000000001', 'lider_celula', 'ganhar'),
  ('00000000-0000-0000-0000-000000000001', 'lider_celula', 'central-celula'),
  ('00000000-0000-0000-0000-000000000001', 'lider_celula', 'g12'),
  -- lider_consol
  ('00000000-0000-0000-0000-000000000001', 'lider_consol', 'consolidar'),
  ('00000000-0000-0000-0000-000000000001', 'lider_consol', 'consol-individual'),
  -- pastor (visao ampla do ciclo)
  ('00000000-0000-0000-0000-000000000001', 'pastor', 'ganhar'),
  ('00000000-0000-0000-0000-000000000001', 'pastor', 'consolidar'),
  ('00000000-0000-0000-0000-000000000001', 'pastor', 'consol-individual'),
  ('00000000-0000-0000-0000-000000000001', 'pastor', 'g12'),
  ('00000000-0000-0000-0000-000000000001', 'pastor', 'central-celula'),
  ('00000000-0000-0000-0000-000000000001', 'pastor', 'enviar'),
  ('00000000-0000-0000-0000-000000000001', 'pastor', 'comunicados'),
  ('00000000-0000-0000-0000-000000000001', 'pastor', 'calendario'),
  ('00000000-0000-0000-0000-000000000001', 'pastor', 'relatorios'),
  -- lider_g12
  ('00000000-0000-0000-0000-000000000001', 'lider_g12', 'g12'),
  ('00000000-0000-0000-0000-000000000001', 'lider_g12', 'central-celula'),
  ('00000000-0000-0000-0000-000000000001', 'lider_g12', 'ganhar'),
  ('00000000-0000-0000-0000-000000000001', 'lider_g12', 'enviar')
on conflict (igreja_id, papel, tela) do nothing;

-- ----------------------------------------------------------------------------
-- 7) Amostras de dominio (delta-003) — NAO sao dados de producao.
--    Demonstram estados do pipeline / inbox / relatorios.
-- ----------------------------------------------------------------------------

-- 7.1) Celula piloto (lider = pastor)
insert into celulas (id, igreja_id, nome, lider_id, dia_reuniao, cobertura_espiritual, ativo)
values (
  '00000000-0000-0000-0000-0000000000c1',
  '00000000-0000-0000-0000-000000000001',
  'Celula Central', '00000000-0000-0000-0000-0000000000b1',
  'quarta', 'Pastor Piloto', true
)
on conflict (id) do nothing;

-- 7.2) Contatos em diferentes estados do pipeline
insert into pessoas (id, igreja_id, nome, telefone, tipo, etapa, subetapa, presencas_celula, aceitou_jesus, acompanhamento, origem) values
  ('00000000-0000-0000-0000-0000000000b2', '00000000-0000-0000-0000-000000000001',
   'Maria Visitante', '+5511999990002', 'visitante', 'ganhar', 'novo_contato', 0, false, 'sem', 'whatsapp'),
  ('00000000-0000-0000-0000-0000000000b3', '00000000-0000-0000-0000-000000000001',
   'Joao em Consolidacao', '+5511999990003', 'visitante', 'consolidar', 'em_consolidacao', 2, true, 'em_andamento', 'culto')
on conflict (id) do nothing;

-- membro consolidado vinculado a celula
insert into pessoas (id, igreja_id, nome, telefone, tipo, etapa, subetapa, presencas_celula, aceitou_jesus, acompanhamento, celula_id, lider_id, origem) values
  ('00000000-0000-0000-0000-0000000000b4', '00000000-0000-0000-0000-000000000001',
   'Ana Membro', '+5511999990004', 'membro', 'discipular', 'consolidado', 8, true, 'consolidado',
   '00000000-0000-0000-0000-0000000000c1', '00000000-0000-0000-0000-0000000000b1', 'celula')
on conflict (id) do nothing;

-- 7.3) Conversa de inbox + mensagens
insert into conversations (id, igreja_id, pessoa_id, telefone, estado, ultima_mensagem, nao_lidas)
values (
  '00000000-0000-0000-0000-0000000000d1',
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-0000000000b2',
  '+5511999990002', 'ia', 'Ola! Gostaria de conhecer a igreja.', 1
)
on conflict (id) do nothing;

insert into messages (igreja_id, conversation_id, direcao, autor, texto) values
  ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000d1', 'in',  'contato', 'Ola! Gostaria de conhecer a igreja.'),
  ('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000d1', 'out', 'ia',      'Que alegria ter voce por aqui! Como posso te ajudar?');

-- 7.4) Item de fila aberto (relatorio pendente da celula central)
insert into work_queue_items (igreja_id, tipo, titulo, contexto, status, prioridade)
values (
  '00000000-0000-0000-0000-000000000001',
  'relatorio',
  'Relatorio da Celula Central pendente',
  'celula 00000000-0000-0000-0000-0000000000c1 — semana 2026-W24',
  'aberto', 2
)
on conflict do nothing;

-- 7.5) Relatorio de exemplo (status recebido para demonstrar baixa de fila)
insert into reports (igreja_id, celula_id, semana, data_reuniao, presentes, visitantes, decisoes, status, origem)
values (
  '00000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-0000000000c1',
  '2026-W23', '2026-06-03', 12, 3, 1, 'recebido', 'manual'
);

commit;
