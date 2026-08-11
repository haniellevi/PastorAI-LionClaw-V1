#!/usr/bin/env bash
set -euo pipefail

# Instala de forma atômica o pacote completo consumido pelo cron M02.  O cron
# chama apenas /usr/local/sbin/pastorai-backup.sh; por isso o auxiliar que lê a
# DATABASE_URL precisa existir em um caminho fixo e verificável, não no checkout
# temporário do release.
umask 077

if [[ "${PASTORAI_LEGACY_BACKUP_INSTALL_TEST_MODE:-0}" != 1 && "${EUID}" -ne 0 ]]; then
  echo "ERRO: execute como root" >&2
  exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_BACKUP="${PASTORAI_LEGACY_BACKUP_SOURCE:-${SCRIPT_DIR}/backup-production.sh}"
SOURCE_HELPER="${PASTORAI_LEGACY_BACKUP_HELPER_SOURCE:-${SCRIPT_DIR}/prepare-database-service.py}"
TARGET_BACKUP="${PASTORAI_LEGACY_BACKUP_TARGET:-/usr/local/sbin/pastorai-backup.sh}"
TARGET_HELPER_DIR="${PASTORAI_LEGACY_BACKUP_HELPER_DIR:-/usr/local/libexec/pastorai-backup}"
TARGET_HELPER="${TARGET_HELPER_DIR}/prepare-database-service.py"
TARGET_HELPER_SHA256="${TARGET_HELPER}.sha256"

fail_if_requested() {
  if [[ "${PASTORAI_LEGACY_BACKUP_INSTALL_TEST_MODE:-0}" == 1 \
    && "${PASTORAI_LEGACY_BACKUP_INSTALL_FAIL_STEP:-}" == "$1" ]]; then
    echo "ERRO: falha de teste injetada em instalacao do backup" >&2
    return 1
  fi
}

validate_source() {
  local path="$1"
  [[ -f "${path}" && ! -L "${path}" ]] || {
    echo "ERRO: artefato do backup ausente" >&2
    return 1
  }
}

validate_installed_file() {
  local path="$1" expected_mode="$2" actual
  [[ -f "${path}" && ! -L "${path}" ]] || return 1
  actual="$(stat -c '%u:%g:%a' "${path}")"
  [[ "${actual}" == "0:0:${expected_mode}" ]]
}

validate_source "${SOURCE_BACKUP}"
validate_source "${SOURCE_HELPER}"

TRANSACTION_DIR="$(mktemp -d "${TMPDIR:-/tmp}/pastorai-legacy-backup-install.XXXXXX")"
STAGE_DIR="${TRANSACTION_DIR}/stage"
ROLLBACK_DIR="${TRANSACTION_DIR}/rollback"
mkdir -p "${STAGE_DIR}" "${ROLLBACK_DIR}"
ROLLBACK_READY=0
COMMITTED=0
LIVE_TEMP_FILES=()
TARGET_BACKUP_DIR="$(dirname -- "${TARGET_BACKUP}")"
TARGET_BACKUP_DIR_EXISTED=0
TARGET_HELPER_DIR_EXISTED=0
[[ -d "${TARGET_BACKUP_DIR}" ]] && TARGET_BACKUP_DIR_EXISTED=1
[[ -d "${TARGET_HELPER_DIR}" ]] && TARGET_HELPER_DIR_EXISTED=1

snapshot_file() {
  local target="$1" name="$2"
  if [[ -e "${target}" ]]; then
    cp -p -- "${target}" "${ROLLBACK_DIR}/${name}"
    : >"${ROLLBACK_DIR}/${name}.present"
  fi
}

restore_file() {
  local target="$1" name="$2"
  if [[ -f "${ROLLBACK_DIR}/${name}.present" ]]; then
    install -o root -g root -m "$(stat -c '%a' "${ROLLBACK_DIR}/${name}")" \
      "${ROLLBACK_DIR}/${name}" "${target}"
  else
    rm -f -- "${target}"
  fi
}

