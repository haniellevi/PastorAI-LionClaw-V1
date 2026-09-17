# Manifesto do candidato, F2 epoch DEV offline

## Escopo fechado

Este manifesto cobre exatamente os dez arquivos alterados: a ficha, os sete
arquivos novos do diretório `f2-dev-epoch-design` e os dois artefatos legados
vinculados. Captura externa, ambiente vivo, ledger, executor e SQL ficam fora
do conjunto.

| Campo | Valor |
| --- | --- |
| Base e HEAD | `48c57f7bca780b652bf16c096f4d1859918018c9` |
| Branch | `docs/f2-dev-epoch-design-20260917` |
| SHA-256 da ficha, incluída no agregado | `d0426e62b37450aa14c46a33a8e950901e1bc3cbae69d432cdfc51e2f9205c7d` |
| Fonte DEV aceita | `18d2e78ffc16d26f20f1e58459969c9c3bcc5cf58896c33c6225daedd01f6cb9` |
| Estado | candidato documental local, sem ambiente vivo ou materialização |

Os três campos dinâmicos abaixo são substituídos por `64` zeros para o cálculo
canônico. Nenhum outro byte é normalizado.

```text
PATCH_CANONICAL_SHA256=422f3e0debb13691f11d338765678a6e9d655faf1a4c3cf6ab8049e9b95c2447
SELF_CANONICAL_SHA256=509b2456eeea8ba0ed5276e4af6daf4b56897e01f3288d679c8b8a28b7db4ac7
AGGREGATE_SHA256=7aead4d3f03822714db29e415b772628be39d7c15212559f2f759274b0532dec
```

## Arquivos cobertos

| Arquivo relativo | SHA-256 |
| --- | --- |
| `docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md` | `d0426e62b37450aa14c46a33a8e950901e1bc3cbae69d432cdfc51e2f9205c7d` |
| `docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/CANDIDATE-MANIFEST.md` | `SELF_CANONICAL_SHA256` |
| `docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/DECISION-PACKET.md` | `3b2e2621ef52da4a6d63ad5d61d184e756f7ba518d3f4f2b007e5f1ff95180d2` |
| `docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/DEV-EPOCH-TRUST-ANCHORS.md` | `a1007c6c87899684e106e944821b26bae93131e4759c900e0fd40ed859696fa7` |
| `docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/FINAL-REPORT.md` | `2e61c4fbed70d223a646cff3f856fd620011d9c7c5d4209a78827f35f7cd1dd3` |
| `docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/MATERIALIZABILITY-GAPS.md` | `82f37336bf384a2a7501866099802d83c03f99f30b7d09ab2d67f9da9d5de087` |
| `docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/NO-IMPORT-CONTRACT.md` | `426e97993ae1f628f26a7c4e138053f686a813c931e91313ebc0667457f44773` |
| `docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/SOURCE-CONFERENCE.md` | `8765901b72d6593bbc365b92ffd45b06ac826d9fb7af7730c2dd09e0a7dce6a7` |
| `docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/CANDIDATE-MANIFEST.md` | `fced634c3ec78c8d4ddd87caf55de56ed18379d3e17ee09c6faffb3ec1f5e44b` |
| `docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/REPRODUCIBILITY-RECIPES.md` | `84e6a7378f9eb063434a5b2642075bb21c721b814fd9eb4f4cd3810c7327a802` |

`PATCH_CANONICAL_SHA256` vincula caminho ordenado, NUL e bytes canônicos.
`SELF_CANONICAL_SHA256` é o hash do manifesto normalizado. O agregado vincula
cada caminho ao hash bruto, usando o self canônico para este manifesto. A
ficha e os dois artefatos legados entram como bytes cobertos, sem ampliar o
escopo operacional desta missão.

## Reprodutor autocanônico

Execute da raiz da worktree. O bloco não abre captura, rede, banco ou ambiente
vivo.

```bash
python3 -I -B - <<'PY'
from __future__ import annotations

import hashlib
import re
from pathlib import Path

files = (
    'docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md',
    'docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/CANDIDATE-MANIFEST.md',
    'docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/DECISION-PACKET.md',
    'docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/DEV-EPOCH-TRUST-ANCHORS.md',
    'docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/FINAL-REPORT.md',
    'docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/MATERIALIZABILITY-GAPS.md',
    'docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/NO-IMPORT-CONTRACT.md',
    'docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/SOURCE-CONFERENCE.md',
    'docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/CANDIDATE-MANIFEST.md',
    'docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design/REPRODUCIBILITY-RECIPES.md',
)
manifest_name = 'docs/ops/dev-migration-history-remediation/f2-dev-epoch-design/CANDIDATE-MANIFEST.md'
package_dir = Path('docs/ops/dev-migration-history-remediation/f2-dev-epoch-design')
expected_package_files = (
    'CANDIDATE-MANIFEST.md',
    'DECISION-PACKET.md',
    'DEV-EPOCH-TRUST-ANCHORS.md',
    'FINAL-REPORT.md',
    'MATERIALIZABILITY-GAPS.md',
    'NO-IMPORT-CONTRACT.md',
    'SOURCE-CONFERENCE.md',
)
mission = Path('docs/missions/M-2026-09-17-f2-dev-epoch-design-offline.md')
mission_sha256 = 'd0426e62b37450aa14c46a33a8e950901e1bc3cbae69d432cdfc51e2f9205c7d'
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
    raise SystemExit('RESULT=FAIL_F2_DEV_EPOCH_MANIFEST_ORDER')
if tuple(sorted(path.name for path in package_dir.iterdir() if path.is_file())) != expected_package_files:
    raise SystemExit('RESULT=FAIL_F2_DEV_EPOCH_MANIFEST_SCOPE')
if hashlib.sha256(mission.read_bytes()).hexdigest() != mission_sha256:
    raise SystemExit('RESULT=FAIL_F2_DEV_EPOCH_MISSION_SHA256')
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
    raise SystemExit('RESULT=FAIL_F2_DEV_EPOCH_MANIFEST_FIELDS')
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
    raise SystemExit('RESULT=FAIL_F2_DEV_EPOCH_MANIFEST_FILE_SHA256')
self_canonical = hashlib.sha256(canonical(manifest_name, manifest)).hexdigest()
patch = hashlib.sha256()
patch.update(b'F2-DEV-EPOCH-DESIGN-PATCH-CANONICAL-v1\0')
for name in files:
    patch.update(name.encode('utf-8') + b'\0' + canonical(name, raw[name]) + b'\0')
patch_canonical = patch.hexdigest()
aggregate = hashlib.sha256()
aggregate.update(b'F2-DEV-EPOCH-DESIGN-FILE-AGGREGATE-v1\0')
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
    raise SystemExit('RESULT=FAIL_F2_DEV_EPOCH_MANIFEST_DYNAMIC_SHA256')
for name in files:
    digest = self_canonical if name == manifest_name else actual_files[name]
    print('FILE_SHA256 ' + name + ' ' + digest)
print('PATCH_CANONICAL_SHA256=' + patch_canonical)
print('SELF_CANONICAL_SHA256=' + self_canonical)
print('AGGREGATE_SHA256=' + aggregate_sha256)
print('RESULT=PASS_F2_DEV_EPOCH_MANIFEST_REPRODUCIBLE')
PY
```

## Referência de continuidade

A decisão e a única autorização humana futura estão definidas em
`DECISION-PACKET.md`. Este manifesto não materializa epoch, não reclassifica
fontes e não amplia o escopo operacional.
