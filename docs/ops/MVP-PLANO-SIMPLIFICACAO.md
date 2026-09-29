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
  finalidade (migrations d2b2 e d2b2b3 marcadas como pausadas em 27/09) e
  `tarefas_operacionais`;
- D3 (turn identity, plan, receipts, outbox v2) e D6 (coordenador offline de
  relatório);
- sessão dedicada D2A (migration d2a marcada como pausada em 27/09) e projeção
  privada do runtime;
- executor catalog-bound, atestação de ambiente, divergence v4, replay PG17 e
  missões F1/F2;
- testes que congelam hash ou leem texto de documento.

### 3.4 Migrations: processo simples

1. Arquivo `AAAAMMDD_HHMMSS_slug.sql` com `igreja_id`, RLS e rollback comentado.
2. O CI roda a migration num PostgreSQL descartável (reaproveitando o job já
   existente).
3. **Local** (desde 27/09, no lugar do DEV): `./dev.sh migrate` aplica as
   pendentes e `./dev.sh reset` recria o banco do zero com todas
   ([`AMBIENTE-LOCAL.md`](AMBIENTE-LOCAL.md)).
4. **PROD:** só no release: backup, `MIGRATION_DATABASE_URL=... python
   scripts/migrate.py apply <arquivo> --yes`, verificação e registro no log da
   fatia.
5. ~~Reconciliar ou recriar o DEV~~: substituído pelo ambiente local (§3.5).

### 3.5 Ambientes: local e produção (decisão de 27/09)

Até 27/09 só a produção funcionava de ponta a ponta, então todo teste real
acontecia nela, e cada mudança era feita duas vezes (DEV e PROD). Agora:

| | Local (`./dev.sh`) | Produção |
|---|---|---|
| Banco | Supabase local, recriado pelas migrations em ~1 min | Supabase PROD |
| Dados | fictícios, gerados por script | Filadélfia (reais) |
| WhatsApp | simulador ou chip de teste | número da Filadélfia |
| Quando muda | a cada alteração | só no release, quando o proprietário decide |

- [x] **1. Ambiente local** (`./dev.sh`): Supabase local, backend e workers em
      Docker com recarga automática, frontend e seed fictício com duas igrejas
      ([registro](../sprints/2026-09-27-ambiente-local.md)).
- [ ] **2. Simulador de WhatsApp:** página tipo WhatsApp que manda mensagens
      como se fossem da Evolution e mostra a resposta do bot, com o fluxo real
      (webhook, fila, agente, LLM); só a rede do WhatsApp é simulada.
- [ ] **3. Chip de teste:** número próprio de teste conectado por QR à
      Evolution local. Nunca o número da Filadélfia.
- [ ] **4. Release:** a Vercel deixa de publicar a cada merge e passa a
      publicar só a branch `producao`. Um script faz, na ordem: backup,
      migrations pendentes, backend, frontend e checagens. Backend e frontend
      sobem juntos (fim do B13), e a revisão da Sarah das migrations passa a
      ser uma por release.

