-- V3: consolidação pelo WhatsApp usa somente S3 e notification_outbox.
-- A migration não ativa gates, não cria marcadores de ativação e não reprocessa
-- pendências históricas. A primeira ativação observada é registrada pelo worker.

begin;
set local lock_timeout = '2s';

-- S3 continua fechado por ação, alvo e recibo literal. Argumentos são validados
-- pelo catálogo/serviço; a migration não tenta duplicar o schema JSON do runtime.
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
      'atribuir_consolidacao'
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
    );

alter table public.agent_action_receipts
  drop constraint if exists agent_action_receipts_receipt_text_closed;
alter table public.agent_action_receipts
  add constraint agent_action_receipts_receipt_text_closed
    check (receipt_text in (
      'Registro confirmado.',
      'Relatório confirmado.',
      'Lembrete confirmado.',
      'Fonovisita confirmada.',
      'Consolidação atribuída.',
      'Lembretes de consolidação ativados.'
    ));

alter table public.whatsapp_reminder_preferences
  drop constraint if exists whatsapp_reminder_preferences_kind_closed;
alter table public.whatsapp_reminder_preferences
  add constraint whatsapp_reminder_preferences_kind_closed
    check (reminder_kind in ('agenda', 'cell_report', 'consolidation'));

-- As FKs compostas abaixo recusam referências de outro tenant. As PKs globais
-- legadas permanecem para os caminhos existentes que ainda endereçam somente id.
do $v3_tenant_keys$
begin
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.decisions'::regclass
      and conname = 'decisions_igreja_id_id_key' and contype = 'u'
  ) then
    alter table public.decisions
      add constraint decisions_igreja_id_id_key unique (igreja_id, id);
  end if;
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.consolidacoes'::regclass
      and conname = 'consolidacoes_igreja_id_id_key' and contype = 'u'
  ) then
    alter table public.consolidacoes
      add constraint consolidacoes_igreja_id_id_key unique (igreja_id, id);
  end if;
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.work_queue_items'::regclass
      and conname = 'work_queue_items_igreja_id_id_key' and contype = 'u'
  ) then
    alter table public.work_queue_items
      add constraint work_queue_items_igreja_id_id_key unique (igreja_id, id);
  end if;
end
$v3_tenant_keys$;

alter table public.consolidacoes
  add column if not exists origin_decision_id uuid,
  add column if not exists assignment_revision bigint not null default 0;
alter table public.work_queue_items
  add column if not exists consolidacao_id uuid;
alter table public.notification_outbox
  add column if not exists consolidacao_id uuid,
  add column if not exists work_queue_item_id uuid;

do $v3_constraints$
begin
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.consolidacoes'::regclass
      and conname = 'consolidacoes_assignment_revision_nonnegative' and contype = 'c'
  ) then
    alter table public.consolidacoes
      add constraint consolidacoes_assignment_revision_nonnegative
        check (assignment_revision >= 0);
  end if;
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.consolidacoes'::regclass
      and conname = 'consolidacoes_tenant_origin_decision_fkey' and contype = 'f'
  ) then
    alter table public.consolidacoes
      add constraint consolidacoes_tenant_origin_decision_fkey
        foreign key (igreja_id, origin_decision_id)
        references public.decisions (igreja_id, id)
        on delete set null (origin_decision_id);
  end if;
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.work_queue_items'::regclass
      and conname = 'work_queue_items_tenant_consolidacao_fkey' and contype = 'f'
  ) then
    alter table public.work_queue_items
      add constraint work_queue_items_tenant_consolidacao_fkey
        foreign key (igreja_id, consolidacao_id)
        references public.consolidacoes (igreja_id, id)
        on delete cascade;
  end if;
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.notification_outbox'::regclass
      and conname = 'notification_outbox_tenant_consolidacao_fkey' and contype = 'f'
  ) then
    alter table public.notification_outbox
      add constraint notification_outbox_tenant_consolidacao_fkey
        foreign key (igreja_id, consolidacao_id)
        references public.consolidacoes (igreja_id, id)
        on delete set null (consolidacao_id);
  end if;
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.notification_outbox'::regclass
      and conname = 'notification_outbox_tenant_work_queue_item_fkey' and contype = 'f'
  ) then
    alter table public.notification_outbox
      add constraint notification_outbox_tenant_work_queue_item_fkey
        foreign key (igreja_id, work_queue_item_id)
        references public.work_queue_items (igreja_id, id)
        on delete set null (work_queue_item_id);
  end if;
