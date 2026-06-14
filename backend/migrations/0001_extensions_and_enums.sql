-- ============================================================================
-- PastorAI 1.0 — Migration 0001: Extensions e Enums
-- SPEC secao 2.1 — tipos enumerados usados pelas tabelas multi-tenant.
-- ============================================================================

begin;

-- ----------------------------------------------------------------------------
-- Extensions
-- ----------------------------------------------------------------------------
create extension if not exists "pgcrypto";   -- gen_random_uuid()

-- ----------------------------------------------------------------------------
-- Enums (idempotentes via DO blocks)
-- ----------------------------------------------------------------------------

-- igrejas.status
do $$ begin
  create type igreja_status as enum ('ativa', 'suspensa', 'aguardando_aprovacao', 'inadimplente');
exception when duplicate_object then null; end $$;

-- pessoas.genero
do $$ begin
  create type pessoa_genero as enum ('m', 'f');
exception when duplicate_object then null; end $$;

-- pessoas.tipo
do $$ begin
  create type pessoa_tipo as enum ('visitante', 'membro', 'lider', 'pastor', 'discipulo');
exception when duplicate_object then null; end $$;

-- pessoas.etapa
do $$ begin
  create type pessoa_etapa as enum ('ganhar', 'consolidar', 'discipular', 'enviar');
exception when duplicate_object then null; end $$;

-- pessoas.subetapa
do $$ begin
  create type pessoa_subetapa as enum ('novo_contato', 'visitante', 'em_consolidacao', 'consolidado');
exception when duplicate_object then null; end $$;

-- pessoas.acompanhamento
do $$ begin
  create type pessoa_acompanhamento as enum ('sem', 'em_andamento', 'consolidado');
exception when duplicate_object then null; end $$;

-- app_users.status
do $$ begin
  create type app_user_status as enum ('ativo', 'convidado');
exception when duplicate_object then null; end $$;

-- user_roles.papel (papeis acumulados — inclui admin)
do $$ begin
  create type user_role_papel as enum ('admin', 'pastor', 'lider_g12', 'lider_consol', 'lider_celula', 'lider_mult', 'membro');
exception when duplicate_object then null; end $$;

-- role_permissions.papel (admin tem acesso implicito, fora do enum)
do $$ begin
  create type role_perm_papel as enum ('pastor', 'lider_g12', 'lider_consol', 'lider_celula', 'lider_mult', 'membro');
exception when duplicate_object then null; end $$;

-- conversations.estado
do $$ begin
  create type conversation_estado as enum ('ia', 'humano', 'aguardando');
exception when duplicate_object then null; end $$;

-- messages.direcao
do $$ begin
  create type message_direcao as enum ('in', 'out');
exception when duplicate_object then null; end $$;

-- messages.autor
do $$ begin
  create type message_autor as enum ('contato', 'ia', 'humano');
exception when duplicate_object then null; end $$;

-- work_queue_items.tipo
do $$ begin
  create type work_queue_tipo as enum ('visitante', 'atendimento', 'relatorio', 'conectar_celula', 'fonovisita');
exception when duplicate_object then null; end $$;

-- work_queue_items.status
do $$ begin
  create type work_queue_status as enum ('aberto', 'assumido', 'resolvido');
exception when duplicate_object then null; end $$;

-- reports.status
do $$ begin
  create type report_status as enum ('recebido', 'pendente');
exception when duplicate_object then null; end $$;

-- reports.origem
do $$ begin
  create type report_origem as enum ('whatsapp_texto', 'whatsapp_audio', 'manual');
exception when duplicate_object then null; end $$;

-- broadcasts.modo
do $$ begin
  create type broadcast_modo as enum ('agora', 'agendado');
exception when duplicate_object then null; end $$;

-- broadcasts.repeticao
do $$ begin
  create type broadcast_repeticao as enum ('once', 'daily', 'weekly', 'biweekly', 'monthly');
exception when duplicate_object then null; end $$;

-- broadcasts.status
do $$ begin
  create type broadcast_status as enum ('rascunho', 'agendado', 'enviado');
exception when duplicate_object then null; end $$;

-- whatsapp_connections.status
do $$ begin
  create type whatsapp_status as enum ('online', 'offline', 'reconectando');
exception when duplicate_object then null; end $$;

-- subscriptions.status
do $$ begin
  create type subscription_status as enum ('ativa', 'pendente', 'inadimplente');
exception when duplicate_object then null; end $$;

-- system_managers.papel_operacional
do $$ begin
  create type system_manager_papel as enum ('admin_sistema', 'operador');
exception when duplicate_object then null; end $$;

-- consolidacoes.tipo
do $$ begin
  create type consolidacao_tipo as enum ('individual', 'universidade_vida');
exception when duplicate_object then null; end $$;

-- decisions.vinculo
do $$ begin
  create type decision_vinculo as enum ('celula', 'visitante');
exception when duplicate_object then null; end $$;

-- multiplicacoes.status
do $$ begin
  create type multiplicacao_status as enum ('agendada', 'sem_agendamento', 'aprovada', 'concluida');
exception when duplicate_object then null; end $$;

commit;
