-- ============================================================================
-- PastorAI — Migration 20260711_152127 — Missão M7B-W1.2 (regra 6)
-- Reclassifica a Pessoa que representa o NÚMERO CONECTADO ao WhatsApp/Evolution
-- da igreja: o backfill legado a deixou como tipo 'membro', mas o número oficial
-- de atendimento não participa da jornada (não é membro/discípulo). A limpeza de
-- vínculos ativos (pastor, líder e este número) já foi feita à mão em PROD; falta
-- só corrigir o TIPO deste registro, que ficou 'membro' sem vínculo.
--
-- Alvo (todas as condições, por construção idempotente e preciso):
--   * p.tipo = 'membro';
--   * SEM vínculo ATIVO em celula_membro (o registro do número já está solto —
--     um membro real de célula tem vínculo ativo e NÃO é tocado por isto);
--   * o telefone da pessoa == o número conectado em whatsapp_connections DA MESMA
--     igreja, comparado pela chave CANÔNICA COMPLETA (função temporária abaixo,
--     réplica fiel de app/domain/phone.py::normalize_phone: descarta o +55 e
--     reinsere o 9º dígito). NÃO comparamos só os 8 últimos dígitos: um sufixo
--     colidente entre DDDs diferentes reclassificaria a pessoa errada.
-- Novo tipo: 'contato' — o tipo de ENTRADA, neutro, já suportado pelo enum
-- pessoa_tipo (nenhum enum novo é inventado). É o menos comprometido: não é
-- discípulo, não é membro, não lidera, não é pastor.
--
-- Tenant-safe: o EXISTS de whatsapp_connections casa pela MESMA igreja_id, e o
-- NOT EXISTS de celula_membro também — nunca reclassifica por causa de outra
-- igreja. (No SQL editor a conexão é `postgres`/BYPASSRLS e enxerga todos os
-- tenants; por isso o join por igreja_id é obrigatório aqui.)
--
-- Somente DML + 1 função TEMPORÁRIA (pg_temp, some ao fim da sessão): não altera
-- schema persistente, enum, índice, RLS nem policy. Idempotente — reexecutar não
-- toca em nada (o registro já virou 'contato', que não casa tipo = 'membro'; a
-- função é create-or-replace). Roda em transação (sem ALTER TYPE).
--
-- ⚠️ Aplicar manualmente no Supabase, em ordem de nome de arquivo. Aplicar
--    PRIMEIRO em DEV, rodar as queries de verificação (abaixo) e só então em
--    PROD. NÃO aplicada em nenhum ambiente por esta missão.
-- ============================================================================

begin;

-- Chave canônica de telefone — réplica EXATA de normalize_phone (Python):
-- só-dígitos; se >11 díg. e começa com 55, descarta o 55; se ficar com 10 díg.,
-- reinsere o 9º dígito após o DDD. Temporária (pg_temp): não persiste no schema.
create or replace function pg_temp.pastorai_canon_phone(raw text)
returns text language sql immutable as $fn$
  with d1 as (
    select case
      when length(v) > 11 and left(v, 2) = '55' then substr(v, 3)
      else v
    end as v
    from (select regexp_replace(coalesce(raw, ''), '\D', '', 'g') as v) d0
  )
  select case
    when v = '' then ''
    when length(v) = 10 then substr(v, 1, 2) || '9' || substr(v, 3)
    else v
  end
  from d1;
$fn$;

update pessoas p
set tipo = 'contato'
where p.tipo = 'membro'
  and not exists (
    select 1
    from celula_membro cm
    where cm.pessoa_id = p.id
      and cm.igreja_id = p.igreja_id
      and cm.ativo = true
  )
  and exists (
    select 1
    from whatsapp_connections wc
    where wc.igreja_id = p.igreja_id
      and wc.numero is not null
      and pg_temp.pastorai_canon_phone(p.telefone) <> ''
      and pg_temp.pastorai_canon_phone(wc.numero)
        = pg_temp.pastorai_canon_phone(p.telefone)
  );

commit;

-- ============================================================================
-- VERIFICAÇÃO (rodar manualmente; não faz parte da transação acima)
-- ============================================================================
--
-- 1) Pré-checagem (ANTES do backfill) — quem CANDIDATA (filtro amplo pelos 8
--    dígitos, para eyeball). Confira nome/telefone; esperado: só o(s) registro(s)
--    do número oficial (ex.: "Whatsapp Filadelfia Corrente"). Se aparecer um
--    membro legítimo, PARE e investigue antes de rodar. (O UPDATE real é mais
--    ESTRITO: casa a chave canônica completa, então pode tocar MENOS que isto.)
--
--    select p.id, p.igreja_id, p.nome, p.telefone, p.tipo
--    from pessoas p
--    where p.tipo = 'membro'
--      and not exists (
--        select 1 from celula_membro cm
--        where cm.pessoa_id = p.id and cm.igreja_id = p.igreja_id and cm.ativo = true)
--      and exists (
--        select 1 from whatsapp_connections wc
--        where wc.igreja_id = p.igreja_id and wc.numero is not null
--          and right(regexp_replace(wc.numero, '\D', '', 'g'), 8)
--            = right(regexp_replace(p.telefone, '\D', '', 'g'), 8));
--
-- 2) Pós-checagem — DEPOIS do backfill o mesmo predicado deve retornar 0 linhas
--    (o registro deixou de ser 'membro'). Reexecutar a migration não muda nada.
--
-- 3) Prova de não-dano: a contagem de pessoas 'membro' COM vínculo ativo de
--    célula é IDÊNTICA antes e depois (o NOT EXISTS as protege por construção).
--
--    select count(*) as membros_com_vinculo_ativo
--    from pessoas p
--    where p.tipo = 'membro'
--      and exists (select 1 from celula_membro cm
--        where cm.pessoa_id = p.id and cm.igreja_id = p.igreja_id and cm.ativo = true);
-- ============================================================================
