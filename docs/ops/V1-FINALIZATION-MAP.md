# PastorAI / Igreja 12 — mapa autoritativo para finalizar a V1

Atualizado em 2026-08-19, fuso `America/Sao_Paulo`.

Este documento é o ponto de entrada para qualquer pessoa ou agente de IA que
assuma o encerramento da V1. Ele reúne o estado vivo conhecido, a ordem de
execução, os gates obrigatórios, os riscos e a definição de conclusão.

> Este arquivo é um snapshot operacional. Antes de qualquer ação, refaça o
> preflight de Git, GitHub e ambiente. SHA, checks, mergeabilidade e estado de
> produção são dados temporais.

## 0. Estado vivo consolidado — 2026-08-19

Esta seção prevalece sobre os trechos históricos do snapshot de 2026-08-17
abaixo. O histórico foi preservado para auditoria; ele não deve ser usado como
estado atual de PR, SHA, checks ou prioridade.

### Integrações concluídas desde o snapshot

| Frente | PR | SHA da PR | Merge em `main` | Evidência |
|---|---:|---|---|---|
| Hotfix Pessoa | #252 | `57c6acabaa92a4b326d0a6b939d19963d68da684` | `91862f3dd6988122cf7d7aa1b4be1b7a4358b2ed` | PR mesclada; validação de concorrência e revisão independente concluídas no fluxo da missão |
| M08 readiness/observabilidade | #249 | `5c7055d577ae51163b322d1874bbfe943d769c2b` | `9e5bab9962c83628bf30d427921ad6125134511a` | Integrada após CI 3/3 e `REVIEW_PASS`; reaberta abaixo por falha de integração posterior |

`origin/main` confirmado neste registro: `9e5bab9962c83628bf30d427921ad6125134511a`.
O merge de #249 tem como pais a `main` anterior
`91862f3dd6988122cf7d7aa1b4be1b7a4358b2ed` e o SHA revisado da PR.

### Fila vigente

1. **P2 reaberta — M08 / PR #249:** a execução RLS da árvore de merge da PR
   documental falhou em
   `test_agent_reply_concurrent_recovered_claims_execute_once_before_transport[10]`.
   O estado observado foi `ia_execucao_ambigua` onde o teste exige `ia`.
   Reproduzir contra PostgreSQL descartável e corrigir antes de M01.
2. **P3 — M01 / PR #234:** corretivo REVIEW-9 de billing/Asaas, somente após
   a revalidação de M08.
3. **P4 — M06 / PR #244:** hardening, após a conclusão de M01.
4. **P5 — E-mail Brevo**, **P6 — M09 / PR #245**, **P7 — Células** e
   **P8 — PR #257**, na ordem original, salvo decisão humana explícita.

### PRs consultadas ao vivo

| PR | Estado | HEAD | Checks no HEAD | Próxima exigência |
|---:|---|---|---|---|
| #234 | OPEN/DRAFT, CLEAN | `a2011c5e6354ebc85221496b4257c81ff17f0eeb` | 3/3 verdes | corretivo REVIEW-9, integração da `main` atual e nova revisão |
| #244 | OPEN/DRAFT, CLEAN | `7caf85d18f34452f8c8f3dc9100b0bfc9d3d712d` | 3/3 verdes | reproduções M06 e integração da `main` atual |
| #245 | OPEN/READY, CLEAN | `919e1ab58cbfca3f8f3ff4048a4c453a448551b4` | 4/4 verdes | retry Playwright/Chromium e preflight vivo |
| #257 | OPEN/READY, CLEAN | `bbd331f7634777d43166385dd31bb3ba349bee0c` | 3/3 verdes | revisão independente visual e compatibilidade com Células |

O runbook `docs/ops/PRODUCTION-RUNBOOK.md` continua com dívida documental:
deve incorporar os contratos finais de M08 e, posteriormente, do gate dedicado
Brevo. Isso não autoriza instalação, migration, deploy, flags ou produção.

## 1. Objetivo

Finalizar a V1 sem misturar branches, sem promover código não revisado e sem
usar produção como ambiente de teste. O encerramento exige:

1. resolver e revisar todas as frentes abertas;
2. integrar cada branch à `main` atual, uma por vez;
3. obter CI verde no SHA integrado;
4. criar um único SHA candidato de release;
5. executar migrations e deploys somente por gates humanos separados;
6. provar saúde, readiness, login, isolamento e integrações controladas;
7. atualizar os runbooks canônicos e registrar a evidência final.

