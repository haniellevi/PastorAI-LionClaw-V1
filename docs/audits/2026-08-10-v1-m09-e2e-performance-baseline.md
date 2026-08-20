# V1-09 / M09 — baseline E2E e performance (Fase A)

**Início:** 2026-08-09 · **fechamento da coleta inicial:** 2026-08-10 ·
**revalidação de integração:** 2026-08-20

**Status:** `PHASE_A_BASELINE_PASS` · revalidada localmente no SHA atual;
aceite final de produção ainda pendente

**Código da aplicação medido originalmente:**
`3f085ec7228d770649b0d9041f0e16154fe37629`

**SHA do harness revalidado:** `e7e20837e7aba333d91b3b3d07bd59319644f655`
(sobre a base M00 integrada em `5a0f12f5062bfd45d780dacf29090c8f34a66da8`)

**Branch do laboratório:** `codex/v1-m09-e2e-performance`

## Conclusão

A Fase A está reproduzível e verde. Login, dashboard, restauração de sessão,
navegação, troca de modelo e conexão WhatsApp foram exercitados em build de
produção local, num Chromium real, com dados fictícios e API-mock presa a
loopback. Um guard estrutural compartilhado valida `M09_APP_URL` e
`M09_API_URL` antes do build, da configuração dos servidores e dos helpers. Ele
aceita somente HTTP em `localhost`, IPv4 `127.0.0.0/8` ou IPv6 `::1`, sem
credenciais, caminho além da raiz, query ou fragmento. A representação bruta
também precisa ser canônica, sem controles, whitespace ou barras invertidas; a
falha acontece antes de qualquer rede.

No SHA de revalidação, cada tentativa também grava um snapshot em `afterEach`.
Assim, requests sanitizados, timeline e bloqueio de rede permanecem disponíveis
mesmo se uma asserção falhar. O mock foi atualizado para os contratos atuais de
permissões, avisos e preloads de Inbox/Ganhar, sem abrir acesso a nenhum serviço
real.

Isto **não é o aceite final da M09**. A Fase B precisa repetir as medições no
SHA efetivamente implantado após os gates restantes da V1.

## O que foi medido

Ambiente local:

- `next build` de produção, sem alterar componentes da aplicação;
- Node `v24.19.0`; o workflow versionado usa a mesma versão, alinhada ao M00;
- Playwright `1.62.1`, Chromium;
- latência deliberada do mock: login 280 ms, `/auth/me` 320 ms, cada leitura do
  dashboard 140 ms;
- nenhuma credencial real; senha fictícia é registrada apenas como
  `[redacted]`;
- troca de modelo e geração de QR alteram somente memória do mock local.

## Orçamentos

| Sinal | Meta V1 | Gate da Fase A | Resultado local |
| --- | ---: | ---: | ---: |
| Feedback visual após ação | p75 ≤ 250 ms | amostra < 500 ms | login 81,9 ms; navegação p75 85,7 ms |
| Página aquecida completa | p75 < 1.000 ms | p75 < 1.000 ms | **109,9 ms** (8 amostras) |
| Login novo → dashboard completo | separado do warm; alvo provisório PROD p75 ≤ 5 s | amostra local < 4 s | **1.437,7 ms** |
| Sessão restaurada → dashboard completo | separado do warm; alvo provisório PROD p75 ≤ 5 s | amostra local < 4 s | **1.581 ms** |
| Erros JS / `console.error` | zero | zero | **zero** |
| Requisições externas no laboratório | zero | zero | **zero** |

Os números frios são amostras de laboratório, não p75 de produção. Menos de
1 segundo só é declarado para a navegação **já aquecida**, onde há oito
amostras controladas.

Para a Fase B, os Core Web Vitals seguem os limites “bons” no p75: LCP ≤ 2,5 s,
INP ≤ 200 ms e CLS ≤ 0,1, segmentados entre mobile e desktop. Referência:
<https://web.dev/articles/vitals>.

## Gates E2E criados

1. Login novo: feedback imediato, perfil completo na resposta e nenhum
   `/auth/me` redundante.
2. Restauração: `/auth/me` valida a sessão antes das leituras do dashboard.
3. Dashboard: fila, equipe, células e visão geral começam em paralelo.
4. Navegação: Agenda aquecida mede feedback e tela completa em oito amostras.
5. Agente IA: troca de `gpt-5.6-luna` para `gpt-5.6-terra`, comprovando um
   único `PUT /agent/model` no mock.
6. WhatsApp: gera QR e comprova um único `POST /whatsapp/connection` com
   `{ "action": "connect" }` no mock.

