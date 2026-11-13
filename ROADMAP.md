# Igreja 12 — roteiro único

## Decisões do dono de 12/11/2026 (registro)

O Plano Casa Limpa e as decisões de 13/11 (seção 7) regem a execução. Para a
virada, valem o alvo A, a autorização por bloco com o agente como operador,
o limite por migration, a recuperação por estado e os envios fechados ao fim.
As regras de produto deste registro seguem vigentes onde o plano não as altera.

**Ordem do trabalho:**

1. Arrumar a casa: documentação fiel ao estado real e triagem de branches.
2. Preparar e fazer a primeira publicação do que já está na `main`. Pela
   leitura de 27/10 (não reverificada) há 51 migrations pendentes em PROD;
   desde `afdfb78d` não entrou migration nova na `main`.
3. Logo após o deploy, desenvolver as lacunas do PRD, sem esperar o aceite
   pastoral das 20 conversas.

**Produção:**

- Cada ação em PROD exige autorização explícita do dono, uma por ação.
- Raniel é o operador nomeado da janela; janela em horário comercial.
- Envios pausados durante a janela e religados exatamente como estavam.
- Rollback imediato pré-autorizado se o smoke pós-deploy falhar.
- Primeira virada (12/11): um SIM único para o `run` inteiro, incluindo o
  ponto de não retorno; riscos aceitos por escrito: escrita direta no Supabase
  na janela, WhatsApp/cobranças chegando na janela e pausa do backup da VPS
  (runbook §12.4).
- Leitura técnica de produção (sem dados de pessoas) autorizada.
- A VPS de produção é compartilhada com outros sistemas do Raniel (olaki, sites-api, emcorr, GravAI, Fowler, hermes): a janela e os releases tocam só a Igreja 12 (runbook §12.0).
- Painel (frontend) novo vai ao ar na mesma janela, logo após a A10, com SIM
  próprio (SIM 5); passo e volta: runbook §12.5. SHA do painel: ver a linha
  da decisão de 12/11 abaixo.
- Antes de PROD, rodar o ensaio sintético existente; DEV online fica para depois.
- SHA da janela, decisão de 12/11 tomada pelo orquestrador com delegação do
  Raniel (opção A, sem repinar): backend em `afdfb78d` com o executor fixo
  `37c7d68d`; ferramenta e painel no SHA da `main`. O painel só vai ao ar se o
  contrato da API for igual ao de `afdfb78d`; se não for, o J8 não publica nada
  (runbook §12.5). Conferido em 12/11 com a `main` que já tem a #665: contrato
  idêntico. Kit da primeira virada: runbook §12.6. V8 feito; o primeiro
  `rehearse-backup` (V9) recusou no restore (extensão `supabase_vault` ausente
  na imagem oficial). Correção em PR; o V9 precisa ser refeito na VPS, com a
  ferramenta atualizada, e fechar com `seconds` abaixo de 60 antes do SIM 2.
- `statement_timeout` de 2 min na role do aplicador: não alterar a role. O
  caminho fixo da janela não repassa `PGOPTIONS` nem aceita `options` na URL;
  decisão em aberto com o orquestrador (runbook §12.6).
- O release seguinte (backend da `main`, com as correções feitas depois de
  `afdfb78d`) depende de o Raniel atualizar `BACKEND_DEPLOY_SAFE_BASE_SHA` e
  cadastrar os 4 secrets de acesso à VPS no environment `backend-production`.

**Escopo:** todo o PRD em código, com os gates fechados e o piloto Filadélfia
restrito à equipe interna. Abrir gate ou ampliar o piloto continua exigindo
decisão nominal própria.

**Itens antes pausados:** controlador A8/C2 e contenção de escritores,
governança E4B/D3/D6/D2A, atestações, catálogos e F1/F2 serão retomados e
concluídos depois da primeira publicação. Antes dela, só se antecipa o que for
exigido para o deploy ser seguro.

**Regras de produto decididas:**

- B3: a inbox fica visível só para os papéis fixos atuais; remover da
  configuração a opção de acesso customizado que a tela não honra.
- B4: envio humano pelo painel bloqueia contato com opt-out; visitante em
  reunião já passada é aceito no painel e recusado no WhatsApp.
- Decisão 21 (conhecimento oficial): feito (código, sem release). Dúvida sem
  resposta vai ao responsável vigente do setor `conhecimento_oficial`; sem
  responsável (ou sem acesso ao inbox) vai à fila do admin; escalar é a
  transferência humana.
- RF-26: gatilhos iniciais configuráveis e editáveis pelo admin: visitante
  novo a acompanhar, liderado em consolidação, relatório de célula pendente,
  prazo vencendo e meta atingida.
- Confirmadas (antes provisórias): sigilo de oração (só pastores leem; líder
  só com SIM da pessoa e enquanto durar o vínculo; admin e secretaria não
  leem); tela Enviar (líder vê só aptidão e pendências); conhecimento (admin
  elabora e publica; pastor revisa a própria área).
- B17: decidido levar o banco para São Paulo. Execução só após medição nova,
  plano com custo e tempo de parada e autorização própria, em janela separada
  da primeira publicação.

**Pendências abertas:**

- O termo "G2b" da agenda não está definido em nenhum arquivo do repositório
  (conferido em 12/11); investigar o significado antes de usar Google.
- EVT-7 segue a regra: conciliar com provedor/logs antes de decidir reenvio.

**Branches antigas:** triagem em modo leitura; o dono decide o que trazer para
a `main`. Nenhuma branch remota é apagada.

## Plano Casa Limpa — Igreja 12 (13/11/2026, versão 3.1)

Este plano substitui o "Plano de conclusão (proposto em 12/11/2026)", os
handoffs de 13/11 (`.dev/handoff/`) e os planos anteriores. O PRD
(funcionalidades que faltam) volta depois da Fase 9.

Versão 3: refeita depois de duas auditorias do Codex (`gpt-6.1-sol`, esforço
alto; versões 1 e 2 reprovadas), de uma conferência no código por 11 agentes e
das decisões do dono colhidas em 13/11 (seção 7). A mudança principal: a
produção vai para a `main` em **uma parada só**, e o segundo release, que
estava travado, sai do plano.

### 1. Objetivo e definição de pronto

No fim, cada item precisa estar provado com comando e saída, não declarado:

1. Todo trabalho válido desta pasta está na `main` do GitHub; o que não entrou
   está no cofre (item 6) e listado por nome na fila do `ROADMAP.md`.
2. A produção roda o backend e o painel do commit **A** da `main` (definido na
   tarefa 4.1), com as 130 migrations aplicadas, saudável, com os envios
   **fechados** por decisão do dono. Commits da `main` posteriores a A são
   aceitos só se não mudarem o que vai ao ar, provado por dois comandos vazios:
   `git diff --stat A origin/main -- backend/app backend/migrations backend/Dockerfile backend/.dockerignore backend/requirements.lock backend/scripts/migrate.py deploy/backend-release.sh deploy/check_backend_schema.py deploy/emit_schema_check.py deploy/schema_compatibility.py deploy/release_topology.py deploy/docker-compose.yml`
   e `git diff --stat A origin/main -- frontend`. Na prova final, conferir os
   contêineres ativos e o alias de produção da Vercel contra o recibo da virada.
3. No GitHub só existem a branch `main` e a tag `v1.0.0` (as `refs/pull/*` são
   do GitHub e não se apagam). No computador: só `main`, sem worktrees,
   stashes, tags de backup ou referências de arquivo.
4. A pasta local é um clone limpo da `main` mais uma lista curta e justificada
   de arquivos locais (tarefa 8.1).
5. O `ROADMAP.md` tem só as decisões vigentes, o registro curto deste plano e
   a fila do que vem depois.
6. Existe um cofre local testado, fora do repositório, com o bundle Git, os
   arquivos preservados e seus SHAs. O Drive recebe a parte liberada pela
   triagem. Antes da limpeza, o dono decide sobre uma segunda cópia integral
   e as entradas retidas na origem têm destino registrado (7.1 e 9.2).

### 2. Estado de partida

Lido em 13/11/2026. Números de Git são recontados na hora de cada fase; não
usar os números abaixo para apagar nada.

