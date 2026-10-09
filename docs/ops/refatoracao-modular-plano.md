# Plano de refatoração modular e DEV online — Igreja12/PastorAI

## Contexto

O objetivo é desenvolver, testar, entender e publicar mudanças com menos tempo e esforço, sem perder funcionalidades, dados ou segurança. Já está decidido: a migração Neon foi cancelada; haverá DEV online separado de PROD, com dados fictícios e integrações simuladas; o DEV será publicado automaticamente; PROD só por uma ação explícita; e mudanças reversíveis não precisam de aprovação a cada passo.

Esta revisão é diagnóstico e desenho. Nada foi implementado, provisionado ou operado, e não houve acesso remoto. Os fatos abaixo vêm do código; o estado vivo de PROD não foi verificado.

**Base verificada.** `main` em `d36ab813`. Revisão de 08/10/2026, corrigida em 09/10/2026 (ver o fim do documento). Os números de linha citados valem para esse SHA.

---

## 1. Diagnóstico prioritário

### 1.1 Fluxo principal (fatos)
1. **Webhook.** `routers/whatsapp.py:333` autentica por HMAC/token (`:392-404`), limita o tamanho e chama `WebhookQueue.enqueue` → 202. O router importa a fila de dentro do worker (`whatsapp.py:43`).
2. **Fila.** Lista Redis própria em `workers/queue_worker.py:1714` (`lpush`/`brpoplpush`, 5 tentativas, dead-letter). `QueueWorker.handle_envelope` (`:2509`) → `claim_processing` (`:1995`) → `ingest_message_event_ex` (`:1226`).
3. **Ingestão e tenant.** Resolve a `WhatsappConnection` e chama `promote_to_tenant` (`db/tenant_session.py:196`, GUC + `authenticated`, reaplicado a cada transação). Depois cria ou dedupe Pessoa, Conversation e Message (`:1398-1455`). O painel usa outro mecanismo: `set_tenant_context` (`deps.py:171`, `db/rls.py:39`).
4. **Agente.** `run_agent_for_message` (`:4538`) checa a lista piloto (`config.py:184`) e tenta três caminhos, todos no mesmo worker: privilegiado (`agent/privileged_turn.py` + `services/agent_privilege_catalog.py`), Tier A/Jev (`:4093`) e o legado LangGraph (`agent/runtime.py:1507` → `graph.py:166`, nós fixos em `nodes.py`).
5. **Domínio.** O caminho privilegiado chama serviços compartilhados com o painel: `ministerial_actions.py`, `consolidation_workflow.py`. Não existe camada de repositório; routers, serviços, agente e workers fazem `select()` direto.
6. **Resposta.** Máquina de estados da intenção de resposta (`domain/agent_reply.py:10-19`) com chave idempotente (`:2724`), dedupe no Redis e no banco (`:755-776`), handoff revalidado antes do HTTP (`:3622`), opt-out (`:3330`) e `EvolutionClient.send_agent_text` (`services/evolution.py:446`), que é bloqueado por `ALLOW_REAL_SENDS` dentro do cliente.
7. **Painel.** `routers/conversations.py` (inbox, handoff, envio humano), `work_queue.py`, `dashboard.py`, `contacts.py`. O frontend centraliza as chamadas em `src/lib/*-api.ts` via `authedFetch` (`dashboard-api.ts:163`).

### 1.2 Obstáculos, em ordem de custo real

