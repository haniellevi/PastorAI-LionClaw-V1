# Manifesto reproduzível da análise F1

## Binding da análise

| Campo | Valor |
| --- | --- |
| Base Git | `e1da65d0a6fa5286674f425f855600eb3e4982bb` |
| Branch | `docs/dev-migration-history-remediation-f1-20260915` |
| Diretório desta análise | `docs/ops/dev-migration-history-remediation/f1-analysis/` |
| Evidência externa somente leitura | SHA-256 `b1c3e1bda63b55e7c5496d318bcf039d9a4d130de60ced535d918be233313e1b`, modo `0600`, coleta `2026-09-15T11:18:39-03:00` |
| SQL F1 congelado, não coberto por este manifesto | `8829decd0f0101329058ad07900ce7b7ca8b1c4fe5695f4e3cec05cff4bf288c` |
| Agregado F1 congelado, não coberto por este manifesto | `956187b9711ea9d67e9f8fdf31c3980e3ebbf64da98401c275f1dc80d2a91a29` |
| Declaração humana separada | `DEV_DATA_DISPOSITION=NO_VALUE_NO_PII` |
| Referência descartável | PostgreSQL `17.6`, imagem local SHA-256 `00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929`, `--pull=never`, `--network none`, sem porta publicada |
| Resultado local | Replay oficial `77/77`, traço `77/77`, banco de traço recriado via banco `postgres`, contrato fresh validado, coleta opaca e rollback de referência concluídos |
| Parser e pré-validação sintéticos | `5/5` aprovados: DEV/REFERENCE válidos, record type com pipe desconhecido, marker sem pipe desconhecido, SHA incorreto e modo `0644`, sem emissão de canário |
| E2E F1 congelado | `RESULT=PASS_PG17_E2E_F1_B1_B2_AND_REGRESSION` em PostgreSQL 17.6 local descartável |
| Guarda de privacidade | `13/13` em `backend/tests/test_source_contact_privacy.py` |

O manifesto cobre todos os arquivos versionáveis deste subdiretório, inclusive
os auxiliares de reprodução. A evidência externa, índices opacos temporários e
qualquer saída catalográfica bruta não entram no repositório.

## Recibos opacos da rodada final pós-LENTE

Os três recibos foram gerados no diretório temporário da rodada final local e
não são versionados nem copiados para este repositório. Seus hashes permitem
reproduzir a rodada sem expor conteúdo catalográfico, transcrição, binding,
definições ou dados de domínio.

| Arquivo temporário | SHA-256 |
| --- | --- |
| `dev-catalog-safe-index.json` | `a783fa04da2df40981c24e464b8fc4cb997be5b8d535e9dc7d307498636ebf25` |
| `reference-catalog-safe-index.json` | `ac228120cd0e80d0de3436687a06321d86c69f580af22de08703ce4c4f86bb42` |
| `reference-trace.json` | `320ce1580991ca65e9887e676f28997b6a0c6d6f97b466cd4cc327220bc5fb0c` |

```text
PATCH_CANONICAL_SHA256=273c9a6799b3d5bb3623273688dfa5cea753035620a473e575e900a78f676415
SELF_CANONICAL_SHA256=9e7f33b1fdadf46ff3d6eb44a6fa0b5b02e66983119246170fd520b71df18109
AGGREGATE_SHA256=557c4dee7f19582f7ceb0bb165cf8a383993a09ebfd657bdf00b010947eec2e5
```

## Arquivos cobertos

