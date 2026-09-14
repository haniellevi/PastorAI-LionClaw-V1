# Registro de execução local

Registro histórico do candidato submetido à única revisão LENTE. Os hashes
abaixo se reproduzem na worktree de revisão preservada, não na entrega após
P1. Para o estado final, consulte FINAL-REPORT.md e o índice FINAL-CANDIDATE
no controle.

Missão: `M-2026-09-13-d6-cell-report-operational-contract`.

Base: `7a7afa3d08927f3f5b2ed116638aed3131dde88b`.
Branch: `docs/d6-cell-report-operational-contract-20260913`.
Ambiente: `local/offline`, sem banco, rede, credenciais, runtime, hooks ou
efeito externo.

## Preflight

Em `2026-09-13T18:44:02-03:00`, conforme ficha de abertura, a base e a branch
foram fixadas. Nesta execução, a conferência local em
`2026-09-13T18:56:48-03:00` confirmou o mesmo SHA. Os únicos itens não
rastreados antes de escrever o candidato eram a ficha e os dois recibos de
abertura da missão; eles foram preservados.

## Teste focal executado

Início: `2026-09-13T18:57:15.204460-03:00`.
Fim: `2026-09-13T18:57:16.404801-03:00`.

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/raniel-linux/workspace/PastorAi-1.0/backend/.venv-runtime/bin/python -I -B /home/raniel-linux/workspace/PastorAi-1.0/.worktrees/maestri-astra-workspace-plan/docs/ops/pr364-rebase/run_offline_pytest.py /home/raniel-linux/workspace/PastorAi-1.0/.worktrees/d6-cell-report-operational-contract-20260913 /home/raniel-linux/workspace/PastorAi-1.0/.worktrees/d6-cell-report-operational-contract-20260913/docs/ops/d6-cell-report-contract/pytest-resolver tests/test_cell_report_meeting_resolver.py
```

Resultado: `17 passed in 0.50s`, código de saída `0`,
`OFFLINE_GUARD_DENIALS=0`. Recibos gerados pelo runner:
`pytest-resolver.json` e `pytest-resolver.xml`.

O runner usou Python `3.13.14`, ambiente limpo sem credenciais de aplicação e
guardas para rede/conexões. Seus limites declarados no recibo permanecem:
processos filhos permitidos herdam as restrições do sandbox, mas isso não é
atestação de isolamento do sistema operacional. O teste usa dados sintéticos e
um monkeypatch de `require_tenant_scope`; ele não prova RLS PostgreSQL viva,
identidade externa, banco, caller, consentimento ou efeito de domínio.

## Exclusões deliberadas

Não foi executada a suíte do coordenador. Ela possui gates permissivos e mint
de permit em testes, incompatíveis com a proibição desta missão de fabricar
concessão, writer, monkeypatch ou bypass de `purpose_consent`. C06-C08 ficaram
documentados e C09-C10 ficaram `BLOCKED_BY_E4B`.

## Validação documental final

Horário da validação: `2026-09-13T19:06:21-03:00`.

Os comandos abaixo terminaram com código de saída `0`:

```bash
git diff --check 7a7afa3d08927f3f5b2ed116638aed3131dde88b
git diff --exit-code 7a7afa3d08927f3f5b2ed116638aed3131dde88b -- backend/app backend/migrations docs/ops/MAESTRI-PERSISTENCE-MANIFEST.md
```

A primeira comparação não encontrou erro de espaço ou patch inválido. A
segunda confirmou ausência de alterações em `backend/app`,
`backend/migrations` e no manifesto de persistência. A conferência de
inventário registrou cinco arquivos rastreados modificados e onze arquivos não
rastreados, dos quais três já eram artefatos de abertura preservados: a ficha,
`OPENING-RECEIPT.json` e `PR362-DISPOSITION.md`.

Também foram conferidos: exatamente dez linhas C01-C10 na matriz, ausência de
espaço final nos documentos alterados e JSON válido nos dois recibos JSON. A
matriz final está em `SCENARIO-MATRIX.md:20-29`: C01 e C04 são
`VERIFICADO_OFFLINE`; C02, C03 e C05-C08 são
`EXPECTATIVA_DOCUMENTADA`; C09 e C10 são `BLOCKED_BY_E4B`.

Hash determinístico do conjunto de conteúdo semântico, calculado após a
validação acima: `SHA-256 7e27d897eee3696d0a985fc5ee169857de69368d0fccaab267dfd4680d642059`.
O conjunto e o procedimento de reprodução estão em `PATCH-REVIEW.md`.

Em `2026-09-13T19:13:43-03:00`, o patchset completo produziu:

PATCHSET_SHA256_NORMALIZADO: 88ffb8fb186f1f7b81cd66d708f1812513aefd3ff4117006df4dbd90c7320ad8

Esse segundo hash cobrirá todos os dezesseis caminhos do candidato, inclusive
os não rastreados. Para evitar autorreferência, a reprodução substitui apenas
o valor desse campo nos três documentos de evidência por 64 zeros antes de
calcular os hashes de conteúdo e do conjunto.

Limite final: essas verificações demonstram consistência do patch local e do
teste executado neste SHA. Elas não substituem revisão independente, RLS em
PostgreSQL, fonte E4B, caller, runtime, banco, DEV ou PROD.
