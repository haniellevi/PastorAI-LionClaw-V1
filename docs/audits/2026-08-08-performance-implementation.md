# Implementação do plano de desempenho — 2026-08-08

## Resultado executivo

O primeiro ciclo de correções de desempenho foi implementado em um worktree
isolado, medido antes/depois e revisado por uma segunda análise independente.
O parecer daquele fechamento foi: **nenhum achado P0–P2 restante no diff
publicado naquele momento**.

Um segundo ciclo, executado em DEV com autenticação, Redis e PostgreSQL reais,
encontrou gargalos que o laboratório público não mostrava: latência de rede até
o banco, round-trips sequenciais no bootstrap, indisponibilidade do Redis
adicionando cerca de oito segundos ao login e tratamento incorreto de falhas de
infraestrutura como senha inválida. Esses pontos foram corrigidos localmente,
revalidados e consolidados em commits da branch. O último lote de warmup e
`/team/lookup` também foi versionado; a branch ainda não recebeu o novo push e
produção continua intocada.

Principais resultados locais:

- First Load JS de `/`: **218 kB → 110 kB** (`-49,5%`).
- Lighthouse mobile simulado: **91 → 98**.
- LCP mediano: **3,43 s → 2,29 s** (`-33,0%`).
- TBT mediano: **108 ms → 19,5 ms** (`-81,9%`).
- Transferência inicial: **365,7 kB → 227,6 kB** (`-37,8%`).
- Suíte backend: **289,3 s → 20,2 s** (`-93,0%`), mesmo crescendo de
  1.846 para 1.924 testes selecionados.
- Painel autenticado completo, mediana de laboratório: **4,60 s → 3,26 s**
  (`-29,0%`).
- `/dashboard/overview`, p50 no DEV real: **2,51 s → 1,50 s** (`-40,1%`).
- `/auth/me`, p50 no DEV real: **1,30 s → 1,11 s** (`-15,0%`).
- Login aquecido: o encadeamento backend `login + /auth/me` de cerca de
  **4,81 s** foi reduzido a um único `login` de **1,51 s** de tempo da
  aplicação (**1,63 s** de parede no cliente local).
- Painel após reinício do backend, mediana de três partidas controladas:
  **6,78 s → 4,02 s** (`-40,7%`).
- Painel aquecido, mediana do gate final: **3,49 s → 2,87 s** (`-17,7%`).
- `/team/lookup` aquecido, p50 no gate final: **1,86 s → 1,47 s**
  (`-20,7%`).

Esses números são de laboratório local. Não equivalem a RUM de usuários reais,
nem provam o comportamento de banco/Redis sob carga de produção.

## Isolamento e fonte do código

- Checkout principal encontrado em `9121abb`, detached e com alterações locais:
  **não foi modificado**.
- Worktree de implementação:
  `.codex/worktrees/performance-plan`.
- Branch: `codex/performance-plan`.
- Base: `deb95a8cfebc154168bcc13a2bd304aa34260bcf` (`origin/main` no início).
- Integração mais recente: `origin/main` em
  `4755e5fb559cb653c4f10958b68cbc08f0703520`, incorporada pelo merge local
  `19fb55a55d08a15e5ddc1553670228a859312029`.
- Estado operacional: a migration de idempotência outbound foi aplicada
  **somente no banco DEV**, com autorização explícita e validação; não houve
  migration em produção nem deploy. A branch local está integrada e validada;
  o PR permanece draft e o novo SHA ainda não foi publicado no momento deste
  registro.

### Gate de frescor do grafo

O prompt do gate final foi registrado em `2026-08-08 08:09:48 -03:00`. Para a
revisão de publicação, o Graphify do backend foi atualizado novamente após as
alterações e após a integração com `main`:

- backend: manifesto/relatório de `2026-08-08`, 6.853 nós, 23.586 arestas e
  256 comunidades;
- diagnóstico: zero endpoints ausentes ou pendentes, zero self-loops e zero
  arestas duplicadas/colapsadas;
