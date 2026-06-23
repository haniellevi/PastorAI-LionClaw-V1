-- ============================================================================
-- PastorAI — Migration 20260623_170000_igreja_dono_assinatura
-- #4: "admin principal" (dono) da igreja para o gating da Assinatura. Adiciona
-- igrejas.dono_id (FK -> app_users, SET NULL no delete) e faz backfill com o
-- admin MAIS ANTIGO de cada igreja (o primeiro admin = dono natural).
-- Só o dono enxerga/gerencia a Assinatura; o master reatribui pelo console.
--
-- ADD COLUMN é transacional: begin/commit. Aplicar manualmente no Supabase,
-- em ordem de nome de arquivo.
-- ============================================================================

begin;

alter table igrejas
  add column if not exists dono_id uuid references app_users(id) on delete set null;

comment on column igrejas.dono_id is
  '#4: dono (admin principal) da igreja — único admin que enxerga/gerencia a Assinatura. NULL = sem dono (o master precisa reatribuir).';

-- Backfill: dono = admin MAIS ANTIGO (primeiro admin) de cada igreja.
update igrejas ig
set dono_id = sub.user_id
from (
  select distinct on (ur.igreja_id) ur.igreja_id, ur.user_id
  from user_roles ur
  join app_users au on au.id = ur.user_id
  where ur.papel = 'admin'
  order by ur.igreja_id, au.created_at asc, au.id asc
) sub
where ig.id = sub.igreja_id and ig.dono_id is null;

commit;
