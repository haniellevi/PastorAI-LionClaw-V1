# Release em lote, outubro de 2026

Atualizado em 24/10/2026 sobre a `main` no commit `354a83d`.

Este runbook prepara a janela de release das migrations acumuladas e do
backend. Ele não autoriza nem executa acesso a PROD. Use também o
[runbook de produção](PRODUCTION-RUNBOOK.md), o
[runbook de backup](BACKUP-FIREWALL-RUNBOOK.md), o
[manual do release de backend](../../deploy/BACKEND-RELEASE-MANUAL.md) e o
[aplicador de migrations](../../backend/migrations/README.md).

## Estado e gates

O registro de 14/10 informa 78 migrations aplicadas e quatro pendentes:
`20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql`,
`20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql`,
`20260925_183811_preserve_platform_admins_on_tenant_deletion.sql` e
`20260926_120446_platform_jev_settings.sql`. Os quatro arquivos continuam ativos
em `migrate.py::migration_files()`. `deploy/backend-release.sh` monta o manifesto
com todas as migrations ativas, e `deploy/check_backend_schema.py` bloqueia o
release se qualquer nome esperado faltar em `public.schema_migrations`.

**Decisão do dono (Raniel, 23/10/2026, no chat): opção (1), aplicar as quatro.**
Elas ficam ativas no manifesto e são aplicadas na ordem lexical global. O deploy
só é autorizado quando todas as migrations ativas do SHA candidato estiverem
registradas no ledger do ambiente alvo. A decisão vale só para a escolha da
opção; não autoriza aplicar nada: cada migration em PROD continua exigindo
autorização nominal própria, backup verificado antes e SHA registrado.

Condições por migration, acordadas com o Codex em análise só de leitura:

| Migration | Condição antes de aplicar |
|---|---|
| `20260711_023515` (backfill de tipo "membro") | **Conferir antes.** Muda dados de pessoas reais e não tem reversão automática. O operador roda a consulta de candidatos da seção "Consultas de conferência" (somente `SELECT`), o dono vê quem mudaria (sem exportar telefone) e só então autoriza. Guardar id, igreja e tipo original fora do repositório para eventual reversão. |
| `20260711_152127` (número de atendimento deixa de ser "membro") | **Conferir antes.** Mesma regra: consulta com o final de 4 dígitos do telefone, e o dono confirma que o alvo é o número conectado, não uma pessoa. Guardar o tipo anterior. |
| `20260925_183811` (usuário de plataforma sem igreja) | Sem conferência de dados: não altera linhas. Necessária para a exclusão de igreja. Rollback exige tratar os `igreja_id` NULL. |
| `20260926_120446` (configuração da Jev) | Cria tabela vazia e fechada. A Jev continua desligada: aplicar não abre gate, não insere chave nem lista de igrejas; ativação segue sujeita a DPA e gates próprios. |

Se a conferência de uma das duas primeiras mostrar candidato inesperado, parar,
não aplicar e voltar ao dono. O Codex sugeriu excluir a quarta enquanto a Jev
estiver pausada; o dono decidiu aplicar, e a exclusão exigiria um SHA candidato
revisado à parte, com risco maior do que uma tabela vazia. Não inferir aplicação
pelo número 78.

As migrations com `OPERATIONAL_AUTHORIZATION=BLOCKED` continuam fora da
seleção de `migrate.py`; não remover o marcador nem aplicá-las neste release.
O preflight e o deploy precisam usar o SHA exato aprovado da `main` e o ledger
`public.schema_migrations` do banco correto. Pendências e gates lidos em
24/10: ver "Bloqueios concretos". Backup real: não verificado.

Manter fechados em todos os quatro serviços (`backend`, `queue-worker`,
`cron-worker` e `broadcast-worker`):

- `ALLOW_REAL_SENDS=false`;
- `ASAAS_BILLING_ENABLED=false`;
- `BREVO_SEND_MODE=off`;
- `BROADCAST_ASYNC_ENABLED=false`;
- `AgentConfig.ativo=false` para cada igreja incluída;
- Jev sem `TYPESAFE_API_KEY` e sem igrejas em
  `JEV_SHADOW_TRIAGE_IGREJA_IDS`.

Todos esses gates continuam desligados durante o lote. Não imprimir `.env`,
credenciais ou valores secretos. `stuck_flow` permanece desligado até existir
credencial dedicada. O script de deploy existente confere os quatro gates de
serviço; `AgentConfig.ativo` e Jev continuam sendo verificações independentes.
Executar qualquer etapa em PROD exige autorização nominal do dono. Nenhum
resultado local prova PROD.

Esses gates fechados são condição da janela futura. A leitura de 24/10 mostra
o piloto vivo com gates abertos (ver "Bloqueios concretos"); chegar à janela
exige contenção e autorizações próprias. Isso não é ordem para fechar gates
agora.

## Bloqueios concretos em PROD (leitura de 24/10/2026)

Leitura somente leitura autorizada pelo pedido da sessão; nenhum deploy,
migration ou restart foi executado. Sem PII, UUIDs, `.env` ou valores secretos.

1. **Migrations pendentes.** Comparação de nomes pelo CLI Supabase em
   transação somente leitura: 124 migrations ativas no SHA `354a83d`, 78
   registradas em `public.schema_migrations`, 46 pendentes (exatamente as 4
   antigas e as 42 do lote) e 0 entradas desconhecidas. A migration de logout
   `20261023_120000` está pendente e `public.auth_sessions` não existe.
2. **Duplicidade de vínculo Pessoa.** Consulta agregada equivalente aos dois
   checks de dados do preflight, em `REPEATABLE READ READ ONLY` com
   `bypassrls=true`: `invalid_cell_links=0` e
   `duplicate_user_person_groups=1`. Não é a execução integral de
   `release_preflight.py` e não retornou UUIDs nem PII. Bloqueia
   `20261025_100000_team_pessoa.sql` e o lote até reconciliar pelo fluxo
   administrativo autorizado (passo 3 da sequência), sem SQL de escrita
   automático, e repetir o preflight.
3. **Gates abertos no piloto vivo.** `docker inspect` com allowlist restrita
   aos quatro gates de serviço, sem ler `.env`:
   - `backend`, `queue-worker` e `cron-worker`: `ALLOW_REAL_SENDS=true`,
     `BREVO_SEND_MODE=live`, `BROADCAST_ASYNC_ENABLED=false`;
     `ASAAS_BILLING_ENABLED` ausente.
   - `broadcast-worker`: `ALLOW_REAL_SENDS=true` (entrada duplicada),
     `BROADCAST_ASYNC_ENABLED=false`; `BREVO_SEND_MODE` e
     `ASAAS_BILLING_ENABLED` ausentes.

   Ausência não prova `false`; defaults efetivos não verificados.
   `AgentConfig.ativo` e Jev: não verificados. Fechar gate não equivale a
   pausar fila e pode cancelar pendências; a contenção para a janela exige
   plano e autorização nominal próprios.
4. **Instalação sem rastreio de versão.** Backend e workers usam imagem criada
   em 02/10/2026 sem label de revisão; `/opt/pastorai-current` e
   `/opt/pastorai-releases` ausentes; instalação em `/opt/pastorai-lionclaw`,
   sem Git. O primeiro release por `deploy/backend-release.sh` exige uma
   transição inicial testada a partir desse estado. Não inventar SHA anterior
   nem contornar guardas do script; o plano de volta depende dessa transição.
   Ver "Transição inicial da instalação atual".

## Transição inicial da instalação atual

**Estado: PREPARAÇÃO, não pronta para execução.** Complementa a sequência
deste runbook; não autoriza nenhuma etapa nem é plano paralelo.

**Ponto de partida (leitura de 24/10).** Instalação em `/opt/pastorai-lionclaw`,
sem Git, sem `/opt/pastorai-releases` nem `/opt/pastorai-current`; imagem
`sha256:4a65f30e…b241` sem label de revisão, cujo ID coincide com o recibo de
manutenção de 02/10. Comparação somente leitura dentro do backend vivo com o
`candidate_manifest` de `maintenance-profile.json` (`app/*.py` e
`requirements.lock`, sem copiar conteúdo): 148 esperados, 148 iguais,
0 ausentes, 0 diferentes, 0 inseguros. Isso comprova a identidade desse
recorte com `07a3f4d`; não comprova a imagem inteira, a configuração nem os
workers. Brevo `live` foi confirmado pelo dono e é preservado.

**Requisitos antes de qualquer janela**, cada um com evidência revisada:

1. **Release ativo verificável.** `deploy/backend-release.sh` recusa executar
   sem `/opt/pastorai-releases`, sem `/opt/pastorai-current` resolvendo para
   `releases/<SHA de 40 caracteres>` com `deploy/`, configuração privada,
   `check_backend_schema.py` e manifesto de `migrate.py` daquele SHA e, na
   promoção por imagem, sem label de revisão igual ao SHA ativo. Chegar a esse
   estado exige procedimento revisado e ensaiado em ambiente sintético. Criar
   symlink, diretório ou label não prova o SHA anterior e não deve ser usado
   como prova.
