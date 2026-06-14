-- ============================================================================
-- PastorAI 1.0 — Migration 0004: Triggers de state machine e automacoes
-- SPEC secao 2.3. Implementa a maturidade da pessoa como estado governado por
-- regras (F2) e as automacoes do pipeline G12.
-- ============================================================================

begin;

-- ----------------------------------------------------------------------------
-- trg_set_updated_at — mantem updated_at atualizado.
-- Aplicado a conversations (unica tabela com a coluna no schema atual).
-- ----------------------------------------------------------------------------
create or replace function fn_set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists trg_set_updated_at on conversations;
create trigger trg_set_updated_at
  before update on conversations
  for each row
  execute function fn_set_updated_at();

-- ----------------------------------------------------------------------------
-- trg_promote_pipeline — state machine F2/delta-013/031.
-- Avanca etapa/subetapa/tipo quando presencas_celula >= 3 OU aceitou_jesus.
-- Visitante -> membro (etapa ganhar/consolidar -> consolidar, subetapa em_consolidacao).
-- BEFORE para mutar a propria linha sem reentrancia.
-- ----------------------------------------------------------------------------
create or replace function fn_promote_pipeline()
returns trigger
language plpgsql
as $$
begin
  if (coalesce(new.presencas_celula, 0) >= 3 or coalesce(new.aceitou_jesus, false) = true) then
    -- promove visitante -> membro
    if new.tipo = 'visitante' then
      new.tipo := 'membro';
    end if;

    -- avanca etapa: quem estava em ganhar passa para consolidar
    if new.etapa is null or new.etapa = 'ganhar' then
      new.etapa := 'consolidar';
    end if;

    -- subetapa: sai de novo_contato/visitante para em_consolidacao
    if new.subetapa is null or new.subetapa in ('novo_contato', 'visitante') then
      new.subetapa := 'em_consolidacao';
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_promote_pipeline on pessoas;
create trigger trg_promote_pipeline
  before insert or update of presencas_celula, aceitou_jesus, tipo, etapa, subetapa on pessoas
  for each row
  execute function fn_promote_pipeline();

-- ----------------------------------------------------------------------------
-- trg_link_cell_promote — US-20.
-- Ao vincular contato a uma celula, marca acompanhamento = consolidado.
-- BEFORE UPDATE quando celula_id passa de NULL para um valor.
-- ----------------------------------------------------------------------------
create or replace function fn_link_cell_promote()
returns trigger
language plpgsql
as $$
begin
  if new.celula_id is not null and (old.celula_id is null or old.celula_id <> new.celula_id) then
    new.acompanhamento := 'consolidado';
    if new.subetapa is null or new.subetapa <> 'consolidado' then
      new.subetapa := 'consolidado';
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_link_cell_promote on pessoas;
create trigger trg_link_cell_promote
  before update of celula_id on pessoas
  for each row
  execute function fn_link_cell_promote();

-- ----------------------------------------------------------------------------
-- trg_report_received_clears_queue — US-26/RF-29.
-- Ao inserir report com status=recebido, resolve o work_queue_items tipo
-- relatorio da celula/semana. Como work_queue_items nao referencia celula
-- diretamente, o match e feito por igreja + tipo + contexto contendo o
-- celula_id (convencao: o contexto do item de relatorio inclui o celula_id).
-- ----------------------------------------------------------------------------
create or replace function fn_report_received_clears_queue()
returns trigger
language plpgsql
as $$
begin
  if new.status = 'recebido' then
    update work_queue_items
      set status = 'resolvido'
      where igreja_id = new.igreja_id
        and tipo = 'relatorio'
        and status <> 'resolvido'
        and (
          contexto ilike '%' || new.celula_id::text || '%'
          or contexto ilike '%' || new.semana || '%'
        );
  end if;
  return new;
end;
$$;

drop trigger if exists trg_report_received_clears_queue on reports;
create trigger trg_report_received_clears_queue
  after insert on reports
  for each row
  execute function fn_report_received_clears_queue();

-- ----------------------------------------------------------------------------
-- trg_decision_opens_consolidation — US-37/delta-041.
-- AFTER INSERT em decisions: cria consolidacao (etapa inicial) e, se
-- vinculo=visitante, cria work_queue_items tipo conectar_celula prazo +24h.
-- ----------------------------------------------------------------------------
create or replace function fn_decision_opens_consolidation()
returns trigger
language plpgsql
as $$
declare
  v_consolidacao_id uuid;
