# Igreja 12 — Plano de simplificação e caminho para o MVP

Criado em 2026-09-23 sobre `origin/main` `9132d82`. **Aprovado pelo
proprietário em 2026-09-24**, com todas as decisões da seção 5. É o guia
operacional do projeto. `docs/ops/V1-FINALIZATION-MAP.md` passa a ser
histórico.

**Igreja piloto: Filadélfia** (já cadastrada, com dados e WhatsApp conectado).

Objetivo único do MVP: **uma igreja piloto conecta o WhatsApp, o agente de IA
responde às pessoas de forma útil e os pastores acompanham tudo no painel.**
Todo o resto vem depois.

---

## 1. Diagnóstico (fatos medidos no código)

### 1.1 O bot não responde no WhatsApp, e isso é bloqueio de código

Nenhuma configuração do `main` atual faz o agente responder:

- **Worker:** `queue_worker.py:2706-2713`. O `main()` só monta o agente pela
  sessão dedicada D2A. Sem `AGENT_RUNTIME_DATABASE_URL`, `agent_runner=None`:
  as mensagens são gravadas e nenhum turno de IA roda.
- **Login do agente:** mesmo com a URL preenchida, o papel `agent_runtime` foi
  criado como `NOLOGIN`, então a conexão falha e o turno vai para quarentena.
- **Runtime:** mesmo com login, `agent/runtime.py:601-621` devolve
  `handled=False` (`runtime_effects_unavailable`) **sempre**, antes de qualquer
  LLM ou envio.

O caminho antigo, que funcionava pela sessão principal com
`set_tenant_context` e RLS, continua intacto no código. Só os testes o usam.
Em resumo, **uma fundação de segurança substituiu o caminho que funcionava
antes de estar pronta, e o produto regrediu.**

### 1.2 Mesmo destravado, o agente quase não é IA

- `agent/nodes.py` é uma árvore fixa de respostas: termo LGPD, "consentimento
  registrado", resumo de relatório para líderes e uma saudação genérica.
- O LLM só reescreve a saudação do onboarding, e **a mensagem da pessoa é
  excluída do prompt de propósito** (`runtime.py:456`).
- Não há memória de conversa, perfil da igreja nem ferramentas em uso
  (`tool_calls=[]`).

### 1.3 O esforço foi para o processo, não para o produto

| Medida | Valor |
|---|---|
| Últimos 40 PRs | 30 de governança, migration, consentimento ou docs; 10 de produto |
| PRs de feature entre 14/09 e 22/09 | zero |
| Código de governança vs. produto (backend) | ~41 mil vs. ~57 mil linhas |
| Testes | 140 mil linhas, 2,1× o app; 41% são de governança |
| Hashes SHA-256 congelando arquivos | ~172, inclusive código de produto (agente, relatório de célula) |
| Documentação | 82 mil linhas, 68% de processo |
| Jobs de CI | 17, dos quais 12 são de governança |
| Worktrees e branches locais | 77 e 172 |
| Missões abertas | 9, todas de governança (migrations, F2, E4B) |

### 1.4 Migrations travadas

- Não existe hoje **nenhuma forma autorizada** de aplicar migration em DEV ou
  PROD (`backend/migrations/README.md`).
- O DEV tem 44 migrations pendentes e 8 aplicadas fora de ordem.
- Qualquer feature que precise mudar o banco está parada.

### 1.5 Produção instável

