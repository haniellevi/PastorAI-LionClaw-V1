---
id: M-2026-09-15-f2-prod-readonly-collection
status: recorte_congelado_para_parecer_conjunto
prepared_at: 2026-09-15T22:59:32-03:00
environment: local; PROD e DEV somente por operador humano após conferência do SQL exato
execution_authorized: false_pending_exact_sql_joint_apt
strategy: A_recommended_not_yet_selected
---

# F2: recorte da coleta PROD e DEV somente leitura

## Resultado observável desta etapa

Preparar, sem SQL executável e sem acesso a ambiente vivo, o contrato de duas
coletas independentes de metadados: primeiro PROD, depois DEV equivalente. Os
dois resultados serão congelados e só então comparados para sustentar o desenho
documental da estratégia A e do epoch/cutover. Este recorte não escolhe A ou B,
não cria epoch, não implementa executor e não autoriza escrita.

## Ficha Mission Control

```yaml
id: M-2026-09-15-f2-prod-readonly-collection
objetivo: obter evidência sanitizada e vinculada separadamente de PROD e DEV sobre ledgers, catálogo e assinaturas estruturais, sem ler domínio ou escrever, para permitir a decisão A/B e o desenho posterior do epoch/cutover
preflight:
  repositorio: github.com/haniellevi/PastorAI-LionClaw-V1
  branch: docs/dev-migration-history-remediation-f2-readonly-20260915
  sha_efetivo: f856f53f48e79a53609ff699d5603119f60202e0
  worktree_limpo: true antes deste arquivo
  ambiente: local; nenhuma sessão PROD ou DEV nesta preparação
  horario: 2026-09-15T22:59:32-03:00
  runbook_lido: docs/ops/MISSION-CONTROL.md; docs/ops/MAESTRI-PERSISTENCE-MANIFEST.md; docs/ops/dev-migration-history-remediation/RANIEL-READONLY-RUNBOOK.md; docs/ops/dev-migration-history-remediation/f1-analysis/STRATEGY-A-B-DECISION-PACKET.md
  grafo: não disponível; code-review-graph permanece desabilitado
worktree: .worktrees/dev-migration-history-remediation-f2-readonly-20260915
branch: docs/dev-migration-history-remediation-f2-readonly-20260915
sha_base: f856f53f48e79a53609ff699d5603119f60202e0
operador_de_ambiente: Raniel; agentes não abrem sessão PROD ou DEV
revisores_pre_coleta:
  - OpenCode, CONSELHEIRO
  - CLAUDE, CONSELHEIRO
arquivos_permitidos_nesta_etapa:
  - docs/missions/M-2026-09-15-f2-prod-readonly-collection.md
criterios_de_aceite:
  - o recorte define forma, limites, abortos, privacidade, binding, recibos e ordem sem conter SQL executável
  - PROD e DEV usam arquivos e hashes próprios, com núcleo observacional equivalente e guardas de forma específicas por ambiente
  - o SQL futuro passa em teste PostgreSQL 17 descartável antes de qualquer execução humana
  - os dois conselheiros marcam APTO o recorte e, depois, os bytes exatos do SQL e runbook antes de Raniel executar
  - nenhuma comparação PROD x DEV começa antes de as duas transcrições sanitizadas serem congeladas separadamente
riscos_de_tenant:
  - leitura de linha de domínio; bloqueada por fontes restritas a pg_catalog, information_schema e aos dois ledgers
  - exposição de nomes sensíveis de objetos; nomes fora da allowlist estática derivada do catálogo de 77 migrations são substituídos por referências opacas
  - exposição de statement; somente hashes e classes não sensíveis podem sair, nunca o texto armazenado
  - alvo incorreto ou binding reutilizado; cada ambiente exige binding novo e digest próprio, sem reutilização entre F1, PROD e DEV
  - carga ou alerta operacional em PROD; uma sessão fora do pico, timeouts curtos e aviso prévio ao operador, sem silenciar monitor
plano_de_teste:
  - inspeção source-only prova ausência de escrita, pg_dump, EXPLAIN ANALYZE, função de usuário e fonte de domínio
  - PostgreSQL 17 local descartável exercita formas PROD e DEV, todos os abortos, digest, mascaramento, recibo qecho e rollback
  - fixture PROD prova public.schema_migrations ausente e ledger nativo presente com cardinalidade previamente declarada
  - fixture DEV prova ledger público e nativo presentes sob guarda própria, sem reutilizar a expectativa PROD
  - fixture adversarial prova que nome fora da allowlist, statement e dado de domínio não aparecem
  - teste prova TARGET_DIGEST estável no mesmo alvo lógico e diferente com binding, database, porta/socket ou versão diferentes
  - privacy guard do repositório e git diff --check antes de qualquer publicação futura
plano_de_rollback:
  - nesta etapa, descartar apenas o arquivo local se o recorte for rejeitado
  - em cada coleta, ROLLBACK explícito é obrigatório; qualquer erro encerra a única sessão e impede repetição sem nova conferência
  - como não há escrita permitida, não existe compensação de banco nesta fase
proximo_checkpoint: APTO conjunto de OpenCode e CLAUDE sobre este arquivo e seu SHA-256; somente depois preparar SQL e runbook exatos
proximo_gate_humano: Raniel executar os arquivos exatos aprovados, primeiro PROD fora do pico e depois DEV, entregando evidências separadas; isso não autoriza comparação, epoch, executor ou aplicação
```