2. **Base de recuperação.** O código ativo é o backport de manutenção
   `07a3f4d` (sobre `eb5a09b`), cujo contrato de 02/10 tinha 70 entradas no
   ledger; hoje há 78. Conciliar essa diferença antes de usar o contrato de
   manutenção como checker anterior. Release legado sem checker exige plano de
   recuperação revisado, sem copiar o checker candidato para a árvore antiga
   ([manual do release](../../deploy/BACKEND-RELEASE-MANUAL.md)).
3. **Identidade dos quatro serviços.** O recibo de 02/10 mantinha os workers na
   imagem legada; a leitura de 24/10 mostra os quatro na imagem da API.
   Registrar a identidade de cada serviço antes de definir o estado anterior.
4. **Gates e filas.** O script exige os quatro gates fechados em todos os
   processos antes do preflight; o piloto vivo está com envios abertos. Fechar
   `ALLOW_REAL_SENDS` cancela pendências de forma terminal. Antes da janela:
   inventário somente leitura das filas, decisão nominal de Raniel entre pausa
   que preserve fila (exige código e testes próprios) ou outra contenção, e
   plano de aviso/tratamento das pendências.
5. **Banco.** Backup verificado, reconciliação da duplicidade e preflight sem
   achados, conforme a sequência do release.

Leitura complementar de 24/10: Docker Compose 5.6.0 e `timeout` presentes;
backend, queue e cron têm labels Compose do projeto `pastorai`, mas broadcast
não tem labels de projeto/serviço. O procedimento deve identificar e conter
explicitamente cada consumidor; não presumir cobertura dos quatro por Compose.
Os dois backfills de julho retornaram 0 candidatos cada na consulta agregada
dos predicados completos, somente leitura. O único grupo duplicado tem igreja
e não envolve liderança ativa nesse instante. Revalidar esses fatos na janela;
nenhuma conta foi escolhida e nenhuma linha foi alterada.

**Recuperação**, escolhida antes da janela por decisão nominal de Raniel:

Ensaio local de 24/10: baseline operacional nominal de 78 seguido das 46
pendentes e reconstrução independente de 124 produzem catálogos idênticos.
A guarda aditiva recusa `previous schema contract changed`: há mudanças em
RLS, constraints, grants e função existentes, além de triggers, índices únicos
e FKs novos sobre relações antigas. O runner de `07a3f4d` também não seleciona
o mesmo conjunto das 78 entradas operacionais; contagem igual não prova
manifesto igual. Nenhuma migration pausada foi executada no ensaio.
Com dados fictícios, 10 verificações confirmaram recusa de duplicidades
ativo/revogado e ativo/ativo, atomicidade da falha, índice e isolamento da
auditoria; os dois backfills de julho tiveram 6 testes aprovados. A correção
dos vínculos nesses testes é exclusiva da fixture, não procedimento de PROD.

O painel atual não resolve a duplicidade no backend legado: a rota
`PUT /team/{usuario_id}/pessoa` não existe em `07a3f4d`; revogar mantém o
vínculo. A rota nova depende da auditoria criada pela própria migration que
recusa duplicados. O procedimento nominal foi integrado pela PR #572 (`830decc1`),
compartilhando as regras humanas, com auditoria atômica, testes e revisão
independente. A execução real continua pendente de escolha privada das contas,
backup, contenção e autorização nominal. Nenhuma conta pode ser escolhida automaticamente.

- **(A) Voltar à imagem atual depois das migrations:** só é alternativa se
  `deploy/schema_compatibility.py` comprovar, com catálogos reconstruídos das
  migrations nominais (nunca capturados do banco vivo e rotulados como
  esperados), que o schema resultante preserva o contrato do código ativo.
  Sem essa prova, não usar.
- **(B) Corrigir adiante com contenção:** manter os gates fechados, conter os
  processos afetados, preservar schema e evidências e preparar correção
  revisada; compensação de banco só com autorização própria.

Nenhuma das duas garante rollback universal: migrations não são desfeitas
automaticamente, cancelamentos de fila são terminais e a reversão das
migrations 1 e 2 depende do registro guardado fora do repositório.

## Autorizações nominais

Complemento de identidade (24/10): o ID completo da imagem viva coincide com
o [recibo sanitizado de manutenção de 02/10](../performance/2026-10-02-backend-maintenance-production.json),
associado ao candidato `07a3f4d9a4fe510cf83fd48d5deaa52dcfbb7e02`.
O header público atual informa `unknown`; não houve comparação integral de
arquivos nesta consulta. O perfil antigo de manutenção exige exatamente 70
migrations e não pode ser reutilizado automaticamente com as 78 atuais.
O recibo preservava workers legados e Brevo `off`; a imagem comum aos quatro
serviços e Brevo `live` em três são diferenças atuais. Raniel confirmou em
24/10 no chat que Brevo `live` está autorizado; preservar o estado atual.
A mudança das imagens dos workers ainda não foi esclarecida. Essa confirmação
não autoriza testes de envio, fechar gates, recuperar imagens ou alterar
configuração; a contenção para a janela continua exigindo procedimento próprio.

Cada ação de PROD exige autorização própria de Raniel, com ambiente, SHA,
escopo e operador registrados. A autorização para uma etapa não se estende à
seguinte.

| Etapa | Quem autoriza | Quem executa e registra |
|---|---|---|
| Gerar e validar backup | Raniel, dono | Operador nominal da janela, com acesso autorizado à VPS e ao projeto Supabase |
| Consultar estado e rodar preflight | Raniel, para uma leitura somente leitura no alvo identificado | Operador nominal, usando role com `BYPASSRLS` e sem imprimir a URL |
| Reconciliar um achado | Raniel e admin/pastor nominal da igreja afetada | Responsável autorizado pelo fluxo administrativo aprovado para aquele registro |
| Aplicar migrations | Raniel, para a lista exata aprovada e SHA | Operador nominal, uma migration por invocação de `migrate.py` |
| Deploy do backend | Raniel, para o SHA completo e janela | Operador nominal pelo workflow manual existente |
| Smoke pós-deploy | Raniel, para o SHA e janela | Operador nominal, somente com chamadas sem efeitos externos |
| Plano de volta | Raniel, para a volta ao SHA anterior | Operador nominal; script de release, sem rollback de schema |

Registrar autorizações e recibos fora deste repositório, sem PII ou segredos.
Este documento e o merge do código não são autorizações operacionais.

## Sequência do release

1. **Backup verificado antes de qualquer migration.** Com autorização nominal
   de Raniel, o operador executa
   o procedimento instalado `/usr/local/sbin/pastorai-backup.sh` conforme o
   runbook de backup. Confere que o manifesto sanitizado informa
   `status=verified`, que o SHA-256 do pacote confere e que o pacote contém o
   dump `supabase-prod-public.dump` e os demais itens previstos. Registra hora,
   nome do artefato e SHA-256, sem copiar o pacote ou conteúdo de PROD para este
   workspace. Se o pacote ou o checksum falhar, parar.
2. **Preflight inicial.** Na cópia exata do SHA aprovado, com acesso de banco
   fornecido pelo canal autorizado e nunca por argumento ou log, executar:

   ```bash
   python3 backend/scripts/release_preflight.py
   ```

   O comando lê `MIGRATION_DATABASE_URL` do ambiente seguro, inicia transação
   `REPEATABLE READ READ ONLY`, recusa role que não contorne RLS e executa
   somente `SELECT`. Guarda a saída sanitizada. As migrations são listadas em
   `migrate.py::migration_files()`; `APLICADA` e `PENDENTE` preservam a ordem
   lexical do aplicador. `sem_arquivo` conta entradas do ledger sem arquivo
   ativo. A base `20261014` limita a verificação das tabelas esperadas no
   backup; o preflight reporta todas as migrations ativas do aplicador.
   Qualquer achado de FK, duplicidade, tabela ausente ou entrada sem arquivo
   interrompe o lote até decisão humana nominal. Pendências só são aplicadas
   depois da decisão sobre as quatro antigas e sobre a lista nova. Exit `0`
   significa apenas ausência desses achados; não significa schema liberado,
   migrations concluídas ou release pronto. Exit `1` exige reconciliação; exit
   `2` indica que o preflight não conseguiu verificar o alvo. Para autorizar o
   deploy, nenhuma migration ativa do manifesto do SHA candidato pode faltar no
   ledger; aplique todas ou use a opção de exclusão em SHA revisado descrita em
   Estado e gates.
   A checagem da FK reproduz o par `(igreja_id, celula_id)` que será validado
   pela migration `20261018_080000`; a checagem de duplicidade usa
   `(igreja_id, pessoa_id)` não nulo, como o índice da #543.