- raiz validada: o diretório `backend/` deste worktree integrado;
- o grafo frontend construído antes das edições permaneceu desatualizado e não
  foi usado como prova do diff final.

O grafo atualizado serviu apenas para contexto estrutural. A validação final das
mudanças continuou sendo feita diretamente no código, nos testes e no build.

Para o segundo ciclo, esse índice deixou de ser válido como evidência: o
`graph.json` era de `2026-08-07 23:01`, anterior às mudanças locais de
`2026-08-08`. Uma atualização foi tentada, mas expirou após aproximadamente
124 s. O estado foi classificado como **DESATUALIZADO/NÃO COMPROVADO** e toda a
análise posterior usou inspeção direta, testes, build e medições de runtime.

## Medições antes e depois

### Frontend — pacote e build de produção

| Métrica | Antes | Depois | Variação |
|---|---:|---:|---:|
| First Load JS `/` | 218 kB | 110 kB | -49,5% |
| First Load JS `/gestao` | 218 kB | 110 kB | -49,5% |
| First Load JS `/admin` | 120 kB | 108 kB | -10,0% |
| Build, tempo total | 93,3 s | 48,2 s | -48,3% |
| Compilação Next | 30,0 s | 19,7 s | -34,3% |

O tempo do build inicial tem confiabilidade menor: havia 245 processos Node já
existentes e duas falhas de cache do webpack. Os tamanhos de pacote e o
Lighthouse são evidências mais estáveis.

### Frontend — Lighthouse, mediana de três execuções

Perfil: mobile simulado, rota pública local, build de produção, três relatórios
JSON válidos.

| Métrica | Antes | Depois | Variação |
|---|---:|---:|---:|
| Performance | 91 | 98 | +7 pontos |
| FCP | 1.215,3 ms | 1.213,8 ms | estável |
| LCP | 3.426,6 ms | 2.294,2 ms | -33,0% |
| TBT | 108,0 ms | 19,5 ms | -81,9% |
| TTI | 3.426,6 ms | 2.462,7 ms | -28,1% |
| CLS | 0 | 0 | estável |
| Bytes transferidos | 365.684 B | 227.594 B | -37,8% |
| Trabalho da main thread | 675,6 ms | 521,7 ms | -22,8% |
| Economia apontada em JS não usado | 137.770 B | 0 B | eliminada na rota |

Resultados finais por execução:

| Run | Nota | FCP | LCP | TBT | TTI |
|---:|---:|---:|---:|---:|---:|
| 1 | 98 | 1.072,1 ms | 2.294,2 ms | 18,0 ms | 2.462,7 ms |
| 2 | 98 | 1.213,8 ms | 2.418,4 ms | 19,5 ms | 2.467,4 ms |
| 3 | 98 | 1.215,4 ms | 2.270,6 ms | 33,0 ms | 2.353,6 ms |

O Lighthouse retornou `EBUSY` ao tentar apagar o perfil temporário do Chrome
depois de cada execução no OneDrive/Windows. Os três relatórios já estavam
gravados e íntegros; o erro foi apenas de cleanup.

### Backend

| Métrica | Antes | Depois | Variação |
|---|---:|---:|---:|
| Testes selecionados | 1.846 | 1.924 | +78 testes |
| Tempo interno da suíte | 289,3 s | 20,2 s | -93,0% |
| Import de `app.main`, mediana de 3 | 1.880 ms | 1.654 ms | -12,0% |
| Processo → primeiro `/health` | 2.211 ms | ~2.072 ms | -6,3% |
| `/health`, mediana de 50 | 1,62 ms | 1,661 ms | estável (+0,041 ms) |
| `/health`, p95 final | — | 2,037 ms | — |

A maior queda da suíte veio da aplicação FastAPI compartilhada por sessão de
testes. Antes, `create_app()` custava aproximadamente 194 ms e era repetido em
cada teste. O cache do pytest também foi desativado porque o `sessionfinish`
ficava preso ao criar `.pytest_cache` no OneDrive; o stack foi confirmado com
faulthandler.

### Runtime autenticado — frontend e APIs em DEV

