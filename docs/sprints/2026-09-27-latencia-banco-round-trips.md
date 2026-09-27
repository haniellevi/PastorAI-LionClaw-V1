# Latência do banco: idas e voltas por requisição — 2026-09-27

**Branch:** `perf/db-round-trips` · **Commits:** ver PR · **Deploy:** nenhum. PROD, VPS e Supabase não foram tocados.

## Contexto

Medição do proprietário em PROD (27/09, só leitura): o VPS (Hostinger, Brasil)
fala com o Supabase PROD em **us-west-2** a ~185 ms por ida e volta. Cada
requisição autenticada levava ~1,3 s só de banco; `/ready`, ~1,7 s. O servidor
estava ocioso, então o tempo é espera de rede, não processamento.

## Como foi medido

- Postgres 17.6 descartável (mesma imagem do CI), schema dos models e RLS
  mínima (`authenticated` NOBYPASSRLS, `current_igreja_id()`, policy por
  `igreja_id`). Nada de DEV/PROD.
- Um proxy TCP entre o app e o banco registra cada mensagem `Query` do
  protocolo do Postgres. Com psycopg2, cada uma é uma ida e volta completa.
  O mesmo proxy atrasa cada sentido em 92,5 ms para simular os 185 ms de PROD.
- HTTP real (uvicorn + httpx), pool aquecido, mediana de 3 chamadas. Clerk,
  Evolution e Storage falsos. O worker do WhatsApp roda o código real do
  worker e do agente, com Evolution e LLM falsos (LLM instantâneo).
- O `/auth/me` simulado (1,32 s) bate com os ~1,3 s medidos em PROD.

## Medições

Requisições do painel, 185 ms simulados. "Idas" são as que acontecem antes da
resposta; o ROLLBACK final sai depois da resposta e não pesa no tempo visto.

| Endpoint | Idas antes | Idas depois | Tempo antes | Tempo depois |
|---|---|---|---|---|
| `GET /auth/me` | 7 | 4 | 1.318 ms | 755 ms |
| `GET /whatsapp/connection` | 8 | 5 | 1.510 ms | 946 ms |
| `GET /conversations/{id}/messages` | 10 | 7 | 1.890 ms | 1.325 ms |
| `GET /setup/checklist` | 13 | 10 | 2.456 ms | 1.887 ms |
| `GET /roles/permissions` | 8 | 5 | 1.507 ms | 944 ms |
| 6 chamadas em paralelo (abertura de tela) | | | 2.495 ms | 1.940 ms |

As 3 idas economizadas por requisição: o `SELECT 1` do pre-ping e os dois
`SET LOCAL ROLE` separados. O que sobra no `/auth/me`: `BEGIN` (o psycopg2
manda à parte), claim + papel, busca do usuário, tenant + papel.

Mensagem do WhatsApp (webhook → worker → agente), 185 ms simulados:

| Mensagem | Antes | Depois |
|---|---|---|
| "Oi" (recebe o termo LGPD) | 167 idas, 32,6 s | 130 idas, 25,7 s |
| "sim" | 155 idas, 29,2 s | 117 idas, 22,0 s |
| "Que horas é o culto?" | 152 idas, 28,6 s | 114 idas, 21,5 s |

Confirmação em PROD: no teste real da equipe interna em 27/09, com o backend
`e6aafc2` (a base deste PR), a resposta chegou ao celular em ~28 s
(`2026-09-26-prod-sessao-a-ledger-e-deploy.md`), perto dos 28,6 a 32,6 s
que a simulação do "antes" deu.

Composição do "sim" depois do PR: 24 comandos de contexto de tenant, 12
provas de escopo (`require_tenant_scope`), 30 BEGIN/COMMIT/ROLLBACK (15
transações curtas) e 51 consultas de domínio. Antes havia ainda 14 pings e 24
`SET LOCAL ROLE`. **Com o banco a 185 ms, o bot não cumpre a meta da Fase 1
(resposta em menos de 10 s), mesmo com este PR.**

## O que foi feito

- Contexto de tenant numa ida só: `set_tenant_context`,
  `set_tenant_context_for_igreja` (`backend/app/db/rls.py`) e o listener
  `after_begin` (`backend/app/db/tenant_session.py`) mandam o GUC e
  `set_config('role', 'authenticated', true)` no mesmo `SELECT`.