3. **Reconciliação manual antes da #543.** Antes de aplicar
   `20261025_100000_team_pessoa.sql`, confirmar zero duplicidades da chave
   `(igreja_id, pessoa_id)`. Qualquer duplicidade de igreja/pessoa exige
   reconciliação manual pelo fluxo administrativo autorizado. O operador entrega
   ao dono e ao admin/pastor da igreja afetada somente contagens e UUIDs; não
   usar exclusão em lote, SQL de escrita, merge automático ou escolha do agente.
   Repetir o preflight depois da reconciliação. Só seguir com zero violações de
   FK e unicidade, zero tabela ausente e destino explícito para cada entrada
   `sem_arquivo` e migration pendente que afete o lote.
4. **Migrations por `migrate.py`.** Com a lista aprovada, conferir primeiro
   `python3 backend/scripts/migrate.py status`. Aplicar uma migration por vez,
   na ordem apresentada e com registro nominal da saída:

   ```bash
   python3 backend/scripts/migrate.py apply <arquivo.sql> --yes
   ```

   Para as migrations marcadas `CONCURRENTLY` na tabela abaixo e a migration
   anterior à base indicada após a tabela, usar as invocações exatas com
   `--no-transaction` listadas ali. Para as demais, manter a transação padrão.
   Não usar `apply_migrations.py`, SQL manual, wrappers catalog-bound,
   `--no-transaction` sem requisito explícito da migration, nem tentar fazer um
   teste passar abrindo gate. Antes da #543, repetir a checagem de duplicidades
   `(igreja_id, pessoa_id)`. Em erro, parar no primeiro arquivo e preservar o
   estado para decisão de Raniel. Depois da lista aprovada, repetir `status` e
   o preflight somente leitura. Nenhum item aprovado deve permanecer pendente;
   resolver nominalmente qualquer divergência antes do deploy. O segundo
   preflight verifica também se as tabelas criadas pelas migrations já
   registradas desde 15/10 existem em `public`, schema inteiro coberto pelo
   dump de backup.
5. **Deploy do backend.** Depois do banco e dos preflights, Raniel autoriza
   separadamente o SHA completo de 40 caracteres. O operador usa o workflow
   manual **Backend release** da `main`; ele chama
   `deploy/backend-release.sh` na VPS. Manter o mesmo SHA que foi aprovado e
   inspecionado. Não disparar workflow durante esta preparação.
6. **Smoke sem efeitos.** Com os gates acima fechados, conferir `/health` e
   `/ready` públicos e no loopback, `docker compose ps`, CORS e isolamento das
   portas 8000/8080, seguindo a seção 8 do runbook de produção. Usar somente
   GETs e conta de teste previamente aprovada. Não testar envio, cobrança,
   broadcast, recuperação que possa contatar usuário, WhatsApp nem Jev. Se
   saúde ou readiness falhar, seguir o plano de volta sem reabrir gates.
7. **Gates continuam fechados.** Conferir os quatro processos depois do
   restart, `AgentConfig.ativo=false` por igreja e Jev inativo. Registrar
   confirmação sem mostrar valores secretos. O smoke não autoriza ativação.
8. **Plano de volta.** Em falha, Raniel decide nominalmente a recuperação e o
   operador usa o rollback de código do `deploy/backend-release.sh`, que
   verifica a compatibilidade do SHA anterior antes de retomar os serviços.
   Migrations não são desfeitas automaticamente. Preservar banco, backup e
   evidências. Corrigir adiante ou preparar uma compensação de banco revisada
   sob autorização própria. Nunca restaurar dump por cima de PROD como
   rollback improvisado.

### Critérios de contenção — provas operacionais ainda pendentes

A contenção do legado precisa identificar explicitamente backend, queue,
cron e broadcast: este último não tem labels Compose na leitura de 24/10.
Parar somente workers não bloqueia escritas humanas nem webhooks na API.
Antes de autorizar uma janela, ensaiar com dados fictícios o bloqueio de
entrada, término gracioso dos quatro processos, ausência de novas escritas
após a parada e preservação de gates e pendências. Verificar também políticas
de reinício e supervisores; uma leitura isolada de `Running=false` não prova
contenção durável.

O ensaio deve recusar identidade trocada/ausente, registrar timeout sem
promover release nem retomar automaticamente, e incluir trabalho em curso
na fronteira do provedor simulado. Retomada pré-DDL e recuperação pós-DDL
são provas diferentes: a recusa de compatibilidade entre 78 e 124 migrations
continua impedindo prometer retorno automático ao legado. Pendências podem
expirar durante a janela; preservar filas não garante elegibilidade futura.

Leitura estática do Git `07a3f4d` (não confirma configuração viva): Evolution
aponta diretamente para `backend:8000/whatsapp/webhook`; bloquear só o proxy
externo não contém esse ingresso. Queue termina o item atual depois do sinal;
cron pode terminar o tick inteiro, incluindo etapas posteriores ao sinal;
broadcast cerca a próxima requisição, mas permite concluir a já iniciada.
Os quatro serviços declaram `restart: always`, sem prazo de parada explícito.
O ensaio precisa medir término real e tratamento do efeito ambíguo, não apenas
recebimento de SIGTERM. Configuração viva de supervisor e retry externo seguem
não verificados.

Consulta SSH somente leitura em 24/10 às 17:22 UTC confirmou nos quatro
containers vivos `restart=always`; `StopSignal` e `StopTimeout` não constam
explicitamente na configuração inspecionada. A consulta projetou somente
esses campos e nomes, sem ler variáveis de ambiente. Isso não comprova o
prazo efetivo de término nem ausência de outros supervisores. Nenhum serviço
foi parado ou reiniciado.

A segunda opinião independente do Claude Opus acrescentou três cenários ao
ensaio: provedor simulado que reenvia ou não webhooks recusados, reinício por
supervisor e envio concluído com commit ainda pendente. Não presumir retry de
provedor real nem reenvio seguro de efeito ambíguo. A retomada com gates
preservados pode drenar o acúmulo e também é um efeito externo a autorizar.
Testes de reboot/daemon devem existir apenas em infraestrutura sintética
isolada, nunca reiniciando o Docker do host compartilhado.

A recusa do checker de compatibilidade aditiva não prova que todo caminho do
legado falharia; prova que o retorno automático não está demonstrado e não
pode ser oferecido como recuperação garantida.

Esse é um requisito de preparação local, não uma autorização ou procedimento
executável em produção. Nenhum gate deve ser fechado para realizar o ensaio.

## Reconciliação excepcional de vínculo duplicado

**Estado: preparação.** Código e testes sintéticos; não executado em nenhum
ambiente real. Não autoriza a operação.

O backend ativo não tem a rota de desvincular, e a migration
`20261025_100000_team_pessoa.sql`, que cria a trilha `team_pessoa_eventos`, só
pode ser aplicada sem duplicidades. Para esse impasse,
`backend/scripts/reconcile_team_pessoa.py` desvincula **um** acesso escolhido
nominalmente e mantém o outro. Ele nunca escolhe sozinho.

**Escopo:** a leitura de 24/10 encontrou um único grupo duplicado, com duas
linhas no maior grupo e sem liderança ativa. A ferramenta trata exatamente esse
formato (duas contas) e recusa qualquer outro.

**Momento:** usar a ferramenta de um SHA fixado e revisado, **antes** de
aplicar as 46 migrations pendentes; os testes sintéticos rodam sobre o
baseline real de 78 migrations. Da reconciliação até a criação do índice único
por `20261025_100000`, manter contidos os writers que criam ou alteram vínculo
Pessoa (convites, ativação, gestão de equipe), não apenas durante a transação
da ferramenta. Repetir o preflight imediatamente antes da migration.

- **Prévia (padrão):** transação `REPEATABLE READ READ ONLY`; nada é travado
  nem alterado. Emite `CONFIRMACAO=DESVINCULAR:<sha256 do payload>`, código
  técnico sem UUIDs ou dados pessoais que muda com qualquer campo aprovado.
- **Aplicação (`--aplicar`):** exige igreja, pessoa esperada, conta a manter,
  conta a corrigir, admin ativo da igreja, operador ativo em
  `platform_admins` (pode ser o próprio admin, se tiver os dois papéis
  atuais), id de operação UUID, SHA exato de 40 caracteres e, na entrada
  padrão, a linha exata emitida pela prévia. Tudo é revalidado no servidor,
  sob trava, na ordem Igreja → Pessoa → acessos → papel `admin` →
  `platform_admins`. Revogação concorrente desses papéis faz a operação
  esperar e, se confirmada, recusar.
- **Recusa:** se o grupo atual não for exatamente as duas contas aprovadas
  (resolvido ou com mais linhas), se a conta a manter não for acesso ativo
  utilizável, se a pessoa liderar célula ativa, se a role não ignorar RLS, se
  faltar schema ou auditoria, ou se `lock_timeout` sair de 1–30000 ms. Só o
  vínculo muda: papéis não são sincronizados, e status, papéis, dono e
  número de admins são conferidos antes do commit.
- **Auditoria:** uma linha em `platform_audit_log` com UUIDs, operação, SHA e
  hash do payload, na mesma transação. Falha da auditoria desfaz tudo. Não
  cria tabelas.
- **Idempotência:** o mesmo id com o mesmo conteúdo retorna `JA_APLICADA`
  somente se admin e operador ainda estiverem autorizados; o mesmo id com
  outro conteúdo é recusado.
