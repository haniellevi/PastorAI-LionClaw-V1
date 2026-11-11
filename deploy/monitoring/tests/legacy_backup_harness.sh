#!/usr/bin/env bash
set -euo pipefail

# Simula a instalação M02 em árvore vazia.  Não toca /usr/local, cron, Docker
# real ou checkout de produção: todos os destinos são redirecionados ao sandbox.
TEST_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DEPLOY_DIR="$(CDPATH= cd -- "${TEST_DIR}/../.." && pwd)"
INSTALL_SCRIPT="${DEPLOY_DIR}/install-legacy-backup.sh"
SANDBOX="$(mktemp -d /root/pastorai-legacy-backup-test.XXXXXX)"
trap 'rm -rf -- "${SANDBOX}"' EXIT INT TERM

LEGACY_ROOT="${SANDBOX}/legacy"
BACKUP_SCRIPT="${LEGACY_ROOT}/usr/local/sbin/pastorai-backup.sh"
HELPER_DIR="${LEGACY_ROOT}/usr/local/libexec/pastorai-backup"
HELPER="${HELPER_DIR}/prepare-database-service.py"
HELPER_SHA256="${HELPER}.sha256"
BACKUP_ROOT="${SANDBOX}/backups"
ENV_FILE="${SANDBOX}/deploy.env"
COMPOSE_FILE="${SANDBOX}/docker-compose.yml"
LOG="${SANDBOX}/docker.log"
BIN_DIR="${SANDBOX}/bin"
SECRET='postgresql://synthetic-user:synthetic-secret@example.invalid/database?sslmode=require'

mkdir -p "${BIN_DIR}"
printf 'DATABASE_URL=%s\nSUPABASE_URL=https://unused.invalid\nSUPABASE_SERVICE_ROLE_KEY=unused\n' "${SECRET}" >"${ENV_FILE}"
printf 'services: {}\n' >"${COMPOSE_FILE}"
chmod 0600 "${ENV_FILE}" "${COMPOSE_FILE}"

cat >"${BIN_DIR}/docker" <<'EOF'
#!/usr/bin/env sh
set -eu
printf '%s\n' "$*" >>"${FAKE_DOCKER_LOG:?}"
case " ${*} " in
  *' pause '*) exit 91 ;;
  *) exit 23 ;;
esac
EOF
chmod 0755 "${BIN_DIR}/docker"

install_package() {
  PASTORAI_LEGACY_BACKUP_INSTALL_TEST_MODE=1 \
  PASTORAI_LEGACY_BACKUP_TARGET="${BACKUP_SCRIPT}" \
  PASTORAI_LEGACY_BACKUP_HELPER_DIR="${HELPER_DIR}" \
  bash "${INSTALL_SCRIPT}" >/dev/null
}

run_backup() {
  : >"${LOG}"
  (
    cd /
    PATH="${BIN_DIR}:$PATH" \
    FAKE_DOCKER_LOG="${LOG}" \
    PASTORAI_BACKUP_ROOT="${BACKUP_ROOT}" \
    PASTORAI_ENV_FILE="${ENV_FILE}" \
    PASTORAI_COMPOSE_FILE="${COMPOSE_FILE}" \
    PASTORAI_BACKUP_LOCK_FILE="${SANDBOX}/backup.lock" \
    PASTORAI_BACKUP_MONITOR_MANIFEST="${SANDBOX}/backup-status.json" \
    PASTORAI_BACKUP_HELPER="${HELPER}" \
    PASTORAI_BACKUP_HELPER_SHA256="${HELPER_SHA256}" \
    bash "${BACKUP_SCRIPT}" >"${SANDBOX}/output" 2>&1
  )
}

run_backup_expect_preflight_failure() {
  local status=0
  run_backup || status=$?
  [[ "${status}" -ne 0 ]]
  [[ ! -s "${LOG}" ]]
  ! grep -Fq "${SECRET}" "${SANDBOX}/output"
  if [[ -d "${BACKUP_ROOT}" ]] && find "${BACKUP_ROOT}" -maxdepth 1 -name '.pg-credentials.*' -print -quit | grep -q .; then
    echo 'temporary credentials leaked after preflight' >&2
    exit 71
  fi
}

# Full package installation from an otherwise empty /usr/local tree.  Running
# from / proves the installed entrypoint has no checkout-relative dependency.
install_package
[[ -f "${BACKUP_SCRIPT}" && ! -L "${BACKUP_SCRIPT}" ]]
[[ "$(stat -c '%u:%g:%a' "${BACKUP_SCRIPT}")" == '0:0:700' ]]
[[ "$(stat -c '%u:%g:%a' "${HELPER}")" == '0:0:700' ]]
[[ "$(stat -c '%u:%g:%a' "${HELPER_SHA256}")" == '0:0:600' ]]
[[ "$(stat -c '%h' "${HELPER}")" == '1' ]]
[[ "$(stat -c '%h' "${HELPER_SHA256}")" == '1' ]]
status=0
run_backup || status=$?
[[ "${status}" -eq 23 ]]
grep -Eq '(^| )run( |$)' "${LOG}"
! grep -Eq '(^| )pause( |$)' "${LOG}"
! grep -Fq "${SECRET}" "${SANDBOX}/output"
if find "${BACKUP_ROOT}" -maxdepth 1 -name '.pg-credentials.*' -print -quit | grep -q .; then
  echo 'temporary credentials leaked after installed backup' >&2
  exit 72
fi

