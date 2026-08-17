#!/usr/bin/env bash
set -euo pipefail

# Backup portátil da produção. Não imprime credenciais e deve ser executado
# somente como root na VPS.
umask 077

# The active release file is the only credential source.  Scrub inherited
# connection settings before *any* helper is launched: an environment unset in
# a later subshell would still leave Python and other preflight helpers exposed.
unset DATABASE_URL PGPASSWORD PGHOST PGHOSTADDR PGPORT PGDATABASE PGUSER \
  PGSERVICE PGSERVICEFILE PGPASSFILE PGOPTIONS PGSSLMODE PGSSLCERT PGSSLKEY \
  PGSSLROOTCERT PGSSLCRL PGCONNECT_TIMEOUT PGAPPNAME PGTARGETSESSIONATTRS \
  PGCHANNELBINDING

BACKUP_ROOT="${PASTORAI_BACKUP_ROOT:-/root/pastorai-backups}"
ENV_FILE="${PASTORAI_ENV_FILE:-/opt/pastorai-current/deploy/.env}"
COMPOSE_FILE="${PASTORAI_COMPOSE_FILE:-/opt/pastorai-current/deploy/docker-compose.yml}"
MONITOR_MANIFEST="${PASTORAI_BACKUP_MONITOR_MANIFEST:-/var/lib/pastorai-backup/backup-status.json}"
DATABASE_SERVICE_HELPER="${PASTORAI_BACKUP_HELPER:-/usr/local/libexec/pastorai-backup/prepare-database-service.py}"
DATABASE_SERVICE_HELPER_SHA256="${PASTORAI_BACKUP_HELPER_SHA256:-/usr/local/libexec/pastorai-backup/prepare-database-service.py.sha256}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_ROOT}/${STAMP}"
ARCHIVE="${BACKUP_ROOT}/pastorai-backup-${STAMP}.tar.gz"
LOCK_FILE="${PASTORAI_BACKUP_LOCK_FILE:-/var/lock/pastorai-backup.lock}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "ERRO: execute como root" >&2
  exit 1
fi

if [[ ! -s "${ENV_FILE}" || ! -s "${COMPOSE_FILE}" ]]; then
  echo "ERRO: release ativo sem .env ou docker-compose.yml" >&2
  exit 1
fi

validate_database_service_helper() {
  local helper_stat checksum_stat helper_links checksum_links expected actual
  if [[ ! -f "${DATABASE_SERVICE_HELPER}" || -L "${DATABASE_SERVICE_HELPER}" \
    || ! -f "${DATABASE_SERVICE_HELPER_SHA256}" || -L "${DATABASE_SERVICE_HELPER_SHA256}" ]]; then
    echo "ERRO: pacote de credencial do backup incompleto" >&2
    return 1
  fi
  helper_stat="$(stat -c '%u:%g:%a' "${DATABASE_SERVICE_HELPER}")"
  checksum_stat="$(stat -c '%u:%g:%a' "${DATABASE_SERVICE_HELPER_SHA256}")"
  if [[ "${helper_stat}" != "0:0:700" || "${checksum_stat}" != "0:0:600" ]]; then
    echo "ERRO: permissao do pacote de credencial do backup invalida" >&2
    return 1
  fi
  helper_links="$(stat -c '%h' "${DATABASE_SERVICE_HELPER}")"
  checksum_links="$(stat -c '%h' "${DATABASE_SERVICE_HELPER_SHA256}")"
  if [[ "${helper_links}" != "1" || "${checksum_links}" != "1" ]]; then
    echo "ERRO: pacote de credencial do backup com hardlink nao permitido" >&2
    return 1
  fi
  expected="$(tr -d '[:space:]' <"${DATABASE_SERVICE_HELPER_SHA256}")"
  if [[ ! "${expected}" =~ ^[0-9a-fA-F]{64}$ ]]; then
    echo "ERRO: checksum do pacote de credencial do backup invalido" >&2
    return 1
  fi
  actual="$(sha256sum "${DATABASE_SERVICE_HELPER}" | awk '{print $1}')"
  if [[ "${actual}" != "${expected,,}" ]]; then
    echo "ERRO: checksum do pacote de credencial do backup divergente" >&2
    return 1
  fi
}