- Pre-ping só para conexão parada (`backend/app/db/session.py`): quem voltou
  ao pool há menos de `DB_POOL_PING_IDLE_SECONDS` (padrão 60) é reusada sem
  `SELECT 1`; a mais antiga é testada como antes e, se estiver morta, o pool é
  invalidado e a requisição segue numa conexão nova. `0` volta ao
  `pool_pre_ping=True`. Keepalive TCP a cada 30 s na conexão parada.
- CORS: `max_age=7200` explícito (`backend/app/main.py`). O padrão do
  Starlette já era 600 s.
- Sessão dedicada D2A (pausada, sem efeito em PROD hoje):
  `backend/app/db/agent_runtime_session.py` faz a guarda de checkout numa ida
  (autocommit, sem BEGIN/ROLLBACK) e dispensa o pre-ping duplicado (3 idas a
  menos por checkout quando voltar). O GUC e a prova de identidade continuam
  em instruções separadas: juntos, a prova passaria mesmo com a conexão em
  autocommit, e o ganho numa sessão pausada seria de 1 ida (P2-1 da Sarah).
- Testes: unitários atualizados para o SQL novo e para o ping por ociosidade;
  `tests/test_tenant_context_round_trips_pg.py` (Postgres real) prova uma
  instrução só, RLS aplicada, reversão no commit/rollback, a mesma checagem de
  permissão do `SET ROLE` (SQLSTATE 42501 sem membership) e a troca de uma
  conexão morta após o tempo de ociosidade.

## Decisões

- **`set_config('role', ..., true)` no lugar de `SET LOCAL ROLE`.** O
  PostgreSQL aplica os dois pelo mesmo caminho (GUC `role`, mesma checagem de
  membership, reverte com a transação); o PostgREST do Supabase troca o papel
  assim. O `SET LOCAL ROLE authenticated` continua obrigatório em espírito: só
  mudou a forma de enviar. Se o papel falhar, a instrução inteira falha e a
  transação aborta (fail-closed, T6 continua verde).
- **Ping por ociosidade, não remoção do pre-ping.** Troca aceita: se o pooler
  reiniciar e a conexão tiver sido usada há menos de 60 s, uma requisição
  falha com 500 e o pool se renova; antes ela só ficava lenta. Alavanca de
  volta: `DB_POOL_PING_IDLE_SECONDS=0` e reiniciar.
- **Preflight continua existindo.** O cache do navegador é por URL; cada
  conversa, página ou filtro novo ainda paga um OPTIONS (~55 ms, sem banco).
  Safari limita o cache a 10 min. Eliminar de vez exigiria servir a API na
  mesma origem do painel (proxy da Vercel); não feito. Efeito colateral
  registrado em `docs/ops/PROD-ENV-RUNBOOK.md`: uma origem removida da lista
  pode seguir mandando requisições por até 2 h (as respostas já ficam
  bloqueadas na hora).
- **Sem otimização por endpoint neste PR** (PR pequeno, revisão focada em RLS).
  Ficam como próximos passos, com ganho estimado.

## Para o proprietário: opções de infraestrutura

Hoje o servidor fica no Brasil e o banco nos EUA (Oregon). Cada pergunta do
servidor ao banco leva ~0,19 s e uma tela faz de 4 a 10 perguntas; uma
mensagem do WhatsApp faz mais de 100. Aproximar os dois é o que resolve.

| | Só este PR | A. Servidor nos EUA (Oregon) | B. Banco em São Paulo |
|---|---|---|---|
| Tela do painel, por chamada | 0,8 a 1,9 s | 0,2 a 0,4 s | 0,1 a 0,25 s (estimado) |
| Resposta do bot (sem o tempo da IA) | 21 a 26 s | 0,1 a 0,3 s | 0,2 a 1,3 s (estimado) |
| Custo mensal | igual | VPS novo, ~US$ 24 (AWS Lightsail 2 vCPU/4 GB), mais o atual até o fim do contrato; a Hostinger não tem Oregon | igual (Supabase não cobra por região); alguns dólares a mais nos dias com os dois projetos |
| Tempo fora do ar | nenhum | 30 a 60 min | 30 a 60 min, em horário combinado |
| Risco principal | bot lento demais para a meta de 10 s | WhatsApp pode pedir para parear de novo (QR code com o celular da igreja); DNS e certificado | cópia do banco, dos arquivos (fotos/mídias) e troca de chaves e endereços; o projeto antigo fica de reserva para voltar |