| Tema | Fato | Fonte |
|---|---|---|
| Uso do sistema | **ninguém usa hoje**; está em desenvolvimento; os dados do banco de produção são de teste e podem se perder; a configuração (login, igreja, WhatsApp, chaves) deve ser mantida | dono, 13/11 |
| Outros sistemas na VPS | **em uso real**; a regra de tocar só a Igreja 12 continua inteira | dono, 13/11 |
| Repositório | `haniellevi/PastorAI-LionClaw-V1`, **público**; "apagar branch ao mesclar" desligado; avisos de segurança desligados; a `main` exige PR, revisão, branch atualizada e 4 checks | `gh`, 13/11 |
| Exposição no repositório público | nenhuma senha, chave, e-mail, telefone ou CPF nos arquivos conferidos; a credencial do Maestri citada num commit de agosto **nunca foi ao GitHub** (só existe numa branch local) e o dono informou que já foi trocada ou não é mais usada | conferência por padrão, 13/11 |
| `main` no GitHub | `1e298817`; 4 checks verdes; nenhuma PR aberta | `gh`, 13/11 |
| Produção: saúde | `/health` e `/ready` ok | consulta pública, 13/11 |
| Produção: versão e banco | backend legado (registro `07a3f4d9`, de 24/10) e 78 migrations aplicadas (registro de 27/10); leitura viva: **não verificada** (tarefa 1.1) | ROADMAP |
| Migrations na `main` | 130 ativas e 5 pausadas; 52 pendentes em produção; a 130ª (`20261112_160000_celula_alerta_regras.sql`) altera a tabela `cell_alerts`, inclusive RLS e permissões | Git |
| Primeira virada (janela A1–A10) | **não executada**. Hoje a ferramenta está fixa no backend `afdfb78d` (129 migrations). O ensaio de 13/11 funcionou, mas o tempo **total** foi 99,4 s e a regra do runbook barra acima de 60 s | handoff de 13/11; runbook §12.6 |
| O que os 60 s medem | o tempo total (cópia do banco + restore + migrations), não o de cada migration. O corte real é o `statement_timeout` de 2 min da role, que o clone do ensaio **não reproduz**. Quanto dos 99,4 s foi cópia: não verificado (relato fala em cerca de 85 s) | código, 13/11 |
| Release normal pelo GitHub | nunca rodou; 0 secrets; e **não aceita** a migration 130: o verificador do release ativo recusa migration a mais, o do candidato recusa migration a menos e o pacote de compatibilidade recusa mudança em tabela que já existia | `deploy/backend-release.sh:582-590`, `deploy/check_backend_schema.py:200-217`, `deploy/schema_compatibility.py:99-165` |
| Backup depois da virada | a virada não cria `/opt/pastorai-current` nem o `.env` dele; o backup diário e o release normal dependem disso; o J9 do runbook só religa o cron, sem testar | `deploy/backup-production.sh:17-35`, runbook §12.2 |
| Painel | o que está no ar é do SHA `afdfb78d`; o contrato de API da `main` é diferente | Git, runbook |
| Trabalho pronto fora da `main` | 6 branches, 1 commit cada, já no GitHub, sem PR: inventário `23530956`, dependências `25c6c437`, botão Assistente `5529f7bd`, CSP que bloqueia `8d410766`, corrida de turma `0e039e67`, gatilho B15 `ef3a073f` | Git, `gh` |
| Referências locais | 229 branches, 24 tags, 2 stashes, 7 worktrees, 57 `refs/archive`, 17 `refs/codex`, `refs/preserve`, `refs/pr670`; 68 branches e 9 tags têm commit que não está em nenhuma referência remota (142 commits); 71 commits soltos, sem referência, o mais novo de 12/11 | Git, 13/11 |
| Branches remotas | 170 além da `main` | `gh`, 13/11 |
| Dentro de `.git` | restos que não são do Git: `local-test-envs` (136 MB), `cursor` (35 MB), `local-preservation`, `opencode`, 3 inventários `.txt` | leitura por nome, 13/11 |
| Fora desta pasta | nenhum outro clone; `~/.codex/worktrees` tem 34 pastas sem código | leitura, 13/11 |

### 3. Regras que valem em todas as fases

1. **Guardar antes de apagar.** Provar no cofre a recuperação do que for
   apagado definitivamente. Antes da limpeza do Git ou da pasta antiga,
   resolver a decisão da segunda cópia (7.1).
2. **Produção só com SIM do dono**, digitado na conversa da sessão que
   executa. O agente executa; o dono aprova **um bloco por vez**, com a lista
   de ações e o risco na frente (decisão de 13/11, válida para este plano). O
   passo sem volta (mudar o banco) tem um SIM só dele. Senhas e códigos de
   verificação ficam só com o dono.
3. **A VPS é compartilhada e os vizinhos estão em uso real:** tocar só a
   Igreja 12; foto dos outros sistemas antes e depois de cada bloco (runbook
   §12.0); qualquer diferença para tudo. Entre blocos consecutivos, a foto
   final de um serve de referência inicial para o seguinte.
4. **Uma PR por vez na `main`**: pequena, checks verdes, branch atualizada,
   merge com `gh pr merge N --merge --match-head-commit <sha>`.
5. **Revisão da Sarah** antes de integrar mudança de RLS/autenticação, antes
   de mudar o caminho que aplica migration em produção e antes de aplicar
   migration em produção. O mesmo GO pode cobrir a integração e a execução
   se identificar os SHAs, a role e o procedimento aprovados. Mudança
   relevante reabre a revisão.
6. **Sem código novo de produto.** Só entra o que já está feito, mais o que a
   publicação exigir (tarefa 4.2).
7. **Segredos** nunca entram em chat, documento, log ou commit. Arquivo de
   segredo só é copiado de um lugar para outro dentro da VPS, sem ser lido.
8. **Nunca editar migration.**
9. **Congelamento da `main`:** do merge da ferramenta (4.6) até o fim da
   virada (5.5), nenhuma outra PR entra. Se a base de T avançar antes do
   merge, refixar A e refazer as provas afetadas no novo candidato.
10. **Sem migration nova** na `main` até o release normal ganhar um caminho
    para mudança em tabela existente (fila, item 1).
11. **Cuidado enxuto** (decisão de 13/11): ficam 1 backup antes de mexer no
    banco, os 4 checks, a revisão de segurança e os envios fechados; saem
    cópias extras de backup, aviso à equipe, esperas fixas e fotos repetidas
    dentro do mesmo bloco. Segue-se no mesmo dia, com as provas verdes.
12. Registre a prova uma vez. O `ROADMAP.md` aponta para o recibo ou manifesto
    da fase. Depois da última PR (6.6), registre no manifesto datado do cofre.

### 4. Ordem, dependências e por quê

| Fase | Nome | Mexe em produção? | Depende de | Por que nesta posição |
|---|---|---|---|---|
| 0 | Cofre | não | — | sem cópia testada, erro de limpeza é perda definitiva |
| 1 | Leituras | leitura | — | troca registros antigos por fatos de hoje |
| 2 | Integrar na `main` | não | 0.1–0.6 | o que vai ao ar é a `main` |
| 3 | Enxugar o repositório | não | 2.1 | tira o peso morto; anda em paralelo e **pausa** no congelamento |
| 4 | Ferramenta da virada apontada para a `main` | não | 1, 2 | destrava a virada e elimina o segundo release |
| 5 | Virada (a única parada) | **sim** | 4 | leva banco, backend e painel para a `main` de uma vez |
| 6 | Depois da virada | **sim** (limpeza) | 5 | remove a ferramenta de uso único e os restos |
| 7 | Limpeza do Git | não | 6 | a última PR já entrou; nada mais cria branch |
| 8 | Pasta local nova | não | 7 | troca a pasta por um clone limpo |
| 9 | Prova final | leitura | 8 | fecha o plano e abre a fila |

Caminho crítico: prova local do cofre → 2 → 4 → 5, com as leituras da Fase 1
em paralelo. A Fase 3 não segura a virada: o que dela não
tiver entrado até o congelamento continua depois da Fase 5 (remover documento
não muda o que está no ar; a prova é o item 2 da seção 1).

Por que uma parada só (e não virada + release, como na versão 2): o release
normal recusa a migration 130 nos dois sentidos, e as saídas estudadas exigem
código novo e ensaio próprio. Apontar a virada direto para a `main` troca três
constantes e os testes da ferramenta, usa o caminho que já foi ensaiado e
deixa backend e painel no mesmo SHA. O custo: refazer o kit e o ensaio (V8 e
V9), que já teriam de ser refeitos por causa da regra de tempo.

### 5. Fases e tarefas

Colunas: **SIM** = precisa do "sim" do dono no chat; **Pronto quando** = a
prova. Quem executa é o agente, salvo quando a linha diz "dono".

#### Fase 0 — Cofre

Justificativa: 142 commits, os stashes, 71 commits soltos e arquivos úteis só
existem neste disco. O cofre testado é o que permite apagar depois.

| ID | Tarefa | SIM | Pronto quando |
|---|---|---|---|
| 0.1 | Criar referências locais para o que não tem nome: cada stash em `refs/backup-stash/N` e cada commit solto (`LC_ALL=C git fsck --unreachable --no-reflogs`) em `refs/backup-solto/<sha>`. Escrita local e reversível | não | contagem de referências criadas = stashes + commits soltos |
| 0.2 | Bundle: `git bundle create ~/workspace/_backups/igreja12/git-AAAAMMDD.bundle --all` | não | `git bundle verify` ok |
| 0.3 | Manifesto por nome, SHA e alvo simbólico de cada ref; registrar HEADs à parte. Listar commits fora das refs locais de acompanhamento de `origin` (`git rev-list --all --not --remotes=origin`) | não | refs e HEADs batem com `git bundle list-heads` |
| 0.4 | Importar o bundle em um bare temporário com `git fetch <bundle> '+refs/*:refs/*'`. Conferir os SHAs, recompor refs simbólicas e a ordem dos stashes pelo manifesto. Verificar o pack complementar se houver objetos preservados fora do bundle | não | 0 diferenças e `git fsck` sem erros; remover o bare após a triagem |
| 0.5 | Inventariar por nome e tamanho arquivos úteis fora do Git, checkouts órfãos sob a pasta a limpar e restos de `.git` (`local-test-envs`, `cursor`, `local-preservation`, `opencode`, inventários). Se houver alterações locais, preservar separadamente o que está no índice e o que está na pasta de trabalho. Copiar o material permitido com `SHA256SUMS`. Registrar os protegidos, como `.env` reais, chaves e `usuario-dev.md`, como retidos na origem, sem abrir nem copiar | não | `sha256sum -c` da cópia; entradas retidas listadas para 9.2 |
| 0.6 | Manter o bundle integral e o pack complementar em quarentena local. Para o ZIP, verificar nomes e conteúdo dos arquivos candidatos por padrões de credenciais e dados pessoais, sem registrar valores. Itens com correspondência ou sem triagem possível ficam locais. Qualquer artefato Git candidato a sair exige triagem de todo o seu histórico alcançável, inclusive mensagens e tags | não | manifesto dos itens liberados e dos retidos |
| 0.7 | Cópia no Google Drive: o agente gera um `.zip` da parte liberada pela 0.6 com `SHA256SUMS`; o dono sobe pelo navegador | dono | dono confirma; hash do zip anotado no manifesto |
| 0.8 | Logins de DEV em texto (`usuario-dev.md`): o dono passa para um gerenciador de senhas | dono | dono confirma; o arquivo sai na Fase 8 |
| 0.9 | GitHub: ligar os avisos de segurança, com correções automáticas desligadas. A ativação da exclusão automática fica para depois da 7.4, com autorização na lista desse bloco | **SIM** (muda ajuste do repositório) | avisos ligados |

**Prova local de 13/11/2026.** Em uma restauração independente, `git bundle verify`,
`git fsck --full` e a comparação por SHA confirmaram 576 referências, 7 HEADs,
33.339 objetos Git (incluindo o pack complementar) e a ordem dos 2 stashes.
`sha256sum -c` confirmou 5.238 arquivos copiados e os 9 textos extraídos do ZIP.
O manifesto está em `~/workspace/_backups/igreja12/20261113-fase0/manifesto/`.
O bundle integral ficou em quarentena local. A confirmação do ZIP no Drive,
a migração dos logins e os avisos no GitHub seguem pendentes. A decisão da
segunda cópia fica na 7.1. O inventário da 9.2 inclui as 146 entradas retidas.

