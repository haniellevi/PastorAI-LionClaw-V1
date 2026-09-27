# queue-worker: timeout transitório do Redis não encerra mais o processo — 2026-09-27

**Branch:** `fix/queue-worker-redis-transient` (PR #425) · **Base:** `e6aafc2` · **Deploy:** PROD `eb5a09b` em 27/09, 13:16 UTC.
Código e testes: local, com Redis falso e Redis 7 descartável em Docker.
Investigação e deploy: VPS de PROD, com chave temporária revogada no fim.

## Incidente

Em PROD (release `e6aafc2`), às 06:15:57 UTC de 27/09, o
`pastorai_queue_worker` caiu com
`redis.exceptions.TimeoutError: Timeout reading from socket`, lançado em
`_read_from_socket`. O Docker religou o container (restart count 1) às
06:16:05. A fila estava vazia.

## Causa no código

- `QueueWorker.run()` não tratava erro do Redis. Um `TimeoutError` ou
  `ConnectionError` em `refresh_worker_lease`, `recover_pending` ou `claim`
  saía de `main()` e encerrava o processo. Com o código de `e6aafc2` e um Redis
  falso que dá timeout no BRPOPLPUSH, `run()` levanta exatamente esse erro.
- A margem era curta. O BRPOPLPUSH bloqueava 5 s no servidor, e o
  `socket_timeout` do cliente era 7 s. Um travamento de mais de ~2 s (no Redis,
  na rede ou no host) perto do fim da espera transforma a resposta vazia normal
  em `TimeoutError`. Com a fila vazia, o worker passa quase todo o tempo nesse
  comando.
- Dois outros caminhos também encerravam o worker. A thread de heartbeat parava
  o consumo em qualquer exceção ao renovar a lease. E o `unregister_worker` do
  `finally` podia trocar um desligamento limpo por um traceback.
- O traceback de PROD não mostra o frame do worker, então a linha exata é
  inferência: o BRPOPLPUSH é o único comando cuja duração normal chega perto do
  timeout. O travamento veio do backup diário (seção seguinte).

## Causa do travamento: o backup diário pausa o Redis

O cron da VPS roda `/usr/local/sbin/pastorai-backup.sh`
(`deploy/backup-production.sh`) todo dia às 06:15:01 UTC. Para copiar os
volumes, o script faz `docker pause` no Redis, na Evolution e no Postgres da
Evolution, compacta os três volumes e só então faz `docker unpause`. Em 27/09,
pelo journal da VPS:

- ~06:15:52: começa a pausa (primeiro container de `tar`);
- 06:15:57: o worker cai, 7 s depois do envio do BRPOPLPUSH em andamento
  (enviado ~06:15:50, antes da pausa);
- ~06:16:01: termina o último `tar` e o Redis volta.

A pausa dura ~9 s e se repete todo dia (26/09 teve o mesmo padrão). O log do
Redis não mostra erro no intervalo, e o `apt-daily-upgrade` das 06:15:18 não
instalou nada. O log do worker dessa hora se perdeu (container recriado às
11:10 UTC), então a linha exata continua inferida, mas o horário bate ao
segundo. Com a correção, o worker registra um aviso, espera e continua quando o
Redis volta, dentro da lease de 30 s.

## O que foi feito (`backend/app/workers/queue_worker.py`)

- **Erros transitórios.** `redis.exceptions.TimeoutError` e `ConnectionError`
  (inclusive `BusyLoadingError`, e também quando os scripts de retry os
  embrulham em `RuntimeError(...) from exc`) no registro, na renovação da
  lease, na recuperação e no claim agora geram um aviso no log com a etapa e a
  tentativa. O worker espera 0,5 s, dobrando até 5 s, e tenta de novo. Quando
  o Redis volta, o log registra `recovered after N failure(s)` e a espera
  recomeça em 0,5 s.
- **Resposta perdida.** Se o BRPOPLPUSH (ou o script de reconcile) rodou no
  Redis mas a resposta não chegou, o item fica na lista privada do worker.
  O mesmo vale para um ACK não confirmado. Com a lease renovada e nenhum item em
  andamento, `WebhookQueue.requeue_own_claims` devolve a lista privada à fila.
  O LMOVE é atômico e põe o item de volta na ponta de consumo, na ordem
  original, à frente de mensagens mais novas. A nova leitura é deduplicada pelo
  marcador de idempotência e pelo estado do retry.
- **Heartbeat.** Um erro transitório adia a renovação para o próximo tick.
  Lease expirada, erro não transitório e worker travado continuam parando o
  consumo.
- **Saúde degradada** (achado P1 do Codex na PR #425). Se as falhas do Redis
  durarem mais que uma lease (30 s), o worker publica `error`, e o healthcheck
  e a readiness passam a acusar. Isso cobre o caso em que o BRPOPLPUSH falha
  enquanto a lease e o heartbeat ainda funcionam. O estado volta a `ready`
  quando o Redis responde. Soluços curtos não mudam o estado publicado, para
  não abrir incidente falso no monitor.
- **Desligamento.** Um erro transitório no `unregister_worker` vira aviso. A
  lease expira pelo TTL, e o registro continua permitindo a recuperação.
  `stop()` marca a parada antes de logar, para que o SIGTERM não se perca.
- **`ack` de envelope malformado.** Deixa de propagar erro do Redis, como já
  acontecia no caminho normal.
- **Margem.** `BRPOP_TIMEOUT` passa de 5 para 2 s, e o `socket_timeout`
  continua em 7 s. A margem sobe de 2 para 5 s.

## Decisões

- **Tentativas sem limite, com espera limitada (no máximo 5 s).** Encerrar o
  processo não ajuda enquanto o Redis estiver fora. A lease continua sendo a
  trava: se expirar durante a queda, o worker para como antes, sem mexer na
  própria lista. O Docker (`restart: always`) sobe outro processo, que recupera
  o item.
- **Troca aceita:** um host, porta ou TLS errado também dá `ConnectionError`.
  Nesse caso o worker fica tentando em vez de reiniciar em loop. O sinal passa
  a ser o aviso `stage=register` no log e o healthcheck `unhealthy` (sem
  heartbeat).
- **O progresso continua registrado durante as esperas.** O watchdog de
  progresso detecta a thread principal travada. Sem esse registro, uma queda
  total de mais de 60 s voltaria a encerrar o processo. O sinal de "vivo, mas
  sem consumir" é o estado `error` depois de 30 s de falhas.
- **Encurtar o bloqueio em vez de aumentar o `socket_timeout`.** O timeout
  também limita a renovação da lease: dois heartbeats de 10 s mais 7 s dão
  27 s, abaixo da lease de 30 s. A conta ignora uma reconexão (até 3 s de
  connect). Nesse pior caso a lease expira e o worker para com segurança
  (`ClaimOwnershipLost`), como antes. O custo é, com a fila vazia, ~3 comandos
  baratos a cada 2 s em vez de a cada 5 s. Em troca, um retry agendado é
  promovido até 3 s mais cedo.
- **O que ainda derruba o processo (falha fechada):** `ResponseError`
  (WRONGTYPE, MISCONF, OOM), `AuthenticationError` e `AuthorizationError`, fila
  de retry inutilizável e erro de script sem causa transitória.
- **O que não mudou:** os scripts Lua e o tratamento de `ClaimOwnershipLost`
  durante o processamento de um item (lease perdida, agente em execução em
  outro processo).
- **Espera em fatias de 1 s, checando `_running`,** como fazem o `cron_worker`
  e o `broadcast_worker`. O SIGTERM continua rápido sem chamar `Event.set()`
  dentro do handler de sinal.
- **LMOVE exige Redis 6.2 ou mais novo.** PROD usa `redis:7-alpine`, e os
  testes usam Redis 7.4.

## Pendente / próximo passo

- **Conferir o backup de 28/09, 06:15 UTC.** O log do `queue-worker` deve
  mostrar `Redis call failed ... attempt=1` e `recovered after N failure(s)`,
  sem reinício do container. Precisa de acesso à VPS.
- **O backup pausa o Redis e a Evolution ~9 s todo dia.** Com a correção isso
  não derruba mais o worker, mas os dois ficam parados nesse intervalo. Dá para
  copiar o Redis sem pausar (`BGSAVE` e cópia do `dump.rdb`). Não feito.
- **Monitor público:** o cron pede uma execução a cada 30 min, mas o GitHub
  rodou o workflow só a cada 2 a 6 h entre 25 e 27/09. Um incidente curto passa
  sem alerta.
- **Erro transitório durante o processamento de um item** continua valendo como
  falha do item (usa 1 das 5 tentativas) ou para o worker por
  `ClaimOwnershipLost`. Fora do escopo.
- **BRPOPLPUSH** está deprecated desde o Redis 6.2 (o substituto é BLMOVE), mas
  funciona no Redis 7. A troca não foi feita.

## Verificação

- **31 casos novos.**
  - 28 com Redis falso, em `test_whatsapp_worker.py`: timeout no poll ocioso;
    resposta perdida do BRPOPLPUSH (com a ordem preservada) e do reconcile; ACK
    não confirmado; ACK de envelope malformado; lease perdida durante a queda;
    registro com o Redis carregando; backoff e reinício da espera; saúde
    `error` depois de 30 s de falhas e volta a `ready`; SIGTERM durante a
    espera; erros não transitórios; heartbeat; desligamento; classificação dos
    erros; margens de timeout.
  - 3 com Redis 7.4 real em Docker, em `test_queue_redis7_transition.py`:
    socket timeout real com a mensagem de PROD; resposta perdida do claim;
    resposta perdida do reconcile, com o estado canônico do retry preservado.
  - Os testes de laço têm um teto de polls: uma regressão falha em vez de
    travar o CI.
- **Revisão adversarial independente** (subagente, só leitura) das invariantes
  de lease, lista de processamento, retry e recuperação. Não encontrou defeito
  de correção. Os três achados de baixa severidade e três dos nits foram
  corrigidos: ACK não confirmado, teste com timeout curto em todos os comandos,
  testes que podiam travar, ordem do requeue, ordem de `stop()` e teste do ACK
  malformado.
- **Revisão do Codex na PR #425:** um P1. O worker continuava `ready` enquanto
  não consumia. Foi corrigido com a saúde degradada acima.
- **Mutações:** remover o requeue, voltar o requeue para o fim da fila, não
  marcar o ACK não confirmado ou não publicar `error` faz falhar os testes
  correspondentes, sem travar.
- **`./test-local.sh` terminou com exit 0**, usando Python 3.13.14 e Node
  24.19.0 via `PASTORAI_PYTHON` e `PASTORAI_NODE_BIN`.
  - Backend: 5.450 passed, 340 deselected (`rls_integration`), zero skip,
    incluindo os 27 testes Redis 7.
  - Frontend: 883 testes em 99 arquivos, e typecheck.
- Nada disso prova o comportamento em PROD. A prova operacional é o próximo
  backup (28/09, 06:15 UTC) passar sem reinício do container.

## Deploy em PROD — `eb5a09b` (27/09, 13:16 UTC)

Feito pelo Claude Code com "ok" do proprietário, pela seção 5 do
`PRODUCTION-RUNBOOK.md` e pelo roteiro B1–B3 do deploy anterior. Sem migration.

- **Acesso:** chave ed25519 temporária (`claude-deploy-2026-09-27`), colada pelo
  proprietário com `expiry-time="20260928Z"`. A host key foi conferida contra o
  registro já conhecido do IP. No fim, a chave saiu do `authorized_keys` (as duas
  linhas coladas; 9 → 7 linhas) e o acesso passou a ser recusado. Artefato e log
  de build foram apagados da VPS.
- **Artefato:** `git archive` do `eb5a09b` (`backend` + `deploy`, sem testes e
  sem `.env*`), 306 arquivos, SHA-256 `f74275e6a02b…`. A mesma receita reproduz
  os 306 arquivos do `e6aafc2`. A única diferença para o release ativo era o
  `queue_worker.py`; `backend` e `deploy` são idênticos aos do merge `dd02368`
  (a #427 só mudou docs).
- **Travas:** `ALLOW_REAL_SENDS=true` já estava ligado. O proprietário escolheu o
  deploy completo mantendo os envios ligados. A prova pós-restart conferiu que as
  travas ficaram iguais nos 4 processos: envios ligados; Asaas, broadcast e Brevo
  desligados; lista piloto definida. O `.env` foi copiado idêntico, modo 600, sem
  impressão.
- **B1:** release em `/opt/pastorai-releases/eb5a09b…`. A imagem anterior
  `pastorai-backend:e6aafc2` (`439b42dff0e0`) ficou para rollback; a nova
  `pastorai-backend:eb5a09b` (`bab6320c3331`) saiu em 5 s, com o código novo
  conferido dentro dela. O dry-run mostrou só os 4 processos do app.
- **B2:** `docker compose up -d --no-deps --wait` dos 4 processos às 13:15:52,
  todos `healthy` às 13:16:17. O `--wait` evita o falso negativo do `/health` do
  deploy anterior. `/health` ok, `/ready` verde e symlink trocado para o
  `eb5a09b`.
- **B3:** `/health` e `/ready` públicos verdes; portas 8000 e 8080 sem resposta
  de fora; Redis e Evolution intocados (start às 12:01:06); `queue-worker` sem
  erro e sem reinício.
- A `main` já está à frente: a #424 (latência do banco) entrou depois deste
  deploy e não foi implantada.

**Rollback:** do código, revert do commit. Do deploy, apontar
`/opt/pastorai-current` de volta para o release `e6aafc2…` e recriar os 4
processos a partir dele (imagem `pastorai-backend:e6aafc2` guardada). Não há
migration nem mudança de configuração.