end
$v3_constraints$;

create unique index if not exists consolidacoes_origin_decision_once_idx
  on public.consolidacoes (igreja_id, origin_decision_id)
  where origin_decision_id is not null;
create unique index if not exists work_queue_items_fonovisita_consolidacao_once_idx
  on public.work_queue_items (igreja_id, consolidacao_id)
  where tipo = 'fonovisita' and consolidacao_id is not null;
create index if not exists work_queue_items_consolidacao_idx
  on public.work_queue_items (igreja_id, consolidacao_id);
create index if not exists notification_outbox_consolidacao_idx
  on public.notification_outbox (igreja_id, consolidacao_id);
create index if not exists notification_outbox_work_queue_item_idx
  on public.notification_outbox (igreja_id, work_queue_item_id);

-- A referência viva é nullable após remoção de sua origem. A identidade opaca,
-- o estado terminal e a reserva diária permanecem intactos para não reabrir envio.
alter table public.notification_outbox
  drop constraint if exists notification_outbox_purpose_closed,
  drop constraint if exists notification_outbox_reference_shape_chk,
  drop constraint if exists notification_outbox_origin_kind_closed,
  drop constraint if exists notification_outbox_live_origin_identity_chk;
alter table public.notification_outbox
  add constraint notification_outbox_purpose_closed
    check (purpose in (
      'agenda_reminder',
      'agenda_evt7',
      'cell_report_reminder',
      'consolidation_connection_open',
      'consolidation_connection_deadline',
      'consolidation_fonovisita'
    )),
  add constraint notification_outbox_reference_shape_chk
    check (
      (purpose = 'agenda_reminder' and origin_kind = 'event'
        and reuniao_id is null and agenda_alert_recipient_id is null
        and consolidacao_id is null and work_queue_item_id is null)
      or (purpose = 'agenda_evt7' and origin_kind = 'event'
        and reuniao_id is null and agenda_subscription_id is null
        and consolidacao_id is null and work_queue_item_id is null)
      or (purpose = 'cell_report_reminder' and origin_kind = 'meeting'
        and event_id is null and agenda_subscription_id is null
        and agenda_alert_recipient_id is null
        and consolidacao_id is null and work_queue_item_id is null)
      or (purpose in ('consolidation_connection_open', 'consolidation_connection_deadline')
        and origin_kind = 'consolidacao'
        and event_id is null and reuniao_id is null
        and agenda_alert_recipient_id is null and agenda_subscription_id is null
        and work_queue_item_id is null)
      or (purpose = 'consolidation_fonovisita'
        and consolidacao_id is null
        and origin_kind = 'work_queue'
        and event_id is null and reuniao_id is null
        and agenda_alert_recipient_id is null and agenda_subscription_id is null)
    ),
  add constraint notification_outbox_origin_kind_closed
    check (origin_kind in ('event', 'meeting', 'consolidacao', 'work_queue')),
  add constraint notification_outbox_live_origin_identity_chk
    check (
      (event_id is null or (origin_kind = 'event' and origin_id = event_id))
      and (reuniao_id is null or (origin_kind = 'meeting' and origin_id = reuniao_id))
      and (
        consolidacao_id is null
        or (origin_kind = 'consolidacao' and origin_id = consolidacao_id)
      )
      and (work_queue_item_id is null
        or (origin_kind = 'work_queue' and origin_id = work_queue_item_id))
    );

-- A revisão só avança quando a responsabilidade muda. O serviço trava a
-- consolidação e as tarefas ligadas antes de atualizar, e compara esta revisão
-- contra os argumentos S3 para rejeitar proposta desatualizada ou ABA.
create or replace function public.fn_consolidacoes_assignment_revision()
returns trigger
language plpgsql
as $$
begin
  if new.responsavel_id is distinct from old.responsavel_id then
    new.assignment_revision := old.assignment_revision + 1;
  elsif new.assignment_revision is distinct from old.assignment_revision then
    raise exception 'assignment_revision é gerenciada pelo servidor'
      using errcode = '22023';
  end if;
  return new;
