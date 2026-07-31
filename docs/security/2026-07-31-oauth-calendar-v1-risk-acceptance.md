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
| **G3** | Continuidade de `sessionStorage` no roundtrip em PWA iOS instalada | só se PWA iOS estiver no V1 |
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
