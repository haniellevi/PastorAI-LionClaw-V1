# OAUTH-CALENDAR-V1 — aceite de riscos e decisão de rollout

**Data:** 2026-07-31 · **Base:** `badfa91` · **Conversa:** `OAUTH-STATE-THREATMODEL-1`
**Status:** aceites registrados pelo dono; implementação neste PR (draft).

## Achado que originou a mudança

`GET /calendar/callback` era público e **não lia sessão nenhuma**: gravava
`calendar_sync` apenas com base no `igreja_id` carregado no `state` JWT. Isso
permitia account-linking CSRF em duas direções:

- **Cross-tenant** — um admin induz alguém de outra igreja a consentir, e o
  refresh token da vítima acaba no tenant do atacante.
- **Intra-tenant** — um admin A1 induz o admin A2 da **mesma** igreja a vincular
  a **agenda pessoal** de A2, que A1 depois lê pelo tenant. Comparar apenas
  tenant + papel **não** fecha este caso.

## Desenho implementado

`state` opaco de 256 bits · tabela `calendar_oauth_flows` com `state_hash` e
`flow_secret_hash` **separados** · PKCE S256 com `code_verifier` cifrado apenas
no servidor · callback público que **só estaciona** o `code` · `POST
/calendar/connect/finish` autenticado que compara `app_user_id` + `igreja_id`,
consome o fluxo atomicamente e só então troca o código · purge no `cron_worker`.

Dois segredos distintos porque eles têm exposições diferentes: o `state` viaja
ao Google e cai no access log; o `flowSecret` fica em `sessionStorage`
(particionado por origem) e nunca sai das origens do painel.

## Retomada por identidade (OAUTH-PWA-IOS-G3)

**Decisão do dono, 2026-07-31: PWA iOS instalada é superfície suportada no V1.**
G3 passa a ser bloqueador de merge.

O desenho acima amarrava a conclusão à continuidade do `sessionStorage`, e numa
PWA iOS essa continuidade não existe:

- sair para `accounts.google.com` é navegação **fora do `scope`** do manifest
  (`"scope": "/"`), então o iOS entrega o link ao Safari. O retorno cai num jar
  de storage **separado** do da PWA instalada — `sessionStorage` vazio;
- mesmo quando o retorno reabre a PWA, o iOS pode tê-la encerrado em segundo
  plano e relançado com `sessionStorage` zerado;
- no caso mais comum a PWA nem é encerrada: fica viva em segundo plano com o
  botão preso em "Abrindo o Google…", e o consentimento conclui noutro app.

**Correção:** `POST /calendar/connect/finish` passa a aceitar `flowSecret`
**opcional**. Sem ele, a linha é encontrada por `app_user_id` + `igreja_id` do
Bearer, com `consumed_at IS NULL`, `code_encrypted IS NOT NULL`,
`expires_at > now()`, `ORDER BY criado_em DESC LIMIT 1 FOR UPDATE`.

Por que o modelo de ameaça continua o mesmo:

| Invariante | Como se sustenta sem o `flowSecret` |
|---|---|
| Vínculo com `app_user_id` + `igreja_id` | O `WHERE` **é** a autorização, e as duas colunas vêm do Bearer. O caminho do `flowSecret` acha a linha pelo hash e **compara exatamente as mesmas colunas** logo depois: tudo que a retomada aceita, aquele caminho já aceitaria. |
| Conclusão por usuário/tenant diferente | Impossível por construção: a busca nunca sai das linhas do próprio chamador. Fluxo alheio não é lido nem queimado. |
| TTL, uso único, replay | Inalterados — mesmo `_burn`, mesmo `FOR UPDATE`, mesmo `consumed_at`. Uma segunda retomada não encontra a linha consumida. |
| Callback público sem troca | Inalterado: continua só estacionando. |
| Nada sensível em URL/log | Nada novo trafega. Ao contrário — a retomada não manda segredo nenhum. |
| Fail-closed, sem fallback legado | Sem fluxo próprio estacionado, a resposta é 202 e **nada conecta**. Nenhum caminho legado é reintroduzido. |
| Sem `localStorage` | Nenhum storage novo. O `sessionStorage` vira otimização de precisão, não pré-requisito. |

**Oráculo.** Com `flowSecret` apresentado e não encontrado a resposta segue 409
— não há queda para a retomada, justamente para não transformar um palpite de
segredo em sinal. Sem segredo, o 202 só informa ao chamador algo sobre as
**próprias** linhas.

**Concorrência.** Duas tentativas resolvem para a mais recente que de fato
voltou do Google (`code_encrypted IS NOT NULL` + `criado_em DESC`); as demais
morrem no TTL e no purge. Consentimento ainda em voo nunca é sequestrado por uma
retomada: sem `code` estacionado ele não entra no `WHERE`.

**Frontend.** Uma tentativa de retomada **por montagem**, só quando o admin não
está conectado — com o segredo local no marcador `ready`, sem segredo em
qualquer outro caso. Fora do retorno é sondagem: 202/409 são silenciosos e o
card mostra o CTA normal. Mais um disparo em `visibilitychange`, **apenas** após
um redirect real ao Google nesta montagem, que é o que destrava a PWA viva em
segundo plano. Nenhum dos dois é polling: são eventos discretos e contados.

Isto **não** altera migration, schema, allowlist de origem, escopos, nem
qualquer configuração no Google Cloud.

## Riscos residuais aceitos

