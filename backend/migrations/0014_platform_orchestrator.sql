-- ============================================================================
-- PastorAI 1.0 — Migration 0014: orquestrador padrão (modelo do master)
-- "O master define UM orquestrador padrão; cada igreja começa igual a todas e
-- pode ser ajustada depois." É o padrão TEMPLATE: esta tabela guarda o modelo
-- (1 linha), e ao APROVAR uma igreja o modelo é COPIADO para o AgentConfig dela
-- (por igreja). O runtime do agente NÃO muda — segue lendo o AgentConfig por
-- igreja (zero risco no motor de IA).
--
-- Plano de PLATAFORMA (sem igreja_id), igual a platform_admins: só o master
-- (service role, BYPASSRLS) lê/grava. RLS habilitada e sem policy + revoke.
-- Linha única (idempotente). Roda como service role.
-- ============================================================================

begin;

create table if not exists platform_orchestrator (
  id            uuid primary key default gen_random_uuid(),
  nome          text,
  tom           text,
  comportamento text not null default '',
  updated_at    timestamptz not null default now()
);

alter table platform_orchestrator enable row level security;

do $$ begin
  revoke all on table platform_orchestrator from authenticated;
exception when undefined_object then null; end $$;
do $$ begin
  revoke all on table platform_orchestrator from anon;
exception when undefined_object then null; end $$;

-- Seed do modelo padrão (1 linha só; idempotente).
insert into platform_orchestrator (nome, tom, comportamento)
select
  'Assistente da Igreja',
  'acolhedor e pastoral',
  'Você é o agente da igreja no WhatsApp. Acolha cada pessoa com cuidado pastoral, entenda a necessidade dela, e conduza com simplicidade e respeito. Registre decisões, visitas e dados usando as ferramentas disponíveis — nunca invente informações nem prometa o que não pode cumprir. Quando não souber, ofereça encaminhar para um líder humano.'
where not exists (select 1 from platform_orchestrator);

comment on table platform_orchestrator is
  'Modelo padrão do orquestrador (1 linha), definido pelo master. Copiado para o AgentConfig de cada igreja na aprovação (padrão template). Acesso só via service role (BYPASSRLS). Ver migration 0014.';

commit;