| # | Obstáculo | Evidência | Tipo |
|---|---|---|---|
| D1 | **`main` e PROD divergem; publicar virou projeto.** Pelo registro de 02/10, a API de PROD roda um backport (`07a3f4d9`) sobre o legado `eb5a09b`, e os workers rodam o legado. PROD não tem `notification_outbox`, `cell_report_reminders` nem `consolidation_whatsapp_activation`, que a `main` exige. O frontend sai da `main` automaticamente pela Vercel; o backend é manual (B13). | `deploy/BACKEND-MAINTENANCE-RELEASE.md:10-22`, commit `6ebab19e`, `MVP:305-312` | Fato documental; PROD vivo não verificado |
| D2 | **Não há ambiente integrado.** O `e2e-critical` roda contra uma API mock (`frontend/playwright.config.ts:35-48`). Os testes de turno usam provedor, fila e TestClient sintéticos. O simulador de WhatsApp está pendente (`MVP:187`). A stack local roda um worktree por vez (`AMBIENTE-LOCAL.md`). | Fatos | Fato |
| D3 | **Cerimônia acima do plano enxuto.** 34 dos últimos 100 commits são de governança sem código de produto, e 31 são só docs. Cada feature carrega de 3 a 16 arquivos de evidência. O registro de `698f9d43` cita revisão independente "LENTE", 35 pins, hashes e "autorização nominal de merge". O MVP contradiz a si mesmo: `:511-516` exige conselheiros e Sarah por item, contra `:124-126`. O `sarah.md:3` cobre releases e atestações. | `git log`, `docs/sprints/2026-10-02-mvp-own-visitor-expectation.md` | Fato |
| D4 | **Uma ação do agente custa cerca de 8 camadas e uma migration em PROD.** `698f9d43` mexeu em 16 arquivos (7 de produto); o nome da ação aparece em 5 arquivos. A lista de ações é um CHECK no banco, então cada ação nova exige migration (`migrations/20261002_173000…sql`). `privileged_turn.py` conhece cada funcionalidade pelo nome (`:65-293`) e importa privados do worker (`:36`, `:722`, `:907`). | Fato | Fato |
| D5 | **Regras duplicadas.** (a) `registrar_decisao` existe em `agent/tools.py:78` e em `ministerial_actions.py:112`, e as cópias já divergem. (b) "Vincular pessoa à célula" tem 3 cópias (`tools.py:196`, `contacts.py:964`, `cells.py:1048`). (c) A checagem de opt-out está espalhada em 7 lugares sem predicado único. (d) A expectativa de visitante tem a regra 3 vezes, e o humano e o agente divergem sobre reunião passada (`ministerial_actions.py:98` vs `cell_meetings.py:~547`). (e) O frontend espelha permissões e a regra de promoção (`permissions.ts:56`, `contacts-api.ts:566` = `domain/pipeline.py:62`). | Fato | Fato |
| D6 | **Testes frágeis que sobraram.** O sentinela de migrations (`deploy/tests/test_backend_schema_pg17.py:36-40`, `==82`) obrigou um commit extra (`eb620afd`). Há hash de docstring (`test_source_contact_privacy.py:31-69`), testes que leem runbook ou YAML (`test_production_runbook.py`, `test_rls_ci_contract.py`), `inspect.getsource` em 4 arquivos e `readFileSync` de TSX em 6. O schema está declarado em 5 lugares sem teste ORM×SQL (`models.py`, migrations, `conftest_rls.py:81-198`, `check_backend_schema.py`, `backend-release.sh:36`). | Fato | Fato |
| D7 | **Arquivos-deus e dependências invertidas.** `queue_worker.py` tem 4.918 linhas e 6 responsabilidades. Serviços importam o worker (`cell_report_audio_service.py:2158…`). 9 serviços levantam `HTTPException`. Há dois `PrivilegeContext` (`domain/agent_authz.py:80`, `services/whatsapp_privilege.py:97`). Os routers têm SQL e regra (`platform_admin` 111 ocorrências, `subscription` 73). | Fato | Fato |
| D8 | **Configuração espalhada.** Existem 2 `BaseSettings` (`config.py:51`, `semantic_triage.py:86`). 7 listas por igreja são lidas por `os.environ` fora do Settings. O padrão "constante `*_APPROVED_RELEASE_ID=None` no código + env" está copiado em 4 serviços (`whatsapp_agenda.py:33`, `consolidation_whatsapp.py:14`, `cell_report_whatsapp.py:42`, `whatsapp_privilege.py:48`). 3 lugares leem `allow_real_sends` sem o guard (`consolidation_whatsapp.py:93`, `broadcast_worker.py:57`, `broadcasts.py:239`). | Fato | Fato |
| D9 | **Código sem uso no `main`.** | | Fato (grep) |

Detalhe de D9:
- **Comprovadamente sem chamador** no app, testes ou scripts, cerca de 6,4 mil linhas: `services/e4b_consent_boundary.py`, `e4b_consent_persistence.py`, `consent_evidence_store_postgres.py`, `domain/e4b_consent.py`, `domain/consent_evidence_store.py` e `services/consent_evidence_store.py`. A única referência é o manifesto de hashes em `deploy/maintenance-profile.json`.
- **Scripts:** 40 de `backend/scripts/` sem referência no repositório. Isso não prova desuso: scripts podem ser chamados à mão ou por runbook. Remover só depois de verificar consumidores, um por um.
- **Só testes usam:** `agent/private_checkpoint.py`, `services/consent_ledger_receipt.py`, `services/purpose_consent.py`, `cell_report_meeting_target_adapter.py`.
- **Provavelmente sem uso, não comprovado:** `agent/tools.py`. A busca não encontrou produtor de `tool_calls` não vazio (estado inicial vazio em `nodes.py:198`; `nodes.py:436` só zera em `report_capture_node`), mas o runtime ainda importa `TOOLS` (`runtime.py:57`) e chama `_execute_tools` (`runtime.py:2221`). Só remover depois de provar a ausência de produtor (teste de turno e rastreio do caminho).
- **Desativado, não morto (manter):** D2A, as listas `*_ENABLED_IGREJA_IDS`, Jev, S3/V1/V2/V3/V4 atrás de flag.