Perfil: build de produção local em `127.0.0.1:3002`, backend local em
`127.0.0.1:8002`, sessão DEV real e banco Supabase DEV remoto. A métrica
“painel completo” esperou fila, jornada e responsáveis terminarem de carregar;
ela é uma medição de parede controlada no navegador interno, não Web Vitals/RUM
persistente.

| Métrica | Antes | Depois | Variação |
|---|---:|---:|---:|
| Painel completo, mediana | 4.596 ms (5 runs) | 3.263 ms (5 runs finais) | -29,0% |
| `/auth/me`, p50 | 1.300,97 ms | 1.106,21 ms | -15,0% |
| `/dashboard/overview`, p50 | 2.508,35 ms | 1.503,36 ms | -40,1% |
| `/work-queue`, p50 | 1.658,98 ms | 1.431,22 ms | -13,7% |
| `/team/lookup`, p50 | 1.993,91 ms | 1.844,68 ms | -7,5% |

Outras rotas medidas antes da otimização mantiveram o mesmo perfil dominado por
banco remoto: Agenda 2.335 ms, Inbox 2.346 ms e Ganhar 1.953 ms. Contatos não
foi cronometrado com essa conta porque a permissão da rota não estava presente;
o redirecionamento para o painel não foi contado como resultado de Contatos.

O primeiro carregamento após reiniciar o backend ainda exibia penalidade de
abertura fria de conexões. O gate final moveu uma única abertura de conexão para
o `lifespan`, antes de o backend aceitar tráfego, e eliminou duas consultas
redundantes de `/team/lookup`.

| Gate final | Antes do lote | Depois | Variação |
|---|---:|---:|---:|
| Painel após restart, mediana de 3 | 6.775 ms | 4.020 ms | -40,7% |
| `/auth/me` após restart, p50 | 3.513 ms | 1.159 ms | -67,0% |
| Painel aquecido, mediana de 5 | 3.488 ms | 2.869 ms | -17,7% |
| `/team/lookup` aquecido, p50 | 1.858 ms | 1.474 ms | -20,7% |

As três partidas finais levaram aproximadamente 5,55 s, 8,34 s e 6,09 s do
processo até `/health`; a mediana foi 6,09 s. Esse custo agora acontece durante
a readiness e ficou abaixo do `start_period` de 20 s do Compose. Depois do
`/health`, os três painéis ficaram completos em 4,02 s, 4,20 s e 3,94 s. As
cinco amostras aquecidas tiveram mediana de 2,87 s. Todas terminaram
autenticadas, sem 500/429 e sem warning/error no navegador. Uma amostra aquecida
de 7,23 s foi mantida como outlier; ela não alterou a mediana e reforça que o
gate de staging deve observar cauda, não apenas p50.

Essas medições autenticadas foram feitas no SHA `a66aa71`, imediatamente antes
das integrações finais com a `main`. Os merges `2ed1e19` e `19fb55a`
incorporaram cache, preload e o ajuste de posição do acesso administrativo,
passaram nos testes aplicáveis, mas ainda devem repetir o smoke/RUM autenticado
no SHA publicado; os números acima não foram retroativamente atribuídos aos
merges.

### PostgreSQL DEV — latência e índice outbound

Medição segura de conexão e `SELECT 1`, sem alterar dados:

- conexão: 1.960,94 ms na primeira abertura e 931,58–962,05 ms nas seguintes;
- query simples: p50 159,44 ms, p95 320,80 ms, máximo 321,35 ms;
- conclusão: a distância entre backend e banco é o maior custo residual das
  APIs autenticadas, multiplicado por cada round-trip SQL sequencial.

A migration `20260808_011500_messages_outbound_provider_id_uidx.sql` foi
aplicada **somente em DEV**, após preflight confirmar zero duplicatas e nenhum
índice anterior. O índice foi verificado em `pg_index` como
`valid/ready/live/unique`, com definição e predicado esperados, e registrado em
`schema_migrations`. Um `EXPLAIN (ANALYZE, BUFFERS)` seguro confirmou
`Index Only Scan`, execução de 0,05 ms, dois blocos em cache e zero leituras.

