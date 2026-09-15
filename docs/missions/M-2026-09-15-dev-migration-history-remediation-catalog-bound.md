---
id: M-2026-09-15-dev-migration-history-remediation-catalog-bound
status: proposta_de_recorte_pendente_de_autorizacao
prepared_at: 2026-09-15T00:50:00-03:00
proposal_authorized_by: Raniel
execution_authorized: false
environment: local; DEV somente leitura futura por operador humano; PROD fora
---

# M-2026-09-15-dev-migration-history-remediation-catalog-bound

## Princípio de decisão

Não se corrige um ledger antes de distinguir histórico ausente de efeito físico
ausente. O primeiro resultado da missão deve classificar, com evidência de
schema, cada uma das 44 migrations que estão no catálogo e não estão no ledger
público DEV. Nenhuma classificação pode nascer só do nome do arquivo, da ordem
do catálogo ou da presença de objetos parecidos.

A estratégia escolhida para DEV deve ensaiar o caminho necessário em PROD. Como
PROD também diverge e não pode ser recriado, uma recriação limpa de DEV prova
uma instalação nova, mas não prova sozinha a remediação de um ambiente legado.

## Ficha Mission Control proposta

```yaml
id: M-2026-09-15-dev-migration-history-remediation-catalog-bound
objetivo: determinar o estado físico das 44 migrations ausentes do ledger público DEV e, após decisão humana separada, preparar uma remediação de histórico e um executor catalog-bound que possam ensaiar com segurança o caminho futuro de PROD
preflight:
  repositorio: github.com/haniellevi/PastorAI-LionClaw-V1, clone local
  branch_consultada: codex/maestri-astra-workspace-plan
  sha_efetivo_da_proposta: bc75b1518f037d51fae4df6e79945a0ce6e58bc7
  sha_base_planejado: e1da65d0a6fa5286674f425f855600eb3e4982bb
  worktree_da_proposta_limpo: false; alterações anteriores do controle foram preservadas e esta proposta adiciona somente este arquivo
  ambiente: local; nenhuma sessão DEV, VPS ou PROD nesta proposta
  horario: 2026-09-15T00:50:00-03:00
  runbook_lido: docs/ops/MISSION-CONTROL.md; docs/ops/MAESTRI-PERSISTENCE-MANIFEST.md; pacote integrado pela PR #399 em docs/ops/migration-head77-dev-apply-readiness/
  grafo: não disponível; code-review-graph permanece desabilitado
worktree_planejado_f1: .worktrees/dev-migration-history-remediation-f1-20260915
branch_planejada_f1: docs/dev-migration-history-remediation-f1-20260915
sha_base: e1da65d0a6fa5286674f425f855600eb3e4982bb
especialistas_planejados:
  - FORJA, gpt-5.6-terra max, prepara inventário e consulta F1 no worktree próprio
  - LENTE, gpt-5.6-terra max, exatamente uma rodada somente leitura sobre o candidato F1 congelado em worktree própria
arquivos_permitidos_f1:
  - docs/missions/M-2026-09-15-dev-migration-history-remediation-catalog-bound.md
  - docs/ops/dev-migration-history-remediation/**
criterios_de_aceite_f1:
  - inventariar as 44 migrations ausentes do ledger público, seus efeitos esperados e a evidência de schema necessária para cada uma
  - anexar as 8 posições divergentes do ledger público, comparando a ordem aplicada com a ordem do catálogo e registrando dependências relevantes para o futuro epoch/cutover
  - classificar cada item como PHYSICAL_EFFECTS_PRESENT, PHYSICAL_EFFECTS_ABSENT, PARTIAL_OR_CONFLICTING ou NOT_SCHEMA_DECIDABLE, sem inferir aplicação quando a evidência não for conclusiva
  - responder com contagem e lista completas se os efeitos das 44 migrations já existem no schema DEV, não existem, existem parcialmente ou não são decidíveis por metadados de schema
  - substituir a consulta ACL inconclusiva por uma leitura que derive todos os grantees diretos de relacl/aclexplode e enumere pg_default_acl do schema public e os defaults globais com defaclnamespace=0 antes de classificá-los; qualquer role fora da allowlist deve produzir UNEXPECTED_CUSTOM_GRANTEE sem expor seu nome
  - usar statements de supabase_migrations.schema_migrations somente como evidência secundária sobre execução pelo fluxo nativo, comparando hash ou padrões não sensíveis sem imprimir o SQL armazenado, sem ler dado de domínio e sem aceitar essa coluna como prova isolada de aplicação
  - reexecutar o preflight em DEV somente em transação REPEATABLE READ READ ONLY, por Raniel, com rollback final e saída sanitizada
  - vincular a saída a um target binding técnico opaco de DEV, sem host, usuário, DSN, IP, segredo ou identificador reutilizável
  - obter de Raniel uma declaração sanitizada DEV_DATA_DISPOSITION sobre existência de dado real, PII e valor de preservação antes de considerar recriação
  - preservar public.schema_migrations e supabase_migrations.schema_migrations sem insert, update, delete, backfill ou reordenação
  - produzir pacote de decisão F1 que compare A e B com a evidência coletada e recomende uma estratégia
  - executar exatamente uma rodada LENTE sobre o candidato F1 congelado
riscos_de_tenant:
  - grant direto a role customizada ficar invisível; impedido por enumeração anterior à classificação e falha fechada diante de qualquer grantee inesperado
  - objeto homônimo ou parcial ser tratado como migration aplicada; impedido por assinaturas estruturais por migration e estado PARTIAL_OR_CONFLICTING
  - target DEV incorreto; impedido por binding opaco produzido pelo operador e conferido no mesmo recibo da coleta
  - leitura de payload, PII ou dado pastoral; proibida, com consultas limitadas a pg_catalog, information_schema, ledgers e contagens/metadados aprovados
  - perda de dado ao escolher recriação; opção B bloqueada até DEV_DATA_DISPOSITION provar NO_VALUE_NO_PII e Raniel autorizar separadamente a ação destrutiva
  - ensaio não representar PROD; estratégia precisa demonstrar como o mesmo epoch/cutover e executor tratariam a divergência de PROD sem recriação
  - default privilege de schema ou global conceder acesso futuro a objeto ainda ausente; impedido por inventário de pg_default_acl, incluindo defaclnamespace=0, antes da classificação ACL
  - ordem divergente do ledger alterar dependências; impedido pelo anexo das 8 posições e por decisão explícita no desenho de epoch/cutover
plano_de_teste_f1:
  - teste source-only confirma allowlist de comandos SQL, BEGIN READ ONLY, timeouts e ROLLBACK
  - PostgreSQL 17 local descartável prova que a consulta ACL detecta role customizada sem publicar seu nome
  - teste de cobertura exige 44 de 44 itens, anexo das 8 posições divergentes, evidência por item e nenhuma classificação positiva sem assinatura suficiente
  - teste de target binding rejeita ausência, troca ou reuso de binding
  - pytest backend/tests/test_source_contact_privacy.py
  - git diff --check
plano_de_rollback_f1:
  - descartar somente o patch e a worktree F1 se o recorte for rejeitado
  - em DEV, usar exclusivamente transação read-only e ROLLBACK; diante de erro antes do rollback, Raniel executa somente ROLLBACK e encerra
  - nenhuma compensação de banco é prevista em F1 porque nenhuma escrita é permitida
fora_de_escopo_agora:
  - criar worktree ou branch de execução, acionar especialista ou iniciar F1
  - conectar a DEV, VPS ou PROD; ler dado de domínio, PII, segredo, host, usuário, DSN ou credencial
  - criar ou aplicar migration, corrigir ledger, criar epoch, executar cutover ou aplicar SQL
  - implementar ou publicar executor, commit, push, PR, merge, deploy, restart ou ativação
  - alterar manifesto, grants, flags, runtime, billing, envio ou AgentConfig
proximo_gate: Raniel autorizar nominalmente o recorte F1 desta ficha após os pareceres dos dois conselheiros
encerramento:
  status_final: pendente; proposta não executada
  sha_final: nenhum
  branch_final: nenhuma
  pr: nenhum
  mutacoes: somente esta ficha local, sem ambiente ou Git externo
  evidencias: pareceres dos conselheiros pendentes
  riscos_residuais: estado físico das 44 migrations, disposição dos dados DEV, target binding e estratégia ainda não determinados
  registro: esta ficha; notas 01/02 permanecem inalteradas até decisão de Raniel
```

