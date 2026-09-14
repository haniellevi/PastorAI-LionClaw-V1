---
id: M-2026-09-13-d6-cell-report-operational-contract
status: concluida_offline
authorized_by: Raniel
authorized_on: 2026-09-13
environment: local_offline
---

# M-2026-09-13-d6-cell-report-operational-contract

## Ficha MISSION-CONTROL

```yaml
id: M-2026-09-13-d6-cell-report-operational-contract
objetivo: Fechar o contrato verificável de reunião confiável e precondição externa de consentimento para relatório de célula por texto, entregando escopo executável da missão de implementação seguinte.
preflight:
  repositorio: haniellevi/PastorAI-LionClaw-V1, clone local (raiz relativa ../..)
  workspace: IGREJA 12 - MANUAL
  terminal: Orquestrador
  branch: docs/d6-cell-report-operational-contract-20260913
  sha_efetivo: 7a7afa3d08927f3f5b2ed116638aed3131dde88b
  worktree_limpo: true antes da criação desta ficha e dos artefatos da missão
  ambiente: local/offline, sem banco
  horario: 2026-09-13T18:44:02-03:00, início do preflight local; recibo de abertura contém horário final
  runbook_lido: docs/ops/MISSION-CONTROL.md e ADR WhatsApp-first, seção Gate sucessor desta fatia offline
  grafo: indisponível, code-review-graph desabilitado; busca limitada por arquivo
worktree: .worktrees/d6-cell-report-operational-contract-20260913
branch: docs/d6-cell-report-operational-contract-20260913
sha_base: 7a7afa3d08927f3f5b2ed116638aed3131dde88b
especialistas:
  - preparação pelo Orquestrador, gpt-6-astra ultra, concluída antes de qualquer delegação
  - execução prevista FORJA, gpt-5.6-terra max, nesta worktree; sessão efetiva deve ser confirmada antes de acionamento
  - revisão prevista LENTE, gpt-5.6-terra max, sessão distinta read-only em worktree própria do candidato; no máximo uma rodada
criterios_de_aceite:
  - A1. Destino prévio do PR362 registrado como áudio adiado; um único contrato D6-CELL-REPORT ativo, sem copiar ou aprovar D6-AUDIO.
  - A2. Contrato fecha entradas confiáveis, vínculo igreja/ator/inbound/reunião, fonte e validade temporal; reunião ausente, ambígua ou adulterada falha fechada.
  - A3. tarefas_operacionais é precondição externa; DenyAllOperationalConsentGate permanece padrão; concessão, writer e bypass de purpose_consent proibidos.
  - A4. Matriz fechada de 10 cenários abaixo, com expectativa, evidência e estado explícitos; positivos dependentes de consentimento ficam BLOCKED_BY_E4B, nunca PASS ou skip disfarçado.
  - A5. Diff restrito à allowlist, validação documental e testes offline pertinentes sem falhas; bytes dos serviços, manifesto, flags e guardas preservados.
  - A6. Uma única rodada de revisão independente do candidato exato (SHA base e hash do patch), achados resolvidos ou impedimento declarado; nenhum novo ciclo de contratos.
  - A7. FINAL-REPORT aponta M-D6-CELL-REPORT-MEETING-TARGET-IMPLEMENTATION, com arquivos, testes e dependências; não abre runtime ou consentimento positivo.
riscos_de_tenant:
  - Tenant, ator, identidade e capacidades devem vir do backend confiável; entrada do modelo não estabelece autoridade.
  - Alvo de reunião de outra igreja, ator, inbound ou contexto temporal deve ser recusado; selo local não equivale a prova durável.
  - Consentimento de outra finalidade ou pessoa não autoriza tarefas_operacionais; indisponibilidade ou dúvida resultam em negação.
plano_de_teste:
  - git diff --check 7a7afa3d08927f3f5b2ed116638aed3131dde88b
  - pytest offline focal de test_cell_report_meeting_resolver.py com runner já existente, comando exato abaixo
  - validação da matriz dos 10 cenários e revisão de proveniência com referências arquivo:linha; casos positivos permanecem bloqueados
  - comparação byte a byte de backend/app, backend/migrations e manifesto com SHA base; inventário de todos os arquivos inclusive não rastreados
plano_de_rollback:
  - Reverter somente o patch identificado da missão, após conferir hash e que não há alterações posteriores de terceiros.
  - Arquivos novos só podem ser retirados do candidato se constarem do recibo e mantiverem o hash registrado; preservar cópia de evidência, notas, branch e worktree.
  - Não usar reset --hard, clean, remoção de worktree ou reversão de commits anteriores; nenhuma ação remota ou dado a compensar.
proximo_gate: Raniel autorizar nominalmente M-D6-CELL-REPORT-MEETING-TARGET-IMPLEMENTATION após o contrato cumprir o aceite e a única revisão.
```

## Autorização e pré-condição satisfeita

Ordem nominal de Raniel recebida no chat em 13/09/2026. Parecer dos dois
conselheiros lido na nota `Consenso dos Conselheiros`, linha 16:
ambos APTO COM RESSALVAS, sem divergência, com as três ressalvas transcritas
nos critérios A1, A3, A4, A6 e A7. Não há consulta pendente para repetir a abertura.