Em PostgreSQL descartável com 500 mil linhas, a mesma consulta caiu de p50
22,965 ms sem índice para 0,797 ms com índice, aproximadamente 28,8 vezes mais
rápida. A construção concorrente levou 0,554 s e ocupou cerca de 11 MiB nesse
volume sintético.

Nota operacional: usar `set_session(readonly=True)` através do pooler em modo
transaction propagou `default_transaction_read_only=on` para sessões
reutilizadas. Nenhuma mutação ocorreu durante a tentativa; oito sessões
sequenciais e oito paralelas foram explicitamente restauradas e verificadas
como read-write. Esse método não deve ser reutilizado nesse pooler.

## Causas confirmadas e correções executadas

### 1. JavaScript monolítico e cadeia crítica de autenticação

**Causa:** shell, login e 24 telas eram importados estaticamente. Providers de
autenticação também atingiam páginas públicas, e a interface autenticada só
começava a baixar depois de `/auth/me`.

**Correção:**

- remoção de `force-dynamic` global;
- providers apenas nas superfícies que precisam deles;
- remoção da dependência Clerk não usada;
- `next/dynamic` para shells, login, console e as 24 telas;
- preload do shell e de exatamente uma tela relevante em paralelo a `/auth/me`,
  tanto em sessão persistida quanto após login novo;
- preload equivalente do console admin.

### 2. Contatos sem limite de dados/DOM

**Causa:** o frontend carregava todas as páginas de 200 itens em sequência e
renderizava a coleção inteira. Filtros locais distorciam total/paginação.

**Correção:**

- paginação server-side de 50 itens;
- filtros aplicados no SQL antes de `count/offset`;
- ordenação estável com desempate por ID;
- consulta de líderes limitada aos IDs da página;
- deep-link carrega detalhe sob demanda, incluindo estado arquivado;
- proteção contra respostas fora de ordem e contra linhas antigas sob filtros
  novos;
- mutations recarregam a página correta para evitar buracos por offset;
- helper legado continua agregando todas as páginas para consumidores que ainda
  dependem desse contrato;
- células são cacheadas em vez de recarregadas a cada página/filtro.

### 3. Polling e renderização do Inbox

**Causa:** polls podiam se sobrepor e, em caso de request pendurado, bloquear
atualizações indefinidamente. Atualização após envio podia ser perdida.

**Correção:** single-flight por recurso, trailing refresh após envio,
`AbortController`, timeout de 12 s (menor que o poll de 15 s), cancelamento na
troca de conversa/unmount e propagação de `signal` até as APIs.

### 4. Upload base64 e pressão de memória

**Causa:** arquivo inteiro virava base64/JSON sem fronteira confiável de tamanho;
validação Pydantic acontece depois de o parser já ter alocado o body.

**Correção:** limite de 16 MiB no frontend e no payload decodificado, mais
middleware ASGI pré-parser que rejeita `Content-Length` excedido e também conta
chunks quando o header está ausente. A resposta é 413. O segundo ciclo ampliou
a proteção para um teto global de 2 MiB nos métodos com body, mantendo políticas
explícitas de 1 MiB para webhook e aproximadamente 22,4 MiB para mídia. Upload
de logo de 1,5 MiB e rotas sem body continuam válidos.

### 5. Webhook/Redis e perda de trabalho

**Causa:** Redis síncrono no endpoint async, cliente/pool por request, ausência
de limites e `BRPOP` removendo o item antes de concluir.

**Correção:** queue cacheada, operação síncrona movida para threadpool, body de
webhook limitado a 1 MiB, timeouts/pool Redis e 503 retryable. O worker agora
usa lista privada por processo, lease, heartbeat, recovery apenas de worker
expirado, `BRPOPLPUSH`, ACK explícito e transição retry/dead-letter atômica via
Lua.

### 6. Concorrência e idempotência do worker

**Causa:** restart, crash ou perda de lease podia duplicar mídia/trabalho; duas
cópias do mesmo claim podiam atravessar o guard Redis.

**Correção:**