**Correção de certeza:** "sem chamador" em D9 vale para os módulos E4B/evidência (busca de import em app, testes e scripts). Para scripts e `agent/tools.py` é hipótese até verificar consumidores.

**Hipóteses (não verificadas):** a proteção de branch pode diferir dos 4 checks documentados; o ORM e o SQL podem ter divergido; a ausência de opt-out no envio humano (`conversations.py:646`) pode ser intencional; os tempos de CI e de `./test-local.sh` não foram medidos nesta revisão.

**O que já funciona e deve ser aproveitado:**
- adaptador único por provedor, com o guard dentro do cliente Evolution;
- máquina de estados idempotente da resposta;
- serviços compartilhados nas ações novas (`consolidation_workflow`, `ministerial_actions`);
- `domain/pipeline.validate_transition` compartilhado;
- 4.228 testes de backend com PG17 descartável;
- `rls-integration`;
- compose de PROD e de dev;
- `migrate.py`;
- `dev.sh` com recusa de marcadores de PROD;
- backup antes de migration;
- workflow de PROD com `environment` e `concurrency`.

---

## 2. Arquitetura proposta: o que eu faria do zero, aproveitando o que existe

**Forma:** um monólito modular, com um repositório e uma imagem de backend. Os 4 processos atuais (API e 3 workers) continuam, usando os mesmos módulos. Não há microserviço, barramento de eventos nem framework interno.

### 2.1 Módulos de negócio
Cada módulo é um pacote com `servico.py` (funções públicas com `igreja_id` e `Ator` explícitos e erros de domínio) e regras puras. Os modelos ficam em `db/models.py` até haver motivo para dividir.

| Módulo | Responsabilidade | Problema que a separação resolve |
|---|---|---|
| `identidade` | igrejas, usuários, papéis, `PrivilegeContext` único, Clerk | D7: dois `PrivilegeContext` e dois `permissions.py` |
| `pessoas` | pessoa, dedupe por telefone, **`pode_contatar()`** (opt-out e consentimento) | D5c: 7 checagens de opt-out espalhadas |
| `celulas` | célula, reunião, presença, expectativa de visitante, relatório | D5b/D5d: regras triplicadas |
| `consolidacao` | pipeline, decisões, fonovisita, fila de trabalho | D5a: `registrar_decisao` duplicado |
| `agenda` | eventos, Google Calendar | uso de privado `_query_rows` pelo catálogo |
| `conversas` | ingestão, conversa, mensagem, inbox, handoff | tira a ingestão do worker-deus (D7) |
| `mensageria` | outbox, entrega WhatsApp, retries, broadcast | retry e entrega hoje ficam dentro do `queue_worker` |
| `agente` | turno, roteador, LLM e **registro de ações** (uma ação = um arquivo) | D4: 8 camadas por ação |
| `cobranca` | Asaas, planos | já está isolado; extrair o SQL do `subscription.py` quando for mexido |
| `plataforma` | console admin, configuração do Jev | — |

### 2.2 Direção das dependências e contratos
```
routers (HTTP) ─┐
workers (loops) ├─► servicos dos modulos ─► regras puras (domain) ─► db (sessao, tenant, models)
agente ─────────┘            │
                             └─► integracoes/ (evolution, llm, asaas, brevo, google, clerk, typesafe)
```
- **Proibido:** serviço → worker, router → worker, serviço → `HTTPException`, agente → tabela direta.
- O router traduz erro de domínio em HTTP; o agente traduz em resposta.
- Um teste de import (via `ast`, nada de hash) barra as setas invertidas. É o único "framework" necessário.
- **Painel e agente usam o mesmo serviço.** O que muda é o `Ator` (canal, pessoa, papel). Regras que divergem por canal viram parâmetro explícito de política, não um `if expected_actor_pessoa_id` escondido.
- **Contrato de ação do agente** (`agente/acoes/<acao>.py`): `nome`, `alvo`, esquema de argumentos, `autorizar(ctx)`, `resumo(args)` e `executar(sessao, ctx, args)`, que chama o serviço do módulo. `privileged_turn` e o catálogo despacham de forma genérica. Na primeira extração o CHECK do banco, as regras e as condições de ativação ficam como estão; relaxar o CHECK é uma mudança funcional separada, avaliada depois.
- **Integrações:** cada provedor tem um adaptador (já é assim) e um único guard de efeito real. Jev ganha um adaptador próprio, no lugar de `httpx` dentro de `semantic_triage`.