## Limites absolutos

A coleta é observacional. Permanecem fora:

- qualquer escrita em PROD ou DEV, inclusive tabela temporária, advisory lock,
  materialized view, comentário, grant, backfill, ledger ou migration;
- `pg_dump`, `COPY` de dados, `EXPLAIN ANALYZE`, extensão, DDL e chamada de
  função definida pela aplicação;
- recriação ou troca de DEV, estratégia B, aplicação, cutover, deploy, restart,
  credencial, alteração de firewall ou monitor;
- envio real, billing, broadcast, Brevo, `ALLOW_REAL_SENDS`,
  `BROADCAST_ASYNC_ENABLED` e `AgentConfig.ativo`;
- comparação PROD x DEV, desenho final do epoch e implementação do executor
  antes de ambas as evidências terem sido congeladas e aceitas.

A sessão PROD é sempre executada por Raniel. Agentes recebem somente saída já
sanitizada. Nenhum host, DSN, database, usuário, IP, certificado, segredo,
binding ou identificador reutilizável entra no repositório, chat ou canvas.

## Artefatos futuros, ainda não criados

Após o APTO conjunto deste recorte, a preparação produzirá arquivos separados:

1. `PROD-READONLY-F2.sql`, com guarda de forma PROD e recibo PROD;
2. `DEV-READONLY-F2.sql`, com guarda de forma DEV e recibo DEV;
3. runbook humano único, com seções independentes e proibição de executar os
   dois ambientes na mesma sessão ou com o mesmo binding;
4. runner PostgreSQL 17 descartável, sem rede e sem porta publicada;
5. manifesto reproduzível com hash de todos os bytes candidatos.

Nenhum desses artefatos existe ou está autorizado por este recorte. Os bytes
exatos, hashes e resultado local voltarão aos dois conselheiros antes de Raniel
executar qualquer arquivo.

## Contrato de sessão viva

Cada ambiente usa uma única conexão e uma única transação. A execução futura
deve ocorrer fora do horário de pico, depois de Raniel avaliar capacidade de
conexões e monitoramento. Antes de abrir a sessão, o runbook avisará que a nova
conexão e consultas de catálogo podem gerar alerta legítimo. Nenhum alerta será
suprimido e nenhum limite será elevado.

O SQL futuro deve iniciar a transação assim:

- `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY`;
- `statement_timeout = 5000ms`;
- `lock_timeout = 1000ms`;
- `idle_in_transaction_session_timeout = 15000ms`;
- `row_security = off`, para falhar fechado se alguma fonte depender de RLS.