- `claim_id` preservado em retry/recovery;
- CAS de ownership e marcadores `processing/done`;
- prova atômica de posse combinando lease viva e presença do item na lista
  privada, revalidada antes/depois da trava, do upload e do commit;
- worker que perdeu ou não consegue comprovar posse interrompe o handler e deixa
  o recovery assumir, inclusive quando o dono antigo continua vivo;
- liberação do marcador de retry também exige o dono atual, impedindo o worker
  antigo de apagar o estado do recuperador;
- trava transacional `pg_advisory_xact_lock` por
  `(igreja_id, provider_message_id)` antes de contato/mídia/commit;
- consulta sob a trava inclui `direcao`, permitindo os índices parciais;
- mídia inbound usa caminho estável
  `{igreja}/provider/{sha256(provider_message_id)}.{ext}`, independente de uma
  conversa provisória;
- índice único outbound foi refletido no modelo e preparado em migration
  separada; foi aplicado e validado somente em DEV, não em produção.

### 7. Clientes HTTP recriados em caminhos quentes

**Causa:** Evolution criava conexão HTTP por envio/download.

**Correção:** `EvolutionClient` ganhou pool lazy e lifecycle determinístico. Os
workers long-lived fecham apenas clientes próprios. O worker inbound injeta uma
única instância compartilhada nos caminhos de resposta do agente e download de
mídia.

### 8. N+1 em saúde de células

**Causa:** aproximadamente `1 + células × até 32 consultas`, reuniões carregadas
e ordenadas em Python, além de materialização de membros/presenças/visitantes só
para contagem.

**Correção:** seis consultas fixas: células + cinco lotes. Contagens usam
`GROUP BY`, existência usa `DISTINCT` e as dez reuniões válidas mais recentes
são limitadas no SQL com `row_number() over(partition by celula_id)`.

### 9. Autorização, LangGraph e observabilidade

- removidas cargas redundantes de papéis/permissões antes das rotas;
- `MemorySaver` ilimitado foi removido; o grafo fica stateless e emite warning
  se uma URL de checkpoint estiver configurada sem saver durável;
- respostas normais e 500 agora carregam `X-Request-ID` e `Server-Timing`;
- logs usam rota normalizada e duração, sem criar cardinalidade por URL real.

### 10. Login, autorização e painel no runtime DEV

**Causas confirmadas:**

- Redis indisponível era consultado duas vezes no login, com aproximadamente
  4,1 s por tentativa antes do fail-open;
- o frontend mostrava a mesma mensagem para senha errada e falha 500 do banco;
- login fresco fazia `/auth/login` e depois `/auth/me` serialmente;
- `/auth/me` executava seis SQL sequenciais e `/dashboard/overview`, sete;
- clientes HTTP do Clerk eram recriados e falha/timeout do provedor era
  classificada como credencial inválida;
- falhas transitórias de sessão apagavam a experiência autenticada ou podiam
  deixar a interface pendurada sem prazo.

**Correções:**

- Redis com conexão/leitura de 0,5 s, sem retry interno; fail-open preservado;
- 401/422, 403, 429, rede e 5xx exibem estados diferentes;
- login devolve token + perfil completo e o frontend valida o contrato antes de
  persistir; durante rollout misto, a resposta legada usa `/auth/me` como
  fallback seguro;
- falha transitória preserva token e mostra tela de indisponibilidade com retry;
- 401, 403 e demais recusas 4xx definitivas encerram a sessão e permitem trocar
  de conta; somente rede, timeout, 429 e 5xx permanecem recuperáveis;
- autenticação operacional e administrativa têm deadline de 20 s, superior ao
  orçamento nominal do Clerk + Redis + banco frio; o Inbox permanece em 12 s;
- Clerk usa pool HTTP por lifespan, fecha deterministicamente e distingue senha
  recusada de indisponibilidade 503;
- o pool SQLAlchemy agora limita espera por checkout a 5 s e o psycopg2 limita
  abertura de conexão a 5 s;
- `/auth/me` usa `joinedload` de papéis e caiu de seis para cinco SQL, mantendo
  integralmente o contexto RLS;