| # | Risco | Decisão |
|---|---|---|
| **R1** | Atacante com **leitura do navegador da vítima** obtém `state` + `code_challenge` do histórico e pré-amarra um authorization code, transformando o park em injeção real. **Não é cobertura completa de PKCE.** | **D1 — ACEITO.** Nesse cenário o atacante já alcança o token de sessão e o `sessionStorage`; o PKCE não é o elo mais fraco. Não há correção dentro do OAuth: o `code_challenge` sempre trafega na URL de consentimento. |
| **R2** | DoS limitado a TTL + reclique: um `state` vazado pode ocupar o first-write do park, e o `finish` da vítima falha em `invalid_grant`. | **D2 — ACEITO.** Exige posse de um `state` vivo; custo para a vítima é um novo clique. |
| **R3** | Oráculo de 1 bit no destino do redirect (fluxo conhecido × desconhecido). | **D2 — ACEITO.** Só informa "vivo ou morto" a quem já tem o `state`, que sozinho não concede privilégio. |
| **R4** | Admin legítimo conecta a própria agenda pessoal ("entra em Configurações → Agenda → Conectar"). Zero verificações disparam, em qualquer desenho de `state`. | **D2 — ACEITO.** É limite do modelo de produto (uma agenda por igreja, qualquer admin conecta). Mitigação possível só na UI — exibir qual conta Google, quem conectou e quando — registrada como frente de produto separada, **fora deste V1**. |
| **R5** | Segredos de fluxo expirado vivem até ~1 tick do cron-worker (300s por padrão) além do TTL. | **D2 — ACEITO.** Knob disponível: um `UPDATE ... SET code_encrypted = NULL, verifier_encrypted = NULL` antes do `DELETE`. Não incluído por padrão. |
| **R6** | **Retenção indeterminada** de `verifier`/`code` cifrados num rollback de backend em que o cron-worker novo **não** permaneça. | **CONDICIONAL — NÃO COBERTO POR D2.** Só precisa de decisão se essa via de rollback for exercida. Nesse caso: limpeza explícita (`delete from calendar_oauth_flows where expires_at <= now();`) **ou** aceite próprio de R6. |

## G5 — rollout

**Fail-closed puro.** Sem flag de compatibilidade e sem fallback para a escrita
legada do callback, que é removida no mesmo PR.

Frontend novo contra backend antigo **não redireciona ao Google**: sem
`flowSecret` não existe quem conclua o fluxo, então o card mostra mensagem segura
em vez de mandar o usuário consentir à toa.

Backend novo contra frontend antigo é **falha recuperável por refresh**: o
callback estaciona o code, ninguém chama o `finish`, o fluxo expira e é purgado.
Nenhuma escrita legada ocorre.

## Ordem de deploy (o cron-worker é pré-condição do backend)

0. Construir o artefato e **registrar o image ID esperado**.
1. `deploy/.env` com `CALENDAR_OAUTH_RETURN_ORIGINS` (recriar, nunca `restart` —
   `docker compose restart` não relê o `.env`).
2. Migration aditiva.
3. Recriar **somente** o cron-worker (`--force-recreate`).
4. **G7a** — barreira. Se falhar, **parar**: o backend permanece antigo e nenhum
   fluxo V1 é criado.
5. Recriar o backend (`--force-recreate`).
6. **G7b** — paridade de image ID com o aprovado em G7a + `/health`.
7. Frontend novo.
8. Soak.

Os passos 3 e 5 **não podem ser coordenados**: uma prova posterior não protege o
intervalo em que o backend novo já aceita o primeiro fluxo sem purge vivo.
Coordenar exigiria um feature gate no backend que não existe e está fora do V1.

## Gates

| Gate | Conteúdo | Estado |
|---|---|---|
| **G1a** | `has_table_privilege('authenticated','public.calendar_sync', 'INSERT'/'UPDATE')` | **DEV: PASS** (`true`/`true`). **PROD: pendente** — não autoriza deploy nem migration |
| **G1b** | `calendar_oauth_flows`: SELECT/INSERT/UPDATE `true`, **DELETE `false`**, `anon` SELECT `false` | pendente — só após a migration aplicada em DEV |
| **G2** | Testes de corrida rodaram sem skip (`RLS_TEST_DATABASE_URL` presente) | pendente |
| **G4** | Google Cloud Console aceita `code_challenge` S256 | pendente |
| **G7a/G7b** | Ver ordem acima | a cada deploy |
| **G3** | Conexão conclui em PWA iOS instalada **sem** continuidade de `sessionStorage` | **BLOQUEADOR DE MERGE** (dono decidiu: PWA iOS está no V1). Correção implementada e coberta por teste; **só passa com iPhone real** — jsdom, simulador e navegador desktop **não** contam |
| **G6** | Parser do `AppShell` verificado | só se `app.*` entrar na allowlist |

## Frentes separadas, deliberadamente fora deste PR

- **Revogação no Google ao desconectar** — hoje `DELETE /calendar` só apaga a
  linha local; o refresh token segue válido no Google indefinidamente.
- **Redução de escopo** — `calendar.events` é read/write e nenhum caminho ativo
  escreve no Google. Reduzir `_SCOPES` **não altera refresh tokens já emitidos**:
  o grant vive na conta Google. Pior, `include_granted_scopes=true` faz o
  re-consentimento devolver a **união** dos escopos, então sem revogar antes nada
  estreita.
- **Limpeza em lote dos imports do Google** — `DELETE /events/{event_id}` já
  existe e está na UI; falta o lote, e ele precisa de tombstone porque o dedup
  olha só linhas existentes.
- **Higiene de logs** — `--no-access-log` no uvicorn e scrub de query string na
  borda. É infra: nenhuma linha de Python impede o servidor de logar a request
  line com `code` e `state`.

Sobre rate limit: fato de código é que `/calendar/connect` e `/calendar/callback`
não injetam `RateLimiter`. Qualquer conclusão sobre confiabilidade de IP depende
do proxy real, que não existe no repositório — **não comprovado**, não
classificado como vulnerabilidade.
