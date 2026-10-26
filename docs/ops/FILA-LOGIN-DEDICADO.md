# Login dedicado da fila normal (`queue_worker_runtime`)

Candidata local (branch `feat/queue-worker-runtime-final-20261026`, migration
`20261030_160000_queue_worker_runtime_identity.sql`). Testada só em PostgreSQL
17.6 sintético com conexão direta. Nada aplicado em produção; URL, versão do
PostgreSQL, memberships reais de `authenticated`, dono das funções e modo do
pooler de produção: **não verificados**. O padrão continua `legacy`.

## O que muda e o que não muda

- `QUEUE_WORKER_DATABASE_MODE` aceita exatamente `legacy` (padrão) ou
  `dedicated`. Qualquer outro valor (vazio, maiúsculas, espaços) impede o
  queue-worker de iniciar. Só o queue-worker lê essas duas variáveis.
- `legacy`: a fila usa a sessão principal e o lookup ORM originais, sem
  depender da migration nem ler `QUEUE_WORKER_DATABASE_URL`. É o piloto atual.
- `dedicated`: toda transação da fila normal (ingestão, turno, fences,
  retomada privada, CAS/ownership/renovação de envio, lease do agente) usa só
  `QUEUE_WORKER_DATABASE_URL`. Sem URL válida o processo não inicia; nunca cai em
  `DATABASE_URL`. A URL sozinha não ativa o modo.
- Não mudam: D2A/`agent_runtime_session` e governança (pausados), API, cron,
  broadcast, logins privados (`private_send_runtime`, `private_storage_runtime`,
  `private_summary_runtime`), policies e grants de domínio, gates e listas.

## Identidade

O papel é criado NOLOGIN NOINHERIT NOSUPERUSER NOBYPASSRLS NOCREATEDB
NOCREATEROLE NOREPLICATION, com **uma** membership: `authenticated` WITH
INHERIT FALSE, SET TRUE, sem ADMIN. Antes do seam de tenant o login não tem
privilégio em nenhuma tabela; só `queue_resolve_instance(text)` descobre a
igreja da instância (busca exata, sem normalizar nem limitar tamanho, no máximo
uma linha `igreja_id`/`numero`, só o próprio login, papel `none` e sem GUC de
igreja). Depois, o seam existente (`tenant_session`) baixa cada transação para
`authenticated` com a igreja, como hoje.

Provas, sem `SET ROLE` substituindo o login:

- conexão nova: `search_path` de sessão `pg_catalog, public, pg_temp`;
- todo checkout do pool, inclusive a conexão crua do lease: login, atributos
  vivos dos **dois** papéis, membership exata, nenhum membro do login capaz de
  SET ou INHERIT (no PostgreSQL 16+ o criador não superusuário, como o
  `postgres` do Supabase, recebe ADMIN com INHERIT/SET FALSE; na configuração
  conferida ele não tem SET/INHERIT, mas administradores podem alterar
  permissões e ficam fora da ameaça coberta), nada de que o login seja dono
  nem ACL direta dele no banco atual ou em objetos compartilhados além de
  USAGE em `public` e EXECUTE nas duas funções, ambos sem GRANT OPTION,
  `authenticated` sem memberships e sem tabela própria sem FORCE RLS, sem
  role/igreja/claims JWT (`request.jwt.claims` e `request.jwt.claim.sub`),
  path fixo, `row_security=on` e nenhuma relação temporária. Senão a conexão é
  descartada e outra é aberta;
- todo BEGIN, antes do seam: o mesmo estado de login;
- depois do seam (inclusive savepoints): efetivo `authenticated` com exatamente
  a igreja fixada na sessão. Trocar de igreja na mesma sessão continua proibido.
  A ordem real (prova de login → seam → prova de escopo) é afirmada em PG.
  A fila nunca escopa com ator; se escopasse, a claim JWT gravada pelo seam
  é recusada (falha fechada).

A função SQL `queue_worker_runtime_session()` repete as verificações de papéis
e a ACL direta do login ao vivo; drift recusa até conexão já aberta. A
verificação de ACL olha só concessões **diretas** ao login (via `pg_shdepend`
e `aclexplode`): privilégios recebidos por PUBLIC, como EXECUTE padrão de
funções antigas, ficam fora e não se alega privilégio mínimo absoluto além do
que os testes provam. A migration valida o
`authenticated` embutido (sem SUPERUSER/BYPASSRLS/CREATEROLE/CREATEDB/
REPLICATION, sem memberships, sem tabela própria sem FORCE) e recusa, sem
reparar. Papel preexistente só é aceito NOLOGIN, com atributos seguros, sem
membro capaz de usá-lo, no máximo a membership segura já criada a partir de outro banco
(membership é global no cluster) e sem objetos ou privilégios no banco atual.

`whatsapp_connections` não tem FORCE RLS: o dono da tabela lê sem BYPASSRLS, e
`queue_resolve_instance` não entra nos contratos de dono do preflight. No teste
de completude do catálogo ele é uma exclusão explícita, com a condição de que o
dono da função seja dono de `whatsapp_connections` ou tenha BYPASSRLS. Com outro
dono sem BYPASSRLS, mesmo com SELECT e EXECUTE explícitos, a chamada falha fechada
(42501 de RLS), como prova `test_queue_worker_runtime_pg`. O login
`queue_worker_runtime` continua sem BYPASSRLS. O dono real em PROD não foi
verificado.