Execução histórica da coleta inicial da Fase A, com o código medido em
`3f085ec7228d770649b0d9041f0e16154fe37629` e o primeiro harness M09 em
`c35ae64de300e5637fe6503fac7c96fe30c1a07e`:

```text
Playwright após `npm ci`: 5 passed (30.0s)
Vitest: 61 arquivos, 518 testes PASS
typecheck: PASS
lint: PASS
next build: PASS
```

Essas contagens registram a coleta inicial e não representam a suíte ampliada
pelos corretivos posteriores do guard de loopback.

### Revalidação de integração atual

No SHA `e7e20837e7aba333d91b3b3d07bd59319644f655`, sobre a main que já contém
M00, a execução local aprovou:

```text
npm audit --omit=dev --audit-level=high: 0 vulnerabilidades
lint: PASS
typecheck: PASS
Vitest: 86 arquivos, 783 testes PASS
next build: PASS
Playwright: 5 fluxos PASS (20,5 s)
```

Os cinco snapshots de outcome não registraram requests externos nem requests
locais pendentes. As evidências JSON ficam em
`frontend/test-results/<teste>/metrics/` durante cada run e incluem SHA, versão
do Node, timeline, requests sanitizados e arrays de erros. O diretório é
artefato de CI, não arquivo versionado.

## Waterfalls encontrados

### 1. Autenticação ainda é uma barreira real para os dados

No login novo, `/auth/login` levou 292 ms. As quatro leituras do dashboard
começaram 324 ms depois do término do login. Na sessão restaurada, `/auth/me`
levou 328 ms e as leituras começaram 317 ms depois.

Isso confirma a cadeia:

```text
validar identidade → montar shell/tela → buscar dados do dashboard
```

No login novo os chunks autenticados começam logo após a resposta de login. Na
restauração, os chunks já são aquecidos enquanto `/auth/me` está em voo, o que
é melhor. Reduzir o intervalo pós-auth pode melhorar o cold load, mas exigiria
mudança em componente de produção. Pela regra da onda paralela, nenhuma
otimização foi aplicada nesta branch; o finding volta ao orquestrador.

### 2. O fan-out do dashboard está correto

Depois do gate de auth, `/work-queue`, `/team/lookup`, `/cells` e
`/dashboard/overview` começaram com dispersão de apenas 8 ms, tanto no login
novo quanto na restauração. Não há waterfall entre essas quatro leituras.

## Navegador interno e produção read-only

O navegador interno do Codex confirmou no laboratório local:

- login e dashboard populado;
- Agenda carregada;
- troca de modelo com o `PUT` esperado;
- geração de QR com o `POST` esperado;
- zero erros de navegador.

Em produção, `https://app.igreja12.com.br/` foi aberto sem autenticação e sem
cliques de ação. A página pública de login carregou, a navegação inicial do
navegador levou aproximadamente 1,67 s e não houve erro no console. Essa
leitura não comprova painel autenticado, Web Vitals nem SHA implantado e,
portanto, não conta como aceite da Fase B.

## Finding devolvido ao orquestrador

`M09-PERF-AUTH-GAP-1` — há um intervalo local de aproximadamente 320 ms entre
o fim da validação de auth e o início das leituras do dashboard. Não é blocker
da Fase A e ainda não pode ser classificado em produção. M06/M08 devem terminar
antes de qualquer mudança no fluxo de produção.

`M09-DEPENDENCY-NANOID-1` — finding histórico encerrado para esta integração:
`npm audit --omit=dev --audit-level=high` retornou 0 vulnerabilidades no
lockfile atual. Não foi aplicado override de dependência pela M09; qualquer novo
advisory deve ser reavaliado em uma missão própria.

## Fase B — checklist de aceite final

Somente depois dos deploys aprovados de M06/M07/M08:

1. registrar SHA implantado e provar que frontend/API pertencem à mesma
   release esperada;
2. executar ao menos cinco amostras cold e oito warm, separando desktop e
   mobile;
3. medir feedback, dashboard completo, LCP, INP e CLS no p75;
4. verificar `console.error`, exceções não tratadas e respostas 4xx/5xx;
5. validar login/dashboard/navegação em produção somente leitura;
6. manter troca de modelo e WhatsApp no mock/sandbox, salvo autorização
   explícita para um tenant canário;
7. comparar com este baseline sem misturar máquina, SHA ou ambiente;
8. declarar `FINAL_PASS` somente se E2E estiver verde, erros forem zero, os
   orçamentos estiverem cumpridos e toda evidência apontar para o mesmo SHA.