## Primeiro entregável obrigatório de F1

F1 deve produzir uma matriz com exatamente 44 linhas. Cada linha liga uma
migration ausente do ledger público a seus efeitos esperados, às consultas
read-only usadas, ao resultado DEV e a uma destas classificações:

- `PHYSICAL_EFFECTS_PRESENT`: todas as assinaturas estruturais necessárias
  existem e coincidem;
- `PHYSICAL_EFFECTS_ABSENT`: nenhuma assinatura necessária existe;
- `PARTIAL_OR_CONFLICTING`: há efeito parcial, objeto homônimo ou assinatura
  divergente;
- `NOT_SCHEMA_DECIDABLE`: o arquivo contém efeito de dados ou outro efeito que
  metadados de schema não conseguem provar sem leitura proibida.

Somente `PHYSICAL_EFFECTS_PRESENT` permite concluir que os efeitos físicos já
existem. Ela não permite escrever uma entrada no ledger nem afirmar como ou
quando a migration foi aplicada. Qualquer item parcial ou não decidível bloqueia
uma fila de aplicação até decisão humana específica.

A matriz deve vir acompanhada de um anexo das 8 posições divergentes do ledger
público, comparando a ordem aplicada com a ordem do catálogo e registrando
dependências que afetem o epoch/cutover. A coluna `statements` do ledger nativo
pode servir como evidência secundária de execução pelo fluxo Supabase, mas seu
SQL nunca pode ser impresso: somente hash ou padrões não sensíveis podem entrar
na evidência. Ela não prova aplicação sozinha nem autoriza leitura de dados de
domínio.

