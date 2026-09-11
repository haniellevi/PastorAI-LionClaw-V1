# Fundação V3 para execução catalog-bound

Data: 2026-09-10
Status: implementada localmente, sem autorização operacional

## Contexto

A missão I2 exige uma fronteira V3 que possa descrever e validar localmente o
candidato C3 sem reutilizar os caminhos V2, sem ler arquivos e sem iniciar
qualquer operação contra banco, rede, credencial, DSN ou ledger. O candidato
está vinculado ao SHA de repositório
`02a4f1aecfcf0433455e1b5c93a96b10e2358a55`, ao SHA-256 SQL
`6952a2aaca04d6765a0bc77f831b2507e9cf5fd77d80f76e43b0816b06806e6b`, ao
SHA-256 do head
`9b756191d6a3e89fca61b3c88015b1f76423692e09b12270239389bef63dd1f5` e ao
SHA-256 do digest
`ed6398ff6cfc15981208631075b724fb128991682e6c7e607acf72fb913a6ac2`.

## Decisão

Criar uma implementação V3 autônoma em
`backend/scripts/catalog_bound_execution_v3.py`, com wrapper em
`backend/scripts/execute_catalog_bound_migration_v3.py`. A ligação C3 é uma
dataclass congelada, construída por literais completos no código-fonte. A
validação aceita somente objetos JSON de forma fechada, contendo a ligação
exata e um dos três tipos explícitos de verificação:

1. envelope de autorização externa;
2. replay durável;
3. cutover.

Cada tipo só expressa a ausência da sua prova externa correspondente:
`EXTERNAL_AUTHORIZATION_UNVERIFIED`, `DURABLE_REPLAY_UNVERIFIED` ou
`CUTOVER_UNVERIFIED`. O contrato não converte uma alegação local em
autorização, replay ou decisão de cutover.

A CLI permite apenas `describe` e `validate`. Comandos que poderiam sugerir
ou iniciar aplicação, bootstrap, harden, reconciliação, cutover ou ledger
legado são rejeitados com saída não zero antes de I/O. Não há leitura de
arquivo, DSN, SQL executável, driver, subprocesso, rede, descritor herdado ou
acesso a ambiente nesta fundação.

## Consequências

A V3 é revisável como código-fonte e pode recusar material de entrada que não
seja integralmente vinculado ao candidato. Ela não verifica bytes fora do
próprio objeto recebido e não pode provar estado de repositório, catálogo,
banco, snapshot, autorização humana, replay durável ou cutover. Esses limites
são intencionais e permanecem explícitos na interface.

O rollback é remover somente os dois scripts V3, sua suíte focal e os registros
documentais desta missão antes de integrar a mudança. Nenhuma migration, dado,
schema ou ambiente precisa de compensação porque esta decisão não executa I/O.

## Evidência local

No worktree
`/home/raniel-linux/workspace/PastorAi-1.0/.worktrees/e4b-c3-catalog-bound-executor-v3`,
branch `feat/e4b-c3-catalog-bound-executor-v3`, a pré-condição foi registrada
em 2026-09-10T23:07:55-03:00 no SHA
`02a4f1aecfcf0433455e1b5c93a96b10e2358a55`, com estado inicial limpo. A
evidência posterior é limitada a compilação Python e às suítes source-only
focais executadas no mesmo worktree. Ela não é evidência de PostgreSQL, RLS,
ambiente compartilhado nem produção.

## Próximo gate

Uma pessoa autorizada deve aprovar, em missão separada, os trust anchors, a
fonte privada no SHA exato, as atestações externas, o replay durável e a
decisão de cutover. Esta decisão não concede esse gate.
