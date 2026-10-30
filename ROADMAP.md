# Igreja 12 — roteiro único

## Fase 1 — transporte observado e consolidação enxuta do release (29/10/2026)

Base integrada `64853268a4c1623f5b9d4906457335fcb7849931` (#597–#604). Esta seção consolida o caminho crítico mínimo até o release restrito do piloto Filadélfia e substitui a cadência anterior de microetapas de laboratório offline (A1/I0: extração manual `.deb`, `unshare/chroot`, CPython 3.13.18 e VM QEMU sem rede), que não é retomada. O arquivamento dos diretórios temporários `/tmp/igreja12-*-20261029/` fora do repositório é registro do operador, não verificável a partir do repositório nem reverificado nesta fatia.

### Escopo e limites desta fatia (A3 parcial — contrato/encoder)

**Esta fatia é contrato + encoder de comandos sobre um driver fornecido pelo chamador. Não é executor real, não é inventário real, não é implementação de ingresso e não é autorização operacional.** A3 **não** está completa.

- `deploy/first_transition_host_transport.py`: `SimulatedHostTransport` intacto; `ObservedHostTransport` valida forma e fixa identidades das três dependências de suporte (`redis`, `evolution-postgres`, `evolution-api`), dos três serviços Compose legados + `broadcast-worker` avulso e `support_digest`; lê metadados de filas (`queue_metadata` via `redis-meta`, sem payloads) e codifica `restart-always`, `start`, `open-ingress`. Todos os valores são **reportados pelo driver**.
- `deploy/first_transition_host_contract.py`: `LocalHostContract` intacto; `ObservedHostContract` grava recibos `evidence='driver-reported'`, `host_verified=False`, `quiescence_proven=False`. `resume_legacy` pré-DDL (`backend → queue-worker → broadcast-worker → cron-worker` → `open-ingress`) revalida, imediatamente antes de cada efeito e após cada observação: ausência de marcador DDL no diário, ingresso bloqueado durante toda retomada parcial e antes de autorizar sua abertura, e igualdade da fila com a base assentada antes do **primeiro início efetivamente observado** (início recibado, ou intencionado com `started` comprovadamente novo; mera intenção não conta, e serviço `running` com `started` inalterado é inconsistência recusada antes de efeitos; replay incluído). Mudanças de fila após um serviço realmente iniciado são legítimas. Cada efeito de retomada (`start`, `restart=always`, `open-ingress`) também passa por uma guarda pré-efeito que julga, sem nova leitura, a **última observação feita pelo próprio transporte** (DDL no diário, ingresso, identidades, serviços e fila antes do primeiro início); no `ObservedHostTransport`, o comando só é emitido depois que a guarda aceita, e o transporte sem guarda recusa (um port alternativo é parte da base de confiança; o contrato só detecta uma guarda omitida após a chamada); é só encoder, não autoridade de retomada. Não há atomicidade sobre driver/host: resta a janela entre essa última observação e o efeito.
- `deploy/first_transition_adapter.py`: `LocalTransition` (banco local descartável) compõe-se **somente** com `LocalHostContract` simulado e diário válido; `ObservedHostContract`, recibos `observed-host` e evidência `LocalEvidence.observed` são recusados antes de `db.observe` ou de escrita no diário. Os diários são separados nos dois sentidos: `LocalTransition` (inclusive sem host) recusa diário com eventos `observed-host-*` na construção e antes de cada execução/etapa; `ObservedHostContract` recusa diário com `adapter-*`/`local-host-*` em `contain`/`assert_contained`/`resume_legacy` antes de qualquer leitura ou efeito do port (com marcador DDL, `post-ddl-resume-forbidden` mantém prioridade). `LocalEvidence.observed` é apenas envelope de metadados: sua validação não autoriza `LocalTransition` nem prova produção. Pins SQL (`afdfb78d71a53f2861632806e13cdda4662d7d63`) e executor (`37c7d68d60b6f86cfb1fe75d4c720530537845d6`) preservados; `plan.digest` reflete os novos hashes de `adapter_sources()`.

### Bloqueadores pendentes antes do pacote operacional de produção (Pacote 4)

1. **Driver real** de inventário/ingresso/executor de host: implementação e revisão independentes ainda não existem; até lá nenhum recibo é evidência de host (`host_verified=False`).
2. **Prova de banco** de que nenhuma DDL ocorreu antes de `resume_legacy` (leitura do ledger/marcador no BD); a ausência de marcador no diário não prova nada sobre DDL feita fora dele.
3. **Prova de ingresso e de escritores desconhecidos** independente do driver.
4. **Fila/quiescência**: contagem por chave declarada não comprova conteúdo, chaves não declaradas nem `notification_outbox`; não existe ferramenta de "comprovar quiescência".
5. **Recuperação nominal de contenção parcial/saída anormal** (ex.: `exit 143`, timeout de `wait`): hoje `contain` recusa fail-closed sem SIGKILL nem retomada. O replay de `contain` não repete o sinal já intencionado para o mesmo papel, mas **pode avançar a papéis seguintes** após um timeout (desligar restart, sinalizar e esperar outros serviços); não é "sem efeitos". `resume_legacy` sobre contenção parcial recusa sem efeitos. O procedimento manual de retorno precisa ser definido e revisado.
6. **Recuperação de retomada parcial**: se `resume_legacy` parar no meio (ex.: serviço iniciado sai antes de `restart=always` → `resume-not-fresh`; DDL, ingresso, identidade ou fila recusados após o primeiro início), a ferramenta fica parada com ingresso bloqueado e parte dos serviços já de pé, sem recuperação automática; o procedimento precisa ser definido e revisado.
7. O token `RESUME:<fingerprint>` vincula a identidade do host no diário; **não** representa aprovação humana nem autoriza ação.

### Plano enxuto em 5 fases e pacotes de aprovação

| Fase | Escopo objetivo | Portão de aprovação humana |
|---|---|---|
| **Fase 1 (atual)** | Consolidar roteiro enxuto e entregar A3 **parcial**: `ObservedHostTransport` + `ObservedHostContract` + `resume_legacy` como contrato/encoder sobre driver do chamador, com suíte sintética. Revisão independente concluída em 30/10/2026: GO para PR parcial, sem P0/P1, por GPT-6.1-Sol High e Sarah Opus 5.5 High. | **Pacote 1:** commit, push em branch própria e abertura da PR (sem merge). |
| **Fase 2 (A4)** | Acompanhar os 6 workflows automáticos na PR, integrar na `main`, confirmar `main` verde e gerar o pacote `.tar.gz` com `deploy/package_backend_release.py`. | **Pacote 2:** merge na `main` após CI verde. |
| **Fase 3 (A5 + A6)** | Preflight somente leitura no banco e VPS de PROD (`release_preflight.py`, `backend-release-ledger.sql`, `backend-release-inventory.sql`) e prova de backup/restore real (`backup-production.sh`) em banco temporário isolado antes de qualquer DDL. Em paralelo: implementar e revisar o driver real e as provas de BD/ingresso/escritores/fila e as recuperações (bloqueadores 1–6). | **Pacote 3:** leitura read-only em PROD + execução de backup e restore em alvo isolado. |
| **Fase 4 (A7 + A8 + A9)** | **Pré-requisito: bloqueadores 1–6 resolvidos e revisados.** Na janela aprovada: conter os 4 serviços antigos (`restart=no` + `SIGTERM`) antes de fechar gates (evitando que o `cron-worker` cancele pendências de `notification_outbox` durante a janela) → verificar quiescência (ferramenta pendente) → backup novo da janela → aplicar as 51 migrations (43 TX / 8 NT) uma a uma via `migrate.py` → subir os 4 serviços novos + painel com funções fora do escopo desligadas → smoke `/health` e `/ready`. | **Pacote 4:** janela operacional de produção com horário, SHA e contingência definidos. |
| **Fase 5 (A10)** | Reabrir envio restrito ao piloto Filadélfia (equipe interna), monitorar filas/erros e concluir o aceite pastoral (20 conversas/cenários G12). | **Pacote 5:** reabertura do gate do piloto Filadélfia. |


**Validação de fechamento (30/10/2026):** sete suítes sintéticas pertinentes com Python 3.13.15: **333 passed, 49 subtests passed**; Ruff e `git diff --check` aprovados. Revisores avaliaram os bytes fornecidos; não executaram essa suíte. A suíte completa com casos PostgreSQL **não foi validada** (URL de fixture ausente), e os resultados do CI devem ser conferidos pelo SHA exato na PR; testes locais não os substituem. GO limitado à **PR parcial**. Pacote 1 autorizado nominalmente em 30/10/2026: commit, push sem force e abertura da PR; sem merge, dispatch manual, deploy, reativação, VPS ou produção. Antes da publicação foram reconfirmados DEV disabled_manually, DEV_PIPELINE_ENABLED=false, zero projetos Vercel ligados ao repositório e zero publicações ativas nos projetos do painel; deploymentEnabled=false permanece no código.

**P2 não bloqueantes desta PR:** port alternativo e diário do contrato observado permanecem na base de confiança do chamador; callback que contamine o diário durante execução local pode deixar diagnóstico `adapter-failed` antes da recusa; ampliar a matriz de estados intermediários continua melhoria de teste. Não há isolamento contra código malicioso no mesmo processo nem atomicidade entre observação e efeito. Implementação do driver real, prova operacional e recuperação nominal continuam bloqueadoras de produção, conforme itens 1–6.

## Fatia local — segurança do controlador (29/10/2026)

Base integrada `609952de`. Commit/push sem force e PR separada autorizados
em 29/10/2026, após reconferir suspensões; merge não autorizado.
Sem dispatch manual, deploy, reativação, novos ensaios físicos locais, VPS
ou produção. OPERATIONAL_AUTHORIZATION=BLOCKED para essas operações.
Pré-publicação: DEV disabled_manually e DEV_PIPELINE_ENABLED=false; painel
Vercel sem vínculo Git, nenhum projeto vinculado a este repositório na equipe,
nenhuma publicação em andamento; deploymentEnabled=false preservado.
Quatro checks obrigatórios app15368, strict=true e enforce_admins=true.
Abertura da PR aciona seis workflows de testes, incluindo recursos sintéticos
descartáveis no GitHub; não aciona publicação/deploy. Evidências de CI ficam
na PR por head exato; a validação local não as substitui.
Sinais SIGINT/SIGTERM/SIGHUP geram relatório e limpeza limitada; segunda
interrupção encerra a tentativa de limpeza. Subprocesso CLI próprio é encerrado
com espera limitada, nunca grupo alheio. Falha primária permanece fail.
CID ausente/vazio nunca é adotado por nome: preserva resíduo para recuperação
nominal. Mutação sem resposta confirmada deixa registro pending persistente;
mesmo ps vazio não comprova limpeza e retorna incomplete. Não apagar o registro
para forçar sucesso. Limpeza-only não resolve incerteza por conta própria.
Após decisão nominal sobre o resíduo, registrar o desfecho em relatório novo
e usar novo run/estado; preservar o estado incerto como evidência.
Remoção exige ID do cidfile do run, nome e label; varredura residual por label
apenas acusa recursos, nunca remove desconhecidos. Estado exclusivo persistente
0700 fora de árvores com marcador .git, sem symlink ou componentes ..; lock exclusivo e intent atômico antes de create; scope
vinculado a imagem/run/daemon. Primeiro sinal durante cleanup permite concluí-la;
segundo a interrompe. CLI em nova sessão, sinal durante spawn é diferido até
registrar o filho. Janela de reaping tem até dois segundos além do timeout.
Modos com efeito agora exigem --state-dir e --daemon-id além de --run-id/--report;
cleanup-only lê o estado original e exige relatório novo. Comandos históricos
sem esses argumentos não devem ser reutilizados. Nenhum desses modos executado.
Overrides remotos/contextos recusados antes de processos; config Docker vazia,
socket fixo e daemon nominal/Linux não-rootless conferidos antes de mutação.
Isso reduz uso acidental, não comprova isolamento: socket pode ser túnel e o ID
aprovado precisa pertencer a ambiente descartável. VPS/produção proibidos.
Snapshot inicial recusa com código fixo sem DDL ou detalhes de driver.
Pins SQL/executor, migrations e gates intactos; backup muda adapter_sources/
plan_digest, recibos anteriores recusados por plan-changed. Não contornar.
Testes só com doubles e sentinelas anti-processo/rede; PG, Docker, sinais reais,
SSH e provedores não executados. Validação local: 162 testes e 2 subtestes
aprovados; Ruff e git diff --check aprovados. CI automático acompanha a PR.
Revisão final Sarah e limites registrados na entrega.
Nenhuma nova autorização operacional é concedida pelo código/documento.

Quatro P2 corrigidos localmente: interrupção abortável somente durante
communicate, no máximo uma exceção por espera e sem substituir exceção em
propagação; poll/reaping protegidos; relatório exclusivo 0600 fora de checkout,
sem symlink ou ..; testes de symlinks, dono do lock e falhas concorrentes.
Pending correlaciona operação, índice, nome e ID conhecido. Cleanup informa
códigos sanitizados por recurso; registro antigo/inválido vira pending-unverified.
Nenhum texto arbitrário de erro/estado é copiado para o relatório.
Revisão Sarah Opus 5.5 high concluída: GO local, P0=0/P1=0/P2=0;
quatro P2 fechados por leitura dos bytes enviados. Revisora não executou testes.
Limites: sinal pode ser adiado até timeout; reaping pode falhar; sinal antes
de instalar handlers pode deixar relatório vazio, sem efeito Docker. Parecer
e manifesto no pacote local controller-safety-p2-20261029. Sem autorização operacional.



## Estado vigente — #601 integrada e publicação da #602 autorizada (29/10/2026)

#601 integrada por merge commit `19eae0b0c140ea36d7ea93a5874867bf53c34f70`,
head autorizado `83f962a1`, sem bypass ou exclusão da branch. Os seis workflows
push da nova main passaram: backend40828306185, frontend40828306170,
E2E40828306164, RLS40828306174, tooling40828306177, sintético40828306165.
Nenhum dispatch manual executado. A PR601 havia aprovado 98 testes do adaptador
no CI, sem skips, com PostgreSQL descartável removido; isso não valida a #602.

Candidato #602: composição do head `af5158d5` com esta main; commit/push sem
force, base main e acompanhamento CI autorizados pelo dono em 29/10.
Conflitos de testes resolvidos preservando as duas séries; Vercel false global
herdado da main intacto. DEV disabled_manually e DEV_PIPELINE_ENABLED=false,
Vercel Git desvinculado e nenhuma publicação ativa na conferência pré-merge.
Código do probe não foi executado fisicamente. Apenas simuladores nos testes.
Validação local: 99 passed, 2 subtests, sem skips; testes PG ainda não executados
nesta composição. Resultados físicos/CI de 28/10 são históricos, não transferíveis.
Sarah Opus 5.5 high: GO local, P0=0/P1=0; revisão sanitizada sem ferramentas.
Pendências antes de ampliar/executar novamente o transporte: SIGTERM/SIGHUP do
controlador podem impedir finally e deixar fixtures com restart=always;
conferência residual por label ainda não implementada; snapshot inicial de backup
pode propagar erro de driver antes do marcador. Probe usa socket Docker local
sem guarda técnica de host: não executar em VPS. A allowlist explícita de
`deploy/package_backend_release.py` exclui `rehearse_first_transition_commands.py`.
Limites registrados, sem implementação/ensaio adicional nesta preparação.

CI do novo head pendente nesta gravação; evidências finais na PR #602.
Sem autorização de merge, dispatch manual, deploy, reativação, ensaios físicos
locais, acesso VPS ou produção.

Restam integração autorizada da #602 com CI do futuro head, proposta de topologia
sintética e aprovação nominal de qualquer execução operacional. 51 migrations
não foram aplicadas em produção. Transporte real/ingresso/filas, backup/restore
operacional, preflight atual, janela/SHAs/contingência e retomada do piloto seguem
pendentes. Registros abaixo são históricos e não concedem autorização vigente.


## Histórico — preparação e publicação da #601 antes da integração

#600 integrada por merge commit `60e29d142040ebc5b21c35af18884b2449321308`,
head autorizado `da1cc2e0`, sem bypass, git push manual ou exclusão da branch. Dono aceitou
explicitamente a lacuna histórica da main `ed7f4c10`; isso não cria CI retroativo.
Seis workflows automáticos event=push aprovados no SHA novo: backend
40822044870, frontend 40822045020, E2E 40822044871, RLS 40822044970, tooling
40822044886 e sintético 40822045064. Nenhum dispatch manual autorizado ou executado.

#601: dono autorizou commit/push sem force e base main, a partir do head
original `84366305` e da composição local com a main acima. Conflitos resolvidos preservando ensaio das 51 migrations no
clone, identidade cluster/OID/owner antes da limpeza FORCE, todos os testes das
duas séries e Vercel deploymentEnabled=false global herdado da main, sem alteração. Recibos de índices e recusa
de adoção sem recibo da #600 preservados. DEV continua disabled_manually e
DEV_PIPELINE_ENABLED=false; nenhum gate operacional alterado.

Validação do candidato: 85 testes/2 subtestes offline e Ruff aprovados;
nenhum banco/contêiner local executado. Testes PostgreSQL da composição ainda
não verificados: dependem de publicação autorizada e CI do futuro head.
Sarah Opus 5.5 high: GO de preparação local, sem P0/P1 após correção documental.
CI do novo head pendente nesta gravação; evidências finais na PR #601.
Sem autorização de merge, dispatch manual, deploy, reativação, ensaio físico
local, VPS ou produção.
Registros de autorização e resultados anteriores abaixo são históricos.


Registro histórico de 27/10/2026 às 15:38 UTC sobre `afdfb78d`; estado vigente no topo. Esta é a única fonte ativa
de planejamento; substitui os planos de MVP e refatoração e seu acompanhamento.
O [PRD canônico](docs/Docs20260611_163530/PRD20260611_163530.md) conserva os
requisitos. As decisões de 15/10 prevalecem sobre os cortes antigos de escopo,
inclusive a entrada de Universidade da Vida e Capacitação Destino.

**Objetivo:** cuidar das pessoas e organizar a rotina G12 pelo WhatsApp oficial;
o painel serve à configuração, supervisão, exceções e ações sensíveis.
A V1 encerrou como piloto controlado; o produto completo ainda está em construção.

**Como ler:** **feito** = entrega delimitada implementada; **em andamento** =
entrega parcial; **falta** = trabalho ou decisão pendente. A coluna de produção
é separada: código e teste local não provam publicação ou ativação. Os testes e
publicações citados abaixo são registros anteriores, não repetidos nesta entrega.
Quando falta prova, usamos **não verificado**. Produção é o sistema em uso;
`main` é o código integrado; teste local exercita uma simulação no computador.

**Piloto:** Filadélfia, restrito a testadores internos. A decisão de 15/10 mantém
o agente ligado como está, sem ampliar o piloto. O registro informa resposta em
cerca de 28 s e monitor verde desde 14/10; o estado atual é **não verificado**.
O último backend registrado é `eb5a09b` (27/09); versão atual: **não verificado**.

**Recuperação manual do CI, commit/push autorizado na #600 — 29/10/2026:** sobre o head
publicado da #600 `3e3375ed`, proposta de cinco linhas: adicionar
`workflow_dispatch` a backend-tests, frontend-ci, rls-integration, tooling-static
e synthetic-release. E2E já possui esse gatilho. Nenhum job/permissão/gate muda.
O dono autorizou commit/push sem force na própria #600 e acompanhamento do CI
automático, com Sarah Opus 5.5 high. CI do novo head pendente nesta gravação;
evidências finais serão registradas na PR. Merge e dispatch manual seguem proibidos.
A integração futura habilita recuperação na nova main; não cria prova retroativa
para `ed7f4c10`. Protocolo e comandos no início do runbook de release. 65 testes/30 subtestes
offline e três cenários do gate DEV aprovados: dispatch não substitui event=push.
Sarah Opus 5.5 high: GO do plano local, sem P0/P1; gate DEV permanece inalterado.

**Correções da revisão automática da #600 — 29/10:** retomada compara presença
e definição (hash de pg_get_indexdef) dos índices concorrentes com recibos do
diário; divergência recusa sem reparar. Índice concorrente sem recibo após crash recusa retomada; não adota definições
sem prova. Reobservação final confere os recibos antes de declarar conclusão.
Backup sintético captura cluster/OID/proprietário antes de marcar o clone;
limpa falha de comentário somente com identidade preservada. Falha antes de
capturar identidade mantém recusa de limpeza, exigindo recuperação nominal.
Sete regressões PG adicionadas para o CI; nenhum banco local executado.
Subprocesso do teste SIGKILL agora desabilita bytecode. Testes offline do Codex:
50 aprovados e 10 subtestes; Sarah revisa o diff sanitizado, sem executar testes.
Main ed7f4c10 tem E2E manual aprovado (40814255271); cinco workflows sem runs
no SHA exato, sem dispatch. Não declarar main verde nem transferir checks de
árvore equivalente. Publicação e correções da #600 autorizadas, merge não.

**Atualização vigente — #599 integrada em 29/10/2026.** Merge commit
`ed7f4c10104f4537b8918000c0868992245b9429`, head autorizado `9e0dbda9`.
Checks obrigatórios verdes, sem bypass e branch preservada. Vercel/DEV seguem
suspensos. A atualização da #600 sobre esta main foi autorizada para commit/push normal,
base main e CI, sem merge ou publicação das demais PRs.
Conflito Vercel resolvido preservando deploymentEnabled=false global da main;
o bloqueio antigo por branch da #600 não substitui a suspensão global.
Código do adaptador e SHAs pinados afdfb78d/37c7d68d preservados. Leitor Git
com modo estrito opt-in e empacotador da #599 preservados. Resultados do novo head na PR #600; checks anteriores não validam este candidato.
Sarah Opus 5.5 high: GO para futura publicação/CI, sem P0/P1;
50 testes e 10 subtestes offline aprovados, Ruff aprovado. CI de push da main ausente; E2E manual aprovado, cinco workflows
ainda não executados no SHA exato. Main não declarada verde. SHAs pinados comprovados
ancestrais da nova main; recibos antigos não validam o novo digest dos módulos.
Chave PGDG segue obtida da fonte oficial por HTTPS sem fingerprint pinado;
client 17 sem patch fixado: risco residual de suprimento restrito ao runner efêmero.
Consulta oficial: https://wiki.postgresql.org/wiki/Apt. Não é gate operacional. Sem deploy, reativação, novo ensaio
físico local, VPS ou dados de produção. Registros divergentes abaixo são históricos.

**Revisão Sarah — Opus 5.5 high:** orientação vigente do dono: trabalhar
com Sarah como revisora crítica e cética, confrontando seus achados com evidências,
sem concordância automática. Sua revisão não concede autorização operacional.
Na #599, revisão inicial pediu recusa de arquivos inesperados, permissões
explícitas e prova do empacotador real no CI. Correções: exclusão documental
explícita, diretórios 0755 e extração com permissões do pacote, Python 3.13.14
fixado no workflow manual e execução da CLI real sobre o SHA do CI.
35 testes e 10 subtestes locais passaram, Ruff aprovado; sem ensaio físico.
A hipótese de diretórios root impedirem appuser foi limitada pela evidência
de chown no Dockerfile; ainda assim as permissões agora são determinísticas.
Inventário atual: backend/app somente Python; fora de Python/SQL nas árvores
selecionadas existe apenas backend/migrations/README.md. .env.example aparece
só como comentário do Compose, não é dependência executada do pacote.
O build físico histórico de afdfb78d não valida este head; nenhum novo build
físico foi executado. CI/revisão finais constam na PR #599 e não autorizam merge.

**Atualização vigente — #598 integrada em 28/10/2026.** Merge commit
`beb194f930eecd5bf7df744bd6e23eaa88d04b4b`, head autorizado
`083c3f9ec720af1dfe3917980f4b68499c4a920b`. Seis workflows verdes no
head e na main anterior antes do merge, sem bypass e com branch preservada.
A #599 foi composta localmente sobre essa main, sem conflitos, preservando
seu código original `b3d93473` e as suspensões Vercel/DEV da main.
Validação local em Python 3.13: 26 testes e 8 subtestes passaram; Ruff aprovado.
Atualização autorizada para commit/push sem force push, base main e CI da #599.
Nenhum merge ou publicação das demais PRs autorizado. Resultados do novo head
na [PR #599](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/599);
checks antigos não validam o novo candidato. Os registros
anteriores são históricos quando divergirem deste estado. Nenhum deploy,
reativação, novo ensaio físico local, acesso à VPS ou dados de produção.
SQLs e aplicador pinados nos ensaios anteriores não são repinados.

**Atualização vigente — #597 integrada em 28/10/2026.** Merge commit
`940ac49ef82eedf7a67da666fab8435c12f7d760`, head autorizado
`8542e9911083924100a10f180241808c44fe91ee`, com seis workflows verdes antes do
merge, sem bypass e com branch preservada. Main resultante `940ac49e`.
As proteções de quatro checks e as suspensões Vercel/DEV foram reconfirmadas;
nenhum deploy, reativação, VPS, dado de produção ou ensaio físico local.
A #598 foi composta sobre essa main, sem conflitos, preservando integralmente
o código e as fixtures do head anterior `37c7d68d`. Sua atualização recebeu
autorização de commit/push sem force push, base main e acompanhamento do CI.
Validação local em Python 3.13: **46 testes unitários passaram**; Ruff,
JSON/YAML/Bash e diff check aprovados. Nenhum banco ou migration executado.
Resultados do novo head na [PR #598](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/598);
checks antigos não se transferem para ele. Nenhum merge da #598, nem publicação
ou integração das #599–#602, autorizado nesta etapa. Merge exige decisão
posterior às evidências do CI.
Registros anteriores abaixo são históricos quando divergirem deste estado.

**Atualização vigente — #603 integrada em 28/10/2026.** Main resultante
`e2eb2d04f08caf46f676a4f560acc77a61c5e351`, merge commit do head autorizado
`3283633ac6e912de7548f4e974575145083312df`, sem bypass e com branch preservada.
Removido somente o requisito Vercel da proteção da main; backend-tests,
frontend-ci, e2e-critical e rls-integration mantidos com app_id 15368,
strict=true e enforce_admins=true. Demais proteções conferidas sem alteração.
DEV continua disabled_manually com variável false; Vercel permanece sem Git e
sem publicação pendente. Nenhum deploy, reativação, VPS ou dados de produção.
A atualização da #597 sobre essa main teve commit/push e acompanhamento do CI
autorizados. Preserva o histórico do head anterior `d0382051`, o painel/runbook
e a suspensão #603, sem force push. Os resultados do novo head devem ser
consultados na [PR #597](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/597);
checks antigos não validam o candidato atualizado. Nenhum merge da #597 ou
publicação/merge das #598–#602 autorizado nesta etapa. Merge depende de nova
decisão após as evidências. Referências históricas abaixo não alteram esse limite.

**Decisão vigente — 28/10/2026: suspender publicações automáticas antes da integração.**
O dono decidiu suspender painel/Vercel e promoção DEV antes das PRs #597–#602.
Preparação local independente sobre a main conhecida `afdfb78d`: Vercel Git
`deploymentEnabled=false` para todas as branches; DEV somente por disparo manual,
ainda condicionado a `DEV_PIPELINE_ENABLED=true`, main e validação do candidato.
O CI permanece ativo. A #603 reutiliza exatamente o lock da ferramenta de auditoria
da #597 (`msgpack` 1.2.1 → 1.2.3), permitindo validar esta PR antes dela;
nenhuma dependência de runtime da aplicação é alterada. Suspensão remota **aplicada e verificada em 28/10/2026** com autorização nominal:
workflow DEV `380485201` em `disabled_manually`, variável antes ausente agora
`DEV_PIPELINE_ENABLED=false`, vínculo Git Vercel desconectado. Projeto e seis
domínios preservados; último deployment inalterado; nenhuma publicação pendente
na consulta. Autorizados commit/push/PR e CI após essa confirmação. Sem merge,
deploy, ensaio físico local, acesso à VPS ou dados de produção.
Antes de integrar qualquer PR, reconfirmar a suspensão externa descrita
no [runbook](docs/ops/RELEASE-LOTE-2026-10.md#suspensão-das-publicações-automáticas--aplicada-integração-pendente).
A [PR #603](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/603) deve preceder
#597 → #598 → #599 → #600 → #601 → #602;
reconciliar os arquivos Vercel/ROADMAP nas dependentes preservando esta decisão.
Publicação manual, retomada automática e eventual cancelamento de execução já
iniciada exigem autorização própria. Histórico de autorizações anteriores não
prevalece sobre esta decisão.

## Execução autônoma solicitada em 25/10

Objetivo contínuo registrado em 25/10/2026 19:56 UTC, com janela solicitada
até 26/10/2026 19:56 UTC. A continuidade depende da sessão e dos limites da plataforma;
não há garantia de 24 horas ininterruptas.

- Equipe segue implementando, testando, revisando e publicando PRs, sem pedir confirmação a cada fatia.
- Claude Opus 5.5 executa e aplica `/pr`; Codex revisa; segunda opinião Claude preservada.
- Ao terminar uma tarefa, selecionar a próxima pendência executável deste ROADMAP.
- Se um item depender do dono, registrar motivo, ação e onde fazer; continuar os demais itens independentes.
- Autorizações específicas permanecem necessárias para merge de cada PR e operações reais, conforme AGENTS. O dono aprovou o pacote #577–#594 para integração nesta sessão, incluindo eventual frontend automático na Vercel. Backend, banco, restart e gates exigem autorização separada.
- Release, aceite pastoral e ampliação do piloto não são concluídos apenas com código e testes.

Após a solicitação original, o dono aprovou em 26/10 a integração específica do pacote #577–#594; essa é a fase atual em execução, com os gates de backend e banco separados.

## Pendências — visão rápida

Atualização: 27/10/2026, 15:38 UTC. **14 frentes pendentes e 1 encerrada**;
resumo das pendências detalhadas abaixo, sem somar tarefas repetidas.
A lista antiga de 22 tarefas está arquivada e não determina o progresso atual.

**Última integração:** [PR #596](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/596), merge `afdfb78d`; quatro checks e Vercel aprovados no head antes do merge. Isso não comprova operação do backend em produção.

**Frontend automático:** publicação com sucesso registrada na Vercel para `7bc7fa72` às 2026-10-27T00:59:10Z. Prova por metadados GitHub/Vercel; funcionamento da interface, backend e banco não verificados nesta integração.
**Integrações concluídas: 18/18 do pacote + #595 e #596.** Main `afdfb78d`; quatro checks obrigatórios aprovados no merge. Backend e banco não foram publicados por essas integrações.

**Correção adicional (fora das 18):** [PR #595](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/595) — evita erro quando dois pedidos iguais criam o mesmo currículo ao mesmo tempo. Revisão Codex e Opus aprovada; 234 testes de CD passaram em banco sintético. Estado: integrada na main em `7bc7fa72`; CI pós-merge com os quatro checks aprovados.

**Outra correção adicional:** [PR #596](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/596) — evita falha quando dois pedidos iguais criam a mesma turma da Universidade da Vida ao mesmo tempo. 89 testes locais aprovados; revisão Codex e Opus aprovada. Estado atual: integrada na main em `afdfb78d`; quatro checks e Vercel aprovados no head `83dfcc4b`; CI da main com os quatro checks aprovados.

**Agora:** plano e prévia revisados por Codex e Opus, disponíveis no [runbook operacional de release](docs/ops/RELEASE-LOTE-2026-10.md) para o SHA `afdfb78d71a53f2861632806e13cdda4662d7d63`, com 51 migrations pendentes e a primeira transição da instalação legada na VPS srv2031318. O dono recebe plano e prévia antes de qualquer aplicação. Preparação local do adaptador ensaiada; publicação/CI da composição atual autorizadas nesta etapa, sem merge; transporte real e qualquer ensaio físico adicional exigem decisão própria; não há deploy pronto para disparar. A correção de acesso duplicado foi CANCELADA após reset externo; não pedir identificadores nem executar reconciliação. Leitura atual confirmou 0 duplicidades. Escritas no banco, deploy, restart, gates, backup novo e canários não autorizados.

**Consolidação local — 27/10/2026:** a pasta principal `PastorAi-1.0` foi atualizada por fast-forward para `afdfb78d`; plano e painel agora são gerados nela. Foram removidas 95 worktrees já integradas, sem apagar branches ou commits, e 1 foi arquivada reversivelmente por cache pertencente a outro usuário. Todos os 1.241 registros de arquivos/diretórios ignorados das pastas removidas foram preservados opacamente em área privada do Git, sem abrir conteúdo nem versioná-lo. O saldo registrado ainda inclui 9 áreas sob Codex e rascunhos pendentes de revisão. DEV local recuperado e saudável; produção não alterada. As alterações de documentação e ferramenta do painel seguem em PR própria e continuam aguardando integração; não alteram fases de produção nem gates.

**Retomada local — 27/10/2026:** falha da #597 identificada na auditoria do lock
de ferramentas (`msgpack 1.2.1`); correção local para `1.2.3` validada pelas duas
auditorias, sem vulnerabilidades conhecidas retornadas. Correção publicada na #597 (`d0382051`), com CI aprovada; PR aberta, sem merge. Ensaio SQL do candidato exato `afdfb78d` em PG 17.6
descartável, sem rede externa: base de 78 seguida das 51 pendentes, ledger 129,
zero pendentes/índices inválidos, quatro roles NOLOGIN e limpeza confirmada.
Detalhes e limites no runbook do lote. Pacote publicado na #599 (`b3d9347`),
com CI aprovada e sem merge; adaptador descrito abaixo. Nenhuma operação em produção.


**Executor de migrations — PR #598 publicada em 27/10:** padrão CLI de 2s,
com `SET LOCAL`/`SHOW` para preservar o isolamento histórico. Validação local:
60 testes (46 unitários e 14 PG 17.6), replays 78→129 e 0→129 pela CLI,
ledger 129 e zero índices inválidos. A histórica `20260827_175634` recebeu
5s explícitos, conforme seu SQL; as oito pendentes concorrentes usam o caminho
próprio. Head `37c7d68d`, CI aprovada; PR aberta e dependente da #597, sem merge.
Nenhuma migration ou operação em produção; adaptador real segue pendente.

**Adaptador — [PR #600](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/600) publicada (28/10/2026):** branch
`feat/first-transition-adapter-20261027`, base `37c7d68d` (#598).
Registro histórico da autorização de 28/10 (não se transfere à composição atual): commit, push e PR para revisão, sem merge/deploy.
Bloqueio histórico de preview por branch, superado pela suspensão global da main;
`frontend/vercel.json` não muda outras branches nem configurações remotas.
Preflight completo pré/pós, dump/restore fictício com extensões, matriz de cinco
pontos de SIGKILL e contrato de host 3 Compose + 1 avulso por simulador.
Arquivo de dump temporário, `archive_persisted=false`; não é backup operacional.
Redis permanece simulado, sem conteúdo da dead, `content_verified=false`.
O dono autorizou
explicitamente enviar os sete arquivos novos e resumo sanitizado ao Claude.
Opus 5.5 high revisou o código em três rodadas; a final concluiu **sem
bloqueador para a fatia local**, sem aprovar produção. Foram corrigidos os seis
achados: colisão de concorrentes antes do marcador, retry de execução incompleta
(inclusive SIGKILL) sem bloquear replay concluído, gates de backfill por fase,
manifesto das seis dependências locais, restore com dados fictícios não vazios
sob FORCE RLS e ordenação C do ledger. Também foram fixados hostaddr, identidade
com OID, recibo de restore vinculado ao marcador e colisões de nomes com qualquer
relação. Candidatos são revalidados até a migration correspondente ser aplicada.
**Validação local repetida para publicação: 68 passed em 138,20s**, Ruff aprovado, PostgreSQL e clones
removidos. Parecer e manifesto do snapshot revisado em `output/release/`. Na preparação
da PR, removido somente um espaço final no helper de backup; sem alteração semântica.
CI própria preparada no check `backend-tests`: histórico Git completo, imagem
PG17 por digest, ferramentas PG17 pelo repositório oficial PGDG e launcher dos
68 testes. A primeira tentativa de CI falhou na instalação do client ausente
no Ubuntu; corrigida a origem do pacote, sem mudar o código revisado. CI de `8ef92e3a7cfdb75e9c366a168ddff415962a8b5b` aprovada em 28/10:
`backend-tests`, `frontend-ci`, `e2e-critical`, `rls-integration` (quatro shards
e agregador), `tooling-static` e `synthetic-release`. No CI, os 68 testes do
adaptador passaram em 154,49s, com limpeza confirmada. Nenhum deployment Vercel
para esta branch na consulta de metadados. Esta atualização documental gera
novo SHA; seu resultado exato fica na descrição da PR #600. A próxima
etapa técnica é ensaiar as 51 no clone restaurado e preparar o transporte real
contra o contrato, testando só com doubles até nova autorização. Sem merge, deploy, leituras remotas ou alterações em produção.

**HISTÓRICO — clone e transporte simulado de 28/10, publicado em `84366305`:**
Resultados e autorização abaixo não se transferem ao candidato composto sobre
`60e29d14`; publicação atual da #601 não autorizada.
branch `feat/first-transition-clone-transport-20261028`, base `4eea5393` da #600.
Aplicação das 51 também no clone UUID restaurado, antes do marcador da fonte;
ledger final 129 e preflight completo, com fonte reconferida. Transporte de
comandos preparado com driver obrigatório de simulação, IDs explícitos e espera
limitada, sem executor de processos/SSH. **Suíte completa após revisão: 91 passed em 260,03s, zero skips**,
Ruff, YAML/Bash e diff check aprovados; PostgreSQL descartável removido.
Opus 5.5 high revisou esta fatia em duas rodadas: **sem bloqueador local**,
condicionado à suíte completa verde, condição cumprida. Correções incorporadas:
recibo validado antes do marcador/replay, catálogo final clone/fonte comparado,
limpeza FORCE só em clone marcado e timeouts de ensaio ampliados. Publicação
em PR separada e CI autorizadas; resultados do head exato ficam na descrição
da PR dependente da #600, sem necessidade de presumir prova de produção. Preview da nova branch
explicitamente desabilitado, sem alterar outras branches ou configuração remota.
Merge, deploy, VPS e produção continuam fora do escopo.
Próximo passo após validação: apresentar a diff e definir ensaio físico isolado
antes de implementar/conectar qualquer driver real. Sem merge/deploy/VPS/produção.

**HISTÓRICO — preparação de 28/10, publicada em `af5158d5`, base `84366305`:** branch
`feat/local-transport-rehearsal-20261028`, publicada na [PR #602](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/602), sobre #601.
Pendências do Opus tratadas localmente: sanitização do erro de catálogo final,
identidade distinta do clone e flag explícita de DDL global. Ensaio de comandos
preparado com modo padrão sem efeitos e nove testes com doubles; execução física
autorizada especificamente pelo dono e concluída com sucesso em 28/10. Proposta: quatro processos fictícios, sem rede/portas,
512 MiB/1 CPU no total, imagem local imutável e limpeza por nomes/UUID próprios.
Comandos de execução/recuperação, recursos e limites no [runbook](docs/ops/RELEASE-LOTE-2026-10.md#ensaio-local-de-comandos--executado-com-aprovação).
**Validação local: 106 passed em 277,79s**, PostgreSQL descartável removido.
Após acrescentar `--no-healthcheck`, os nove testes do ensaio preparado foram
revalidados (9 passed); Ruff, YAML/Bash e diff check aprovados. Ensaio físico dos comandos: **PASS em quatro fixtures**, saídas 0, sem reinício,
limpeza `clean` e zero contêineres do UUID na consulta local independente. As
duas primeiras tentativas falharam no logging e foram limpas; corrigido
`compress=false` mantendo um arquivo local de 1 MiB, com nove testes revalidados.
Não prova workers reais, Compose, ingresso ou filas. Não confundir com o CI da #601.
Nova autorização cobre revisão externa pelo Opus 5.5 high, correções, commit/push,
PR separada e acompanhamento de CI; não cobre novos ensaios físicos. A revisão
identificou argumento inválido no launcher do CI e ausência de `--run-id`
obrigatório nos modos com efeito; ambos corrigidos. Validação posterior apenas
offline: **78 passed, 2 subtests passed**; revisão final Opus 5.5 high sem bloqueadores locais, Ruff e diff check aprovados. Preview
desabilitado também para esta branch. Resultados finais e SHA do CI devem ser
consultados na [PR #602](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/602); provas físicas acima são históricas.
Ordem de integração proposta: **#597 → #598 → #599 → #600 → #601 → #602** (#598/#599
independentes entre si após #597). Nenhum merge autorizado; integração pode
publicar frontend na main e requer decisão específica. Antes do release ainda
faltam transporte real/ingresso/filas/topologia ensaiados e revisados, integração
aprovada, backup/restore operacional, preflight atual sanitizado, decisões de
contenção/gates, janela com SHAs e contingência, e retorno nominal do piloto.
Consultas GitHub confirmaram #597–#601 abertas, sem merge e com os seis workflows
verdes nos respectivos heads. Publicação/revisão externa estão autorizadas;
VPS, produção, merge/deploy e novos ensaios físicos permanecem fora do escopo.
Na integração, além do frontend automático na main, `dev-synthetic.yml` pode
promover para DEV após CI se `DEV_PIPELINE_ENABLED` estiver habilitado (estado
não verificado); isso precisa ser tratado antes de autorizar merge.

**Pacote aprovado: 18/18 integradas; 0 pendentes.** Autorização nominal recebida: “pacote aprovado para integração”, cobrindo #577–#594 e possível frontend automático Vercel. Os checks dos SHAs originais são históricos; cada head atualizado exige quatro checks e Vercel novamente. Dependentes serão direcionadas à main após integrar os pais. Backend, banco, restart e gates exigem autorização separada. Sem bypass, force push ou remoção de branches.

**Empacotador do release — preparação de PR em 27/10:** seleção explícita de
blobs Git do SHA exato, sem configuração privada ou scripts administrativos;
manifesto por arquivo. Passaram 9 testes próprios, 17 do workflow e regressão
com 157 testes/216 subtestes. Pacote `afdfb78d`: 404 arquivos, build production
aprovado, 396 arquivos na imagem conferidos sem divergências. Commit/push
autorizados; CI/revisão do commit publicado pendentes. Transição legada ainda
depende de adaptador; nenhum deploy. Evidências no runbook do lote.

| Frente | O que falta / para quê | Quem resolve |
|---|---|---|
| 1. Parada segura | Provas sintéticas integradas (#577–#581 e #586). Falta adaptar, ensaiar e revisar a primeira transição real do legado; controlador existente é só sintético. | Equipe prepara; operação real depende de autorização. |
| 2. Backup e recuperação | Provar que o sistema pode ser restaurado se algo falhar. | Equipe prepara; você autoriza operação real e ajusta backup externo. |
| 3. Conta duplicada | **Encerrada.** Correção cancelada pelo dono; reset externo realizado. Leitura de 27/10: zero duplicidades. Não executar desvínculo. | Nenhuma correção a executar; só revalidar na janela. |
| 4. Atualização do banco | Aplicar as **51 migrations pendentes**, uma por vez, após backup e aprovação. Lista exata no runbook do release. | Equipe prepara; você aprova antes de aplicar. |
| 5. Publicação do piloto | Preparar primeira transição da VPS antiga, atualizar os quatro serviços e validar compatibilidade com o painel, preservando igreja/master/Pessoa/configurações. | Equipe prepara; você aprova a janela e a retomada. |
| 6. Aceite pastoral | Validar 20 conversas e o caminho completo do G12. | Você/equipe pastoral testa; equipe técnica corrige. |
| 7. Memória e exclusão | #584 e #585 integradas; falta publicar, provisionar identidades privadas e validar sob gates próprios. Não ativar automaticamente. | Equipe prepara; ativação depende de autorização. |
| 8. Conhecimento oficial | Validar respostas com fontes aprovadas e fechar decisão pastoral. | Equipe + você/equipe pastoral. |
| 9. Pessoas e rotinas | Completar planejamento e alertas. Correção de acesso ao alerta #589 integrada; validação no piloto ainda pendente. | Equipe; você decide regras de acesso pendentes. |
| 10. Agenda | Concluir Google e lembretes; conferir eventos antigos antes de reenviar. | Equipe; conexão Google e envios exigem autorização. |
| 11. Comunicados, e-mail e cobrança | Validar cada canal separadamente antes do uso real. | Equipe prepara; você aprova cada teste real. |
| 12. Segurança e bugs | MFA depende de configuração. Logout, B5/B15 e prova B7 integrados (#568/#591–#593); publicação e aceite ainda pendentes. | Equipe; você configura MFA e decide regras pendentes. |
| 13. Uso, velocidade e monitoramento | Testar celular/acessibilidade, medir lentidão e completar alertas. | Equipe + testadores do piloto. |
| 14. Ambiente de testes online | Definir custo/recursos e disponibilizar testes separados da produção. | Equipe prepara; você decide custo e contratação. |
| 15. Organização e lançamento | Publicar acompanhamento restante, organizar arquivos e revisar ampliação. | Equipe; limpeza e ampliação dependem de sua decisão. |

**Condicionado, sem ativação autorizada:** Jev depende de contrato de proteção
de dados, avaliação de qualidade e sua decisão específica.
**Já integradas:** #572, #573, #574, #575, #576 e #577. Isso não comprova atualização de produção.
Este resumo mantém a ordem e os critérios do roteiro detalhado; não é plano novo.

## Progresso da retomada — 24/10/2026

Acompanhamento desta retomada dentro do roteiro; não é plano paralelo nem muda
as prioridades abaixo. Produção: somente a leitura datada na seção seguinte.

| Tarefa | Estado | Próximo passo |
|---|---|---|
| Levantamento da `main` e das PRs | feito | GitHub reconfirmado em 25/10: #572, #573, #574, #575 e #576 integradas; main em `6b0b302b`. |
| Sessões de trabalho | feito | Executor Opus 5.5 e segunda opinião estabelecidos; Codex orquestra e revisa. |
| Reconciliação do ROADMAP e do [runbook do lote](docs/ops/RELEASE-LOTE-2026-10.md) | feito (local) | Plano atual de 27/10: 51 migrations conferidas por nome e ordem (8 concorrentes). Registro anterior de 42 descreve o recorte histórico, não o release atual. Diff check passou; nenhuma aplicação. |
| Integração documental | parcial | O runbook atualizado e uma atualização do ROADMAP estão publicados na #573. O gerador do painel e o acompanhamento local ampliado ainda não foram publicados. |
| Painel local derivado do roteiro (`tools/render_progress.py` → `output/painel/`) | feito (local) | Validado pelo Codex: gerado com Python 3.13; `index.html` e a fonte local com HTTP 200 em `127.0.0.1:8777`, sem servir o restante do repositório; filtros, busca e limpar funcionando; desktop e celular (390 px) sem overflow nem erro de JS. Visualização do roteiro, sem percentual global nem prova de produção. **Não é** a validação sintética do pacote, registrada na linha seguinte. |
| Validação sintética do pacote do lote | feito (local) | Evidências locais distintas, sem somar totais: (a) restauração sintética `RESTORE_SINTETICO=OK tabelas=2 contagens=2:1`; (b) PG: `test_release_preflight_pg`, `test_release_bundle_pg` e `test_release_schema_compatibility_pg` com 11 passed, 0 skip, 37,34 s, Python 3.13.14, PostgreSQL 17 alpine isolado, ambiente limpo e 124 migrations ativas aplicadas por `migrate.cmd_apply`; (c) `deploy/tests`: 156 testes + 141 subtestes, 0 skip, 98,89 s, em 7 arquivos (backend_release, release_image_compose, maintenance_schema, maintenance_release, dev_pipeline, dev_coordination, backend_workflow), Python 3.13.14 com `network=none`, sem socket real; (d) ensaio físico PASS no SHA `354a83d891fe7295164d980a175dacdd2feba69e` com 9 checks (independent-migrations, process-readiness, frontend-http-headers, persistent-pending-queue, failed-swap-containment, additive-code-recovery, synthetic-reset, reset-reservation-invalidated, completed-acceptance-preserved), imagens construídas limpas (backend `8fbc14c58e9a`, frontend `dfb46ef35735`), relatório conferido pelo Codex e limpeza com 0 containers, redes e volumes. **Não comprova** compatibilidade com o banco de PROD nem com o SHA ativo, gates, backup real, release ou aceite das 20 conversas. |
| Conferir backend/banco e preparar janela | em andamento | Leitura 27/10 pós-reset: 78 aplicadas/51 pendentes no candidato `afdfb78d`; 0 duplicidades e 0 vínculos inválidos. VPS saudável em layout legado, imagem sem revisão Git, gates preservados. Redis: 2 itens de falha preservados; não ler conteúdo, apagar ou reenviar. Preparar plano e prévia antes de aplicar; adaptador real da primeira transição ainda não disponível. |
| Reconciliação excepcional de vínculo Pessoa (#572) | feito (integrado) | Merge `830decc1`, todos os checks aprovados. Escolha privada das contas e execução real dependem de backup, contenção e autorização nominal. |
| Ensaio sintético de contenção (#573) | feito — integrada | Commit `61cdf07e`: 54 testes locais, sete cenários Docker e 129 testes dos workers aprovados. Às 20:46 UTC: todos os checks GitHub passaram, incluindo backend-tests, frontend-ci, e2e-critical e rls-integration. Merge autorizado e concluído às 20:50 UTC em `c5c180ca`. |
| Ciclo de vida do queue-worker real do legado | feito — #574 integrada | Branch `test/legacy-queue-entrypoint-20261024`, base `c5c180ca`: Claude Code executor, revisão Codex e segundo Claude sem bloqueios. 88 testes, zero skip; sete verificações físicas PASS, fonte/lock legado conferidos e limpeza sem sobras. Publicada na [PR #574](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/574), commit `94a4b9ec`; todos os checks aprovados e merge autorizado em 25/10 às 18:45 UTC, SHA `3f21b20a`. Não prova ingestão ativa nem produção. |
| Ingestão ativa durante SIGTERM | feito — #575 integrada | Rebase próprio em `785dad91` sobre a main após o merge da #574; código testado preservado, base e descrição atualizadas pelo Claude Opus 5.5 aplicando a skill `/pr`. Todos os checks do SHA `785dad91` aprovados, incluindo backend-tests, frontend-ci, e2e-critical e rls-integration. Merge autorizado em 25/10 às 19:01 UTC, SHA `a3e83a51`. 130 testes (42 novos + 88 regressão), 20 verificações físicas aprovadas; commit/ACK únicos, dedup com/sem marcador, isolamento RLS e limpeza sem sobras. Revisão Claude incorporada; versão final verificada pelo Codex. [PR #575](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/575). Não comprova turno completo, parada após escritas não confirmadas ou produção. |
| Parada do cron-worker real durante tick ativo | feito — #576 integrada | Claude Opus 5.5 implementou e publicou usando a skill `/pr`; revisão independente Claude e Codex concluídas. Commit `441629b2`: 176 testes (46 novos + 130 regressão), 13 verificações físicas PASS, bloqueio 6,445 s, saída 0,652 s, limpeza sem sobras. [PR #576](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/576). Contenção só após saída; não prova produção, supervisor, pós-DDL nem SLA/billing com trabalho ativo. Todos os checks do SHA `441629b2` aprovados. Merge autorizado e confirmado em 25/10 às 19:41 UTC: `6b0b302b`. |
| Parada do broadcast ocioso real | feito — integrada no pacote | Commit `f8ded9c6`: 216 testes (40 novos + 176 regressão), 10 verificações físicas PASS com PID1 Python explicitamente garantido; dois ciclos ociosos/paradas em 0,503/0,549 s; limpeza sem sobras. Claude executor e segunda opinião, revisão Codex; publicada com skill `/pr`. [PR #577](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/577). Não cobre envio ativo, pendências no banco, supervisor ou produção. Todos os checks do SHA `f8ded9c6` aprovados; integração confirmada. Integração confirmada neste pacote: #577 em 92821e35. |
| Parada do backend com requisição em andamento | feito — integrada no pacote | Commit `8f6bb9b4`: 279 testes (103 novos + 176 regressão) e 12 verificações físicas PASS. Ciclo HTTP retido durante SIGTERM, 202 e envelope único na fila, novas conexões recusadas; saída 1,202 s após liberação e fila preservada no reinício. ACK TCP confirmado; posição interna do handler inferida. Limpeza sem sobras, revisão Claude/Codex, skill `/pr`. [PR #578](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/578). Não prova produção, consumo pelo agente ou pós-DDL. Todos os checks do SHA `8f6bb9b4` aprovados, incluindo backend-tests, frontend-ci, e2e-critical e rls-integration. integração confirmada. Integração confirmada neste pacote: #578 em 64d7509d. |
| Transição inicial legado → release atual | feito — integrada no pacote | **#579:** pronta, integração confirmada. **#580:** atualização/rollback; CI aprovada, depende da #579. **#581:** retomada segura; CI aprovada, depende da #579. Ensaios sintéticos aprovados; produção inalterada. Integração confirmada neste pacote: #579 em 84fb7f11, #580 em 74919ee0, #581 em 87ba1e42. |
| Conta restrita para exclusão de áudios | feito — integrada no pacote | SHA `1f8e164`, base #582. Revisão independente Claude e Codex aprovadas; os quatro checks obrigatórios passaram na nova rodada. Autorização de merge solicitada, sem resposta. Depois da #582: retarget para main e novo CI. Nenhuma migration ou credencial foi aplicada em produção. Integração confirmada neste pacote: #582 em 1a5cb9c9, #583 em ae15449d. |
| Upload concluído sem resposta | feito — integrada no pacote | SHA `98a66c9`, base #583. Revisão independente e Codex aprovadas; 980 testes de regressão, 88 novos, 14 falhas provocadas detectadas e dois ensaios físicos aprovados (rodadas distintas). Backend, frontend, E2E, RLS, ensaio sintético e preview aprovados no SHA exato. Depois da #583: retarget para main e novos checks. Sem merge ou produção. Integração confirmada neste pacote: #583 em ae15449d, #584 em a5c1b06b. |
| Conta restrita para finalizar envios | feito — integrada no pacote | SHA `80cadcb8`, base #583, independente da #584. Revisão Claude/Codex aprovada; backend e 2.636 casos completos de RLS aprovados, zero falhas/skips. 21 arquivos do commit conferidos com o manifesto revisado. Recursos de teste removidos. Backend, frontend, E2E e RLS aprovados no SHA exato; integração confirmada. Sem produção. Integração confirmada neste pacote: #583 em ae15449d, #584 em a5c1b06b, #585 em 5d4e735e. |
| Parada de comunicado durante envio | feito — integrada no pacote | SHA `cf291a15`, base #577. Revisão final Claude/Codex aprovada; 329 testes distintos e ensaios 200/500 aprovados após correções. Tempo total 4,153/4,057 s, registros preservados e limpeza conferida. Publicação revisada pelo Codex; quatro checks obrigatórios aprovados no SHA exato. Sem merge ou produção. Integração confirmada neste pacote: #577 em 92821e35, #586 em 80b1373f. |
| Permissões dos donos das funções privadas | feito — integrada no pacote | SHA `451fba52`, base #585. Revisões aprovadas; 248 testes locais, incluindo oito novos, sem somar rodadas sobrepostas. Histórico da fatia: checagem de cinco contratos. Candidato atual examina dez contratos mais exclusões específicas; assinaturas presentes não atestam corpo/ACL. Quatro checks obrigatórios aprovados. Sem migration, elevação automática de privilégios, merge ou produção. Integração confirmada neste pacote: #585 em 5d4e735e, #587 em 2c47c160. |
| Credencial da geração de memória | feito — integrada no pacote | Branch `feat/private-summary-runtime-20261026`, base #587. Revisão independente de autenticação/RLS e Codex aprovadas; 507 testes de regressão e 7.039 testes backend + 14 subtestes aprovados, com sobreposição. Migração só sintética; sem ativação. Login principal continua poderoso; entregar a credencial só ao cron e isolar retomada seguem pendentes. Publicada em `cac435c4` sobre #587; quatro checks aprovados, merge não autorizado. Integração confirmada neste pacote: #587 em 2c47c160, #588 em bd673afa. |
| Baixa de alertas de célula | feito — integrada no pacote | Branch `fix/cell-alert-authorization-20261026`, base main `6b0b302b`, independente das PRs de memória. Problema reproduzido duas vezes; 21 novos cenários aprovados e 1.476 casos distintos de regressão verificados em execuções complementares. Revisões Opus e Codex aprovadas. Publicada em `57f47d76` sobre main; quatro checks aprovados. Sem gerador novo, merge ou produção. Integração confirmada neste pacote: #589 em 8a5dcada. |
| Identidade da fila inteira | feito — integrada no pacote | Commit 0f2f6b8d sobre #588; os quatro checks passaram, incluindo os quatro shards e agregador RLS. Modo atual preservado como padrão; credencial dedicada só por configuração explícita, sem fallback. 132 testes locais aprovados com e sem dependência de outro banco; revisão Opus/Codex aprovada. Migration só sintética; sem LOGIN provisionado ou ativação. Integração confirmada neste pacote: #588 em bd673afa, #590 em 383115d1. |
| Falsos “sem interesse” (B5) | feito — integrada no pacote | Commit 21e8975f sobre main 6b0b302b, independente da #590. Quatro checks aprovados. 358 testes locais, incluindo nove de turno; Opus/Codex GO. Heurística limitada, sem reprocessar contatos antigos; opt-out, consentimento e regra geográfica preservados. Sem produção. Integração confirmada neste pacote: #590 em 383115d1, #591 em de437cf2. |
| Números do relatório (B15) | feito — integrada no pacote | Commit a2af8eec sobre main 6b0b302b. Correção revisada por Opus/Codex; 477 testes de regressão e quatro de turno passaram. Quatro checks obrigatórios aprovados no SHA publicado (consulta 18:18 UTC). Sem novo registro oficial, alteração de roteamento ou produção. Integração confirmada neste pacote: #592 em 09bb14d7. |
| Primeiro consentimento (B7) | feito — integrada no pacote | Commit 0c9d6e4b sobre main 6b0b302b. Três testes novos com webhook/migrations reais e 57 regressões passaram; Codex/Opus GO. Uma igreja sintética; fila em memória e LLM simulado. Sem código de aplicação, regra nova ou produção. Integração confirmada neste pacote: #593 em 77a8fd3f. |
| Auditoria após exclusão | feito — integrada no pacote | Commit a2a00891 sobre main 6b0b302b. Documenta UUIDs/hash técnicos preservados, correlação e acessos existentes. Só docs; diff/links/fontes conferidos, Codex/Opus GO. Sem nova retenção, purga, política ou acesso. Integração confirmada neste pacote: #594 em 03d2ad43. |
| Release do piloto e aceite das 20 conversas | falta | Operações reais só com autorização nominal e runbook específico. |

## Evidência operacional — consulta iniciada em 24/10/2026, 15:40 UTC

**Pós-reset — 27/10/2026, 15:20–15:24 UTC:** consultas somente leitura confirmaram 1 igreja, 1 usuário utilizável ligado à Pessoa da mesma igreja, 1 Pessoa, 4 planos, 2 papéis e 1 admin de plataforma; há 1 configuração de agente ativa. Configurações/permissões preservadas são declaração do dono, não comparação integral de conteúdo. Zero mensagens, outbox e fila de trabalho no banco; Redis tem 2 itens em dead, zero na fila principal/retry/processing neste instante. Os dois itens de falha foram preservados, sem leitura de conteúdo nem reenvio. Manifesto de backup: verified em 27/10 06:16 UTC; relação com horário do reset e cobertura pós-reset não verificadas. Nenhuma escrita, backup novo, migration, deploy, restart ou alteração de gates.


**Prévia do vínculo — encerrada pelo dono:** correção cancelada após reset externo. Nenhuma reconciliação foi aplicada. Consulta agregada de 27/10 às 15:20 UTC confirmou zero grupos duplicados. Não retomar a prévia nominal nem solicitar UUIDs, nomes ou credenciais para essa correção.


**Histórico antes do reset — conferência de 27/10/2026, 02:30 UTC:** acesso confirmado à VPS e ao Supabase por CLI (MCP sem permissão). Candidato `afdfb78d`: 129 migrations ativas, 78 registradas, 51 pendentes, 0 desconhecidas; 0 vínculos inválidos de célula; 1 grupo com dois acessos vinculados à mesma Pessoa. Quatro papéis dedicados e dez contratos privados ainda ausentes. API local HTTP200; imagem sem revisão Git, layout legado e URLs dedicadas ausentes. Manifesto de backup `verified` em 26/10 06:16 UTC; restauração/cobertura não verificadas. Gates existentes preservados. Nenhuma escrita, backup novo, migration, deploy ou restart. Bloqueio histórico, posteriormente encerrado: a correção foi cancelada pelo dono após reset externo; a leitura de 15:20 UTC confirmou zero duplicidades. Não executar a reconciliação. As consultas retornaram somente metadados e contagens, sem PII/UUIDs; não foi execução integral de `release_preflight.py`.

Preparação local adicional em 24/10: replay sintético das 78 migrations
operacionais seguido das 46 pendentes produz catálogo idêntico à reconstrução
limpa das 124. A guarda de compatibilidade aditiva recusa corretamente
`previous schema contract changed`; retorno automático ao legado não provado.
Ensaio com dados fictícios passou em 10 verificações de duplicidade,
atomicidade, índice e isolamento, além de 6 testes dos backfills de julho.
Isso não prova os dados reais nem autoriza migrations. Reconciliação nominal posteriormente validada, revisada e integrada pela
#572 (`830decc1`); execução real continua pendente. Ver resultados abaixo.

Verificação somente leitura autorizada pelo pedido do usuário nesta sessão;
não autoriza escrita, migration, deploy, restart nem abertura de gate.

- API: `GET /health` 200 (`status=ok`) e `GET /ready` 200 (`status=ready`);
  app, admin e painel responderam 200.
- Frontend: Vercel confirma deploy de produção READY
  [`dpl_CGiT9GTCvk2GQvcd8T8zhqV12YiK`](https://vercel.com/raniel-levis-projects/pastorai-frontend-prod/CGiT9GTCvk2GQvcd8T8zhqV12YiK),
  aliases dos três domínios, SHA `354a83d891fe7295164d980a175dacdd2feba69e`.
- Backend: OpenAPI público 200, 150 rotas, sem `/auth/logout` nem
  `/admin/logout`. Indica divergência de capacidades entre frontend e backend;
  não prova o SHA do backend nem a ausência real da rota.
- Banco (projeto `pffafnchtxbimpwyaczq`): o conector MCP `codex_apps` segue
  sem permissão, mas o CLI Supabase já autenticado executou `SELECT` dentro de
  `BEGIN READ ONLY` nesta sessão (24/10). Resultado: 78 linhas em
  `public.schema_migrations`; a migration de logout `20261023_120000` não está
  registrada e `public.auth_sessions` não existe; o maior nome lexical
  registrado é `20261002_173000_visitor_expectation_whatsapp.sql` (não indica
  a última aplicação cronológica). Comparação de nomes na mesma via
  somente leitura: 124 migrations ativas no SHA `354a83d`, 78 registradas, 46
  pendentes (exatamente as 4 antigas e as 42 do lote), 0 desconhecidas.
  Consulta agregada equivalente aos dois checks de dados do preflight, em
  `REPEATABLE READ READ ONLY` com `bypassrls=true`: `invalid_cell_links=0` e
  `duplicate_user_person_groups=1` (não é execução integral do preflight; sem
  UUIDs nem PII). A duplicidade bloqueia o lote até reconciliação pelo fluxo
  administrativo autorizado, sem SQL de escrita automático. Nenhuma migration
  aplicada por nós. Outros ledgers e o restante do schema: **não verificado**.
- Devin tem `supabase-prod-readonly` e Hostinger cadastrados, sem ferramentas
  expostas nesta conversa; o OAuth `devin mcp login supabase-prod-readonly` foi
  concluído pelo usuário em 24/10, com retorno `Successfully authenticated`.
  As ferramentas nativas ainda não estão expostas nesta conversa; o CLI
  permite continuar as consultas somente leitura.
- SSH em `srv2031318.hstgr.cloud`: acesso temporário como `igreja12-ops`
  configurado pelo dono e testado em 24/10. O usuário tem sudo completo;
  uso autorizado nesta etapa apenas para consultas. Chave expira em
  26/10 às 00:00 UTC; nenhum arquivo protegido lido.
- VPS: `/opt/pastorai-current` e `/opt/pastorai-releases` ausentes conforme
  consulta do dono; instalação localizada em `/opt/pastorai-lionclaw`, sem Git.
  Backend e três workers usam a imagem
  `sha256:4a65f30e1c2dfbcf84c88e9c88203a4176a8d10f7d1b345248bc367ec9a9b241`,
  criada em 02/10/2026 às 16:44 UTC, sem label de revisão. Sem mounts na
  consulta do dono; `docker diff` do backend vazio na consulta SSH direta.
  Reinícios de 23–24/10 não comprovam release novo. Commit exato do backend:
  **não verificado**. O primeiro release exige transição inicial testada a
  partir dessa instalação, sem inventar SHA nem contornar guardas do script.
- Gates (`docker inspect` com allowlist só dos quatro gates de serviço, sem
  ler `.env`): `backend`, `queue-worker` e `cron-worker` com
  `ALLOW_REAL_SENDS=true`, `BREVO_SEND_MODE=live`,
  `BROADCAST_ASYNC_ENABLED=false` e `ASAAS_BILLING_ENABLED` ausente;
  `broadcast-worker` com `ALLOW_REAL_SENDS=true` (entrada duplicada),
  `BROADCAST_ASYNC_ENABLED=false` e `BREVO_SEND_MODE`/`ASAAS_BILLING_ENABLED`
  ausentes. Ausência não prova `false`; defaults, `AgentConfig.ativo` e Jev:
  **não verificado**. O runbook exige gates fechados como condição da janela
  futura, com contenção e autorização próprias; não é ordem para fechar agora.
- CORS: permite as três origens públicas.
- Consultas agregadas adicionais em 24/10, somente leitura: os predicados
  exatos dos dois backfills de julho retornaram 0 candidatos cada; repetir
  antes da aplicação. O grupo duplicado tem igreja e não envolve liderança
  ativa na consulta atual (1 grupo, 0 sem igreja, 0 com liderança ativa).
  Isso não escolhe a conta a conservar nem autoriza corrigir o vínculo.
- Ferramentas na VPS: Docker Compose 5.6.0 e `timeout` presentes. Backend,
  queue e cron têm labels do projeto Compose `pastorai`; broadcast não tem
  labels de projeto/serviço. A contenção não pode presumir que Compose
  gerencia os quatro containers da mesma forma.
- Identidade histórica da imagem: o ID vivo coincide exatamente com o
  [recibo sanitizado de 02/10](docs/performance/2026-10-02-backend-maintenance-production.json),
  que o associa ao candidato `07a3f4d9a4fe510cf83fd48d5deaa52dcfbb7e02`.
  Hoje `/health` e `/ready` retornam 200 e `x-backend-release=unknown`.
  Isso associa a imagem ao release registrado, sem revalidar todos os arquivos.
  Comparação somente leitura dentro do backend vivo com o `candidate_manifest`
  de `maintenance-profile.json` (`app/*.py` e `requirements.lock`, sem copiar
  conteúdo): 148 esperados, 148 iguais, 0 ausentes, 0 diferentes, 0
  inseguros. Comprova a identidade desse recorte com `07a3f4d`; não comprova
  a imagem inteira nem a configuração.
  O recibo preservava workers legados e Brevo `off`; hoje os quatro serviços
  usam a imagem da API e três declaram Brevo `live`. Quando e por que essas
  mudanças ocorreram: **não verificado**. Raniel confirmou no chat de 24/10
  que Brevo em `live` está autorizado; preservar essa configuração. Essa
  confirmação não autoriza novos testes de envio, deploy ou mudanças de gates.
- GitHub (só metadata): o workflow manual **Backend release** existe no SHA; o
  environment `backend-production` tem revisor e restrição à branch `main`;
  variáveis de allowlist/base configuradas. Nenhum secret
  `BACKEND_DEPLOY_HOST`, `BACKEND_DEPLOY_USER`, `BACKEND_DEPLOY_SSH_KEY` ou
  `BACKEND_DEPLOY_KNOWN_HOSTS` listado no repositório nem no environment
  consultados. Validade de credenciais: **não verificado**.

### Ensaio de contenção e retomada pré-DDL — validado localmente

Autorizado pelo dono após o merge da #572. Fatia isolada na branch
`test/legacy-containment-rehearsal-20261024`, base `830decc1`, com Claude Code
Opus como executor e revisão independente concluída, sem bloqueios de
segurança para o ambiente descartável. Publicada com autorização do dono na
[PR #573](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/573), commit
`61cdf07ed3eb62ccc813e772501b624690dedf22`. Em 24/10 às 20:46 UTC, todos os checks passaram,
incluindo backend-tests, frontend-ci, e2e-critical e rls-integration;
Merge autorizado pelo dono e concluído em 24/10 às 20:50 UTC, SHA `c5c180ca1aa9769c38086d171eb2262c9d371ac1`. Execução em produção não autorizada nesta etapa. Ambiente exclusivamente
sintético: quatro processos, broadcast sem labels Compose, ingresso interno,
pendências e trabalho em curso, parada graciosa, recusa por identidade/timeout
e retomada explícita antes de DDL, preservando a configuração dos gates.

Validação concluída em 24/10: **54 testes unitários e sete cenários Docker
aprovados**. Redis real com dados fictícios; workers e provedor simulados.
Envio em curso antes do SIGTERM comprovado nos casos de conclusão e resposta
perdida; retomada não repete o efeito ambíguo. Pendências, bytes, prazos e gates
preservados. Cleanup de todos os cenários limpo; inventário independente
confirmou ausência de sobras e preservação dos recursos preexistentes.
`production_ready=false`: não é prova de prontidão para operação real.

Regressão de suporte concluída no SHA `830decc1`: 129 testes de queue,
cron e broadcast aprovados, zero falhas/skips, runtime do lock exato e rede
bloqueada. Esse resultado cobre classes e fluxos com provedores simulados;
não é prova de SIGTERM do entrypoint nem da versão legada viva.

O ensaio anterior insere marcadores somente depois de parar e os retira antes
de recuperar; não comprova tratamento de trabalho em curso. O novo recibo
deve separar provas do controlador/topologia simulada das provas de workers
reais. SIGTERM do legado, retry de provedores externos, reinício de daemon e
recuperação pós-DDL continuam não verificados até ensaios próprios. Nenhuma
operação de produção nem reinício do Docker compartilhado foi autorizado.

### Reconciliação excepcional — validação local de 24/10

Fatia isolada em `fix/reconcile-team-legacy-20261024`, baseada em
`354a83d891fe7295164d980a175dacdd2feba69e`. Commit/push/abertura autorizados
pelo dono em 24/10 e concluídos: commit `b2dc832f6a4f7e0f2e757a13a66d485f58e494a4`,
[PR #572](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/572).
Checks oficiais concluídos com sucesso: backend-tests, frontend-ci,
e2e-critical, rls-integration, tooling-static e synthetic-release; preview
Vercel aprovado. Resultado confirmado para o commit `b2dc832f`. Merge autorizado e concluído em 24/10 às 19:25 UTC, commit
`830decc1fb18226e036555f1baae259a467ec62f`. Execução em produção não
autorizada por essa solicitação; merge não comprova deploy ou reconciliação real.
A ferramenta exige escolha nominal de qual acesso desvincular, autorização
atual de admin/operador, confirmação do conteúdo e auditoria atômica. A prévia
é somente leitura. Não houve execução contra produção.

Segunda rodada: **116 testes aprovados, zero falhas e zero skips**, em 74,32 s,
com dois avisos de depreciação. **Limite descoberto depois:** a imagem reutilizada
tinha LangGraph 1.0.10, abaixo do requisito atual >=1.2.3; esse resultado é
parcial. **Revalidação concluída:** os mesmos 116 testes passaram sem falhas
ou skips no runtime exato (Python 3.13.14, LangGraph 1.2.14, manifesto e
pip check aprovados). Inclui baseline sintético das 78 migrations,
reconciliação, aplicação das 46 pendentes, concorrência de revogação,
idempotência e regressão da gestão de equipe. Revisão independente por
Claude Code Opus 5.5: nenhum bloqueio concreto de código. Isso não substitui
`backend-tests`, `frontend-ci`, `e2e-critical` e `rls-integration` do diff antes
da integração. Os testes não comprovam aplicação ou autorização em produção.

Validação local ampliada concluída no ambiente corrigido: Ruff aprovado;
frontend com Node 24 e lock exato passou lint, TypeScript, 1.381 testes
em 153 arquivos, build e smoke de cabeçalhos — passos do workflow reproduzidos
localmente; depois, os checks oficiais da #572 também passaram antes do merge. E2E: 88/88 aprovados em 6,9 min,
com Playwright 1.62.1, Chromium 1234 e API simulada. RLS completo aprovado: 2.566 executados, zero falhas, erros ou skips,
com os quatro relatórios JUnit conferidos pelo verificador oficial. Também
aprovados 13 contratos de coleta/divisão, um contrato de schema de deploy
e oito testes de manutenção PostgreSQL.
Backend offline: 6.927 casos cobertos em execuções complementares — 6.898
aprovados na rodada ampla, 27 Redis7 aprovados separadamente com Docker
real descartável e dois casos de health/performance aprovados após corrigir
a variável de SHA do runner (25 testes na repetição). Contratos deploy/monitor:
213 de 214 comprovados em execuções complementares; o teste que exige
systemd ativo permanece não verificado. Quatro testes JS de monitor passaram
com Node 24. Esses resultados não equivalem a quatro jobs verdes no GitHub. Auditorias Python de runtime (61 dependências) e tooling
(29 dependências) sem vulnerabilidades conhecidas.
Auditoria de dependências frontend de produção: zero vulnerabilidades;
auditoria incluindo desenvolvimento apontou três pacotes afetados já presentes
no lock da base (`undici` high, `vitest` e `@vitest/mocker` moderate).
Correção desses alertas ainda não realizada; não confundir o resultado da
auditoria de produção com ausência de alertas no conjunto inteiro.

Leitura SSH de 24/10 às 17:22 UTC: os quatro containers vivos declaram
`restart=always`; sinal e timeout de parada não estão explícitos nos campos
inspecionados. Prazo efetivo e outros supervisores continuam não verificados.
Nenhum restart ou alteração de configuração foi executado.

Pendente operacional: conter escritores entre a reconciliação e o índice
único, definir recuperação da transição e registrar a prévia no aceite nominal.
A escolha das contas e autorização real continuam humanas; não publicar
identidades no plano ou no chat.

## O que depende de Raniel agora

1. Supabase de produção: conexão atual **não verificada**. O OAuth/CLI
   registrado em 24/10 não comprova acesso nesta sessão. A última consulta
   pelo MCP foi recusada por permissão; em 26/10 o conector manual não apareceu
   entre as ferramentas disponíveis. Reconectar o MCP correto e liberar leitura
   será necessário antes de uma nova consulta autorizada; não enviar tokens no chat.
2. VPS: acesso testado em 24/10 conforme registro histórico; conexão e versão
   em uso agora **não verificadas**. Operações reais continuam condicionadas
   à autorização nominal e ao runbook, sem presumir acesso atual.
3. Preparar as credenciais temporárias do release em GitHub > Settings >
   Secrets and variables > Actions (ou no environment `backend-production`),
   pelos canais seguros; nunca colar no chat. Não executar o release agora.
4. Revalidar antes da janela que a contagem de grupos duplicados de vínculo
   Pessoa continua em zero. A reconciliação foi cancelada após o reset;
   não solicitar identificadores nem executar correção cadastral.
5. A equipe prepara o pacote, a transição inicial testada e o plano de
   contenção dos gates, e pede autorizações separadas (backup, migrations e
   deploy) quando estiver pronto; nada a autorizar nem fechar agora.
6. Aceite das 20 conversas e do G12 após release autorizado à equipe interna;
   não enviar conversas reais ao chat.

Demais correções e testes seguem com a equipe de agentes.

Regra do dono de 25/10: trabalhos de PR são executados pelo Claude Code Opus 5.5 com a skill `/pr`, com acompanhamento e revisão do Codex.

## 1. Organização (histórico)

Roteiro único (#480) e arquivamento documental (lotes 1 e 2, #481/#482) feitos.
Checkout principal em `main` com estado anterior preservado em
`refs/archive/checkout-principal-20261016`. **Falta (dono):** decidir arquivos
locais restantes (`output/`, configurações locais e exemplos de ambiente) e
limpar worktrees antigas de forma recuperável. Nada de limpeza global, apagar
migrations ou branches remotas sem ordem própria.

Consolidação local de 27/10, autorizada pelo dono:
- o checkout principal avançou por fast-forward para a `main` `afdfb78d`, com
  as alterações locais preservadas em stash retido;
- o lote 1 de limpeza removeu 17 worktrees integradas, preservando as branches;
- o plano, o runbook do lote e o painel foram reunidos no checkout principal
  como trabalho local, **ainda não integrado na `main` remota**;
- as worktrees com trabalho local, as divergentes e as sem prova continuam
  preservadas até decisão própria.

## 2. Critério de pronto e saúde técnica

Estado em 27/10/2026: #574–#576 e #577–#593 integradas na `main` (SHAs abaixo e no
runbook do lote). Código integrado não é release. Nesta integração não houve
execução em PROD nem aplicação remota de migrations, e não alteramos gates nem
ampliamos o piloto. Provisionamento dos LOGINs dedicados e estado atual de
produção: não verificados.

Atualização operacional de 24/10: a reconciliação excepcional de vínculos
Pessoa foi integrada pela #572 (`830decc1`), com checks aprovados; não foi
executada em produção. A fatia local de contenção pré-DDL passou em 54 testes
unitários e sete cenários Docker, com revisão Claude Opus e limpeza completa.
Cobre controlador/topologia sintéticos, não os entrypoints legados nem
recuperação após DDL real; `production_ready=false`. Integrada pela #573
(`c5c180ca`), com backend-tests, frontend-ci, e2e-critical e rls-integration
aprovados. A fatia seguinte passou localmente: ciclo de vida do entrypoint
real do queue-worker de `07a3f4d`, Redis descartável e dependências do legado;
88 testes (novo controlador + regressão da contenção) e sete verificações
físicas aprovados, limpeza sem sobras. Entrega na branch
`test/legacy-queue-entrypoint-20261024`; integração depende dos checks da PR.
Não inclui turno ativo, envio externo ou produção. Próxima prova: ingestão
ativa com barreira transacional em PostgreSQL sintético.
Ver [runbook atualizado e limites](docs/ops/RELEASE-LOTE-2026-10.md).

Em 25/10, a #574 (`94a4b9ec`) está aberta com todos os checks aprovados.
A etapa de ingestão ativa foi validada localmente na branch
`test/legacy-queue-active-ingestion-20261025`, baseada nesse commit.
Prova independente de ingestão ativa passou localmente em 25/10: espera no
lock observada, nenhuma mensagem antes da liberação, commit único, consentimento,
ACK e saída zero; limpeza concluída. A extensão independente também passou:
reenvios após reinício com e sem marcador Redis, contagens/não lidas
preservadas e sessão legada autenticada com leitura de outra igreja vazia
e INSERT recusado por RLS (`42501`), com escrita permitida na própria igreja.
O ensaio permanente passou em 130 testes (42 novos + 88 de regressão) e 20
verificações físicas, limpeza sem erros/sobras, revisão Claude incorporada
e verificação final pelo Codex. A barreira fica antes das escritas do domínio;
não prova turno completo do agente nem produção. Sem alterações em PROD.

Ingestão ativa integrada pela #575 (`a3e83a51`), após a #574. Fatia seguinte
na branch `test/legacy-cron-active-20261025`: o cron-worker real de `07a3f4d`
recebe SIGTERM com a purga de fluxos OAuth fictícios bloqueada por row lock,
e só depois da liberação se exige remoção única do expirado, válido preservado,
tick concluído, heartbeat `stopped`, saída zero e nenhum novo tick. O `stop()`
legado não interrompe o tick (SLA/crons/billing seguem após o sinal); contenção
só após a saída. Primeira rodada em 25/10 (Codex): 172 testes e ensaio físico
com 13 verificações aprovados, bloqueio 5,918 s, saída 0,626 s após liberação,
limpeza completa; revisão independente sem bloqueios. Depois disso a guarda
temporal ficou mais precisa (medida após o último check, heartbeat reconfirmado
antes de liberar). Revalidação final local concluída: 176 testes (46 novos + 130
de regressão, zero skip) e 13 verificações físicas aprovadas, bloqueio 6,445 s,
saída 0,652 s, limpeza sem sobras. Integrada pela #576 (`6b0b302b`). Não prova supervisor/restart, pós-DDL, outros serviços nem produção.

Tick ativo do cron integrado pela #576 (`6b0b302b`). Broadcast ocioso integrado
pela #577 (`92821e35`), branch `test/legacy-broadcast-stop-20261025`: ciclo de vida do broadcast-worker real
de `07a3f4d` **ocioso** (gates fechados, sem Postgres), PID 1 sem `init`
(`HostConfig.Init=false`): heartbeat `idle` renovado, log `enabled=False` sem
tick/envio, SIGTERM com saída zero e `stopped`, reinício do mesmo container como
nova execução e segundo SIGTERM limpo. Validação final local (Codex): 216 testes
(40 novos + 176 de regressão, zero skip) e 10 verificações físicas aprovadas,
saídas 0,503/0,549 s, limpeza sem sobras; revisão independente incorporada.
Checks do SHA `f8ded9c6` verdes antes do merge. Ausência de rede é inferida
(destinos mortos, gates `false`, caminho ocioso do código), não capturada. Não
prova broadcast ativo, transporte/pendências, supervisor, pós-DDL, RLS nem produção.

Backend em curso integrado pela #578 (`64d7509d`), branch
`test/legacy-backend-stop-20261025`, desenvolvida sobre `6b0b302b` sem depender
da #577 e atualizada com a `main` após ela: o backend ASGI
real de `07a3f4d` (`uvicorn app.main:app` como PID 1, sem init) recebe SIGTERM
com um `POST /whatsapp/webhook` autenticado em curso, com o corpo parcial retido
pelo cliente. Antes da liberação se exigem: ACK no cliente, conexão retida pelo
PID 1 sem bytes pendentes, listener fechado e fila vazia. Depois: 202, um evento
na fila, saída 0 e bytes preservados após reinício sem consumidor. Validação
local final em 25/10: 279 testes (103 novos + 176 de regressão, zero skip) e
ensaio físico do Codex com 12 verificações, retenção 6,600 s, saída 1,202 s após
a liberação, limpeza sem sobras; revisão independente incorporada. Sustenta um
ciclo HTTP aberto, não a linha exata do handler; um request gera um envelope,
sem prova de idempotência. `/health` 200 não é readiness. Não prova consumo pelo
worker, agente, RLS, supervisor, topologia viva, pós-DDL nem produção.
Checks do SHA `b58b64c0` verdes antes do merge.

Transição inicial integrada legado→atual: entrega local validada (25/10, branch
`test/initial-legacy-transition-20261025`); integrada pela #579 (`84fb7f11`),
checks do SHA `f9d71d74` verdes antes do merge. `deploy/initial_transition.py` conduz a primeira virada que
`backend-release.sh` recusa: contenção durável dos quatro processos de `07a3f4d`
(3 Compose + broadcast avulso, `restart=no` persistido antes do SIGTERM), drain
conferido item a item com filas críticas preservadas (principal, DLQ, retry
agendado), reconciliação real, 46 migrations por `migrate.py` após marcador
irrevogável e candidato da fonte `6b0b302bd1c1` (imagem derivada local não
oficial) em projeto Compose separado, com readiness real e layout
`releases/<SHA>`. Ensaio sintético completo aprovado na rodada 3 (684,1 s,
quatro cenários + catálogo de referência); a correção final da retomada foi
reensaiada só no pré-DDL (54,9 s). Revisão da PR: a reconciliação commitada antes de
uma queda é recuperada no replay só como delta exato autorizado (cenários
`main`/`pre-ddl` reensaiados em PostgreSQL sintético).
Forma de PROD = instalação observada em
24/10, não reverificada. Adoção persistente da topologia do candidato pelo
instalador: integrada pela #580 (`74919ee0`). Retomada
pré-DDL de legado com `RestartCount>0`: corrigida em
`fix/legacy-resume-restarts-20261025` (só aceita o start do próprio
controlador; replay terminal revalida), integrada pela #581 (`87ba1e42`; checks
do SHA `3f0a9d98` verdes antes do merge).
Não prova reinício do daemon, retry real da Evolution, turno do agente nem produção.

Adoção persistente da topologia: integrada pela #580 (`74919ee0`), branch
`feat/persistent-release-topology-20261025`, redirecionada à `main` após a #579;
checks do SHA `3406616b` verdes antes do merge (`backend-tests` na segunda
tentativa, após timeout do `pg_isready` num teste de monitor alheio à fatia).
`backend-release.sh` (segurança v3; o workflow passa a exigir v3) adota
`deploy/release-topology.json` só do release ativo (projeto permanente, rede
externa existente, nomes e IDs legados reservados), com `-p` e ordem
base→topologia→checker→pin em toda chamada, contenção só de IDs próprios e
rollback pelo ID de imagem verificado (sem rebuild), nos modos build e digest.
Ensaio físico sintético desde o `write_layout` real aprovado (rodada 5, após
integrar `9047c591`: 54 verificações, sem sobras); callback real da Evolution
não provado; tags de retenção de imagem acumulam sem poda automática.
Atualizar `BACKEND_DEPLOY_SAFE_BASE_SHA` após o merge: passo operacional não
executado. Legado com `RestartCount>0`: retomada pré-DDL tratada pela #581;
`production_ready=false`.

Fatia seguinte, sobre a #577 (integrada em `92821e35`), na branch
`test/legacy-broadcast-active-20261026`, integrada pela #586 (`80b1373f`; checks
do SHA `5459824d` verdes antes do merge): broadcast-worker real de `07a3f4d`
com envio **ativo** durante SIGTERM. Gates abertos só no container sintético,
Evolution falsa na rede interna, Postgres/Redis descartáveis e três entregas
fictícias em duas igrejas, materializadas pela função legada. A falsa retém a
1ª requisição, observada antes do sinal; com o sinal, log de transporte em
andamento, processo vivo, uma requisição e banco inalterado. Após liberar:
resultado commitado (`aceito`; variante 500 → `desconhecido`), demais entregas
intactas, saída 0 e `stopped`; o reinício do mesmo container drena só as duas
pendentes, sem repetir a retida. Em todas as fases o ledger tem exatamente
2 broadcasts, 2 execuções e 3 entregas com os IDs do seed; o total do comando
SIGTERM até a saída é medido e recusado a partir de 10 s. Validação local
(Claude), após correção da revisão Codex: 329 testes (113 novos + 216 de
regressão, zero skip) e rodadas físicas 200 e 500 aprovadas, 19 verificações
cada, total de 4,2/4,1 s, limpeza sem sobras. Revisão Claude e Codex aprovada.
Retida sempre na igreja A; igreja de entrega única só em teste unitário. Prova
só nenhum **segundo** envio após o sinal; não prova `docker stop`/SIGKILL,
agendados, 429, vários workers, supervisor, pós-DDL nem produção.
Compatibilidade na integração: as migrations `20261030_*` (#583–#585) faziam o
preflight dos ensaios com baseline (`select_baseline`) recusar por contagem
total; agora só o conjunto de 78 antes do corte é fixo (seleção, SQL e bundle
iguais aos de `cf291a15`; na data, 127 ativas; com as #588/#590 são 129, sem
efeito na seleção de 78). As rodadas físicas acima não foram repetidas.


**Um módulo só está concluído** quando tem, nesta ordem: (1) código na `main`
com os quatro checks e E2E do turno completo quando envolve o agente;
(2) release controlado para o piloto interno: migrations aplicadas com backup
prévio, runbook e gate aberto só para as igrejas/testadores listados, por
decisão nominal do dono; (3) aceite pastoral registrado com conversas/telas
reais desse piloto; (4) abertura ampliada por nova decisão nominal;
(5) monitoramento e procedimento de desligamento conhecidos.
"Feito (código)" abaixo cobre só o passo 1; os passos 2 e 4 exigem autorização
humana nominal e nunca são inferidos de merge ou teste verde.

**Estoque desligado:** UV, CD, Enviar, oração, células próximas, memória,
conhecimento e agenda pelo WhatsApp estão prontos só no passo 1. Antes de abrir
novas frentes grandes, priorizar o aceite das 20 conversas e um release em lote
planejado (migrations acumuladas, backup, reconciliação de duplicidades de
vínculo Pessoa e ordem de aplicação), para transformar estoque em uso real.

**Saúde técnica (metas medidas, uma fatia por PR, sem reescrita geral):**

| Meta | Medida em 22/10 (atualizada em 23/10) | Alvo |
|---|---|---|
| Tempo do `rls-integration` | 16–23 min serial em 22/10; 23/10: ~9–10 min com 4 partes paralelas (#550) e `backend-tests` ~4 min sem apt (#553), 0 skip | ≤ 8 min com divisão em partes paralelas, sem `skip` |
| Verificação estática do backend | ruff com regras de erro no CI (#554); tipagem ainda não | ruff só com regras de erro no CI; tipagem depois, por pasta |
| Arquivos de produção gigantes | `models.py` 5,0k, `queue_worker.py` 5,0k, `cell_report_audio_service.py` 4,1k, `routers/subscription.py` 3,7k, `notification_outbox.py` 3,5k, `agent/runtime.py` 2,3k linhas | arquivo tocado não cresce além de ~800 linhas; extrair uma responsabilidade coesa por PR quando a área for tocada |
| Camadas | acesso direto ao banco em 31/41 routers; inversões serviço→router eliminadas, com teste de camadas que cobre import relativo e alias (#555) | eliminar as 2 inversões; mover consulta para o serviço ao tocar a rota |
| Isolamento por igreja | helpers RLS novos e legados convivem | migrar um caminho por PR com teste PG de duas igrejas |
| Código pausado | ~5k linhas E4B/purpose consent no app | decidir: manter isolado ou arquivar em PR própria |
| Migrations | 17 nomes legados | checar padrão só nos arquivos novos; não renomear histórico |
| E2E do painel | Playwright usa API simulada | um E2E sintético navegador → FastAPI de um fluxo crítico |

## 3. Próximas funcionalidades

| Entrega | Estado | Implementação / teste | Produção |
|---|---|---|---|
| Pedido de oração pelo WhatsApp (V4) | feito | Primeira versão de texto e pedido próprio integrada na main pela [PR #484](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/484), merge `2d408d92`; implementação e testes registrados. DESLIGADO por igreja e por trava de release; sem produção. Sigilo da coleta/histórico integrado pela #515; áudio protegido retido e excluído pela fila privada (#529) (backend/RLS, marcador, prévia e mídia; exclusão privada #509 e fila durável). Fatia 2 integrada pela #519: inbox mostra marcador acessível e orientação ao pastor, reconcilia a cada poll (texto e mídia protegidos somem no mesmo ciclo), mantém leitura autorizada pelo servidor, paginação/handoff/busca e mostra recibo de exclusão atualizável; sem backend/migration ou ativação. Decisões pastorais provisórias. Pendente: aceite pastoral (áudio já integrado pela #529). | não verificado em produção |
| Indicar células próximas | feito | Indicação guiada somente por bairro integrada na main pela [PR #486](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/486), merge `1caf4a36`; implementação e testes registrados. Só células ativas com divulgação autorizada, sem endereço ou dados do líder; sem cálculo de distância ou vínculo automático. DESLIGADO por igreja e por trava de release; sem produção. | não verificado em produção |
| Fluxo G12: ganhar, consolidar e célula | em andamento | Implementado na main, desligado e sem produção: evento real de visita de célula ligado à Pessoa ([PR #487](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/487), merge `05eb07b9`); aceite explícito da fonovisita com convite de 24h, troca após aceite e autoatribuição ([PR #488](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/488), merge `8d3d13f2`); primeira visita sugere vínculo com a célula, confirmado por pastor/admin ([PR #489](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/489), merge `b3fdd6fc`). G12 PR 5 integrada na [PR #490](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/490): percurso reunião → atraso → lembrete → baixa comprovado pelo agente e painel com provedor simulado; supressão terminal registrada só para igrejas da release/lista V1a; handoff e conexão indisponível são transitórios; nenhum gate aberto. Falta aceitar com o piloto o caminho completo. | Fluxo completo: não verificado |
| Aceite pastoral do atendimento | falta | Aprovar 20 conversas reais, incluindo visitante, oração, horário, opt-out e crise; corrigir os problemas encontrados. Roteiro preparado, não executado: [aceite pastoral do piloto](docs/ops/ACEITE-PASTORAL-PILOTO.md). | não verificado |

## 4. Demais funcionalidades e qualidade

Modularizar a área quando ela for tocada, preservando os serviços existentes,
segundo as metas de saúde técnica da seção 2.
Sem reescrita geral, renomeio em massa ou refatoração como pré-requisito de tudo.

| Entrega | Estado | Implementação / teste | Produção |
|---|---|---|---|
| Atendimento básico, consentimento, opt-out, passagem para humano e informações públicas | feito | Resposta de IA ao texto atual, contexto curto da conversa e consultas determinísticas registrados; isolamento e controles mantidos. | Piloto registrado; estado atual não verificado. |
| Ações por papel (S3) | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Relatório por texto (V1a) | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Relatório por áudio (V1b) | feito | Versão base na main, com testes sintéticos registrados. Decisão pastoral 15 (18/10, Raniel), integrada pela #512: mídia, transcrição e hashes sob consentimento v2 sem purga automática de 24h; saída por exclusão admin/aprovação de pedido da pessoa. Capturas v1/sem versão v2 preservam purga de até 24h. Exclusão por conversa (#509), pessoa/igreja (#518/#541/#561) e pedido da pessoa pelo WhatsApp com decisão do admin (#535) estão implementados, todos desligados (pedido: release None, lista vazia); operação não comprovada. Risco: maior volume retido; sem migration/backfill. Ver [política](docs/ops/EXCLUSAO-PRIVADA.md). Antes de ativar: pré-requisitos de Memória privada abaixo (upload com resultado desconhecido, identidade do worker, tombstones); validar a operação desses caminhos, porque o aviso v2 promete o pedido de exclusão. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Agenda V2 | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Consolidação V3 | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Presença própria (V4) | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Expectativa de visitante (V4) | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Simulador e prova integrada de visitante | feito | Transporte falso, fila Redis, worker, catálogo, autorização, banco com isolamento entre igrejas e acesso autenticado; testes locais/CI registrados (#462/#466). Não prova aceite online pelo navegador nem lembretes com gates fechados. | Simulador não se destina a PROD. |
| Ferramentas de desenvolvimento e testes | feito | Versões alinhadas ao CI; `test-local.sh` recusa alvo desconhecido (#464), com teste registrado. Corrige o falso sucesso sem executar testes. | Ferramenta de desenvolvimento. |
| Refatorações de visitante e leitura da resposta | feito | Validação de nome no domínio e leitura fora do worker, com regressão registrada (#465/#467). | não verificado |
| Universidade da Vida | feito (código) | Integrada na main em 18/10 (#491–#494, #496): turmas, calendário de oito aulas + Encontro, responsáveis, matrícula explícita, chamada com reposição e correção com histórico, marcos Encontro/batismo, conclusão humana com aptidão à CD e WhatsApp do responsável **desligado** (`UV_WHATSAPP_APPROVED_RELEASE_ID=None`). Migrations `20261017_210500`, `_220000`, `_230000` validadas só em PostgreSQL local sintético. Corrida em 26/10: dois pedidos iguais de criação de turma ao mesmo tempo podiam gerar exceção não tratada na rota, comprovada em simulação (`unique(igreja_id,id)` fora do árbitro de `on conflict(id)`; HTTP de produção não testado). Correção na PR #596 (`fix/uv-turma-race-20261026`, `on conflict do nothing`), com teste PG real pela rota (24 pares por papel, admin e líder; vermelho no código antigo e verde com a correção; 89 testes do arquivo UV aprovados, rodada local na base `2c47c160`); ainda não integrada. `uv_matriculas` e `cd.create_turma`: padrões semelhantes a diagnosticar, não verificados. | Aplicação das migrations: **não verificado**; ativação não autorizada. |
| Capacitação Destino | feito (código) | Base integrada em 18/10 (#495, #497–#501): currículo versionado, turmas, matrícula, frequência/reposição, conclusão, progressão, equivalência e certificado revogável. Integrada em 19/10 (#511): equivalência entre versões da mesma família sem matrícula nova, origem rastreada, pré-requisitos/certificado e matrícula concluída fora do índice de andamento. CD não promove liderança; WhatsApp **desligado** (`CD_WHATSAPP_APPROVED_RELEASE_ID=None`). Migrations CD `20261018_010000`–`_040000` e `_090000` só em PostgreSQL local sintético. Corrida em 26/10 (falha RLS da main `87ba1e42`): criação idêntica concorrente de currículo podia dar 409, porque `on conflict(id)` só arbitrava a PK e `unique(igreja_id,id)` levantava violação. Corrigida pela #595, integrada em 27/10 (merge `7bc7fa72`; `on conflict do nothing`, releitura e 409 preservados), com teste PG real que sincroniza o INSERT (16 pares, vermelho no código antigo e verde com a correção); produção não verificada. `uv_turmas`: correção na PR #596, ainda não integrada. `cd_turmas` e `uv_matriculas`: padrões semelhantes a diagnosticar, não verificados. | Aplicação das migrations: **não verificado**; ativação não autorizada. |
| Enviar e multiplicação | feito (código) | Integrado em 19/10 (#502–#507, #510, #520): contrato de aptidão, avaliação humana com eventos imutáveis, nomeação de líder e abertura de célula por solicitação com aprovação web de pastor/admin distinto do autor/candidato, tela Enviar, evidências oficiais UV/CD/Reencontro (Reencontro validado/revogado/revalidado com histórico; revogação bloqueia novas operações, sem promoção/destituição automática) e WhatsApp **desligado** (`ENVIAR_WHATSAPP_APPROVED_RELEASE_ID=None`, lista por igreja vazia): consulta mínima de pendências/evidências e solicitações após SIM literal, com idempotência e recibo após commit; avaliação, validação e aprovação ficam no painel autenticado. Pré-requisito de release: usuários da coordenação vinculados a uma Pessoa ativa (`app_users.pessoa_id`). Ajustes P2 do WhatsApp integrados pela #521 (`c7166cd1`): roteamento restrito ao catálogo, confirmação objetiva e aviso de paginação. Migrations `20261018_050000`–`_080000` e `_100000` só em PostgreSQL sintético; aplicar UV/CD/Enviar antes do deploy do backend; `_080000` valida FK em `celula_solicitacao` e pode falhar com linha legada inconsistente. | Aplicação das migrations: **não verificado**; ativação não autorizada. |
| Memória privada durável | em andamento | Exclusão antes de memória nova. Integradas: fila durável de exclusão (#509), exclusão por pessoa e igreja/reset (#518), resumo privado por conversa (#526), retomada privada pelo comando exato "retomar conversa" (#531), pedido de exclusão com decisão web do admin (#535) e reset privado por pessoa no painel (#541). Contagens privadas agregadas no Hoje do admin (#546) e reset privado por igreja com confirmação pelo nome, SLA dos pedidos e quitação atômica dos pedidos pendentes cobertos pelo recibo (#561, migration nova, não aplicada). Tudo DESLIGADO (release None, lista vazia, flag false, teto 0). Integrada pela #582 (`1a5cb9c9`; checks do SHA `c37972d9` verdes antes do merge): 2xx do Storage após o prazo resolve a ownership do upload de áudio, sem transcrição; resultado desconhecido segue retido. Integrada pela #583 (`ae15449d`; checks do SHA `02335e89` verdes antes do merge; migration `20261030_100000` só em PG sintético, não aplicada em PROD): tarefas de limpeza e uploads de áudio usam só o login dedicado `private_storage_runtime` (NOBYPASSRLS, RLS por igreja, `search_path` fixo com `pg_temp` por último, sem fallback); sem ele novas entradas de áudio ficam pendentes sem download/upload/transcrição e a limpeza não roda (recibos pendentes); recuperação e reenvio de respostas seguem. Integrada pela #584 (`a5c1b06b`; checks do SHA `9ae8032a` verdes antes do merge; migration `20261030_110000` só em PG sintético, não aplicada em PROD): reconhecimento positivo PARCIAL de upload de áudio commitado cuja resposta se perdeu (token por tentativa commitado antes do POST em `x-metadata`, info do Storage estrito, CAS do token também no finish, liberação só com tarefa pendente); ausência/erro/tempo nunca liberam; abortado/em voo e legado seguem retidos; ensaio só contra storage-api `6dd28b4` local, hospedado não verificado. Integrada pela #585 (`5d4e735e`; checks do SHA `0190cd00` verdes antes do merge; migration `20261030_120000` só em PG sintético, não aplicada em PROD): a liberação da ownership de envio usa só o login dedicado `private_send_runtime` por função com chave e igreja; `authenticated` perde só o DELETE; INSERT/renovação seguem nas transações do domínio; a liberação não mascara mais retry/perda de claim. Sem o login, respostas seguem, mas a ownership fica retida (recibo `pendente_envio`, retentável não reenviado). Não protege contra dono/BYPASSRLS. Integrada pela #588 (`bd673afa`; checks do SHA `b2978c5b` verdes antes do merge; migration `20261030_140000` só em PG sintético, não aplicada em PROD): todo o ciclo de geração de resumos do cron (descoberta, claim, reserva, projeções e publicação) usa só o login dedicado `private_summary_runtime`, sem fallback; grants mínimos em quatro tabelas privadas, orçamento só por função de custo fixo, tabelas centrais só por seis projeções tipadas; orquestração, ordem de locks, HTTP sem sessão e revalidações inalteradas; `enqueue`, solicitante NULL e permissões antigas de `authenticated` intactos (login principal com BYPASS segue capaz: limite declarado). Sem o login, a geração não roda. Integrada pela #590 (`383115d1`; checks do SHA `8a59a796` verdes antes do merge; migration `20261030_160000` só em PG 17.6 sintético, não aplicada em PROD): modo explícito `QUEUE_WORKER_DATABASE_MODE` (`legacy` padrão, piloto inalterado; `dedicated` só com `QUEUE_WORKER_DATABASE_URL`, sem fallback) em que toda a fila normal (ingestão, turno, fences, retomada, CAS/ownership/renovação de envio e lease) roda no login `queue_worker_runtime` (NOBYPASSRLS, NOINHERIT, uma membership em `authenticated` sem ADMIN, papéis e estado da conexão provados a cada checkout/BEGIN; igreja descoberta só por função tipada); configuração Jev ilegível no turno privilegiado vira handoff de gate fechado. Não operacional: LOGIN não provisionado, modo do pooler/versão/memberships de PROD não verificados ([runbook](docs/ops/FILA-LOGIN-DEDICADO.md)). Pré-requisitos de ativação abertos: reconciliação de upload com resultado desconhecido (abortado/em voo/legado; versão, gateway e versionamento do Storage hospedado), identidade dos fences, do INSERT/renovação de envios e da retomada privada (só a geração de resumos foi isolada; tarefas, uploads, liberação de envios e geração de resumos integrados; fila normal integrada pela #590 em modo `dedicated` opcional, não operacional), provisionar os logins nominalmente e separar a URL por processo (API/queue/cron/broadcast compartilham o mesmo `env_file`), expiração de tombstones, dono/BYPASSRLS das funções no release (integrada pela #587 (`2c47c160`; checks do SHA `e9117752` verdes antes do merge): prova em PG sintético de que, com dono sem BYPASSRLS, liberação de envio, limpeza do Storage e exclusão falham fechadas, sem recibo verde nos cenários provados; o preflight somente leitura acusa dono sem SUPERUSER/BYPASSRLS nos contratos privados presentes (dez: cinco da #587, dois da #584 e três da #588, cujo corpo lê tabela com FORCE RLS; o resolvedor `queue_resolve_instance` da #590 lê só tabela sem FORCE e é exclusão explícita, válida se o dono da função for dono da tabela ou tiver BYPASSRLS, com os logins da aplicação sem BYPASSRLS; dez contratos + cinco exclusões = 15 definers `row_security=off` classificados) e lista como não verificados os ausentes; dono real em PROD e preflight pós-migration: não verificados). Ver [operação/limites](docs/ops/RESUMOS-PRIVADOS.md). | não verificado |
| Conhecimento oficial | em andamento | Base versionada e API editorial (#513/#514), busca autorizada (#516), painel editorial (#517), exclusão definitiva admin com confirmação (#524) e consulta pelo WhatsApp com fontes autorizadas (#525), DESLIGADA (`CONHECIMENTO_WHATSAPP_APPROVED_RELEASE_ID=None`, lista vazia), sem ingestão de conversas. Falta aceite pastoral e decisão 21 definitiva. | não verificado |
| Ferramentas e especialistas por área | em andamento | Ampliar rotinas pelo WhatsApp usando os mesmos serviços do painel; comportamento global versionado, dados e execução por igreja, credencial OpenAI própria da igreja. | não verificado |
| Pessoas, responsabilidades, Minha Célula, Central e Hoje | em andamento | Integradas: pendências da Central em Hoje (#528), responsabilidade por setor com vigência (#530), pendências por responsabilidade vigente (#534) e gestão web de responsabilidades (#539). O aviso de contas da coordenação sem Pessoa ativa já foi entregue pela #557. Integrada pela #589 (`8a5dcada`; checks do SHA `868fecd1` verdes antes do merge): a baixa de alerta de célula passa a seguir a regra da leitura (pastor/admin ou líder direto, escopo do detalhe, `igreja_id` explícito); superior na cadeia deixa de baixar alerta que não vê. Faltam planejamento e o gerador de alertas (RF-26), que depende de decisão sobre gatilhos. | Cobertura completa: não verificado. |
| Triagem semântica Jev | em andamento | S1 implementada/testada com simulações; falta avaliar qualidade real, crise/humano e falsos opt-outs, contrato de tratamento de dados e autorização específica. Jev B/C/D continuam condicionados. | não verificado; não autoriza ativação. |
| Comunicados, assinatura/Asaas e e-mail/Brevo | em andamento | Bases implementadas; faltam aceite por finalidade, domínio/remetente e canários separados. Não envolver a igreja em cortesia em cobrança real. | não verificado |
| Onboarding da igreja, equipe, permissões e console | em andamento | Integradas: autorização de telas isolada por igreja (#536), reenvio de convite isolado (#538) e vínculo Pessoa ↔ usuário pelo admin, com auditoria e índice único (#543); ativação trava a igreja antes de Pessoa/usuário, eliminando a espera mútua com a gestão de equipe, com teste da corrida com convite que já traz Pessoa (#556). A tela de equipe sinaliza contas sem Pessoa vinculada (#557). Leitura após reset em 27/10: zero duplicidades de (igreja, pessoa). Correção nominal cancelada; revalidar ausência antes da migration da #543. | Cobertura completa: não verificado. |
| Exclusão da pessoa, exclusão da igreja e reset | em andamento | Fatias integradas: #509, #518, pedido da pessoa com decisão admin (#535) e reset privado por pessoa (#541). Reset privado preserva cadastros/opt-out/consentimento e não autoriza reset cadastral. A trilha de vínculo Pessoa (#543) guarda UUIDs após exclusão aprovada; contrato atual documentado (#594) no [runbook de exclusão](docs/ops/EXCLUSAO-PRIVADA.md#trilha-de-vínculo-pessoa-543-após-exclusão), sem anonimização nem purga; produção não verificada. Novos derivados acompanham sua implementação. | não verificado |
| UX, acessibilidade e desempenho do painel | em andamento | Integradas: teclado nas abas da Central (#527) e foco/anúncios/reflow no atendimento (#532). Faltam leitor de tela e celular reais, zoom e métricas autenticadas de campo. | Frontend publicado conforme registros; backend/telemetria e operação completa: não verificado. |
| Agenda completa e importação Google | em andamento | Operações locais pelo WhatsApp com SIM e recibo integradas (#540), desligadas. Lembretes pela outbox com gate próprio fechado (#547) e janela configurável por evento (2h/24h/72h/168h, públicos existentes, invalidação de pendentes; #560). Faltam G2b e credencial Google isolada por igreja antes de usar Google. | não verificado |
| Observabilidade de IA e operação | em andamento | Há logs/custos/filas, consumo de IA por igreja (#537) e idade/contagem agregada de mensagens e tarefas pendentes por igreja (#544, só admin, sem conteúdo); outbox e webhooks entram na medição, com DLQ separada e função de métricas restrita a admin ativo da igreja (#562, migration nova, não aplicada); alerta `stuck_flow` preparado e DESLIGADO até existir credencial dedicada de leitura. Faltam métricas por rota, retenção e metas de serviço. | não verificado |

**Segurança e decisões que permanecem abertas:**

- **em andamento:** auditoria de 03/10: redação de segredo em logs e escopo
  de igreja nas rotinas automáticas integrados (#558). Faltam MFA no console
  (depende de ligar no Clerk). Logout no servidor integrado pela #568
  (`354a83d8`); aplicação da migration `20261023_120000` e publicação em
  produção: **não verificado**. Release segue o [runbook do lote](docs/ops/RELEASE-LOTE-2026-10.md):
  migration, backend e frontend, e o deploy encerra todas as sessões. Acessibilidade
  automática (axe WCAG 2.1 A/AA) nas telas principais integrada (#559); leitor
  de tela e celular reais: **não verificado**.
- **em andamento:** dependências corrigidas e triadas (#463/#469/#470; Next 15.5.28 em #552);
  auditorias das dependências de produção registradas como limpas em 10/10, mas permaneciam cinco
  alertas altos nas ferramentas ligados a `braces`. Situação atual **não verificado**.
- **falta:** decidir a divergência de acesso customizado ao inbox, opt-out no
  envio humano e expectativa de visitante em reunião passada (backlog técnico
  B3/B4). Preservar opt-out global e regras por canal até decisão; refatoração
  não muda comportamento silenciosamente.
- **em andamento:** B5 (CSIM comercial) integrado pela #591 (`de437cf2`; checks
  do SHA `a9ca7c0a` verdes antes do merge): "comercial" passa a exigir
  oferta explícita do próprio contato (verbo em 1ª pessoa ou após auxiliar em
  1ª pessoa, + objeto, palavra inteira, sem negação/citação); empresa,
  profissão, boleto ou marketing como assunto, terceira pessoa ou pergunta
  genérica deixam de fechar o atendimento. Heurística limitada, sem LLM; ofertas
  fora da lista passam despercebidas e "preciso de oração, quero vender
  produtos" ainda marca (1ª pessoa). Sem reprocessar contatos já marcados; "fora da cidade"
  inalterado. Ativação do agente e efeito em produção: **não verificado**.
- **em andamento:** B15 (interpretação de relatório): a extração de contagens do
  resumo legado foi integrada pela #592 (`09bb14d7`; checks do SHA `59d8f129`
  verdes antes do merge): `presentes: 12` em linhas ou numa linha não empresta
  número de outro rótulo, com teste do turno no banco descartável. Gatilho por
  palavra + dígito e o restante de B15 seguem abertos.
- **em andamento:** B7 (primeiro consentimento) reconferido em teste com
  migrations reais e contato fictício: termo → "Aceito" → aceite da versão
  atual gravado → turno seguinte vai ao onboarding sem repetir o termo; recusa
  não grava aceite e opt-out bloqueia aceite posterior
  (`test_consent_multiturn_e2e_pg.py`), integrado pela #593 (`77a8fd3f`; checks do
  SHA `8ea84977` verdes antes do merge). Não prova Redis, Evolution
  nem LLM reais; produção **não verificado**.
- **falta:** não declarar B5/B7/B15 resolvidos pela presença em auditoria.
  B1/B2/B3/B4/B14/B16 têm correções registradas, com disponibilidade atual em
  produção **não verificado**.
- **falta, quando houver necessidade concreta:** diagnóstico de configuração
  sem segredos, registro de ações sem relaxar autorizações e retirada individual
  de código/testes com proteção equivalente (B1/B2/B5 do backlog técnico).
  Medir ganho real por fatia na PR, sem percentuais inventados (B6).

**Trabalhos a preservar fora da main, conforme inventário de 15/10:** medições,
ferramentas de avaliação da interpretação e demonstração V1a de 13/10 em
`integracao-incremental-20261013`; auditoria em
`arquitetura-performance-seguranca-20261003`. Integração desse material e estado
dos arquivos não salvos: **não verificado**. Nenhuma cópia ou descarte nesta entrega.

**Decisões pastorais aprovadas em 18/10 (Raniel):**

- CD: 6 módulos de 10 aulas; todas as aulas com reposição; sequência linear, exceção só pela coordenação (admin/pastor); certificado após módulos obrigatórios e confirmação da coordenação; CD não promove a líder.
- UV: conclusão confirmada pelo responsável da turma ou admin/pastor; `lider_consol` pode criar turma e ver elegíveis (risco aceito).
- CD entre versões: conclusões de versão anterior valem na nova mediante equivalência da coordenação (implementado nesta fatia; produção não verificada).
- Enviar: avaliação exige UV, CD certificado e Reencontro como critérios distintos, com decisão humana final; aprova pastor/admin distinto do autor e do candidato; líderes atuais preservados como legado e revisados caso a caso; aprovar executa na hora com confirmação; evidência revogada barra novas nomeações e abre revisão, sem destituição automática.
- Tela Enviar: o líder não vê a avaliação (decisão/motivo) dos discípulos; vê só aptidão e pendências (opção padrão adotada; reversível).

## 5. No final: banco, latência, infraestrutura e release

| Entrega | Estado | O que falta |
|---|---|---|
| Banco Supabase e histórico de migrations | em andamento | Leitura somente leitura de 27/10 após reset externo: 129 migrations ativas no SHA `afdfb78d`, 78 no ledger, 51 pendentes (4 antigas + 47 novas), 0 desconhecidas e 0 pausadas aplicadas; 0 grupos duplicados e 0 vínculos de célula inválidos. As duas classificações antigas têm 0 candidatos neste instante. Decisão 23/10 de aplicar as quatro antigas preservada; cada aplicação continua sujeita à janela, backup e autorização. Contagens não provam igualdade integral do schema ou configurações; preflight integral e backup pós-reset ainda pendentes. Lista exata e condições no runbook do release; Neon cancelada. |
| Reconciliação da virada da agenda V2b | falta | Visibilidade/inventário de usuários, gates e entrega dos 11 eventos EVT-7: **não verificado**. Conciliar com provedor/logs antes de decidir qualquer reenvio, que pode duplicar. |
| Resposta rápida (B17), capacidade e estabilidade | falta | Meta abaixo de 10 s adiada para esta etapa; medir região de servidor/banco e decidir infraestrutura. Investigar incidentes e falhas de prontidão da API: monitor verde registrado não prova causa resolvida. |
| DEV online isolado | em andamento | Preparação integrada e ensaio sintético registrados (#468/#471); ambiente disponível **não verificado**, registrado como ainda inexistente. Faltam executor exclusivo, região, teto de custo, recursos e aceite de login/Storage/navegador com duas igrejas. Local continua opcional para depuração/testes. |
| Publicação coordenada de backend/frontend e recuperação | em andamento | Preparação e ensaio integrados (#472/#473; merge de #473 confirmado no Git). Checagens só leitura (#563, `61e84383`) e runbook com ensaio de restauração sintético (#565, `100463ba`) integrados; ensaios de parada, transição, topologia e retomada integrados (#574–#581, #586). [Runbook do lote](docs/ops/RELEASE-LOTE-2026-10.md) com o plano e a prévia de 27/10. Execução contra PROD: **não verificado**. Falta pacote validado, versão viva anterior, compatibilidade de banco, contenção dos consumidores, janela e autorização nominal. Não prometer rollback universal. |
| Publicação automática no DEV e explícita em PROD | falta | Operar o caminho preparado e acertar a publicação do frontend com a API (B9/B13). Não alterar agora a automação atual ou gates. |
| Backup diário e restauração | em andamento | PROD agora é a VPS `srv2031318.hstgr.cloud` (a `srv1728329` será desativada); runbooks atualizados (#545). Em 21/10, leitura somente: backup diário com manifesto recente e monitor de produção instalado e saudável na VPS nova. Faltam restaurar em alvo isolado, aceitar a chave do host novo no backup externo (Windows) e incluir novas tabelas privadas. |
| Revisão antes de ampliar o piloto ou lançar | falta | Conferir autenticação/Clerk Production, configurações, gates e privacidade; canários Asaas/Brevo/broadcast/agente independentes. Governança pausada não é reativada automaticamente. |

**Preservar para esta etapa:** pré-checagem de backup em
`vps07a-source-20261005`, guarda de rede em `vps04a-network-guard`,
`lock_timeout` em `elastic-kirch-0de4a3` e scripts de backup externo cifrado
(`deploy/offsite-encrypt-backup.sh` e `deploy/pull-offsite-backup.sh`). Os scripts,
a avaliação Jev de 26/09 e as evidências de 04/10 estão somente na referência
local `refs/archive/checkout-principal-20261016`, nos caminhos originais;
preservação conferida, integração e funcionamento **não verificados** nesta
entrega. Os demais candidatos continuam sem nova conferência de recuperação;
não são correções declaradas entregues.

Governança E4B/D3/D6/D2A, atestações, catálogos e F1/F2 de governança permanecem
pausados; reavaliação somente por necessidade e decisão próprias. Isso não
adianta banco/infra nem impede desenvolver UV/CD após a etapa 3.

## Evidências e manutenção

A consolidação usa os dois planos agora históricos
([MVP histórico](https://github.com/haniellevi/PastorAI-LionClaw-V1/blob/a812b9a6ef68b8757fda9e776e4f149cc2913722/docs/ops/MVP-PLANO-SIMPLIFICACAO.md) e
[refatoração histórica](https://github.com/haniellevi/PastorAI-LionClaw-V1/blob/a812b9a6ef68b8757fda9e776e4f149cc2913722/docs/ops/refatoracao-modular-plano.md)), os 22 itens do
[acompanhamento arquivado](https://github.com/haniellevi/PastorAI-LionClaw-V1/blob/a812b9a6ef68b8757fda9e776e4f149cc2913722/docs/ops/acompanhamento/tarefas.json), a [cobertura do PRD](docs/ai/PRD-COVERAGE.md) e o Git da base.
O [registro V2b](docs/sprints/2026-10-15-v2b-verificacao-pos-cutover.md) mantém
explícitos os limites da consulta anterior; ele não declara o banco consistente.
Na retomada de 24/10 houve só a leitura de produção registrada em "Evidência
operacional", sem escrita. Os documentos históricos são
evidência, não instruções para retomar suas sequências ou manter seu painel.

Daqui para frente, atualizar somente este roteiro quando o estado/escopo mudar
e registrar entrega, testes e limites na descrição da PR. Requisitos e runbooks
continuam sendo referências técnicas; sem novo sprint, painel ou plano paralelo.
O painel local solicitado em 24/10 (`output/painel/`) é só visualização gerada
deste roteiro, sem planejamento paralelo; após atualizar esta fonte, executar
`tools/render_progress.py` para regenerá-lo.
Integração exige `backend-tests`, `frontend-ci`, `e2e-critical` e
`rls-integration`; produção e efeitos reais exigem autorização nominal própria.
