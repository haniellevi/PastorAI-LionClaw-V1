# Manifesto reproduzível, F2 epoch e cutover offline

## Escopo fechado

Este manifesto cobre exatamente os sete arquivos deste diretório. Ele não cobre
ficha, captura externa, JSON privado, ambiente vivo, executor ou ledger. O
pacote é documental, local e bloqueado para operação.

| Campo | Valor |
| --- | --- |
| Pino fonte da derivação | `de1ea1e659be9a4f2a988740b72a9ed8edd68bfb` |
| Branch | `docs/f2-epoch-cutover-design-20260916` |
| Catálogo top-level | `77` arquivos `.sql` |
| Digest de basenames | `950bde59ce2b65b4596a6ca9ecf284a85aa18ba49dba9b8cac6913004b8fa415` |
| Árvore de migrations | `ff84b1274a342ea47e1e378446ed72caa27cef4b` |
| Estado | publicado no PR #403; sem banco, DEV, PROD, VPS, executor ou materialização |

A autocanonização substitui somente os três valores dinâmicos abaixo por `64`
zeros. Todos os outros bytes dos sete arquivos participam dos cálculos.

```text
PATCH_CANONICAL_SHA256=0b3c53eca0b7dc49e0f5826c1753de46297efcf3f9d78aec643ce6e461511672
SELF_CANONICAL_SHA256=1b1d5a606b0e5f01a2e0c556e2980e1616264fd2df9e7107427a10bb6877a1e2
AGGREGATE_SHA256=81bd86340a764e48b8947e5bcb4182b0a510e29e0edb9b822d1b205fd0715b14
```

## Arquivos cobertos

| Arquivo relativo | SHA-256 |
| --- | --- |
| `CANDIDATE-MANIFEST.md` | `SELF_CANONICAL_SHA256` |
| `CUTOVER-ROLLBACK-CONTRACT.md` | `bedbb53e9bceb05587e28fbc0b02048c6b26ed81e1b45b31ea8a62f6f1cf32b9` |
| `DECISION-PACKET.md` | `989bfd3cdc2fc900a03d47fe6b511afd471d06ca68daeaf4a45645a40a4343d1` |
| `EPOCH-TRUST-ANCHORS.md` | `5eb5c91f16d6f5b32751daf7d45a12f56f6b710c9db99f8a7ebf8cd821196cba` |
| `NON-DERIVABLE-CATALOG-INVENTORY.md` | `0f6a665ad4bea211c1925676bc34ae627e2ea99018e27d5bed33c6893c388c2c` |
| `PROD-UNMATCHED-EVIDENCE-MATRIX.md` | `8f2a787f019f2b1db76f5e5a06dfd2da280d19618fc031932825759033f65273` |
| `REPRODUCIBILITY-RECIPES.md` | `84e6a7378f9eb063434a5b2642075bb21c721b814fd9eb4f4cd3810c7327a802` |

`PATCH_CANONICAL_SHA256` vincula os caminhos ordenados, NUL e bytes canônicos.
`SELF_CANONICAL_SHA256` é o hash do manifesto após normalização. O agregado
vincula cada caminho ao hash bruto, usando o self canônico para o manifesto.

## Recibo da rodada corretiva pós-publicação

O parecer anterior ligado ao patch
`6968c9781870db19d3fb0773ea099368cf380915b7abaf8e9d1b01b51c083fc2`
e ao agregado
`8781afa8acd4ada75969d32b481c21d9c7a7bf583250b58b68e62579b0d580a9`
fica `SUPERSEDED` pela mudança de bytes desta rodada. A nova conferência conjunta
vincula-se somente aos hashes regenerados abaixo.

A rodada corrige as três threads do PR #403: autenticação fail-closed da
captura, do derivador e do snapshot pinado antes da derivação; criação ou
rejeição segura da saída conforme modo `0600`; e reconciliação do gate vigente
nos oito arquivos. A ficha permanece fora do conjunto autocanônico dos sete
documentos e foi conferida separadamente:

```text
FICHA_SHA256=c0d73d5a8e9d1972b68f9c002845605fdd931290430922842a80894356baa705
```

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

Esta regeneração vincula a receita nova SHA-256 `84e6a7378f9eb063434a5b2642075bb21c721b814fd9eb4f4cd3810c7327a802`. O APTO e a publicação do PR #403 referem-se aos bytes anteriores e não são transportados. O patch `892d66d56d7d4609a1a5bd51953e2b7c1d1646998ad6a568b18475cde13eb612` e o commit `d1aad87edc54aac8c9bcf311e903caeeec6c297f` ficam `SUPERSEDED` nesta rodada. Os bytes novos foram conferidos por OpenCode+QWEN na missão DEV epoch PR #404 antes da publicação, sendo essa a origem do APTO. O merge continua retido.
