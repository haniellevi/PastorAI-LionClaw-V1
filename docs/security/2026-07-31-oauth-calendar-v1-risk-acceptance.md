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
ao Google e cai no access log; o `flowSecret` fica no `localStorage` da própria
origem do painel e nunca sai dela.

## PWA iOS + posse obrigatória do `flowSecret` (G3)

**Decisão do dono, 2026-07-31: PWA iOS instalada é superfície suportada no V1.**
G3 passa a ser bloqueador de merge.

O problema de continuidade é real. Numa PWA iOS:

- sair para `accounts.google.com` é navegação **fora do `scope`** do manifest
  (`"scope": "/"`), então o iOS entrega o link ao Safari. O retorno cai num jar
  de storage **separado** do da PWA instalada;
- mesmo quando o retorno reabre a PWA, o iOS pode tê-la encerrado em segundo
  plano e relançado;
- no caso mais comum a PWA nem é encerrada: fica viva em segundo plano com o
  botão preso em "Abrindo o Google…", e o consentimento conclui noutro app.

### Tentativa descartada: retomar por identidade

Uma primeira correção fez o `flowSecret` virar **opcional**, achando a linha por
`app_user_id` + `igreja_id` do Bearer. **Foi revertida** por
`PR222-OPTIONAL-SECRET-SECURITY-REVIEW-1`. O raciocínio de que "identidade
equivale ao segundo segredo" **está errado** e não deve ser reintroduzido:

- `app_user_id` + `igreja_id` provam apenas **quem finaliza**. Não provam **qual
  conta Google consentiu** — nada no fluxo amarra as duas coisas;
- com isso, a posse de um `state` vivo passava a bastar: um terceiro abre a URL
  de autorização **original** noutro navegador, consente com a conta Google
  dele, o callback público estaciona o `code`, e o fluxo **fechava sozinho** na
  próxima montagem da tela do admin — sem clique, sem marcador de retorno;
- pior que a versão anterior: abandonar o consentimento deixava de proteger, a
  janela virava o TTL inteiro, e não havia mais corrida a vencer.

### O que o PKCE cobre — e o que não cobre

PKCE recusa um `code` emitido para **outra** requisição de autorização: o
`code_challenge` daquela requisição não casa com este `code_verifier` e o Google
devolve `invalid_grant`.

PKCE **não impede** que alguém abra a URL de autorização **ORIGINAL** deste fluxo
noutro navegador e consinta com outra conta Google. O `code` sai amarrado ao
**mesmo** `code_challenge`, então a troca sucede e os tokens são os do terceiro.
PKCE prova que o `code` pertence a ESTA requisição; nunca prova QUAL conta
consentiu.

