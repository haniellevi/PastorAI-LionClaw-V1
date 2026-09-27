# queue-worker: timeout transitório do Redis não encerra mais o processo — 2026-09-27

**Branch:** `fix/queue-worker-redis-transient` · **Base:** `e6aafc2` · **Deploy:** não.
Ambiente local, com Redis falso e Redis 7 descartável em Docker. Nenhum acesso a
PROD ou à VPS.

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
  timeout. O motivo do travamento do Redis não foi investigado.

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

- **Deploy:** rebuild da imagem e restart do `queue-worker`, pelo runbook. Não
  foi feito aqui.
- **Motivo do travamento do Redis às 06:15 UTC** (Fase 4, B8 e B16). Leituras
  sugeridas em PROD, só de leitura:
  - `docker logs pastorai_redis` perto de 06:15:50 (procurar
    `Asynchronous AOF fsync is taking too long` ou BGREWRITEAOF);
  - `redis-cli INFO persistence` e `LATENCY LATEST`;
  - I/O e CPU steal do host no mesmo horário.

  O Redis roda com `appendonly yes` e é compartilhado com a Evolution (db 1).
- **Erro transitório durante o processamento de um item** continua valendo como
  falha do item (usa 1 das 5 tentativas) ou para o worker por
  `ClaimOwnershipLost`. Fora do escopo.
- **BRPOPLPUSH** está deprecated desde o Redis 6.2 (o substituto é BLMOVE), mas
  funciona no Redis 7. A troca não foi feita.

## Verificação

- **30 casos novos.**
  - 27 com Redis falso, em `test_whatsapp_worker.py`: timeout no poll ocioso;
    resposta perdida do BRPOPLPUSH (com a ordem preservada) e do reconcile; ACK
    não confirmado; ACK de envelope malformado; lease perdida durante a queda;
    registro com o Redis carregando; backoff e reinício da espera; SIGTERM
    durante a espera; erros não transitórios; heartbeat; desligamento;
    classificação dos erros; margens de timeout.
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
- **Mutações:** remover o requeue, voltar o requeue para o fim da fila ou não
  marcar o ACK não confirmado faz falhar os testes correspondentes, sem travar.
- **`./test-local.sh` terminou com exit 0**, usando Python 3.13.14 e Node
  24.19.0 via `PASTORAI_PYTHON` e `PASTORAI_NODE_BIN`.
  - Backend: 5.449 passed, 340 deselected (`rls_integration`), zero skip,
    incluindo os 27 testes Redis 7.
  - Frontend: 883 testes em 99 arquivos, e typecheck.
- Nada disso prova o comportamento em PROD. A prova operacional é o deploy
  seguido de logs sem reinício do container.

**Rollback:** revert do commit. Não há migration nem mudança de configuração.
