# Manifesto do candidato, briefing PROD coorte A

## Escopo fechado

Este manifesto cobre exatamente nove arquivos: a ficha e os oito arquivos do
pacote. Capturas externas, derivador, JSON, ambiente vivo, credenciais e
qualquer resultado de coleta ficam fora do conjunto.

| Campo | Valor |
| --- | --- |
| Base e HEAD local | `18ecd50472a309de3ac838f898f3a6ade9ff763d` |
| Branch | `docs/f2-prod-cohort-a-identity-readonly-20260917` |
| Estado | briefing local, SQL e runner propostos e não executados |
| Gate único | `OWNER_AUTHORIZE_PROD_UNMATCHED_IDENTITY_EVIDENCE_READ_ONLY` |

Os três campos abaixo são substituídos por 64 zeros no cálculo canônico:

```text
PATCH_CANONICAL_SHA256=82c0698f87e323c9cc83f56d84141283052b724a6488cfac706801d6d30d294c
SELF_CANONICAL_SHA256=67d11cb783a008a704b7533d0738b9ce4b42a95a0161ddbcafc27c2a4a83872d
AGGREGATE_SHA256=1b8e3e834506375465f4ebdb1591873d8219fbb10a27efd390a112689dcda432
```

## Arquivos cobertos

| Arquivo relativo | SHA-256 |
| --- | --- |
| `docs/missions/M-2026-09-17-f2-prod-cohort-a-identity-readonly.md` | `e4e5a4d5ecbbe4472554fc8ab3b1e0a0b00c41b0f4629b43a85c05fa70901185` |
| `docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/BRIEFING.md` | `88c4a1816846fdf69f8243f81cf5ee9741f47834d3e0cd22c7b31a49e5466dad` |
| `docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/CANDIDATE-MANIFEST.md` | `SELF_CANONICAL_SHA256` |
| `docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/EVIDENCE-CONTRACT.md` | `876f28257c2e8f447df9f763ff379dfa5c078bccd79d1fb0b81848e84bede792` |
| `docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/PROD-READONLY-F2-COHORT-A.sql` | `84898a80b53c41e3dbaf6b68bea2911a99116ccbf48e6f4f05eed6562c9ba7e7` |
| `docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/RANIEL-PROD-COHORT-A-RUNBOOK.md` | `5fca28eab12fd6157aa296e2af5c21126bb081af1fa06458e85b10731a371cb7` |
| `docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/SOURCE-PINS.md` | `c4ce335e33c27d915f2462a04ec3535d4ec514c6ca91c5c3a888668d245f5f85` |
| `docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/run-pg17-f2-prod-cohort-a-e2e.sh` | `b8d0249c9eb321c414f3f9fc316fb9c19305451d1279677eb6ec22f8cdbafbf0` |
| `docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/test_validate_f2_prod_cohort_a_package.py` | `b84a25a2f858ffb5055fca67047ada6c556bc85bdb9d67df4d6d30d3f8ac10c8` |

## Reprodutor autocanônico

Execute da raiz da worktree. Ele lê somente os nove arquivos versionáveis e não
abre rede, banco ou fonte externa.