- **Saída:** só códigos, contagens e o código de confirmação. A conexão vem
  apenas de `TEAM_PESSOA_RECONCILE_DATABASE_URL`, aceita só URL `postgresql`,
  sem `.env` nem configuração da aplicação; erros de parser ou driver saem
  como código fixo, sem DSN. O script não integra o catálogo do agente.

**Autenticação:** o script não autentica pessoas. UUIDs informados não são
login; a ferramenta só confere que eles têm, agora, os papéis exigidos. Quem
executa responde pela sessão nominal autorizada (credencial de banco e acesso
ao host), registrada fora do repositório com nome, horário e SHA.

**Limite de concorrência:** as travas da Pessoa, dos acessos, do papel
`admin` e da allowlist bloqueiam quem altera esses registros durante a
transação (a FK também trava a Pessoa). `lock_timeout` (5 s por padrão, máximo
30 s) faz a operação desistir em vez de esperar; nesse caso nada muda.
Caminhos que alterem `app_users` sem travar Igreja ou Pessoa não são
serializados; a verificação posterior recusa divergências visíveis até ali.
Depois do commit, só a contenção de writers impede uma nova duplicidade.

A execução em PROD exige backup verificado, autorização nominal de Raniel e do
admin da igreja para as duas contas, operador nominal e SHA registrados.
Anexar a saída sanitizada da prévia ao registro nominal antes da aplicação;
o token vincula os argumentos, mas sozinho não prova que a prévia foi executada.

## Logout no servidor (migration 20261023_120000)

A migration `20261023_120000_auth_session_revocation.sql` precisa estar aplicada
antes do código novo. Os logins de igreja em `auth.py` e de plataforma em
`platform_admin.py` registram o `jti` na tabela; sem ela, esses logins falham.

Tokens antigos sem `jti` passam a receber `401` quando o backend novo entra.
Isso encerra as sessões de todos os usuários e admins da plataforma no deploy;
comunicar essa saída à equipe antes da janela.

A ordem é migration, backend e frontend. Aplicar a migration por
`backend/scripts/migrate.py`, depois publicar o backend e, por último, o
frontend que chama o logout no servidor. A execução em PROD exige backup
verificado e autorização nominal de Raniel para o SHA, ambiente e janela.

Se for necessário voltar, reverter backend e frontend ao SHA anterior. O SQL
mantém o rollback comentado; qualquer remoção do schema deve seguir o processo
de migration com autorização nominal. Sem o código novo, tokens emitidos pelo
backend novo continuam válidos no fluxo antigo até expirarem. Migration aplicada,
rollback de código e release são etapas distintas; não executar nenhuma etapa
em PROD com base apenas neste registro.

## Migrations do lote posteriores à base de 14/10

Conferi `backend/scripts/release_preflight.py`, integrado pela #563
(`61e84383`): `BASELINE_DATE=20261014` limita a
checagem de tabelas esperadas no backup, enquanto o relatório percorre
`migrate.py::migration_files()` e classifica cada arquivo como aplicada ou
pendente. Essa função exclui migrations pausadas e ordena os nomes
lexicalmente. A tabela contém as 42 migrations ativas posteriores à base no
checkout atual, na ordem de aplicação; não afirma que estejam aplicadas em
PROD. Cada rollback resume o comentário da migration e exige reversão de
callers, preservação de dados e migration compensatória aprovada via
`backend/scripts/migrate.py`; não executar SQL de rollback manualmente.

A main atual já integra #556, #558, #560, #561, #562 e #568. As #556, #558 e
#560 não adicionam migrations; #561 adiciona a migration de reset privado da
igreja ao fim da lista, #562 adiciona as seis migrations de métricas e índices
operacionais abaixo, e #568 adiciona a migration de logout no servidor. As origens de cada arquivo foram conferidas no histórico
Git.

A busca literal `grep -il 'concurrently' backend/migrations/*.sql` encontrou
`20260701_014654_evt6_google_event_dedup_index.sql`,
`20260808_011500_messages_outbound_provider_id_uidx.sql`,
`20261023_100001_ai_usage_tenant_created_idx.sql`,
`20261023_110001_notification_outbox_pending_created_idx.sql`,
`20261023_110002_notification_outbox_retry_created_idx.sql`,
`20261023_110003_notification_outbox_expired_lease_idx.sql`,
`20261023_110004_messages_pending_agent_created_idx.sql`,
`20261023_110005_work_queue_pending_created_idx.sql`,
`20261028_100001_private_erasure_requests_overview_idx.sql` e
`20261028_100002_private_resume_delivered_overview_idx.sql`. A migration
`20260701_014654` só cita `CONCURRENTLY` em comentário e executa `CREATE UNIQUE
INDEX` comum; as outras nove executam `CREATE INDEX CONCURRENTLY` ou
`CREATE UNIQUE INDEX CONCURRENTLY`. `20260808_011500` antecede a base de 14/10,
por isso não integra esta tabela, mas também exige `--no-transaction` se estiver
pendente. As oito posteriores à base estão identificadas nas linhas da tabela.

