# Snapshot confiável do repositório para governança de migrations

Data: `2026-09-03`

Estado: `IMPLEMENTADO E COMPROVADO OFFLINE / AINDA NÃO INTEGRADO / SEM
ATESTACAO VIVA / OPERACAO BLOQUEADA`.

Base auditada: `c2fb16ad9a6b028c317c56a0b02c4362ae903e26`.

## Problema

Os verificadores de migrations rejeitam corretamente qualquer ancestral,
diretório de governança ou arquivo que seja gravável por grupo ou por outros.
O checkout compartilhado desta máquina nasce sob `umask 0002`: o primeiro
ancestral inseguro observado é `/home/raniel-linux/workspace`, modo `0775`, e
os diretórios do repositório também podem ter modo `0775`. Alterar apenas
`backend/migrations` ou `docs/governance/migrations` não corrige a cadeia de
confiança; aplicar `chmod` recursivo ao workspace compartilhado mudaria
arquivos e worktrees de outros agentes.

## Decisão

Ferramentas de captura, atestação, reconciliação e aplicação de migrations não
devem usar o checkout compartilhado como fonte confiável. Elas devem partir de
um snapshot privado e descartável criado por
`backend/scripts/trusted_repository_snapshot.py` para um SHA completo e
explícito.

O snapshot:

- usa exclusivamente objetos Git locais, sem fetch, rede, shell, hooks,
  credenciais persistidas ou resolução de ref simbólica;
- desabilita `replace objects` e autentica os bytes do objeto commit contra o
  SHA recebido;
- vincula o único header `tree` do commit à árvore recalculada e autentica cada
  blob pelos bytes extraídos;
- rejeita submodule, symlink, hardlink, FIFO, device, traversal, colisão de
  caminho e caminhos protegidos definidos em `AGENTS.md`;
- exige `/tmp` real, sticky e com modo `01777`, cria uma raiz aleatória como
  filha direta, normaliza raiz e diretórios para `0700` e arquivos para `0600`;
- valida owner, group, inode, device, número de links, modo, tamanho e hash,
  removendo o arquivo tar antes de entregar o snapshot;
- limpa falhas e snapshots por descritores e identidade de inode, sem seguir
  links nem remover uma raiz substituída.

Executáveis versionados também ficam em `0600`; qualquer script do snapshot é
invocado por um interpretador fixado, nunca por confiança no bit executável.
Processos com o mesmo UID pertencem à mesma fronteira de confiança POSIX: esta
política protege contra permissões amplas, substituição de caminho e conteúdo
Git divergente, mas não promete isolamento entre processos hostis do mesmo UID.

## Evidência offline

Na base `c2fb16ad`, o materializador produziu um snapshot de 1.019 arquivos e
92 árvores, ambos os diretórios de topo em `0700`, arquivos em `0600` e cleanup
confirmado. Dentro dele, o verificador do catálogo terminou com exit `0`,
`MIGRATION_CATALOG_HEAD_VERIFIED_OFFLINE` e 75 migrations.

A suíte adversarial terminou com `38/38` casos aprovados e cobre `umask 0002`,
SHA inválido, `git replace`, objeto commit adulterado, árvore divergente,
headers inválidos, blob adulterado,
traversal, links, arquivos especiais, modo incorreto, caminho protegido,
mutação da origem, substituição da raiz, contrato de `/tmp`, ambiente do
subprocesso e saída sanitizada. A revisão independente bloqueou a primeira
versão por permitir `git replace`; a implementação corrente fecha esse bypass
e o possível leak em falha precoce de criação. A rechecagem final concluiu
`GO`, com `P0=0`, `P1=0` e `P2=0`.

## Limites e rollback

O snapshot é somente fonte. Ele não autoriza conexão, captura, SQL, DML,
migration, runner, DEV, PROD, deploy, flag ou runtime. Uma falha de criação,
autenticação ou cleanup bloqueia a etapa consumidora. O rollback é deixar de
usar e remover o snapshot identificado; nenhuma permissão do checkout
compartilhado é alterada.

A condição histórica `0775` continua existindo no workspace, mas deixa de ser
aceita como caminho operacional. O P2 é encerrado pela política de isolamento,
não por enfraquecimento dos verificadores nem por `chmod` global.

`operational_authorization=false` e `next_stage_authorized=false` permanecem
estritos.

## Próximo estágio único

`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`, limitado
à implementação e aos testes offline/PG17 descartáveis de um executor que use
o snapshot confiável, faça identidade e captura na mesma conexão, aceite DEV e
PROD como alvos separados e emita somente artefatos sanitizados bloqueados.
Este registro não declara consumo e não autoriza credencial, rede, banco
compartilhado, captura viva, cutover ou aplicação de migration.