Antes de avaliar a estratégia B, o pacote exige uma declaração de Raniel com um
destes valores, sem dados ou contagens sensíveis:

- `DEV_DATA_DISPOSITION=NO_VALUE_NO_PII`;
- `DEV_DATA_DISPOSITION=VALUE_OR_PII_PRESENT`;
- `DEV_DATA_DISPOSITION=UNKNOWN`.

Somente o primeiro valor torna B elegível para decisão. Ele não autoriza apagar
ou recriar o ambiente.

## Estratégias a comparar após F1

| Critério | A. Reconciliar o DEV divergente | B. Recriar um DEV limpo e aplicar 77 em ordem |
| --- | --- | --- |
| Objetivo | Preservar o ambiente e criar epoch/cutover explícito para o histórico divergente | Validar instalação limpa em projeto ou branch novos quando DEV for descartável |
| Custo estimado | Alto: 44 assinaturas, decisão por lacuna, desenho de epoch/cutover e executor capaz de falhar fechado | Médio se não houver dado/configuração de valor; alto se integrações e configuração precisarem ser reconstruídas |
| Risco principal | Duplicar efeito já existente ou legitimar drift se uma assinatura for classificada incorretamente | Perder dado/PII, omitir configuração e produzir um ensaio que não representa o PROD legado |
| Ledgers existentes | Permanecem imutáveis; nenhum backfill ou reordenação | Ambiente antigo é preservado até autorização destrutiva; o novo começa vazio e registra a ordem real |
| Valor como ensaio de PROD | Alto, pois exercita divergência, epoch/cutover e executor sem depender de recriação | Parcial: prova instalação limpa, mas não prova reconciliação de PROD; exige ensaio adicional do caminho A sobre snapshot sanitizado |
| Pré-condição decisiva | Matriz 44/44 conclusiva o bastante para desenhar o epoch sem inferência | `DEV_DATA_DISPOSITION=NO_VALUE_NO_PII` e autorização nominal destrutiva separada |
| Rollback | Antes do commit de banco, rollback transacional; depois, somente compensação forward-only aprovada | Manter o DEV antigo intacto até aceite do novo; troca de alvo e descarte são gates independentes |

## Recomendação explícita

Recomendação preliminar: **estratégia A**. Ela custa mais, porém é o único dos
dois caminhos que ensaia diretamente o problema que também existe em PROD, onde
recriação não é opção. F1 pode mudar detalhes do desenho, mas não deve trocar
para B só por conveniência operacional.