## 2. Regras permanentes

- Trabalhar em **uma missão por vez**.
- Revisão, correção, publicação, Ready, merge, migration, deploy, ativação de
  flags, canário e produção são gates separados.
- Nunca inferir autorização para Supabase, Hostinger/VPS, Vercel, Asaas,
  Evolution, Brevo, Google ou produção.
- Não abrir, imprimir ou transmitir `.env`, chaves, JWTs, DSNs ou dados de
  usuários.
- Usar worktree isolado e limpo. Não desenvolver na raiz principal atual.
- Não resetar, restaurar, limpar ou sobrescrever mutações desconhecidas.
- CI verde não substitui revisão independente nem prova contra a `main` atual.
- Toda reprodução concorrente de banco deve usar PostgreSQL real e descartável.
- Artefatos temporários devem ser removidos; recursos alheios não podem ser
  reutilizados, parados ou excluídos.
- Grafo stale ou sem integridade comprovada é `NAO_COMPROVADO`, não evidência.

## 3. Fonte de verdade e estado do workspace

### 3.1 Git vivo

| Item | Estado em 2026-08-17 |
|---|---|
| Repositório | `haniellevi/PastorAI-LionClaw-V1` |
| `origin/main` | `45eddf28d8c9d9543cd0e0b580d20b2a54783889` |
| Última integração em `main` | PR #256, polimento visual final |
| Checkout raiz | detached em `9121abb4f36790df74546b89ca24ad1641cbdb4d` |
| Estado da raiz | suja, com alterações rastreadas e não rastreadas |
| Regra | não usar a raiz para implementação, merge ou testes destrutivos |

O projeto ainda está cadastrado no Codex Desktop pelo caminho:

```text
C:\Users\hanie\Searches\OneDrive\Documentos\workspace\PastorAi-1.0
```

A migração definitiva para `C:\workspace` ou Linux deve ocorrer depois que as
missões Windows abaixo forem encerradas ou entregues em branches remotas.

### 3.2 Grafos

| Grafo | Última escrita observada | Situação |
|---|---:|---|
| Graphify | 2026-08-07 | stale, aproximadamente 232 horas |
| CodeGraph | 2026-08-08 | stale, aproximadamente 215 horas |

Nenhum dos dois cobre o HEAD, a `main` atual e as mudanças locais. Eles não
foram usados na elaboração deste mapa. Atualização futura deve ocorrer somente
em checkout limpo do SHA final da V1.

### 3.3 Ordem das fontes

Quando houver divergência, usar esta ordem:

1. GitHub e `origin/main` consultados no momento da ação;
2. árvore Git e diff do worktree proprietário;
3. testes reproduzidos no SHA exato;
4. runbooks canônicos versionados;
5. este mapa;
6. relatórios históricos e conversas antigas;
7. grafos, somente quando frescos e íntegros.

## 4. Base já integrada

As seguintes fundações já estão em `origin/main` e devem ser preservadas:

- PR #246, M07: locks reproduzíveis, hashes, verificador de manifests e
  container backend UID `10001`; a resolução transitiva de `nanoid` foi
  atualizada para `3.3.18` pela M08, substituindo a anterior `3.3.17`;
- PRs #247, #248 e #250: fundação UX, dashboard e acesso/liderança de células;
- PR #251: acessibilidade de presença;
- PRs #253 a #256: identidade Diamante, design system e polimento visual;
- correções anteriores de login, agenda, tenant, broadcasts e contatos já
  presentes na história de `main`.

M02, backup/rollback, e M07, dependências reproduzíveis, estão encerradas como
missões de implementação. Seus contratos continuam obrigatórios no release.

## 5. PRs abertas no GitHub

Registro histórico consultado em 2026-08-17. Para o estado atual, usar a
seção 0:

| Prioridade | PR | Branch / HEAD | Estado | Checks | Papel no fechamento |
|---:|---:|---|---|---|---|
| 1 | #252 | `codex/hotfix-pessoa-phone-concurrency` / `25b55614681227e8860e25e9964a0f15ca997182` | OPEN/DRAFT, CLEAN; revisão bloqueada por ambiente | 3/3 verdes | desbloqueia integração segura da M08 |
| 2 | #249 | `codex/v1-m08-readiness-observability` / `43b840e04b0593afa463ad1f6d716ffcfa5ea42a` | OPEN/DRAFT, CONFLICTING | 3/3 verdes no HEAD antigo | readiness, workers, monitor e backup |
| 3 | #234 | `codex/complimentary-church-plans` / `a2011c5e6354ebc85221496b4257c81ff17f0eeb` | OPEN/DRAFT, CLEAN | 3/3 verdes | billing/Asaas e planos cortesia |
| 4 | #244 | `codex/v1-m06-hardening` / `7caf85d18f34452f8c8f3dc9100b0bfc9d3d712d` | OPEN/DRAFT, CLEAN | 3/3 verdes | RLS, ACLs, executor e hardening |
| 5 | #245 | `codex/v1-m09-e2e-performance` / `919e1ab58cbfca3f8f3ff4048a4c453a448551b4` | OPEN/READY, CLEAN | 4/4 verdes | baseline E2E/performance |
| 8 | #257 | `fix/central-celulas-hoje` / `bbd331f7634777d43166385dd31bb3ba349bee0c` | OPEN/READY, CLEAN | 3/3 verdes | melhoria visual da Central; não bloqueia segurança |

Auto-merge estava desabilitado nas PRs críticas verificadas. Reconfirmar antes
de cada gate.

## 6. Frentes sem PR final

### 6.1 E-mail Brevo

- Branch: `codex/v1-brevo-email-gate`.
- HEAD base do corretivo: `6dd42a8356ecd94908d794d7eac4e8f237fd2325`.
- Worktree: `C:\Users\hanie\.codex\worktrees\743a\PastorAi-1.0`.
- Restava somente uma fixture de teste em `backend/tests/test_brevo_gate.py`.
- Testes já observados no diff: direcionado `4 passed`; suíte Brevo
  `139 passed`, sob zero rede e zero leitura de `.env`.
- Bloqueio atual: permissão de escrita no gitdir compartilhado impediu
  `git add`/commit. Não ampliar ACLs recursivamente.

Definição de pronto desta frente:

1. criar um commit local único contendo somente a fixture;
2. revisão independente read-only;
3. integrar a `main` atual em gate separado;
4. publicar PR Draft;
5. CI verde, revisão da PR, Ready e merge em gates separados;
6. atualizar o runbook, pois Brevo agora possui gate dedicado e não deve ser
   descrito como subordinado apenas a `ALLOW_REAL_SENDS`.

### 6.2 Transferência e remoção de membros de células

- Branch: `codex/cell-member-transfer-removal`.
- HEAD observado: `05c0aad7839d835fdbfaa762c84f9d7b94f8568d`.
- Worktree proprietário:
  `C:\Users\hanie\.codex\worktrees\340b\PastorAi-1.0`.
- Revisão independente dedicada foi criada no worktree `7074` e pausada para
  cumprir a regra de uma missão por vez.
- `celula_membro` ativo é o vínculo canônico; `pessoas.celula_id` é espelho
  legado. Remover da célula nunca exclui a Pessoa.

Findings parciais já obtidos antes da pausa:

- P1: confirmação pode permanecer stale após alteração do payload;
- P2: `payload_atual` não é recapturado sob lock nos fluxos de
  rejeição/ajuste.

Nenhuma correção desses findings foi iniciada.

A revisão deve retestar:

- fila da Central acima de 50 solicitações;
- reset da confirmação ao mudar payload;
- correção real antes de reenviar;
- motivo e payload append-only por evento;
- concorrência transferência versus liderança;
- confirmação no contrato HTTP, `payload_atual` e recuperação após `409`.

Depois: corrigir findings, revisar novamente, integrar `main`, publicar PR Draft,
obter CI, Ready e merge.

## 7. Fila serial de encerramento

Não iniciar a próxima linha enquanto a atual não produzir seu estado final e o
mapa não for atualizado. A seção 0 registra a conclusão de P1 e P2; P3 é a
próxima missão.

### P1 — Hotfix Pessoa / PR #252 — CONCLUÍDA EM 2026-08-17

O bloco abaixo é o diagnóstico histórico preservado. A PR foi mesclada em
`91862f3dd6988122cf7d7aa1b4be1b7a4358b2ed`; consultar a seção 0 para a
evidência de encerramento.

