# Manifesto reproduzível do candidato revisado

Base Git: `5e2082e94db2b6af6b34cfe351d81cf54b85aa76`.

Escopo: os 11 arquivos do pacote técnico após as correções documentais P1/P2
autorizadas por Raniel. `LENTE-REVIEW.md` registra a revisão e fica fora deste
agregado para evitar misturar o parecer com o candidato avaliado.

## SHA-256 por arquivo

```text
e6fd17d9cc64d848a34829250ad73392d14e324217acc537ef1d188db587ee02  docs/missions/M-MIGRATION-HEAD77-DEV-APPLY-READINESS-READONLY.md
d666b1891d46c64b20fefb930a761b0bdfc74abdf2665eeea62dc457a848d604  docs/ops/migration-head77-dev-apply-readiness/APPLICATION-PACKET.md
11ca4354b320ce7eb54a8a48d3163bc3e62684091d0872f199da319ef3d3b703  docs/ops/migration-head77-dev-apply-readiness/DEV-LEDGER-RECONCILIATION.md
34346ec5e04ccf2ff9c5db660da832f26c0529494c8f9300dbeb106fba626770  docs/ops/migration-head77-dev-apply-readiness/DEV-READONLY-EVIDENCE.md
a61954c3f65ed4ca938797009c1f6f8becd80f922ab133cbcfebe89177596565  docs/ops/migration-head77-dev-apply-readiness/DEV-READONLY-PREFLIGHT.sql
e0f6dc9f2d9f079204c0cf31ab2e317c3e911f919e577f6e21a81587dd680e7d  docs/ops/migration-head77-dev-apply-readiness/FORJA-REPORT.md
9da78206fee68c1a007533c066ee5b2d600c9f5e395ac683eb4cb1de4d8cf5ea  docs/ops/migration-head77-dev-apply-readiness/MISSION-CONTROL.md
467bb29c3d61976d9c9c9c7b6430932bfd3da60b7c32f67257f64df01395bee4  docs/ops/migration-head77-dev-apply-readiness/ROLLBACK-PACKET.md
38fc9fb2ccd65264276f674b6e7e4a5128a3fa48c81c75997cfc1a310c39c0ba  docs/ops/migration-head77-dev-apply-readiness/SHELL-OPERATOR-RUNBOOK.md
1e049bb0cb6425ba5251a9d88f317eacfeba3d307d61adaff7150d62faab2a12  docs/ops/migration-head77-dev-apply-readiness/SOURCE-INVENTORY.md
01dc1e794559cc489828dadc43704d24845004bffec70100a0f058efae65c70c  docs/ops/migration-head77-dev-apply-readiness/VPS-READONLY-EVIDENCE.md
```

Agregado SHA-256:
`5ade765c1827bc01b7bf31abc7166255f2f3c6ea76c82448964a0108015d4b41`.

## Comando de reprodução

Executar a partir da raiz do worktree. O agregado concatena, para cada caminho
na ordem abaixo, `path`, byte NUL, SHA-256 hexadecimal e quebra de linha.

```bash
python3 - <<'PY'
import hashlib
from pathlib import Path

files = (
    "docs/missions/M-MIGRATION-HEAD77-DEV-APPLY-READINESS-READONLY.md",
    "docs/ops/migration-head77-dev-apply-readiness/APPLICATION-PACKET.md",
    "docs/ops/migration-head77-dev-apply-readiness/DEV-LEDGER-RECONCILIATION.md",
    "docs/ops/migration-head77-dev-apply-readiness/DEV-READONLY-EVIDENCE.md",
    "docs/ops/migration-head77-dev-apply-readiness/DEV-READONLY-PREFLIGHT.sql",
    "docs/ops/migration-head77-dev-apply-readiness/FORJA-REPORT.md",
    "docs/ops/migration-head77-dev-apply-readiness/MISSION-CONTROL.md",
    "docs/ops/migration-head77-dev-apply-readiness/ROLLBACK-PACKET.md",
    "docs/ops/migration-head77-dev-apply-readiness/SHELL-OPERATOR-RUNBOOK.md",
    "docs/ops/migration-head77-dev-apply-readiness/SOURCE-INVENTORY.md",
    "docs/ops/migration-head77-dev-apply-readiness/VPS-READONLY-EVIDENCE.md",
)

aggregate = hashlib.sha256()
for name in files:
    digest = hashlib.sha256(Path(name).read_bytes()).hexdigest()
    print(digest, name)
    aggregate.update(name.encode() + b"\0" + digest.encode() + b"\n")
print("AGGREGATE", aggregate.hexdigest())
PY
```

Resultado esperado: os 11 hashes acima e o agregado
`5ade765c1827bc01b7bf31abc7166255f2f3c6ea76c82448964a0108015d4b41`.
