# Manifesto reproduzível do candidato F1

## Binding congelado

| Campo | Valor |
| --- | --- |
| Candidato | `F1_CANDIDATE_FROZEN_RUNBOOK_HISTORY_REMEDIATED_PENDING_LIMITED_OPEN_CODE_AND_CLAUDE_APTO` |
| Base Git | `e1da65d0a6fa5286674f425f855600eb3e4982bb` |
| Branch | `docs/dev-migration-history-remediation-f1-20260915` |
| Diretório permitido | `docs/ops/dev-migration-history-remediation/` |
| Ficha imutável | `docs/missions/M-2026-09-15-dev-migration-history-remediation-catalog-bound.md` |
| SHA-256 da ficha conferido | `1f4528d9bb80962e7366b897bb435ed17d7c604a4f7e8feffc91ce411c4a5725` |
| Candidato anterior revogado | `09eaa414ea222d4bb3c1675d799eba9124f81791c460e2fa5c4c7195b319d306`, `NAO_APTO` conjunto |
| Escopo da próxima conferência | somente `B1`, `B2` e regressão |
| Ambientes acessados pelo agente | `LOCAL_SOURCE_ONLY`, `LOCAL_DISPOSABLE_POSTGRES_17` |
| Ambientes não acessados pelo agente | `DEV`, `VPS`, `PROD` |

`DEV-READONLY-F1.sql` permanece byte idêntico ao candidato anterior, com
SHA-256 `8829decd0f0101329058ad07900ce7b7ca8b1c4fe5695f4e3cec05cff4bf288c`.
A correção altera somente o runbook humano e os campos de integridade deste
manifesto.

Os três campos abaixo são normalizados para 64 caracteres `0` antes do cálculo
dos hashes canônicos. Isso elimina a circularidade do hash do próprio manifesto
sem retirar sua verificação. Nenhum outro byte é normalizado.

```text
PATCH_CANONICAL_SHA256=785b219b5f9473fc012265744b04ea663881b7b1f6524c31aae4cfa11de73034
SELF_CANONICAL_SHA256=127ca9af381e2b6fa86e940130728e42135ffacf0b99d739d8bbad9b00ef8587
AGGREGATE_SHA256=956187b9711ea9d67e9f8fdf31c3980e3ebbf64da98401c275f1dc80d2a91a29
```

## Arquivos F1 e SHA-256

| Arquivo relativo | SHA-256 |
| --- | --- |
| `DEV-READONLY-F1.sql` | `8829decd0f0101329058ad07900ce7b7ca8b1c4fe5695f4e3cec05cff4bf288c` |
| `DIVERGENT-POSITIONS-ANNEX.md` | `3923de834176c1519a79bb3030c4d429905eced421eb4cf0a334ff44c258b7a6` |
| `F1-REPORT.md` | `2ac294c83883da5f29b6c0ac8ba113ddc2358559369e6d63370d632e77ae7bd7` |
| `F1-CANDIDATE-MANIFEST.md` | `SELF_CANONICAL_SHA256` declarado acima |
| `INVENTORY-44.md` | `e6f11d78788d8807cc3c630771d0b7ff477e0698402861b46bb39da22ece2709` |
| `PG17-E2E.sql` | `d41e79626c1dbc4c2eef28fe85639238d637962d9c09983f1f9a66c18098bf0e` |
| `RANIEL-READONLY-RUNBOOK.md` | `c4729a0e585408439313cda89011f22a04112877d4cf89361c3061a49226d58e` |
| `ROLLBACK.md` | `5203fe03a2b9ef107477efa039d786057254e298e0c72a59740d50fff9f63e15` |
| `SANITIZED-RECEIPTS.md` | `2314ed13850fc2bf7447652d7963867f64028baaa50c51adc5833b60aa74eabc` |
| `run-pg17-e2e.sh` | `05f1b67c2fb56d70167d98aeb6e3ca95e244c09b0ad46c0ded9c59cdbbc7f824` |

`SELF_CANONICAL_SHA256` é o SHA-256 de `F1-CANDIDATE-MANIFEST.md` depois da
normalização descrita acima. Os demais valores da tabela são SHA-256 dos bytes
brutos de cada arquivo. O hash de patch usa todos os dez arquivos em ordem
lexicográfica, cada caminho UTF-8 relativo seguido de NUL, dos bytes canônicos
do arquivo e de NUL. O agregado usa os mesmos caminhos em ordem lexicográfica,
o SHA-256 bruto de cada arquivo não manifesto, o hash canônico do manifesto e
um separador de nova linha.