[[ "$(stat -c '%a' "${BACKUP_ROOT}")" == 700 ]]
run_dir="$(find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -name '20??????T??????Z')"
[[ -n "${run_dir}" && "$(stat -c '%a' "${run_dir}")" == 700 ]]
BACKUP_ROOT="${SANDBOX}/failure-backups"
mkdir -m 0700 "${BACKUP_ROOT}"

# Missing, changed and permissive helpers must fail before Docker can reach a
# pause action.  Reinstall a complete package between each independent case.
rm -f -- "${HELPER}"
run_backup_expect_preflight_failure
install_package
printf '\n# altered\n' >>"${HELPER}"
run_backup_expect_preflight_failure
install_package
chmod 0755 "${HELPER}"
run_backup_expect_preflight_failure

# A regular file with another hardlink has a second writable name outside the
# fixed helper directory.  Reject both helper and checksum before any Docker
# action, even when owner, mode and digest still look valid.
install_package
ln "${HELPER}" "${SANDBOX}/helper-hardlink"
run_backup_expect_preflight_failure
rm -f -- "${SANDBOX}/helper-hardlink"
install_package
ln "${HELPER_SHA256}" "${SANDBOX}/checksum-hardlink"
run_backup_expect_preflight_failure
rm -f -- "${SANDBOX}/checksum-hardlink"

# The destination is checked before the first Docker command. Preserve an
# existing tree and refuse symlinks, writable ancestors and permissive roots.
valid_root="${BACKUP_ROOT}"
BACKUP_ROOT="${SANDBOX}/symlinked-root"
ln -s "${valid_root}" "${BACKUP_ROOT}"
run_backup_expect_preflight_failure
[[ -z "$(ls -A "${valid_root}")" ]]

ln -s "${SANDBOX}" "${SANDBOX}/symlinked-parent"
BACKUP_ROOT="${SANDBOX}/symlinked-parent/absent"
run_backup_expect_preflight_failure
[[ ! -e "${SANDBOX}/absent" ]]

BACKUP_ROOT="${SANDBOX}/permissive-root"
mkdir -m 0750 "${BACKUP_ROOT}"
run_backup_expect_preflight_failure
[[ "$(stat -c '%a' "${BACKUP_ROOT}")" == 750 && -z "$(ls -A "${BACKUP_ROOT}")" ]]

mkdir -m 0770 "${SANDBOX}/writable-parent"
BACKUP_ROOT="${SANDBOX}/writable-parent/absent"
run_backup_expect_preflight_failure
[[ ! -e "${BACKUP_ROOT}" ]]

printf 'fixture-lock\n' >"${SANDBOX}/backup.lock"
exec 8>>"${SANDBOX}/backup.lock"
flock -n 8
BACKUP_ROOT="${SANDBOX}/locked-backup"
run_backup
[[ ! -e "${BACKUP_ROOT}" && ! -s "${LOG}" ]]
[[ "$(cat "${SANDBOX}/backup.lock")" == fixture-lock ]]
flock -u 8
exec 8>&-

cat >"${BIN_DIR}/date" <<'EOF'
#!/bin/sh
printf '%s\n' 20261005T120000Z
EOF
chmod 0755 "${BIN_DIR}/date"
stamp=20261005T120000Z
BACKUP_ROOT="${valid_root}"
mkdir -m 0700 "${BACKUP_ROOT}/${stamp}"
printf 'preserve-run\n' >"${BACKUP_ROOT}/${stamp}/fixture"
run_backup_expect_preflight_failure
[[ "$(cat "${BACKUP_ROOT}/${stamp}/fixture")" == preserve-run ]]

for suffix in '' .sha256; do
  BACKUP_ROOT="${SANDBOX}/occupied${suffix}"
  mkdir -m 0700 "${BACKUP_ROOT}"
  artifact="${BACKUP_ROOT}/pastorai-backup-${stamp}.tar.gz${suffix}"
  printf 'preserve-artifact\n' >"${artifact}"
  run_backup_expect_preflight_failure
  [[ ! -e "${BACKUP_ROOT}/${stamp}" && "$(cat "${artifact}")" == preserve-artifact ]]
done

BACKUP_ROOT="${SANDBOX}/linked-artifact"
mkdir -m 0700 "${BACKUP_ROOT}"
artifact="${BACKUP_ROOT}/pastorai-backup-${stamp}.tar.gz"
ln -s "${SANDBOX}/absent-artifact" "${artifact}"
run_backup_expect_preflight_failure
[[ -L "${artifact}" && ! -e "${SANDBOX}/absent-artifact" ]]

# Installation must reject a hardlinked source helper before it snapshots or
# overwrites the live package.  Use a copied source so the repository file is
# never hardlinked by this controlled test.
SOURCE_HELPER="${SANDBOX}/source-helper.py"
cp "${DEPLOY_DIR}/prepare-database-service.py" "${SOURCE_HELPER}"
ln "${SOURCE_HELPER}" "${SANDBOX}/source-helper-hardlink"
before="$(sha256sum "${HELPER}" | awk '{print $1}')"
set +e
PASTORAI_LEGACY_BACKUP_INSTALL_TEST_MODE=1 \
PASTORAI_LEGACY_BACKUP_TARGET="${BACKUP_SCRIPT}" \
PASTORAI_LEGACY_BACKUP_HELPER_DIR="${HELPER_DIR}" \
PASTORAI_LEGACY_BACKUP_HELPER_SOURCE="${SOURCE_HELPER}" \
bash "${INSTALL_SCRIPT}" >/dev/null 2>&1
status=$?
set -e
[[ "${status}" -ne 0 ]]
[[ "$(sha256sum "${HELPER}" | awk '{print $1}')" == "${before}" ]]

printf 'LEGACY_BACKUP_OK\n'
