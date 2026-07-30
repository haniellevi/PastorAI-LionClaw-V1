# Aceite final da V1 - smokes DEV OPTIN-1 e REATIVAR-1 - 2026-07-30

## Identificacao

| Campo | Valor |
| --- | --- |
| Baseline | `origin/main` em `4dde325dfb818350a14a1c8fa264c7172f17c6ce` |
| Ambiente validado | DEV isolado (`APP_ENV=staging`) |
| Frontend / backend | `localhost:3000` / `127.0.0.1:8000` |
| Projeto DEV | `cxmjojnocigekgcxhubi` |
| Envios externos | desabilitados (`external_sends_enabled=false`) |
| Producao | nao acessada e nao alterada |
| Deploy / migration | nenhum |

Este registro fecha as duas evidencias funcionais que permaneceram pendentes no
[registro da release FECH-2](./2026-07-20-release-fech2-833b5a3.md). Na verificacao
anterior, os fluxos estavam bloqueados pela ausencia de dados elegiveis em
producao. A validacao atual criou dados sinteticos exclusivamente em DEV, sem
fabricar estado em PROD.

## Guardas de seguranca

- O projeto, o ambiente e as flags foram conferidos antes de qualquer escrita.
- Os registros usados no smoke foram sinteticos e identificados pelo prefixo
  `SMOKE`.
- Nenhuma mensagem foi enviada e nenhuma integracao externa foi acionada.
- Nenhuma credencial, telefone completo, token ou identificador completo de
  pessoa foi registrado neste documento.
- Nao houve exclusao fisica de dados; o encerramento usou o arquivamento normal
  do produto.

## OPTIN-1

Objetivo: provar o ciclo `opt-out -> reativacao de comunicacoes -> arquivamento`
pela superficie administrativa.

1. Foi criada pela UI a pessoa sintetica `SMOKE OPTIN-1 20260729-235201`.
2. Um script one-off guardado, mantido fora do repositorio, aplicou o opt-out na
   mesma transacao e sob as regras RLS do ambiente DEV.
3. O estado gerou um consentimento append-only `optout:v1`, sem ator humano.
4. Como a acao de reativacao vive no painel de contato, foi criada uma conversa
   sintetica vazia somente para tornar essa superficie alcancavel. Ela ficou no
   estado `ia`, com zero mensagens e zero envios.
5. O administrador acionou `Reativar comunicacoes` pela UI. O estado final ficou
   `optout=false` e foi criado o consentimento `reoptin:v1` com ator
   administrativo.
6. A pessoa foi arquivada pela UI com o motivo `smoke V1`.

| Evidencia | Resultado |
| --- | --- |
| Pessoa | `9c7d1d85...` |
| Tenant | `00000000...` |
| Conversa sintetica | `3dc18c47...`, zero mensagens |
| Consentimentos | `optout:v1` -> `reoptin:v1` |
| Estado final | `optout=false`, pessoa arquivada |

## REATIVAR-1

Objetivo: provar o ciclo de vida de uma pessoa arquivada sem exclusao fisica.

1. Foi criada pela UI a pessoa sintetica `SMOKE REATIVAR-1 20260729-235202`.
2. A pessoa foi arquivada pela UI com o motivo `smoke V1`.
3. A pessoa foi reativada pela UI; o evento preservou o motivo original e
   registrou o ator administrativo.
4. A pessoa foi arquivada novamente pela UI para deixar o ambiente DEV em um
   estado final conhecido.

| Evidencia | Resultado |
| --- | --- |
| Pessoa | `2cc026ad...` |
| Eventos | `arquivada` -> `reativada` -> `arquivada` |
| Ator | administrador autenticado |
| Estado final | pessoa arquivada |

## Resultado final

| Criterio | Veredito |
| --- | --- |
| OPTIN-1 funcional em DEV | PASS |
| REATIVAR-1 funcional em DEV | PASS |
| Eventos e consentimentos append-only | PASS |
| Zero envio externo | PASS |
| Zero exclusao fisica | PASS |
| Arvore Git e codigo alterados pelo smoke | NAO |
| Deploy, migration ou escrita em PROD | NAO |

Os dois fluxos funcionais pendentes da FECH-2 estao aceitos para o encerramento
da V1. Esta prova e deliberadamente de DEV: ela nao declara que uma escrita real
foi repetida em producao.

A validacao financeira tambem nao exige cobranca real em PROD para o aceite da
V1. A decisao e os criterios da missao futura estao em
[2026-07-30-v1-billing-sandbox.md](../decisions/2026-07-30-v1-billing-sandbox.md).

## Pendencias posteriores a V1

- Executar `BILLING-SANDBOX-1` em sandbox ou ambiente financeiro de teste
  separado, conforme a decisao versionada.
- Tratar qualquer nova regressao funcional como uma missao propria, sem
  reabrir este aceite por ausencia de cobranca real em PROD.