| Arquivo relativo | SHA-256 |
| --- | --- |
| `ANALYSIS-CANDIDATE-MANIFEST.md` | `SELF_CANONICAL_SHA256` declarado acima |
| `DIVERGENT-8-ANALYSIS.md` | `d2be03296da1ad23e77ae4582206da839905550c8e86f90f73f487412fe24f10` |
| `MATRIX-44.md` | `9f5c9962760e3a3d693aa30999ec0834c2decb8d7e5762c398f201a061f61ecc` |
| `REFERENCE-COMPARISON-ANNEX.md` | `145883b6f38ce99db59c4e73681625a39f1a7fd8e795e9e316b539096171a8fe` |
| `STRATEGY-A-B-DECISION-PACKET.md` | `6046b38359405349e9c292ba3230e0503977cada43b1ec47d31673e1143e712e` |
| `capture-reference-deltas.py` | `a8d7f6dab32a2b58df933d8ca10a0f7838914824cc9679aa76b50fbbef6cc8c7` |
| `catalog-safe-index.py` | `c5362217c88d2be394abaf1c50aaff30207a3cb08341443e58ad93d37b64af7e` |
| `generate-reference-comparison.py` | `54f1c72c8dc5e2f53f3469a95538616940b0936580ab3306604eafd894552adc` |
| `run-pg17-reference.sh` | `f34060aa8ecd178b79b6aacf1b161bb19a819cfe07e4ae83f3edcbd24e6c54ce` |
| `test_catalog_safe_index.py` | `81d5673c706d27b253b03461a753d816ac05ea2d6e3ff7bf41d14837275c7f06` |

Os três campos dinâmicos são normalizados para 64 caracteres `0` para o cálculo
canônico. O patch usa caminho UTF-8, NUL, bytes canônicos e NUL para todos os
arquivos em ordem lexicográfica. O agregado usa caminho UTF-8, NUL, hash bruto
dos arquivos não-manifesto ou hash canônico deste manifesto e nova linha.

## Reprodução local, offline e sem saída bruta

Partindo da raiz do worktree, defina `evidence_path` como o caminho autorizado
para a transcrição externa. O comando valida hash e modo antes de chamar o
runner. O runner usa somente imagens já locais, `--pull=never`, `--network
none`, nenhum mapeamento de porta e remove os containers descartáveis. Os três
artefatos em `/tmp` são índices/hash/traço opacos e não devem ser copiados ao
repositório.

```bash
evidence_path=/caminho/autorizado/f1-dev-cast.txt
test "$(stat -c '%a' "$evidence_path")" = 600
test "$(sha256sum "$evidence_path" | awk '{print $1}')" = \
  b1c3e1bda63b55e7c5496d318bcf039d9a4d130de60ced535d918be233313e1b
test "$(sha256sum docs/ops/dev-migration-history-remediation/DEV-READONLY-F1.sql | awk '{print $1}')" = \
  8829decd0f0101329058ad07900ce7b7ca8b1c4fe5695f4e3cec05cff4bf288c
scratch_dir="$(mktemp -d /tmp/f1-reference-XXXXXX)"
python3 -I -B docs/ops/dev-migration-history-remediation/f1-analysis/test_catalog_safe_index.py
bash docs/ops/dev-migration-history-remediation/f1-analysis/run-pg17-reference.sh \
  "$scratch_dir" "$evidence_path"
test "$(sha256sum "$scratch_dir/dev-catalog-safe-index.json" | awk '{print $1}')" = \
  a783fa04da2df40981c24e464b8fc4cb997be5b8d535e9dc7d307498636ebf25
test "$(sha256sum "$scratch_dir/reference-catalog-safe-index.json" | awk '{print $1}')" = \
  ac228120cd0e80d0de3436687a06321d86c69f580af22de08703ce4c4f86bb42
test "$(sha256sum "$scratch_dir/reference-trace.json" | awk '{print $1}')" = \
  320ce1580991ca65e9887e676f28997b6a0c6d6f97b466cd4cc327220bc5fb0c
python3 -I -B docs/ops/dev-migration-history-remediation/f1-analysis/generate-reference-comparison.py \
  --dev-index "$scratch_dir/dev-catalog-safe-index.json" \
  --reference-index "$scratch_dir/reference-catalog-safe-index.json" \
  --trace "$scratch_dir/reference-trace.json" \
  | diff -u - docs/ops/dev-migration-history-remediation/f1-analysis/REFERENCE-COMPARISON-ANNEX.md
```

Este verificador lê somente o subdiretório F1 e não abre banco ou rede:

