-- RF-26 / US-23: regras de alerta ao líder de célula, configuráveis por igreja.
-- O admin liga, desliga e edita parâmetros; o cron avalia o estado do banco e
-- grava em cell_alerts um alerta por fato (idempotente). Nenhum envio externo.
set lock_timeout='2s';

create table public.celula_alerta_regras (
 id uuid primary key default gen_random_uuid(),
 igreja_id uuid not null references public.igrejas(id) on delete cascade,
 tipo text not null check(tipo in ('visitante_novo','liderado_em_consolidacao','relatorio_pendente','prazo_vencendo','meta_atingida')),
 ativo boolean not null default false,
 parametros jsonb not null default '{}'::jsonb check(jsonb_typeof(parametros)='object'),
 atualizado_por uuid,
 atualizado_em timestamptz not null default clock_timestamp(),
 -- atualizado_por é só auditoria (app_user); sem FK para não travar reset/exclusão de conta.
 unique(igreja_id,tipo)
);
alter table public.celula_alerta_regras enable row level security;
alter table public.celula_alerta_regras force row level security;
create policy tenant_isolation on public.celula_alerta_regras for all to authenticated
 using(igreja_id=public.current_igreja_id() and igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid and session_user not in ('authenticator','authenticated','anon'))
 with check(igreja_id=public.current_igreja_id() and igreja_id=nullif(current_setting('app.tenant_igreja_id',true),'')::uuid and session_user not in ('authenticator','authenticated','anon'));
revoke all on public.celula_alerta_regras from public,anon,authenticated,service_role;
grant select on public.celula_alerta_regras to authenticated;
grant insert(igreja_id,tipo,ativo,parametros,atualizado_por,atualizado_em) on public.celula_alerta_regras to authenticated;
grant update(ativo,parametros,atualizado_por,atualizado_em) on public.celula_alerta_regras to authenticated;

-- Alertas gerados: regra de origem + chave do fato (opaca, sem PII) tornam a
-- avaliação idempotente. Alertas de célula (relatório, meta, visitante sem
-- cadastro) não têm Pessoa; os manuais/legados continuam com regra_tipo nulo.
alter table public.cell_alerts alter column pessoa_id drop not null;
alter table public.cell_alerts add column regra_tipo text;
alter table public.cell_alerts add column fato_chave text;
alter table public.cell_alerts add constraint cell_alerts_regra_fato_check
 check((regra_tipo is null and fato_chave is null) or (regra_tipo is not null and fato_chave is not null and length(fato_chave) <= 200));
create unique index cell_alerts_regra_fato_uniq on public.cell_alerts(igreja_id,regra_tipo,fato_chave);

-- Rollback (somente depois de remover o código que grava regra_tipo/fato_chave;
-- alertas sem Pessoa precisam ser tratados ou removidos sob procedimento próprio
-- antes de restaurar o NOT NULL):
-- drop index public.cell_alerts_regra_fato_uniq;
-- alter table public.cell_alerts drop constraint cell_alerts_regra_fato_check;
-- alter table public.cell_alerts drop column fato_chave;
-- alter table public.cell_alerts drop column regra_tipo;
-- alter table public.cell_alerts alter column pessoa_id set not null;
-- drop table public.celula_alerta_regras;
