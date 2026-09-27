#!/usr/bin/env bash
# Ambiente LOCAL do PastorAI: Supabase local, backend, workers e frontend.
#
#   ./dev.sh up             sobe tudo; na primeira vez cria o banco e os dados de teste
#   ./dev.sh reset          apaga o banco local e recria (migrations + dados de teste)
#   ./dev.sh seed           recria os dados que faltarem e religa as contas do Clerk dev
#   ./dev.sh migrate        aplica só as migrations pendentes no banco local
#   ./dev.sh down [--tudo]  para backend, workers e frontend (--tudo: e o Supabase local)
#   ./dev.sh status         mostra o que está rodando e os endereços
#   ./dev.sh logs [serviço] acompanha os logs (backend, queue-worker, cron-worker,
#                           broadcast-worker, redis ou frontend)
#   ./dev.sh psql           abre o psql no banco local
#
# Nada aqui toca DEV ou PROD. Guia: docs/ops/AMBIENTE-LOCAL.md
set -euo pipefail
umask 022

root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
main_root=$(cd "$(git -C "$root" rev-parse --path-format=absolute --git-common-dir)/.." && pwd)
env_file="${PASTORAI_DEV_ENV:-$main_root/.env.dev}"
compose_file="$root/deploy/docker-compose.dev.yml"
state_dir="$root/.dev"
network="pastorai-supabase-local"
db_container="supabase_db_pastorai-local"
node_bin="${PASTORAI_NODE_BIN:-$HOME/.nvm/versions/node/v$(cat "$root/.nvmrc")/bin}"

info() { printf '\033[1;34m▸\033[0m %s\n' "$*"; }
aviso() { printf '\033[1;33m!\033[0m %s\n' "$*"; }
erro() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; exit 1; }

env_valor() { sed -n "s/^$1=//p" "$env_file" | tail -1; }
porta_front() { local p; p=$(env_valor DEV_FRONTEND_PORT); echo "${p:-3012}"; }
porta_api() { local p; p=$(env_valor DEV_BACKEND_PORT); echo "${p:-8000}"; }

# --- .env.dev ----------------------------------------------------------------

garantir_env() {
  # O .env.dev mora no checkout principal: o exclude local do Git o protege em
  # qualquer branch, mesmo antes de o .gitignore novo chegar lá.
  local exclude
  exclude="$(git -C "$root" rev-parse --path-format=absolute --git-common-dir)/info/exclude"
  mkdir -p "$(dirname "$exclude")"
  grep -qxF '/.env.dev' "$exclude" 2>/dev/null || printf '/.env.dev\n/.dev/\n' >>"$exclude"
  if [[ ! -f "$env_file" ]]; then
    cp "$root/deploy/.env.dev.example" "$env_file"
    chmod 600 "$env_file"
    info "criei $env_file a partir de deploy/.env.dev.example"
  fi
  local chave valor
  for chave in SECRETS_ENCRYPTION_KEY SESSION_JWT_SECRET EVOLUTION_API_KEY EVOLUTION_WEBHOOK_SECRET; do
    grep -qE "^${chave}=" "$env_file" || printf '%s=\n' "$chave" >>"$env_file"
    if grep -qE "^${chave}=$" "$env_file"; then
      valor=$(python3 -c 'import base64,os,secrets,sys; print(base64.urlsafe_b64encode(os.urandom(32)).decode() if sys.argv[1] == "SECRETS_ENCRYPTION_KEY" else secrets.token_urlsafe(32))' "$chave")
      sed -i "s|^${chave}=$|${chave}=${valor}|" "$env_file"
    fi
  done
  # Trava contra misturar ambientes: nada de chave ou endereço de produção aqui.
  if grep -qE 'sk_live_|pk_live_|pffafnchtxbimpwyaczq|supabase\.co|pooler\.supabase\.com|api\.igreja12\.com\.br' "$env_file"; then
    erro "$env_file tem chave ou endereço de produção/nuvem. O ambiente local usa só o Supabase local e o Clerk de desenvolvimento."
  fi
}

# --- Supabase local ----------------------------------------------------------

supabase_cli() {
  local cli
  for cli in "$root/node_modules/.bin/supabase" "$main_root/node_modules/.bin/supabase"; do
    if [[ -x "$cli" ]]; then
      DO_NOT_TRACK=1 SUPABASE_TELEMETRY_DISABLED=1 "$cli" "$@" --workdir "$root"
      return
    fi
  done
  erro "Supabase CLI ausente: rode 'npm ci' na raiz de $main_root (Node $(cat "$root/.nvmrc"))."
}