Na opção A, o painel fica mais lento para quem está no Brasil que na B, porque
cada chamada do navegador atravessa até os EUA. Na B, os dados dos membros
passam a ficar no Brasil.

**Recomendação: B, banco em São Paulo.** É a mais rápida para os pastores e
para o bot, não muda o custo, não mexe no WhatsApp e é reversível. Antes de
decidir, um teste de 10 minutos: criar um projeto vazio do Supabase em São
Paulo e medir do VPS o mesmo `psql SELECT 1` de hoje. Abaixo de ~15 ms, seguir.

Na B, as mensagens que chegarem durante a janela esperam na fila do Redis (o
webhook não usa o banco) e são respondidas depois. Pontos do roteiro:
dump/restore com papéis e RLS; copiar o Storage à parte (não vem no backup);
trocar `DATABASE_URL`, `SUPABASE_URL` e chaves no backend, na Vercel, no
backup e no monitor; acrescentar a ref do projeto novo na trava
`_PROD_DENYLIST` de `backend/tests/conftest_rls.py`; conferir o ledger
`schema_migrations`. É migration/infra de PROD: backup antes e revisão da Sarah.

## Pendente / próximo passo

- **Sarah: GO no `ef6f2c1` e no delta `82c7fc0`** (P0=0, P1=1), válido com
  `rls-integration` verde no head. Os cinco P2 da primeira rodada foram
  tratados em `82c7fc0` (D2A com GUC e prova separados de novo, restauração do
  autocommit como no SQLAlchemy, comentário sobre `handle_error`, defasagem de
  CORS no runbook, item do plano desmarcado). O P2-6 do delta (voltar a
  assertiva de que a D2A nunca manda `'role'`) entrou no commit seguinte.
- **P1-1 decidido em 27/09:** o proprietário aceitou a exceção de mexer na
  D2A pausada (guarda de checkout e pre-ping; sem efeito em PROD hoje) e
  autorizou o merge do PR #424. Decisão registrada no PR. O merge não é deploy:
  o código entra em produção no próximo deploy pelo runbook.
- Decisão do proprietário sobre a infraestrutura (seção acima) e o teste de
  latência em São Paulo. Enquanto o banco estiver em us-west-2, o aceite da
  Fase 1 (resposta em menos de 10 s) não é alcançável.
- Próximos cortes no código, cada um em PR próprio:
  - worker: 15 transações por mensagem; `mark_tenant_scoped` numa sessão nova
    aplica o escopo duas vezes (listener + aplicação imediata, ~9 idas); as 12
    provas de escopo poderiam ir junto do contexto. Mexe na barreira de RLS,
    precisa de revisão.
  - `/setup/checklist`: 6 consultas em sequência cabem numa (−5 idas, ~0,9 s).
  - `/conversations/{id}/messages`: contagem e página numa consulta (−1 ida).
  - O `BEGIN` separado é do psycopg2; só sai trocando de driver.
- Pool de 5 conexões: a primeira rajada acima disso abre conexões frias
  (~3,9 s cada em PROD). Aumentar exige conferir o limite do pooler em modo
  sessão; não mexido.

## Verificação

- `./test-local.sh`: backend 5.431 testes e frontend 883 testes verdes
  (Python 3.13.14, Node 24.19.0, `umask 022`).
- `pytest -m rls_integration` em PostgreSQL 17.6 descartável: 345 passaram,
  zero pulados, incluindo T1–T6, D2A real (pool contaminado) e os 5 novos.
- Os testes novos falham se o `SET LOCAL ROLE` separado voltar (conferido).
- Medições com latência simulada, não em PROD. A medição real depois do
  deploy é repetir o `psql`/`/ready` do proprietário e cronometrar `/auth/me`.