Antes de criar a worktree foi registrada a decisão em
`docs/ops/d6-cell-report-contract/PR362-DISPOSITION.md` no controle.
PR #362, head `e41998c5e9aa698bde60e062682064d91dc24fbf`, é proposta exclusiva
de áudio: ADIADA na fila local, não integra nem concorre com a linha ativa de
relatório por texto. A PR remota continua OPEN, sem mutação.
Cópia dessa decisão acompanha a ficha na worktree da missão.

A base é o merge commit do PR #364, recebido nominalmente e conferido no Git
local com os pais `9487eac` e `7442025`. Não se afirma ter renovado a ref
remota de main nesta abertura. CI pós-merge: 15/15 contextos obrigatórios
SUCCESS mais Vercel success, conforme verificação transmitida pelo CONSELHEIRO;
não reexecutado nesta preparação. Incidente PROD #392 está fora.

## Escopo permitido e arquivos

Preparação, contrato documental único, matriz de cenários, testes de contrato
puramente offline com dados sintéticos e evidência sanitizada. Sem alteração
de comportamento do produto. A autorização de abertura não é autorização
operacional.

Allowlist para a execução desta missão:

- `docs/missions/M-2026-09-13-d6-cell-report-operational-contract.md`;
- `docs/decisions/2026-09-13-d6-cell-report-operational-contract.md`, único contrato da missão;
- `docs/decisions/2026-08-27-whatsapp-first-tenant-agent-architecture.md`, somente referência e estado do gate D6-CELL-REPORT;
- `docs/ai/AI-BOOTSTRAP.md`, `docs/ai/PRD-COVERAGE.md` e `docs/WIKI-IGREJA12.md`, somente rastreabilidade desta fatia, sem declarar operação;
- `docs/ops/d6-cell-report-contract/`, matriz, recibos, patch e relatório;
- `docs/sprints/2026-09-13-d6-cell-report-operational-contract.md` e trecho desta missão em `docs/ops/POST-V1-MISSION-REGISTER.md`;
- `backend/tests/test_d6_cell_report_operational_contract.py`, se necessário para verificação real das recusas já implementadas; sem writer falso, concessão ou bypass.

Notas de controle no canvas são mantidas pelo Orquestrador.
Os artefatos desta ficha são locais e não commitados nesta preparação.

Fora: runtime/caller/worker/webhook, banco inclusive local, migrations, grants,
credenciais, E4b, áudio/transcrição, LLM, storage, envio, ativação, publicação,
push/PR/merge/deploy, incidente PROD #392, manifesto, flags e guardas.
Nenhum recibo E4b nem a branch documental `67659a3` entra neste candidato.

## Matriz de aceite fechada

Os estados abaixo são expectativas do contrato; não são testes executados.

| ID | Cenário | Expectativa e evidência exigida |
|---|---|---|
| C01 | Reunião fora da igreja confiável | Recusa, referência ao teste isolado e às validações do resolver |
| C02 | Ator sem responsabilidade válida | Recusa, sem promoção de autoridade pelo modelo |
| C03 | Reunião ausente | Sem alvo, motivo explícito |
| C04 | Duas reuniões elegíveis | Ambiguidade, sem escolha silenciosa |
| C05 | Alvo de outro inbound/ator ou janela inválida | Recusa antes de qualquer operação, referência à fronteira existente |
| C06 | Consentimento ausente ou gate indisponível | Deny-all, sem gravar nem conceder |
| C07 | Consentimento retirado ou finalidade divergente | Negação; evidência de leitura source-only, sem writer de teste |
| C08 | Validade ou proveniência de consentimento não comprovada | Negação; não presumir estado de expiração que o domínio não possua |
| C09 | Proposta que exige consentimento concedido | BLOCKED_BY_E4B, não executar caminho positivo |
| C10 | Confirmação/persistência que exige consentimento concedido | BLOCKED_BY_E4B, não executar caminho positivo |

A matriz final distingue EXPECTATIVA_DOCUMENTADA, VERIFICADO_OFFLINE e
BLOCKED_BY_E4B por linha, com fonte, comando quando houver execução e limite.
Não criar teste que apenas espelhe o próprio texto para fabricar prova funcional.
Casos C01-C08 sem prova adequada permanecem não verificados e impedem declarar
o respectivo comportamento implementado. O contrato pode fechar com decisões
documentais explícitas e dependências bloqueadas, sem alegar integração.

## Comandos e evidência

Executar a partir da worktree da missão. Runner e intérprete existentes
são dependências locais, não arquivos do produto; não instalar pacotes.

```bash
git diff --check 7a7afa3d08927f3f5b2ed116638aed3131dde88b
git diff --exit-code 7a7afa3d08927f3f5b2ed116638aed3131dde88b -- backend/app backend/migrations docs/ops/MAESTRI-PERSISTENCE-MANIFEST.md
git status --porcelain=v1 --untracked-files=all
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ../../backend/.venv-runtime/bin/python -I -B ../maestri-astra-workspace-plan/docs/ops/pr364-rebase/run_offline_pytest.py . ./docs/ops/d6-cell-report-contract/pytest-resolver tests/test_cell_report_meeting_resolver.py
```

