-- ============================================================================
-- PastorAI — Migration 20260708_164756_backfill_celula_membro_canonico
--
-- Achado C-02: convite Parte A (team.py), ativação Parte B (auth.py) e
-- link_cell (contacts.py) escreviam SÓ o espelho legado `pessoas.celula_id`,
-- nunca o vínculo canônico `celula_membro` (fonte de verdade — Q1, migration
-- 20260703_123803). Resultado: a visão do líder/discípulo (que lê
-- celula_membro) não mostrava pessoas vinculadas por esses 3 caminhos, mesmo
-- com pessoas.celula_id corretamente preenchido. O código dos 3 pontos de
-- escrita já foi corrigido nesta mesma PR (grava os dois a partir de agora);
-- esta migration só corrige o HISTÓRICO já divergente.
--
-- Puramente DML (backfill de dados) — não altera schema, RLS ou policies
-- (celula_membro já existe desde 20260703_123803, com sua própria RLS).
--
-- Idempotente (roda de novo sem duplicar nem reverter vínculos corretos):
--   1) desativa celula_membro ATIVO que diverge da célula atual do espelho
--      (pessoas.celula_id manda — caso de transferência via link_cell que
--      nunca desativou o vínculo canônico antigo, antes do fix desta PR);
--   2) reativa a linha certa se ela já existir mas estiver inativa (evita
--      duplicar — respeita o índice único parcial celula_membro_pessoa_ativa_uq);
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

-- 2) Reativa a linha que já existe pra (pessoa, célula atual) mas está inativa
--    (ex.: um retorno à mesma célula depois de uma transferência antiga).
update celula_membro cm
set ativo = true, updated_at = now()
from pessoas p
where cm.pessoa_id = p.id
  and cm.igreja_id = p.igreja_id
  and cm.celula_id = p.celula_id
  and cm.ativo = false
  and p.celula_id is not null;

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