```bash
python3 -I -B - <<'PY'
from __future__ import annotations

import hashlib
import re
from pathlib import Path

root = Path('docs/ops/dev-migration-history-remediation/f1-analysis').resolve()
files = (
    'ANALYSIS-CANDIDATE-MANIFEST.md',
    'DIVERGENT-8-ANALYSIS.md',
    'MATRIX-44.md',
    'REFERENCE-COMPARISON-ANNEX.md',
    'STRATEGY-A-B-DECISION-PACKET.md',
    'capture-reference-deltas.py',
    'catalog-safe-index.py',
    'generate-reference-comparison.py',
    'run-pg17-reference.sh',
    'test_catalog_safe_index.py',
)
manifest_name = 'ANALYSIS-CANDIDATE-MANIFEST.md'
dynamic = re.compile(
    rb'(?m)^(PATCH_CANONICAL_SHA256|SELF_CANONICAL_SHA256|AGGREGATE_SHA256)='
    rb'[0-9a-f]{64}$'
)
declared = re.compile(
    rb'(?m)^(PATCH_CANONICAL_SHA256|SELF_CANONICAL_SHA256|AGGREGATE_SHA256)='
    rb'([0-9a-f]{64})$'
)
table_entry = re.compile(rb'(?m)^\| `([^`]+)` \| `([0-9a-f]{64})` \|$')
receipt_entry = re.compile(rb'(?m)^\| `([^`]+\.json)` \| `([0-9a-f]{64})` \|$')
if files != tuple(sorted(files)):
    raise SystemExit('FAIL=FILES_NOT_LEXICOGRAPHIC')
raw = {name: (root / name).read_bytes() for name in files}
if {path.name for path in root.iterdir() if path.is_file()} != set(files):
    raise SystemExit('FAIL=UNMANIFESTED_FILE')

def canonical(data: bytes) -> bytes:
    return dynamic.sub(lambda match: match.group(1) + b'=' + b'0' * 64, data)

manifest = raw[manifest_name]
expected = dict(declared.findall(manifest))
if set(expected) != {
    b'PATCH_CANONICAL_SHA256',
    b'SELF_CANONICAL_SHA256',
    b'AGGREGATE_SHA256',
}:
    raise SystemExit('FAIL=MANIFEST_DYNAMIC_FIELDS_INVALID')
actual_files = {
    name: hashlib.sha256(raw[name]).hexdigest()
    for name in files
    if name != manifest_name
}
expected_files = {
    name.decode('utf-8'): digest.decode('ascii')
    for name, digest in table_entry.findall(manifest)
    if name.decode('utf-8') in files
}
if expected_files != actual_files:
    raise SystemExit('FAIL=FILE_SHA256_MISMATCH')
receipts = {
    name.decode('utf-8'): digest.decode('ascii')
    for name, digest in receipt_entry.findall(manifest)
}
if set(receipts) != {
    'dev-catalog-safe-index.json',
    'reference-catalog-safe-index.json',
    'reference-trace.json',
}:
    raise SystemExit('FAIL=OPAQUE_RECEIPT_CONTRACT')
self_canonical = hashlib.sha256(canonical(manifest)).hexdigest()
patch = hashlib.sha256()
patch.update(b'F1-ANALYSIS-PATCH-CANONICAL-v1\0')
for name in files:
    patch.update(name.encode('utf-8') + b'\0' + canonical(raw[name]) + b'\0')
patch_canonical = patch.hexdigest()
aggregate = hashlib.sha256()
aggregate.update(b'F1-ANALYSIS-FILE-AGGREGATE-v1\0')
for name in files:
    digest = self_canonical if name == manifest_name else actual_files[name]
    aggregate.update(name.encode('utf-8') + b'\0' + digest.encode('ascii') + b'\n')
aggregate_sha256 = aggregate.hexdigest()
if expected != {
    b'PATCH_CANONICAL_SHA256': patch_canonical.encode('ascii'),
    b'SELF_CANONICAL_SHA256': self_canonical.encode('ascii'),
    b'AGGREGATE_SHA256': aggregate_sha256.encode('ascii'),
}:
    raise SystemExit('FAIL=DYNAMIC_HASH_MISMATCH')
for name in files:
    digest = self_canonical if name == manifest_name else actual_files[name]
    print(f'FILE_SHA256 {name} {digest}')
print(f'PATCH_CANONICAL_SHA256={patch_canonical}')
print(f'SELF_CANONICAL_SHA256={self_canonical}')
print(f'AGGREGATE_SHA256={aggregate_sha256}')
print('RESULT=PASS_F1_ANALYSIS_MANIFEST_REPRODUCIBLE')
PY
```
