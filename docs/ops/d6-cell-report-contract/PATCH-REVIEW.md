# Patch revisável e rollback

Registro histórico do candidato submetido à única revisão LENTE. Os hashes
abaixo se reproduzem na worktree de revisão preservada, não na entrega após
P1. Para o estado final, consulte FINAL-REPORT.md e o índice FINAL-CANDIDATE
no controle.

Base de comparação: `7a7afa3d08927f3f5b2ed116638aed3131dde88b`.
Branch candidata: `docs/d6-cell-report-operational-contract-20260913`.
Ambiente de montagem: `local/offline`.

## Escopo para revisão independente

O inventário integral está em `FINAL-REPORT.md`. O patch é exclusivamente
documental: cinco arquivos rastreados modificados, seis documentos novos de
candidato, três artefatos de abertura preservados e dois recibos sanitizados do
runner. Não inclui `backend/app`, `backend/migrations`,
`docs/ops/MAESTRI-PERSISTENCE-MANIFEST.md`, flags, guardas, credenciais ou dados
reais.

O revisor deve comparar tanto os arquivos rastreados quanto os não rastreados,
pois a ficha, o contrato e os recibos ainda não foram preparados para commit.
Os comandos de controle já executados na worktree foram:

```bash
git diff --check 7a7afa3d08927f3f5b2ed116638aed3131dde88b
git diff --exit-code 7a7afa3d08927f3f5b2ed116638aed3131dde88b -- backend/app backend/migrations docs/ops/MAESTRI-PERSISTENCE-MANIFEST.md
git status --porcelain=v1 --untracked-files=all
```

## Hash de conteúdo semântico

Em `2026-09-13T19:06:21-03:00`, o conjunto abaixo produziu
`SHA-256 7e27d897eee3696d0a985fc5ee169857de69368d0fccaab267dfd4680d642059`:

- `docs/ai/AI-BOOTSTRAP.md`
- `docs/ai/PRD-COVERAGE.md`
- `docs/WIKI-IGREJA12.md`
- `docs/decisions/2026-08-27-whatsapp-first-tenant-agent-architecture.md`
- `docs/decisions/2026-09-13-d6-cell-report-operational-contract.md`
- `docs/missions/M-2026-09-13-d6-cell-report-operational-contract.md`
- `docs/ops/POST-V1-MISSION-REGISTER.md`
- `docs/ops/d6-cell-report-contract/SCENARIO-MATRIX.md`
- `docs/sprints/2026-09-13-d6-cell-report-operational-contract.md`

Reprodução, a partir da raiz da worktree, sem alterar arquivos:

```bash
sha256sum \
  docs/ai/AI-BOOTSTRAP.md \
  docs/ai/PRD-COVERAGE.md \
  docs/WIKI-IGREJA12.md \
  docs/decisions/2026-08-27-whatsapp-first-tenant-agent-architecture.md \
  docs/decisions/2026-09-13-d6-cell-report-operational-contract.md \
  docs/missions/M-2026-09-13-d6-cell-report-operational-contract.md \
  docs/ops/POST-V1-MISSION-REGISTER.md \
  docs/ops/d6-cell-report-contract/SCENARIO-MATRIX.md \
  docs/sprints/2026-09-13-d6-cell-report-operational-contract.md | LC_ALL=C sort | sha256sum
```

## Hash do patchset completo

PATCHSET_SHA256_NORMALIZADO: 88ffb8fb186f1f7b81cd66d708f1812513aefd3ff4117006df4dbd90c7320ad8

O hash abaixo inclui os cinco arquivos rastreados modificados e os onze
arquivos não rastreados do inventário. Para que os três documentos que exibem
o próprio valor possam pertencer ao conjunto, a única normalização substitui
`PENDING` ou o hash exibido por 64 zeros antes do cálculo. Nenhum outro byte é
normalizado.

```bash
(
  export LC_ALL=C
  for candidate_file in \
    docs/WIKI-IGREJA12.md \
    docs/ai/AI-BOOTSTRAP.md \
    docs/ai/PRD-COVERAGE.md \
    docs/decisions/2026-08-27-whatsapp-first-tenant-agent-architecture.md \
    docs/decisions/2026-09-13-d6-cell-report-operational-contract.md \
    docs/missions/M-2026-09-13-d6-cell-report-operational-contract.md \
    docs/ops/POST-V1-MISSION-REGISTER.md \
    docs/ops/d6-cell-report-contract/EXECUTION-RECORD.md \
    docs/ops/d6-cell-report-contract/FINAL-REPORT.md \
    docs/ops/d6-cell-report-contract/OPENING-RECEIPT.json \
    docs/ops/d6-cell-report-contract/PATCH-REVIEW.md \
    docs/ops/d6-cell-report-contract/PR362-DISPOSITION.md \
    docs/ops/d6-cell-report-contract/SCENARIO-MATRIX.md \
    docs/ops/d6-cell-report-contract/pytest-resolver.json \
    docs/ops/d6-cell-report-contract/pytest-resolver.xml \
    docs/sprints/2026-09-13-d6-cell-report-operational-contract.md
  do
    printf '%s ' "$candidate_file"
    sed -E 's/PATCHSET_SHA256_NORMALIZADO: (PENDING|[0-9a-f]{64})/PATCHSET_SHA256_NORMALIZADO: 0000000000000000000000000000000000000000000000000000000000000000/' "$candidate_file" | sha256sum | awk '{print $1}'
  done
) | sha256sum
```

## Rollback

O rollback autorizado pelo contrato é documental e seletivo. Depois de
confirmar o patch, o hash e a ausência de alterações posteriores de terceiros,
reverter somente os caminhos desta missão. Preservar a ficha,
`OPENING-RECEIPT.json`, `PR362-DISPOSITION.md` e os recibos de teste.

Não usar `git reset --hard`, `git clean`, remoção de worktree, banco, rede ou
operação remota. Não há alteração de aplicação, schema ou ambiente
compartilhado a compensar.