Ele deve terminar com `ROLLBACK` e, depois do rollback bem-sucedido, emitir o
recibo pelo canal de saída da consulta usando `\qecho`. `\echo` é proibido no
arquivo, pois não segue o redirecionamento `\o` e pode deixar o recibo fora da
evidência. Os recibos esperados serão distintos:

- `F2_PROD_FINAL_RECEIPT=ROLLBACK_COMPLETED_F2_PROD`;
- `F2_DEV_FINAL_RECEIPT=ROLLBACK_COMPLETED_F2_DEV`.

Ausência, duplicidade ou posição não terminal do recibo invalida a coleta. Em
erro, timeout, forma inesperada ou saída fora do contrato, Raniel executa apenas
`ROLLBACK`, fecha a sessão e envia o motivo sanitizado. Não repete, amplia o
timeout, troca principal ou investiga interativamente sem nova conferência.

## Guardas de forma específicas

A evidência histórica de 28/08 indica uma forma PROD diferente da F1 DEV. O
candidato PROD partirá destas expectativas declaradas antes da execução:

- `public.schema_migrations`: `ABSENT` é estado explícito aceito;
- `supabase_migrations.schema_migrations`: `PRESENT`;
- cardinalidade nativa esperada: `6`;
- colunas, tipos e nulabilidade do ledger nativo: contrato estático revisado;
- nenhuma expectativa `EXPECTED_33` será reutilizada em PROD.

Essas expectativas são somente guarda de coleta e precisam ser confirmadas nos
bytes exatos futuros. Forma ou cardinalidade diferente gera apenas um código
sanitizado, como `F2_ABORT_PROD_LEDGER_SHAPE_DRIFT`, seguido de `ROLLBACK`. A
coleta não tenta adaptar o SQL, descobrir conteúdo ou continuar parcialmente.

O candidato DEV terá guarda própria baseada na evidência F1 congelada:

- `public.schema_migrations`: `PRESENT`, cardinalidade declarada `33`;
- `supabase_migrations.schema_migrations`: `PRESENT`, cardinalidade declarada
  `6`;
- forma diferente gera `F2_ABORT_DEV_LEDGER_SHAPE_DRIFT` e encerra.

A diferença observada vira resultado. Ela nunca é corrigida durante a coleta.
PROD e DEV usam o mesmo conjunto de categorias observacionais quando a forma
passa, mas nenhum arquivo aceita automaticamente a forma do outro ambiente.

## Fontes e privacidade

O SQL futuro poderá ler somente:

- `pg_catalog`;
- `information_schema` quando o mesmo fato não puder ser obtido com segurança
  em `pg_catalog`;
- metadados de `public.schema_migrations`, se a relação existir;
- metadados e fingerprints de
  `supabase_migrations.schema_migrations`, sem imprimir `statements`.

Nenhuma relação de domínio pode aparecer em `FROM`, `JOIN`, subconsulta,
função, `COPY` ou consulta dinâmica. Definições de função, policy, índice,
constraint, trigger e default podem ser processadas apenas dentro de hash no
servidor; seu texto bruto nunca sai. O SQL não chama função de usuário. Funções
`pg_get_*def` só podem alimentar um digest, sem projetar a definição.

A allowlist de nomes publicáveis será gerada offline a partir do catálogo
imutável das 77 migrations e revisada junto com o SQL. Para qualquer relação
fora dela, a saída usa apenas referência opaca derivada de schema, classe e
nome. O nome cru não aparece nem em resultado de sucesso nem em aborto. Nomes
de tenant, pessoa, igreja, operador ou role inesperada nunca são impressos.

A coluna `statements` do ledger nativo só pode produzir cardinalidade, hash ou
classe sintática não sensível. Nenhum prefixo, comentário, literal ou trecho do
SQL armazenado é selecionado ou registrado.

## Binding e captura