Houve ~30 incidentes "[Monitor] Produção indisponível" em um mês. O último
(#401) ficou aberto 7 dias. O deploy do backend é manual, pelo runbook.

### 1.6 Ruído que esconde bugs reais

As falhas dos testes locais (125 no backend, 54 no frontend) são todas de
ambiente, não do produto:

- `umask 0002` faz os scripts de migration recusarem arquivos graváveis pelo
  grupo;
- Python local 3.12, contra 3.13 no CI;
- Node local 26, contra 24 no CI.

Quando todo teste local "falha", ninguém percebe quando um bug de verdade
aparece.

---

## 2. Estratégias que deram errado

1. **Endurecer antes de funcionar.** Houve prova de proveniência, trust
   anchors, atestação por ambiente, catálogo de consentimento com sucessão e
   ledger imutável antes de a primeira igreja receber uma resposta do bot.
   Esse é o nível de rigor de um banco, aplicado a um piloto sem usuário.
2. **Fundações offline sem caller.** D3 (turn identity, plan, receipts), D6
   (coordenador de relatório), E4B (persistência de consentimento), a projeção
   privada e o executor catalog-bound são milhares de linhas que não entregam
   nada ao usuário e ainda precisam de manutenção.
3. **Documento virou teste.** Os testes leem textos de docs e congelam
   arquivos por hash, então mudar uma linha de código obriga a atualizar doc,
   hash e revisão. O custo de cada mudança triplicou.
4. **Gate de revisão para tudo.** A revisão independente é obrigatória mesmo
   em fatias pequenas, e as missões ficam presas em estados como
   "parecer conjunto" ou "merge retido".
5. **Multiagente com muitos papéis** (Maestri com 5 papéis), o que multiplica
   a cerimônia em vez da entrega.
6. **Sistema completo em vez de fatias verticais.** UV, capacitação, broadcast,
   billing, Brevo e consentimento por finalidade avançaram em paralelo, e o
   fluxo principal (WhatsApp → IA → painel) nunca fechou.

---

## 3. Nova metodologia (MVP enxuto)

### 3.1 Regras

1. **Uma fatia vertical por vez.** Cada fatia termina em algo que um pastor
   ou um contato consegue usar. Ordem da seção 4.
2. **`main` sempre implantável.** Branch curta por fatia, PR pequeno e merge
   no mesmo dia ou no dia seguinte.
3. **CI obrigatório só de produto:** `backend-tests`, `frontend-ci`,
   `e2e-critical` e `rls-integration`. Os jobs de governança ficam opcionais
   ou desligados.
4. **Documentação mínima:** este plano (vivo) e um registro curto por fatia em
   `docs/sprints/`. Sem ADR por fatia, sem mapa de 400 linhas e sem teste que
   lê documento.
5. **Um agente executor por fatia** (Claude Code direto nesta pasta). Revisão
   independente (Sarah) **só** para migration de produção e mudanças de
   RLS/autenticação.
6. **Testar como o usuário usa:** ao fim de cada fatia, mandar uma mensagem
   real para o número de teste e ver a resposta. Isso vale mais que 50 testes
   de hash.

### 3.2 Travas que ficam (mínimo inegociável)

| Trava | Por quê |
|---|---|
| RLS por `igreja_id` + `set_tenant_context` (`SET LOCAL ROLE authenticated`) | impede vazar dados entre igrejas |
| Segredos fora do git | básico |
| Opt-out por regex antes de qualquer resposta | LGPD e respeito à pessoa |
| `ALLOW_REAL_SENDS` + lista de igrejas piloto para envio real | kill switch global e escopo do piloto |
| `AgentConfig.ativo` por igreja | pausa o bot sem deploy |
| Backup do banco antes de cada migration em PROD | reversibilidade |
| Termo LGPD simples na primeira conversa | base legal mínima |

### 3.3 Travas pausadas (congeladas, não apagadas)

Ficam na branch `archive/governanca-2026-09` e deixam de ser mantidas e de
bloquear o `main`. Voltam, se voltarem, na Fase 5.

- E4B (catálogo, ledger e evidência de consentimento), consentimento por
  finalidade e `tarefas_operacionais`;
- D3 (turn identity, plan, receipts, outbox v2) e D6 (coordenador offline de
  relatório);
- sessão dedicada D2A e projeção privada do runtime;
- executor catalog-bound, atestação de ambiente, divergence v4, replay PG17 e
  missões F1/F2;
- testes que congelam hash ou leem texto de documento.

### 3.4 Migrations: processo simples

1. Arquivo `AAAAMMDD_HHMMSS_slug.sql` com `igreja_id`, RLS e rollback comentado.
2. O CI roda a migration num PostgreSQL descartável (reaproveitando o job já
   existente).
3. **DEV:** `MIGRATION_DATABASE_URL=... python scripts/migrate.py apply <arquivo> --yes`,
   que registra em `public.schema_migrations` na mesma transação.
4. **PROD:** backup, o mesmo comando, verificação e registro no log da fatia.
5. Uma vez só: reconciliar as 44 pendentes do DEV, ou recriar o DEV a partir
   do schema de PROD (é o mais simples).

---

## 4. Roteiro por fases

### Fase 0 — Destravar o processo (1 a 2 dias)

- [x] Proprietário aprova as decisões da seção 5.
- [x] Atualizar `CLAUDE.md` e `AGENTS.md` com as regras 3.1 a 3.4. Marcar
      `V1-FINALIZATION-MAP.md`, `MISSION-CONTROL.md` e `AI-BOOTSTRAP.md` como
      históricos.
- [x] Criar `archive/governanca-2026-09` e remover do `main` os testes de
      governança, hash e documento (58 arquivos, ~46 mil linhas) e 6
      workflows de CI de governança.
- [x] Processo simples de migration: `backend/scripts/migrate.py` e
      `backend/migrations/README.md` reescrito.
- [x] Ambiente local igual ao CI: `./test-local.sh` (Python 3.13 do
      `backend/.venv-runtime`, Node 24 do `.nvmrc`, `umask 022`). Backend e
      frontend (854 testes) verdes localmente.
- [x] Checks obrigatórios da `main`: `backend-tests`, `frontend-ci`,
      `e2e-critical`, `rls-integration` e Vercel.
- [ ] Limpar worktrees e branches mortas (só as limpas e já integradas).
- [ ] Reconciliar ou recriar o DEV (44 migrations pendentes) com
      `scripts/migrate.py status`. Precisa da URL do DEV, que fica com o
      proprietário.

**Pronto quando:** `./test-local.sh` passa, e o CI tem só os jobs
obrigatórios de produto.

### Fase 1 — O bot responde no WhatsApp (3 a 5 dias)

- [ ] Worker: se `AGENT_RUNTIME_DATABASE_URL` estiver vazio, usar a sessão
      principal (`session_factory` + `set_tenant_context`), o caminho que já
      existe e tem testes.
- [ ] Runtime: remover o retorno fixo `runtime_effects_unavailable` do caminho
      principal (ele continua só para a sessão dedicada).
- [ ] Nova env `WHATSAPP_REPLY_IGREJA_IDS`: envio real só para igrejas piloto,
      mesmo com `ALLOW_REAL_SENDS=true`.
- [ ] Verificar se a instância Evolution está conectada antes de enviar.
      Timeout ou 5xx vira uma nova tentativa limitada, em vez de "ambígua para
      sempre".
- [ ] Teste real: número de teste manda "oi", recebe o termo, responde "sim"
      e recebe a saudação.

**Pronto quando:** as mensagens para o número da igreja piloto recebem
resposta em menos de 10 s e aparecem no inbox do painel.

### Fase 2 — O agente fica útil (1 a 2 semanas)

- [ ] **O LLM responde à mensagem de verdade.** O prompt passa a levar a
      mensagem da pessoa, o perfil da igreja (horários de culto, endereço,
      células, tom, via `AgentConfig.comportamento`, editável no painel) e as
      últimas 10 mensagens da conversa (já persistidas; sem checkpointer).
- [ ] Guardrails simples: opt-out, handoff para humano quando a pessoa pede ou
      há sinal de crise (regex primeiro; Jev depois do DPA), tamanho máximo de
      resposta e proibição de inventar dados.
- [ ] Handoff: a conversa vai para `humano` e o líder vê o alerta no inbox.
- [ ] Ferramentas só de leitura: "qual célula perto de mim", "horário do
      culto".
- [ ] Aceite do termo mais robusto: "sim, mas não quero…" não conta como
      aceite (bug B4).

**Pronto quando:** 20 conversas de teste reais (visitante, pedido de oração,
dúvida de horário, opt-out, crise) têm respostas aprovadas pelo pastor.

### Fase 3 — Fluxo G12 mínimo ponta a ponta (2 semanas)

- [ ] **Ganhar:** um contato novo pelo WhatsApp vira visitante no painel, com
      a origem registrada.
- [ ] **Consolidar:** a fila de fonovisita e a atribuição de consolidador
      funcionam (já existem; validar com o piloto).
- [ ] **Célula:** relatório pelo painel (já existe) e aviso ao líder quando o
      relatório atrasar.
- [ ] Corrigir os bugs que o piloto encontrar, com a lista viva na seção 6.

### Fase 4 — Produção estável (em paralelo à Fase 3)

- [ ] Investigar a causa raiz dos ~30 incidentes do monitor (VPS, Evolution,
      Supabase, Redis).
- [ ] Deploy automatizado: uma GitHub Action ou um script único
      `deploy.sh` com build, restart, health check e rollback.
- [ ] Backup diário verificado e restauração testada uma vez.

### Fase 5 — Endurecimento (só com o MVP rodando e usado)

Priorizar pelo risco real observado: Clerk Production, Asaas real, ledger de
consentimento (E4B), sessão dedicada D2A, memória e RAG, Jev (depois do DPA),
UV e Capacitação, e Enviar editável.

---

## 5. Decisões do proprietário (aprovadas em 2026-09-24)

1. Aprovada a troca do guia operacional para este plano.
2. Autorizada a remoção dos testes de hash e de documento, e a desobrigação
   dos jobs de CI de governança.
3. Autorizado o processo simples de migration (3.4) e a reconciliação ou
   recriação do DEV.
4. Autorizada a volta do agente ao caminho de sessão principal com RLS
   (Fase 1), pausando a sessão dedicada D2A.
5. Igreja piloto: **Filadélfia**. O número de teste ainda precisa ser definido.
6. Maestri pausado até a Fase 3; trabalho direto, um agente por fatia.

## 6. Lista de bugs e lacunas (viva)

| # | Bug ou lacuna | Onde | Fase |
|---|---|---|---|
| B1 | Bot não responde: worker só liga a sessão D2A e o runtime devolve `handled=False` | `queue_worker.py:2706`, `runtime.py:601` | 1 |
| B2 | LLM ignora a mensagem da pessoa; respostas são texto fixo | `runtime.py:456`, `nodes.py` | 2 |
| B3 | Status da instância não é verificado antes do envio; 5xx vira `ia_ambigua` e nunca é reenviado | `queue_worker.py`, `evolution.py` | 1 |
| B4 | `is_acceptance` aceita "sim, mas não quero…" (só olha a 1ª palavra) | `domain/consent.py:88` | 2 |
| B5 | `classify_contact` marca "sem interesse" por substring ("empresa") | `domain/classification.py` | 2 |
| B6 | Nenhuma detecção de crise ou risco; vai para a saudação genérica | `agent/nodes.py` | 2 |
| B7 | Primeira mensagem sempre recebe o termo (o trigger não grava `consent_records`) | `migrations/0004_triggers.sql` | 2 |
| B8 | ~30 incidentes de indisponibilidade em um mês | produção | 4 |
| B9 | Deploy manual do backend | `deploy/` | 4 |
| B10 | 44 migrations pendentes no DEV e 8 fora de ordem | Supabase DEV | 0 |
| B11 | Testes locais falham por ambiente (umask, Python 3.12, Node 26) | máquina local | 0 |
| B12 | `V1-FINALIZATION-MAP.md` desatualizado (cita PR #257 como aberto) | docs | 0 |
| L1 | UV e Capacitação são placeholders; Enviar é só leitura | frontend | 5 |
| L2 | Apenas OpenAI como provedor do agente | `AgenteScreen.tsx` | 5 |
