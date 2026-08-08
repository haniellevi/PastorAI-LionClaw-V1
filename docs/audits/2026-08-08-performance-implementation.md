# Implementação do plano de desempenho — 2026-08-08

## Resultado executivo

O primeiro ciclo de correções de desempenho foi implementado em um worktree
isolado, medido antes/depois e revisado por uma segunda análise independente.
O parecer final da revisão foi: **nenhum achado P0–P2 restante no diff**.

Principais resultados locais:

- First Load JS de `/`: **218 kB → 108 kB** (`-50,5%`).
- Lighthouse mobile simulado: **91 → 98**.
- LCP mediano: **3,43 s → 2,29 s** (`-33,0%`).
- TBT mediano: **108 ms → 19,5 ms** (`-81,9%`).
- Transferência inicial: **365,7 kB → 227,6 kB** (`-37,8%`).
- Suíte backend: **289,3 s → 20,2 s** (`-93,0%`), mesmo crescendo de
  1.846 para 1.924 testes selecionados.

Esses números são de laboratório local. Não equivalem a RUM de usuários reais,
nem provam o comportamento de banco/Redis sob carga de produção.

## Isolamento e fonte do código

- Checkout principal encontrado em `9121abb`, detached e com alterações locais:
  **não foi modificado**.
- Worktree de implementação:
  `.codex/worktrees/performance-plan`.
- Branch: `codex/performance-plan`.
- Base: `deb95a8cfebc154168bcc13a2bd304aa34260bcf` (`origin/main` no início).
- Integração final: `origin/main` em
  `602761c25bfd23d779704c34a11b88a93b80ea7e`, incorporada por merge normal.
- Estado operacional: mudanças versionadas nesta branch para revisão em PR
  rascunho; **nenhuma migration foi aplicada e não houve merge da PR nem
  deploy**.

### Gate de frescor do grafo

O prompt do gate final foi registrado em `2026-08-08 08:09:48 -03:00`. Para a
revisão de publicação, o Graphify do backend foi atualizado novamente após as
alterações e após a integração com `main`:

- backend: manifesto/relatório de `2026-08-08`, 6.852 nós, 23.585 arestas e
  261 comunidades;
- diagnóstico: zero endpoints ausentes ou pendentes, zero self-loops e zero
  arestas duplicadas/colapsadas;
- raiz validada: o diretório `backend/` deste worktree integrado;
- o grafo frontend construído antes das edições permaneceu desatualizado e não
  foi usado como prova do diff final.

O grafo atualizado serviu apenas para contexto estrutural. A validação final das
mudanças continuou sendo feita diretamente no código, nos testes e no build.

## Medições antes e depois

### Frontend — pacote e build de produção

| Métrica | Antes | Depois | Variação |
|---|---:|---:|---:|
| First Load JS `/` | 218 kB | 108 kB | -50,5% |
| First Load JS `/gestao` | 218 kB | 109 kB | -50,0% |
| First Load JS `/admin` | 120 kB | 107 kB | -10,8% |
| Build, tempo total | 93,3 s | 45,2 s | -51,6% |
| Compilação Next | 30,0 s | 15,8 s | -47,3% |

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
chunks quando o header está ausente. A resposta é 413 e o middleware só atua na
rota de envio de mídia.

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
- trava transacional `pg_advisory_xact_lock` por
  `(igreja_id, provider_message_id)` antes de contato/mídia/commit;
- consulta sob a trava inclui `direcao`, permitindo os índices parciais;
- mídia inbound usa caminho estável
  `{igreja}/provider/{sha256(provider_message_id)}.{ext}`, independente de uma
  conversa provisória;
- índice único outbound foi refletido no modelo e preparado em migration
  separada; **não foi aplicado a banco algum**.

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

### 10. Testes e CI

- aplicação FastAPI compartilhada por sessão, com overrides limpos por teste;
- novos testes de limites, corrida, paginação, query count, pooling,
  observabilidade e code-splitting;
- workflows com concorrência cancelável, timeouts e duração dos testes;
- três workflows YAML revalidados com parser.

## Validação final

- Backend integrado: **1.924/1.924 PASS**, 135 testes `rls_integration` em skip
  por exigirem Postgres real; 23,5 s de parede (20,2 s internos).
- Frontend integrado: **52 arquivos, 455/455 PASS**; 25,7 s de parede
  (22,21 s internos).
- TypeScript: **PASS** (`--incremental false`).
- ESLint direto, sem cache e `--max-warnings 0`: **PASS**.
- Build Next de produção limpo e integrado: **PASS**, 45,2 s; compilação
  15,8 s.
- YAML: **3/3 PASS**.
- `git diff --check`: **PASS**; somente avisos esperados de conversão LF/CRLF.
- Revisão independente: **95 testes backend focados, 6 testes frontend de
  performance, TypeScript e diff-check PASS; zero P0–P2 no diff final**.
- Revisão independente após integrar `main`: **222/222 testes focados PASS** e
  nenhuma perda semântica nos quatro arquivos sobrepostos.

## Gates e riscos ainda não executados

### Gate 1 — banco DEV/STAGING

Migration preparada:

`backend/migrations/20260808_011500_messages_outbound_provider_id_uidx.sql`

Antes de aplicar:

1. confirmar que o índice inbound histórico está presente;
2. rodar o preflight de duplicatas outbound documentado no próprio arquivo;
3. revisar/limpar qualquer duplicata com aprovação humana;
4. executar o único comando `CREATE UNIQUE INDEX CONCURRENTLY` fora de
   `BEGIN/COMMIT`; ele evita bloquear as escritas durante a construção;
5. validar em `pg_index` que o índice está `valid/ready/live/unique` e conferir
   `pg_get_indexdef`; uma falha pode deixar índice `INVALID` e exige recuperação
   manual antes de reaplicar;
6. aplicar primeiro em DEV/STAGING e então executar os 135 testes RLS em
   Postgres descartável/real.

Nenhuma dessas ações foi feita nesta execução.

### Gate 2 — carga e banco real

Ainda faltam:

- `EXPLAIN (ANALYZE, BUFFERS)` das consultas de contatos, células, autorização
  e dedupe em um volume representativo;
- teste com múltiplos workers, Redis e Postgres reais;
- validação de pool/saturação e memória sob upload concorrente;
- RUM autenticado em dispositivo/rede real e métricas de p75.

### Dívidas arquiteturais fora deste ciclo

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

## Próximos passos recomendados

1. Acompanhar os checks do PR rascunho, incluindo o Postgres descartável do
   workflow RLS, e repetir a revisão no SHA publicado.
2. Medir o Gate 2 com Redis/Postgres e dados representativos; definir budgets
   de p75/p95.
3. Executar o Gate 1 em DEV/STAGING somente com aprovação explícita.
4. Fazer canário em staging; deploy/produção continuam como gates separados.