O runner bloqueia rede, conexões SQLAlchemy/libpq/SQLite e leitura de caminhos
protegidos, com ambiente limpo; seus limites documentados continuam válidos.
Se houver novo teste permitido, acrescentar apenas seu caminho exato à lista
do mesmo runner após revisão de que não concede consentimento nem fabrica writer.
Capturar comando, SHA, hash do patch incluindo novos arquivos, horário, resultado,
contagens e limites. Não herdar os 615 testes de outro SHA como validação desta missão.
Suíte HTTP anterior teve travamento TestClient/AnyIO; não declarar suíte completa
verde nem enfraquecer isolamento para contornar esse limite.

## Execução e revisão sem novo ciclo de governança

Preparação é responsabilidade do Orquestrador no controle; execução posterior
usa esta worktree exclusivamente com FORJA, após conferir modelo/esforço e -C.
LENTE recebe uma worktree própria do candidato exato, somente leitura, em
sessão distinta. Especialistas não escrevem notas, não executam Maestri e não
recrutam. Nenhum especialista foi acionado durante esta preparação.

Há no máximo uma rodada de revisão independente. Correções do parecer cabem
no mesmo escopo e são verificadas objetivamente; impedimento restante aparece
no relatório, sem outra missão de contrato. O parecer estratégico conjunto
já está registrado, não será solicitado de novo para a mesma abertura.

## Saída obrigatória e único próximo gate

A saída é o contrato verificável e a missão sucessora de IMPLEMENTAÇÃO
`M-D6-CELL-REPORT-MEETING-TARGET-IMPLEMENTATION`: adaptar o resolver existente
para produzir o alvo confiável do coordenador, com vínculos igreja/ator/inbound
e validade, testes locais de recusa e de resolução sem efeito.
Sua ficha futura fixa arquivos e testes a partir do contrato entregue.
Não implementa writer de consentimento, não liga runtime e não executa
proposta/confirmação que dependa de consentimento concedido; esses casos
continuam BLOCKED_BY_E4B.

Gate humano único: Raniel autorizar nominalmente essa implementação depois
do aceite desta missão. Não há push, merge, banco, publicação ou ativação
incluídos nessa decisão. Esta ficha abre a missão de contrato e não declara
contrato concluído ou revisado.


## Execução local registrada

Em `2026-09-13T18:57:15-03:00` a `2026-09-13T18:57:16-03:00`, o runner
offline autorizado executou somente
`backend/tests/test_cell_report_meeting_resolver.py`: `17 passed`, saída `0`
e `OFFLINE_GUARD_DENIALS=0`. Os recibos sanitizados estão em
`docs/ops/d6-cell-report-contract/pytest-resolver.json` e
`docs/ops/d6-cell-report-contract/pytest-resolver.xml`.

O candidato documental ativo é
`docs/decisions/2026-09-13-d6-cell-report-operational-contract.md`; a matriz
C01-C10 está em `docs/ops/d6-cell-report-contract/SCENARIO-MATRIX.md`. A suíte
do coordenador não foi executada porque contém gates permissivos de teste,
incompatíveis com esta missão. C06-C08 permanecem expectativas documentadas e
C09-C10 permanecem `BLOCKED_BY_E4B`.

Não houve mudança em `backend/app`, migrations, manifesto, flags, guardas,
banco, rede, runtime, caller, consentimento positivo ou efeito externo. O
estado desta ficha é `aguardando_revisao_independente`; a revisão não foi
realizada por este implementador.


## Encerramento atual

O conteúdo de abertura e execução acima permanece como histórico. A missão foi
concluída como contrato documental após a única revisão LENTE e o tratamento
objetivo do P1-A7, sem implementar a sucessora nem abrir efeitos externos.

```yaml
encerramento:
  status_final: concluída
  horario: 2026-09-13T19:42:10.523019-03:00
  sha_final: 7a7afa3d08927f3f5b2ed116638aed3131dde88b
  candidato: SHA base mais patch local não commitado; hash integral no FINAL-CANDIDATE-INDEX.json do controle
  branch_final: docs/d6-cell-report-operational-contract-20260913
  pr: nenhum
  mutacoes: worktrees locais, documentos e notas do canvas; nenhum efeito externo
  evidencias: FINAL-REPORT.md, LENTE-REVIEW.md, P1-VERIFIED.json e CLOSURE-RECEIPT.json em docs/ops/d6-cell-report-contract; pytest-resolver 17/17
  riscos_residuais: contrato não é integração; C02/C03/C05-C08 documentais; C09/C10 BLOCKED_BY_E4B; consentimento externo e deny-all preservados
  registro: docs/sprints/2026-09-13-d6-cell-report-operational-contract.md e docs/ops/POST-V1-MISSION-REGISTER.md
  proximo_gate: Raniel autorizar nominalmente M-D6-CELL-REPORT-MEETING-TARGET-IMPLEMENTATION
```