- `/dashboard/overview` usa agregações e caiu de sete para duas consultas no
  escopo da igreja e três no escopo de líder;
- o `lifespan` aquece exatamente uma conexão com `SELECT 1`, encerra a
  transação e devolve o checkout ao pool antes do `/health`; falhas continuam
  best-effort e geram apenas warning sanitizado;
- `/team/lookup` usa `joinedload` dos papéis da página e caiu de quatro para
  duas consultas próprias, sem varrer novamente todos os papéis do tenant.

### 11. Testes e CI

- aplicação FastAPI compartilhada por sessão, com overrides limpos por teste;
- novos testes de limites, corrida, paginação, query count, pooling,
  observabilidade e code-splitting;
- workflows com concorrência cancelável, timeouts e duração dos testes;
- três workflows YAML revalidados com parser.

## Validação final

- Backend integrado offline: **1.949/1.949 PASS**, 40,9 s de parede; os 135
  testes `rls_integration` foram executados separadamente em PostgreSQL real
  descartável e deram **135/135 PASS**.
- Frontend integrado: **55 arquivos, 490/490 PASS**; 26,6 s de parede
  (22,17 s internos).
- TypeScript: **PASS** (`--incremental false`).
- ESLint direto, sem cache e `--max-warnings 0`: **PASS**.
- Build Next de produção limpo e integrado: **PASS**, 48,2 s; compilação
  19,7 s; First Load JS 110 kB em `/`, 110 kB em `/gestao` e 108 kB em
  `/admin`.
- YAML: **3/3 PASS**.
- `git diff --check`: **PASS**; somente avisos esperados de conversão LF/CRLF.
- Revisão independente do worker: **59 testes focados PASS, 7 SKIP** e nenhum
  P0–P2 restante no split-brain/ownership.
- Correções finais de auth/admin: **41/41 testes focados PASS**, incluindo
  providers sob 401, 403, 4xx definitivo e falha transitória.
- Re-revisão independente de auth, dashboard, limites de body, Clerk, pool e
  worker: **nenhum P0–P2 remanescente no escopo alterado**.
- Revisão independente após integrar `main`: **222/222 testes focados PASS** e
  nenhuma perda semântica nos quatro arquivos sobrepostos.
- Gate final após warmup e `/team/lookup`: **1.969 PASS, 135 SKIP** na suíte
  offline completa; em seguida, os **135/135 testes RLS passaram** contra
  PostgreSQL 16 local descartável, sem skips.
- Testes focados do último lote: **44/44 PASS**; revisão independente não
  encontrou P0–P2; `git diff --check` permaneceu em **PASS**.
- Integração final com a `main`: backend **1.972 PASS, 135 SKIP**;
  frontend **58 arquivos, 509/509 PASS**; TypeScript, ESLint direto sem cache e
  build de produção em cópia limpa: **PASS**. O build manteve First Load JS de
  110 kB em `/`, 110 kB em `/gestao` e 108 kB em `/admin`.
- Delta final da `main` até `4755e5f`: somente posição do acesso Admin na
  navegação; `Sidebar` + `AppShell` **10/10 PASS** e TypeScript **PASS**.
- A revisão do merge encontrou duas corridas P2 — resposta antiga repovoando o
  cache e timeout inicial do Inbox aparecendo como lista vazia. Ambas foram
  corrigidas, receberam regressões determinísticas e a re-revisão deu
  **20/20 PASS, nenhum P0–P2 remanescente**.

## Gates executados e pendências

### Gate 1 — banco DEV: PASS; STAGING/PROD: não executado

Migration preparada e aplicada somente em DEV:

`backend/migrations/20260808_011500_messages_outbound_provider_id_uidx.sql`

Passos executados:

1. preflight de duplicatas outbound: zero grupos duplicados;
2. inspeção do catálogo: nenhum índice outbound anterior;
3. execução do único comando `CREATE UNIQUE INDEX CONCURRENTLY` fora de
   `BEGIN/COMMIT`; ele evita bloquear as escritas durante a construção;
