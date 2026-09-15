# Manifesto reproduzível da análise F1

## Binding da análise

| Campo | Valor |
| --- | --- |
| Base Git | `e1da65d0a6fa5286674f425f855600eb3e4982bb` |
| HEAD da correção PR #400 | `e07d4bd81506b2977c8b5c7fbea7c1f6a9f65564` |
| Branch | `docs/dev-migration-history-remediation-f1-20260915` |
| Diretório desta análise | `docs/ops/dev-migration-history-remediation/f1-analysis/` |
| Evidência externa somente leitura | SHA-256 `b1c3e1bda63b55e7c5496d318bcf039d9a4d130de60ced535d918be233313e1b`, modo `0600`, coleta `2026-09-15T11:18:39-03:00` |
| SQL F1 congelado, não coberto por este manifesto | `8829decd0f0101329058ad07900ce7b7ca8b1c4fe5695f4e3cec05cff4bf288c` |
| Agregado F1 congelado, não coberto por este manifesto | `956187b9711ea9d67e9f8fdf31c3980e3ebbf64da98401c275f1dc80d2a91a29` |
| Declaração humana separada | `DEV_DATA_DISPOSITION=NO_VALUE_NO_PII` |
| Referência descartável | PostgreSQL `17.6`, imagem local SHA-256 `00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929`, `--pull=never`, `--network none`, sem porta publicada |
| Resultado local | Replay oficial `77/77`, traço direcional V2 `77/77`, banco de traço recriado via banco `postgres`, contrato fresh validado e rollback de referência concluídos |
| Parser e pré-validação sintéticos | `29/29` aprovados: contrato compartilhado parser/comparador, perfis `SEALED_F1` e `STRICT_FUTURE`, recibos, ordem terminal, contagens, estados, abortos, modo, SHA, índice não pinado, marcadores e tipos desconhecidos, ciclo transitório, lacuna direcional, scan de caminhos pessoais e ausência de canário |
| E2E F1 congelado | `RESULT=PASS_PG17_E2E_F1_B1_B2_AND_REGRESSION` em PostgreSQL 17.6 local descartável |
| Guarda de privacidade | `13/13` em `backend/tests/test_source_contact_privacy.py` |

O manifesto cobre todos os arquivos versionáveis deste subdiretório, inclusive
os auxiliares de reprodução. A evidência externa, índices opacos temporários e
qualquer saída catalográfica bruta não entram no repositório.

## Recibos opacos preservados e regenerados na correção PR #400

Os recibos não são versionados nem copiados para este repositório. O runner
recebe a evidência local como argumento efêmero, exige arquivo regular, modo
`0600` e SHA-256 pinado antes de abrir ou parsear, e regenera o índice DEV no
perfil `SEALED_F1`. O perfil aceita eco interno de rollback `0/1`; o perfil
`STRICT_FUTURE` exige o eco. O índice de referência e o traço direcional V2
são locais em PostgreSQL 17.6 descartável. Os hashes permitem verificar a
cadeia sem expor conteúdo catalográfico, transcrição, binding, definições,
dados de domínio ou caminho pessoal.

| Arquivo temporário | SHA-256 |
| --- | --- |
| `dev-catalog-safe-index.json` | `a783fa04da2df40981c24e464b8fc4cb997be5b8d535e9dc7d307498636ebf25` |
| `reference-catalog-safe-index.json` | `ac228120cd0e80d0de3436687a06321d86c69f580af22de08703ce4c4f86bb42` |
| `reference-trace.json` | `0563a1b5b11ebbede584cdc5a3865d9913cb77605e50d516c0857dde7f67453e` |

```text
PATCH_CANONICAL_SHA256=4fb2f04ca4d7a2e65fcb50a16270bea550bd4607345be61b8357c1be378a444b
SELF_CANONICAL_SHA256=d322c5501f2a506310aeb20453560489ab3d28d46c755668334da570a7465db5
AGGREGATE_SHA256=68e567488d1ef7f3b0df6c5d723e7beb40d494570adb5d911b8445373b10bf3b
```

## Arquivos cobertos

