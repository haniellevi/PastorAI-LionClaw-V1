# MISSION-CONTROL vigente, M-2026-09-14-e4b-tarefas-operacionais-source-readiness-offline

ORDEM A nominal de Raniel em 14/09/2026: EXECUÇÃO AUTORIZADA, retomada CONTROLADA de E4b somente para leitura estática. Publicação B concluída antes: PRs #393/#394/#395 abertas, sem merge. Ordem C: PR #362 intocada.

Este cabeçalho substitui os trechos de proposta abaixo. A ficha preparada é preservada para rastreabilidade, sem reabrir discussão de escopo. Worktree própria criada na base indicada, limpa antes destes artefatos; hora e fontes exatas em OPENING.json. Nenhum novo andar.

ALLOWLIST DE ESCRITA EFETIVA: somente docs/ops/e4b-source-readiness/ nesta worktree. NEXO deve escrever SOURCE-MAP.md, IMPLEMENTATION-PACKET.md e FINAL-REPORT.md. Ficha e recibos de controle são mantidos pelo Orquestrador. Não alterar ficha histórica docs/missions, sprint, fonte, manifesto ou outros arquivos. Notas somente 01/02, pelo Orquestrador.

Somente leitura estática de fontes: NÃO executar pytest, imports de produto, scripts operacionais, banco, migration, credencial, rede, LLM, caminho positivo ou concessão sintética. O comando pytest proposto abaixo foi SUBSTITUÍDO por conferência estática nesta ordem. Validação: SHA256, diff --check, completude do mapa e conferência arquivo:linha. Evidência histórica de teste/replay é apenas lida, nunca reexecutada.

NEXO gpt-5.6-terra max: análise e três documentos na worktree desta missão. LENTE gpt-5.6-terra max: EXATAMENTE uma rodada read-only em sessão/worktree próprias de cópia exata, preparada pelo Orquestrador após freeze. Nenhum especialista usa Maestri, recruta, escreve canvas ou executa efeitos externos. Achado grave P0/P1 volta a Raniel; não abrir R2/R3/R4 nem corrigir silenciosamente para obter novo parecer.

FONTES PERMITIDAS: caminhos e hashes enumerados em OPENING.json; bootstrap AGENTS.md, docs/ai/AI-BOOTSTRAP.md, docs/ai/PRD-COVERAGE.md, docs/WIKI-IGREJA12.md da base; docs/ops/MISSION-CONTROL.md, MAESTRI-PERSISTENCE-MANIFEST.md e MAESTRI-ASTRA-WORKSPACE-PLAN.md do controle. Descoberta adicional somente em backend/app/domain, backend/app/services e docs/decisions de arquivos de consentimento diretamente referenciados pelas fontes, registrando cada caminho/hash novo. Não indexar repo inteiro, abrir caminhos protegidos ou varrer conversas/históricos.

ACEITE: seis critérios do recorte abaixo, com validação exclusivamente estática; fonte ainda externa, deny-all intacto, C09/C10 BLOCKED_BY_E4B. Diferenciar ausência conhecida da fonte (objeto da missão) de achado grave no candidato, sem fingir consentimento durável. Não há novo contrato. FINAL-REPORT aponta M-E4B-TAREFAS-OPERACIONAIS-SOURCE-IMPLEMENTATION, escopo executável e dependências, sem iniciá-la.

ROLLBACK: somente patch documental novo da missão, por hashes e preservando histórico, recibos, notas e worktrees. Nenhum commit/push/PR E4b autorizado. Sem execução automática de rollback.

ÚNICO GATE HUMANO SEGUINTE: Raniel revisar o resultado e autorizar nominalmente M-E4B-TAREFAS-OPERACIONAIS-SOURCE-IMPLEMENTATION no recorte executável apurado. Se houver P0/P1, decisão sobre esse achado vem antes, substituindo esse gate. Nenhum gate intermediário de execução/revisão já autorizadas. Merge das PRs D6 permanece fora desta missão e exige frase nominal por PR, sem pedido de merge agora.

## Proposta original preservada, subordinada à ordem acima

# M-2026-09-14-e4b-tarefas-operacionais-source-readiness-offline

Status: RECORTE PROPOSTO, EXECUÇÃO NÃO AUTORIZADA NEM INICIADA.
Preparado em 14/09/2026 por ordem nominal de Raniel via CONSELHEIRO.
Esta preparação documental não retoma E4b e não constitui novo contrato D6.

## Objetivo

