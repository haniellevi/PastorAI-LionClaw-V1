-- ============================================================================
-- PastorAI — Migration 20260624_171110_agent_config_requests_fila_requisicao_admin_master
-- #10b Fase 1 (delta-043/044): fila de requisição admin → master.
-- O admin da igreja NÃO edita o comportamento do agente (só o master); aqui ele
-- SOLICITA mudanças por mensagem livre. O master lê (console), ajusta a config
-- pelo editor existente e RESOLVE a requisição (atendida|recusada + resposta).
-- Tabela tenant: o admin vê só a própria igreja (RLS); o master acessa todas
-- via BYPASSRLS (plano de plataforma).
--
-- Aplicar manualmente no Supabase, em ordem de nome de arquivo.
-- ============================================================================

begin;

create table if not exists agent_config_requests (
  id uuid primary key default gen_random_uuid(),
  igreja_id uuid not null references igrejas(id) on delete cascade,
  -- quem pediu; SET NULL preserva o histórico se o usuário for removido.
  solicitante_user_id uuid references app_users(id) on delete set null,
  mensagem text not null,
  status text not null default 'pendente',
  resposta text,
  -- platform_admin (app_user) que resolveu; SEM FK (rastro sobrevive à exclusão),
  -- no mesmo espírito do platform_audit_log.
  resolvido_por uuid,
  criado_em timestamptz not null default now(),
  resolvido_em timestamptz,
  constraint agent_config_requests_status_chk
    check (status in ('pendente', 'atendida', 'recusada'))
);

comment on table agent_config_requests is
  'Fila de requisição admin->master para mudanças no agente (#10b Fase 1).';

-- Lista de pendentes por igreja (admin) e por status (master).
create index if not exists ix_agent_config_requests_igreja_status
  on agent_config_requests (igreja_id, status, criado_em desc);

-- RLS por tenant (mesmo padrão de 0003 / calendar_sync): o admin só enxerga e
-- escreve a própria igreja; o master usa a conexão BYPASSRLS.
alter table agent_config_requests enable row level security;
drop policy if exists tenant_isolation on agent_config_requests;
create policy tenant_isolation on agent_config_requests
  for all
  using (igreja_id = current_igreja_id())
  with check (igreja_id = current_igreja_id());

commit;
