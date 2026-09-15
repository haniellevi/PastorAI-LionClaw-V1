#!/usr/bin/env python3
"""Gera o anexo F1 de comparação DEV x referência a partir de índices opacos."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Iterable


REPO_ROOT = Path(__file__).resolve().parents[4]
MIGRATIONS_DIR = REPO_ROOT / "backend" / "migrations"
INVENTORY_PATH = REPO_ROOT / "docs" / "ops" / "dev-migration-history-remediation" / "INVENTORY-44.md"
FROZEN_SQL_SHA256 = "8829decd0f0101329058ad07900ce7b7ca8b1c4fe5695f4e3cec05cff4bf288c"
FROZEN_AGGREGATE_SHA256 = "956187b9711ea9d67e9f8fdf31c3980e3ebbf64da98401c275f1dc80d2a91a29"
SAFE_INDEX_FORMAT = "F1_CATALOG_SAFE_INDEX_V3"
NOT_SCHEMA_DECIDABLE = {13, 17, 21, 22, 30, 32, 33, 34, 38}
PARTIAL = {12, 15, 19, 36, 37}
ABSENT = {40, 41, 42, 43, 44}
ACL_STATE_RECORD_TYPES = {"CATALOG_SCHEMA", "CATALOG_RELATION"}
CATALOG_RECORD_TYPES = {
    "CATALOG_SCHEMA",
    "CATALOG_RELATION",
    "CATALOG_COLUMN",
    "CATALOG_CONSTRAINT",
    "CATALOG_INDEX",
    "CATALOG_RLS_POLICY",
    "CATALOG_FUNCTION",
    "CATALOG_TRIGGER",
    "CATALOG_TYPE",
    "CATALOG_ROLE_AGENT_RUNTIME",
    "CATALOG_ROLE_AGENT_RUNTIME_MEMBERSHIP",
    "SCHEMA_ACL_DIRECT_GRANTEE",
    "RELACL_DIRECT_GRANTEE",
    "PROACL_DIRECT_GRANTEE",
    "DEFAULT_ACL_SCOPE",
    "DEFAULT_ACL_DIRECT_GRANTEE",
    "UNEXPECTED_CUSTOM_GRANTEE_SUMMARY",
    "PREFLIGHT_SCOPE",
}
CONTROL_RECORD_TYPES = {
    "TARGET_DIGEST",
    "F1_SESSION",
    "LEDGER_RELATION",
    "LEDGER_COLUMN",
    "PUBLIC_LEDGER_COUNT_EXPECTATION",
    "PUBLIC_LEDGER_ENTRY",
    "NATIVE_LEDGER_COUNT_EXPECTATION",
    "NATIVE_LEDGER_ENTRY",
    "NATIVE_LEDGER_STATEMENT_FINGERPRINT",
}
SAFE_INDEX_FIELDS = {
    "format",
    "receipt_marker_counts",
    "record_count",
    "record_type_counts",
    "records",
    "rollback_receipt_state",
    "source",
    "source_observed_record_type_counts",
}
REQUIRED_DEV_CONTROL_TYPES = {
    "TARGET_DIGEST",
    "F1_SESSION",
    "PUBLIC_LEDGER_COUNT_EXPECTATION",
    "NATIVE_LEDGER_COUNT_EXPECTATION",
}
ALLOWED_RECEIPT_MARKERS = {
    "DEV": {"BEGIN", "SET", "ROLLBACK", "ROLLBACK_COMPLETED_F1"},
    "REFERENCE": {
        "BEGIN",
        "SET",
        "ROLLBACK",
        "REFERENCE_CATALOG_ADAPTER",
        "REFERENCE_CATALOG_ROLLBACK_COMPLETED",
    },
}
INVENTORY_ANCHORS = {
    5: "20260704_100000_celula_pr2_reuniao_presenca_expectativa.sql",
    30: "20260730_205332_billing_setup_configuration.sql",
    39: "20260827_175634_d1a_tenant_runtime_integrity.sql",
    44: "20260910_142830_add_e4b_consent_persistence.sql",
}


def _digest(label: bytes, pairs: Iterable[tuple[str, str]]) -> str:
    hasher = hashlib.sha256()
    hasher.update(label)
    for key, value in pairs:
        hasher.update(key.encode("ascii"))
        hasher.update(b"\x1f")
        hasher.update(value.encode("ascii"))
        hasher.update(b"\n")
    return hasher.hexdigest()


def _valid_count_map(value: object, allowed_names: set[str]) -> bool:
    return (
        isinstance(value, dict)
        and all(
            isinstance(name, str)
            and name in allowed_names
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count > 0
            for name, count in value.items()
        )
    )


def _read_index(path: Path, source: str) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="ascii"))
    if (
        not isinstance(document, dict)
        or set(document) != SAFE_INDEX_FIELDS
        or document.get("format") != SAFE_INDEX_FORMAT
        or document.get("source") != source
    ):
        raise ValueError("safe index contract invalid")
    records = document.get("records")
    record_count = document.get("record_count")
    if (
        not isinstance(records, list)
        or not records
        or not isinstance(record_count, int)
        or isinstance(record_count, bool)
        or record_count != len(records)
    ):
        raise ValueError("safe index records absent")
    record_counts = Counter()
    for record in records:
        if (
            not isinstance(record, dict)
            or set(record) != {
                "definition_sha256",
                "key_sha256",
                "payload_sha256",
                "record_type",
            }
            or not all(
                isinstance(record[field], str)
                and re.fullmatch(r"[0-9a-f]{64}", record[field])
                for field in ("definition_sha256", "key_sha256", "payload_sha256")
            )
            or not isinstance(record["record_type"], str)
            or record["record_type"] not in CATALOG_RECORD_TYPES
        ):
            raise ValueError("safe index record invalid")
        record_counts[record["record_type"]] += 1
    if len({record["key_sha256"] for record in records}) != len(records):
        raise ValueError("safe index duplicate key")
    if not _valid_count_map(document.get("record_type_counts"), CATALOG_RECORD_TYPES):
        raise ValueError("safe index record count contract invalid")
    if document["record_type_counts"] != dict(sorted(record_counts.items())):
        raise ValueError("safe index record count mismatch")
    observed_allowed = CATALOG_RECORD_TYPES | (CONTROL_RECORD_TYPES if source == "DEV" else set())
    observed = document.get("source_observed_record_type_counts")
    if not _valid_count_map(observed, observed_allowed):
        raise ValueError("safe index observed count contract invalid")
    if any(observed.get(name) != count for name, count in record_counts.items()):
        raise ValueError("safe index observed catalog mismatch")
    markers = document.get("receipt_marker_counts")
    if not _valid_count_map(markers, ALLOWED_RECEIPT_MARKERS[source]):
        raise ValueError("safe index receipt marker contract invalid")
    if markers.get("BEGIN", 0) > 1 or markers.get("SET", 0) > 5 or markers.get("ROLLBACK", 0) > 1:
        raise ValueError("safe index psql marker count invalid")
    receipt_state = document.get("rollback_receipt_state")
    if source == "DEV":
        if any(observed.get(name) != 1 for name in REQUIRED_DEV_CONTROL_TYPES):
            raise ValueError("safe index DEV control receipt incomplete")
        rollback_echo = markers.get("ROLLBACK_COMPLETED_F1", 0)
        rollback_command = markers.get("ROLLBACK", 0)
        if rollback_echo > 1 or rollback_command > 1 or not (rollback_echo or rollback_command):
            raise ValueError("safe index DEV rollback receipt incomplete")
        expected_state = "F1_ECHO_OBSERVED" if rollback_echo else "PSQL_ROLLBACK_COMMAND_OBSERVED"
        if receipt_state != expected_state:
            raise ValueError("safe index DEV rollback state invalid")
    else:
        if (
            markers.get("REFERENCE_CATALOG_ADAPTER") != 1
            or markers.get("REFERENCE_CATALOG_ROLLBACK_COMPLETED") != 1
            or receipt_state != "REFERENCE_ECHO_OBSERVED"
        ):
            raise ValueError("safe index reference receipt incomplete")
    return document


def _read_trace(path: Path) -> dict[int, dict[str, object]]:
    document = json.loads(path.read_text(encoding="ascii"))
    if (
        document.get("format") != "F1_REFERENCE_STRUCTURAL_TRACE_V1"
        or document.get("migration_count") != 77
        or document.get("postgres_version_num") != 170006
        or not isinstance(document.get("catalog_digest_sha256"), str)
    ):
        raise ValueError("trace contract invalid")
    trace: dict[int, dict[str, object]] = {}
    migrations = document.get("migrations")
    if not isinstance(migrations, list) or len(migrations) != 77:
        raise ValueError("trace migration count invalid")
    for entry in migrations:
        if not isinstance(entry, dict):
            raise ValueError("trace entry invalid")
        position = entry.get("position")
        source_hash = entry.get("migration_sha256")
        keys = entry.get("safe_key_sha256")
        counts = entry.get("record_type_counts")
        if (
            not isinstance(position, int)
            or position in trace
            or not isinstance(source_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", source_hash) is None
            or not isinstance(keys, list)
            or keys != sorted(keys)
            or len(keys) != len(set(keys))
            or any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in keys)
            or not isinstance(counts, dict)
            or any(not isinstance(name, str) or not isinstance(value, int) or value < 0 for name, value in counts.items())
        ):
            raise ValueError("trace entry shape invalid")
        trace[position] = entry
    if set(trace) != set(range(77)):
        raise ValueError("trace positions invalid")
    return trace


def _catalog_entries() -> list[tuple[str, str]]:
    entries = sorted(path for path in MIGRATIONS_DIR.glob("*.sql") if path.is_file())
    if len(entries) != 77:
        raise ValueError("catalog source count invalid")
    return [(path.name, hashlib.sha256(path.read_bytes()).hexdigest()) for path in entries]


def _inventory_entries(catalog_entries: list[tuple[str, str]]) -> list[tuple[str, str, int]]:
    raw = INVENTORY_PATH.read_text(encoding="utf-8")
    names = re.findall(r"(?m)^\|\s*\d+\s*\|\s*`([^`]+\.sql)`", raw)
    if len(names) != 44 or len(names) != len(set(names)):
        raise ValueError("inventory source count invalid")
    catalog_by_name = {name: (position, digest) for position, (name, digest) in enumerate(catalog_entries)}
    entries: list[tuple[str, str, int]] = []
    for number, name in enumerate(names, start=1):
        if name not in catalog_by_name:
            raise ValueError("inventory source missing from catalog")
        position, digest = catalog_by_name[name]
        entries.append((name, digest, position))
    if any(entries[number - 1][0] != name for number, name in INVENTORY_ANCHORS.items()):
        raise ValueError("inventory anchor mismatch")
    return entries


def _render_counts(reference: dict[str, str], dev: dict[str, str], key_types: dict[str, str], keys: list[str]) -> str:
    expected = Counter(key_types[key] for key in keys if key in reference)
    matched = Counter(
        key_types[key]
        for key in keys
        if key in reference and dev.get(key) == reference[key]
    )
    if not expected:
        return "NONE 0/0"
    return "; ".join(f"{name} {matched[name]}/{expected[name]}" for name in sorted(expected))


def _classify(number: int, equality: str, dev_present_count: int) -> str:
    if number in NOT_SCHEMA_DECIDABLE:
        return "NOT_SCHEMA_DECIDABLE"
    if number in PARTIAL:
        return "PARTIAL_OR_CONFLICTING"
    if number in ABSENT:
        return "PHYSICAL_EFFECTS_ABSENT" if dev_present_count == 0 else "PARTIAL_OR_CONFLICTING"
    if equality == "EQUAL":
        return "PHYSICAL_EFFECTS_PRESENT"
    return "PARTIAL_OR_CONFLICTING"


def _canonical_annex(markdown: str) -> str:
    return re.sub(
        r"(?m)^ANNEX_CANONICAL_SHA256=[0-9a-f]{64}$",
        "ANNEX_CANONICAL_SHA256=" + "0" * 64,
        markdown,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev-index", required=True)
    parser.add_argument("--reference-index", required=True)
    parser.add_argument("--trace", required=True)
    args = parser.parse_args()
    try:
        dev_document = _read_index(Path(args.dev_index), "DEV")
        reference_document = _read_index(Path(args.reference_index), "REFERENCE")
        trace = _read_trace(Path(args.trace))
        entries = _inventory_entries(_catalog_entries())
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit("FAIL=REFERENCE_COMPARISON_INPUT") from exc

    dev = {record["key_sha256"]: record["payload_sha256"] for record in dev_document["records"]}
    reference = {record["key_sha256"]: record["payload_sha256"] for record in reference_document["records"]}
    dev_definition = {
        record["key_sha256"]: record["definition_sha256"]
        for record in dev_document["records"]
    }
    reference_definition = {
        record["key_sha256"]: record["definition_sha256"]
        for record in reference_document["records"]
    }
    dev_key_types = {record["key_sha256"]: record["record_type"] for record in dev_document["records"]}
    key_types = {record["key_sha256"]: record["record_type"] for record in reference_document["records"]}
    if any(dev_key_types[key] != key_types[key] for key in dev.keys() & reference.keys()):
        raise SystemExit("FAIL=REFERENCE_TYPE_INDEX")

    rows: list[str] = []
    totals = Counter()
    divergence_totals = Counter()
    for number, (migration_name, migration_hash, position) in enumerate(entries, start=1):
        entry = trace[position]
        if entry["migration_sha256"] != migration_hash:
            raise SystemExit("FAIL=REFERENCE_TRACE_SOURCE_MISMATCH")
        keys = [key for key in entry["safe_key_sha256"] if key in reference]
        missing_from_reference = len(entry["safe_key_sha256"]) - len(keys)
        matched = [key for key in keys if dev.get(key) == reference[key]]
        dev_present = [key for key in keys if key in dev]
        acl_only = [
            key
            for key in keys
            if key in dev
            and dev[key] != reference[key]
            and key_types[key] in ACL_STATE_RECORD_TYPES
            and dev_definition[key] == reference_definition[key]
        ]
        reference_hash = _digest(b"F1-REFERENCE-MIGRATION-v1\0", ((key, reference[key]) for key in keys))
        dev_hash = _digest(b"F1-DEV-MIGRATION-v1\0", ((key, dev.get(key, "ABSENT")) for key in keys))
        equality = (
            "EQUAL"
            if keys and len(matched) == len(keys) and missing_from_reference == 0
            else ("NO_STRUCTURAL_TRACE" if not keys else "DIFFERENT_OR_PARTIAL")
        )
        if equality == "EQUAL":
            divergence = "NONE"
        elif keys and missing_from_reference == 0 and len(matched) + len(acl_only) == len(keys):
            divergence = "ACL_ONLY"
        elif not keys:
            divergence = "NO_STRUCTURAL_TRACE"
        else:
            divergence = "DEFINITION_OR_MISSING_REFERENCE"
        classification = _classify(number, equality, len(dev_present))
        totals[classification] += 1
        divergence_totals[divergence] += 1
        rows.append(
            "| {number} | `{name}` | `{keyset}` | `{reference_hash}` | `{dev_hash}` | "
            "{equality} | `{divergence}` | {counts} | `{classification}` |".format(
                number=number,
                name=migration_name,
                keyset=_digest(b"F1-MIGRATION-KEYSET-v1\0", ((key, "KEY") for key in keys)),
                reference_hash=reference_hash,
                dev_hash=dev_hash,
                equality=equality,
                divergence=divergence,
                counts=_render_counts(reference, dev, key_types, keys),
                classification=classification,
            )
        )

    global_equal = sum(1 for key, payload in reference.items() if dev.get(key) == payload)
    global_missing = sum(1 for key in reference if key not in dev)
    global_different = sum(1 for key, payload in reference.items() if key in dev and dev[key] != payload)
    text = """# Anexo F1, comparação catalográfica DEV x referência PG17