4. validação em `pg_index`: `valid/ready/live/unique`, definição correta e
   registro em `schema_migrations`;
5. `EXPLAIN (ANALYZE, BUFFERS)`: `Index Only Scan`, 0,05 ms;
6. suíte RLS em PostgreSQL descartável real: **135/135 PASS**.

Produção continua intocada. A aplicação em STAGING/PROD exige novo preflight,
backup/observabilidade, janela controlada e autorização separada.

### Gate 2 — parcial

Executado:

- Redis local real para o fluxo de login e validação do fail-open;
- PostgreSQL DEV real para latência, login, painel e `EXPLAIN` do índice;
- PostgreSQL descartável com 500 mil linhas para ganho do índice;
- 135 testes RLS em PostgreSQL descartável real;
- navegação autenticada controlada no dashboard, Agenda, Inbox e Ganhar.

Ainda faltam:

- `EXPLAIN (ANALYZE, BUFFERS)` das consultas de contatos, células, autorização
  e saúde de células em volume representativo;
- teste de concorrência com múltiplos workers usando Redis e Postgres reais;
- validação de pool/saturação e memória sob upload concorrente;
- RUM persistente em usuários/dispositivos/redes reais e métricas de p75.

### Dívidas arquiteturais fora deste ciclo

- O backend e o banco DEV estão em regiões/caminhos de rede com query simples
  em p50 de 159 ms. A maior oportunidade restante é aproximar o runtime do
  banco e avaliar conexão direta, pooler de sessão ou pooler dedicado conforme
  a topologia real; trocar a URL sem esse teste não é uma correção de código.
- O pool agora limita checkout e conexão, mas não foi imposto um
  `statement_timeout` global. Em Supavisor transaction mode, configuração de
  sessão não é segura/suportada; os próximos limites devem ser definidos por
  transação/endpoint após observar consultas legítimas lentas.
- Seis consumidores legados de Contatos ainda usam o helper que agrega todas as
  páginas sequencialmente. A tela principal está paginada, mas seletores e
  consolidação continuam com custo `O(N/200)` até receberem busca/paginação
  própria.
- O fail-open do Redis está limitado a 0,5 s sem retry, porém ainda não há
  circuit breaker/log sampling; uma indisponibilidade prolongada pode gerar
  custo e ruído repetidos em cada login.
- Algumas operações de conversa ainda mantêm `FOR UPDATE` enquanto fazem HTTP
  ou Storage. A correção segura pede outbox/estado intermediário e idempotência,
  não uma troca local de linhas.
- Busca de telefone ainda usa `regexp_replace/right` por linha. A solução é uma
  coluna canônica indexada, migration e `EXPLAIN` antes/depois.
- A janela já existente entre commit inbound e resposta do agente não oferece
  exatamente-uma-vez. Fechá-la exige outbox durável.
- Se o produto precisar memória conversacional persistente no LangGraph, deve
  ser instalado/configurado um saver externo durável; o estado atual é
  intencionalmente stateless para não crescer RSS sem limite.
- Uma credencial compartilhada de usuário DEV apareceu em captura de
  diagnóstico. A rotação deve ser feita como ação de segurança separada, sem
  reutilizar nem registrar o valor anterior.

## Próximos passos recomendados

1. Publicar a branch integrada, atualizar o PR draft existente e repetir os
   checks no SHA exato publicado.
2. Executar `EXPLAIN` e carga representativa de Contatos, células e autorização;
   migrar os seis consumidores legados para busca/paginação própria.
3. Testar múltiplos workers com Redis + PostgreSQL reais e upload concorrente,
   medindo p95, memória, pool e recuperação de lease.
4. Aproximar backend e banco em um ambiente de staging e repetir as medições;
   depois escolher o modo de conexão Supabase adequado à topologia.
5. Instrumentar RUM persistente e adotar budgets p75/p95 de login, painel e
   rotas críticas. A medição do navegador interno é laboratório, não RUM.
6. Aplicar a migration em staging, fazer canário e só então avaliar produção;
   commit, PR, staging, deploy e produção continuam gates separados.