### 2.3 Banco, filas, IA e WhatsApp
- **Banco:** mantém Supabase, RLS, `promote_to_tenant`/`set_tenant_context` e `migrate.py`. Nada muda em RLS, API ou schema por causa da organização em módulos.
- **Fila:** mantém o Redis próprio, que já tem dedupe, lease e dead-letter. O worker vira só o laço; ingestão e entrega vão para `conversas` e `mensageria`.
- **IA:** mantém `services/llm.py` como única porta para a OpenAI.
- **WhatsApp:** mantém o `EvolutionClient`. Em DEV ele fala com uma **Evolution simulada**. Trocar a URL não basta: o cliente bloqueia toda chamada com `ALLOW_REAL_SENDS=false`, e ligar essa flag libera também LLM, Google Calendar e Jev. Por isso a simulação ganha configuração própria (ver §2.4), sem tocar no `ALLOW_REAL_SENDS`.

### 2.4 Configuração por ambiente
- Um `Settings` só, com `APP_ENV ∈ {test, local, dev, production}`. O `TriageSettings` é absorvido.
- Uma função `recurso_ativo(nome, igreja_id)` lê `RECURSO_<NOME>_IGREJAS` e substitui as 4 cópias e as leituras de `os.environ`.
- **Validação na partida** (hoje só existe no `dev.sh`):
  - `dev`/`local` recusam host do Supabase de PROD, `sk_live` e Evolution que não seja o simulador, exceto lista explícita de números de teste;
  - `production` recusa o simulador.
- **Simulação do WhatsApp:** `WHATSAPP_TRANSPORTE=simulado` + `EVOLUTION_SIMULADOR_URL`. Com ela, o `EvolutionClient` envia somente para o host do simulador, mesmo com `ALLOW_REAL_SENDS=false`; qualquer outro destino continua bloqueado. LLM, Google, Asaas, Brevo e Jev seguem o gate atual, desligados. Sem LLM, o turno usa o caminho determinístico atual (termo LGPD, consultas públicas), o que basta para provar o fluxo. A validação na partida recusa `simulado` em `production` e recusa URL de simulador fora de `localhost`/rede interna do compose.
- Um `.env.example` por ambiente documenta todas as variáveis, sem valores.

### 2.5 Testes
| Camada | O que prova | Quando roda |
|---|---|---|
| Regras puras e serviço | regra de negócio, autorização por papel | a cada edição (`./dev.sh test`) |
| PG17 descartável (`rls_integration`) | tenant, RLS, concorrência, migration aplica | CI |
| Turno completo via simulador | webhook → fila → agente → serviço → resposta → inbox, recusa sem papel, opt-out | CI (novo) e smoke do DEV |
| Playwright com mock | UI crítica | CI (mantido) |
| ORM × migrations | schema único | CI (novo; substitui as listas manuais) |

Os testes migram para `tests/<modulo>/` só quando o módulo é tocado, sem mudança em massa.

### 2.6 Manter, simplificar, substituir, remover
- **Manter:**
  - RLS, os dois mecanismos de tenant e `rls-integration`;
  - a máquina de resposta idempotente;
  - os adaptadores de provedor;
  - `ALLOW_REAL_SENDS`, a lista piloto e `AgentConfig.ativo`;
  - `ASAAS_BILLING_ENABLED` e `BREVO_SEND_MODE`;
  - o termo LGPD e o SIM do usuário antes de ação ministerial (confirmação do produto, não governança);
  - backup antes de migration em PROD;
  - os compose files, `migrate.py` e o seed fictício.
- **Simplificar:**
  - `queue_worker` vira só laço;
  - um Settings e uma função de recurso;
  - `privileged_turn` com despacho genérico;
  - o frontend recebe as capacidades do `/me` no lugar de matrizes espelhadas, mantendo o espelho só como dica de UI.
- **Substituir:**
  - as listas `EXPECTED_MIGRATIONS`/`REQUIRED_COLUMNS` e o sentinela `==82` pela leitura do diretório de migrations + ledger + teste ORM×SQL;
  - `maintenance-profile.json` e os recibos por hash pela promoção do digest da mesma imagem.
- **Remover do `main`** (a branch `archive/governanca-2026-09` já guarda o histórico):
  - os 6 módulos E4B/evidência sem chamador (depois de reconfirmar a busca no SHA da remoção);
  - scripts e `apply_migrations.py` **somente depois de verificar consumidores** (runbooks, operação manual);
  - `agent/tools.py` e `_execute_tools` **somente depois de provar** que nenhum caminho produz `tool_calls`, e depois que as regras de `vincular_celula` e `avancar_trilha` estiverem no serviço.