## Método e limite

Este anexo vincula a análise a um replay local, offline e descartável das 77
migrations no SHA base. O replay usa o harness versionado do repositório. A
coleta final executa somente a seção catalográfica do SQL F1 congelado, depois
de provar que os dois ledgers locais de referência estão ausentes. Por isso, o
SQL F1 byte-idêntico não é executado nessa referência: seus guards exigem
`EXPECTED_33` e `EXPECTED_6`, enquanto o harness exige os dois ledgers ausentes
após cada migration. A adaptação local falha fechada se qualquer ledger surgir;
ela não cria, mascara, preenche nem compara ledgers como equivalentes.

O SQL F1 congelado permanece SHA-256 `{sql_sha}` e o agregado F1 congelado
permanece SHA-256 `{aggregate_sha}`. A fonte DEV é a transcrição sanitizada já
verificada, sem cópia dos seus bytes para este repositório. Chave segura é o
SHA-256 de `record_type`, `schema_ref`, `relation_ref`, `object_ref` e ordinal
opaco de ocorrência. O anexo nunca imprime esses componentes, definições,
binding, dado de domínio ou nome/OID de role inesperada.

O índice opaco V3 inclui também `definition_sha256`. Em
`CATALOG_SCHEMA` e `CATALOG_RELATION`, ele normaliza somente `acl_state`; nos
outros record types ele continua a cobrir o payload completo. Assim,
`ACL_ONLY` significa que toda diferença atribuível da linha se restringe a
`acl_state`. Uma diferença desse tipo pode decorrer da execução local versus
o contrato de plataforma Supabase e, isoladamente, não prova drift DEV. Ela
continua conservadoramente parcial porque sua igualdade não é `EQUAL`. Grants
diretos, default ACL, grantee e qualquer outra definição nunca recebem o rótulo
`ACL_ONLY` por essa normalização.

