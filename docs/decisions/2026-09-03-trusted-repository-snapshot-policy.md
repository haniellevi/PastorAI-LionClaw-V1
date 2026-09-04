# Snapshot confiável do repositório para governança de migrations

Data: `2026-09-03`

Estado: `IMPLEMENTADO E COMPROVADO OFFLINE / MITIGACAO PARCIAL PARA
CONSUMIDORES MIGRADOS / BOOTSTRAP EXTERNO AINDA NAO PINADO / AINDA NAO
INTEGRADO / SEM ATESTACAO VIVA / OPERACAO BLOQUEADA`.

Base auditada: `c2fb16ad9a6b028c317c56a0b02c4362ae903e26`.

## Problema

As ferramentas legadas de captura e reconciliação que impõem a política de
permissões estrita rejeitam qualquer ancestral, diretório de governança ou
arquivo gravável por grupo ou por outros. Essa guarda não existe uniformemente
em todo verificador; em particular, o verificador do head do catálogo vincula e
revalida metadados, mas não rejeita sozinho o modo `0775`.
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
`GO`, com `P0=0`, `P1=0` e `P2=0` estritamente no escopo da primitiva offline
revisada. Essa classificação não encerra o risco residual do checkout físico.

## Limites e rollback

O snapshot é somente fonte. Ele não autoriza conexão, captura, SQL, DML,
migration, runner, DEV, PROD, deploy, flag ou runtime. Uma falha de criação,
autenticação ou cleanup bloqueia a etapa consumidora. O rollback é deixar de
usar e remover o snapshot identificado; nenhuma permissão do checkout
compartilhado é alterada.

A condição `0775` continua existindo no workspace. Seu uso direto é mitigado
somente para consumidores migrados quando a primitiva e o bootstrap forem
iniciados por um launcher externo confiável. Esse trust anchor ainda não
existe; além disso, as ferramentas legadas de apply, capture e reconcile ainda
não foram integradas transitivamente ao snapshot. Portanto, o P2 permanece
aberto globalmente, sem enfraquecimento dos verificadores nem `chmod` global.

`operational_authorization=false` e `next_stage_authorized=false` permanecem
estritos.

## Próximo estágio único

O gate `OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`
foi consumido exclusivamente para o candidato local documentado em
[`2026-09-03-migration-environment-attestation-executor-v2.md`](2026-09-03-migration-environment-attestation-executor-v2.md).
Ele reinvoca o código a partir deste snapshot e mantém DEV e PROD como alvos
separados. Identidade e captura compartilham conexão e backend PID, mas usam
duas transações e dois snapshots `REPEATABLE READ READ ONLY` separados. O
resultado permanece sanitizado e bloqueado; nenhuma conexão viva foi feita.

O único estágio corrente global é
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`,
restrito à consulta remota somente leitura de `refs/heads/main`, ao preflight da
base, ao push da branch candidata, à abertura da PR e à observação do CI e do
Vercel Preview automáticos. Não autoriza merge, banco compartilhado, DEV, PROD,
migration, runner ou alteração de flags;
`operational_authorization=false` e `next_stage_authorized=false` permanecem
estritos.

Somente após a integração posterior sob gate próprio e o CI verde, o estágio
funcional futuro poderá ser
`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_EXECUTOR_V2_EXTERNAL_TRUST_ANCHORS_OFFLINE`;
ele não é o estágio corrente nem está autorizado.