end;
$$;

drop trigger if exists trg_consolidacoes_assignment_revision on public.consolidacoes;
create trigger trg_consolidacoes_assignment_revision
  before update on public.consolidacoes
  for each row execute function public.fn_consolidacoes_assignment_revision();

-- Toda nova consolidação recebe uma única pendência canônica de fonovisita. O
-- índice parcial permanece válido inclusive após baixa, portanto nunca há replay.
create or replace function public.fn_consolidacao_creates_fonovisita()
returns trigger
language plpgsql
as $$
begin
  insert into public.work_queue_items (
    igreja_id,
    consolidacao_id,
    tipo,
    titulo,
    contexto,
    pessoa_id,
    responsavel_id,
    status,
    prazo,
    prioridade
  ) values (
    new.igreja_id,
    new.id,
    'fonovisita',
    'Fonovisita de consolidação pendente',
    null,
    new.pessoa_id,
    new.responsavel_id,
    'aberto',
    null,
    1
  )
  on conflict (igreja_id, consolidacao_id)
    where tipo = 'fonovisita' and consolidacao_id is not null do nothing;
  return new;
end;
$$;

drop trigger if exists trg_consolidacao_creates_fonovisita on public.consolidacoes;
create trigger trg_consolidacao_creates_fonovisita
  after insert on public.consolidacoes
  for each row execute function public.fn_consolidacao_creates_fonovisita();

-- Preserva o gatilho canônico de decisão e apenas acrescenta as referências V3.
-- A consolidação inserida dispara a fonovisita acima na mesma transação.
create or replace function public.fn_decision_opens_consolidation()
returns trigger
language plpgsql
as $$
declare
  v_consolidacao_id uuid;
begin
  insert into public.consolidacoes (
    igreja_id,
    pessoa_id,
    origin_decision_id,
    tipo,
    responsavel_id,
    progresso,
    concluida,
    prazo_conexao
  ) values (
    new.igreja_id,
    new.pessoa_id,
    new.id,
    'individual',
    new.responsavel_id,
    0,
    false,
    new.prazo_conexao
  )
  returning id into v_consolidacao_id;

  insert into public.consolidacao_etapas (
    igreja_id,
    consolidacao_id,
    etapa,
    concluida
  ) values (
    new.igreja_id,
    v_consolidacao_id,
    'aceitou_jesus',
    true
  );

  if new.vinculo = 'visitante' then
    insert into public.work_queue_items (
      igreja_id,
      consolidacao_id,
      tipo,
      titulo,
      contexto,
      pessoa_id,
      responsavel_id,
      status,
      prazo,
      prioridade
    ) values (
      new.igreja_id,
      v_consolidacao_id,
      'conectar_celula',
      'Conectar nova decisão a uma célula',
      'Decisão ' || new.id::text || ' (visitante), conectar em até 24h',
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

-- A ativação é tenant-only e permanece vazia até o worker observar todos os
-- gates abertos. Fechamento/reabertura são transições do serviço sob lock;
-- nenhum humano pode criar, consultar ou mudar este marcador diretamente.
create table if not exists public.consolidation_whatsapp_activation (
  igreja_id uuid primary key,
  activated_at timestamptz,
  gate_open boolean not null default false,
  constraint consolidation_whatsapp_activation_igreja_fkey
    foreign key (igreja_id) references public.igrejas (id) on delete cascade,
  constraint consolidation_whatsapp_activation_gate_open_chk
    check (not gate_open or activated_at is not null)
);

alter table public.consolidation_whatsapp_activation
  add column if not exists activated_at timestamptz,
  add column if not exists gate_open boolean not null default false;

do $v3_activation_constraints$
begin
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.consolidation_whatsapp_activation'::regclass
      and conname = 'consolidation_whatsapp_activation_igreja_fkey' and contype = 'f'
  ) then
    alter table public.consolidation_whatsapp_activation
      add constraint consolidation_whatsapp_activation_igreja_fkey
        foreign key (igreja_id) references public.igrejas (id) on delete cascade;
  end if;
  if not exists (
    select 1 from pg_catalog.pg_constraint
    where conrelid = 'public.consolidation_whatsapp_activation'::regclass
      and conname = 'consolidation_whatsapp_activation_gate_open_chk' and contype = 'c'
  ) then
    alter table public.consolidation_whatsapp_activation
      add constraint consolidation_whatsapp_activation_gate_open_chk
        check (not gate_open or activated_at is not null);
  end if;