| Ordem | Origem | Migration e efeito | Rollback resumido |
|---:|---|---|---|
| 1 | #484 | `20261016_180000_prayer_requests.sql`: persiste propostas e pedidos próprios de oração com RLS. | Drenar respostas, preservar pedidos confirmados e autorização; manter gates fechados e remover schema só por compensação aprovada. |
| 2 | #487 | `20261017_180000_visit_events.sql`: registra evidências de visitas a células com auditoria. | Reverter callers, preservar evidências; remover tabela e funções por compensação aprovada. |
| 3 | #488 | `20261017_180100_consolidacao_atribuicoes_aceite.sql`: persiste convites e aceite explícito de atribuições. | Suspender writers, preservar histórico privado e restaurar a função de revisão V3 antes de remover schema. |
| 4 | #492 | `20261017_210500_uv_turmas.sql`: cria turmas, atividades, responsáveis e matrículas da UV. | Reverter callers, preservar registros de formação e remover as tabelas em compensação. |
| 5 | #493 | `20261017_220000_uv_presencas.sql`: cria presença atual e histórico imutável das aulas UV. | Reverter callers, preservar histórico e remover tabelas, triggers, funções e constraints em compensação. |
| 6 | #494 | `20261017_230000_uv_marcos_conclusao.sql`: registra marcos e conclusões UV e a origem da aptidão. | Reverter callers, preservar marcos e históricos; remover tabelas, triggers, funções, constraint e coluna em compensação. |
| 7 | #497 | `20261018_010000_cd_catalogo_turmas.sql`: cria currículo, módulos, aulas, turmas, calendário e responsáveis CD. | Reverter callers, preservar catálogo, calendário e responsáveis; remover tabelas em compensação. |
| 8 | #498 | `20261018_020000_cd_matriculas.sql`: cria matrículas CD e snapshots de eventos de estado. | Reverter callers, preservar matrículas e eventos; remover dependências em compensação. |
| 9 | #499 | `20261018_030000_cd_presencas.sql`: cria frequência CD atual e histórico imutável. | Reverter callers, preservar histórico e remover tabelas, triggers, funções e constraints em compensação. |
| 10 | #500 | `20261018_040000_cd_conclusoes_certificados.sql`: registra conclusões, certificados e revogações CD. | Reverter callers, preservar conclusões e certificados; remover triggers, funções e tabelas em compensação. |
| 11 | #503 | `20261018_050000_enviar_avaliacoes.sql`: persiste avaliações humanas e eventos privados de aptidão. | Restaurar callers, preservar decisões e eventos; remover objetos em compensação. |
| 12 | #504 | `20261018_060000_enviar_nomeacao.sql`: adiciona solicitação versionada de nomeação de líder. | Restaurar callers e preservar histórico; reverter constraints e índices em compensação. |
| 13 | #505 | `20261018_070000_enviar_abertura.sql`: permite solicitação de abertura sem origem, sem backfill. | Restaurar callers, preservar solicitações e eventos; nunca apagar histórico nem rebaixar líderes. |
| 14 | #505 | `20261018_080000_enviar_reforcos.sql`: valida a FK de célula e reforça isolamento da solicitação. | Manter a FK validada; só restaurar estado anterior da validação por compensação aprovada. |
| 15 | #509 | `20261018_090000_exclusao_privada.sql`: cria exclusão privada durável de conversa e derivados. | Conter consumidores, drenar tarefas e preservar recibos; conteúdo apagado não é restaurável. |
| 16 | #510 | `20261018_100000_enviar_reencontro.sql`: registra evidência de Reencontro como marco oficial. | Reverter callers, preservar marcos e revogações; reconciliar duplicidades antes de reverter constraints. |
| 17 | #511 | `20261018_110000_cd_equivalencias_versoes.sql`: registra equivalências entre versões de currículo CD. | Reverter callers, preservar evidências e vínculos de certificados; remover view, tabelas e função em compensação. |
| 18 | #515 | `20261018_120000_prayer_message_privacy.sql`: restringe leitura do histórico de oração por igreja e papel. | Reverter consulta do backend junto com o schema, preservar recibos/tarefas #509 e manter gates fechados. |
| 19 | #513 | `20261018_130000_conhecimento_oficial.sql`: cria documentos, versões e operações de conhecimento oficial. | Parar callers e preservar documentos; não remover schema se houver documentos ou operações. |
| 20 | #516 | `20261018_140000_conhecimento_trechos.sql`: cria trechos transacionais e busca lexical autorizada. | Parar callers, preservar snapshots e citações; remover dependências em compensação. |
| 21 | #518 | `20261019_090001_exclusao_privada_pessoa_igreja.sql`: adiciona exclusão privada por pessoa ou igreja com recibos. | Conter consumidores, preservar recibos/barreiras e restaurar a função de #515 antes de compensar; conteúdo apagado não é restaurável. |
| 22 | #524 | `20261019_110001_conhecimento_exclusao.sql`: registra exclusão definitiva de documentos e citações oficiais vinculadas. | Parar callers e preservar auditoria; conteúdo apagado não é restaurável nem deve ser recriado. |
| 23 | #526 | `20261019_120001_private_conversation_summaries.sql`: cria resumos privados operacionais sem consumidor ativo. | Parar e drenar workers, preservar recibos e restaurar a função de exclusão anterior antes de remover schema. |
| 24 | #529 | `20261020_100000_prayer_audio_privacy.sql`: restringe áudio de oração ao pastor, inclusive compartilhamentos legados. | Restaurar políticas/funções só após aprovação pastoral; preservar associações e tarefas privadas. |
| 25 | #531 | `20261020_200000_private_resume.sql`: habilita retomada explícita de resumo, desligada por padrão. | Conter consumidores e restaurar a função anterior de invalidação; manter retomada desligada. |
| 26 | #530 | `20261021_100000_responsabilidades_setor.sql`: registra responsabilidades por setor e vigência sem conceder acesso. | Restaurar callers e preservar histórico; remover tabela e função em compensação aprovada. |
| 27 | #535 | `20261022_100000_private_erasure_requests.sql`: registra pedidos de exclusão privada e decisões do admin. | Parar consumidores e preservar pedidos, decisões e recibos; não compensar enquanto houver pedido pendente. |
| 28 | #544 | `20261023_100000_ai_usage_force_rls.sql`: força RLS na tabela de logs de uso, mantendo a política existente. | Restaurar apenas o comportamento anterior de FORCE RLS; manter RLS habilitada e a política. |
| 29 | #544 | `20261023_100001_ai_usage_tenant_created_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa logs de uso por igreja e data. | Conferir validade e remover índice com `DROP INDEX CONCURRENTLY` em migration compensatória. |
| 30 | #562 | `20261023_110000_operations_outbox_pending_metrics_fn.sql`: agrega métricas pendentes por igreja para admin ativo. | Remover a função por compensação após conter callers; a remoção também elimina seu ACL. |
| 31 | #562 | `20261023_110001_notification_outbox_pending_created_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa itens pendentes da outbox por igreja e criação. | Conferir validade e remover índice concorrentemente por compensação. |
| 32 | #562 | `20261023_110002_notification_outbox_retry_created_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa itens de retry da outbox por igreja e criação. | Conferir validade e remover índice concorrentemente por compensação. |
| 33 | #562 | `20261023_110003_notification_outbox_expired_lease_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa leases expirados da outbox por igreja e claim. | Conferir validade e remover índice concorrentemente por compensação. |
| 34 | #562 | `20261023_110004_messages_pending_agent_created_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa intenções de saída da IA por igreja e criação. | Conferir validade e remover índice concorrentemente por compensação. |
| 35 | #562 | `20261023_110005_work_queue_pending_created_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa itens acionáveis da fila por igreja e criação. | Conferir validade e remover índice concorrentemente por compensação. |
| 36 | #568 | `20261023_120000_auth_session_revocation.sql`: registra o `jti` das sessões próprias (sem guardar o JWT) para logout no servidor e revogação, com RLS forçada. Precisa estar aplicada antes do backend novo. | Reverter backend e frontend ao SHA anterior antes; remover as quatro políticas e a tabela `auth_sessions` só por compensação aprovada, o que descarta registros de sessão e revogação. |
| 37 | #543 | `20261025_100000_team_pessoa.sql`: aplica unicidade de Pessoa por igreja e cria auditoria técnica. Exige reconciliação manual prévia de duplicidades `(igreja_id, pessoa_id)`. | Reverter callers e preservar auditoria; remover índice e tabela somente por compensação aprovada. |
| 38 | #541 | `20261027_100000_reset_settles_erasure_requests.sql`: faz reset manual de pessoa cumprir pedidos privados pendentes. | Parar consumidores, preservar pedidos/recibos e restaurar wrapper anterior; não reabrir pedidos cumpridos. |
| 39 | #546 | `20261028_100000_private_memory_overview.sql`: expõe contagens administrativas sem conteúdo ou ação automática. | Remover a função por compensação; não há dados apagados e RLS/grants existentes permanecem. |
| 40 | #546 | `20261028_100001_private_erasure_requests_overview_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa inventário de pedidos por igreja, estado e idade. | Conferir validade e remover índice concorrentemente por compensação. |
| 41 | #546 | `20261028_100002_private_resume_delivered_overview_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa retomadas privadas entregues por igreja. | Conferir validade e remover índice concorrentemente por compensação. |
| 42 | #561 | `20261029_100000_reset_settles_church_erasure_requests.sql`: faz reset privado da igreja cumprir os pedidos cobertos pelo recibo. | Parar consumidores, preservar pedidos/recibos e restaurar wrapper #541; não reabrir pedidos cumpridos. |

As invocações abaixo usam a ordem lexical entre as migrations concorrentes. Cada
uma deve ser aplicada somente quando alcançar sua posição na ordem global
mostrada por `migrate.py status`, depois dos prechecks descritos no próprio
arquivo:

```bash
python3 backend/scripts/migrate.py apply 20260808_011500_messages_outbound_provider_id_uidx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_100001_ai_usage_tenant_created_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_110001_notification_outbox_pending_created_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_110002_notification_outbox_retry_created_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_110003_notification_outbox_expired_lease_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_110004_messages_pending_agent_created_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_110005_work_queue_pending_created_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261028_100001_private_erasure_requests_overview_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261028_100002_private_resume_delivered_overview_idx.sql --yes --no-transaction
```

## Consultas de conferência das migrations 1 e 2 (somente leitura)

Rodar no banco correto, com autorização nominal, dentro de `BEGIN READ ONLY; ...
ROLLBACK;`, e **antes** de aplicar `20260711_023515` e `20260711_152127`. O
resultado mostra nomes e identificadores: ver só na sessão do operador e do dono;
não copiar para chat, issue, log de CI nem documento. Nenhuma consulta mostra o
telefone completo (a segunda mostra só o final de 4 dígitos).

Para poder reverter, o operador guarda **fora do repositório** apenas
`id`, `igreja_id` e o tipo atual (`atual`) de cada linha listada, em local
autorizado, antes de aplicar. Se aparecer linha inesperada, parar e voltar ao dono.

```sql
-- Migration 1: pessoas com vínculo ativo na mesma igreja que passariam a "membro"
SELECT p.id, p.igreja_id, p.nome, p.tipo AS atual, 'membro' AS proposto
FROM public.pessoas p
WHERE (p.tipo IS NULL OR p.tipo::text IN ('contato','visitante'))
  AND EXISTS (SELECT 1 FROM public.celula_membro cm
              WHERE cm.pessoa_id = p.id AND cm.igreja_id = p.igreja_id AND cm.ativo IS TRUE)
ORDER BY p.igreja_id, p.nome, p.id;

-- Migration 2: registro cujo telefone canônico coincide com o número conectado
-- da mesma igreja, sem vínculo ativo, hoje "membro" (passaria a "contato")
WITH p AS (
  SELECT id, igreja_id, nome, tipo,
         CASE WHEN length(d) > 11 AND left(d, 2) = '55' THEN substr(d, 3) ELSE d END AS d
  FROM (SELECT id, igreja_id, nome, tipo,
               regexp_replace(coalesce(telefone, ''), '\D', '', 'g') AS d
        FROM public.pessoas) s),
pn AS (
  SELECT *, CASE WHEN length(d) = 10 THEN substr(d, 1, 2) || '9' || substr(d, 3) ELSE d END AS k
  FROM p),
w AS (
  SELECT igreja_id,
         CASE WHEN length(d) > 11 AND left(d, 2) = '55' THEN substr(d, 3) ELSE d END AS d
  FROM (SELECT igreja_id, regexp_replace(coalesce(numero, ''), '\D', '', 'g') AS d
        FROM public.whatsapp_connections WHERE numero IS NOT NULL) s),
wn AS (
  SELECT igreja_id,
         CASE WHEN length(d) = 10 THEN substr(d, 1, 2) || '9' || substr(d, 3) ELSE d END AS k
  FROM w)
SELECT p.id, p.igreja_id, p.nome, right(p.k, 4) AS fone_final_4,
       p.tipo AS atual, 'contato' AS proposto
FROM pn p
WHERE p.tipo = 'membro' AND p.k <> ''
  AND NOT EXISTS (SELECT 1 FROM public.celula_membro cm
                  WHERE cm.pessoa_id = p.id AND cm.igreja_id = p.igreja_id AND cm.ativo IS TRUE)
  AND EXISTS (SELECT 1 FROM wn w WHERE w.igreja_id = p.igreja_id AND w.k = p.k)
ORDER BY p.igreja_id, p.nome, p.id;
```