`ANNEX_CANONICAL_SHA256={annex_placeholder}`

## Cobertura global

| Origem | Registros catalográficos opacos | Igualdade de payload | Ausente em DEV | Mesmo key, payload divergente |
| --- | ---: | ---: | ---: | ---: |
| Referência PG17 | `{reference_records}` | `{global_equal}` | `{global_missing}` | `{global_different}` |
| DEV sanitizado | `{dev_records}` | não aplicável | não aplicável | não aplicável |

As contagens globais são comparação de catálogo por chave segura. Não são
comparação de ledger, prova de aplicação nem autorização de epoch, cutover ou
alteração de ambiente.

## Comparação por migration

Em `TIPO a/b`, `a` é a quantidade de chaves com payload DEV idêntico e `b` a
quantidade de chaves estruturais finais da referência atribuídas ao delta local
da migration. `NO_STRUCTURAL_TRACE` é esperado para efeitos só de dados,
reconciliação ou no-op condicional. A classificação final ainda respeita esse
teto: igualdade estrutural não transforma DML em prova de aplicação.

As contagens de auditoria estática já registradas na matriz são uma assinatura
de fonte, não uma substituição desta comparação. Três pontos permanecem
explicitamente separados: o item 5 mantém `REL 3/3` na fonte e tem
`CATALOG_RELATION 0/3` por chave DEV/ref; o item 30 mantém seis alvos
relacionais na fonte e continua não decidível por DML, enquanto o traço só
atribui quatro deltas de metadado relacional; o item 39 mantém `CON 13/13` e
`IDX 11/11` de comandos explícitos. Para este último, o coletor F1 registra
mais três índices de suporte a constraints, por isso a linha catalográfica é
`CATALOG_INDEX 14/14`; helpers `pg_temp` não entram no coletor persistente.