O DEV na nuvem foi recriado em 27/09 como espelho do schema de PROD (PR #431)
e ficou parado. Não recebe mais migrations nem testes.

---

## 4. Roteiro por fases

### Fase 0 — Destravar o processo (1 a 2 dias)

- [x] Proprietário aprova as decisões da seção 5.
- [x] Atualizar `CLAUDE.md` e `AGENTS.md` com as regras 3.1 a 3.4. Marcar
      `V1-FINALIZATION-MAP.md`, `MISSION-CONTROL.md` e `AI-BOOTSTRAP.md` como
      históricos.
- [x] Criar `archive/governanca-2026-09` e remover do `main` os testes de
      governança, hash e documento (59 arquivos, ~46 mil linhas) e 6
      workflows de CI de governança.
- [x] Processo simples de migration: `backend/scripts/migrate.py` e
      `backend/migrations/README.md` reescrito. É o processo aprovado para a
      fatia de exclusão e reset de tenant.
- [x] Candidato local de exclusão e reset de tenant: transação única, manifesto
      externo durável, drain idempotente, bloqueios E4B e ledger no reset total.
      Continua sem banco compartilhado, provedor ou execução real.
- [x] Ambiente local igual ao CI: `./test-local.sh` (Python 3.13 do
      `backend/.venv-runtime`, Node 24 do `.nvmrc`, `umask 022`). Backend e
      frontend (854 testes) verdes localmente.
- [x] Checks obrigatórios da `main`: `backend-tests`, `frontend-ci`,
      `e2e-critical`, `rls-integration` e Vercel.
- [ ] Limpar worktrees e branches mortas (só as limpas e já integradas).
- [x] ~~Reconciliar ou recriar o DEV~~: substituído em 27/09 pelo ambiente
      local (§3.5). O banco local nasce das migrations, com os dados de
      referência das seeds, e o DEV deixa de ser pré-requisito da próxima
      migration em PROD. No mesmo dia o DEV na nuvem foi recriado como espelho
      de PROD (PR #431) e depois parado.

**Pronto quando:** `./test-local.sh` passa, e o CI tem só os jobs
obrigatórios de produto.

### Fase 1 — O bot responde no WhatsApp (3 a 5 dias)

- [x] Worker: o agente roda na sessão principal com o tenant fixado
      (`mark_tenant_scoped` + `require_tenant_scope`, RLS por `igreja_id`).
      A sessão dedicada D2A está pausada e `AGENT_RUNTIME_DATABASE_URL` é
      ignorada.
- [x] Nova env `WHATSAPP_PILOTO_IGREJA_IDS`. O WhatsApp automático (agente,
      aviso de billing e SLA) só vale para igrejas piloto, mesmo com
      `ALLOW_REAL_SENDS=true`. Envios feitos por uma pessoa no painel não
      dependem da lista.
- [x] Nova env `WHATSAPP_SLA_ENABLED` (desligada). Cobranças de SLA por
      WhatsApp só com ela ligada **e** igreja piloto. Enquanto estiver
      desligada, as cobranças ficam pendentes; ao ligar, o acúmulo sai de uma
      vez, então limpe a fila antes. Aviso de agenda e broadcast agendado têm
      flags próprias (`AGENDA_NOTIFY_ENABLED`, `BROADCAST_ASYNC_ENABLED`) e não
      passam pela lista.
- [x] Verificar a instância Evolution antes de enviar; timeout ou 5xx vira
      nova tentativa limitada, em vez de "ambígua para sempre" (B3; fatia
      própria). Implementação local em 25/09: até cinco tentativas por envelope,
      depois dead-letter; sem teste real ou deploy. Timeout após envio pode
      duplicar resposta, pois a Evolution não garante idempotência nesse fluxo.
- [ ] **Ligar na Filadélfia e testar com número real** (passo a passo abaixo). Ligado em 27/09. No teste da equipe interna (27/09), a resposta chegou ao celular em ~28 s; a meta de < 10 s ainda não foi atingida (banco em us-west-2, tarefa própria).

**Pronto quando:** as mensagens para o número da Filadélfia recebem resposta
em menos de 10 s e aparecem no inbox do painel.

**Medição de 27/09 (local, latência de PROD simulada):** com o banco em
us-west-2 a ~185 ms por ida, o código em produção (`e6aafc2`) faz 152 a 167
idas ao banco por mensagem, 29 a 33 s, o que bate com os ~28 s do teste real.
Depois dos cortes do PR #424, 114 a 130 idas, 21 a 26 s. A meta de 10 s
depende de aproximar servidor e banco (B17,
[registro](../sprints/2026-09-27-latencia-banco-round-trips.md)).

#### Passo a passo para ligar na Filadélfia (proprietário)

**Decisão de 26/09: piloto apenas com testadores internos da equipe pastoral.**
Não divulgar o número ao público. O baseline corrigido identificou 5 de 43
casos de crise no corpus sintético; a regex não sustenta abertura pública.
A restrição permanece até a nova detecção de risco/handoff passar pela
avaliação e revisão definidas abaixo. Deploy ou merge não removem essa restrição.

Ordem revisada em 26/09: o banco vem antes do código, porque o `main` mapeia
colunas e tabelas que o backend antigo não usava. Estado real depois da sessão
operacional de 26/09 (registro em
[`2026-09-26-prod-sessao-a-ledger-e-deploy.md`](../sprints/2026-09-26-prod-sessao-a-ledger-e-deploy.md)):

1. ✅ **Backup** do banco de PROD: `pastorai-backup-20260926T200839Z` (antes do
   ledger) e `pastorai-backup-20260926T210416Z` (antes da migration S2), com
   SHA-256 conferido contra o `.sha256` e o manifesto.
2. ✅ **Banco de PROD**, com revisão da Sarah em cada escrita:
   - Ledger `public.schema_migrations` criado com registro nominal de 69
     migrations: 63 por prova de objeto no catálogo e 6 só de dados por
     evidência histórica (exceção aceita pelo proprietário). Já estavam
     aplicadas, entre outras, `20260822_225752`, `20260824_180000`,
     `20260826_030508` e `20260826_094317`.
   - Aplicada `20260926_191500_agent_public_profile` (S2), com backup antes,
     `lock_timeout` de 2 s na mesma transação e conferência de permissões
     antes e depois. Exceção única ao "DEV primeiro": a próxima migration em
     PROD só depois do DEV reconciliado.
   - `migrate.py status` lista 8 pendentes, **nenhuma para aplicar em lote**
     (cada uma tem gate próprio): `20260711_023515` e `20260711_152127` (só
     dados, sem prova de aplicação), d1a, d2a, d2b2, d2b2b3, `20260925_183811`
     e `20260926_120446`.
   - Correção do plano anterior: o `main` **não** depende da
     `20260925_183811` para login, `/me` ou o Console. Sem ela, só a
     **exclusão de igreja** falha (500 com rollback se a igreja tiver admin de
     plataforma; sem admin, apaga usuários no Clerk e arquivos no Storage mesmo
     com `ALLOW_REAL_SENDS=false`). **Não excluir igreja** até o gate dessa
     migration. A `20260926_120446_platform_jev_settings` é opcional: sem ela o
     console do Jev mostra só o ambiente e salvar responde 409.
3. ✅ **Deploy** feito em 26–27/09: backend `e6aafc2` (main pós-#423) nos quatro
   processos, com `ALLOW_REAL_SENDS=false` na troca; `/admin/jev` sem login
   responde 401. Texto original do passo: deploy do backend com o `main` atualizado, pelo runbook de produção
   (rebuild da imagem; reiniciar `backend`, `queue-worker` e `cron-worker`),
   ainda com `ALLOW_REAL_SENDS=false`: a prova pós-restart do runbook aborta
   se os envios estiverem abertos. Confira que
   `https://api.igreja12.com.br/admin/jev` sem login responde 401, não 404
   (404 = backend antigo, bug B13).
4. **Painel da Filadélfia → Agente** (27/09: credencial OpenAI ativa e validada e
   agente ativo; informações públicas ainda vazias): credencial OpenAI validada e ativa,
   agente **ativo**, comportamento com o tom da igreja.
5. ✅ **`.env` de PROD** (27/09, 01:18 UTC: reaberto só para a Filadélfia, com
   aceite de risco do proprietário; SLA, Asaas, Brevo, broadcast, agenda e Jev
   desligados) — passo separado, depois do deploy verificado:
   - `WHATSAPP_PILOTO_IGREJA_IDS=<igreja_id da Filadélfia>` (copie do Admin
     Master);
   - `ALLOW_REAL_SENDS=true`. Isso também libera envios feitos por pessoas
     no painel de qualquer igreja: inbox, broadcast "agora" e LLM do
     assistente. Brevo, Asaas e aviso de agenda têm flags próprias
     desligadas;
   - `WHATSAPP_SLA_ENABLED=false` por enquanto.

   Reinicie os serviços.
6. **Teste:** de um celular que não seja o da igreja, mande "oi" para o
   número da Filadélfia. Esperado: o termo LGPD. Responda "sim". Esperado:
   a saudação. As duas conversas aparecem no inbox. Não clique em "Assumir
   (pausar IA)" durante o teste: isso cancela a resposta do robô.
   27/09: resposta entregue em ~28 s; antes, foi preciso reconectar a Evolution,
   que estava "Online" sem receber desde 03/09 (registro da sessão).
7. **Desligar rápido, se precisar:** agente inativo no painel, lista vazia
   ou `ALLOW_REAL_SENDS=false` e reiniciar.

Nesta fase o agente ainda responde com textos fixos, e o LLM só reescreve a
saudação. Responder de verdade à mensagem da pessoa é a Fase 2.

### Fase 2 — O agente fica útil (1 a 2 semanas)

Fatia 1 implementada em código, com testes sintéticos e sem implantação:
[registro de 26/09](../sprints/2026-09-26-mvp-fase2-fatia1.md). Os itens
marcados abaixo descrevem o código; o aceite de 20 conversas reais continua
pendente. Não há garantia geral de factualidade por teste de prompt.

- [x] **O LLM responde à mensagem de verdade.** O prompt passa a levar a
      mensagem da pessoa, o estilo da igreja em `AgentConfig.comportamento`
      e as últimas 10 mensagens persistidas da conversa. Desde PR421, o bloco
      de informações públicas é removido do prompt; as consultas reconhecidas
      respondem pelo cadastro validado, sem LLM ou checkpointer.
- [x] Guardrails simples: opt-out, handoff para humano quando a pessoa pede ou
      há sinal de crise (regex primeiro; Jev depois do DPA), tamanho máximo de
      resposta e proibição de inventar dados.
- [x] Handoff: a conversa vai para `humano` e o líder vê o alerta no inbox.
- [x] Consultas públicas somente leitura: horário do culto, endereço da igreja
      e indicação de célula por bairro explicitamente publicado no perfil do
      agente. Respostas determinísticas, sem LLM nem alterações cadastrais.
      Contrato inicial: [fatia 2](../sprints/2026-09-26-mvp-fase2-fatia2.md).
- [x] **S2 em produção:** painel/API de campos públicos estruturados,
      migration tenant/RLS, perguntas naturais de culto e remoção de Cf no
      legado ([registro da fatia](../sprints/2026-09-26-mvp-s2-perfil-publico.md)).
      Sarah GO no código `fe544d7`. Em 26/09: migration `20260926_191500`
      aplicada em PROD com backup e revisão da Sarah, PR #423 integrado e
      backend `e6aafc2` implantado
      ([registro da sessão](../sprints/2026-09-26-prod-sessao-a-ledger-e-deploy.md)).
      Informações públicas da Filadélfia ainda vazias no painel.
      A S2b aprovada abaixo substitui a fonte pública por Igreja/Celula e
      mantém novo gate de migration/deploy. Esta atualização da PR426 não
      aplicou banco compartilhado nem fez deploy.
- [ ] Proximidade geográfica de células: o cadastro atual não fornece distância
      nem política pública para endereços residenciais; indicação por bairro
      não representa a célula mais próxima.
- [x] Aceite do termo mais robusto: "sim, mas não quero…" não conta como
      aceite (bug B4).

#### Decisão aprovada: agente com decisões tipadas e privilégios

Plano aprovado pelos conselheiros, com ajustes de 26/09:
[contrato S1/S2/S3](mvp-fase2-agente-inteligente-plano.md). Substitui a proposta
LLM + moderação e a sequência histórica J1/J2 abaixo para o caminho ativo.
Uma PR por fatia:

- S1: três sinais Jev tier A (crise, humano, provável opt-out), fail-safe,
  `JEV_ENABLED_IGREJA_IDS` vazia e distinta da sombra; resposta LLM preservada.
  Opt-out inferido solicita uma única confirmação SAIR, sem aplicar saída.
  Somente palavra explícita/regex persiste opt-out diretamente.
- S2: campos públicos estruturados no painel/API, com migration e RLS,
  substituem bloco livre de comportamento; descartar caracteres `Cf` no legado.
  Perguntas `que horas comeca o culto?`, `que horas e o culto`, `horario do culto`
  e `quando e o culto`, com/sem acento e pontuação, consultam cadastro público
  ou retornam ausência, sem cair no LLM sem horário.
- S3: identidade/papel derivados no servidor e ferramentas por papel, conforme
  a revisão WhatsApp-first de 27/09 abaixo; Clerk para leituras sensíveis,
  confirmação explícita por ação ministerial comum. Perguntas dependentes Jev
  B/C/D somente depois das respectivas decisoras.

Dev/holdout sintéticos ficam congelados antes de ajustar perguntas e limiares.
Ativação exige holdout aferido (crise recall >=90%, FPR<10%, humano recall>=85%,
com Wilson95%), DPA e decisão nominal de Raniel, além dos gates técnicos.
Mock verde não aferiu qualidade do Jev. Medir handoff total no holdout; no
piloto, mais de 30% das conversas avaliadas na janela diária exige pausa e
revisão. Corpus enriquecido não estima prevalência real. Sem provider real,
DEV ou PROD nesta preparação; piloto continua interno, sem divulgação pública.

#### Ordem WhatsApp-first aprovada por Raniel, 27/09/2026

Base: [PRD0611, delta-046/047/052](../Docs20260611_163530/PRD20260611_163530.md)
e [cobertura](../ai/PRD-COVERAGE.md). O agente é o assistente do sistema:
rotinas comuns pelo WhatsApp; painel para configuração, governança e ações
sensíveis. Esta ordem substitui Clerk obrigatório para todo dado não público,
sem declarar as próximas verticais implementadas.

0. **Agora: S2b aprovada**, Igreja/Celula como fonte pública, oferta determinística
   de secretaria e UI protegida por suporte da API. Validar em ambiente local
   descartável e no CI, conforme §3.5. O [roteiro DEV histórico](s2b-church-cell-20260927/RECONCILIAR-DEV-RANIEL.md)
   foi supersedido; DEV na nuvem não é pré-requisito de merge ou migration.
   Migration/deploy PROD continuam sujeitos ao gate humano próprio de release.
1. **S3 revisada:** `PrivilegeContext` derivado no servidor por telefone único,
   vínculo ativo `app_users.pessoa_id -> user_roles` e `celulas.lider_id`;
   ambiguidade encaminha a humano. Ações ministeriais comuns por telefone
   exigem confirmação explícita por ação; leituras sensíveis exigem Clerk;
   finanças nunca são liberadas por telefone. Revalidar tenant/papel no uso.
   [Plano aprovado com ajustes](mvp-s3-whatsapp-first-plano.md): roteamento BYO
   com enum fechado sem depender de Jev; plataforma genérica de proposta,
   confirmação única em até 10 minutos e comprovante após commit, provada
   somente com `registrar_decisao` e `marcar_presenca`. Jev B/C/D continua
   inerte até seus gates. Flag `AGENT_PRIVILEGE_ENABLED_IGREJA_IDS` vazia e
   constante `PRIVILEGE_APPROVED_RELEASE_ID=None` mantêm a S3 inerte;
   ativação interna sem Jev exige ordem nominal e testes, sem DPA TypeSafe.
2. **V1: relatório de célula pelo WhatsApp**, primeira vertical delta-052.
   [Plano aprovado com ajustes](mvp-v1-relatorio-celula-whatsapp-plano.md),
   dividido em duas PRs: V1a entrega texto, lembrete, extração, resumo/correção,
   confirmação S3, serviço humano e comprovante após commit; V1b acrescenta áudio.
   A fonte de consentimento no MVP é o termo LGPD existente, com versão,
   timestamp e revogação persistidos, negando quando ilegível. E4B e
   `tarefas_operacionais` continuam pausados; nenhum mint ou bypass do legado.
   Primeiro lembrete tem aviso registrado e PARAR LEMBRETES persistido;
   SAIR global prevalece. Oferta é só total declarado em centavos, sem
   operação financeira; decisões são agregadas. Confirmação em10min e
   rascunho de24h; até quatro extrações com tetos do plano.
   V1b exige aceite separado versionado, binário/transcrição temporários
   por24h e relatório confirmado independente do áudio depois da purga.
   Flag `CELL_REPORT_ENABLED_IGREJA_IDS` vazia e release em código
   `CELL_REPORT_APPROVED_RELEASE_ID=None` mantêm a entrega inerte.
3. **V2: agenda**, [plano aprovado com ajustes](mvp-v2-agenda-whatsapp-plano.md).
   V2a entrega primeiro consulta por papel, título institucional validado e fallback
   seguro; [V2b integrada via #435](v2b-agenda-20260927/README.md)
   reúne lembretes, outbox única e cutover V1a/EVT-7, sem replay
   histórico, com unicidade por tenant/destinatário/ocorrência/finalidade, janela
   08:00 inclusive até 21:00 exclusive e teto agenda de dois/dia.
   [Registro V2a](../sprints/2026-09-27-whatsapp-agenda-v2a.md): implementação
   autorizada; #434 foi integrada à main em `87e13da`, sem deploy ou ativação.
   Desenvolvimento local e release em lote seguem a decisão de 27/09;
   #435 foi integrada em `8c6cc3c`, sem migration aplicada ou ativação.
4. **V3: consolidação**, [plano aprovado](mvp-v3-consolidacao-whatsapp-plano.md)
   com consulta, fonovisita e atribuição pelo WhatsApp, confirmação S3 e alertas
   pela outbox comum. Primeiro nome somente ao responsável atual em conversa
   individual; coordenação sem atribuição recebe códigos/contagens. [Candidato
   validado localmente](v3-consolidacao-20260928/README.md), base original PR435 `342f0ce`,
   sem ativação, migration compartilhada ou conclusão do domínio presumida.
5. **V4: membro**, presença, expectativa de visitante e pedido de oração.
6. **Trilha UX do painel**, quando houver capacidade, sem travar as verticais.

Cada item segue plano de até 40 linhas aprovado pelos conselheiros, PR, Sarah,
merge pelos gates e deploy com gate próprio. O plano S2b já está aprovado;
S3 e V1 também possuem planos aprovados; demais fatias exigem seus planos. Mudança backend exige aviso antes
do merge e deploy manual; nova migration mantém backup e gate de banco.
Nenhum merge, aprovação ou teste autoriza provedores/envios reais.

#### Trilha Jev histórica (J0/sombra), 26/09

O Jev não gera texto: devolve probabilidades para perguntas como "é crise?".
Custa cerca de US$ 0,00003 por mensagem e acrescenta cerca de 1 s por
chamada, então **custo não é a alavanca; o ganho é acertar** onde a regex erra
(B4, B5, B6, B15). O custo de IA acumulado da plataforma é US$ 0,03.

- [x] **J0, avaliação offline:** `backend/scripts/jev_eval.py` com corpus
      sintético pt-BR rotulado (`backend/scripts/data/jev_corpus_v1.jsonl`).
      Sem chave, mede só as regras atuais e serve de critério para corrigir
      B4, B5, B6 e B15. Com chave (`--jev`, teto de US$ 0,05), mede o Jev em
      instruções PT e EN. GO: crise com recall ≥ 95% e ≤ 5% de falso alarme,
      zero falso opt-out no limiar, veto de todo "sim, mas não…", CSIM sem os
      falsos positivos de substring. O corpus ainda precisa de frases
      escritas pelo pastor antes de uma decisão final.
- [x] **Configuração pelo console (26/09):** chave da TypeSafe (cifrada com
      `SECRETS_ENCRYPTION_KEY`, nunca devolvida), modelo, timeout, data do DPA e
      igrejas em modo sombra, que só aceitam igreja com DPA informado. Campo
      vazio usa o ambiente. `ALLOW_REAL_SENDS` e a URL da API ficam só no
      servidor.
- [ ] **J1, sombra na Filadélfia:** só com J0 = GO, chave, DPA com a TypeSafe,
      termo LGPD que cite IA e processador estrangeiro e backend atualizado.
      Chamada depois do envio da resposta, em transação própria (nunca na
      transação do turno), cliente HTTP persistente, versão do modelo fixada e
      custo em `ai_usage_logs`. A configuração do console vem de
      `effective_settings` numa sessão de plataforma, passada como
      `settings=`: a sessão com escopo de tenant roda como `authenticated`,
      que não lê `platform_jev_settings` (achado da Sarah, 26/09). Termina por
      volume (≥ 300 turnos), não por tempo.
- [ ] **J2, proposta histórica substituída pelo plano S1 acima:** um por vez, cada um com flag: crise → handoff
      e alerta; CSIM só com confirmação do Jev (sem Jev, não marca); veto de
      aceite (o Jev nunca concede); opt-out aditivo (probabilidade alta
      aplica). Chamada antes do turno com prazo total de 1,5 s e as regras
      como piso.

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
- [x] `queue-worker` espera e tenta de novo em timeout ou queda transitória
      do Redis, em vez de encerrar o processo (incidente de 27/09, B16).
      Implantado em PROD em 27/09 (`eb5a09b`). O travamento vinha do backup
      diário das 06:15 UTC, que pausa o Redis por ~9 s.
      [Registro](../sprints/2026-09-27-queue-worker-redis-transitorio.md).
- [x] Menos idas ao banco por requisição, em código (PR #424, Sarah GO,
      exceção D2A aceita pelo proprietário; entra em produção no próximo
      deploy): contexto de tenant numa instrução, ping só em conexão parada,
      preflight CORS por 2 h.
      `/auth/me` de 1,3 s para 0,75 s com 185 ms simulados
      ([registro](../sprints/2026-09-27-latencia-banco-round-trips.md)).
- [ ] Decidir a infraestrutura (B17): banco em São Paulo (recomendado) ou
      servidor em Oregon. Antes, medir do VPS a latência de um projeto vazio
      em sa-east-1.
- [ ] Deploy automatizado: é o release do item 4 da §3.5 (Vercel só na branch
      `producao` e um script único com backup, migrations, backend, frontend,
      health check e rollback).
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
7. (27/09) Desenvolvimento e testes no ambiente local; PROD só por release
   (§3.5). A frente do DEV na nuvem foi encerrada e o DEV ficou parado.

## 6. Lista de bugs e lacunas (viva)

| # | Bug ou lacuna | Onde | Fase |
|---|---|---|---|
| B1 | Bot não responde: worker só liga a sessão D2A e o runtime devolve `handled=False` | `queue_worker.py:2706`, `runtime.py:601` | 1 |
| B2 | LLM ignora a mensagem da pessoa; respostas são texto fixo | `runtime.py:456`, `nodes.py` | 2 |
| B3 | Status da instância não é verificado antes do envio; 5xx vira `ia_ambigua` e nunca é reenviado | `queue_worker.py`, `evolution.py` | 1 |
| B4 | `is_acceptance` aceita "sim, mas não quero…" (só olha a 1ª palavra) e recusa "claro" e "pode ser", reenviando o termo em loop | `domain/consent.py:88` | 2 |
| B5 | `classify_contact` marca "sem interesse" por substring ("empresa") | `domain/classification.py` | 2 |
| B6 | Nenhuma detecção de crise ou risco; vai para a saudação genérica | `agent/nodes.py` | 2 |
| B7 | Primeira mensagem sempre recebe o termo (o trigger não grava `consent_records`) | `migrations/0004_triggers.sql` | 2 |
| B8 | ~30 incidentes de indisponibilidade em um mês | produção | 4 |
| B9 | Deploy manual do backend | `deploy/` | 4 |
| B10 | ~~44 migrations pendentes no DEV e 8 fora de ordem~~ Resolvido em 27/09: o DEV na nuvem parou e o banco local nasce das migrations (§3.5) | Supabase DEV | 0 |
| B11 | Testes locais falham por ambiente (umask, Python 3.12, Node 26) | máquina local | 0 |
| B12 | `V1-FINALIZATION-MAP.md` desatualizado (cita PR #257 como aberto) | docs | 0 |
| B13 | Frontend (Vercel, automático) à frente do backend (deploy manual, último release registrado de 26/08): rotas novas dão 404, como "Não foi possível carregar o status do Jev". Mensagem clara no console em 26/09; a correção é o deploy | deploy, `admin-api.ts` | 1 |
| B14 | Custo de IA (em US$) exibido como R$ no console. Corrigido em 26/09 | `AdminConsole.tsx`, `ChurchPage.tsx` | 0 |
| B15 | `is_optout_request` perde "me tira da lista", "pare" e "stop"; `looks_like_report` responde "Relatório recebido!" a "vou mandar o relatório amanhã" e troca números no formato em linhas | `domain/consent.py`, `domain/report.py` | 2 |
| B16 | `queue-worker` caiu em PROD (27/09) com `TimeoutError` do Redis: 2 s de margem entre o BRPOPLPUSH e o `socket_timeout`, e nenhum retry no laço. Corrigido e implantado em 27/09 (`eb5a09b`). O travamento vem do backup diário, que pausa o Redis ~9 s às 06:15 UTC | `queue_worker.py` | 4 |
| B17 | VPS no Brasil e banco em us-west-2 (~185 ms por ida): tela 0,8 a 1,9 s por chamada e bot 21 a 26 s por mensagem; impede o aceite da Fase 1 | infra (VPS, Supabase) | 4 |
| L1 | UV e Capacitação são placeholders; Enviar é só leitura | frontend | 5 |
| L2 | Apenas OpenAI como provedor do agente | `AgenteScreen.tsx` | 5 |