Estas consultas não são executadas por `release_preflight.py` nem pelo CI. Os
dois `SELECT`s passaram por sintaxe e resultado em `BEGIN READ ONLY; ...
ROLLBACK;` em PostgreSQL 17 descartável com duas igrejas e dados sintéticos. A
consulta 1 retornou somente pessoas com vínculo ativo e tipo `contato`,
`visitante` ou `NULL`. A consulta 2 retornou membros sem vínculo ativo nas
formas `+55` com e sem 9º dígito e local com 9º dígito, incluindo vínculo
inativo; não retornou vínculo ativo, pessoa de outra igreja com o mesmo
telefone nem DDD distinto com o mesmo sufixo. A consulta 2 reproduz o predicado
e os passos de canonicalização da função `pg_temp.pastorai_canon_phone` da
migration `20260711_152127`, comparando o telefone canônico completo. A saída
da consulta 2 não projeta o telefone completo e mostra somente seus quatro
dígitos finais. Nenhum banco real foi consultado.

## Ensaio de restauração sintética

O ensaio não lê nem toca backups reais nem arquivos `.env`. Recusa `DOCKER_HOST`
explícito e contexto Docker cujo endpoint não seja um socket Unix local. Usa
apenas a imagem PostgreSQL 17 já presente na máquina, container com rede
desabilitada e diretório de dados em `tmpfs`. Cria um dump custom do schema
`public` com UUIDs e linhas fictícias, restaura em outro banco do mesmo
container descartável e exige as contagens `synthetic_private_records=2` e
`synthetic_team_events=1`.

```bash
bash backend/scripts/release_restore_synthetic.sh
```

Saída esperada: `RESTORE_SINTETICO=OK tabelas=2 contagens=2:1`. A ausência da
imagem local interrompe o ensaio; não baixar imagem automaticamente na janela
de produção. O script remove o container e os arquivos temporários ao terminar.

## O que não fazer

- Não conectar a PROD, VPS, banco remoto, deploy ou serviço externo durante a
  preparação deste runbook.
- Não abrir `ALLOW_REAL_SENDS`, `ASAAS_BILLING_ENABLED`, `BREVO_SEND_MODE`,
  `BROADCAST_ASYNC_ENABLED`, `AgentConfig.ativo` ou qualquer gate Jev.
- Não aplicar migrations fora da lista e da ordem aprovada por `migrate.py`.
- Não automatizar reconciliação, apagar duplicidades, ignorar RLS ou mascarar
  achado com migration manual.
- Não copiar PII, dados pastorais, dumps reais, URLs, credenciais, chaves ou
  conteúdo de `.env` para relatório, chat, log, teste ou commit.
- Não usar backup real no ensaio local nem restaurar backup sobre banco de
  produção.

## Ensaio sintético de contenção e retomada pré-DDL

Validação local em 24/10, base `830decc1`: 54 testes unitários e os sete
cenários Docker aprovados. O inventário independente confirmou que nenhum
container ou rede preexistente foi removido e que não restaram recursos do
ensaio. Revisão independente Claude Opus sem bloqueios de segurança para
execução descartável. Também passaram 129 testes existentes dos workers
no SHA `830decc1`, com dependências simuladas; não são testes de entrypoint
legado. O campo `production_ready` do recibo permanece `false`.

Redis foi um servidor real com dados fictícios; os workers e o provedor eram
simulados. O campo textual `topology` do recibo usa “falsos” para Redis/provedor;
a descrição precisa do alcance é esta. Não interpretar esse texto como mock
do processo Redis ou como prova de domínio do backend.

**Estado: preparação local.** Não é controlador de PROD, não toca release real,
gates reais, workers da aplicação nem workflows.

`deploy/rehearse_legacy_containment.py` cria os próprios recursos descartáveis
(prefixo aleatório e label `pastorai.synthetic.owner` com o UUID da execução):
uma rede `--internal` sem portas publicadas, Redis, um provedor falso com
barreira e quatro processos **simulados** (`deploy/synthetic_legacy_worker.py`):
`backend`, `queue-worker`, `cron-worker` e `broadcast-worker`. Todos são
containers avulsos, sem labels de Compose, como o `broadcast-worker` observado
em PROD. Entrypoint explícito (`python3` ou `redis-server`; o ENTRYPOINT da
imagem nunca roda), usuário `65534:65534`, raiz somente leitura, sem
capabilities, sem montagem do host, `.env`, credencial ou socket do Docker.
Aceita só IDs de imagem locais (`sha256:...`, sem pull) e o caminho do
relatório; não aceita nome, ID, DSN ou host de alvo existente.

Antes de qualquer efeito, o controlador exige contexto Docker local (socket
Unix, sem `DOCKER_HOST`/`DOCKER_CONTEXT`). Sobe o Redis e espera `PING`; depois
o provedor e os quatro processos; espera os marcadores de partida, gravados só
depois do bind; e por fim confirma o HTTP real de `backend` e provedor com uma
probe interna. Valida o conjunto exato de seis containers próprios: posse,
identidade no ledger, imagem, entrypoint, usuário, rede, ausência de portas e
montagens, e configuração de gate sintética. Os valores de gate são fictícios e
ilustrativos (envio aberto, Brevo `live`, broadcast assíncrono desligado), não
um espelho de PROD: lá não há variável ASAAS real e o default não foi
verificado. Eles permanecem inalterados durante todo o ensaio. Imagem ausente
localmente é recusada como `image-not-local-immutable` antes de qualquer
efeito; comando Docker que excede 120 s vira a recusa fixa `docker-timeout`,
sem comando nem saída, e interrompe a contenção ou a retomada.

A contenção envia só SIGTERM, um serviço por vez (`backend`, `cron-worker`,
`broadcast-worker`, `queue-worker`), com prazo e sem SIGKILL. A retomada
pré-DDL é explícita (token), religa os mesmos containers com a API primeiro e
depois os consumidores, validando o conjunto antes de cada partida; uma falha
de partida registra recusa, sem nova tentativa nem retomada automática.

Cenários, cada um com recursos novos:

| Cenário | Esperado |
|---|---|
| `in-flight-completes-after-sigterm` | Com a barreira fechada, um envio real fica em curso e duas pendências entram pela probe antes de qualquer SIGTERM. A barreira abre entre o sinal e a espera: o envio termina (`done`, efeito 1), saída 0. Com `backend` parado, a probe interna é recusada. A pendência que vence na pausa vai para `expired` com os bytes intactos; a outra é enviada uma vez após a retomada. Um broadcast pendente e um agendamento de cron futuro, semeados antes do SIGTERM, mantêm os mesmos bytes no Redis antes e depois da contenção e da retomada, sem efeito, com os gates inalterados. |
| `in-flight-response-lost` | O efeito ocorre e a resposta não chega: o worker desiste no timeout, leva o item a `ambiguous` sem retry e sai com 0. Após a retomada, o efeito continua 1. Broadcast pendente e cron futuro: mesma verificação de bytes do cenário anterior. |
| `post-ddl-mark` | Depois de marcar o ponto de DDL (sem SQL), a retomada do código antigo é recusada. |
| `graceful-timeout` | Processo que ignora SIGTERM, prazo de 3 s: recusa, o processo continua vivo, DDL e retomada recusados. |
| `identity-swapped` | Container trocado: recusa antes de qualquer sinal. |
| `fifth-writer` | Quinto writer na rede: recusa antes de qualquer sinal. |
| `interrupted` | Interrupção depois do primeiro sinal: a sequência para, sem retomada nem DDL. |

Prazos dos cenários físicos: resposta do provedor 15 s, prazo gracioso 30 s,
expiração 50 s.

Como executar (somente em máquina local descartável, pelo runner do revisor):

```bash
python3 deploy/rehearse_legacy_containment.py \
  --worker-image sha256:<ID local de imagem com python3> \
  --redis-image sha256:<ID local de imagem com redis-server >= 6.2> \
  --report /tmp/legacy-containment-report.json
python3 -m pytest deploy/tests/test_legacy_containment.py
```

A limpeza percorre só o ledger de IDs que esta execução criou (containers,
probes, substituto, intruso e rede) e remove cada um apenas se ainda tiver o
label de posse; nunca procura recursos por label. Tenta todos os IDs mesmo se
uma remoção falhar. Ausência só é concluída por uma listagem read-only de IDs;
Docker indisponível ou `inspect` com falha viram erro e sobra no relatório,
nunca "inexistente". Cenário com limpeza incompleta não é PASS, e o erro de
limpeza não substitui o motivo original da falha. O `docker rm -f` da limpeza
remove recurso descartável próprio e não faz parte da contenção. Nunca
reinicia daemon ou host.