A estratégia B deve permanecer alternativa condicionada. Se F1 provar que DEV
não contém PII nem dado de valor e que os efeitos físicos ausentes justificam um
ambiente novo, B pode validar a instalação limpa das 77 migrations. Mesmo nesse
caso, ela não substitui o ensaio do epoch/cutover necessário para PROD.

## Fases e gates futuros

### F1: verdade física, somente leitura

Entregas: inventário estático dos 44 arquivos, anexo das 8 posições divergentes,
consulta ACL corrigida incluindo `pg_default_acl` de schema e global, consulta
de assinaturas estruturais, uso limitado do ledger nativo por hash ou padrões
não sensíveis, target binding opaco, declaração de disposição dos dados,
transcrição DEV sanitizada e matriz 44/44. Raniel executa a consulta DEV; agentes
não abrem sessão autenticada. A rodada única da LENTE ocorre somente depois de
congelar o candidato F1.

Gate F1, ainda não concedido: Raniel autoriza o recorte F1 e a coleta humana
read-only do pacote exato.

### F2: decisão de estratégia e epoch/cutover

Somente após F1 aceita, produzir a decisão A/B, o modelo de epoch/cutover e o
tratamento de cada classe, preservando os dois ledgers sem backfill ou
reordenação. Cada item `NOT_SCHEMA_DECIDABLE` deve receber um guarda idempotente
revisável ou uma decisão humana específica; enquanto isso não ocorrer, ele
bloqueia a fila. Nenhuma escrita ocorre em F2.

Antes de fechar o desenho como ensaio de PROD, F2 deve comparar a divergência
DEV com uma coleta equivalente, somente leitura, em PROD. Essa coleta futura
exige gate nominal próprio, limita-se a metadados e ledgers, usa target binding
sanitizado e não é autorizada por esta proposta.

Gate F2, futuro: Raniel autoriza primeiro a coleta read-only equivalente em PROD
e, após comparar os dois ambientes, escolhe nominalmente A ou B e autoriza o
desenho exato. Se B for escolhida, a criação, troca ou exclusão de
projeto/branch DEV exige autorização destrutiva própria e
`DEV_DATA_DISPOSITION=NO_VALUE_NO_PII`.

### F3: executor catalog-bound e aplicação DEV

Implementar primeiro, offline, um executor preso ao SHA, catálogo, epoch,
target binding, principal, PostgreSQL 17, TLS e decisão humana. O candidato deve
falhar fechado, passar PostgreSQL 17 descartável e revisão independente antes
de publicação. A aplicação DEV só pode ser executada pelo Raniel, com pacote e
rollback do SHA exato, depois de o executor revisado estar integrado.

Gate F3, futuro e independente: Raniel autoriza nominalmente a aplicação DEV do
candidato exato. Merge do executor e aplicação são decisões separadas.

Se A ou B exigir uma migration nova para epoch, ledger ou schema, a missão para
antes da autoria. Criar a migration pelo fluxo `new_migration.py draft` e
`prepare-head`, revalidar o catálogo e executar replay PostgreSQL 17 exigirão
gate nominal próprio; nenhuma migration nova é autorizada por esta proposta.

## Rollback e compensação futura

- F1: rollback da transação read-only e descarte do patch local.
- F2: reverter somente documentos locais; nenhuma decisão de estratégia produz
  escrita por si só.
- F3 antes do commit de banco: rollback transacional e recibo de aborto.
- F3 depois de commit comprovado: somente compensação forward-only prevista e
  revisada no pacote; sem downgrade destrutivo ou alteração retroativa dos
  ledgers.
- B: preservar o DEV atual até o novo ambiente passar aceite; troca de alvo,
  revogação e descarte são gates separados e nunca decorrem do teste verde.

## Limites desta proposta

Esta ficha não prova o estado físico das 44 migrations, não afirma que DEV é
descartável e não autoriza F1, F2 ou F3. Nenhum banco, VPS, PROD, migration,
executor, branch de missão, especialista, nota do canvas ou efeito externo foi
acionado para produzi-la.