#### Fase 1 — Leituras

Justificativa: a versão do backend, o estado do banco e o que sobrou do
ensaio na VPS são registros antigos ou não verificados.

| ID | Tarefa | SIM | Pronto quando |
|---|---|---|---|
| 1.1 | Acessos do agente: SSH da VPS com a chave do dono, Vercel CLI instalada e logada pelo dono (`vercel whoami`), `gh` como `haniellevi` | **SIM** (bloco de leitura) | os três respondem |
| 1.2 | Leitura da VPS, só metadados (runbook §12.0 e V1): sobras do ensaio, disco e memória, saúde e vizinhos, SHA do backend, nomes das migrations aplicadas e gates. Na sessão do aplicador, conferir role, permissões relevantes, `statement_timeout` e `lock_timeout`; identificar roles de runtime e proprietários dos objetos afetados. Conferir o alvo de `/opt/pastorai-current`, presença dos arquivos privados, cron do backup, configuração sanitizada do kit, nomes de variáveis de `.env.v2` e include do nginx | mesmo SIM | saída anotada sem segredos; substitui os registros de outubro |
| 1.3 | Conferir, só leitura, se os 22 achados do relatório de segurança de julho estão tratados na `main` | não | tabela achado → tratado / pendente; pendente grave vira PR na Fase 2; o resto vai para a fila |
| 1.4 | Lista nominal de prova das referências: para cada branch local e remota, tag e demais referências, uma das provas: (a) ponta ancestral da `main`; (b) `git cherry` sem commit próprio; (c) PR mesclada **com base `main`** e ponta igual ou ancestral do head da PR, ou árvore idêntica; senão (d) veredito da triagem (seção 6) | não | arquivo com uma linha por referência e nenhuma sem prova ou veredito |

#### Fase 2 — Integrar na `main`

Justificativa: o que vai para produção é a `main`. Tudo que está pronto
entra; o que não entra fica no cofre, listado.

Antes de abrir cada PR: atualizar a branch com a `main`. Se a `main` andar
depois: `gh pr update-branch N` e esperar os checks do novo head.

| ID | Tarefa | Branch | Risco | Pronto quando |
|---|---|---|---|---|
| 2.1 | Publicar o ROADMAP com este plano e as decisões vigentes de 13/11 (seção 7); manter o registro de 12/11 até a 3.4. Alinhar o `AGENTS.md` à D8 e às condições de exclusão da 7.4 | `docs/inventario-conclusao-20261112` | nenhum | PR mesclada |
| 2.2 | Corrida ao criar turma (`0e039e67`) | `fix/cd-turma-corrida` | baixo | PR mesclada com o teste de banco **executado** no CI |
| 2.3 | Gatilho de relatório B15 (`ef3a073f`) | `fix/b15-gatilho-relatorio` | baixo | idem, com o E2E executado |
| 2.4 | Botão Assistente (`5529f7bd`) | `feat/painel-assistente-rf47` | baixo | PR mesclada |
| 2.5 | CSP que bloqueia (`8d410766`) | `feat/csp-bloqueio` | médio: pode quebrar tela não coberta por teste; conferida na fumaça da 5.5 | PR mesclada |
| 2.6 | Configuração de dependências (`25c6c437`) com `open-pull-requests-limit: 0` nos 4 ecossistemas (hoje está 3), para o robô não criar branch | `chore/auditoria-deps-dev` | baixo | PR mesclada; `gh pr list` sem PR de robô |

Os scripts de backup externo e o documento da avaliação Jev **não** entram
(decisão D2): ficam no cofre e na fila.

#### Fase 3 — Enxugar o repositório (arquivos rastreados)

Justificativa: "só o necessário". Cada remoção vai por PR; os checks e a
busca de referências provam que nada dependia do que saiu. Não toca em
`backend/migrations`, `backend/scripts/migrate.py`, nos 12 arquivos do pacote
do backend (item 2 da seção 1) nem na ferramenta da virada (sai na Fase 6).

| ID | Tarefa | SIM | Pronto quando |
|---|---|---|---|
| 3.1 | Inventário de todas as pastas rastreadas fora do código (`docs/` por subpasta, `output/`, `tools/`, `supabase/`, scripts da raiz, `backend/scripts/`, `deploy/` de DEV), com veredito por item: MANTER (citado por `AGENTS.md`, `PRODUCT.md`, runbook, `PRD-COVERAGE.md`, CI, teste ou código) ou REMOVER, e para cada REMOVER quem o cita (`git grep` no repositório inteiro) | não | tabela entregue ao dono |
| 3.2 | Dono aprova a tabela | **SIM único**, com a tabela | aprovado |
| 3.3 | PRs de remoção por lote; cada uma remove os arquivos **e** ajusta quem os citava. Já decididos (D4 e D6): governança pausada (cerca de 41 scripts e `docs/governance`) e o pipeline de DEV suspenso (`dev-synthetic.yml`, variável `DEV_PIPELINE_ENABLED`, arquivos só de DEV em `deploy/`). Candidatos: `docs/sprints`, `docs/historico`, `docs/Docs20260704_*`, planos antigos, `QA-PLAN*`, `acompanhar.sh` e seu teste, `tools/render_progress.py`, `backend/scripts/apply_migrations.py`, `output/release/a3-final-local` | coberto pela 3.2 | por PR: checks verdes; `git grep` dos caminhos removidos = 0 fora de migrations; `new_migration.py` e `migrate.py` funcionando (teste) |
| 3.4 | `ROADMAP.md` enxuto, na PR que retira `docs/historico`: mostrar na tabela da 3.2 o que sai; ficam decisões vigentes, este plano e a fila da seção 8 | coberto pela 3.2 | PR mesclada; cada obrigação antiga aparece na fila ou tem decisão de abandono |

O dono aprovou a 3.2 somente para o lote documental da PR #679. Para essa PR,
a prova de migrations da 3.3 é o teste de `migrate.py`. O merge foi
autorizado após os quatro checks obrigatórios passarem. A retomada de
`new_migration.py` fica na fila da seção 8, item 6.