| # | Migration fonte | Chaves seguras SHA-256 | Hash referência | Hash DEV | Igualdade | Natureza da diferença | Contagens por record_type, DEV/ref | Classificação F1 |
| ---: | --- | --- | --- | --- | --- | --- | --- | --- |
{rows}

## Resultado limitado

Distribuição derivada: `PHYSICAL_EFFECTS_PRESENT={present}`,
`PARTIAL_OR_CONFLICTING={partial}`, `PHYSICAL_EFFECTS_ABSENT={absent}` e
`NOT_SCHEMA_DECIDABLE={undecidable}`. O item 5 continua com três relações
estruturais na assinatura fonte, mas não fecha as três chaves de relação contra
DEV. O item 30 preserva `REL 6/6` como escopo fonte e permanece não decidível
por DML. O item 39 preserva 13 constraints e 11 índices explícitos com
`pg_temp` excluído. Os itens 40 a 44 ficam ausentes quando suas chaves de
referência não têm correspondência DEV. ACL pública inesperada continua
`UNRESOLVED`, sem nome ou OID.

Natureza das diferenças: `NONE={no_difference}`, `ACL_ONLY={acl_only}`,
`DEFINITION_OR_MISSING_REFERENCE={definition_or_missing}` e
`NO_STRUCTURAL_TRACE={no_structural_trace}`. `ACL_ONLY` separa o caso limitado
de `acl_state`, mas não altera a classificação conservadora nem transforma a
diferença local versus plataforma em prova de drift DEV.