**Limites.** Não é controlador de PROD nem prova de prontidão para PROD. O
relatório prova a topologia e o controlador sintéticos. Os workers são
simulados: não prova o tratamento de SIGTERM dos workers reais de `07a3f4d`,
retries da Evolution, reinício do Docker, compatibilidade pós-DDL nem a
semântica de fila dos workers legados. A marca de DDL é só estado do
controlador; nenhum SQL é executado.

## Ciclo de vida do queue-worker real do legado

A fatia seguinte à #573 usa `deploy/rehearse_legacy_queue.py` para executar
`python -m app.workers.queue_worker` do SHA fixo
`07a3f4d9a4fe510cf83fd48d5deaa52dcfbb7e02`, com dependências do respectivo
`requirements.lock`. O código do aplicativo não é alterado. O evento fictício
é ignorado pelo parser real antes de banco, agente ou provedor, mas percorre
enfileiramento, claim e ACK reais.

Preparação exclusivamente local e sintética:

1. Executar `python3.13 deploy/rehearse_legacy_queue.py materialize --repo .
   --out /tmp/legacy-queue-source-NOVO`. O destino precisa não existir.
   A seleção lê apenas fontes Python permitidas de `backend/app` e o lock;
   não usa checkout/archive completo nem arquivos de ambiente.
2. Preparar uma imagem Python 3.13 com essa árvore em `/opt/legacy` e instalar
   o lock com `pip install --require-hashes -r /opt/legacy/requirements.lock`.
   Não copiar o workspace inteiro. A imagem não pode conter credenciais,
   configurações externas, volumes declarados ou arquivos extras nessa árvore.
3. Executar `python3.13 deploy/rehearse_legacy_queue.py run --repo .
   --legacy-image sha256:ID_LOCAL --redis-image sha256:ID_LOCAL
   --report /tmp/legacy-queue-report.json`, substituindo os IDs por imagens
   locais imutáveis. O programa recusa daemon remoto e não baixa imagens.

O preflight compara fontes com os blobs Git e nomes/versões instalados com o
lock. O ensaio cria Redis e rede interna próprios, sem portas ou montagens do
host, e exige heartbeat, lease e registro. Depois de SIGTERM exige saída zero,
heartbeat parado e remoção do registro/lease; enfileira enquanto parado,
confere preservação, reinicia o mesmo container e exige consumo/ACK e segunda
parada limpa. A limpeza usa os IDs criados pela execução; sobras impedem PASS.

Um PASS cobre esse ciclo de vida, não uma mensagem pastoral em processamento,
transação PostgreSQL, transporte Evolution, demais workers, restart do host,
compatibilidade pós-DDL ou produção. `production_ready=false` permanece.
A etapa posterior é provar uma ingestão ativa com barreira transacional em
PostgreSQL sintético antes de ampliar a conclusão operacional.

Validação local em 24/10/2026: 88 testes aprovados, zero skip; ensaio físico
com sete verificações aprovado, sem divergência de fonte/runtime, limpeza
com zero erros e nenhum container/rede remanescente. Imagem sintética legada
`34083a4f8d5a`, Redis `ff02b58f971e`; 148 fontes/lock conferidos contra o Git.
A prova independente anterior também passou. Não equivale aos quatro checks
de integração do futuro SHA publicado nem a uma verificação de produção.

## Ingestão ativa durante SIGTERM — validada localmente

A etapa seguinte à #574 usa `deploy/rehearse_legacy_queue_active.py` com o processo real do legado
`07a3f4d`, Redis e PostgreSQL descartáveis. A base sintética usa as 78
migrations selecionadas pelo aplicador atual, preservando RLS e triggers.
São duas igrejas fictícias; não há conexão com banco ou número real.

A barreira é o advisory lock já usado pela ingestão para o identificador da
mensagem, antes de escrever Pessoa/Conversation/Message. Isso prova a parada
enquanto a transação aguarda o fence; não prova parada com escritas ainda
não confirmadas. O ensaio precisa observar o worker bloqueado na transação e com o
envelope em processamento antes do SIGTERM. Enquanto a barreira estiver
fechada, o processo deve permanecer vivo e a mensagem ainda não pode estar
confirmada. Após liberar o lock, exige commit único, ACK, deregistro e saída
zero. Reenvios com e sem o marcador Redis devem preservar as contagens.

O tenant vem da instância oficial registrada, inclusive diante de um
`igreja_id` forjado no payload. Uma prova separada usa a promoção real para
`authenticated`, verifica leitura isolada e recusa de escrita na outra
igreja. O trigger legado confirma `pessoas.consentimento`; não se exige
registro em `consent_records` para este caminho.

Esta etapa ainda não comprova turno completo do agente, envio por provedor,
recuperação após DDL ou produção. Pilotos vazios e gates fechados mantêm a
execução dentro do escopo sintético.

Reprodução local, com as imagens imutáveis já preparadas e Docker local:

```bash
python3.13 deploy/rehearse_legacy_queue_active.py run --repo . --report /tmp/legacy-active-report.json
```

As opções `--legacy-image`, `--redis-image` e `--postgres-image` aceitam apenas
IDs locais `sha256:...`; sem downloads ou alvos existentes. O preflight confere
fonte/runtime legados. O banco recebe somente o aplicador atual e os 78 SQLs
selecionados; registros de bootstrap são preservados e conferidos.

Validação final em 25/10/2026: 130 testes aprovados, zero skip (42 novos e
88 de regressão); 20 verificações físicas aprovadas. A barreira, contando
desde antes do enqueue, durou 6,462 s; saída 0 em 0,636 s após liberação.
ACK estável, TTL sem renovação (comparado pelo instante de expiração),
contagens/não lidas preservadas, escrita na própria igreja permitida e
escrita na outra negada especificamente por RLS. Limpeza sem erros, zero
containers e redes remanescentes. Provas independentes também aprovadas.
Revisão Claude incorporada e versão final verificada pelo Codex.

Não se reproduzem papéis de login/timeouts de produção; não se atesta a
integridade de wheels, sitecustomize ou pth instalados. Os testes/ensaio novos
são evidências locais e não foram adicionados aos workflows existentes.
Os quatro checks obrigatórios do futuro SHA publicado são uma prova separada.

## Tick ativo do cron-worker durante SIGTERM — validado localmente

A etapa seguinte à #575 usa `deploy/rehearse_legacy_cron_active.py`, reaproveitando
a guarda de Docker local, a conferência de fonte/runtime de `07a3f4d`, o ledger
de posse e a mesma base sintética de 78 migrations (aplicador atual, sem
`create_all` nem wrappers pausados, bootstrap oficial preservado). O PID 1 é
`python -m app.workers.cron_worker` original, sem patch nem mock, com gates
fechados, piloto vazio, provedores em loopback morto e `CRON_TICK_SECONDS=10`.

A barreira usa a primeira etapa real do tick: a purga cross-tenant de
`calendar_oauth_flows`. O seed cria, numa igreja fictícia própria, um fluxo
expirado e um válido; antes do worker subir, uma conexão separada mantém
`FOR UPDATE` só no expirado. O ensaio exige, por IP dos containers em
`pg_stat_activity`/`pg_locks`, um único backend do worker executando o
`DELETE` e esperando `transactionid` no xid do holder. Envia SIGTERM e, durante
uma janela observada, exige processo vivo, heartbeat `running`, mesmo bloqueio
e banco inalterado (fluxos e digest de todas as tabelas de `public`). Só então
libera e exige: remoção única do expirado, válido idêntico, linha real
`sla=0, crons=0, plan_changes=0, oauth_flows_purged=1`, pedido de shutdown
registrado antes do fim do tick, saída 0 antes do intervalo do próximo tick,
heartbeat `stopped`, Redis só com o heartbeat e nenhuma outra tabela alterada.
Qualquer aviso/erro/traceback no log do worker é recusa. O orçamento de 20 s fica
abaixo dos 30 s de progresso do legado. Ele é medido depois do último check do
conjunto de containers e da reconfirmação do heartbeat `running`, imediatamente
antes de liberar; a decisão usa o tempo sem arredondar (só o relatório arredonda).

Limites: o `stop()` legado só faz `_running=False`; SLA, crons e billing do tick
em curso continuam depois do sinal, então não há contenção antes da saída. O
seed e o bootstrap não deixam trabalho para essas fases (pré-condição
conferida), logo SIGTERM com trabalho real nelas não é provado. O psycopg2
síncrono tende a adiar o handler até o `DELETE` voltar; isso só é observado. Não
prova supervisor/política de reinício, papéis de login ou timeouts de produção,
pós-DDL, outros serviços nem produção (`production_ready=false`).

Reprodução local, com as mesmas imagens imutáveis do ensaio anterior:

```bash
python3.13 deploy/rehearse_legacy_cron_active.py run --repo . --report /tmp/legacy-cron-report.json
```