subir_supabase() {
  if supabase_cli status >/dev/null 2>&1; then
    return
  fi
  docker network inspect "$network" >/dev/null 2>&1 \
    || docker network create -o com.docker.network.bridge.host_binding_ipv4=127.0.0.1 "$network" >/dev/null
  info "subindo o Supabase local (na primeira vez baixa as imagens)…"
  supabase_cli start --network-id "$network" --yes >"$state_dir/logs/supabase.log" 2>&1 \
    || { tail -20 "$state_dir/logs/supabase.log" >&2; erro "o Supabase local não subiu"; }
}

carregar_chaves_supabase() {
  local saida
  saida=$(supabase_cli status -o env 2>/dev/null) || erro "o Supabase local não está respondendo"
  SUPABASE_ANON_KEY=$(sed -n 's/^ANON_KEY="\(.*\)"$/\1/p' <<<"$saida")
  SUPABASE_SERVICE_ROLE_KEY=$(sed -n 's/^SERVICE_ROLE_KEY="\(.*\)"$/\1/p' <<<"$saida")
  export SUPABASE_ANON_KEY SUPABASE_SERVICE_ROLE_KEY
}

banco_tem_schema() {
  docker exec "$db_container" psql -U postgres -d postgres -Atc \
    "select to_regclass('public.schema_migrations') is not null" 2>/dev/null | grep -q t
}

criar_buckets() {
  docker exec "$db_container" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -c "
    insert into storage.buckets (id, name, public) values
      ('whatsapp-media', 'whatsapp-media', false),
      ('church-logos', 'church-logos', true)
    on conflict (id) do nothing;" >/dev/null
}

# --- backend e workers (Docker) ----------------------------------------------

compose() {
  PASTORAI_DEV_ENV_FILE="$env_file" docker compose --progress quiet \
    --env-file "$env_file" -f "$compose_file" "$@"
}

construir_imagem() {
  info "preparando a imagem do backend…"
  compose build --quiet backend >"$state_dir/logs/build.log" 2>&1 \
    || { tail -20 "$state_dir/logs/build.log" >&2; erro "falhou o build do backend"; }
}

no_backend() { compose run --rm --no-deps -T backend python scripts/dev_local.py "$@"; }

preparar() {
  command -v docker >/dev/null || erro "Docker não encontrado"
  mkdir -p "$state_dir/logs"
  garantir_env
  subir_supabase
  carregar_chaves_supabase
  construir_imagem
}

# --- frontend (npm run dev, fora do Docker) ----------------------------------

frontend_pid() {
  [[ -f "$state_dir/frontend.pid" ]] && kill -0 "$(cat "$state_dir/frontend.pid")" 2>/dev/null \
    && cat "$state_dir/frontend.pid"
}

subir_frontend() {
  [[ -x "$node_bin/node" ]] || erro "Node $(cat "$root/.nvmrc") não encontrado em $node_bin (instale com: nvm install)"
  frontend_pid >/dev/null && return
  if [[ ! -d "$root/frontend/node_modules" ]]; then
    info "instalando as dependências do frontend…"
    (cd "$root/frontend" && PATH="$node_bin:$PATH" npm ci --no-audit --no-fund >"$state_dir/logs/npm.log" 2>&1) \
      || erro "npm ci falhou (veja $state_dir/logs/npm.log)"
  fi
  local porta api
  porta=$(porta_front)
  api="http://localhost:$(porta_api)"
  (
    cd "$root/frontend"
    export PATH="$node_bin:$PATH" NEXT_PUBLIC_API_URL="$api"
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=$(env_valor CLERK_PUBLISHABLE_KEY)
    export NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
    exec setsid nohup npx next dev -p "$porta" -H 127.0.0.1 >"$state_dir/logs/frontend.log" 2>&1
  ) &
  echo $! >"$state_dir/frontend.pid"
  info "frontend subindo em http://localhost:$porta (a primeira página demora a compilar)"
  local _
  for _ in $(seq 1 90); do
    curl -s -o /dev/null "http://127.0.0.1:$porta/" && return
    frontend_pid >/dev/null || { tail -20 "$state_dir/logs/frontend.log" >&2; erro "o frontend parou"; }
    sleep 1
  done
  aviso "o frontend ainda não respondeu; acompanhe com ./dev.sh logs frontend"
}