# The legacy cron starts only this script from /usr/local/sbin.  Validate its
# fixed, separately-installed helper before creating credentials, pausing any
# container, or beginning a backup.  No checkout-relative file is trusted.
validate_database_service_helper

mkdir -p "${BACKUP_ROOT}" "${BACKUP_DIR}"
chmod 700 "${BACKUP_ROOT}" "${BACKUP_DIR}"

exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "INFO: outro backup já está em execução"
  exit 0
fi

paused=0
DATABASE_CREDENTIALS_DIR=""
MONITOR_MANIFEST_TEMP=""
cleanup() {
  if [[ -n "${MONITOR_MANIFEST_TEMP}" ]]; then
    rm -f -- "${MONITOR_MANIFEST_TEMP}"
    MONITOR_MANIFEST_TEMP=""
  fi
  if [[ -n "${DATABASE_CREDENTIALS_DIR}" ]]; then
    rm -rf -- "${DATABASE_CREDENTIALS_DIR}"
    DATABASE_CREDENTIALS_DIR=""
  fi
  if [[ "${paused}" -eq 1 ]]; then
    docker unpause pastorai_evolution pastorai_evo_postgres pastorai_redis \
      >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

DATABASE_CREDENTIALS_DIR="$(mktemp -d "${BACKUP_ROOT}/.pg-credentials.XXXXXX")"
chmod 700 "${DATABASE_CREDENTIALS_DIR}"
python3 "${DATABASE_SERVICE_HELPER}" \
  "${ENV_FILE}" "${DATABASE_CREDENTIALS_DIR}"

# libpq receives only a service name; the mode-0600 service/pass files are
# mounted read-only and removed by cleanup on success, error, signal, or
# interruption.  The process environment was scrubbed before any helper above.
(
  exec docker run --rm \
    --mount "type=bind,src=${DATABASE_CREDENTIALS_DIR},dst=/run/pastorai-backup,readonly" \
    --env PGSERVICE=pastorai_backup \
    --env PGSERVICEFILE=/run/pastorai-backup/pg_service.conf \
    postgres:17-alpine \
    pg_dump --format=custom --compress=9 --no-owner --no-acl --schema=public
) >"${BACKUP_DIR}/supabase-prod-public.dump"
rm -rf -- "${DATABASE_CREDENTIALS_DIR}"
DATABASE_CREDENTIALS_DIR=""
docker run --rm -i postgres:17-alpine pg_restore --list \
  <"${BACKUP_DIR}/supabase-prod-public.dump" \
  >"${BACKUP_DIR}/supabase-prod-public.list"
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
# A non-root monitor must not read the root-only archive.  Verify the artifact
# while still privileged, then publish only bounded, non-secret metadata.
sha256sum -c "${ARCHIVE}.sha256" >/dev/null
MONITOR_MANIFEST_DIR="$(dirname -- "${MONITOR_MANIFEST}")"
install -d -m 0755 "${MONITOR_MANIFEST_DIR}"
MONITOR_MANIFEST_TEMP="$(mktemp "${MONITOR_MANIFEST_DIR}/.backup-status.XXXXXX")"
ARCHIVE_DIGEST="$(sha256sum "${ARCHIVE}" | awk '{print $1}')"
ARCHIVE_BYTES="$(stat -c '%s' "${ARCHIVE}")"
COMPLETED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '{"version":1,"status":"verified","archive":"%s","sha256":"%s","bytes":%s,"completed_at":"%s"}\n' \
  "$(basename -- "${ARCHIVE}")" "${ARCHIVE_DIGEST}" "${ARCHIVE_BYTES}" "${COMPLETED_AT}" \
  >"${MONITOR_MANIFEST_TEMP}"
chmod 0644 "${MONITOR_MANIFEST_TEMP}"
mv -f -- "${MONITOR_MANIFEST_TEMP}" "${MONITOR_MANIFEST}"
MONITOR_MANIFEST_TEMP=""

# Retém 14 dias na VPS. A cópia semanal da Hostinger e a cópia externa
# criptografada são camadas separadas deste diretório local.
find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d \
  -name '20??????T??????Z' -mtime +14 -exec rm -rf -- {} +
find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type f \
  -name 'pastorai-backup-20??????T??????Z.tar.gz*' -mtime +14 -delete

echo "BACKUP_OK stamp=${STAMP} archive=${ARCHIVE}"