- **Trocar a implementação, preservando a verificação:**
  - `test_rls_ci_contract.py` protege a execução integral da suíte RLS (sem `--deselect`, falha com zero testes ou skip). Manter a garantia; trocar o fatiamento por nome de passo por uma checagem estruturada do YAML ou pelo próprio passo de verificação do junit no CI;
  - `test_production_runbook.py` protege que o bloqueio de envios externos roda antes da ativação no `backend-release.sh`. Manter o teste sobre o script; tirar só a dependência do texto do runbook;
  - hash de docstring e `getsource`: trocar por teste de comportamento equivalente antes de apagar.
- **Não remover:** funcionalidade só desativada por flag.

---

## 3. DEV online e PROD

| Parte | DEV online | PROD |
|---|---|---|
| Servidor | VPS próprio (separado do PROD) com o `deploy/docker-compose.yml` atual + serviço `fake-evolution` | VPS Hostinger atual |
| Banco/Storage | projeto Supabase DEV próprio, criado pelas migrations + seed fictício; o `Igreja12-dev` parado só é reaproveitado depois de verificar identidade e isolamento | Supabase PROD |
| Redis/filas | do compose DEV | do compose PROD |
| Painel | projeto Vercel DEV, publicado a cada `main` verde | Vercel PROD, **só pela ação de release** (já aprovado: `MVP:192`) |
| Identidade | instância Clerk de desenvolvimento | Clerk atual |
| Integrações | Evolution simulada; LLM com chave DEV opcional (sem ela, fail-closed); Asaas sandbox; Brevo `off`; Google sem credencial | reais, com os gates atuais |

**Publicação automática no DEV** (`deploy-dev.yml`):
1. Disparo: push na `main` depois dos 4 checks.
2. `concurrency: dev`, sem cancelar o que está em andamento.
3. A imagem é construída **uma vez**, com tag SHA, e enviada ao GHCR.
4. Via SSH, nesta ordem: `compose pull` (prepara a imagem, sem trocar os processos) → `migrate.py apply` das migrations **selecionadas** e compatíveis com o código em execução e com o novo (as marcadas `BLOCKED` ficam de fora) → só então `compose up` de API e workers → seed idempotente → smoke ("oi" no simulador → termo LGPD).
5. O SHA aparece em `/health` e no rodapé do painel.

**Concorrência entre pessoas e agentes:**
- O DEV só recebe a `main`, que funciona como fila única de integração.
- A validação vale para um **SHA**, e a release de PROD recebe esse SHA. Um merge posterior não muda o que vai para PROD.
- A variável `DEV_DEPLOY_PAUSADO` segura novos deploys enquanto alguém faz aceite. Sem previews por branch no início.

**Release PROD** (`release-prod.yml`, evolução do `backend-deploy-manual.yml`):
1. `workflow_dispatch` com o SHA.
2. Pré-condições: o SHA está na `main`, o CI está verde e o DEV registrou deploy e smoke OK nesse SHA.
3. `environment: production`, com aprovação do proprietário: é a única ação explícita.
4. Execução: preparar a imagem do **mesmo digest** (pull, sem ativar) → backup → migrations selecionadas da release → ativar API e workers → frontend do mesmo SHA → smoke → rollback de código se falhar.
5. O rollback de código só é seguro se a versão anterior funcionar com o schema resultante. Por isso as migrations seguem expandir/contrair, e a release verifica essa compatibilidade antes; quando ela não existe, a release declara que não há rollback de código e exige restauração de backup como recuperação.
6. Sarah revisa o PR que contém migration, RLS ou auth, e não cada comando de release.

**Catch-up de PROD (risco principal):**
- A primeira release vai cobrir semanas de `main` e várias migrations.
- O ledger de PROD não reproduz o schema de PROD: o registro documenta 63 migrations por prova de objeto, 6 por evidência histórica e 8 selecionadas ainda pendentes (`MVP:285-297`, `BACKEND-MAINTENANCE-RELEASE.md`). Aplicar "as 70 do ledger" no DEV é só **aproximação**.
- Antes do ensaio: reconciliar schema × ledger com uma comparação somente leitura do schema de PROD (estrutura, sem dados), numa missão própria e autorizada.
- Ensaio no DEV, como aproximação até essa reconciliação: aplicar as 70, rodar o legado e executar a release aplicando **só as migrations selecionadas** para ela, nunca todas as pendentes em lote.
- O ensaio mede tempo e revela quebras, mas não prova que PROD vai se comportar igual.

---

## 4. Fluxo de desenvolvimento proposto