## Verificação reproduzível local

Execute a partir da raiz deste worktree, com Python isolado e sem rede. O bloco
não lê fonte fora deste diretório, não abre banco e não escreve arquivos.

```bash
python3 -I -B - <<'PY'
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

root = Path("docs/ops/dev-migration-history-remediation").resolve()
files = (
    "DEV-READONLY-F1.sql",
    "DIVERGENT-POSITIONS-ANNEX.md",
    "F1-CANDIDATE-MANIFEST.md",
    "F1-REPORT.md",
    "INVENTORY-44.md",
    "PG17-E2E.sql",
    "RANIEL-READONLY-RUNBOOK.md",
    "ROLLBACK.md",
    "SANITIZED-RECEIPTS.md",
    "run-pg17-e2e.sh",
)
manifest_name = "F1-CANDIDATE-MANIFEST.md"
dynamic = re.compile(
    rb"(?m)^(PATCH_CANONICAL_SHA256|SELF_CANONICAL_SHA256|AGGREGATE_SHA256)="
    rb"[0-9a-f]{64}$"
)
declared = re.compile(
    rb"(?m)^(PATCH_CANONICAL_SHA256|SELF_CANONICAL_SHA256|AGGREGATE_SHA256)="
    rb"([0-9a-f]{64})$"
)
table_entry = re.compile(rb"(?m)^\| `([^`]+)` \| `([0-9a-f]{64})` \|$")

raw = {name: (root / name).read_bytes() for name in files}
if tuple(sorted(files)) != files:
    raise SystemExit("FAIL=FILES_NOT_LEXICOGRAPHIC")

def canonical(data: bytes) -> bytes:
    return dynamic.sub(lambda match: match.group(1) + b"=" + b"0" * 64, data)

manifest = raw[manifest_name]
expected = dict(declared.findall(manifest))
if set(expected) != {
    b"PATCH_CANONICAL_SHA256",
    b"SELF_CANONICAL_SHA256",
    b"AGGREGATE_SHA256",
}:
    raise SystemExit("FAIL=MANIFEST_DYNAMIC_FIELDS_INVALID")

actual_files = {
    name: hashlib.sha256(raw[name]).hexdigest()
    for name in files
    if name != manifest_name
}
expected_files = {
    name.decode("utf-8"): digest.decode("ascii")
    for name, digest in table_entry.findall(manifest)
}
for name, digest in actual_files.items():
    if expected_files.get(name) != digest:
        raise SystemExit(f"FAIL=FILE_SHA256_MISMATCH:{name}")

self_canonical = hashlib.sha256(canonical(manifest)).hexdigest()
patch = hashlib.sha256()
patch.update(b"F1-PATCH-CANONICAL-v1\0")
for name in files:
    patch.update(name.encode("utf-8") + b"\0" + canonical(raw[name]) + b"\0")
patch_canonical = patch.hexdigest()

aggregate = hashlib.sha256()
aggregate.update(b"F1-FILE-AGGREGATE-v1\0")
for name in files:
    digest = self_canonical if name == manifest_name else actual_files[name]
    aggregate.update(name.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n")
aggregate_sha256 = aggregate.hexdigest()

expected_values = {
    b"PATCH_CANONICAL_SHA256": patch_canonical.encode("ascii"),
    b"SELF_CANONICAL_SHA256": self_canonical.encode("ascii"),
    b"AGGREGATE_SHA256": aggregate_sha256.encode("ascii"),
}
for field, value in expected_values.items():
    if expected[field] != value:
        raise SystemExit(f"FAIL=DYNAMIC_HASH_MISMATCH:{field.decode('ascii')}")

for name in files:
    digest = self_canonical if name == manifest_name else actual_files[name]
    print(f"FILE_SHA256 {name} {digest}")
print(f"PATCH_CANONICAL_SHA256={patch_canonical}")
print(f"SELF_CANONICAL_SHA256={self_canonical}")
print(f"AGGREGATE_SHA256={aggregate_sha256}")
print("RESULT=PASS_F1_MANIFEST_REPRODUCIBLE")
PY
```

Um resultado positivo prova somente a integridade dos bytes listados e seu
vínculo com a base declarada. Ele não prova estado DEV, identidade do alvo,
aplicação de migration, autorização, deploy, dados ou ambiente compartilhado.
