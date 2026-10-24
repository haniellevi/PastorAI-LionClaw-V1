-- Registra sessões JWT próprias para permitir logout individual e revogação
-- imediata quando um membro perde acesso. Nunca armazena o JWT, apenas seu jti.
-- igreja_id é NULL somente para platform admins destacados de uma igreja.

create table public.auth_sessions (
    jti text primary key,
    igreja_id uuid null,
    app_user_id uuid not null references public.app_users(id) on delete cascade,
    issued_at timestamptz not null,
    expires_at timestamptz not null,
    revoked_at timestamptz null,
    constraint auth_sessions_tenant_user_fkey
        foreign key (igreja_id, app_user_id)
        references public.app_users(igreja_id, id) on delete cascade,
    constraint auth_sessions_expiry_after_issue_check check (expires_at > issued_at)
);

-- The composite FK intentionally skips its tenant-pair check when igreja_id is
-- NULL for a detached platform admin. The app_user_id FK above still anchors
-- that session to an existing user.

create index auth_sessions_user_expiry_idx
    on public.auth_sessions (igreja_id, app_user_id, expires_at);
create index auth_sessions_expiry_idx on public.auth_sessions (expires_at);

alter table public.auth_sessions enable row level security;
alter table public.auth_sessions force row level security;
revoke all on public.auth_sessions from public, anon, authenticated, service_role;
grant select on public.auth_sessions to authenticated;
grant update (revoked_at) on public.auth_sessions to authenticated;
grant select, insert, delete on public.auth_sessions to service_role;
grant update (revoked_at) on public.auth_sessions to service_role;

create policy auth_sessions_self_select on public.auth_sessions
    for select to authenticated
    using (
        igreja_id = public.current_igreja_id()
        and app_user_id = (
            select u.id from public.app_users u
            where u.igreja_id = public.current_igreja_id()
              and u.clerk_user_id = nullif(coalesce(
                  current_setting('request.jwt.claims', true)::jsonb ->> 'sub',
                  current_setting('request.jwt.claim.sub', true)
              ), '')
            limit 1
        )
    );

create policy auth_sessions_self_update on public.auth_sessions
    for update to authenticated
    using (
        igreja_id = public.current_igreja_id()
        and revoked_at is null
        and app_user_id = (
            select u.id from public.app_users u
            where u.igreja_id = public.current_igreja_id()
              and u.clerk_user_id = nullif(coalesce(
                  current_setting('request.jwt.claims', true)::jsonb ->> 'sub',
                  current_setting('request.jwt.claim.sub', true)
              ), '')
            limit 1
        )
    )
    with check (
        igreja_id = public.current_igreja_id()
        and revoked_at is not null
        and app_user_id = (
            select u.id from public.app_users u
            where u.igreja_id = public.current_igreja_id()
              and u.clerk_user_id = nullif(coalesce(
                  current_setting('request.jwt.claims', true)::jsonb ->> 'sub',
                  current_setting('request.jwt.claim.sub', true)
              ), '')
            limit 1
        )
    );

-- UPDATE also needs a SELECT policy for target rows. Admins can inspect only
-- session metadata inside their own church; bearer tokens are never stored.
create policy auth_sessions_admin_select on public.auth_sessions
    for select to authenticated
    using (
        igreja_id = public.current_igreja_id()
        and exists (
            select 1 from public.app_users actor
            join public.user_roles r
              on r.igreja_id = actor.igreja_id and r.user_id = actor.id
            where actor.igreja_id = public.current_igreja_id()
              and actor.clerk_user_id = nullif(coalesce(
                  current_setting('request.jwt.claims', true)::jsonb ->> 'sub',
                  current_setting('request.jwt.claim.sub', true)
              ), '')
              and r.papel = 'admin'
        )
    );

create policy auth_sessions_admin_revoke on public.auth_sessions
    for update to authenticated
    using (
        igreja_id = public.current_igreja_id()
        and revoked_at is null
        and exists (
            select 1 from public.app_users actor
            join public.user_roles r
              on r.igreja_id = actor.igreja_id and r.user_id = actor.id
            where actor.igreja_id = public.current_igreja_id()
              and actor.clerk_user_id = nullif(coalesce(
                  current_setting('request.jwt.claims', true)::jsonb ->> 'sub',
                  current_setting('request.jwt.claim.sub', true)
              ), '')
              and r.papel = 'admin'
        )
    )
    with check (
        igreja_id = public.current_igreja_id()
        and revoked_at is not null
    );

-- Rollback manual:
-- drop policy if exists auth_sessions_admin_revoke on public.auth_sessions;
-- drop policy if exists auth_sessions_admin_select on public.auth_sessions;
-- drop policy if exists auth_sessions_self_update on public.auth_sessions;
-- drop policy if exists auth_sessions_self_select on public.auth_sessions;
-- drop table if exists public.auth_sessions;