| Etapa | Comando ou ação | Feedback esperado |
|---|---|---|
| Editar | editor; `./dev.sh test` (pytest do módulo tocado + `tsc`/vitest afetado) | segundos a poucos minutos (medir) |
| Antes do PR | `./dev.sh check` = `test-local.sh` atual + lint + teste de imports | equivale ao CI sem Docker |
| Integrar | PR pequeno → 4 checks + turno completo → merge sem autorização nominal | CI |
| DEV | automático depois do merge; `./dev.sh dev-logs` (SSH + `compose logs`, JSON com `turn_id`/`igreja_id`, sem PII) | minutos (medir) |
| Validar | navegador no DEV + simulador; dados repostos por `dev-reset` (dispatch manual) | — |
| PROD | `gh workflow run release-prod -f sha=<SHA validado>` + aprovação no environment | uma ação |

- **Comandos:** os novos subcomandos ficam no `dev.sh` (`test`, `check`, `dev-logs`), e o `test-local.sh` vira um alias.
- **Documentos:** AGENTS.md (regras), o plano vivo, o registro curto da fatia e os runbooks de PROD. A stack local (`./dev.sh up`) continua opcional, não obrigatória.

---

## 5. Burocracia × proteção útil

| Exigência | Custo hoje | Proposta | Como detectar regressão sem ela |
|---|---|---|---|
| Revisão "LENTE"/conselheiros por fatia (`MVP:511`) | dias por fatia, PRs retidos | remover; vale o §3.1 | 4 checks + turno completo + smoke no DEV |
| Autorização nominal de merge | merge retido | merge com CI verde | proteção de branch + DEV antes de PROD |
| Sarah ampla (`sarah.md:3`) | revisão em release e doc | restringir a migration em PROD, RLS e auth | `rls-integration` + revisão no PR certo |
| JSON de evidência, pins e hashes nos sprints (2.816 hashes em docs) | 3 a 16 arquivos por feature | SHA do Git + execução do CI + registro do deploy | o histórico do GitHub é a evidência |
| Sentinela `==82`, `EXPECTED_MIGRATIONS`, `REQUIRED_COLUMNS` | edição manual por migration | derivar do diretório + ledger; teste ORM×SQL | a release recusa se faltar migration no ledger |
| Testes de hash, doc, YAML e getsource | qualquer edição quebra o teste | apagar ou trocar por comportamento | `dry-run` do script de release; testes do serviço |
| `*_APPROVED_RELEASE_ID` no código | ativar exige código + deploy | env por ambiente (decisão §8) | ativação continua explícita no env de PROD |
| Regras triplicadas em AGENTS/CLAUDE/MVP | contradições e leitura longa | AGENTS.md único; CLAUDE.md aponta para ele | — |
| README de migrations com narrativa por feature | regra escondida | README só com regras | — |
| Scripts e módulos mortos | leitura, grep e hashes | apagar (estão no arquivo) | `import`/testes quebrariam se houvesse uso |

**Fica como está:**
- auth e autorização no backend;
- RLS por `igreja_id`;
- segredos fora do git;
- opt-out;
- idempotência;
- `ALLOW_REAL_SENDS`, a lista piloto e `AgentConfig.ativo`;
- os flags de Asaas e Brevo;
- backup antes de migration;
- aprovação no environment de PROD;
- o termo LGPD;
- o SIM do usuário antes de ação do agente, que é proteção do produto e não governança.

---

## 6. Abordagens

| | Benefício | Esforço | Risco de regressão | 1ª entrega útil |
|---|---|---|---|---|
| A. Incremental na estrutura atual | médio | baixo | baixo | dias |
| **B. Extração gradual de módulos, guiada por mudança real** | alto | médio, diluído | baixo/médio (cada passo testado) | dias |
| C. Reescrita ampla | incerto | muito alto | alto: perderia idempotência, RLS e 4.228 testes | semanas a meses |

**Recomendação: B, apoiada por A.** O módulo só é extraído quando uma feature real passa por ele, e as correções pontuais (config, testes frágeis, código morto) seguem A. Não há evidência que justifique C: o produto funciona em partes e tem cobertura grande, e o maior custo é processo e publicação, não código irrecuperável.

---

## 7. Passo 0 e três fatias

**Passo 0 (1 PR só de docs, horas).**
- **Problema:** as regras se contradizem (D3) e o DEV online contradiz "só local" (`AGENTS.md:129`, `CLAUDE.md:26`).
- **Limite:** AGENTS.md como fonte única; CLAUDE.md aponta para ele; remover `MVP:511-516` e reescrever o §3.5 com DEV online; restringir `sarah.md`.
- **Resultado e reversão:** sem teste; reverte com `git revert`. Precisa ser mesclado com as alterações não commitadas do usuário nesses arquivos.