| Arquivo relativo | SHA-256 |
| --- | --- |
| `ANALYSIS-CANDIDATE-MANIFEST.md` | `SELF_CANONICAL_SHA256` declarado acima |
| `DIVERGENT-8-ANALYSIS.md` | `1b9ead37227c56df2b122ccce090d595cd8ab89e08ce36c06ad6eca075c61a39` |
| `MATRIX-44.md` | `c7fa12f28dd2fafe12e3f065c96fae6ee5747621126c5da09e6e8c21dd528585` |
| `REFERENCE-COMPARISON-ANNEX.md` | `3568a9dc9e7618c4015a35811cdb65c11c665d3bac90e32ab1f49b29d7758138` |
| `STRATEGY-A-B-DECISION-PACKET.md` | `0dabfa9620eb6e88c5c25621f71d5c648b72d954913cee6254813958f743d508` |
| `capture-reference-deltas.py` | `cf560a3db5a90069cf7619e289a64c27d7860bbe4d7264c5f81b483fbf1f2ac4` |
| `catalog-safe-index.py` | `7e2289fd873d96bf88081a927f8373d0314fe703fd1ac12430751d15d64df06a` |
| `dev_receipt_contract.py` | `85109f0f59e13fa16cd2727242ce31c4160bca86d9ea0b1ab8bb5df7f64296c6` |
| `generate-reference-comparison.py` | `c731d450d87ba51d7704b23ae5575d501356df693989fc5fc0bc3396a605da26` |
| `run-pg17-reference.sh` | `c0e6838044facc8a0f9bcfeb1aa1114436c96ab339d8ab2faf93f44983465355` |
| `test_catalog_safe_index.py` | `ef375bf784303c4168a414229564ed55304919d1a6830f1e52a41daeb1b42a9e` |

Os três campos dinâmicos são normalizados para 64 caracteres `0` para o cálculo
canônico. O patch usa caminho UTF-8, NUL, bytes canônicos e NUL para todos os
arquivos em ordem lexicográfica. O agregado usa caminho UTF-8, NUL, hash bruto
dos arquivos não-manifesto ou hash canônico deste manifesto e nova linha.

## Reprodução local, offline e sem saída bruta

O verificador abaixo reproduz o manifesto do candidato apenas com os onze
arquivos versionados. O teste sintético prova o contrato único de entrada DEV,
inclusive a rejeição anterior à serialização e o scan de caminho pessoal. O
replay que gera o traço V2 usa somente imagens locais, `--pull=never`,
`--network none`, nenhuma porta publicada e container descartável. Qualquer
coleta futura exige novo gate humano e o contrato completo do parser.

```bash
python3 -I -B docs/ops/dev-migration-history-remediation/f1-analysis/test_catalog_safe_index.py
```

Para a reprodução F1 de ponta a ponta, o operador fornece a evidência local
somente como segundo argumento do runner. O caminho não é salvo em arquivo,
manifesto, stdout nem artefato. O runner falha antes de abrir ou parsear se o
arquivo não for regular, não estiver em `0600` ou não corresponder ao hash
pinado. Execute a partir da raiz, com o argumento local autorizado:

```bash
set -euo pipefail
f1_output_dir="$(mktemp -d /tmp/f1-reference-XXXXXX)"
f1_evidence_path="${1:?evidência local obrigatória}"
bash docs/ops/dev-migration-history-remediation/f1-analysis/run-pg17-reference.sh \
  "$f1_output_dir" "$f1_evidence_path"
test "$(sha256sum "$f1_output_dir/dev-catalog-safe-index.json" | awk '{print $1}')" = \
  'a783fa04da2df40981c24e464b8fc4cb997be5b8d535e9dc7d307498636ebf25'
test "$(sha256sum "$f1_output_dir/reference-catalog-safe-index.json" | awk '{print $1}')" = \
  'ac228120cd0e80d0de3436687a06321d86c69f580af22de08703ce4c4f86bb42'
test "$(sha256sum "$f1_output_dir/reference-trace.json" | awk '{print $1}')" = \
  '0563a1b5b11ebbede584cdc5a3865d9913cb77605e50d516c0857dde7f67453e'
python3 -I -B docs/ops/dev-migration-history-remediation/f1-analysis/generate-reference-comparison.py \
  --dev-index "$f1_output_dir/dev-catalog-safe-index.json" \
  --reference-index "$f1_output_dir/reference-catalog-safe-index.json" \
  --trace "$f1_output_dir/reference-trace.json" \
  > "$f1_output_dir/REFERENCE-COMPARISON-ANNEX.md"
cmp -s "$f1_output_dir/REFERENCE-COMPARISON-ANNEX.md" \
  docs/ops/dev-migration-history-remediation/f1-analysis/REFERENCE-COMPARISON-ANNEX.md
printf '%s\n' 'RESULT=PASS_F1_END_TO_END_REPRODUCTION'
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
    'dev_receipt_contract.py',
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
personal_path = b'/' + b'home/'
if any(personal_path in content for content in raw.values()):
    raise SystemExit('FAIL=PERSONAL_PATH_LITERAL')

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