parar_frontend() {
  local pid
  if pid=$(frontend_pid); then
    kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
  fi
  rm -f "$state_dir/frontend.pid"
}

# --- comandos ----------------------------------------------------------------

enderecos() {
  local front api
  front="http://localhost:$(porta_front)"
  api="http://localhost:$(porta_api)"
  cat <<EOF

  Painel (uso diário) $front
  Admin da igreja     $front/gestao
  Console plataforma  $front/admin
  API                 $api   (documentação em $api/docs)
  Banco (Studio)      http://127.0.0.1:54323
EOF
  if [[ -z "$(env_valor CLERK_SECRET_KEY)" ]]; then
    printf '\n'
    aviso "login ainda desligado: preencha CLERK_* e DEV_SEED_EMAIL_* em $env_file e rode ./dev.sh seed"
  fi
  if [[ "$(env_valor ALLOW_REAL_SENDS)" == "true" ]]; then
    aviso "ALLOW_REAL_SENDS=true: o WhatsApp local precisa ser o simulador ou o chip de teste"
  fi
}

cmd_up() {
  preparar
  if banco_tem_schema; then
    no_backend migrate
  else
    info "banco local vazio: criando o schema e os dados de teste…"
    no_backend migrate
    criar_buckets
    no_backend seed
  fi
  info "subindo backend e workers…"
  compose up -d --wait --wait-timeout 180 >"$state_dir/logs/compose.log" 2>&1 \
    || { tail -30 "$state_dir/logs/compose.log" >&2; erro "backend ou workers não ficaram de pé (./dev.sh logs backend)"; }
  subir_frontend
  info "pronto:"
  enderecos
}

cmd_reset() {
  preparar
  info "apagando o banco local…"
  compose stop backend queue-worker cron-worker broadcast-worker >/dev/null 2>&1 || true
  supabase_cli db reset --local --no-seed --network-id "$network" --yes >"$state_dir/logs/reset.log" 2>&1 \
    || { tail -20 "$state_dir/logs/reset.log" >&2; erro "o reset do banco falhou"; }
  carregar_chaves_supabase
  no_backend migrate
  criar_buckets
  no_backend seed
  if compose ps -a --services 2>/dev/null | grep -q .; then
    compose up -d --wait --wait-timeout 180 >"$state_dir/logs/compose.log" 2>&1 || true
  fi
  info "banco local recriado"
}

cmd_seed() {
  preparar
  criar_buckets
  no_backend seed
}

cmd_migrate() {
  preparar
  no_backend migrate
}

cmd_down() {
  mkdir -p "$state_dir/logs"
  parar_frontend
  if [[ -f "$env_file" ]]; then
    compose down --remove-orphans >/dev/null 2>&1 || true
  fi
  if [[ "${1:-}" == "--tudo" ]]; then
    supabase_cli stop >/dev/null 2>&1 || true
    info "Supabase local parado (os dados continuam no volume)"
  fi
  info "ambiente local parado"
}

cmd_status() {
  [[ -f "$env_file" ]] || erro "ainda não configurado: rode ./dev.sh up"
  if supabase_cli status >/dev/null 2>&1; then info "Supabase local: no ar"; else aviso "Supabase local: parado"; fi
  compose ps --format 'table {{.Service}}\t{{.State}}\t{{.Status}}' 2>/dev/null || true
  if frontend_pid >/dev/null; then info "frontend: no ar"; else aviso "frontend: parado"; fi
  enderecos
}

cmd_logs() {
  if [[ "${1:-}" == "frontend" ]]; then
    exec tail -n 100 -f "$state_dir/logs/frontend.log"
  fi
  compose logs -f --tail=100 "$@"
}

cmd_psql() { exec docker exec -it "$db_container" psql -U postgres -d postgres; }

comando="${1:-}"
[[ $# -gt 0 ]] && shift
case "$comando" in
  up) cmd_up ;;
  reset) cmd_reset ;;
  seed) cmd_seed ;;
  migrate) cmd_migrate ;;
  down) cmd_down "$@" ;;
  status) cmd_status ;;
  logs) cmd_logs "$@" ;;
  psql) cmd_psql ;;
  *) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; [[ -z "$comando" ]] || exit 1 ;;
esac