**Fatia 1 — Simulador de WhatsApp e turno completo no CI (recomendada como primeira).**
- **Problema:** não há como exercitar WhatsApp → agente → resposta → inbox sem número real (D2). É pré-requisito do DEV com integrações simuladas e item pendente do `MVP:187`.
- **Limite:** novo `backend/devtools/fake_evolution/` (FastAPI pequeno), que implementa só os endpoints que o `EvolutionClient` usa (estado da conexão, `sendText`, mídia se usada) e emite webhook assinado com o segredo DEV. Inclui uma página HTML mínima de chat e um serviço com perfil próprio no compose dev. **Única mudança de produto:** o modo `WHATSAPP_TRANSPORTE=simulado` no `EvolutionClient` e no `Settings` (§2.4), que libera somente o host do simulador. Nada muda no worker, no agente, nas regras ou nos outros provedores.
- **Resultado observável:** "oi" no simulador → termo LGPD no simulador e a conversa no inbox do painel.
- **Testes:**
  - contrato `EvolutionClient` ↔ fake (`httpx` ASGI), um teste por método usado;
  - turno completo (webhook assinado → Redis → `handle_envelope` → resposta registrada no fake);
  - negativos: assinatura inválida → 401, "SAIR" → sem resposta, igreja fora da lista piloto → sem resposta, `AgentConfig.ativo=false` → sem resposta;
  - validador: `production`+simulador recusa e `dev`+URL real recusa;
  - isolamento: em modo `simulado` com `ALLOW_REAL_SENDS=false`, LLM, Google e Asaas continuam suprimidos, e um envio para host diferente do simulador é recusado.
- **Dependências:** nenhuma infraestrutura.
- **Reversão:** apagar o diretório e o serviço do compose.

**Fatia 2 — DEV online, publicação automática e release PROD com uma ação.**
- **Problema:** D1 e D2.
- **Limite:**
  - `deploy-dev.yml`, imagem única no GHCR, `release-prod.yml` (promove digest e frontend juntos) e smoke compartilhado;
  - a Vercel PROD deixa de sair da `main`;
  - o ensaio de catch-up no DEV;
  - recursos DEV criados só depois da decisão de local e custo.
- **Resultado observável:** merge → o DEV mostra o SHA e o simulador responde; dry-run da release no DEV.
- **Testes:** `actionlint`/`bash -n`, `dry-run` dos scripts e smoke automático.
- **Dependências:** Fatia 1 e as decisões do §8.
- **Reversão:** desligar os workflows; o PROD atual fica intacto até a primeira release.

**Fatia 3 — Contrato único de ação do agente.**
- **Problema:** D4 e D5.
- **Limite:** refatoração pura. Criar `agente/acoes/` e migrar só `registrar_expectativa_visitante` e `marcar_presenca`, as mais recentes e mais testadas; as outras 6 ficam no despacho atual até serem tocadas. **Ficam como estão:** o CHECK do banco, as regras de negócio (inclusive as checagens repetidas dos routers e a divergência humano × agente) e as condições de ativação. Sem migration.
- **Fora do escopo (mudanças funcionais separadas, cada uma com PR próprio):** relaxar o CHECK, trocar flags de ativação, unificar as checagens dos routers, pedido de oração.
- **Resultado observável:** a expectativa de visitante e a presença se comportam igual no simulador; adicionar uma ação passa a exigir menos arquivos (medido na próxima ação real).
- **Testes:** os 508 atuais da fatia (agente, contratos humanos, PG17) passando **sem alteração** + um teste de despacho genérico + turno completo.
- **Dependências:** Fatia 1 (harness); Fatia 2 para o aceite em DEV.
- **Reversão:** as duas ações voltam ao despacho atual com `git revert`; não há mudança de schema.

**Por que a Fatia 1 primeiro:** é pequena, aditiva, não toca auth, RLS nem o caminho privilegiado, e entrega o arnês que protege as refatorações da Fatia 3. Também é a peça que o DEV online exige. Extrair módulos antes de ter o turno completo testável seria refatorar às cegas.

**Fatias seguintes candidatas:** `recurso_ativo()` + Settings único (D8); remoção de código morto e testes frágeis (D6/D9); `pessoas.pode_contatar()`; `queue_worker` em laço + `conversas` + `mensageria`.

---

## 8. Validação do desenho com mudanças reais