Consequência para o risco **R2** da tabela abaixo: a descrição original ("DoS ...
o `finish` da vítima falha em `invalid_grant`") **só vale** quando o `code`
injetado veio de outra requisição. Quando vem da URL original, a troca sucede e o
efeito é vinculação de conta, não negação de serviço. R2 foi corrigido na tabela.

### Regra vigente

> **Sem posse do `flowSecret`, nenhum fluxo é concluído.**

Ela não tem exceção por superfície, por marcador de rota nem por identidade.
Concretamente:

| Onde | Regra |
|---|---|
| `FinishRequest.flowSecret` | obrigatório, `min_length=1`. Corpo sem segredo morre no schema (422) — nenhuma linha é lida, travada ou consumida |
| Busca da linha | **exclusivamente** por `flow_secret_hash`. `app_user_id`/`igreja_id` são validação DEPOIS de achar, nunca chave de busca |
| `_pending_flow_for_user` | removido; um teste falha se o helper voltar a existir |
| Armazenamento do painel | `localStorage` da própria origem, chave versionada `gcal_flow_v2`, objeto `{secret, expiresAt}` |
| Prazo | `expiresAt` vem do `/connect` — o mesmo `expires_at` gravado na linha. O cliente não deriva TTL; o servidor revalida no `finish` e é a autoridade final |
| Limpeza do segredo | ao expirar, concluir, cancelar, levar rejeição terminal (4xx) ou iniciar deliberadamente um fluxo novo |
| Marcador `ready` + segredo vivo | conclui usando exatamente aquele segredo |
| Fora do `ready` | **nenhum POST automático** — nem na montagem, nem no `visibilitychange`. Aparece a CTA "Concluir conexão com o Google" e só o clique conclui |
| Sem segredo vivo | zero POST de `finish`, fail-closed, CTA para reiniciar a conexão |
| `visibilitychange` | apenas destrava a UI e revela a CTA (a PWA iOS fica viva em segundo plano). Não conclui nada |
| 202 | preserva o segredo até o TTL e mantém a ação explícita disponível |
| 409 | terminal: limpa o segredo e oferece reinício |

Custo aceito: numa PWA iOS o admin dá **um toque a mais** ao voltar do Google. É
o preço de manter a conclusão presa à posse do segredo e a uma ação humana.

Isto **não** altera migration, schema, allowlist de origem, escopos, nem
qualquer configuração no Google Cloud.

## Binding de identidade Google (ACCOUNT_IDENTITY_RISK)

**Estado: IMPLEMENTADO, aguardando revisão e gates externos.**
**NÃO é "resolvido em produção".** Nada foi aplicado, deployado ou executado
contra o Google.

### O que estava aberto

`state`, `flowSecret`, PKCE e a identidade Clerk falam todos do lado PastorAI.
Nenhum deles diz **qual conta Google** consentiu. PKCE, em particular, não impede
que alguém abra a URL de autorização **ORIGINAL** noutro navegador e consinta com
outra conta: o `code` sai amarrado ao MESMO `code_challenge`, então a troca
sucede e os tokens são os do terceiro.

### Desenho implementado (Desenho A)

O admin **declara** a conta antes de sair, e o servidor **verifica** quem de fato
autorizou antes de persistir qualquer token:

1. `POST /calendar/connect` recebe `{"expectedGoogleEmail": "..."}`, normaliza
   (trim + lowercase, regex pragmática — sem `EmailStr`, sem `email-validator`,
   mesmo padrão de `app/routers/auth.py`) e grava em
   `calendar_oauth_flows.expected_email`. O e-mail vive só no corpo: nunca em
   query string, nunca em log.
2. `build_consent_url` **não** recebe o e-mail declarado nem envia
   `login_hint`. Assim o endereço não entra no histórico do navegador nem em
   logs de URL. O usuário escolhe a conta diretamente na tela do Google.
3. Escopos ganham `openid email`, e o `finish`, **depois da queima e da troca**,
   chama `fetch_userinfo`. Falha fechada em tudo: erro de transporte, corpo
   não-JSON, `sub`/`email` vazios, ou `email_verified` que não seja exatamente
   `True`.
4. Só então compara `verified_email == expected_email`.

### Ordem no `finish` (o que veio antes continua igual)

Preservados: busca **exclusivamente** por `flow_secret_hash`; validação de
`app_user_id` e `igreja_id`; 202 sem `code`, sem consumir; **queima antes** da
chamada externa; `code` trocado uma única vez; `flowSecret` obrigatório.

Depois da queima: `exchange_code` → `fetch_userinfo` → `email_verified` →
comparação com o declarado → regras de continuidade por `sub` → probe
`list_calendars` → **só então** persistir tokens e identidade.

### Regras de continuidade — a chave é o `sub`, nunca o e-mail

E-mail troca de dono; `sub` não. `calendar_sync.google_account_sub` define a
identidade anterior:

| Situação | Refresh token | `google_calendar_id` |
|---|---|---|
| Primeira conexão (sem linha) | **exige** novo | nasce nulo |
| Conexão legada (`sub` NULL) | **exige** novo | zerado |
| Troca para `sub` diferente | **exige** novo | zerado — a seleção era da outra conta |
| Reconexão com o MESMO `sub` | pode preservar o anterior | preservado |

`prompt=consent` **não** é usado como presunção de que veio refresh token novo.
Qualquer rejeição deixa refresh e access tokens anteriores intactos.

### Rejeições

- **E-mail divergente** → 409 com detalhe estruturado
  `{"code": "conta_divergente", "expected": ..., "verified": ...}`. É a **única**
  recusa com detalhe: sem saber qual conta autorizou, o admin não tem como
  corrigir. Nenhuma escrita em `calendar_sync`, conexão anterior integralmente
  intacta, tokens novos morrem em memória, fluxo permanece consumido (um segundo
  `finish` não troca nada de novo).
- **Mesmo e-mail declarado com `sub` diferente** → 409 terminal com mensagem
  acionável, **sem revelar o `sub`**. Conexão anterior intacta.
- **Fluxo sem `expected_email`** (legado, criado antes do binding) → 409
  fail-closed, sem sequer tentar a troca.
- Todo o resto continua na recusa genérica, sem oráculo de causa.

Nem e-mail, nem `sub`, nem token entram em log — no sucesso ou na recusa.

### Superfície de resposta

`finish` (200) e `GET /calendar/status` passam a devolver `googleAccountEmail`.
Nunca o `sub`, nunca token. Conexão legada continua `connected=true` com
`googleAccountEmail=null`.

### Painel

Campo de e-mail obrigatório antes de iniciar; "Conectado como &lt;conta&gt;" quando
há identidade; "Trocar conta Google" com aviso explícito antes do redirect
quando o e-mail digitado diverge do atual; "Conta Google não registrada" +
"Registrar conta Google" no legado, **sem exigir desconexão** — a conexão antiga
segue válida até uma nova concluir com sucesso. Conta divergente mostra as duas
contas, diz que nada foi alterado e oferece reinício. O `gcal_flow_v2` continua
guardando **apenas** `secret` + `expiresAt`.

### O que este binding NÃO resolve

O risco **R4** permanece, agora por comportamento e não por cegueira: um admin
pode **deliberadamente** declarar e conectar a própria conta pessoal. A diferença
é que a conta Google verificada passa a ser registrada e **exibida no painel**.
Quem realizou a conexão e quando ficam registrados **no banco para auditoria,
mas não são exibidos no V1**. Continua sendo limite do modelo de produto (uma
agenda por igreja, qualquer admin conecta).

### EXTERNAL_CONFIG_PENDING

Nada aqui foi exercitado contra o Google real. Antes de qualquer promoção:

1. **Google Cloud Console** — o OAuth client precisa aceitar os escopos
   `openid email` na tela de consentimento. Não verificado.
2. **Endpoint de userinfo** — o default
   `https://openidconnect.googleapis.com/v1/userinfo` (setting
   `GOOGLE_OAUTH_USERINFO_URL`) nunca foi chamado por este código em ambiente
   real. Os testes usam `MockTransport`.
3. **Migration** `20260801_031500_calendar_account_identity_binding.sql` **não
   aplicada** em lugar nenhum.
4. **G3, G4 e G7a/G7b continuam NÃO EXECUTADOS.**

## Riscos residuais aceitos

| # | Risco | Decisão |
|---|---|---|
| **R1** | Atacante com **leitura do navegador da vítima** obtém `state` + `code_challenge` do histórico e pré-amarra um authorization code, transformando o park em injeção real. **Não é cobertura completa de PKCE.** | **D1 — ACEITO, com o escopo explicitado.** A justificativa vale porque, nesse cenário, o atacante já alcança o token de sessão **e o armazenamento do painel** — inclusive o `flowSecret`. Ela **não** se estende a quem obtém o `state` FORA do navegador da vítima (access log, histórico do Safari sincronizado, aparelho compartilhado): contra esses, a defesa é a posse obrigatória do `flowSecret`. **ATUALIZADO 2026-08-01:** vincular uma conta DIFERENTE da declarada passou a ser mitigado pelo binding de **ACCOUNT_IDENTITY_RISK** — o `finish` consulta o userinfo e recusa sem persistir quando a conta verificada diverge. O binding está **implementado, aguardando revisão e gates externos** (G8/G9, migration, DEV, iPhone real seguem pendentes); o resíduo COMPORTAMENTAL está descrito em **R4**. |
| **R2** | **CORRIGIDO 2026-07-31.** Um `state` vazado ocupa o first-write do park. Se o `code` veio de OUTRA requisição, o `finish` falha em `invalid_grant` e o efeito é DoS de TTL + reclique. Se veio da URL de autorização **ORIGINAL**, a troca **sucede** e o efeito é **vinculação de conta** — ver a seção do PKCE acima. A redação anterior descrevia só o primeiro caso. | **D2 cobre APENAS a parte de DoS.** **ATUALIZADO 2026-08-01:** o risco TÉCNICO de persistir uma conta diferente da declarada é mitigado pelo binding de **ACCOUNT_IDENTITY_RISK** — o `finish` consulta o userinfo e **recusa sem persistir** quando a conta verificada diverge da que o admin declarou; a posse obrigatória do `flowSecret` + conclusão por ação humana continuam eliminando o caminho silencioso. O binding está **implementado, aguardando revisão e gates externos** (G8/G9, migration, DEV, iPhone real seguem pendentes). O risco DELIBERADO — o admin declarar e conectar a própria conta pessoal — permanece como risco comportamental aceito em **R4**. |
| **R3** | Oráculo de 1 bit no destino do redirect (fluxo conhecido × desconhecido). | **D2 — ACEITO.** Só informa "vivo ou morto" a quem já tem o `state`, que sozinho não concede privilégio. |
| **R4** | Admin legítimo conecta a própria agenda pessoal ("entra em Configurações → Agenda → Conectar"). Zero verificações disparam, em qualquer desenho de `state`. | **D2 — ACEITO.** É limite do modelo de produto (uma agenda por igreja, qualquer admin conecta). **ATUALIZADO 2026-08-01:** a conta Google verificada fica registrada e **exibida no painel**; quem conectou e quando ficam registrados **no banco para auditoria, mas não são exibidos no V1**. O risco COMPORTAMENTAL permanece (o admin pode deliberadamente declarar e conectar a conta pessoal), embora a conta conectada tenha deixado de ser invisível. |
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
| **G3** | Em PWA iOS instalada: o segredo sobrevive ao relançamento no `localStorage` da origem, a CTA "Concluir conexão com o Google" aparece, **um toque** conclui, e nada conclui sozinho | **NÃO PROVADO — bloqueador de merge** (dono decidiu: PWA iOS está no V1). Correção implementada e coberta por teste, mas jsdom, simulador e navegador desktop **NÃO** contam. Só passa com **iPhone real** |
| **G8** | Google Cloud Console aceita os escopos `openid email` na tela de consentimento | **NÃO EXECUTADO** — ver EXTERNAL_CONFIG_PENDING |
| **G9** | `GET` real ao endpoint de userinfo devolve `sub` + `email` + `email_verified=true` | **NÃO EXECUTADO** — os testes usam `MockTransport` |
| **G1c** | `calendar_sync`/`calendar_oauth_flows`: colunas novas presentes e GRANTs inalterados após a migration | pendente — só após aplicar `20260801_031500` |
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