Para o lote dos planos QA da V2a (PR #680), o dono também aprovou a 3.2
só para essa retirada. A prova de migrations é o teste de `migrate.py`,
com a retomada de `new_migration.py` na fila da seção 8, item 6. O merge
está autorizado se os quatro checks obrigatórios passarem no SHA candidato.

#### Fase 4 — Ferramenta da virada apontada para a `main`

Justificativa: hoje a virada está travada pela regra de tempo e, mesmo
destravada, deixaria a produção 168 commits atrás, com um segundo release que
o verificador recusa. Esta fase resolve as duas coisas numa PR só.

| ID | Tarefa | SIM | Pronto quando |
|---|---|---|---|
| 4.1 | Fixar **A** na ponta da `main` após a Fase 2 e as PRs já integradas da Fase 3. Resolver os achados graves da 1.3 e conferir se o ledger da 1.2 corresponde à linha de base do candidato | não | SHA de A, 4 checks e `synthetic-release` verdes |
| 4.2 | Preparar a PR **T** sobre A com os ajustes abaixo | não | `git diff A T -- backend frontend` vazio; provas da 4.6 |
| 4.3 | Na T, documentar J9: registrar Compose efetivo, overrides, arquivo privado e dependências; configurar `/opt/pastorai-current` para A; apontar o backup para o arquivo privado efetivo, com modo 0600 e fora do layout verificado. Rodar uma vez o comando do cron manualmente antes de religá-lo | não para documentar; execução na 5.5 | runbook indica como provar um backup novo com `BACKUP_OK`, `sha256sum -c`, status "verified" e serviços de apoio despausados |
| 4.4 | Conferir variáveis obrigatórias de A contra os nomes da 1.2, migrations que mexem no timeout e contrato do painel antigo com a API de A. Registrar se a volta do painel é utilizável. Ensaiar o procedimento de fechar os envios da 5.2 com a mesma imagem e atualizar os vínculos se os IDs mudarem | não | resultado das conferências e procedimento no runbook |
| 4.5 | Sarah revisa RLS e autenticação desde o SHA observado na 1.2 até A, os grants e políticas de `cell_alerts` com as roles efetivas e o caminho de aplicação na T | não | GO por escrito nas condições da regra 5 |
| 4.6 | Antes do merge, rodar `test_first_transition_window_backup_docker` em ambiente sintético no SHA de T, com as 52 migrations e as medições. Registrar comando, SHA e saída. Mesclar com os 4 checks e o `synthetic-release` verdes; registrar o SHA integrado da ferramenta | não | recibo local do teste executado e checks verdes no candidato |

Ajustes da 4.2 na T:

- **(a)** Apontar o adaptador e o orquestrador para A, com 130 migrations
  totais, 78 de base e 52 pendentes (44 comuns e 8 concorrentes). Atualizar
  configuração e testes, incluindo o ensaio Docker da 4.6.
- **(b–c)** Medir cópia, restore e cada migration. Usar no clone uma role
  aplicadora com permissões relevantes equivalentes às da 1.2, separada da
  role de restore. Registrar o `statement_timeout` lido pela conexão que
  aplica as migrations e conferir RLS e grants com as roles de runtime.
- **(d)** Atualizar o runbook §12 e o manual para os passos das Fases 4 e 5.
  Aplicar o limite de 60 s por migration (D9), publicar o painel de A e manter
  envios fechados. Registrar a dispensa de aviso à equipe e de cópia externa
  do dump da janela.
- **(e–f)** Expor na linha de comando a consulta do estado e a retomada
  pré-marcador (`resume_legacy`) pelo mesmo diário. Ensaiar essas entradas
  e documentar o que fazer por estado pós-marcador, reaproveitando a retomada
  da A10. Ensaiar uma rota para falhas de DDL sem depender de repetir o
  `run`, com a prova de retorno do banco e do serviço se a rota escolhida
  for restore.
- **(g)** Antes de A9, comparar o catálogo vivo ao `final_schema_digest` do
  replay do backup da própria janela, vinculado ao marcador. Recusar
  divergências no escopo comparado e documentar se as exclusões previstas do
  restore afetam esse escopo. A A10 revalida o catálogo antes da liberação.
- **(h)** No V8, transferir e conferir os objetos Git de A e do executor
  integrado no repositório da VPS.

#### Fase 5 — Virada (a única parada)

Justificativa: leva o banco de 78 para 130 migrations e sobe backend e painel
de A. É o único passo com ponto sem volta. O sistema fica fora do ar por
cerca de 45 minutos (reservar 2 horas). Como ninguém usa e os dados são de
teste, a data é qualquer dia em que o dono disser.

| ID | Bloco | O que acontece | SIM | Pronto quando |
|---|---|---|---|---|
| 5.1 | Leitura | V1, V2, V3, V5, V7: aproveitar a 1.2 e atualizar estado, gates, IDs, ledger, deployment ativo da Vercel e foto dos vizinhos | **SIM 1** | saídas anotadas |
| 5.2 | Preparo e fechamento dos envios | V6: instalar o include do nginx se faltar, com backup, `nginx -t` e reload. Mostrar a fila por tipo e situação e fechar os envios pelo procedimento da 4.4. Conferir os gates e a imagem dos 4 processos. Em V8/V9, preparar o kit, validar banco e vínculos com os IDs resultantes e ensaiar. Fixar `restore_excluded_expected` pelo recibo e rodar `prepare` na configuração final. Repetir o replay se mudar algum insumo que afete a restauração | **SIM do bloco**, com o efeito sobre a fila | 52 aplicadas, ledger 130, maior migration de até 60 s, role e timeout conforme a 4.2; `plan_digest` e `window_digest` finais anotados; vizinhos iguais à foto |
| 5.3 | Abrir | J1–J2: conferir os digests e que os gates seguem fechados; abrir a janela e pausar só o backup da Igreja 12 | **SIM 2** | registro de início |
| 5.4 | Mudar o banco (**sem retorno automático**) | J3–J6 `run`: registrar gates, conter a aplicação, registrar a fila no J4, fazer o backup da janela, gravar o marcador, aplicar as 52 migrations e testar o backend de A com envios fechados | **SIM 3**, exclusivo | saída sem `refused`; `window_backup_id` anotado; `sha256sum` do `window.dump` igual a ele |
| 5.5 | Fechar | J7 (A10), J8 (painel de A pela Vercel; fumaça de leitura: login, Hoje, Conversas, `/gestao`, console sem violação de CSP), J9 (backup da 4.3, com leitura de Supabase/Storage, pull de imagens, pausa dos três serviços de apoio e escrita dos artefatos) e J10 (saúde, ledger, gates, contagem da fila e vizinhos) | **SIM 4 e 5**, dados juntos com a lista de efeitos | recibos anotados; fim do congelamento |

Se algo recusar, seguir o `recovery.state` no runbook §12. Antes do marcador,
retomar o legado com `resume_legacy` quando o estado permitir. Em
`a10-partial`, repetir a A10 com o mesmo diário e token para a ferramenta
conferir o resultado da etapa interrompida. Em falha de DDL ou contenção,
manter ou completar a contenção, diagnosticar ledger, catálogo e host e
decidir entre correção adiante e restore do `window.dump` com SIM próprio.
O restore exige avaliar escritas posteriores ao backup. Em falha do painel,
usar o deployment da 5.1 se a 4.4 confirmou compatibilidade, ou corrigir
adiante. Em falha do backup diário, confirmar os serviços despausados e
corrigir J9 antes de fechar a janela.

#### Fase 6 — Depois da virada

Justificativa: com a produção na `main` e conferida, saem a ferramenta de uso
único e os restos de versões antigas. Segue no mesmo dia, com a 5.5 verde.

| ID | Tarefa | SIM | Pronto quando |
|---|---|---|---|
| 6.1 | PR que remove a ferramenta da virada por inventário nominal (`deploy/first_transition*`, `rehearse_first_transition_*`, exemplo de configuração, testes), **mantendo** `initial_transition_files`, `initial_transition_ops`, `package_backend_release`, `migrate.py`, `release_preflight.py` e a seção **12.0** do runbook (usada por todo release). Na mesma PR: listas do `backend-tests.yml`, `test_production_runbook.py`, o resto do §12 vira registro curto, `BACKEND-RELEASE-MANUAL.md` ajustado | **SIM** | PR mesclada, checks verdes; os dois `git diff` do item 2 da seção 1 vazios |
| 6.2 | VPS, leitura: imagens, contêineres, releases, tarballs e arquivos do kit da Igreja 12 (`/var/lib/pastorai-first-transition`, `/opt/pastorai-releases`, instalação antiga em `/opt/pastorai-lionclaw`) | **SIM do bloco** | lista anotada |
| 6.3 | VPS: remover os itens aprovados na lista da 6.2. Preservar o release ativo, Compose e overrides efetivos, rede, volumes, serviços de apoio, os quatro IDs reservados exigidos pelo release, o último backup diário e o `window.dump` com kit e diário necessários à recuperação. Retirar o legado só quando a lista provar que ficou sem dependência | **SIM**, com a lista; vale o mesmo bloco se já cobrir a remoção | saúde, dependências do release e do backup conferidas; vizinhos iguais à foto |
| 6.4 | Vercel e Supabase, leitura: projetos, aliases e deployments da Igreja 12; existe projeto DEV antigo? | leitura; **SIM** para remover algo | anotado |
| 6.5 | GitHub: remover variável `DEV_PIPELINE_ENABLED`, environments sem uso (conferir quais são da Vercel), deploy key e caches sem uso | **SIM**, com a lista | checklist preenchida |
| 6.6 | **Última PR do plano**: registro de conclusão, fila da seção 8 e os critérios das fases 7 a 9 no ROADMAP. Depois dela nada mais é versionado por este plano | não | PR mesclada |

#### Fase 7 — Limpeza do Git

Justificativa: o objetivo final é só a `main`. Vem depois da última PR.

| ID | Tarefa | SIM | Pronto quando |
|---|---|---|---|
| 7.1 | Conferir a `main` remota e inventariar branches e tags por nome e SHA. Buscar as pontas que faltam e preservar o que mudou desde a Fase 0. Conferir a restauração dos acréscimos e atualizar o ZIP do Drive se a parte liberada mudou | dono decide sobre a segunda cópia integral antes da limpeza e confirma o ZIP no Drive | cofre final cobre as pontas a excluir; decisão registrada e segunda cópia conferida se adotada |
| 7.2 | Atualizar a lista da 1.4 contra a `main` final, reaproveitando as provas que continuam válidas | não | lista nominal sem pendência |
| 7.3 | Para cada worktree do projeto, confirmar a ponta no cofre, conferir arquivos úteis e verificar se há processo, chat ou contêiner usando. Arquivar as gerenciadas pelo Codex no app e remover as demais com `git worktree remove`, sem `--force` | **SIM**, com a lista | `git worktree list` mostra só o checkout principal |
| 7.4 | Apagar branches remotas diferentes de `main` e tags diferentes de `v1.0.0` somente com o SHA esperado da lista aprovada e do cofre testado. Conferir com `git ls-remote --heads` e `git ls-remote --tags --refs` e exigir o SHA esperado na exclusão. Pontas novas ou alteradas voltam à 7.1 | **SIM único**, com a lista e o ajuste da 0.9 se incluído | sobram `main` e `v1.0.0` |

A decisão sobre a segunda cópia integral segue pendente. Até lá, o material
em quarentena fica neste computador e o Drive recebe o ZIP liberado da 0.7.

As referências locais (branches, stashes, tags de backup, `refs/archive`,
`refs/codex`, `refs/backup-*`) não são apagadas uma a uma: saem com a pasta
antiga na Fase 8, já guardadas no cofre.

#### Fase 8 — Pasta local nova

Justificativa: a forma mais segura de ficar "só com o necessário" é começar
de um clone limpo, em vez de limpar a pasta atual por dentro. Evita coleta
agressiva de objetos e sobra escondida em `.git`.

| ID | Tarefa | SIM | Pronto quando |
|---|---|---|---|
| 8.1 | Lista do que **fica** fora do Git, item a item e com o motivo: `.env*` locais, `.vercel`, configurações locais do `.claude` e do editor. Dependências são reinstaladas | não | lista no manifesto do cofre |
| 8.2 | Com os aplicativos sem sessão ativa na pasta: mover a pasta inteira para `~/workspace/_lixeira/igreja12-pasta-antiga-AAAAMMDD/` e clonar a `main` no mesmo caminho. Reinstalar dependências (Python 3.13 e Node 24). Rodar `./test-local.sh` com ambiente sintético antes de recolocar os itens da 8.1 | **SIM** | SHA da `main` remota, teste local verde e só os ignorados previstos pela 8.1 |
| 8.3 | Arquivar no Codex áreas deste projeto que ficaram fora da lista da 7.3 | dono, se houver | áreas do projeto arquivadas |
| 8.4 | Conferir no clone as refs esperadas (`main`, acompanhamento de `origin/main` e `v1.0.0`), uma worktree, stashes vazios e `git fsck --full` sem erro. Reaproveitar a saída da 8.2 e os 4 checks do CI do commit final | não | saídas no manifesto |

#### Fase 9 — Prova final e encerramento

| ID | Tarefa | SIM | Pronto quando |
|---|---|---|---|
| 9.1 | Conferir os seis itens da seção 1. No manifesto final, referenciar os recibos já produzidos e coletar as verificações que dependem do estado atual | não | provas no manifesto |
| 9.2 | Apagar a lixeira deste plano após conferir no inventário a destinação dos itens que só ficaram na origem, incluindo arquivos protegidos e checkouts órfãos | **SIM**, com a lista | pasta removida e cofre preservado |
| 9.3 | Arquivar as sessões antigas do projeto nos aplicativos | **SIM** | feito |
| 9.4 | Entregar ao dono: o que ficou pronto, o que não foi feito e o primeiro item da fila | não | mensagem final |

### 6. Resultado da triagem de branches (13/11)

Todas as branches e referências sem prova de estar na `main` foram lidas por
conteúdo, e as 398 referências de branch passaram pelo script de prova.

**Conclusão: não há funcionalidade de produto pronta esperando para entrar,
e nenhuma parte do PRD ficou parada numa branch antiga.**

| Veredito | Quantos | O que são |
|---|---|---|
| Integradas, com prova por comando | 271 referências | ancestral (49), sem commit próprio (68), PR mesclada na `main` (147), árvore idêntica (7) |
| Integradas por squash, prova pela PR | 40 nomes | ponta anterior ao head de PR mesclada na `main` |
| Só no cofre (não entram na `main`) | 32 itens | trabalho pausado, planos e auditorias antigos, ferramentas locais, os 2 scripts de backup externo e o documento Jev |
| Descartadas (a `main` tem igual ou mais novo; ficam no cofre mesmo assim) | 51 itens | inclui 12 "parciais" (só o `ROADMAP.md` diferia) e 8 `*-offline` |
| Manter | 1 | tag `v1.0.0` |

Trabalho pausado ou inacabado, guardado no cofre e listado na fila (D-inacabados):

| Item | O que é |
|---|---|
| `codex/backend-performance-maintenance` (`07a3f4d9`) | registro do backend legado de produção (PR #455, mesclada numa base que não é a `main`); referência até o fim da Fase 6 |
| PR #619 (`origin/codex/igreja12-native49-local`, `9ce9a5d9`) | controlador de governança A8/C2; cerca de 25 mil linhas |
| `feat/whatsapp-canary-preparation-v1` | preparação de canário do WhatsApp; 52 arquivos |
| PR #431 (`ops/dev-espelho-prod-20260927`) | espelho DEV de PROD |
| `perf/pos-v1-2026-08-31` | melhoria de desempenho em permissão de célula |
| `origin/wip/antigravity-resgate-2026-07-06` | relatório de segurança de julho (tarefa 1.3) |
| `codex/maestri-persistence` | 19 commits só locais; registra o incidente da credencial |
| Demais | testes de backport antigo, ajustes de design, planos, auditorias, configurações de ferramentas |

Não verificado: rascunho `ds-adocao` linha a linha contra a #640; cada uma das
tags `backup/pre-merge-*` (entram na lista da 1.4).

### 7. Decisões do dono (13/11/2026)

| ID | Decisão | Resposta |
|---|---|---|
| D1 | Onde fica o cofre | cofre integral neste computador e ZIP da parte liberada no Google Drive, sem repositório de arquivo no GitHub. Decisão sobre segunda cópia integral pendente antes da limpeza (7.1) |
| D2 | Scripts de backup externo e documento Jev | ficam no cofre e na fila; não entram agora |
| D3 | Repositório público ou privado | manter público por agora (privado custaria cerca de 35 mil minutos de CI por mês contra 2 mil grátis; estimativa) |
| D4 | Governança pausada | sai do repositório; fica no cofre e na fila |
| D5 | Painel na virada | resolvido pela rota: publica o painel de A |
| D6 | Pipeline de DEV suspenso | sai do repositório |
| D7 | Fila de envios ao fechar os gates | aceitar, vendo a contagem antes |
| D8 | "No final, só a `main`" | confirmado: apagar branches depois de guardar; muda `AGENTS.md` e ROADMAP |
| D9 | Regra de tempo do ensaio | medir cada migration; barra se alguma passar de 60 s; o total não barra |
| D10 | Data da virada | qualquer momento, quando o dono disser |
| D11 | Quem opera | o agente executa, com SIM do dono por bloco |
| D12 | Trabalhos inacabados | cofre e fila |
| D13 | Dados de produção | de teste, podem se perder; a configuração é mantida (atualizar o banco atual, não zerar) |
| D14 | Nível de cuidado | enxuto (regra 11) |
| D15 | Esperas | seguir no mesmo dia, com as provas verdes |
| D16 | Envios depois da virada | fechados até o dono mandar religar |
| D17 | Rota | a mais segura, à escolha do agente: uma parada só, direto para a `main` |
| D18 | Credencial do Maestri | já trocada ou fora de uso |
| D19 | Avisos de segurança do GitHub | ligar só os avisos |

### 8. Fora do escopo e fila do que vem depois

Fora deste plano: funcionalidades do PRD, religar envios, ampliar o piloto e
DEV remoto.

Fila registrada no ROADMAP na última PR:

1. **Release normal pronto para uso** (necessário antes de publicar qualquer
   coisa nova): secrets e variáveis do GitHub, role de inventário, alvos
   aprovados e as demais pré-condições do `BACKEND-RELEASE-MANUAL.md`; caminho
   revisado e ensaiado para migration que altera tabela existente (o
   verificador de hoje só aceita tabela nova); `deploy/maintenance-profile.json`
   atualizado.
2. Lacunas do PRD (A1–A18 e T1–T10 do inventário de 12/11).
3. Religar envios e retomar o piloto, um efeito por vez, por decisão do dono.
4. Backup externo cifrado instalado e testado; novas tabelas privadas
   incluídas no backup.
5. Reduzir o CI para poder tornar o repositório privado.
6. Governança a retomar (A8/C2, E4B, D3, D6, D2A, atestações, catálogos, F1/F2)
   e os trabalhos pausados da seção 6. Retomar o gerador legado
   `new_migration.py` com revisão do contrato de autoria e reconciliação
   do catálogo. Na base da PR #679, faltam 58 SQLs e quatro hashes do
   prefixo histórico divergem.
7. Pausa de envios que preserva a fila (T5).
8. EVT-7 (conciliar antes de reenviar); "G2b" (termo sem definição).
9. Banco em São Paulo (B17): medição, plano e janela própria.
10. Aceite pastoral das 20 conversas.
11. Regra de produto para frases no futuro no gatilho de relatório (B15).
12. Sinal de "IA não configurada" para o botão Assistente.
13. Ligar as PRs automáticas de dependências (hoje com limite 0).
14. Achados pendentes do relatório de segurança de julho (1.3).

### 9. Registro da auditoria

- Codex `gpt-6.1-sol`, esforço alto, só leitura, 13/11: versão 1 **reprovada**
  (24 achados, 2 críticos); versão 2 **reprovada** (13 dos 24 resolvidos, 11
  parciais, 15 achados novos, 1 crítico).
- Conferência no código por 11 agentes em 13/11: 5 conferiram os achados da
  versão 2 e 3 desenharam rotas para a migration 130, cada uma atacada por um
  cético. Nenhuma rota foi derrubada; a rota de uma parada só foi a escolhida.

Como a versão 3 trata os achados da versão 2:

| Achado da versão 2 | Na versão 3 |
|---|---|
| 1 crítico: as duas rotas do release continuam travadas | o release normal sai do plano; a virada vai direto para a `main` (Fase 4); o caminho do release vira o item 1 da fila |
| 2: backup sem configuração depois da virada | tarefas 1.2, 4.3 e 5.5 |
| 3: "timeout explícito" mistura limites | tarefa 4.2 (b), (c) e (d); decisão D9 |
| 4: dump do ensaio não é o backup da janela | o backup da janela (`window.dump`) é o de recuperação e fica na VPS; cópia externa dispensada porque os dados são de teste (D13) |
| 5: pré-condições do manual do release | fora do plano; item 1 da fila |
| 6: comparação final incompleta | item 2 da seção 1, com a lista completa |
| 7: revisão de conteúdo antes de enviar para fora | tarefa 0.6; sem envio ao GitHub (D1) |
| 8: restos de `.git` e commits soltos | tarefas 0.1 e 0.5; sem coleta agressiva (Fase 8 usa clone novo) |
| 9: comando de inventário vazio | tarefa 0.3 |
| 10: falta `fetch` antes da limpeza | tarefa 7.1 |
| 11: seção 12.0 do runbook é operacional | tarefa 6.1 mantém a 12.0 |
| 12: robô de dependências | tarefa 2.6 (limite 0) e 0.9 (só avisos) |
| 13: dependência circular nas decisões | decisões tomadas em 13/11 (seção 7) |
| 14: provas depois da última PR | regra 12 e tarefa 9.1 (manifesto do cofre) |
| 15: prova de pasta igual a clone | Fase 8 (a pasta passa a ser o clone) |
| Parciais 13, 15, 20, 21, 23 | 8.3 (Codex arquiva), seção 2 ("registro"), 2.6, fila item 4, Fase 8 |

- Codex, rodada 3, sobre a versão 3: **reprovada**, mas com a rota confirmada
  ("a rota de uma parada só é viável"). 11 achados, todos incorporados na
  versão 3.1: fechamento dos envios antes da foto dos gates (4.4, 5.2);
  recuperação antes e depois do marcador (4.2 e, f); comparação do
  schema final com o do ensaio (4.2 g); teste real do backup com Docker (4.6);
  objetos Git de A na VPS (4.2 h, 5.2); dependências da instalação antiga
  (4.3, 6.3); triagem no repositório restaurado (0.6); comando do inventário
  (0.3); tags remotas (7.4); contagem de stashes (seção 2).
- Revisão da 3.1 por Codex e Claude Code, em leitura local do commit
  `5b048a87`. As correções de recuperação, ensaio, fechamento dos envios,
  backup e limpeza estão nas tarefas acima. A implementação e as provas da
  ferramenta ficam na T.

## Estado vigente da consolidação e do piloto (10/11/2026)

A consolidação está na `main` até `6088efb1`, com os seis workflows desse
commit aprovados.

| PR | Entrega |
|---|---|
| [#634](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/634) | Validação da rede A9 em candidatos nunca iniciados. |
| [#635](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/635) | Isolamento da configuração da fixture de consolidação. |
| [#636](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/636) | Roles necessárias à fixture de envio privado no PostgreSQL descartável. |
| [#637](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/637) | Diagnóstico sanitizado do alerta do PostgREST no runbook de produção. |
| [#638](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/638) | Correção da associação de campos no parser legado de relatórios. |

A [#619](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/619) foi
fechada como trabalho pausado. A branch foi preservada em `9ce9a5d9`. A9 e os
ajustes de fixtures entraram pelas #634 a #636. O controlador A8/C2 e a
contenção de escritores serão retomados após a primeira publicação (decisão de
12/11 acima).

A10 da primeira virada (12/11, [PR #659](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/659)): implementada em `deploy/first_transition_a10.py`
e ensaiada só em simulação. O `run` fotografa os gates dos quatro processos
antigos antes da contenção; `first_transition_window.py a10`, com SIM próprio,
recria os workers com esses valores, sobe o cron por último, abre as entradas
e verifica; falha contém sem voltar ao legado. Sequência completa da janela,
pontos de SIM e riscos a aceitar: seção 12 do
[runbook de produção](docs/ops/PRODUCTION-RUNBOOK.md). Nada executado em
produção. O controlador A8/C2 não é necessário para a janela.

Raniel confirmou o recorte V1a por texto e painel para a Filadélfia nos
[cenários 19 e 20](docs/ops/ACEITE-PASTORAL-PILOTO.md) e assumiu o aceite
pastoral. Ele fará pessoalmente os testes, somente após um deploy autorizado.
O aceite real dos cenários segue pendente.

Migrations de produção e deploy: em preparação para a primeira publicação,
cada ação com autorização própria do dono (decisões de 12/11). Ativação segue
suspensa. Não enviar as perguntas preparadas ao suporte do Supabase.

O mapa de escritores e os pedidos preparados ficam como histórico, nos
[registros de 24/10 a 06/11](docs/historico/ROADMAP-registros-ate-2026-11-06.md).
As instruções desta seção prevalecem sobre os próximos passos daqueles registros.

## Registros históricos

Os registros datados de 24/10 a 06/11/2026 (mapa de escritores, plano A7–A10,
A3 a A6, integração das #601, #602 e #606, pendências de 27/10 e evidências
operacionais) estão nos
[registros históricos](docs/historico/ROADMAP-registros-ate-2026-11-06.md).
Eles não determinam o estado atual: este roteiro prevalece. Outros documentos
antigos, como `SPEC.md` e `Plan-Designer-Igreja12/`, estão em
[docs/historico](docs/historico/README.md).

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
   deploy) quando estiver pronto; cada ação em PROD será apresentada a Raniel
   para autorização própria (decisões de 12/11).
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
  e depois integrados na `main` pela #597 (merge em 28/10, conferido no
  GitHub em 12/11);
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
`test/legacy-queue-entrypoint-20261024`, integrada pela #574 em 25/10
(`3f21b20a`).
Não inclui turno ativo, envio externo ou produção. Próxima prova: ingestão
ativa com barreira transacional em PostgreSQL sintético.
Ver [runbook atualizado e limites](docs/ops/RELEASE-LOTE-2026-10.md).

Em 25/10, a #574 (`94a4b9ec`) foi integrada na `main` (`3f21b20a`).
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
conhecimento e agenda pelo WhatsApp estão prontos só no passo 1. Ordem de 12/11:
primeiro o release em lote planejado (migrations acumuladas, backup,
reconciliação de duplicidades de vínculo Pessoa e ordem de aplicação); depois
dele, as lacunas do PRD, sem esperar o aceite das 20 conversas.

**Saúde técnica (metas medidas, uma fatia por PR, sem reescrita geral):**

| Meta | Medida em 22/10 (atualizada em 23/10) | Alvo |
|---|---|---|
| Tempo do `rls-integration` | 16–23 min serial em 22/10; 23/10: ~9–10 min com 4 partes paralelas (#550) e `backend-tests` ~4 min sem apt (#553), 0 skip | ≤ 8 min com divisão em partes paralelas, sem `skip` |
| Tempo do `backend-tests` | 11–16 min por execução na main em 10–11/11 (seis execuções), com limite de 20 min no job | ≤ 10 min com partes paralelas e instalação reaproveitada (PR 5 do plano de qualidade) |
| Verificação estática do backend | ruff com regras de erro no CI (#554); tipagem ainda não. Em 11/11: `# noqa: BLE001` sem efeito, porque a regra não está ativa | ruff ampliado só em código novo/alterado (fuso, erro escondido; PR 4); tipagem depois, por pasta (PR 9) |
| Arquivos de produção gigantes | `models.py` 5,0k, `queue_worker.py` 5,0k, `cell_report_audio_service.py` 4,1k, `routers/subscription.py` 3,7k, `notification_outbox.py` 3,5k, `agent/runtime.py` 2,3k linhas | arquivo tocado não cresce além de ~800 linhas; extrair uma responsabilidade coesa por PR quando a área for tocada |
| Camadas | acesso direto ao banco em 31/41 routers; inversões serviço→router eliminadas, com teste de camadas que cobre import relativo e alias (#555) | eliminar as 2 inversões; mover consulta para o serviço ao tocar a rota |
| Isolamento por igreja | helpers RLS novos e legados convivem | migrar um caminho por PR com teste PG de duas igrejas |
| Código pausado | ~5k linhas E4B/purpose consent no app | decidido em 11/11 (Raniel): arquivar em PR própria (PR 7 do plano de qualidade, #651); volta pelo histórico do Git |
| Migrations | 17 nomes legados | checar padrão só nos arquivos novos; não renomear histórico |
| E2E do painel | Playwright usa API simulada | um E2E sintético navegador → FastAPI de um fluxo crítico |

## 3. Próximas funcionalidades

| Entrega | Estado | Implementação / teste | Produção |
|---|---|---|---|
| Pedido de oração pelo WhatsApp (V4) | feito | Primeira versão de texto e pedido próprio integrada na main pela [PR #484](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/484), merge `2d408d92`; implementação e testes registrados. DESLIGADO por igreja e por trava de release; sem produção. Sigilo da coleta/histórico integrado pela #515; áudio protegido retido e excluído pela fila privada (#529) (backend/RLS, marcador, prévia e mídia; exclusão privada #509 e fila durável). Fatia 2 integrada pela #519: inbox mostra marcador acessível e orientação ao pastor, reconcilia a cada poll (texto e mídia protegidos somem no mesmo ciclo), mantém leitura autorizada pelo servidor, paginação/handoff/busca e mostra recibo de exclusão atualizável; sem backend/migration ou ativação. Regra de sigilo confirmada em 12/11 (só pastores; líder só com SIM da pessoa e enquanto durar o vínculo; admin/secretaria não leem); conferir o código contra ela ao tocar a área. Pendente: aceite pastoral (áudio já integrado pela #529). | não verificado em produção |
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
| Universidade da Vida | feito (código) | Integrada na main em 18/10 (#491–#494, #496): turmas, calendário de oito aulas + Encontro, responsáveis, matrícula explícita, chamada com reposição e correção com histórico, marcos Encontro/batismo, conclusão humana com aptidão à CD e WhatsApp do responsável **desligado** (`UV_WHATSAPP_APPROVED_RELEASE_ID=None`). Migrations `20261017_210500`, `_220000`, `_230000` validadas só em PostgreSQL local sintético. Corrida em 26/10: dois pedidos iguais de criação de turma ao mesmo tempo podiam gerar exceção não tratada na rota, comprovada em simulação (`unique(igreja_id,id)` fora do árbitro de `on conflict(id)`; HTTP de produção não testado). Corrigida pela #596 (`fix/uv-turma-race-20261026`, `on conflict do nothing`), integrada em 27/10 (merge `afdfb78d`, conferido no GitHub em 12/11), com teste PG real pela rota (24 pares por papel, admin e líder; vermelho no código antigo e verde com a correção); produção não verificada. `uv_matriculas` e `cd.create_turma`: padrões semelhantes a diagnosticar, não verificados. | Aplicação das migrations: **não verificado**; ativação não autorizada. |
| Capacitação Destino | feito (código) | Base integrada em 18/10 (#495, #497–#501): currículo versionado, turmas, matrícula, frequência/reposição, conclusão, progressão, equivalência e certificado revogável. Integrada em 19/10 (#511): equivalência entre versões da mesma família sem matrícula nova, origem rastreada, pré-requisitos/certificado e matrícula concluída fora do índice de andamento. CD não promove liderança; WhatsApp **desligado** (`CD_WHATSAPP_APPROVED_RELEASE_ID=None`). Migrations CD `20261018_010000`–`_040000` e `_090000` só em PostgreSQL local sintético. Corrida em 26/10 (falha RLS da main `87ba1e42`): criação idêntica concorrente de currículo podia dar 409, porque `on conflict(id)` só arbitrava a PK e `unique(igreja_id,id)` levantava violação. Corrigida pela #595, integrada em 27/10 (merge `7bc7fa72`; `on conflict do nothing`, releitura e 409 preservados), com teste PG real que sincroniza o INSERT (16 pares, vermelho no código antigo e verde com a correção); produção não verificada. `uv_turmas`: corrigida pela #596, integrada em 27/10 (`afdfb78d`). `cd_turmas` e `uv_matriculas`: padrões semelhantes a diagnosticar, não verificados. | Aplicação das migrations: **não verificado**; ativação não autorizada. |
| Enviar e multiplicação | feito (código) | Integrado em 19/10 (#502–#507, #510, #520): contrato de aptidão, avaliação humana com eventos imutáveis, nomeação de líder e abertura de célula por solicitação com aprovação web de pastor/admin distinto do autor/candidato, tela Enviar, evidências oficiais UV/CD/Reencontro (Reencontro validado/revogado/revalidado com histórico; revogação bloqueia novas operações, sem promoção/destituição automática) e WhatsApp **desligado** (`ENVIAR_WHATSAPP_APPROVED_RELEASE_ID=None`, lista por igreja vazia): consulta mínima de pendências/evidências e solicitações após SIM literal, com idempotência e recibo após commit; avaliação, validação e aprovação ficam no painel autenticado. Pré-requisito de release: usuários da coordenação vinculados a uma Pessoa ativa (`app_users.pessoa_id`). Ajustes P2 do WhatsApp integrados pela #521 (`c7166cd1`): roteamento restrito ao catálogo, confirmação objetiva e aviso de paginação. Migrations `20261018_050000`–`_080000` e `_100000` só em PostgreSQL sintético; aplicar UV/CD/Enviar antes do deploy do backend; `_080000` valida FK em `celula_solicitacao` e pode falhar com linha legada inconsistente. | Aplicação das migrations: **não verificado**; ativação não autorizada. |
| Memória privada durável | em andamento | Exclusão antes de memória nova. Integradas: fila durável de exclusão (#509), exclusão por pessoa e igreja/reset (#518), resumo privado por conversa (#526), retomada privada pelo comando exato "retomar conversa" (#531), pedido de exclusão com decisão web do admin (#535) e reset privado por pessoa no painel (#541). Contagens privadas agregadas no Hoje do admin (#546) e reset privado por igreja com confirmação pelo nome, SLA dos pedidos e quitação atômica dos pedidos pendentes cobertos pelo recibo (#561, migration nova, não aplicada). Tudo DESLIGADO (release None, lista vazia, flag false, teto 0). Integrada pela #582 (`1a5cb9c9`; checks do SHA `c37972d9` verdes antes do merge): 2xx do Storage após o prazo resolve a ownership do upload de áudio, sem transcrição; resultado desconhecido segue retido. Integrada pela #583 (`ae15449d`; checks do SHA `02335e89` verdes antes do merge; migration `20261030_100000` só em PG sintético, não aplicada em PROD): tarefas de limpeza e uploads de áudio usam só o login dedicado `private_storage_runtime` (NOBYPASSRLS, RLS por igreja, `search_path` fixo com `pg_temp` por último, sem fallback); sem ele novas entradas de áudio ficam pendentes sem download/upload/transcrição e a limpeza não roda (recibos pendentes); recuperação e reenvio de respostas seguem. Integrada pela #584 (`a5c1b06b`; checks do SHA `9ae8032a` verdes antes do merge; migration `20261030_110000` só em PG sintético, não aplicada em PROD): reconhecimento positivo PARCIAL de upload de áudio commitado cuja resposta se perdeu (token por tentativa commitado antes do POST em `x-metadata`, info do Storage estrito, CAS do token também no finish, liberação só com tarefa pendente); ausência/erro/tempo nunca liberam; abortado/em voo e legado seguem retidos; ensaio só contra storage-api `6dd28b4` local, hospedado não verificado. Integrada pela #585 (`5d4e735e`; checks do SHA `0190cd00` verdes antes do merge; migration `20261030_120000` só em PG sintético, não aplicada em PROD): a liberação da ownership de envio usa só o login dedicado `private_send_runtime` por função com chave e igreja; `authenticated` perde só o DELETE; INSERT/renovação seguem nas transações do domínio; a liberação não mascara mais retry/perda de claim. Sem o login, respostas seguem, mas a ownership fica retida (recibo `pendente_envio`, retentável não reenviado). Não protege contra dono/BYPASSRLS. Integrada pela #588 (`bd673afa`; checks do SHA `b2978c5b` verdes antes do merge; migration `20261030_140000` só em PG sintético, não aplicada em PROD): todo o ciclo de geração de resumos do cron (descoberta, claim, reserva, projeções e publicação) usa só o login dedicado `private_summary_runtime`, sem fallback; grants mínimos em quatro tabelas privadas, orçamento só por função de custo fixo, tabelas centrais só por seis projeções tipadas; orquestração, ordem de locks, HTTP sem sessão e revalidações inalteradas; `enqueue`, solicitante NULL e permissões antigas de `authenticated` intactos (login principal com BYPASS segue capaz: limite declarado). Sem o login, a geração não roda. Integrada pela #590 (`383115d1`; checks do SHA `8a59a796` verdes antes do merge; migration `20261030_160000` só em PG 17.6 sintético, não aplicada em PROD): modo explícito `QUEUE_WORKER_DATABASE_MODE` (`legacy` padrão, piloto inalterado; `dedicated` só com `QUEUE_WORKER_DATABASE_URL`, sem fallback) em que toda a fila normal (ingestão, turno, fences, retomada, CAS/ownership/renovação de envio e lease) roda no login `queue_worker_runtime` (NOBYPASSRLS, NOINHERIT, uma membership em `authenticated` sem ADMIN, papéis e estado da conexão provados a cada checkout/BEGIN; igreja descoberta só por função tipada); configuração Jev ilegível no turno privilegiado vira handoff de gate fechado. Não operacional: LOGIN não provisionado, modo do pooler/versão/memberships de PROD não verificados ([runbook](docs/ops/FILA-LOGIN-DEDICADO.md)). Pré-requisitos de ativação abertos: reconciliação de upload com resultado desconhecido (abortado/em voo/legado; versão, gateway e versionamento do Storage hospedado), identidade dos fences, do INSERT/renovação de envios e da retomada privada (só a geração de resumos foi isolada; tarefas, uploads, liberação de envios e geração de resumos integrados; fila normal integrada pela #590 em modo `dedicated` opcional, não operacional), provisionar os logins nominalmente e separar a URL por processo (API/queue/cron/broadcast compartilham o mesmo `env_file`), expiração de tombstones, dono/BYPASSRLS das funções no release (integrada pela #587 (`2c47c160`; checks do SHA `e9117752` verdes antes do merge): prova em PG sintético de que, com dono sem BYPASSRLS, liberação de envio, limpeza do Storage e exclusão falham fechadas, sem recibo verde nos cenários provados; o preflight somente leitura acusa dono sem SUPERUSER/BYPASSRLS nos contratos privados presentes (dez: cinco da #587, dois da #584 e três da #588, cujo corpo lê tabela com FORCE RLS; o resolvedor `queue_resolve_instance` da #590 lê só tabela sem FORCE e é exclusão explícita, válida se o dono da função for dono da tabela ou tiver BYPASSRLS, com os logins da aplicação sem BYPASSRLS; dez contratos + cinco exclusões = 15 definers `row_security=off` classificados) e lista como não verificados os ausentes; dono real em PROD e preflight pós-migration: não verificados). Ver [operação/limites](docs/ops/RESUMOS-PRIVADOS.md). | não verificado |
| Conhecimento oficial | em andamento | Base versionada e API editorial (#513/#514), busca autorizada (#516), painel editorial (#517), exclusão definitiva admin com confirmação (#524) e consulta pelo WhatsApp com fontes autorizadas (#525), DESLIGADA (`CONHECIMENTO_WHATSAPP_APPROVED_RELEASE_ID=None`, lista vazia), sem ingestão de conversas. Decisão 21 definida em 12/11 (dúvida sem resposta vai ao responsável do setor; admin recebe as sem responsável ou escaladas) e autoria confirmada (admin elabora e publica; pastor revisa a própria área); encaminhamento implementado sem release; falta o aceite pastoral. | não verificado |
| Ferramentas e especialistas por área | em andamento | Ampliar rotinas pelo WhatsApp usando os mesmos serviços do painel; comportamento global versionado, dados e execução por igreja, credencial OpenAI própria da igreja. | não verificado |
| Pessoas, responsabilidades, Minha Célula, Central e Hoje | em andamento | Integradas: pendências da Central em Hoje (#528), responsabilidade por setor com vigência (#530), pendências por responsabilidade vigente (#534) e gestão web de responsabilidades (#539). O aviso de contas da coordenação sem Pessoa ativa já foi entregue pela #557. Integrada pela #589 (`8a5dcada`; checks do SHA `868fecd1` verdes antes do merge): a baixa de alerta de célula passa a seguir a regra da leitura (pastor/admin ou líder direto, escopo do detalhe, `igreja_id` explícito); superior na cadeia deixa de baixar alerta que não vê. RF-26 implementado (#666): regras por igreja (`celula_alerta_regras`) com os cinco gatilhos decididos em 12/11, que o admin liga, desliga e ajusta em /gestao "Alertas ao líder"; o cron avalia o estado do banco e grava um alerta por fato (idempotente); o líder direto vê e trata em Hoje ("Alertas da sua célula") e no detalhe da célula. `cell_alerts` passou ao padrão endurecido (FORCE RLS, grants por coluna). Tudo **desligado**: lista `CELL_ALERT_ENABLED_IGREJA_IDS` vazia e regras desligadas por padrão; sem envio externo nem exposição ao agente do WhatsApp. Migration `20261112_160000` só em PG sintético. Antes de ativar: alertas de consolidação/prazo com Pessoa bloqueiam o arquivamento dela até serem tratados. | Cobertura completa: não verificado. |
| Triagem semântica Jev | em andamento | S1 implementada/testada com simulações; falta avaliar qualidade real, crise/humano e falsos opt-outs, contrato de tratamento de dados e autorização específica. Jev B/C/D continuam condicionados. | não verificado; não autoriza ativação. |
| Comunicados, assinatura/Asaas e e-mail/Brevo | em andamento | Bases implementadas; faltam aceite por finalidade, domínio/remetente e canários separados. Não envolver a igreja em cortesia em cobrança real. | não verificado |
| Onboarding da igreja, equipe, permissões e console | em andamento | Integradas: autorização de telas isolada por igreja (#536), reenvio de convite isolado (#538) e vínculo Pessoa ↔ usuário pelo admin, com auditoria e índice único (#543); ativação trava a igreja antes de Pessoa/usuário, eliminando a espera mútua com a gestão de equipe, com teste da corrida com convite que já traz Pessoa (#556). A tela de equipe sinaliza contas sem Pessoa vinculada (#557). Leitura após reset em 27/10: zero duplicidades de (igreja, pessoa). Correção nominal cancelada; revalidar ausência antes da migration da #543. | Cobertura completa: não verificado. |
| Exclusão da pessoa, exclusão da igreja e reset | em andamento | Fatias integradas: #509, #518, pedido da pessoa com decisão admin (#535) e reset privado por pessoa (#541). Reset privado preserva cadastros/opt-out/consentimento e não autoriza reset cadastral. A trilha de vínculo Pessoa (#543) guarda UUIDs após exclusão aprovada; contrato atual documentado (#594) no [runbook de exclusão](docs/ops/EXCLUSAO-PRIVADA.md#trilha-de-vínculo-pessoa-543-após-exclusão), sem anonimização nem purga; produção não verificada. Novos derivados acompanham sua implementação. | não verificado |
| UX, acessibilidade e desempenho do painel | em andamento | Integradas: teclado nas abas da Central (#527) e foco/anúncios/reflow no atendimento (#532). Faltam leitor de tela e celular reais, zoom e métricas autenticadas de campo. | Frontend publicado conforme registros; backend/telemetria e operação completa: não verificado. |
| Agenda completa e importação Google | em andamento | Operações locais pelo WhatsApp com SIM e recibo integradas (#540), desligadas. Lembretes pela outbox com gate próprio fechado (#547) e janela configurável por evento (2h/24h/72h/168h, públicos existentes, invalidação de pendentes; #560). Faltam G2b (termo sem definição em nenhum arquivo; investigar antes) e credencial Google isolada por igreja antes de usar Google. | não verificado |
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
- **feito (código, sem release):** B3 — a tela Conversas só existe para os
  papéis fixos da inbox (pastor, líderes G12/consolidação/célula, operador;
  admin implícito). Em #permissoes a opção some para os demais papéis; para os
  fixos o admin ainda pode remover. Nenhum papel ganha acesso; o assistente do
  painel segue a mesma regra.
- **feito (código, sem release):** B4 — o envio humano pelo painel (texto e
  mídia) usa a mesma checagem de opt-out global do agente e recusa com 409 e
  motivo visível ao atendente, antes de Storage/Evolution; a indicação de
  visitante para reunião passada é uma regra única por canal (aceita no painel,
  recusada no WhatsApp com orientação para usar o painel).
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
`integracao-incremental-20261013`. Integração desse material e estado dos
arquivos não salvos: **não verificado**.
A auditoria e os planos de outubro de `arquitetura-performance-seguranca-20261003`
ficam no snapshot histórico.

**Decisões pastorais aprovadas em 18/10 (Raniel):**

- CD: 6 módulos de 10 aulas; todas as aulas com reposição; sequência linear, exceção só pela coordenação (admin/pastor); certificado após módulos obrigatórios e confirmação da coordenação; CD não promove a líder.
- UV: conclusão confirmada pelo responsável da turma ou admin/pastor; `lider_consol` pode criar turma e ver elegíveis (risco aceito).
- CD entre versões: conclusões de versão anterior valem na nova mediante equivalência da coordenação (implementado nesta fatia; produção não verificada).
- Enviar: avaliação exige UV, CD certificado e Reencontro como critérios distintos, com decisão humana final; aprova pastor/admin distinto do autor e do candidato; líderes atuais preservados como legado e revisados caso a caso; aprovar executa na hora com confirmação; evidência revogada barra novas nomeações e abre revisão, sem destituição automática.
- Tela Enviar: o líder não vê a avaliação (decisão/motivo) dos discípulos; vê só aptidão e pendências (confirmada pelo dono em 12/11).

**Plano de qualidade de 11/11/2026 (análise do código por amostragem, aprovado por Raniel):**

Uma PR por vez, na ordem abaixo; cada uma começa e é commitada só com
autorização. Leitura por amostragem: sem testes, typecheck nem lint na análise.

| # | PR | Escopo | Estado |
|---|---|---|---|
| 1 | Erros do backend | "Hoje" pelo dia da igreja (`app.datas.hoje_da_igreja`) no desligamento de pessoa, no catálogo privilegiado do agente e no DPA do Jev; `igreja_id` explícito na troca de plano do worker de cobrança e nos telefones do SLA (defesa além da RLS); teto de páginas com falha nas listagens do Asaas e do Storage | feita (#645) |
| 2 | Erros do painel | limpar o store de consolidação no logout; erro explícito sem `NEXT_PUBLIC_API_URL` em produção; tirar o harness do build; conferir trava no backend de cada tela escondida por `isOwner` | feita (#646) |
| 3 | CSP | primeiro `Content-Security-Policy-Report-Only`, depois bloqueando. Cookie de sessão HttpOnly (hoje legível por script, em `.igreja12.com.br` e no `localStorage`) fica como item próprio, com revisão independente de autenticação | modo de teste feito (#647); scripts com nonce (#655); estilos separados (#657); falta bloquear |
| 4 | Verificação Python | ruff ampliado (fuso, `except` amplo, import sem uso) só em código novo ou alterado | feita (#648) |
| 5 | CI | `backend-tests` em partes paralelas; instalação reaproveitada entre workflows | feita (#649) |
| 6 | Documentos | `SPEC.md`, `SPEC_PROGRESS.md`, `Plan-Designer-Igreja12/`, `relatorio-shard3-rls.md` e o histórico deste roteiro para `docs/historico/` | feita (#650) |
| 7 | Arquivar E4B | retirar do app o código de consentimento E4B sem uso | feita (#651) |
| 8 | Tipos gerados | tipos do painel gerados do OpenAPI do backend | feita (#652) |
| 9 | Tipagem Python | checagem de tipos começando por poucas pastas | feita (#653) |
| 10 | Formatador | formatador no painel, por último | feita (#654) |

Ordem de integração: #648 antes da #649 (as duas mudam `backend-tests.yml`;
a #649 se ajusta depois); #654 por último, com a formatação refeita sobre a
`main` atualizada.

Regras que seguem: arquivos gigantes e os cinco pacotes `*_whatsapp`
duplicados só são divididos quando a área for tocada (metas da seção 2);
testes do painel que leem CSS como texto são trocados por testes do que a tela
mostra quando a tela for alterada, e não se criam novos. Fora do plano, sem
decisão: duplicação em `docs/` e pastas de configuração de agentes. Limpeza
local de ~19 GB em `.git/local-preservation/` segue em conferência própria,
item por item com aprovação. Conhecido e sem ação: resposta do agente pode
duplicar se a Evolution der timeout (sem chave de idempotência no provedor).

## 5. No final: banco, latência, infraestrutura e release

| Entrega | Estado | O que falta |
|---|---|---|
| Banco Supabase e histórico de migrations | em andamento | Leitura somente leitura de 27/10 após reset externo: 129 migrations ativas no SHA `afdfb78d`, 78 no ledger, 51 pendentes (4 antigas + 47 novas), 0 desconhecidas e 0 pausadas aplicadas; 0 grupos duplicados e 0 vínculos de célula inválidos. As duas classificações antigas têm 0 candidatos neste instante. Decisão 23/10 de aplicar as quatro antigas preservada; cada aplicação continua sujeita à janela, backup e autorização. Contagens não provam igualdade integral do schema ou configurações; preflight integral e backup pós-reset ainda pendentes. Lista exata e condições no runbook do release; Neon cancelada. |
| Reconciliação da virada da agenda V2b | falta | Visibilidade/inventário de usuários, gates e entrega dos 11 eventos EVT-7: **não verificado**. Conciliar com provedor/logs antes de decidir qualquer reenvio, que pode duplicar. |
| Resposta rápida (B17), capacidade e estabilidade | falta | Meta abaixo de 10 s adiada para esta etapa. Decidido em 12/11 levar o banco para São Paulo; executar só após medição nova, plano com custo e parada e autorização própria, em janela separada. Investigar incidentes e falhas de prontidão da API: monitor verde registrado não prova causa resolvida. |
| DEV online isolado | em andamento (depois da primeira publicação, decisão de 12/11) | Preparação integrada e ensaio sintético registrados (#468/#471); ambiente disponível **não verificado**, registrado como ainda inexistente. Faltam executor exclusivo, região, teto de custo, recursos e aceite de login/Storage/navegador com duas igrejas. Local continua opcional para depuração/testes. |
| Publicação coordenada de backend/frontend e recuperação | em andamento | Preparação e ensaio integrados (#472/#473; merge de #473 confirmado no Git). Checagens só leitura (#563, `61e84383`) e runbook com ensaio de restauração sintético (#565, `100463ba`) integrados; ensaios de parada, transição, topologia e retomada integrados (#574–#581, #586). [Runbook do lote](docs/ops/RELEASE-LOTE-2026-10.md) com o plano e a prévia de 27/10. Execução contra PROD: **não verificado**. Falta pacote validado, versão viva anterior, compatibilidade de banco, contenção dos consumidores, janela e autorização nominal. Não prometer rollback universal. |
| Publicação automática no DEV e explícita em PROD | falta | Operar o caminho preparado e acertar a publicação do frontend com a API (B9/B13). Não alterar agora a automação atual ou gates. |
| Backup diário e restauração | em andamento | PROD agora é a VPS `<vps-host>` (a `srv1728329` será desativada); runbooks atualizados (#545). Em 21/10, leitura somente: backup diário com manifesto recente e monitor de produção instalado e saudável na VPS nova. Faltam restaurar em alvo isolado, aceitar a chave do host novo no backup externo (Windows) e incluir novas tabelas privadas. |
| Revisão antes de ampliar o piloto ou lançar | falta | Conferir autenticação/Clerk Production, configurações, gates e privacidade; canários Asaas/Brevo/broadcast/agente independentes. Governança retomada após a primeira publicação (decisão de 12/11). |

**Recuperação dos snapshots de painel:** o histórico de Minha Célula pagina no
banco e lê em lote só a presença e as indicações do próprio membro. A matriz de
menus seleciona apenas papel e tela. O teste E2E de navegação registra mediana e
p75 de Hoje, Conversas e abertura do atendimento com API fictícia. Latência e
comportamento em produção **não verificados**.

**Preservar para esta etapa:** pré-checagem de backup em
`vps07a-source-20261005`, guarda de rede em `vps04a-network-guard`,
`lock_timeout` em `elastic-kirch-0de4a3` e scripts de backup externo cifrado
(`deploy/offsite-encrypt-backup.sh` e `deploy/pull-offsite-backup.sh`). Os scripts,
a avaliação Jev de 26/09 e as evidências de 04/10 estão somente na referência
local `refs/archive/checkout-principal-20261016`, nos caminhos originais;
preservação conferida. A rotina versionada reaproveita da VPS-07A a validação
do diretório e a criação exclusiva da execução. A instalação e o funcionamento
na VPS continuam **não verificados**. As demais propostas do candidato foram
preservadas para a etapa de infraestrutura.

Governança E4B/D3/D6/D2A, atestações, catálogos e F1/F2 de governança: o dono
decidiu em 12/11 retomar e concluir depois da primeira publicação; antes dela,
só o que for exigido para o deploy ser seguro.

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
