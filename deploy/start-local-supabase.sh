#!/usr/bin/env bash

set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
network_name="pastorai-supabase-local"
supabase_cli="$repo_root/node_modules/.bin/supabase"

cd "$repo_root"

if [[ ! -x "$supabase_cli" ]]; then
  printf 'Supabase CLI ausente em node_modules. Execute npm ci com Node 24.19.0.\n' >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  printf 'Docker daemon inacessível. Reabra a sessão após entrar no grupo docker.\n' >&2
  exit 1
fi

if ! docker network inspect "$network_name" >/dev/null 2>&1; then
  docker network create \
    -o com.docker.network.bridge.host_binding_ipv4=127.0.0.1 \
    "$network_name" >/dev/null
fi

export DO_NOT_TRACK=1
export SUPABASE_TELEMETRY_DISABLED=1

exec "$supabase_cli" start --network-id "$network_name" --yes
