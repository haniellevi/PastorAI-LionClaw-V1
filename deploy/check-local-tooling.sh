#!/usr/bin/env bash

set -uo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

failures=0
network_checks=false
runtime_python="${PASTORAI_RUNTIME_PYTHON:-backend/.venv-runtime/bin/python}"

case "${1:-}" in
  "")
    ;;
  --network)
    network_checks=true
    ;;
  *)
    printf 'Uso: %s [--network]\n' "$0" >&2
    exit 2
    ;;
esac

pass() {
  printf 'OK   %s\n' "$1"
}

fail() {
  printf 'FAIL %s\n' "$1" >&2
  failures=$((failures + 1))
}

check_exact_version() {
  local label="$1"
  local expected="$2"
  shift 2

  local actual
  if ! actual=$("$@" 2>/dev/null); then
    fail "${label}: comando indisponível"
    return
  fi

  if [[ "$actual" == "$expected" ]]; then
    pass "${label} ${actual}"
  else
    fail "${label}: esperado ${expected}, encontrado ${actual}"
  fi
}

check_http() {
  local label="$1"
  local url="$2"
  local status

  status=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 --request GET "$url" 2>/dev/null || true)
  case "$status" in
  200|204|401|405)
    pass "${label}: HTTP ${status}"
    ;;
  *)
    fail "${label}: sem resposta HTTP válida (${status:-000})"
    ;;
  esac
}

check_exact_version "Node" "v24.19.0" node --version

if [[ -x "$runtime_python" ]]; then
  check_exact_version "Python runtime" "Python 3.13.14" "$runtime_python" --version
  if "$runtime_python" -m pip --version >/dev/null 2>&1; then
    pass "Python runtime pip disponível"
  else
    fail "Python runtime: pip ausente (crie o venv com uv venv --seed)"
  fi
else
  fail "Python runtime: ${runtime_python} ausente (crie backend/.venv-runtime ou defina PASTORAI_RUNTIME_PYTHON)"
fi

if docker info >/dev/null 2>&1; then
  pass "Docker daemon acessível"
else
  fail "Docker daemon inacessível; reabra a sessão do Codex após entrar no grupo docker"
fi

if compose_version=$(docker compose version --short 2>/dev/null); then
  pass "Docker Compose ${compose_version}"
else
  fail "Docker Compose indisponível"
fi

check_exact_version "Supabase CLI" "2.115.0" env SUPABASE_TELEMETRY_DISABLED=1 "$repo_root/node_modules/.bin/supabase" --version

if [[ -f supabase/config.toml ]]; then
  pass "supabase/config.toml presente"
else
  fail "supabase/config.toml ausente"
fi

if node -e 'JSON.parse(require("fs").readFileSync(".mcp.json", "utf8"))' >/dev/null 2>&1; then
  pass ".mcp.json válido"
else
  fail ".mcp.json ausente ou inválido"
fi

local_supabase_mcp=$(node -e '
const config = JSON.parse(require("fs").readFileSync(".mcp.json", "utf8"));
const server = config.mcpServers?.["supabase-local"];
if (server?.type === "http" && typeof server.url === "string") process.stdout.write(server.url);
' 2>/dev/null || true)

if [[ -n "$local_supabase_mcp" ]]; then
  check_http "Supabase MCP local" "$local_supabase_mcp"
else
  fail "Supabase MCP local: servidor HTTP supabase-local ausente em .mcp.json"
fi

if $network_checks; then
  check_http "Vercel MCP" "https://mcp.vercel.com"
  check_http "Hostinger MCP" "https://mcp.hostinger.com"
  check_http "Supabase MCP hospedado" "https://mcp.supabase.com/mcp"
  check_http "Brevo MCP" "https://mcp.brevo.com/v1/brevo/mcp"
fi

if (( failures > 0 )); then
  printf '%d verificação(ões) falharam.\n' "$failures" >&2
  exit 1
fi

pass "toolchain local validado"