| Caso | Hoje | No desenho | Testes |
|---|---|---|---|
| Regra: `a73e48d1` (tipos de fila na atribuição) | 2 arquivos, serviço compartilhado (bom) | `consolidacao/servico.py` (igual) | `test_consolidation_workflow_pg` |
| Agente: `698f9d43` (expectativa de visitante) | 16 arquivos, 7 de produto, 8 camadas, migration de CHECK, regra 3× | depois da Fatia 3: `agente/acoes/registrar_expectativa_visitante.py` + `celulas/servico.py` + testes, ainda com a migration de CHECK; sem ela só se o relaxamento do CHECK for aprovado à parte | ação (autorizar/resumo), serviço PG por papel e tenant, turno completo |
| Integração: `dae27ebd` (backoff da Evolution) | 1 arquivo, mas é o `queue_worker` de 4,9 mil linhas | `mensageria/entrega_whatsapp.py` | fake Evolution com injeção de 5xx/timeout |
| Integração ampla: `20a44e23` (outbox) | 45 arquivos, cerca de 9 camadas | outbox em `mensageria`; módulos só chamam `enfileirar_notificacao()` | serviço + PG; ainda cruza módulos, e isso é aceitável por ser fronteira nova |

**Revisão de fronteira:** o Asaas (`e8b06d0a`, 17 arquivos) continua espalhado porque `subscription.py` tem regra e SQL. O SQL só deve ser extraído para `cobranca/servico.py` quando houver uma mudança de cobrança, não antes.

**Métricas (baseline a coletar, nenhum ganho presumido):**
- tempo de `./dev.sh test` e de cada job de CI (medir as últimas 20 execuções pela API do GitHub);
- etapas manuais de merge→DEV e DEV→PROD (contar no runbook atual de 739 linhas e no novo);
- tempo do zero até o simulador responder no DEV;
- arquivos e camadas por feature (baseline: `698f9d43` = 16/8);
- fração de commits só de docs ou governança (baseline: 31 e 34 de 100);
- tempo de merge→DEV e DEV→PROD.

---

## 9. Decisões pendentes e incertezas
1. **Local e custo do DEV** (VPS separado e projeto Supabase DEV): decisão do proprietário antes da Fatia 2.
2. **Ativação de recursos:** trocar as constantes `*_APPROVED_RELEASE_ID` por env por ambiente. Recomendo trocar; a ativação em PROD continua sendo uma ação explícita do proprietário.
3. **CHECK de ações:** relaxar para formato, com a lista em código, é mudança funcional separada, avaliada depois da Fatia 3, via migration de release com Sarah.
4. **Regras divergentes entre humano e agente:** reunião passada na expectativa de visitante; envio humano sem checar opt-out (`conversations.py:646`). São decisões de produto.
5. **Escopo do catch-up de PROD:** quais flags permanecem desligadas depois que a `main` for publicada.
6. **Não verificado:** estado vivo de PROD, proteção de branch real, tempos de CI e de teste, saúde do DEV parado. Esta revisão não valida nada operacionalmente.

---

## Recomendação final

**Adotar o desenho B:** monólito modular, extraído conforme a mudança, com DEV online alimentado só pela `main`, promoção do mesmo artefato por SHA e uma única ação para PROD.

**Por quê:**
- os maiores custos medidos são processo (D3), publicação divergente (D1) e falta de ambiente integrado (D2), e não a impossibilidade de mudar o código;
- os serviços compartilhados mais recentes mostram que o caminho modular já funciona onde foi aplicado.

**Primeiro passo concreto:**
1. PR do Passo 0, só de docs (este documento, AGENTS.md, CLAUDE.md, `sarah.md` e o plano MVP).
2. Em seguida, branch `feat/simulador-whatsapp` para a Fatia 1, com os testes da seção 7.

## Ajustes da revisão de 09/10
Incorporados: (1) ordem de deploy imagem → migrations selecionadas → ativação, e rollback condicionado ao schema; (2) ensaio de catch-up como aproximação até reconciliar schema × ledger, sem aplicar pendentes em lote; (3) certeza corrigida sobre `agent/tools.py` e scripts, e testes de YAML/runbook trocados de implementação sem perder a garantia; (4) modo `WHATSAPP_TRANSPORTE=simulado` sem ligar `ALLOW_REAL_SENDS`; (5) Fatia 3 como refatoração pura, mantendo CHECK, regras e ativação.

## Verificação (ao implementar)
- Passo 0: CI verde; leitura cruzada mostra uma única fonte de regras.
- Fatia 1: `./test-local.sh` + pytest do contrato fake e do turno completo; 4 checks no PR; a demonstração "oi" → termo LGPD → inbox, via simulador na stack local opcional ou no DEV quando existir.
- Fatias 2 e 3: conforme a seção 7; nenhuma fatia é declarada concluída sem o resultado observável.