rollback_install() {
  set +e
  restore_file "${TARGET_BACKUP}" backup-production.sh
  restore_file "${TARGET_HELPER}" prepare-database-service.py
  restore_file "${TARGET_HELPER_SHA256}" prepare-database-service.py.sha256
  [[ "${TARGET_HELPER_DIR_EXISTED}" -eq 1 ]] || rmdir "${TARGET_HELPER_DIR}" >/dev/null 2>&1
  [[ "${TARGET_BACKUP_DIR_EXISTED}" -eq 1 ]] || rmdir "${TARGET_BACKUP_DIR}" >/dev/null 2>&1
  set -e
}

finish_transaction() {
  local status=$?
  trap - EXIT INT TERM
  if [[ "${status}" -ne 0 && "${ROLLBACK_READY}" -eq 1 && "${COMMITTED}" -eq 0 ]]; then
    rollback_install
  fi
  if [[ "${#LIVE_TEMP_FILES[@]}" -gt 0 ]]; then
    rm -f -- "${LIVE_TEMP_FILES[@]}"
  fi
  rm -rf -- "${TRANSACTION_DIR}"
  exit "${status}"
}
trap finish_transaction EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Stage every component and checksum it before writing a live path.  The
# sidecar contains only a digest, never configuration or credentials.
install -o root -g root -m 0700 "${SOURCE_BACKUP}" "${STAGE_DIR}/backup-production.sh"
install -o root -g root -m 0700 "${SOURCE_HELPER}" "${STAGE_DIR}/prepare-database-service.py"
sha256sum "${STAGE_DIR}/prepare-database-service.py" | awk '{print $1}' \
  >"${STAGE_DIR}/prepare-database-service.py.sha256"
chmod 0600 "${STAGE_DIR}/prepare-database-service.py.sha256"
validate_installed_file "${STAGE_DIR}/backup-production.sh" 700
validate_installed_file "${STAGE_DIR}/prepare-database-service.py" 700
validate_installed_file "${STAGE_DIR}/prepare-database-service.py.sha256" 600
fail_if_requested preflight

snapshot_file "${TARGET_BACKUP}" backup-production.sh
snapshot_file "${TARGET_HELPER}" prepare-database-service.py
snapshot_file "${TARGET_HELPER_SHA256}" prepare-database-service.py.sha256
ROLLBACK_READY=1

install -d -o root -g root -m 0755 "${TARGET_BACKUP_DIR}" "${TARGET_HELPER_DIR}"

replace_file() {
  local source="$1" target="$2" mode="$3" staged
  staged="$(mktemp "$(dirname -- "${target}")/.pastorai-backup.new.XXXXXX")"
  LIVE_TEMP_FILES+=("${staged}")
  install -o root -g root -m "${mode}" "${source}" "${staged}"
  mv -f -- "${staged}" "${target}"
}

# Helper and checksum land before the entrypoint; the cron keeps seeing the old
# script until all of its new dependencies are present.  Any later failure is
# restored from the snapshots above.
replace_file "${STAGE_DIR}/prepare-database-service.py" "${TARGET_HELPER}" 700
replace_file "${STAGE_DIR}/prepare-database-service.py.sha256" "${TARGET_HELPER_SHA256}" 600
fail_if_requested helper-installed
replace_file "${STAGE_DIR}/backup-production.sh" "${TARGET_BACKUP}" 700
fail_if_requested backup-installed

validate_installed_file "${TARGET_BACKUP}" 700
validate_installed_file "${TARGET_HELPER}" 700
validate_installed_file "${TARGET_HELPER_SHA256}" 600
expected="$(tr -d '[:space:]' <"${TARGET_HELPER_SHA256}")"
actual="$(sha256sum "${TARGET_HELPER}" | awk '{print $1}')"
[[ "${expected}" =~ ^[0-9a-fA-F]{64}$ && "${actual}" == "${expected,,}" ]] || {
  echo "ERRO: pacote de backup invalido apos instalacao" >&2
  exit 1
}

COMMITTED=1
echo "Backup legado instalado: ${TARGET_BACKUP}"