Primeira rodada em 25/10/2026 (Codex): 172 testes aprovados (42 novos e 130 de
regressão) e ensaio físico aprovado com 13 verificações; bloqueio observado em
5,918 s desde o start do worker, saída 0 em 0,626 s após a liberação, limpeza
sem sobras. A revisão independente não apontou bloqueios nem regressões e pediu
a guarda temporal acima, já aplicada, com testes de recusa sem liberação.
Revalidação final após esse ajuste (Codex, 25/10/2026): 176 testes aprovados,
zero skip (46 novos e 130 de regressão); ensaio físico aprovado com 13
verificações, bloqueio em 6,445 s, saída 0 em 0,652 s após a liberação, limpeza
sem sobras. São evidências locais; os testes/ensaio novos não foram adicionados
aos workflows, e os quatro checks do SHA publicado são prova separada.

## Ciclo de vida ocioso do broadcast-worker real — integrado pela #577 (`92821e35`)

A etapa seguinte à #576 usa `deploy/rehearse_legacy_broadcast.py`, reaproveitando
de `rehearse_legacy_queue.py` a conferência de fonte/runtime de `07a3f4d` (148
fontes + lock), a guarda de Docker local, o ledger e a limpeza por posse. Só há
Redis descartável numa rede `--internal` própria, sem portas, montagens ou
download de imagem; não existe Postgres e `DATABASE_URL`/Evolution apontam para
loopback morto. O PID 1 é `python -m app.workers.broadcast_worker` original,
sem patch nem mock. O container usa `--init=false` explícito e o ensaio exige
`HostConfig.Init` igual a `false`; ausente/`null` (default do daemon, que pode
ter `init: true` e injetar `docker-init` mesmo com `Path=python`) ou `true` é
recusa. Gates: `ALLOW_REAL_SENDS=false`, `BROADCAST_ASYNC_ENABLED=false`,
Brevo `off`, Asaas `false`, piloto vazio e `BROADCAST_WORKER_TICK_SECONDS=10`.

Com esses gates o legado decide `enabled=False` no boot e fica **ocioso**; o
ensaio não abre gate e não afirma estado ativo. Exige: heartbeat `idle` e sua
renovação pelo loop (instante de expiração posterior), Redis só com esse
heartbeat, log com `enabled=False` e o aviso OCIOSO exato como único WARNING
aceito, sem tick, envio, dispatch pausado ou transporte. SIGTERM real: saída 0
antes do próximo tick, heartbeat `stopped`, log igual e TTL não renovado
durante a observação posterior. `docker start` do mesmo container precisa ser
uma nova execução (`StartedAt` novo, segundo boot no log) com `idle`
substituindo `stopped`; o segundo SIGTERM repete a saída 0 e `stopped`.

Ausência de rede não é capturada; é inferida de três fatos: destinos de banco
e Evolution inacessíveis (loopback morto, rede interna sem Postgres), gates
`false` e o caminho ocioso do código legado (`tick()` nunca chamado, sessão
nunca resolvida, `EvolutionClient` sem cliente HTTP até o primeiro uso e
`close()` sem efeito quando nada foi aberto).

Limites: não prova broadcast ativo, trabalho ou transporte Evolution em curso,
pendências no banco, que fechar gate pause fila, supervisor/restart do host,
backend, pós-DDL, RLS nem produção (`production_ready=false`).

Reprodução local, com as mesmas imagens imutáveis legada/Redis dos ensaios anteriores:

```bash
python3.13 deploy/rehearse_legacy_broadcast.py run --repo . --report /tmp/legacy-broadcast-report.json
```

Validação final em 25/10/2026 (Codex): 216 testes aprovados, zero skip (40
novos e 176 de regressão); ensaio físico aprovado com 10 verificações e
`HostConfig.Init=false` conferido; saída 0 em 0,503 s/0,549 s após cada
SIGTERM, heartbeat renovado em 9,947 s/9,948 s, limpeza sem erros nem sobras.
A revisão independente exigiu o PID 1 sem `init` do daemon; a correção foi
confirmada pelo Codex. São evidências locais; os testes/ensaio novos não foram
adicionados aos workflows, e os quatro checks do SHA publicado são prova separada.

## Backend ASGI com HTTP em curso durante SIGTERM — validado localmente

A fatia seguinte (#578; base `6b0b302b`, sem depender da #577, depois atualizada
com a `main` que já contém a #577 em `92821e35`) usa
`deploy/rehearse_legacy_backend.py`. Reaproveita a guarda de Docker local, a
fonte/runtime exatos de `07a3f4d`, o ledger e o Redis próprio. O PID 1 é o console
script real `uvicorn app.main:app --host 0.0.0.0 --port 8000` (CMD do
Dockerfile legado), com `--init=false` conferido, sem patch, mock, rota ou
instrumentação da aplicação. O preflight confere o script contra o RECORD da
distribuição `uvicorn==0.49.0`, o protocolo httptools e as premissas de shutdown
do Uvicorn instalado. Diferenças em relação ao Dockerfile: workdir `/opt/legacy`,
usuário 65534, rootfs read-only, sem `migrations/` e sem healthcheck do Compose.

Configuração: gates fechados, piloto vazio, `EVOLUTION_WEBHOOK_SECRET` fictício
fixo enviado só por header `X-Webhook-Token` (nunca query) e banco em loopback
morto. O único aviso de startup aceito é `Database warmup unavailable`, e
`/health` 200 prova só liveness: não é readiness nem prontidão de produção.
Allowlist exata de avisos: esse warmup (um por boot) e um `Rejected webhook`
da prova negativa (token errado, corpo completo, 401 real e fila vazia). O
relatório leva só marcadores próprios e contagens; o segredo fictício não pode
aparecer nos logs.

Barreira: um probe separado da mesma imagem envia o `POST /whatsapp/webhook`
com `Content-Length` do corpo inteiro e só metade do JSON. O handler legado lê o
corpo antes de autenticar. O probe só publica o READY depois que `TIOCOUTQ` do
socket chega a 0 (bytes confirmados por ACK do servidor, sem `recv`, prazo de
5 s; falha ou timeout encerram o probe e recusam). O controlador exige `outq`
inteiro igual a 0. Antes do SIGTERM, o `/proc` do backend (`docker exec` só
leitura) precisa mostrar a conexão do IP/porta do probe ESTABLISHED,
pertencente ao PID 1, com Recv-Q/Send-Q zero, e a fila precisa estar vazia.
ACK no cliente, Recv-Q 0 no servidor e a conexão retida durante a drenagem
sustentam um ciclo HTTP aberto, não a linha exata do handler
(`request.stream()`). Depois do sinal: backend vivo, log
`Waiting for connections to close`, listener fechado, conexão nova recusada,
mesma conexão retida e lifespan ainda aberto, numa janela observada. Só então
o restante do corpo segue na mesma conexão e se exige: 202
`{"status":"queued"}`, conexão encerrada pelo servidor (sem reuso), um envelope
no `WebhookQueue` real, ordem exata em stderr (resposta antes do lifespan
fechar os pools) e saída 0 sem SIGKILL. A duração da telemetria precisa cobrir o
intervalo sinal→liberação, mas isso é só consistência: inclui o processamento
após a liberação e a latência do kill, então não prova ordem. Os bytes da
fila se mantêm após a parada e após reiniciar o mesmo container sem consumidor;
o segundo SIGTERM também sai com 0.

Orçamentos independentes: barreira 20 s; log de drenagem 10 s após o sinal;
retenção abaixo de 20 s, medida depois do último check; saída em menos de 30 s
após a liberação.

Riscos e limites: a saída 0 depende de PID 1 direto, porque o Uvicorn re-levanta
o SIGTERM após o shutdown e só o PID 1 o ignora; sob init, seria 143. Sem
`--timeout-graceful-shutdown`, um cliente que nunca completa o corpo segura o
shutdown indefinidamente até o prazo do supervisor (SIGKILL). Não prova a
posição interna do handler nem o início do ASGI antes do sinal (inferido), consumo
pelo worker, turno do agente, banco/RLS, retries da Evolution,
supervisor/restart policy, topologia viva (proxy, init, timeouts), pós-DDL nem
produção (`production_ready=false`).

Reprodução local, com as mesmas imagens imutáveis dos ensaios anteriores:

```bash
python3.13 deploy/rehearse_legacy_backend.py run --repo . --report /tmp/legacy-backend-report.json
```

Validação final em 25/10/2026: 279 testes aprovados, zero skip (103 novos e
176 de regressão); ensaio físico (Codex) aprovado com 12 verificações, retenção
de 6,600 s após o sinal, saída 1,202 s após a liberação, segunda parada em
1,168 s, limpeza sem sobras. Premissas do Uvicorn 0.49.0 conferidas na imagem;
revisão independente incorporada. Um request gera um envelope; idempotência de
reenvio não é provada aqui. É prova sobre o HTTP real já existente, não
capacidade nova do agente. Os testes/ensaio não entram nos workflows, e os
quatro checks do SHA publicado são prova separada.
