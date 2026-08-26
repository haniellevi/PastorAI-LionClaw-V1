-- ============================================================================
-- PastorAI: separa autoria pública do estado interno de respostas do agente.
--
-- ``message_autor`` permanece restrito a contato, ia e humano. O ledger usa
-- uma coluna textual com CHECK nomeado para permitir evolução controlada sem
-- transformar estados de transporte em autores expostos pela API.
-- ============================================================================

alter table public.messages
  add column if not exists agent_reply_state text;

do $migration$
begin
  if not exists (
    select 1
      from pg_constraint
     where conname = 'messages_agent_reply_state_check'
       and conrelid = 'public.messages'::regclass
  ) then
    alter table public.messages
      add constraint messages_agent_reply_state_check
      check (
        agent_reply_state is null
        or (
          direcao = 'out'
          and autor = 'ia'
          and agent_reply_state in (
            'ia_reservada',
            'ia_executando',
            'ia_pendente',
            'ia_em_transporte',
            'ia',
            'ia_ambigua',
            'ia_execucao_ambigua',
            'ia_falhou',
            'ia_suprimida',
            'ia_sem_resposta'
          )
        )
      ) not valid;
  end if;
end
$migration$;

alter table public.messages
  validate constraint messages_agent_reply_state_check;
