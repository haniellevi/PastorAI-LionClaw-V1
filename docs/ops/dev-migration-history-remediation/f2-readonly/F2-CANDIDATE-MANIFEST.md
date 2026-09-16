# Manifesto reproduzível do candidato F2 read-only

## Identidade congelada

| Campo | Valor |
| --- | --- |
| Base Git | `f856f53f48e79a53609ff699d5603119f60202e0` |
| Branch | `docs/dev-migration-history-remediation-f2-readonly-20260915` |
| Diretório | `docs/ops/dev-migration-history-remediation/f2-readonly/` |
| Recorte APTO | `docs/missions/M-2026-09-15-f2-prod-readonly-collection.md` |
| SHA-256 do recorte | `727aeee8f71163b718b0a5f07511260324bf9ffaae4c220b47086842b86797ce` |
| Ambiente de teste | `LOCAL_DISPOSABLE_POSTGRES_17_6`, rede `none`, nenhuma porta publicada |
| Resultado E2E | `PASS_PG17_E2E_F2_PROD_DEV_STRICT_FUTURE` |
| Ambientes vivos acessados | `NENHUM` |
| Estado Git | arquivos locais sem commit, push ou PR |

Os três campos abaixo são normalizados para 64 caracteres `0` antes do cálculo
canônico. Nenhum outro byte é normalizado.

```text
PATCH_CANONICAL_SHA256=6a6f4b23bb09fbdf76b39b93a7d3ad88e555a6e84ffbec15691c48005c7f84cb
SELF_CANONICAL_SHA256=2ce38c9fbf259a9a89256f0f7482fa79cb2d115c1908c8a5652ab88e1a7c07db
AGGREGATE_SHA256=7be006ef2fd8fad6ec42490bd29ece50c27c6f6321734e4b55cf1dd36b7f32fc
```

## Arquivos e SHA-256

| Arquivo relativo | SHA-256 |
| --- | --- |
| `DEV-READONLY-F2.sql` | `1567bee8149f9112db4bc96bea9b1a5a7ff4295c0a070a98c2ad93f522a2056f` |
| `F2-CANDIDATE-MANIFEST.md` | `SELF_CANONICAL_SHA256` |
| `PROD-READONLY-F2.sql` | `a30be6984b09ad558a615b0440c4a656c61f3d70ef1ba4ac988512d66de66285` |
| `RANIEL-READONLY-F2-RUNBOOK.md` | `92f4a21dc4044e67eb052a2bc742d9d1bc9601000a1439a221def89f6033f1f9` |
| `run-pg17-f2-e2e.sh` | `3246d38f121bea0de49447a1801527da3f082dfbc362166273230548c850bc74` |

`SELF_CANONICAL_SHA256` é o SHA-256 deste manifesto após a normalização dos
três campos dinâmicos. `PATCH_CANONICAL_SHA256` vincula caminho e bytes
canônicos dos cinco arquivos em ordem lexicográfica. `AGGREGATE_SHA256` vincula
cada caminho ao hash bruto do arquivo, usando o hash canônico para o manifesto.
O conjunto exato é fechado: arquivo adicional ou ausente no diretório falha.

## Verificação reproduzível

Execute da raiz da worktree, sem rede e sem banco:

```bash
python3 -I -B - <<'PY'
from __future__ import annotations
import hashlib
import re
from pathlib import Path
root = Path("docs/ops/dev-migration-history-remediation/f2-readonly").resolve()
files = (
    "DEV-READONLY-F2.sql",
    "F2-CANDIDATE-MANIFEST.md",
    "PROD-READONLY-F2.sql",
    "RANIEL-READONLY-F2-RUNBOOK.md",
    "run-pg17-f2-e2e.sh",
)
manifest_name = "F2-CANDIDATE-MANIFEST.md"
dynamic = re.compile(
    rb"(?m)^(PATCH_CANONICAL_SHA256|SELF_CANONICAL_SHA256|AGGREGATE_SHA256)="
    rb"[0-9a-f]{64}$"
)
declared = re.compile(
    rb"(?m)^(PATCH_CANONICAL_SHA256|SELF_CANONICAL_SHA256|AGGREGATE_SHA256)="
    rb"([0-9a-f]{64})$"
)
table_entry = re.compile(rb"(?m)^\| `([^`]+)` \| `([0-9a-f]{64})` \|$")
actual_names = tuple(sorted(path.name for path in root.iterdir() if path.is_file()))
if actual_names != files:
    raise SystemExit("FAIL=F2_FILE_SET_MISMATCH")
raw = {name: (root / name).read_bytes() for name in files}
def canonical(data: bytes) -> bytes:
    return dynamic.sub(lambda match: match.group(1) + b"=" + b"0" * 64, data)
manifest = raw[manifest_name]
expected = dict(declared.findall(manifest))
if set(expected) != {b"PATCH_CANONICAL_SHA256", b"SELF_CANONICAL_SHA256", b"AGGREGATE_SHA256"}:
    raise SystemExit("FAIL=F2_DYNAMIC_FIELDS_INVALID")
actual_files = {name: hashlib.sha256(raw[name]).hexdigest() for name in files if name != manifest_name}
expected_files = {name.decode(): digest.decode() for name, digest in table_entry.findall(manifest)}
for name, digest in actual_files.items():
    if expected_files.get(name) != digest:
        raise SystemExit(f"FAIL=F2_FILE_SHA256_MISMATCH:{name}")
self_canonical = hashlib.sha256(canonical(manifest)).hexdigest()
patch = hashlib.sha256(); patch.update(b"F2-PATCH-CANONICAL-v1\0")
for name in files:
    patch.update(name.encode() + b"\0" + canonical(raw[name]) + b"\0")
patch_canonical = patch.hexdigest()
aggregate = hashlib.sha256(); aggregate.update(b"F2-FILE-AGGREGATE-v1\0")
for name in files:
    digest = self_canonical if name == manifest_name else actual_files[name]
    aggregate.update(name.encode() + b"\0" + digest.encode() + b"\n")
aggregate_sha256 = aggregate.hexdigest()
actual = {
    b"PATCH_CANONICAL_SHA256": patch_canonical.encode(),
    b"SELF_CANONICAL_SHA256": self_canonical.encode(),
    b"AGGREGATE_SHA256": aggregate_sha256.encode(),
}
for field, digest in actual.items():
    if expected.get(field) != digest:
        raise SystemExit(f"FAIL=F2_DYNAMIC_HASH_MISMATCH:{field.decode()}")
for name in files:
    digest = self_canonical if name == manifest_name else actual_files[name]
    print(f"FILE_SHA256 {name} {digest}")
print(f"PATCH_CANONICAL_SHA256={patch_canonical}")
print(f"SELF_CANONICAL_SHA256={self_canonical}")
print(f"AGGREGATE_SHA256={aggregate_sha256}")
print("RESULT=PASS_F2_MANIFEST_REPRODUCIBLE")
PY
```

O resultado positivo prova somente a integridade dos cinco arquivos e seu
vínculo com o recorte e a base declarados. Não prova identidade de PROD ou DEV,
estado vivo, autorização de execução, migration aplicada, epoch, cutover,
executor, deploy, escrita ou comparação entre ambientes.