Este anexo recomenda somente a continuação documental da estratégia A. A opção
B permanece apenas elegível pela declaração humana já recebida e não está
autorizada.
""".format(
        sql_sha=FROZEN_SQL_SHA256,
        aggregate_sha=FROZEN_AGGREGATE_SHA256,
        annex_placeholder="0" * 64,
        reference_records=reference_document["record_count"],
        dev_records=dev_document["record_count"],
        global_equal=global_equal,
        global_missing=global_missing,
        global_different=global_different,
        rows="\n".join(rows),
        present=totals["PHYSICAL_EFFECTS_PRESENT"],
        partial=totals["PARTIAL_OR_CONFLICTING"],
        absent=totals["PHYSICAL_EFFECTS_ABSENT"],
        undecidable=totals["NOT_SCHEMA_DECIDABLE"],
        no_difference=divergence_totals["NONE"],
        acl_only=divergence_totals["ACL_ONLY"],
        definition_or_missing=divergence_totals["DEFINITION_OR_MISSING_REFERENCE"],
        no_structural_trace=divergence_totals["NO_STRUCTURAL_TRACE"],
    )
    canonical_digest = hashlib.sha256(_canonical_annex(text).encode("utf-8")).hexdigest()
    text = text.replace("ANNEX_CANONICAL_SHA256=" + "0" * 64, "ANNEX_CANONICAL_SHA256=" + canonical_digest)
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