Conferir no código e nos recibos existentes a cadeia de autoridade da fonte
externa de `tarefas_operacionais` e entregar um pacote executável para a
implementação dessa fonte. Identificar exatamente quais componentes existentes
podem ser reutilizados e quais faltam, sem considerar staging, recibo de commit
ou alvo de reunião como consentimento vigente. A saída deve apontar
M-E4B-TAREFAS-OPERACIONAIS-SOURCE-IMPLEMENTATION, com allowlist e dependências
fechadas, sem propor outro contrato ou abrir caminho positivo.

## Preflight e isolamento propostos

Workspace: IGREJA 12 - MANUAL; terminal Orquestrador.
Repo: clone local PastorAi-1.0, haniellevi/PastorAI-LionClaw-V1.
Preparação no controle, branch codex/maestri-astra-workspace-plan.
Base documental do controle após persistência da ficha E4b:
bc75b1518f037d51fae4df6e79945a0ce6e58bc7.

Worktree FUTURA: .worktrees/e4b-tarefas-operacionais-source-readiness-20260914.
Branch FUTURA: docs/e4b-tarefas-operacionais-source-readiness-20260914.
Base proposta: 7b0b6bfd0e1b842d214576a3a1a7eff02acbb307, candidato E4b local
catalog-bound v3. Não representa main atual nem autorização operacional.
Nenhuma worktree/branch foi criada nesta preparação. Antes da futura abertura,
conferir base, estado limpo e hooks efetivos sem modificá-los; preencher hora real.
Não criar andar visual. Grafo desabilitado; busca limitada à allowlist.

Fontes locais somente leitura: ficha E4b histórica persistida; recibo replay77
em docs/e4b-replay77-receipt-20260913 no commit
67659a3c69d94af465e5d3994b060c5e8dd89547; código E4b no SHA proposto; contrato
D6 e FINAL-REPORT da integração na worktree de origem. D6 continua ancorado em
7a7afa3d08927f3f5b2ed116638aed3131dde88b mais patches locais inventariados.
Os quatro commits de fichas não incorporaram esses patches de código/relatório.

## Escopo permitido proposto

Leitura estática das fronteiras E4b C0/C2/C3, purpose_consent e gate do
coordenador; confronto de versões, autoridade humana, igreja, pessoa, finalidade,
termo, origem, revogação, retenção e proveniência durável. Inventariar por
arquivo:linha o que existe, o que está apenas especificado e o que falta.
Conferir recibos já produzidos, sem repetir replay ou acessar seus bancos.
Quando um artefato faltar, registrar ausência e impacto, sem recriar prova.

Allowlist de escrita futura: esta ficha; docs/ops/e4b-source-readiness/
(SOURCE-MAP.md, IMPLEMENTATION-PACKET.md, FINAL-REPORT.md e recibos sanitizados);
docs/sprints/2026-09-14-e4b-source-readiness.md. Código, SQL, catálogos, manifesto,
flags e candidatos anteriores são somente leitura.

Orquestrador prepara e controla evidência; NEXO gpt-5.6-terra max para análise
delimitada em worktree própria, LENTE gpt-5.6-terra max para uma revisão read-only
em sessão e worktree distintas do candidato exato. Reutilizar terminais e
conferir configuração efetiva antes da futura delegação. Nenhum acionado agora.

## Critérios de aceite fechados

1. SOURCE-MAP distingue evidência de gravação/reconciliação de autoridade para
   consentimento vigente; não converte CONFIRMED em autorização de finalidade.
2. Cada requisito de igreja/pessoa/finalidade/termo/origem/revogação/proveniência
   tem fonte exata, SHA/hash e estado implementado, ausente ou não comprovado.
3. Deny-all permanece intacto. C09/C10 continuam BLOCKED_BY_E4B. Não há writer
   fictício, mint/permit positivo, Pessoa.consentimento como substituto ou bypass.
4. O pacote seguinte enumera arquivos a implementar, serviços a reutilizar,
   testes negativos e dependências externas que impedem operação. Nenhuma
   suposição sobre concessão ou disponibilidade da fonte é tratada como prova.
5. Uma rodada LENTE com achados por arquivo:linha e verificação objetiva de
   eventual correção documental; FINAL-REPORT aponta implementação, não contrato.
6. Diff somente documental; testes definidos abaixo sem falha/erro/skip, sem
   inferir RLS, locks, concorrência ou persistência real a partir de teste offline.

## Testes propostos, não executados nesta preparação

Verificação principal: rastreabilidade de todos os itens do SOURCE-MAP,
comparação de hashes com fontes pinadas e git diff --check. Registrar comandos,
horário, ambiente, SHA base e hash do patch documental completo, incluindo novos.