end
$v3_activation_constraints$;

-- O corte só pode avançar ao abrir uma nova época observada pelo worker.
-- Fechar o gate preserva a evidência anterior; atualizar uma época aberta
-- ou retroceder a reabertura permitiria replay de alertas históricos.
create or replace function public.fn_consolidation_whatsapp_activation_epoch()
returns trigger
language plpgsql
as $$
begin
  if not old.gate_open and new.gate_open then
    if new.activated_at is null
       or (old.activated_at is not null and new.activated_at <= old.activated_at) then
      raise exception 'Nova época exige corte posterior ao anterior'
        using errcode = '23514';
    end if;
  elsif new.activated_at is distinct from old.activated_at then
    raise exception 'Corte de ativação só muda na reabertura do gate'
      using errcode = '23514';
  end if;
  return new;
end;
$$;

drop trigger if exists trg_consolidation_whatsapp_activation_epoch
  on public.consolidation_whatsapp_activation;
create trigger trg_consolidation_whatsapp_activation_epoch
  before update on public.consolidation_whatsapp_activation
  for each row execute function public.fn_consolidation_whatsapp_activation_epoch();

alter table public.consolidation_whatsapp_activation enable row level security;
alter table public.consolidation_whatsapp_activation force row level security;

drop policy if exists consolidation_whatsapp_activation_worker_select
  on public.consolidation_whatsapp_activation;
create policy consolidation_whatsapp_activation_worker_select
  on public.consolidation_whatsapp_activation for select to authenticated
  using (
    igreja_id = public.current_igreja_id()
    and nullif(coalesce(
      nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)
    ), '') is null
  );

drop policy if exists consolidation_whatsapp_activation_worker_insert
  on public.consolidation_whatsapp_activation;
create policy consolidation_whatsapp_activation_worker_insert
  on public.consolidation_whatsapp_activation for insert to authenticated
  with check (
    igreja_id = public.current_igreja_id()
    and nullif(coalesce(
      nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)
    ), '') is null
  );

drop policy if exists consolidation_whatsapp_activation_worker_update
  on public.consolidation_whatsapp_activation;
create policy consolidation_whatsapp_activation_worker_update
  on public.consolidation_whatsapp_activation for update to authenticated
  using (
    igreja_id = public.current_igreja_id()
    and nullif(coalesce(
      nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)
    ), '') is null
  )
  with check (
    igreja_id = public.current_igreja_id()
    and nullif(coalesce(
      nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub',
      pg_catalog.current_setting('request.jwt.claim.sub', true)
    ), '') is null
  );

revoke all privileges on table public.consolidation_whatsapp_activation from public;

do $v3_activation_acl$
declare
  target_role text;
begin
  foreach target_role in array array['anon', 'service_role', 'agent_runtime'] loop
    if pg_catalog.to_regrole(target_role) is not null then
      execute format(
        'revoke all privileges on table public.consolidation_whatsapp_activation from %I',
        target_role
      );
    end if;
  end loop;
  if pg_catalog.to_regrole('authenticated') is not null then
    execute 'revoke all privileges on table public.consolidation_whatsapp_activation from authenticated';
    execute 'grant select, insert, update on table public.consolidation_whatsapp_activation to authenticated';
    if pg_catalog.has_table_privilege(
      'authenticated', 'public.consolidation_whatsapp_activation', 'delete'
    ) then
      raise exception 'DELETE permanece concedido em consolidation_whatsapp_activation';
    end if;
  end if;
end
$v3_activation_acl$;

commit;

-- Rollback manual: fechar os gates V3, cancelar elegibilidades pendentes e
-- preservar recibos, estados terminais e reservas. Só então revisar a remoção
-- coordenada das relações, índices, triggers, colunas e constraints V3.