```bash
python3 -I -B - <<'PY'
from __future__ import annotations

import hashlib
import re
from pathlib import Path

files = (
    'docs/missions/M-2026-09-17-f2-prod-cohort-a-identity-readonly.md',
    'docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/BRIEFING.md',
    'docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/CANDIDATE-MANIFEST.md',
    'docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/EVIDENCE-CONTRACT.md',
    'docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/PROD-READONLY-F2-COHORT-A.sql',
    'docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/RANIEL-PROD-COHORT-A-RUNBOOK.md',
    'docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/SOURCE-PINS.md',
    'docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/run-pg17-f2-prod-cohort-a-e2e.sh',
    'docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/test_validate_f2_prod_cohort_a_package.py',
)
manifest_name = 'docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/CANDIDATE-MANIFEST.md'
package_dir = Path('docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly')
expected_package_files = (
    'BRIEFING.md',
    'CANDIDATE-MANIFEST.md',
    'EVIDENCE-CONTRACT.md',
    'PROD-READONLY-F2-COHORT-A.sql',
    'RANIEL-PROD-COHORT-A-RUNBOOK.md',
    'SOURCE-PINS.md',
    'run-pg17-f2-prod-cohort-a-e2e.sh',
    'test_validate_f2_prod_cohort_a_package.py',
)
mission = Path('docs/missions/M-2026-09-17-f2-prod-cohort-a-identity-readonly.md')
mission_sha256 = 'e4e5a4d5ecbbe4472554fc8ab3b1e0a0b00c41b0f4629b43a85c05fa70901185'
dynamic = re.compile(
    rb'(?m)^(PATCH_CANONICAL_SHA256|SELF_CANONICAL_SHA256|AGGREGATE_SHA256)='
    rb'[0-9a-f]{64}$'
)
declared = re.compile(
    rb'(?m)^(PATCH_CANONICAL_SHA256|SELF_CANONICAL_SHA256|AGGREGATE_SHA256)='
    rb'([0-9a-f]{64})$'
)
table_entry = re.compile(rb'(?m)^\| \`([^\`]+)\` \| \`([0-9a-f]{64})\` \|$')

if files != tuple(sorted(files)):
    raise SystemExit('RESULT=FAIL_F2_PROD_COHORT_A_MANIFEST_ORDER')
if tuple(sorted(path.name for path in package_dir.iterdir() if path.is_file())) != expected_package_files:
    raise SystemExit('RESULT=FAIL_F2_PROD_COHORT_A_MANIFEST_SCOPE')
if hashlib.sha256(mission.read_bytes()).hexdigest() != mission_sha256:
    raise SystemExit('RESULT=FAIL_F2_PROD_COHORT_A_MISSION_SHA256')

raw = {name: Path(name).read_bytes() for name in files}
def canonical(name: str, data: bytes) -> bytes:
    if name != manifest_name:
        return data
    return dynamic.sub(lambda match: match.group(1) + b'=' + b'0' * 64, data)

manifest = raw[manifest_name]
matches = declared.findall(manifest)
expected = dict(matches)
if len(matches) != 3 or set(expected) != {
    b'PATCH_CANONICAL_SHA256',
    b'SELF_CANONICAL_SHA256',
    b'AGGREGATE_SHA256',
}:
    raise SystemExit('RESULT=FAIL_F2_PROD_COHORT_A_MANIFEST_FIELDS')

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
    raise SystemExit('RESULT=FAIL_F2_PROD_COHORT_A_FILE_SHA256')

self_canonical = hashlib.sha256(canonical(manifest_name, manifest)).hexdigest()
patch = hashlib.sha256()
patch.update(b'F2-PROD-COHORT-A-PATCH-CANONICAL-v1\0')
for name in files:
    patch.update(name.encode('utf-8') + b'\0' + canonical(name, raw[name]) + b'\0')
patch_canonical = patch.hexdigest()

aggregate = hashlib.sha256()
aggregate.update(b'F2-PROD-COHORT-A-FILE-AGGREGATE-v1\0')
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
    raise SystemExit('RESULT=FAIL_F2_PROD_COHORT_A_DYNAMIC_SHA256')
for name in files:
    digest = self_canonical if name == manifest_name else actual_files[name]
    print('FILE_SHA256 ' + name + ' ' + digest)
print('PATCH_CANONICAL_SHA256=' + patch_canonical)
print('SELF_CANONICAL_SHA256=' + self_canonical)
print('AGGREGATE_SHA256=' + aggregate_sha256)
print('RESULT=PASS_F2_PROD_COHORT_A_MANIFEST_REPRODUCIBLE')
PY
```

## Limite

Este manifesto não autoriza coleta. O único próximo gate humano é
`OWNER_AUTHORIZE_PROD_UNMATCHED_IDENTITY_EVIDENCE_READ_ONLY`.