begin
  -- cria consolidacao individual vinculada a pessoa da decisao
  insert into consolidacoes (igreja_id, pessoa_id, tipo, responsavel_id, progresso, concluida, prazo_conexao)
  values (new.igreja_id, new.pessoa_id, 'individual', new.responsavel_id, 0, false, new.prazo_conexao)
  returning id into v_consolidacao_id;

  -- etapa inicial da trilha: aceitou_jesus
  insert into consolidacao_etapas (igreja_id, consolidacao_id, etapa, concluida)
  values (new.igreja_id, v_consolidacao_id, 'aceitou_jesus', true);

  -- fluxo B (visitante): pendencia de conectar a celula em 24h
  if new.vinculo = 'visitante' then
    insert into work_queue_items (igreja_id, tipo, titulo, contexto, pessoa_id, responsavel_id, status, prazo, prioridade)
    values (
      new.igreja_id,
      'conectar_celula',
      'Conectar nova decisao a uma celula',
      'Decisao ' || new.id::text || ' (visitante) — conectar em ate 24h',
      new.pessoa_id,
      new.responsavel_id,
      'aberto',
      now() + interval '24 hours',
      1
    );
  end if;

  return new;
end;
$$;

drop trigger if exists trg_decision_opens_consolidation on decisions;
create trigger trg_decision_opens_consolidation
  after insert on decisions
  for each row
  execute function fn_decision_opens_consolidation();

-- ----------------------------------------------------------------------------
-- trg_consent_on_inbound — US-31/RF-36.
-- AFTER INSERT em messages direcao=in: concede consentimento a pessoa da
-- conversa (a igreja nunca inicia comunicacao espontanea).
-- ----------------------------------------------------------------------------
create or replace function fn_consent_on_inbound()
returns trigger
language plpgsql
as $$
begin
  if new.direcao = 'in' then
    update pessoas p
      set consentimento = true
      from conversations c
      where c.id = new.conversation_id
        and p.id = c.pessoa_id
        and p.consentimento = false;
  end if;
  return new;
end;
$$;

drop trigger if exists trg_consent_on_inbound on messages;
create trigger trg_consent_on_inbound
  after insert on messages
  for each row
  execute function fn_consent_on_inbound();

-- ----------------------------------------------------------------------------
-- trg_subscription_autoupgrade — US-36/RF-42.
-- AFTER INSERT/UPDATE em pessoas: ao ultrapassar subscriptions.limite, promove
-- o plano e atualiza limite. Tambem reflete plano em igrejas.
-- ----------------------------------------------------------------------------
create or replace function fn_subscription_autoupgrade()
returns trigger
language plpgsql
as $$
declare
  v_total int;
  v_sub   subscriptions%rowtype;
  v_novo_plano  text;
  v_novo_limite int;
begin
  select * into v_sub from subscriptions where igreja_id = new.igreja_id;
  if not found then
    return new;
  end if;

  select count(*) into v_total from pessoas where igreja_id = new.igreja_id;

  -- atualiza contagem corrente de pessoas
  update subscriptions set pessoas = v_total where igreja_id = new.igreja_id;

  if v_sub.limite is not null and v_total > v_sub.limite then
    -- promove plano em escada
    if v_sub.plano = 'ate_100' then
      v_novo_plano := '101_200';
      v_novo_limite := 200;
    elsif v_sub.plano = '101_200' then
      v_novo_plano := 'acima_201';
      v_novo_limite := 999999;
    else
      v_novo_plano := v_sub.plano;
      v_novo_limite := v_sub.limite;
    end if;

    if v_novo_plano <> v_sub.plano then
      update subscriptions
        set plano = v_novo_plano,
            limite = v_novo_limite
        where igreja_id = new.igreja_id;
      update igrejas set plano = v_novo_plano where id = new.igreja_id;
    end if;
  end if;

  return new;
end;
$$;

drop trigger if exists trg_subscription_autoupgrade on pessoas;
create trigger trg_subscription_autoupgrade
  after insert or update on pessoas
  for each row
  execute function fn_subscription_autoupgrade();

commit;
