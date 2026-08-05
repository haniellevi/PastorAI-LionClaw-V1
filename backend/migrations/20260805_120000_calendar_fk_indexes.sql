-- PastorAI — índices das FKs do OAuth Calendar
--
-- Migration aditiva/idempotente. Fecha os avisos do advisor sem alterar dados,
-- policies, grants ou a semântica do fluxo OAuth já aplicado em produção.

begin;

create index if not exists idx_calendar_oauth_flows_igreja
  on calendar_oauth_flows (igreja_id);

create index if not exists idx_calendar_oauth_flows_app_user
  on calendar_oauth_flows (app_user_id);

create index if not exists idx_calendar_sync_connected_by_app_user
  on calendar_sync (connected_by_app_user_id)
  where connected_by_app_user_id is not null;

commit;
