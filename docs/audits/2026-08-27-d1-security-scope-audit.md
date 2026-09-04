# D1: auditoria de segurança, tenant e escopo do agente

**Data-base:** 2026-08-27

**Baseline auditada:** `253d23000a2afefa60210081904eb6b7f081acdd`
(`origin/main`, merge da PR #310)

**Modo:** inspeção local read-only da baseline, seguida por hardening D1A em
branch isolada

**Limite:** nenhuma consulta a Supabase, produção ou VPS; nenhuma migration
aplicada em ambiente compartilhado; nenhuma flag, credencial, mensagem, deploy
ou ativação alterada. A migration candidata foi executada somente no
PostgreSQL descartável descrito na validação local.

## Veredito

A D1 encontrou quatro lacunas de alta relevância antes da criação de memória,
conhecimento e novos especialistas do agente:

1. o worker aceitava `IngestionOutcome.igreja_id` ausente em um caminho de
   compatibilidade, e o runtime derivava a igreja da própria conversa depois
   de consultar apenas pelo `conversation_id`;
2. `whatsapp_connections.instance`, chave usada para resolver a igreja no
   webhook, permitia valores não nulos repetidos entre tenants;
3. relações críticas entre Pessoa, AppUser, papel, conversa e mensagem usavam
   FKs simples por UUID, sem tornar o par `(igreja_id, id)` uma barreira de
   integridade estrutural;
4. o workflow RLS mantinha uma lista manual que omitia quatro módulos já marcados
   e também excluídos da suíte backend offline.

O diff D1A desta PR fecha essas quatro lacunas e passou na validação local
descrita abaixo. Isso comprova o candidato de código, não comprova migration
aplicada, configuração ou estado vivo em qualquer ambiente compartilhado.

## Evidência da baseline

| Achado | Evidência direta no SHA auditado | Risco |
|---|---|---|
| Tenant opcional no worker | `backend/app/workers/queue_worker.py:1679-1687`, `:1752-1755` e `:2239-2254` | Um caller fora do caminho durável podia chegar ao runtime sem tenant obrigatório nem verificação do escopo transacional |
| Runtime derivava tenant depois da primeira leitura | `backend/app/agent/runtime.py:420-439` | A busca inicial era apenas por `Conversation.id`; o tenant não fazia parte do contrato de entrada nem do predicado |
| Instância Evolution sem unicidade global | `backend/app/db/models.py:1995-2007` | Duas igrejas podiam compartilhar a chave de resolução se dados incompatíveis fossem persistidos |
| FKs críticas eram UUID-only | exemplos em `backend/app/db/models.py:185-188`, `:960-963`, `:990-992` e `:2061-2078` | A RLS da linha não impedia, por si só, que uma linha apontasse para pai de outra igreja |
| CI RLS por allowlist | `.github/workflows/rls-integration.yml:85-105` | Quatro módulos marcados estavam fora da lista e também eram excluídos do workflow backend geral pelo marker |

Os quatro módulos omitidos eram `test_agent_event_idempotency_index.py`,
`test_backfill_pessoa_tipo_membro.py`, `test_backfill_whatsapp_numero_tipo.py` e
`test_pessoa_telefone_unique_concurrency.py`.

As linhas citadas pertencem ao SHA fixado acima. A migration e o código D1A
alteram essas posições, portanto a evidência histórica deve ser reaberta com
`git show 253d230:<arquivo>`.

## Hardening D1A candidato

### Tenant obrigatório e fail-closed

- o worker valida `igreja_id` como UUID antes de sessão, ownership guard,
  chamada do agente ou envio externo;
- toda sessão do agente recebe `set_config('app.tenant_igreja_id', ..., true)`
  e passa por uma verificação que exige role `authenticated`, tenant derivado
  e GUC transacional iguais ao tenant esperado;
- `process_inbound_message` exige `igreja_id`, filtra Conversation e Pessoa pelo
  tenant e rejeita um objeto incompatível mesmo se um adapter malicioso ignorar
  o predicado;
- o caso sem `conversation_id` continua no-op porque não abre sessão, não chama
  o agente e não produz efeito externo.

### Integridade estrutural

A migration
`backend/migrations/20260827_175634_d1a_tenant_runtime_integrity.sql`:

- usa transação `SERIALIZABLE` e locks `SHARE ROW EXCLUSIVE` para eliminar a
  janela entre preflight e DDL;
- fixa os objetos no schema `public`, usa `lock_timeout=5s` para falhar sem
  espera indefinida e limita cada statement a 120 segundos;
- interrompe com contagens sanitizadas se encontrar instância duplicada,
  órfão ou vínculo cross-tenant;
- cria unicidade parcial global para `whatsapp_connections.instance` quando o
  valor não é nulo;
- cria chaves únicas parentais `(igreja_id, id)`, dez FKs compostas e os índices
  de apoio, incluindo oito relações críticas e duas de consentimento;
- adiciona as FKs como `NOT VALID` e as valida ainda na mesma transação;
- mantém as FKs simples históricas para preservar `CASCADE` e `SET NULL`;
- falha fechado se uma constraint ou índice homônimo tiver contrato diferente,
  incluindo deferrability, estado live, ordem, collation e opclass;
- não contém correção automática, grants, revokes ou exposição pela Data API.

Rollback do aplicativo não exige remover as barreiras aditivas. Uma eventual
remoção de schema precisa de migration compensatória separada e auditada. Antes
de qualquer ambiente compartilhado, é obrigatório repetir o preflight por
contagens, medir volume e lock, confirmar backup e janela, e obter autorização
nominal própria.

### Contrato do CI

O workflow passa a executar `pytest --strict-markers -m rls_integration tests`,
sem allowlist de arquivos. Um hook de collection exige que todo teste que usa
fixture PostgreSQL transitiva carregue o marker, e que todo teste marcado use a
proteção de banco descartável. O verificador JUnit falha com zero testes, skip
total ou parcial, falha ou erro.

## Validação local

| Validação | Resultado | Limite |
|---|---|---|
| Suíte backend offline | `2.657 passed, 268 deselected` | PostgreSQL e integrações externas excluídos pelo marker |
| Suíte RLS completa em PostgreSQL 17 descartável | `268 passed, 2.657 deselected`, sem skip | Banco local sintético, sem acesso de rede a Supabase |
| Módulo de testes da migration D1A | `20 passed`: 19 casos PostgreSQL e 1 contrato estático ORM/SQL | Aplicação, reaplicação, dez preflights, catálogo, lock timeout, deletes e corrida em schema sintético |
| Collection de toda a suíte | `2.925 tests` | Confirmada pela soma disjunta das execuções offline e RLS |

Os números finais devem ser lidos junto do SHA da PR e dos checks do GitHub.
Nenhum resultado local afirma que produção possui as novas constraints.

## O que a D1A não implementa

- checkpointer LangGraph, memória privada ou role futura `agent_runtime`;
- conhecimento oficial, embeddings, propostas de ação ou outbox;
- novos especialistas ou ferramentas do agente;
- aplicação da migration em Supabase DEV ou PROD;
- deploy, ativação, canário ou abertura de gate.

O runtime atual continua usando a role `authenticated`, agora com tenant
transacional obrigatório e verificado. A role dedicada e o schema privado do
checkpointer pertencem às fases futuras e exigem migrations próprias.

## Gate daquele recorte histórico (consumido)

Naquele recorte, o passo seguinte era revisar e integrar a PR D1A. Ele foi
consumido pela PR #311 no merge
`01265fc7dfe239e487b5cddb6d9f6714128e3c84`; a aplicação posterior ocorreu
somente em DEV, sob preflight e autorização próprios, sem alterar PROD. Isso
não constitui gate corrente nem autoriza nova aplicação, D2, deploy, ativação
do agente ou canário.

O gate
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`
foi proposto no recorte do executor v2, mas não foi consumido. Depois do Commit
A local `9b9395e29cc821d6808738a30a6afe367d4ffbea`, ele foi substituído pela
consolidação
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_SAFETY_R1`, agora o
único estágio global corrente, fechado e não autorizado. Seu eventual consumo
fica restrito ao preflight remoto somente leitura, ao push da branch candidata,
à abertura de PR e à observação do CI e do Preview automáticos. O commit local
não afirma integração, CI remoto ou estado de ambiente, e o gate consolidado
não autoriza merge, banco compartilhado, DEV, PROD, migration, runner ou
alteração de flags. O gate futuro
`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_EXECUTOR_V2_EXTERNAL_TRUST_ANCHORS_OFFLINE`
continua não corrente e não autorizado.
