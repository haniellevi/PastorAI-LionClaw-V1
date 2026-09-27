#!/usr/bin/env bash
# ler_prod_na_vps.sh - leitura SÓ LEITURA do PROD para o espelho DEV = PROD (27/09/2026).
#
# Roda na VPS, como root, e manda o resultado como tar pela saída padrão:
#   ssh root@vps 'bash <kit>/ler_prod_na_vps.sh <kit>' > leitura_prod.tar
# Nada da leitura fica na VPS: a pasta de saída é apagada ao sair (também em
# erro). Quem chamou apaga depois a pasta <kit> que copiou.
#
# A senha do banco não sai da VPS: o helper do backup gera um pg_service.conf e um
# pgpass efêmeros (modo 0600), montados só leitura no container do psql/pg_dump e
# apagados assim que as leituras terminam (também em erro ou interrupção).
# Nada é escrito no banco: pg_dump --schema-only (sem dados) e os .sql do kit, que
# rodam em BEGIN READ ONLY ... ROLLBACK. O inventário roda sem contar linhas.
set -euo pipefail
umask 077

KIT="${1:?uso: bash ler_prod_na_vps.sh <pasta do kit>}"
HELPER="${PASTORAI_DB_HELPER:-/usr/local/libexec/pastorai-backup/prepare-database-service.py}"
ENV_FILE="${PASTORAI_ENV_FILE:-/opt/pastorai-current/deploy/.env}"
IMAGEM="${PASTORAI_PG_IMAGE:-postgres:17-alpine}"
SAIDA="$(mktemp -d "${PASTORAI_SAIDA_BASE:-/root}/pastorai-leitura-prod.XXXXXX")"
CRED="$SAIDA/cred"

limpa() { rm -rf -- "$CRED"; }
limpa_tudo() { rm -rf -- "$SAIDA"; }
trap limpa_tudo EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for f in inventario_ro.sql fingerprint_ro.sql ledger_lista_ro.sql prova_objetos.sql prova_s2.sql; do
  [ -f "$KIT/$f" ] || { echo "falta $KIT/$f" >&2; exit 2; }
done

mkdir -m 700 "$CRED"
python3 "$HELPER" "$ENV_FILE" "$CRED"

pg() {
  docker run --rm -i \
    --mount "type=bind,src=$CRED,dst=/run/pastorai-backup,readonly" \
    --env PGSERVICE=pastorai_backup \
    --env PGSERVICEFILE=/run/pastorai-backup/pg_service.conf \
    --env PGAPPNAME=pastorai-leitura-espelho-dev \
    "$IMAGEM" "$@"
}
ro() { pg psql -X -q -v ON_ERROR_STOP=1 "$@" -f - ; }

pg pg_dump --schema-only --schema=public > "$SAIDA/prod_public_schema.sql"
ro < "$KIT/inventario_ro.sql" > "$SAIDA/inventario_prod.txt"
ro --csv < "$KIT/fingerprint_ro.sql" > "$SAIDA/fingerprint_prod.csv"
ro --csv < "$KIT/ledger_lista_ro.sql" > "$SAIDA/ledger_prod.csv"
ro --csv < "$KIT/prova_objetos.sql" > "$SAIDA/prova_prod.csv"
ro --csv < "$KIT/prova_s2.sql" > "$SAIDA/prova_s2_prod.csv"
limpa

{
  echo "leitura_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "imagem=$IMAGEM $(docker image inspect --format '{{index .RepoDigests 0}}' "$IMAGEM" 2>/dev/null || echo sem-digest)"
  echo "pg_dump=$(docker run --rm "$IMAGEM" pg_dump --version)"
  echo "helper_sha256=$(sha256sum "$HELPER" | cut -d' ' -f1)"
} > "$SAIDA/contexto.txt"
(cd "$SAIDA" && sha256sum prod_public_schema.sql inventario_prod.txt fingerprint_prod.csv ledger_prod.csv \
  prova_prod.csv prova_s2_prod.csv contexto.txt > SHA256SUMS)
tar -C "$SAIDA" -cf - .
