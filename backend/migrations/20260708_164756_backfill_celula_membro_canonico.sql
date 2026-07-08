-- ============================================================================
-- PastorAI — Migration 20260708_164756_backfill_celula_membro_canonico
--
-- Achado C-02: convite Parte A (team.py), ativação Parte B (auth.py),
-- link_cell (contacts.py) e a tool do agente vincular_celula (agent/tools.py)
-- escreviam SÓ o espelho legado `pessoas.celula_id`, nunca o vínculo canônico
-- `celula_membro` (fonte de verdade — Q1, migration 20260703_123803).
-- Resultado: a visão do líder/discípulo (que lê celula_membro) não mostrava
-- pessoas vinculadas por esses 4 caminhos, mesmo com pessoas.celula_id
-- corretamente preenchido. O código dos 4 pontos de escrita já foi corrigido
-- nesta mesma PR (grava os dois a partir de agora); esta migration só corrige
-- o HISTÓRICO já divergente.
--
-- Puramente DML (backfill de dados) — não altera schema, RLS ou policies
-- (celula_membro já existe desde 20260703_123803, com sua própria RLS).
--
-- Idempotente (roda de novo sem duplicar nem reverter vínculos corretos):
--   1) desativa celula_membro ATIVO que diverge da célula atual do espelho
--      (pessoas.celula_id manda — caso de transferência via link_cell que
--      nunca desativou o vínculo canônico antigo, antes do fix desta PR);
--   2) reativa, no máximo, UMA linha (a mais recente) se já existir mas
--      estiver inativa, e só quando a pessoa não tiver nenhuma linha ativa
--      ainda — nunca duplica ativo, mesmo com duplicatas históricas (respeita
--      o índice único parcial celula_membro_pessoa_ativa_uq);
--   3) insere a linha canônica só para quem tem celula_id no espelho e ainda
--      não tem NENHUMA linha (ativa ou inativa) casando com a célula atual.
--
-- Aplicar manualmente no Supabase (DEV primeiro), em ordem de nome de arquivo.
-- ============================================================================

begin;

-- 1) Desfaz o caso "célula mudou mas o vínculo canônico antigo ficou ativo".
update celula_membro cm
set ativo = false, updated_at = now()
from pessoas p
where cm.pessoa_id = p.id
  and cm.igreja_id = p.igreja_id
  and cm.ativo = true
  and p.celula_id is not null
  and cm.celula_id <> p.celula_id;

-- 2) Reativa, no máximo, UMA linha (a mais recente) que já existe pra (pessoa,
--    célula atual) mas está inativa — ex.: um retorno à mesma célula depois de
--    uma transferência antiga. Nunca reativa se já existir alguma linha ativa
--    para a pessoa (evita violar o índice único parcial mesmo diante de
--    duplicatas históricas — `add_cell_member`, anterior a este PR, insere
--    linha nova sem reusar uma inativa existente para o mesmo par).
update celula_membro cm
set ativo = true, updated_at = now()
from pessoas p
where p.celula_id is not null
  and not exists (
    select 1 from celula_membro cm_active
    where cm_active.pessoa_id = p.id
      and cm_active.igreja_id = p.igreja_id
      and cm_active.ativo = true
  )
  and cm.id = (
    select cm2.id
    from celula_membro cm2
    where cm2.pessoa_id = p.id
      and cm2.igreja_id = p.igreja_id
      and cm2.celula_id = p.celula_id
      and cm2.ativo = false
    order by cm2.updated_at desc nulls last, cm2.created_at desc
    limit 1
  );

-- 3) Insere a linha canônica pra quem tem celula_id no espelho mas nenhuma
--    linha (ativa ou inativa) casando com a célula atual — o caso principal
--    do achado C-02 (convite/ativação/link_cell nunca escreviam aqui).
insert into celula_membro (id, igreja_id, celula_id, pessoa_id, papel, ativo, created_at)
select gen_random_uuid(), p.igreja_id, p.celula_id, p.id, 'membro', true, now()
from pessoas p
where p.celula_id is not null
  and not exists (
    select 1 from celula_membro cm
    where cm.pessoa_id = p.id
      and cm.celula_id = p.celula_id
      and cm.igreja_id = p.igreja_id
  );

commit;