## Jev

O login não lê `platform_jev_settings` (nenhum grant, nenhuma chave). No turno
privilegiado com Tier A listado, configuração ilegível agora vira o mesmo
handoff de gate fechado do ramo público (resposta suprimida, conversa `humano`,
sem transporte Jev), em vez de abortar com `ia_reservada`. Gates e release
continuam `None`; nenhum fallback para a chave do ambiente.

## Pré-requisitos antes de qualquer release

1. Versão do PostgreSQL de produção. Suíte: 17.6. Conferência manual local
   (não CI, não PROD): imagens Supabase 15.8.1.085 e 17.6.1.171 do cache,
   migration aplicada pelo `postgres` não superusuário via `migrate.py`, probe e
   lookup reais com LOGIN sintético. PostgreSQL 15 não tem opções de membership
   (vale o NOINHERIT do login); por isso nele qualquer membro do login, mesmo
   só com ADMIN, é recusado (falha fechada). Um `createrole_self_grant` com `set`/`inherit`
   faria o criador poder usar o papel: o modo dedicado recusa (falha fechada).
2. Membership é global no cluster: aplicar a migration em todos os bancos
   que a recebem **antes** de provisionar o LOGIN (papel preexistente com
   LOGIN é recusado).
3. Leitura somente, no banco alvo: atributos e memberships de `authenticated`
   e tabelas de que ele é dono. A migration recusa estado inseguro; não corrigir
   o papel embutido para fazê-la passar. Conferir também o CONNECT no banco: a
   guarda recusa `GRANT CONNECT` direto ao `queue_worker_runtime`; se PUBLIC não
   tiver CONNECT, o modo dedicado falha na conexão (falha fechada). Não reabrir
   PUBLIC nem alterar a ACL automaticamente: mudança exige revisão e decisão.
4. O usuário que aplica a migration precisa poder conceder `authenticated`
   (superusuário ou ADMIN OPTION). Não verificado no Supabase.
5. Modo da conexão: o lease do agente é advisory lock **de sessão**, mantido
   numa conexão ociosa durante o envio HTTP. Exige conexão direta ou pooler em
   modo sessão. A porta 6543 do pooler compartilhado do Supabase (modo
   transação) é recusada; outros proxies não são adivinhados e uma URL aceita
   não prova o modo. O operador verifica o modo antes do release.
6. `env_file` é compartilhado por API, queue, cron e broadcast: a separação de
   URL por processo **não** está entregue. Entregar a URL só ao queue-worker.

## Procedimento nominal (não executado)

1. Backup prévio; aplicar a migration com `backend/scripts/migrate.py` (o
   código em `legacy` não depende dela).
2. Conferir: papel NOLOGIN sem senha, uma membership
   (`authenticated`, admin/inherit falsos, set verdadeiro), duas funções com
   EXECUTE só para o papel.
3. Provisionar por decisão nominal: LOGIN e credencial fora do repositório.
4. Conter o queue-worker (procedimento do lote), configurar só nele
   `QUEUE_WORKER_DATABASE_MODE=dedicated` e `QUEUE_WORKER_DATABASE_URL`
   (direta ou pooler em modo sessão), reiniciar nominalmente só o queue-worker.
   Enquanto ele estiver parado, o webhook continua enfileirando no Redis.
5. Verificar sem dados reais em artefatos: backends do queue-worker com
   `usename = 'queue_worker_runtime'` e heartbeat ativo. Falha de identidade
   aparece como erro de checkout/BEGIN e a fila não processa (falha fechada).

## Rollback

1. Operacional: voltar o queue-worker a `QUEUE_WORKER_DATABASE_MODE=legacy`
   (ou contê-lo) e reiniciar só ele.
2. Revogar a credencial e voltar o papel a NOLOGIN por decisão nominal.
3. Só então, se necessário, o rollback comentado da migration: recusa LOGIN
   provisionado, não toca dados de domínio, para com erro se o papel ainda
   tiver objetos ou privilégios no banco atual (drift local) e só remove o
   papel (e sua membership) quando nenhum outro banco depende dele; caso
   contrário avisa por NOTICE que o manteve. Reaplicar só por `migrate.py`.

## Limites declarados

O login principal continua capaz de tudo (BYPASSRLS). Worker comprometido com
esta credencial ainda escolhe a GUC de igreja e pode definir claims JWT
transação-local, como o principal já pode; o isolamento entre igrejas segue
pela disciplina do seam. Dono/superusuário/operadores com CREATEROLE ficam fora
do escopo. `TEMP` via PUBLIC não é revogado: tratado por path com `pg_temp`
por último e descarte de conexão. A varredura negativa cobre o schema `public`
do PG sintético, não `auth`/`storage`/`extensions` do Supabase. Mídia/áudio,
V1a/V1b, Tier A público, exclusão/conhecimento/agenda/Enviar/CD/UV/células pelo
WhatsApp e a fila Redis real não foram exercitados no modo dedicado.