Regressão mínima offline da política de privacidade pelo runner já aprovado:

```sh
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 backend/.venv-runtime/bin/python -I -B backend/tests/test_source_contact_privacy.py
```

Runner SHA256: 0131eb6d64607da7ff4ffc6745223e0590625b280319fd57f3d73af7cb74cbfd;
Python 3.13.14. Conferir ambos antes de uso. Não executar suítes de consentimento
com concessões sintéticas, PG17, fixtures de banco, aplicação ou testes positivos.
Esse teste não valida o conteúdo factual do mapa; a revisão de fontes o faz.

## Riscos de tenant

Confusão entre igreja, pessoa e operador: exigir vínculos originados no backend
confiável, jamais no modelo. Reuso de prova entre finalidades/igrejas e estado
revogado ou desatualizado: mapear vinculação, frescor e revogação nas fontes.
Ausência de regra implementada deve resultar em bloqueio explícito, nunca
default permissivo. Não levar dados vivos para documentos ou testes. Nenhum
resultado desta missão prova RLS ou isolamento de uma instância de banco.

## Fora de escopo

Implementação ou ativação da fonte, caller/runtime/worker/webhook, migrations
(inclusive draft/prepare-head/replay), banco local/DEV/PROD, credenciais, rede/LLM,
dados reais, concessão/permit positivo, envio, publicação, push/PR/merge/deploy,
manifesto, grants, flags e incidente PROD #392. Nenhum commit da proposta ou do
futuro candidato é autorizado pela preparação atual. Não apagar notas do canvas.

## Rollback

Reverter somente o patch documental novo da missão, conferindo hashes e
preservando recibos, notas, worktree e histórico. Não executar automaticamente,
não usar reset --hard/clean e não desfazer candidatos ou commits anteriores.
Não existe alteração de banco ou efeito externo a compensar neste recorte.

## Único gate humano atual

Raniel revisar este recorte e autorizar nominalmente a execução local/offline
de M-2026-09-14-e4b-tarefas-operacionais-source-readiness-offline. A autorização
de preparar foi consumida; execução permanece fechada. Parecer dos dois
conselheiros subsidia essa decisão sobre suficiência do recorte e dependências
da implementação, sem criar gate intermediário. Publicação e exclusão de notas
continuam fora desta decisão e não são solicitadas agora.

## Encerramento do Orquestrador em 2026-09-14T08:55:22.317361-03:00

Identificação canônica: M-2026-09-14-e4b-tarefas-operacionais-source-readiness-offline.
Execução estática autorizada encerrada; uma única revisão LENTE APTO, nenhum
P0/P1/P2. O período 08:24:11 a 08:32:26 registrado acima é a janela de coleta
anotada pelo NEXO, não o encerramento da redação ou da revisão. O encerramento
real está em CLOSURE-RECEIPT.json; a LENTE registrou verificação às 08:52:48 -03.

Candidato revisado: base 7b0b6bfd0e1b842d214576a3a1a7eff02acbb307 + patch
81b5c39b193ef8106419e3ede1d4e6786871a06f38ee76c2ccc3f0deeab41ecd, cinco documentos.
Cópia revisada preservada integralmente na worktree separada. Após revisão,
somente este encerramento, parecer transcrito, ficha e recibo foram acrescidos;
SOURCE-MAP e IMPLEMENTATION-PACKET mantêm os bytes revisados. Índice final
com hashes está no controle docs/ops/e4b-source-readiness/FINAL-CANDIDATE-INDEX.json.
Nenhum teste executado; validação de hashes, escopo e whitespace. Código,
18 fontes pinadas, manifesto e flags intactos; nenhum commit/publicação E4b.

O diagnóstico está concluído; a fonte operacional continua ausente no recorte.
A próxima missão apontada é M-E4B-TAREFAS-OPERACIONAIS-SOURCE-IMPLEMENTATION.
Gate único: Raniel revisar a entrega e autorizar nominalmente a implementação
com as pré-condições de governança/fonte expressas no pacote. Não executar
essa missão agora, não abrir outro contrato e não inferir consentimento positivo.
Deny-all e C09/C10 BLOCKED_BY_E4B permanecem; sem banco/migration, credencial,
rede de produto, caller/runtime, envio, ativação, DEV/PROD ou incidente #392.

Rollback: somente patch documental local, conferindo hashes e preservando
histórico, recibos, notas e worktrees. Nenhum rollback executado.
