# Manifesto reproduzível, F2 PROD shape diagnostic v2

## Vínculo e limites

| Campo | Valor |
| --- | --- |
| Ficha vinculada, não coberta por este conjunto | `docs/missions/M-2026-09-16-f2-prod-shape-diagnostic-v2.md` |
| SHA-256 atual da ficha | `b8b24dd707f737ba41fcabf94ddb0db341778678a08db1f35ca7bbeb1333a222` |
| Base e HEAD local | `f856f53f48e79a53609ff699d5603119f60202e0` |
| Branch | `docs/dev-migration-history-remediation-f2-readonly-20260915` |
| Diretório fechado | `docs/ops/dev-migration-history-remediation/f2-prod-shape-diagnostic-v2/` |
| Ambiente exercitado | PostgreSQL `17.6` local descartável, `--pull=never`, `--network none`, nenhuma porta publicada |
| Resultado E2E | `PASS_PG17_F2_PROD_DIAG_V2` |
| Ambientes vivos acessados | `NENHUM` |
| Estado operacional | candidato local, sem commit, push, coleta PROD ou DEV |

O conjunto contém somente os quatro arquivos desta missão. O SQL relata a
forma dos dois ledgers canônicos e não trata drift como abortamento. O E2E
exercita presença e ausência pública, cardinalidade distinta, coluna extra,
tipo e nulabilidade alterados, trigger e rule inesperados, opacidade, digest,
teto, recibo terminal, encerramento autocontido do `psql` e rollback. O teste
local não prova identidade de PROD, causa de drift, migration aplicada ou
autorização humana para uma sessão viva.

```text
PATCH_CANONICAL_SHA256=9c1c4e82848429fe752af5b776624a3300db2ba4b6e08546e8ca8f23a8f64031
SELF_CANONICAL_SHA256=26ed988a45d3976a37a8ddca391cef5ef075d79eac953e33bcd1150f8af1abec
AGGREGATE_SHA256=7423b33d648c2b207f9dd79b9d48ee5bd31b2c21ecb9d2fac7dfaaa092fa3b24
```

## Arquivos cobertos

| Arquivo relativo | SHA-256 |
| --- | --- |
| `F2-PROD-DIAG-v2-CANDIDATE-MANIFEST.md` | `SELF_CANONICAL_SHA256` |
| `PROD-READONLY-F2-DIAG-v2.sql` | `adadffddce30e6f1ac55bc78934c1cf89a2fd7f53eae576d6b8b4d4edfb88135` |
| `RANIEL-PROD-DIAG-v2-RUNBOOK.md` | `bcbe7d1ff19cd18350ac8e5c7d84aa597e4e39d05aa220cb8d20b9a67dae9e95` |
| `run-pg17-f2-prod-diag-v2-e2e.sh` | `18e41290d88ed4786e7070f9d81074b0ff3ef4f73344186e7ba43bc6ef83969f` |

Os três campos dinâmicos são normalizados para 64 caracteres `0` no cálculo
canônico. O patch vincula caminho UTF-8, NUL, bytes canônicos e NUL dos quatro
arquivos ordenados. O agregado vincula caminho UTF-8 e hash bruto, usando o
hash canônico deste manifesto para ele próprio.

## Reprodução local

Execute da raiz da worktree. O primeiro comando não abre banco ou rede; o
segundo exige Docker local com a imagem PG17.6 já disponível e falha com estado
`BLOCKED`, nunca com skip, se o requisito local não existir.