**Razão da prioridade:** é pequeno, já revisado quase integralmente e resolve a
corrida que bloqueou a integração da M08.

Pendente:

- PostgreSQL 17 real com psycopg2 e psycopg3;
- matriz 2/5/10 sessões e repetições;
- acesso explícito da sandbox ao pipe Docker e ao índice/wheels aprovados.

Último resultado read-only:

- merge sintético contra `origin/main` atual passou sem conflito;
- a `main` não altera os dois arquivos do hotfix;
- integração da `main` não é tecnicamente necessária para resolver conflito,
  embora possa ser exigida como governança antes de Ready;
- offline: `12 passed, 16 skipped`; consumidores: `73 passed`;
- Docker retornou `permission denied` na sandbox revisora;
- o índice não forneceu psycopg3, portanto a prova obrigatória não ocorreu.

Aceite:

- somente `23505` da constraint `uq_pessoas_telefone_ativa` é deduplicado;
- flush externo ocorre antes do savepoint;
- candidata precisa ser transitória;
- rollback externo e três tentativas limitadas preservados;
- nenhuma duplicidade, deadlock, lock residual ou falso sucesso;
- `REVIEW_PASS` independente no SHA final.

Próximos gates possíveis, sempre separados:

1. integração normal da `main`, se a revisão exigir;
2. CI no novo SHA;
3. revisão final da PR;
4. Ready;
5. merge.

### P2 — M08 / PR #249 — REABERTA EM 2026-08-19

O bloco abaixo é a fila histórica do corretivo REVIEW-7. A PR foi revisada,
passou CI 3/3, foi marcada Ready e mesclada em
`9e5bab9962c83628bf30d427921ad6125134511a`. A execução RLS posterior na
árvore de merge da PR #258 falhou no cenário de 10 workers, portanto o aceite
M08 não permanece comprovado e a seção 0 prevalece.

Pendente no corretivo local REVIEW-7:

- single-flight durável antes de `process_inbound_message`;
- idempotency key estável derivada do claim/evento de entrada;
- preservação de fence, ownership e quarentena de resultado ambíguo;
- rejeição de hardlinks no backup, exigindo `nlink == 1`;
- commit local, revisão independente e integração da `main` atual;
- resolver o conflito da PR sem perder `lock_canonical_phone` nem os controles
  M08.

Aceite:

- 2/5/10 workers executam agente/tools uma única vez por evento;
- zero reenvio cego após timeout ou resposta ambígua;
- Redis, PostgreSQL 17, backup e systemd passam em ambiente descartável;
- monitor sem Docker, `.env` ou `/root`; risco do socket Docker fica restrito e
  documentado na unidade de backup;
- PR CLEAN, CI verde e `REVIEW_PASS` no SHA integrado.

### P3 — M01 / PR #234 — PRÓXIMA PRIORIDADE

Pendente no corretivo REVIEW-9:

- validar semanticamente todos os campos financeiros antes de rede/mutação;
- remover claim/commit prematuro `prepared -> creating`;
- preservar recuperação terminal legítima sem segunda cobrança;
- corrigir `FakeSession` de Subscription para respeitar WHERE, ID e tenant;
- repetir concorrência e spies de GET/POST/PUT/DELETE em PostgreSQL 17;
- integrar a `main` atual depois do corretivo e revisar novamente.

Aceite:

- estados divergentes produzem zero chamada Asaas e zero mutação local;
- locks mantêm a ordem canônica definida pela missão;
- migration forward-only permanece intacta até gate próprio;
- CI verde e revisão independente sem P0-P2.

### P4 — M06 / PR #244

O merge sintético de `7caf85d...` com `45eddf2...` não apresentou conflito e
produziu a árvore esperada:

```text
802398461ecd28c676fe7e33e46e7217b3633ace
```

Pendente:

- repetir o probe com Node 20.20.2 e acesso ao registry;
- build frontend e smoke de headers;
- PostgreSQL 17 descartável e seleção integral `rls-integration`, incluindo
  `test_apply_migrations.py`;
- confirmar os 19 whitespaces documentais como blobs idênticos à `main`;
- somente depois autorizar integração real, CI e nova revisão.

Aceite:

- executor continua fail-closed por nome/hash/confirmação;
- parser não ecoa DSN;
- TOCTOU, symlink, transação+ledger, drift, ACL/RLS, SET ROLE e ADMIN OPTION
  permanecem protegidos;
- nenhuma migration é aplicada a DEV/PROD neste gate.

### P5 — E-mail Brevo

Concluir a sequência descrita na seção 6.1. Antes do merge, confirmar:

- defaults fail-closed;
- wildcard e allowlist malformada bloqueados, inclusive com allow-all;
- `InvalidURL` e demais exceções não preservam segredos em traceback/locals;
- seis callsites sem falso `emailEnviado=true` ou HTTP 500;
- fixtures novas somente em `example.test`;
- zero rede real e zero leitura de `.env`.

### P6 — M09 / PR #245

O delta aplicado sinteticamente sobre a `main` atual passou guard, YAML e builds.
O bloqueio foi `spawn EPERM` ao iniciar Chromium no Windows.

Pendente:

- execução local com permissão restrita ao Playwright/Chromium;
- 5/5 IPv4 e 5/5 em `::1`;
- zero requests externas, console errors e page errors;
- depois, preflight vivo e gate separado de merge.

Não alterar o contrato M07: `nanoid@3.3.18` continua transitivo por override
de segurança da M08, e Playwright `1.62.1` é devDependency da M09.

### P7 — Células

Retomar a revisão dedicada somente depois de P1-P6 ou quando houver decisão
humana explícita para mudar a prioridade. Seguir a seção 6.2.

### P8 — PR #257

PR visual pronta e limpa, mas sem revisão independente registrada neste mapa.
Como não altera endpoint nem regra de negócio, fica depois das correções de
segurança, billing, workers e E2E.

Pendente:

- revisão read-only dos sete arquivos;
- validar fila, navegação e empty state;
- verificar compatibilidade com a branch de transferência/remoção de Células;
- preflight, Ready já presente e merge somente com autorização.

## 8. Dependências entre frentes

```text
PR #252 Hotfix Pessoa [CONCLUÍDA]
  -> integração segura da M08 [PR #249 MESCLADA; ACEITE REABERTO]
     -> corretivo M08 e nova validação integrada

M01 billing -----------\
M06 hardening ----------+-> SHA final de main -> migrations/deploy/smokes
E-mail Brevo -----------/

M09 E2E -------------------> prova final do SHA integrado
Células + PR #257 ---------> fechamento funcional/UX da Central
```

M09 fase local pode ser validada antes, mas o baseline final de produção deve
medir o SHA efetivamente implantado.

## 9. Protocolo obrigatório para cada missão

### 9.1 Preflight

Registrar:

- missão e tipo: correção, revisão, integração, Ready, merge ou produção;
- branch, HEAD, pai, base, `origin/main` e merge-base;
- estado da PR, checks e auto-merge;
- worktree e índice limpos;
- arquivos autorizados e diff esperado;
- recursos externos explicitamente dentro e fora do escopo.

Divergência em SHA, branch, worktree ou autorização resulta em `BLOCKED`.

### 9.2 Implementação

- alteração mínima;
- testes direcionados primeiro;
- PostgreSQL/Redis/Docker descartáveis quando necessários;
- suite proporcional ao risco;
- compilação, YAML/Bash quando aplicável, `git diff --check`, conflitos e
  varredura de segredos;
- exatamente um commit quando o gate assim determinar;
- nenhum push sem autorização nominal.

### 9.3 Revisão independente

- revisor novo e sem participação na implementação;
- estritamente read-only;
- reproduções adversariais próprias;
- findings classificados P0-P3;
- `REVIEW_PASS`, `REVIEW_FAIL` ou `REVIEW_BLOCKED`;
- testes verdes sem parecer independente não equivalem a aprovação.

### 9.4 Integração e publicação

- fetch e preflight vivos;
- merge normal da `main`, salvo autorização diferente;
- resolver somente conflitos autorizados;
- rodar gates na árvore integrada;
- push normal, sem force;
- PR Draft primeiro;
- Ready e merge são gates posteriores.

## 10. Formação do release candidate

Depois que todas as PRs obrigatórias estiverem mergeadas:

1. congelar novas features;
2. registrar o SHA exato de `origin/main`;
3. criar checkout limpo e descartável desse SHA;
4. instalar Python pelos locks com `--require-hashes`;
5. executar `pip check`, verifier e auditoria;
6. executar backend completo e RLS/PostgreSQL 17;
7. executar frontend lint, typecheck, testes e build;
8. executar E2E Playwright IPv4 e IPv6;
9. construir imagem backend sem cache e confirmar UID `10001`;
10. validar Compose sem abrir `.env` real;
11. executar syntax/verify das units e scripts M08 em Linux controlado;
12. executar `git diff --check`, conflitos, segredos e inventário de migrations;
13. publicar um relatório de `RELEASE_CANDIDATE_PASS` ou bloquear.

Nenhum deploy ocorre nesta etapa.

## 11. Migrations e banco

Migrations devem ser tratadas individualmente. Antes de qualquer escrita:

- provar o projeto Supabase alvo;
- PROD permitido somente se o ref for
  `pffafnchtxbimpwyaczq` e houver autorização explícita;
- DEV é `cxmjojnocigekgcxhubi`, mas também exige gate nominal;
- ler o SQL do SHA candidato;
- registrar nome e SHA-256;
- reconciliar o ledger antes de usar qualquer executor;
- fazer backup fresco e provar restauração;
- aplicar uma migration por vez;
- validar schema, grants, RLS, advisors e comportamento;
- registrar rollback/forward-fix possível.

Pendências conhecidas que não podem ser ocultadas:

- drift histórico do ledger de migrations;
- hardening de `public.schema_migrations`;
- revisão de `public.current_igreja_id()`;
- migrations M01 e M06 ainda não autorizadas para ambiente real.

## 12. Deploy e ativação de produção

O runbook canônico atual é `docs/ops/PRODUCTION-RUNBOOK.md` em `origin/main`.
Ele precisa ser atualizado depois dos merges M08 e E-mail, porque hoje ainda
descreve Brevo como bloqueado apenas por `ALLOW_REAL_SENDS` e não contém todos
os contratos finais de readiness/monitoramento.

Sequência recomendada, cada linha com autorização separada:

1. preflight read-only de produção;
2. backup fresco, checksum e teste de restauração;
3. migrations aprovadas, uma por vez;
4. deploy backend do SHA candidato com envios externos fechados;
5. health local e público, readiness, processos e portas;
6. deploy frontend Vercel do mesmo SHA;
7. login, CORS, recuperação neutra e isolamento multitenant;
8. instalar/validar monitoramento e backup M08 sem instalação improvisada;
9. habilitar gate dedicado Brevo somente para allowlist canário;
10. um envio Brevo para destinatário de teste autorizado;
11. habilitar `ALLOW_REAL_SENDS` somente após decisão humana;
12. canários separados de Evolution, Asaas, Google e LLM;
13. habilitar broadcast assíncrono por gate próprio;
14. medir baseline M09 no SHA implantado;
15. manter rollback de backend, frontend e flags pronto durante a janela.

## 13. Evidência mínima para declarar a V1 encerrada

Registrar em um relatório final:

- SHA final de `main` e árvore limpa;
- PRs e commits incluídos;
- checks e testes locais/CI;
- migrations aplicadas e validações pós-migration;
- SHA do backend em produção;
- deployment e aliases Vercel;
- `/health` e `/ready` local/público;
- login e CORS;
- estado de cada flag de envio;
- canários realizados e destinatários sanitizados;
- backup fresco, checksum, offsite e restauração;
- monitor/timers/workers ativos;
- riscos residuais aceitos por humano;
- procedimento de rollback;
- confirmação de que nenhum segredo entrou em Git ou relatório.

O status final só pode ser `V1_ENCERRADA` quando não houver P0-P2 aberto e todos
os gates de produção autorizados tiverem evidência. Caso contrário usar
`V1_CODE_COMPLETE`, `V1_RELEASE_CANDIDATE` ou `V1_BLOCKED` honestamente.

## 14. Estimativa, não compromisso

Com execução estritamente serial:

| Cenário | Estimativa |
|---|---:|
| Melhor caso, sem novos findings | 3 a 4 dias úteis |
| Provável, com 1-2 ciclos corretivos | 5 a 8 dias úteis |
| Conservador, com bloqueios ambientais/produção | 8 a 12 dias úteis |