PROD exige binding aleatório novo, próprio daquela execução. DEV exige outro
binding novo. Nenhum deles pode reutilizar o binding F1 ou o binding do outro
ambiente. O valor fica fora de argv, variável de ambiente, histórico, arquivo,
transcrição e scrollback preservado. O runbook exato deve definir entrada sem
eco e provar que nada foi executado antes de:

1. desligar o histórico do `psql`;
2. definir `ECHO none`;
3. receber o binding sem eco;
4. iniciar a captura com `\o`;
5. incluir somente o arquivo hash-conferido.

O primeiro registro de sucesso será `TARGET_DIGEST`, calculado exatamente por:

```text
sha256(
  binding || chr(31) || current_database() || chr(31) ||
  COALESCE(inet_server_port()::text, 'UNIX_SOCKET') || chr(31) ||
  current_setting('server_version_num')
)
```

O digest é opaco e irreversível sem o binding. Raniel o recalcula fora da
transcrição com comando equivalente revisado, confere igualdade e apaga as
variáveis locais. Antes de limpar o scrollback, a busca silenciosa por um
prefixo do binding deve retornar zero no arquivo capturado e nos históricos do
`psql` e do shell. Se houver ocorrência, a evidência é invalidada, o binding é
descartado e nenhuma nova execução ocorre sem nova conferência.

## Teste local obrigatório antes da coleta

O runner PostgreSQL 17 descartável deverá usar rede `none`, nenhuma porta
publicada e remoção ao final. Ele provará de ponta a ponta:

- forma PROD com ledger público ausente e seis entradas nativas;
- forma DEV com 33 entradas públicas e seis nativas;
- aborto de cada desvio de presença, coluna, tipo, nulabilidade ou
  cardinalidade, sem vazar valor observado;
- sessão read-only, três timeouts, `row_security=off` e rollback terminal;
- recibo `\qecho` capturado uma única vez dentro do arquivo redirecionado;
- nenhuma função de usuário executada e nenhuma relação de domínio lida;
- nomes fora da allowlist mascarados em relation, function, constraint, index,
  policy e trigger;
- zero statement bruto e zero dado de domínio na saída;
- digest presente e estável no mesmo caso, distinto quando mudam binding,
  database, porta/socket ou versão, incluindo conexão por socket Unix.

O teste local não prova identidade, autorização ou carga aceitável de PROD. Ele
prova apenas o comportamento dos mesmos bytes em fixtures controladas.

## Ordem operacional após este recorte

1. OpenCode e CLAUDE conferem este arquivo e seu SHA-256.
2. Somente com ambos `APTO`, preparar os dois SQLs, runbook, runner e manifesto.
3. Testar os bytes exatos em PostgreSQL 17 local descartável.
4. Recalcular hashes e submeter o candidato exato aos dois conselheiros.
5. Somente com novo `APTO` conjunto, Raniel executa PROD fora do pico, em sessão
   única, e entrega transcrição sanitizada, hash, horário e recibo.
6. Sem comparar com DEV, congelar e validar a evidência PROD isoladamente.
7. Raniel executa o arquivo DEV equivalente em outra sessão e com outro binding.
8. Congelar e validar a evidência DEV isoladamente.
9. Apenas então comparar os dois ambientes e preparar o desenho documental A/B
   e epoch/cutover, ainda sem escrita.

## Critério de parada

Qualquer forma inesperada, PII, nome fora do contrato, statement bruto, recibo
ausente, timeout, alerta operacional, dúvida de target, falha de binding ou
capacidade de conexões insuficiente interrompe a etapa. O único resultado
aceito nesse caso é o motivo sanitizado e a confirmação de `ROLLBACK`; não há
segunda tentativa implícita.

## Estado ao congelar este recorte

Nenhum SQL F2 foi criado ou executado. Nenhuma sessão PROD ou DEV foi aberta.
Nenhuma comparação, epoch, cutover, executor, migration, commit, push, PR,
merge, deploy, envio, billing, broadcast, Brevo, credencial ou flag foi
alterada. O próximo checkpoint é exclusivamente o parecer conjunto sobre os
bytes deste arquivo.
