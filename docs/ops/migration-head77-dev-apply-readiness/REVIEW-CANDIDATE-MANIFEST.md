# Manifesto reproduzível do diff completo da missão

Base Git: `5e2082e94db2b6af6b34cfe351d81cf54b85aa76`.

Escopo: todos os 15 arquivos retornados por `git diff --name-only <base>` no
candidato final. O manifesto usa hash autocanônico para cobrir também seus
próprios bytes sem circularidade: somente os valores dos campos
`SELF_CANONICAL_SHA256` e `AGGREGATE_SHA256` são substituídos por 64 zeros antes
do hash do próprio manifesto.

## SHA-256 por arquivo

```text
1de7f106741a00493e6d423b37dab9eae580d939142a334173667832339cedf8  docs/WIKI-IGREJA12.md
e6fd17d9cc64d848a34829250ad73392d14e324217acc537ef1d188db587ee02  docs/missions/M-MIGRATION-HEAD77-DEV-APPLY-READINESS-READONLY.md
59175fa7d90bf19fd3046837060912bf6dfe0c88434b9df47522b7fa14e24f7c  docs/ops/POST-V1-MISSION-REGISTER.md
0e3ec7825c1af13abc31e896dce6ad67b8070a3bb57ad7cddf918b02bcd788c3  docs/ops/migration-head77-dev-apply-readiness/APPLICATION-PACKET.md
11ca4354b320ce7eb54a8a48d3163bc3e62684091d0872f199da319ef3d3b703  docs/ops/migration-head77-dev-apply-readiness/DEV-LEDGER-RECONCILIATION.md
4efe838c3d00bf85921c6b790a00cbf12b3e0b4ca8378cfe126115097254d415  docs/ops/migration-head77-dev-apply-readiness/DEV-READONLY-EVIDENCE.md
a61954c3f65ed4ca938797009c1f6f8becd80f922ab133cbcfebe89177596565  docs/ops/migration-head77-dev-apply-readiness/DEV-READONLY-PREFLIGHT.sql
e0f6dc9f2d9f079204c0cf31ab2e317c3e911f919e577f6e21a81587dd680e7d  docs/ops/migration-head77-dev-apply-readiness/FORJA-REPORT.md
aaa1fc7fe43e9f3cdccddb883108234ac9a108c3538464febb44d6cb353c820f  docs/ops/migration-head77-dev-apply-readiness/LENTE-REVIEW.md
9da78206fee68c1a007533c066ee5b2d600c9f5e395ac683eb4cb1de4d8cf5ea  docs/ops/migration-head77-dev-apply-readiness/MISSION-CONTROL.md
SELF_CANONICAL_SHA256=5bff816a6f043eb7f80cba2f9b603f8f512c5c601d900146e112c98483ad1ac7  docs/ops/migration-head77-dev-apply-readiness/REVIEW-CANDIDATE-MANIFEST.md
467bb29c3d61976d9c9c9c7b6430932bfd3da60b7c32f67257f64df01395bee4  docs/ops/migration-head77-dev-apply-readiness/ROLLBACK-PACKET.md
00f64c1705df3905a657e22def0da77539314bc5bd05420fbedf804e90e25ce2  docs/ops/migration-head77-dev-apply-readiness/SHELL-OPERATOR-RUNBOOK.md
1e049bb0cb6425ba5251a9d88f317eacfeba3d307d61adaff7150d62faab2a12  docs/ops/migration-head77-dev-apply-readiness/SOURCE-INVENTORY.md
aecde60a5906d5f04e76ae20509f49ff071c506889d96212a78b2390a8f84ea6  docs/ops/migration-head77-dev-apply-readiness/VPS-READONLY-EVIDENCE.md
```

`AGGREGATE_SHA256=412c06b589f7377523312040ccc07ca037dff0421fd7d4a89f3beaf465328817`

## Comando de reprodução

Executar a partir da raiz do worktree. Antes do commit corretivo, o comando usa
o diff combinado entre a base, o commit atual e o worktree; no tree commitado,
o mesmo comando lê o diff entre a base e `HEAD`.

```bash
python3 - <<'PY'
import hashlib
import re
import subprocess
from pathlib import Path

base = "5e2082e94db2b6af6b34cfe351d81cf54b85aa76"
self_path = "docs/ops/migration-head77-dev-apply-readiness/REVIEW-CANDIDATE-MANIFEST.md"
expected_files = (
    "docs/WIKI-IGREJA12.md",
    "docs/missions/M-MIGRATION-HEAD77-DEV-APPLY-READINESS-READONLY.md",
    "docs/ops/POST-V1-MISSION-REGISTER.md",
    "docs/ops/migration-head77-dev-apply-readiness/APPLICATION-PACKET.md",
    "docs/ops/migration-head77-dev-apply-readiness/DEV-LEDGER-RECONCILIATION.md",
    "docs/ops/migration-head77-dev-apply-readiness/DEV-READONLY-EVIDENCE.md",
    "docs/ops/migration-head77-dev-apply-readiness/DEV-READONLY-PREFLIGHT.sql",
    "docs/ops/migration-head77-dev-apply-readiness/FORJA-REPORT.md",
    "docs/ops/migration-head77-dev-apply-readiness/LENTE-REVIEW.md",
    "docs/ops/migration-head77-dev-apply-readiness/MISSION-CONTROL.md",
    self_path,
    "docs/ops/migration-head77-dev-apply-readiness/ROLLBACK-PACKET.md",
    "docs/ops/migration-head77-dev-apply-readiness/SHELL-OPERATOR-RUNBOOK.md",
    "docs/ops/migration-head77-dev-apply-readiness/SOURCE-INVENTORY.md",
    "docs/ops/migration-head77-dev-apply-readiness/VPS-READONLY-EVIDENCE.md",
)
files = tuple(sorted(subprocess.check_output(
    ["git", "diff", "--name-only", base], text=True
).splitlines()))
assert files == expected_files, (files, expected_files)

raw = Path(self_path).read_bytes()
self_match = re.search(rb"(?m)^SELF_CANONICAL_SHA256=([0-9a-f]{64})  ", raw)
aggregate_match = re.search(rb"AGGREGATE_SHA256=([0-9a-f]{64})", raw)
assert self_match and aggregate_match
recorded_self = self_match.group(1).decode()
recorded_aggregate = aggregate_match.group(1).decode()
recorded = {
    name.decode(): digest.decode()
    for digest, name in re.findall(rb"(?m)^([0-9a-f]{64})  (docs/.+)$", raw)
}
recorded[self_path] = recorded_self
canonical = re.sub(
    rb"(?m)^(SELF_CANONICAL_SHA256=)[0-9a-f]{64}(  )",
    lambda match: match.group(1) + b"0" * 64 + match.group(2),
    raw,
)
canonical = re.sub(
    rb"(AGGREGATE_SHA256=)[0-9a-f]{64}",
    lambda match: match.group(1) + b"0" * 64,
    canonical,
)
self_digest = hashlib.sha256(canonical).hexdigest()

aggregate = hashlib.sha256()
for name in files:
    digest = self_digest if name == self_path else hashlib.sha256(
        Path(name).read_bytes()
    ).hexdigest()
    print(digest, name)
    assert digest == recorded[name], (name, digest, recorded[name])
    aggregate.update(name.encode() + b"\0" + digest.encode() + b"\n")
aggregate_digest = aggregate.hexdigest()
print("AGGREGATE", aggregate_digest)
assert self_digest == recorded_self, (self_digest, recorded_self)
assert aggregate_digest == recorded_aggregate, (
    aggregate_digest,
    recorded_aggregate,
)
PY
```
