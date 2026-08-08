#!/usr/bin/env bash
set -euo pipefail

# Backup portátil da produção. Não imprime credenciais e deve ser executado
# somente como root na VPS.
umask 077

BACKUP_ROOT="/root/pastorai-backups"
ENV_FILE="/opt/pastorai-current/deploy/.env"
COMPOSE_FILE="/opt/pastorai-current/deploy/docker-compose.yml"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_ROOT}/${STAMP}"
ARCHIVE="${BACKUP_ROOT}/pastorai-backup-${STAMP}.tar.gz"
LOCK_FILE="/var/lock/pastorai-backup.lock"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERRO: execute como root" >&2
  exit 1
fi

if [[ ! -s "${ENV_FILE}" || ! -s "${COMPOSE_FILE}" ]]; then
  echo "ERRO: release ativo sem .env ou docker-compose.yml" >&2
  exit 1
fi

mkdir -p "${BACKUP_ROOT}" "${BACKUP_DIR}"
chmod 700 "${BACKUP_ROOT}" "${BACKUP_DIR}"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "INFO: outro backup já está em execução"
  exit 0
fi

paused=0
cleanup() {
  unset DATABASE_URL
  if [[ "${paused}" -eq 1 ]]; then
    docker unpause pastorai_evolution pastorai_evo_postgres pastorai_redis \
      >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

DATABASE_URL="$(ENV_FILE="${ENV_FILE}" python3 - <<'PY'
import os
from pathlib import Path

for raw in Path(os.environ["ENV_FILE"]).read_text().splitlines():
    raw = raw.strip()
    if raw and not raw.startswith("#") and "=" in raw:
        key, value = raw.split("=", 1)
        if key.strip() == "DATABASE_URL":
            print(value.strip().strip('"').strip("'"))
            break
else:
    raise SystemExit("DATABASE_URL ausente")
PY
)"

docker run --rm -e DATABASE_URL="${DATABASE_URL}" postgres:17-alpine \
  sh -c 'exec pg_dump --dbname="$DATABASE_URL" --format=custom --compress=9 --no-owner --no-acl --schema=public' \
  >"${BACKUP_DIR}/supabase-prod-public.dump"
docker run --rm -i postgres:17-alpine pg_restore --list \
  <"${BACKUP_DIR}/supabase-prod-public.dump" \
  >"${BACKUP_DIR}/supabase-prod-public.list"
unset DATABASE_URL

BACKUP_DIR="${BACKUP_DIR}" ENV_FILE="${ENV_FILE}" python3 - <<'PY'
import json
import os
import pathlib
import urllib.parse
import urllib.request

backup = pathlib.Path(os.environ["BACKUP_DIR"]) / "supabase-storage"
backup.mkdir(parents=True, exist_ok=True)
env = {}
for raw in pathlib.Path(os.environ["ENV_FILE"]).read_text().splitlines():
    raw = raw.strip()
    if raw and not raw.startswith("#") and "=" in raw:
        key, value = raw.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")

url = env["SUPABASE_URL"].rstrip("/")
key = env["SUPABASE_SERVICE_ROLE_KEY"]
headers = {"apikey": key, "Authorization": "Bearer " + key}
manifest = []

def request(path, method="GET", body=None):
    data = None if body is None else json.dumps(body).encode()
    request_headers = dict(headers)
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url + path, data=data, headers=request_headers, method=method
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return response.read()

def walk(bucket, prefix=""):
    offset = 0
    while True:
        items = json.loads(
            request(
                "/storage/v1/object/list/" + urllib.parse.quote(bucket, safe=""),
                "POST",
                {
                    "prefix": prefix,
                    "limit": 100,
                    "offset": offset,
                    "sortBy": {"column": "name", "order": "asc"},
                },
            )
        )
        if not items:
            break
        for item in items:
            full_name = prefix + item["name"]
            if item.get("id") is None and item.get("metadata") is None:
                walk(bucket, full_name.rstrip("/") + "/")
                continue
            encoded = "/".join(
                urllib.parse.quote(part, safe="") for part in full_name.split("/")
            )
            blob = request(
                "/storage/v1/object/authenticated/"
                + urllib.parse.quote(bucket, safe="")
                + "/"
                + encoded
            )
            target = backup / bucket / full_name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
            manifest.append(
                {"bucket": bucket, "name": full_name, "bytes": len(blob)}
            )
        if len(items) < 100:
            break
        offset += len(items)

buckets = json.loads(request("/storage/v1/bucket"))
for bucket in buckets:
    walk(bucket["id"])

(backup / "manifest.json").write_text(
    json.dumps(
        {"buckets": [item["id"] for item in buckets], "objects": manifest},
        indent=2,
    ),
    encoding="utf-8",
)
PY

docker exec pastorai_evo_postgres pg_dump \
  -U evolution -d evolution --format=custom --compress=9 --no-owner --no-acl \
  >"${BACKUP_DIR}/evolution-postgres.dump"
docker run --rm -i postgres:16-alpine pg_restore --list \
  <"${BACKUP_DIR}/evolution-postgres.dump" \
  >"${BACKUP_DIR}/evolution-postgres.list"

install -m 600 "${ENV_FILE}" "${BACKUP_DIR}/deploy.env"
install -m 600 "${COMPOSE_FILE}" "${BACKUP_DIR}/docker-compose.yml"

docker pull alpine:3.20 >/dev/null
docker exec pastorai_evo_postgres psql -U evolution -d evolution \
  -c CHECKPOINT >/dev/null
docker pause pastorai_evolution pastorai_evo_postgres pastorai_redis >/dev/null
paused=1

docker run --rm \
  -v pastorai_evolution_instances:/source:ro \
  -v "${BACKUP_DIR}:/backup" \
  alpine:3.20 tar -czf /backup/evolution-instances-volume.tar.gz -C /source .
docker run --rm \
  -v pastorai_evolution_pg_data:/source:ro \
  -v "${BACKUP_DIR}:/backup" \
  alpine:3.20 tar -czf /backup/evolution-postgres-volume.tar.gz -C /source .
docker run --rm \
  -v pastorai_redis_data:/source:ro \
  -v "${BACKUP_DIR}:/backup" \
  alpine:3.20 tar -czf /backup/redis-volume.tar.gz -C /source .

docker unpause pastorai_evolution pastorai_evo_postgres pastorai_redis >/dev/null
paused=0

curl -fsS http://127.0.0.1:8000/health >"${BACKUP_DIR}/backend-health.json"
docker exec pastorai_evolution wget -qO- http://127.0.0.1:8080 \
  >"${BACKUP_DIR}/evolution-health.json"

cd "${BACKUP_DIR}"
find . -type f ! -name SHA256SUMS -print0 \
  | sort -z \
  | xargs -0 sha256sum >SHA256SUMS
sha256sum -c SHA256SUMS >/dev/null

cd "${BACKUP_ROOT}"
tar -czf "${ARCHIVE}" "${STAMP}"
sha256sum "${ARCHIVE}" >"${ARCHIVE}.sha256"
chmod 600 "${ARCHIVE}" "${ARCHIVE}.sha256"

# Retém 14 dias na VPS. A cópia semanal da Hostinger e a cópia externa
# criptografada são camadas separadas deste diretório local.
find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d \
  -name '20??????T??????Z' -mtime +14 -exec rm -rf -- {} +
find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type f \
  -name 'pastorai-backup-20??????T??????Z.tar.gz*' -mtime +14 -delete

echo "BACKUP_OK stamp=${STAMP} archive=${ARCHIVE}"