As maiores incertezas são M08, M01, reconciliação de migrations e os gates de
produção. Esta estimativa deve ser recalculada após cada `REVIEW_PASS`.

## 15. Tarefas Codex necessárias

| Frente | Task ID | Estado no snapshot |
|---|---|---|
| Coordenação | `019fcac8-89fb-7661-8e13-390901ad9cb2` | ativa |
| M01 | `019fde2d-6c4b-7621-acaa-7f380bf3bd0f` | aguardando prioridade |
| M06 | `019fde31-4247-7d63-a463-1b0f8698fcf4` | aguardando retry |
| M08 | `019fde09-2e44-79e2-b8a6-0abc29b3bf53` | reaberta: falha RLS integrada no cenário concorrente de 10 workers |
| M09 | `019fbb01-09d2-72f1-a50d-4bfb9c6c5801` | aguardando browser retry |
| Pessoa | `019ff1dd-b635-7520-9fcf-38f5d8ab85d6` | concluída: PR #252 mesclada em `91862f3` |
| E-mail | `019ff1d9-d317-7302-abd8-505013762b29` | bloqueada no commit local |
| Células | `019ff37c-f9e1-7562-ae9a-7556a11aec62` | proprietária, pausada |
| Revisão Células | `01a01025-c874-7c71-b581-72ac3b12bdb9` | pausada |

Não criar uma nova tarefa quando uma tarefa proprietária válida já existir.
Revisão independente é exceção e deve usar tarefa nova/read-only.

## 16. Prompt de bootstrap para outro agente

Copie o bloco abaixo ao entregar a coordenação:

```text
Gabarito em uso.

Você assume a coordenação do encerramento da V1 do PastorAI/Igreja 12.
Leia integralmente docs/ops/V1-FINALIZATION-MAP.md antes de agir.

Regras:
- execute uma única missão por vez;
- refaça fetch/preflight vivo antes de toda ação;
- não use a raiz principal se estiver detached ou suja;
- use worktree isolado;
- não use Graphify/CodeGraph sem provar raiz, commit, integridade e frescor;
- não abra .env nem revele segredos;
- revisão, correção, push, PR, Ready, merge, migration, deploy, flags,
  canário e produção são autorizações separadas;
- nunca toque Supabase/VPS/Vercel/Asaas/Evolution/Brevo/Google sem alvo e
  autorização nominal;
- atualize o mapa depois de cada resultado final.

Primeiro:
1. confirme origin/main e as PRs abertas;
2. confirme que somente a missão de maior prioridade está ativa;
3. compare o estado vivo com a seção 7;
4. se divergir, atualize o mapa sem apagar histórico;
5. continue da primeira missão não concluída.

Formato de retorno:
MISSAO: <nome>
STATUS: PASS, FAIL ou BLOCKED
SHA/PR/BRANCH: <valores exatos>
EVIDENCIAS: <testes e checks>
MUTACOES: <lista exata>
RISCOS: <residuais>
PROXIMO GATE: <uma única ação que exige autorização>
```

## 17. Histórico de atualização

- 2026-08-17: mapa criado a partir de GitHub, `origin/main`, tarefas Codex,
  relatórios das missões e runbooks lidos diretamente. Graphify/CodeGraph foram
  rejeitados por staleness. Paralelismo interrompido; Hotfix Pessoa definido
  como única missão prioritária e bloqueado pela sandbox revisora sem
  Docker/psycopg3, apesar de merge sintético limpo.
- 2026-08-19: mapa versionado em worktree limpo a partir do snapshot preservado
  da raiz antiga. Preflight vivo confirmou PR #252 mesclada em `91862f3` e
  PR #249 mesclada em `9e5bab9`. M08 recebeu `REVIEW_PASS` independente no
  SHA `5c7055d` e CI 3/3 verde antes de Ready e merge. P3/M01 passa a ser a
  primeira missão não concluída. Nenhuma migration, deploy, flag, canário ou
  produção foi acionada.
- 2026-08-19: a árvore de merge da PR documental #258 revelou falha RLS
  integrada em `test_agent_reply_concurrent_recovered_claims_execute_once_before_transport[10]`:
  `ia_execucao_ambigua` foi persistido onde o teste exige `ia`. P2/M08 foi
  reaberta; M01 não pode iniciar até reprodução, corretivo, CI e nova revisão.