```bash
python3 -I -B - <<'PY'
from __future__ import annotations

import hashlib
import re
from pathlib import Path

root = Path('docs/ops/dev-migration-history-remediation/f2-prod-shape-diagnostic-v2').resolve()
files = (
    'F2-PROD-DIAG-v2-CANDIDATE-MANIFEST.md',
    'PROD-READONLY-F2-DIAG-v2.sql',
    'RANIEL-PROD-DIAG-v2-RUNBOOK.md',
    'run-pg17-f2-prod-diag-v2-e2e.sh',
)
manifest_name = 'F2-PROD-DIAG-v2-CANDIDATE-MANIFEST.md'
mission = Path('docs/missions/M-2026-09-16-f2-prod-shape-diagnostic-v2.md')
mission_sha256 = 'b8b24dd707f737ba41fcabf94ddb0db341778678a08db1f35ca7bbeb1333a222'
dynamic = re.compile(
    rb'(?m)^(PATCH_CANONICAL_SHA256|SELF_CANONICAL_SHA256|AGGREGATE_SHA256)='
    rb'[0-9a-f]{64}$'
)
declared = re.compile(
    rb'(?m)^(PATCH_CANONICAL_SHA256|SELF_CANONICAL_SHA256|AGGREGATE_SHA256)='
    rb'([0-9a-f]{64})$'
)
table_entry = re.compile(rb'(?m)^\| `([^`]+)` \| `([0-9a-f]{64})` \|$')
if files != tuple(sorted(files)):
    raise SystemExit('FAIL=F2_DIAG_FILES_NOT_LEXICOGRAPHIC')
if tuple(sorted(path.name for path in root.iterdir() if path.is_file())) != files:
    raise SystemExit('FAIL=F2_DIAG_FILE_SET_MISMATCH')
if not mission.is_file() or hashlib.sha256(mission.read_bytes()).hexdigest() != mission_sha256:
    raise SystemExit('FAIL=F2_DIAG_MISSION_BINDING_MISMATCH')
raw = {name: (root / name).read_bytes() for name in files}
def canonical(data: bytes) -> bytes:
    return dynamic.sub(lambda match: match.group(1) + b'=' + b'0' * 64, data)
manifest = raw[manifest_name]
expected = dict(declared.findall(manifest))
if set(expected) != {
    b'PATCH_CANONICAL_SHA256',
    b'SELF_CANONICAL_SHA256',
    b'AGGREGATE_SHA256',
}:
    raise SystemExit('FAIL=F2_DIAG_DYNAMIC_FIELDS_INVALID')
actual_files = {
    name: hashlib.sha256(raw[name]).hexdigest()
    for name in files
    if name != manifest_name
}
expected_files = {
    name.decode('utf-8'): digest.decode('ascii')
    for name, digest in table_entry.findall(manifest)
    if name.decode('utf-8') in actual_files
}
if expected_files != actual_files:
    raise SystemExit('FAIL=F2_DIAG_FILE_SHA256_MISMATCH')
self_canonical = hashlib.sha256(canonical(manifest)).hexdigest()
patch = hashlib.sha256()
patch.update(b'F2-PROD-DIAG-v2-PATCH-CANONICAL-v1\0')
for name in files:
    patch.update(name.encode('utf-8') + b'\0' + canonical(raw[name]) + b'\0')
patch_canonical = patch.hexdigest()
aggregate = hashlib.sha256()
aggregate.update(b'F2-PROD-DIAG-v2-FILE-AGGREGATE-v1\0')
for name in files:
    digest = self_canonical if name == manifest_name else actual_files[name]
    aggregate.update(name.encode('utf-8') + b'\0' + digest.encode('ascii') + b'\n')
aggregate_sha256 = aggregate.hexdigest()
actual = {
    b'PATCH_CANONICAL_SHA256': patch_canonical.encode('ascii'),
    b'SELF_CANONICAL_SHA256': self_canonical.encode('ascii'),
    b'AGGREGATE_SHA256': aggregate_sha256.encode('ascii'),
}
if expected != actual:
    raise SystemExit('FAIL=F2_DIAG_DYNAMIC_HASH_MISMATCH')
for name in files:
    digest = self_canonical if name == manifest_name else actual_files[name]
    print(f'FILE_SHA256 {name} {digest}')
print(f'PATCH_CANONICAL_SHA256={patch_canonical}')
print(f'SELF_CANONICAL_SHA256={self_canonical}')
print(f'AGGREGATE_SHA256={aggregate_sha256}')
print('RESULT=PASS_F2_PROD_DIAG_V2_MANIFEST_REPRODUCIBLE')
PY

bash docs/ops/dev-migration-history-remediation/f2-prod-shape-diagnostic-v2/run-pg17-f2-prod-diag-v2-e2e.sh
```

O próximo gate permanece um único parecer conjunto de OpenCode e CLAUDE sobre
estes hashes exatos. O parecer não autoriza comparação, inferência causal,
escrita, aplicação, DEV ou repetição de uma coleta PROD interrompida.
