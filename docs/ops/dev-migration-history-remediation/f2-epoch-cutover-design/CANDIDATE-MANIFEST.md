# Manifesto reproduzível, F2 epoch e cutover offline

## Escopo fechado

Este manifesto cobre exatamente os sete arquivos deste diretório. Ele não cobre
ficha, captura externa, JSON privado, ambiente vivo, executor ou ledger. O
pacote é documental, local e bloqueado para operação.

| Campo | Valor |
| --- | --- |
| Base e HEAD local | `de1ea1e659be9a4f2a988740b72a9ed8edd68bfb` |
| Branch | `docs/f2-epoch-cutover-design-20260916` |
| Catálogo top-level | `77` arquivos `.sql` |
| Digest de basenames | `950bde59ce2b65b4596a6ca9ecf284a85aa18ba49dba9b8cac6913004b8fa415` |
| Árvore de migrations | `ff84b1274a342ea47e1e378446ed72caa27cef4b` |
| Estado | candidato documental, sem banco, rede, DEV, PROD, VPS, executor ou materialização |

A autocanonização substitui somente os três valores dinâmicos abaixo por `64`
zeros. Todos os outros bytes dos sete arquivos participam dos cálculos.

```text
PATCH_CANONICAL_SHA256=a912d92aad925599985d1e7fc0646e18fc96f4b5e02b20b4af5d3b2dce68c918
SELF_CANONICAL_SHA256=1f26c5d1fb49014d2d59eed5d5aadcac83b38d6acb925e90ce68d3266b762590
AGGREGATE_SHA256=8781afa8acd4ada75969d32b481c21d9c7a7bf583250b58b68e62579b0d580a9
```

## Arquivos cobertos

| Arquivo relativo | SHA-256 |
| --- | --- |
| `CANDIDATE-MANIFEST.md` | `SELF_CANONICAL_SHA256` |
| `CUTOVER-ROLLBACK-CONTRACT.md` | `e77e9606a5902724bba3e4257c95a55cd70a9361f719e58321be795b9683f002` |
| `DECISION-PACKET.md` | `c8558ef461552892d069219f5217b10b5721ac134948a097ffde0ca2b8d42b02` |
| `EPOCH-TRUST-ANCHORS.md` | `9eb6898b986cd088ebd68bb7e7275830e9b25f21da9f4f5fb2faec7797055b9d` |
| `NON-DERIVABLE-CATALOG-INVENTORY.md` | `9b677feb4549b8562108a48810b580d0911b634b1b248ad6e421b3ccb07e0c46` |
| `PROD-UNMATCHED-EVIDENCE-MATRIX.md` | `369b814b8efbcd51e376f1196ca35fc8bb5e9d3183582b0e03f7b5ff5bbb75f8` |
| `REPRODUCIBILITY-RECIPES.md` | `65ec8498ba6e47bc89ac8a157e4318fc0ebd04f806de64e1fcbc69868e010e29` |

`PATCH_CANONICAL_SHA256` vincula os caminhos ordenados, NUL e bytes canônicos.
`SELF_CANONICAL_SHA256` é o hash do manifesto após normalização. O agregado
vincula cada caminho ao hash bruto, usando o self canônico para o manifesto.

## Reprodutor autocanônico

Execute da raiz da worktree. O bloco não abre banco, rede, captura ou ambiente
vivo.

```bash
python3 -I -B - <<'PY'
from __future__ import annotations

import hashlib
import re
from pathlib import Path

root = Path('docs/ops/dev-migration-history-remediation/f2-epoch-cutover-design').resolve()
files = (
    'CANDIDATE-MANIFEST.md',
    'CUTOVER-ROLLBACK-CONTRACT.md',
    'DECISION-PACKET.md',
    'EPOCH-TRUST-ANCHORS.md',
    'NON-DERIVABLE-CATALOG-INVENTORY.md',
    'PROD-UNMATCHED-EVIDENCE-MATRIX.md',
    'REPRODUCIBILITY-RECIPES.md',
)
manifest_name = 'CANDIDATE-MANIFEST.md'
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
    raise SystemExit('RESULT=FAIL_F2_EPOCH_MANIFEST')
if tuple(sorted(path.name for path in root.iterdir() if path.is_file())) != files:
    raise SystemExit('RESULT=FAIL_F2_EPOCH_MANIFEST')
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
    raise SystemExit('RESULT=FAIL_F2_EPOCH_MANIFEST')
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
    raise SystemExit('RESULT=FAIL_F2_EPOCH_MANIFEST')
self_canonical = hashlib.sha256(canonical(manifest)).hexdigest()
patch = hashlib.sha256()
patch.update(b'F2-EPOCH-CUTOVER-DESIGN-PATCH-CANONICAL-v1\0')
for name in files:
    patch.update(name.encode('utf-8') + b'\0' + canonical(raw[name]) + b'\0')
patch_canonical = patch.hexdigest()
aggregate = hashlib.sha256()
aggregate.update(b'F2-EPOCH-CUTOVER-DESIGN-FILE-AGGREGATE-v1\0')
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
    raise SystemExit('RESULT=FAIL_F2_EPOCH_MANIFEST')
print('RESULT=PASS_F2_EPOCH_MANIFEST_REPRODUCIBLE')
print('PATCH_CANONICAL_SHA256=' + patch_canonical)
print('SELF_CANONICAL_SHA256=' + self_canonical)
print('AGGREGATE_SHA256=' + aggregate_sha256)
PY
```

## Próximo gate único

O único próximo gate é parecer `APTO` conjunto de OpenCode e QWEN 3.8 FLASH
sobre estes bytes exatos. Commit, push, PR, merge e qualquer fase executável
permanecem retidos.
