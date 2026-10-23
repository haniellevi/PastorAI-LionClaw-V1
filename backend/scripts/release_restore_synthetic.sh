#!/usr/bin/env bash
# Rehearse a public-schema dump and restore using synthetic rows only.
# Uses only a local Unix-socket Docker daemon; never reads a .env or DB URL.
set -Eeuo pipefail

pg_image=postgres:17-alpine
container_name="release-restore-synthetic-$$-${RANDOM}"
scratch_dir=$(mktemp -d)
dump_file="$scratch_dir/synthetic-public.dump"
docker_cli=""

cleanup() {
  if [[ -n "$docker_cli" ]]; then
    "$docker_cli" rm --force "$container_name" >/dev/null 2>&1 || true
  fi
  rm -rf -- "$scratch_dir"
}
trap cleanup EXIT INT TERM

docker_cli=$(type -P docker) || {
  echo "docker não disponível" >&2
  exit 2
}
if [[ -n "${DOCKER_HOST:-}" ]]; then
  echo "DOCKER_HOST explícito não permitido no ensaio local" >&2
  exit 2
fi
docker_context=$("$docker_cli" context show 2>/dev/null) || {
  echo "não foi possível identificar o contexto Docker" >&2
  exit 2
}
docker_endpoint=$("$docker_cli" context inspect \
  --format '{{.Endpoints.docker.Host}}' "$docker_context" 2>/dev/null) || {
  echo "não foi possível verificar o endpoint Docker" >&2
  exit 2
}
case "$docker_endpoint" in
  unix:///*) ;;
  *)
    echo "endpoint Docker não local; ensaio recusado" >&2
    exit 2
    ;;
esac
unset docker_context docker_endpoint
"$docker_cli" image inspect "$pg_image" >/dev/null 2>&1 || {
  echo "imagem PostgreSQL 17 ausente localmente: $pg_image" >&2
  exit 2
}

"$docker_cli" run --detach \
  --name "$container_name" \
  --network none \
  --tmpfs /var/lib/postgresql/data:rw,size=512m \
  --env POSTGRES_PASSWORD=synthetic-only \
  "$pg_image" >/dev/null

attempt=0
ready_checks=0
while (( ready_checks < 2 && attempt < 30 )); do
  if "$docker_cli" exec "$container_name" pg_isready -U postgres -d postgres >/dev/null 2>&1; then
    ready_checks=$((ready_checks + 1))
  else
    ready_checks=0
  fi
  attempt=$((attempt + 1))
  sleep 1
done
if (( ready_checks < 2 )); then
  echo "PostgreSQL sintético não ficou pronto" >&2
  exit 1
fi

"$docker_cli" exec --interactive "$container_name" \
  psql -X -v ON_ERROR_STOP=1 -U postgres -d postgres <<'SQL'
CREATE TABLE public.synthetic_private_records (
  id uuid PRIMARY KEY,
  igreja_id uuid NOT NULL,
  private_value text NOT NULL
);
INSERT INTO public.synthetic_private_records (id, igreja_id, private_value) VALUES
  ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'synthetic-a'),
  ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000001', 'synthetic-b');

CREATE TABLE public.synthetic_team_events (
  id uuid PRIMARY KEY,
  igreja_id uuid NOT NULL
);
INSERT INTO public.synthetic_team_events (id, igreja_id) VALUES
  ('30000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001');

CREATE DATABASE restore_verify;
SQL

"$docker_cli" exec "$container_name" \
  pg_dump --format=custom --no-owner --no-acl --schema=public \
    -U postgres -d postgres >"$dump_file"

"$docker_cli" exec "$container_name" \
  psql -X -v ON_ERROR_STOP=1 -U postgres -d restore_verify \
  -c 'DROP SCHEMA public CASCADE'

"$docker_cli" exec --interactive "$container_name" \
  pg_restore --exit-on-error --no-owner --no-acl \
    --username=postgres --dbname=restore_verify <"$dump_file"

counts=$("$docker_cli" exec "$container_name" \
  psql -X -qAt -v ON_ERROR_STOP=1 -U postgres -d restore_verify \
  -c "SELECT (SELECT count(*) FROM public.synthetic_private_records)::text || ':' || (SELECT count(*) FROM public.synthetic_team_events)::text")
if [[ "$counts" != "2:1" ]]; then
  echo "contagens da restauração sintética divergiram: $counts" >&2
  exit 1
fi

echo "RESTORE_SINTETICO=OK tabelas=2 contagens=2:1"
