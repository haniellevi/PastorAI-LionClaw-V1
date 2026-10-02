-- Expectativa própria de visitante: amplia somente o par ação/alvo fechado.
-- Preserva os sete pares V3, histórico, recibos e permissões existentes.
-- Não ativa gates nem altera RLS ou o domínio humano de expectativas.

begin;
set local lock_timeout = '2s';

alter table public.agent_action_proposals
  drop constraint if exists agent_action_proposals_action_closed,
  drop constraint if exists agent_action_proposals_target_kind_closed;
alter table public.agent_action_proposals
  add constraint agent_action_proposals_action_closed
    check (action in (
      'registrar_decisao',
      'marcar_presenca',
      'enviar_relatorio_celula',
      'configurar_lembrete_agenda',
      'configurar_lembrete_consolidacao',
      'marcar_fonovisita_feita',
      'atribuir_consolidacao',
      'registrar_expectativa_visitante'
    )),
  add constraint agent_action_proposals_target_kind_closed
    check (
      (action in (
        'registrar_decisao',
        'marcar_presenca',
        'configurar_lembrete_consolidacao'
      ) and target_kind = 'pessoa')
      or (action = 'enviar_relatorio_celula' and target_kind = 'reuniao')
      or (action = 'configurar_lembrete_agenda' and target_kind = 'evento')
      or (action = 'marcar_fonovisita_feita' and target_kind = 'pendencia_consolidacao')
      or (action = 'atribuir_consolidacao' and target_kind = 'consolidacao')
      or (action = 'registrar_expectativa_visitante' and target_kind = 'reuniao')
    );

commit;

-- Rollback manual, fonte somente. O lock precede a inspeção global para
-- impedir novas propostas entre a checagem e a restauração do contrato V3.
-- Qualquer estado/tenant com a nova ação impede a reversão sem apagar dados.
-- ROLLBACK-BEGIN
-- begin;
-- set local lock_timeout = '2s';
-- lock table public.agent_action_proposals in access exclusive mode;
-- do $visitor_expectation_rollback$
-- begin
--   if exists (
--     select 1 from public.agent_action_proposals
--     where action = 'registrar_expectativa_visitante'
--   ) then
--     raise exception 'Rollback indisponível: propostas de visitante existentes.'
--       using errcode = 'P0001';
--   end if;
-- end;
-- $visitor_expectation_rollback$;
-- alter table public.agent_action_proposals
--   drop constraint if exists agent_action_proposals_action_closed,
--   drop constraint if exists agent_action_proposals_target_kind_closed;
-- alter table public.agent_action_proposals
--   add constraint agent_action_proposals_action_closed
--     check (action in (
--       'registrar_decisao',
--       'marcar_presenca',
--       'enviar_relatorio_celula',
--       'configurar_lembrete_agenda',
--       'configurar_lembrete_consolidacao',
--       'marcar_fonovisita_feita',
--       'atribuir_consolidacao'
--     )),
--   add constraint agent_action_proposals_target_kind_closed
--     check (
--       (action in (
--         'registrar_decisao',
--         'marcar_presenca',
--         'configurar_lembrete_consolidacao'
--       ) and target_kind = 'pessoa')
--       or (action = 'enviar_relatorio_celula' and target_kind = 'reuniao')
--       or (action = 'configurar_lembrete_agenda' and target_kind = 'evento')
--       or (action = 'marcar_fonovisita_feita' and target_kind = 'pendencia_consolidacao')
--       or (action = 'atribuir_consolidacao' and target_kind = 'consolidacao')
--     );
-- commit;
-- ROLLBACK-END
