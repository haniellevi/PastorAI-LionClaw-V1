# Proposta offline para remediar a divergência do histórico de migrations

**Estado:** `PROPOSTA OFFLINE / REVISÃO HUMANA BLOQUEADA CONCLUÍDA /
DECISÃO DO OWNER REGISTRADA / NÃO APROVADA PARA IMPLEMENTAÇÃO / NÃO APLICADA`

**Base:** `f73a631c632a1b37cea07073c91fe6ad2a81e995`

## Decisão que governa esta proposta

A revisão independente terminou em bloqueio. DEV possui ledger público com 33
linhas, 6 linhas nativas e deixa de formar o prefixo do catálogo na posição 25,
com oito posições divergentes. PROD não possui ledger público e contém 32
linhas nativas com nomes sanitizados como `null`. Nenhuma dessas observações
autoriza inferir aplicação.

O registro externo da revisão independente possui SHA-256
`18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133`.
O proprietário aceitou o bloqueio e autorizou apenas esta preparação offline;
o registro externo da decisão possui SHA-256
`0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240`.
Os registros brutos, nomes, contatos e assinaturas não são versionados.

## Princípio de correção

Histórico incompleto não deve ser “consertado” por preencher o ledger. Uma
correção segura precisa preservar os fatos legados, provar o estado estrutural
atual por evidência independente e estabelecer uma fronteira futura sem afirmar
que as 75 migrations foram aplicadas.

Por isso, esta proposta recomenda um corte de época controlado somente depois
de uma atestação completa do schema e das invariantes de dados. O corte futuro
não é um backfill, não torna os dois ledgers equivalentes e não apaga a
divergência histórica. Ele cria uma nova fronteira auditável para migrations
posteriores, em contrato ainda a desenhar e revisar.

## Alternativas

### Reconstrução forense completa

É a alternativa de maior fidelidade histórica quando existem registros
externos suficientes para cada migration. O material atual não oferece essa
prova, especialmente em PROD, e a alternativa permanece bloqueada até que
evidências independentes sejam apresentadas.

### Corte de época após atestação

É a recomendação para análise futura. Antes de qualquer implementação, exige:

1. manifesto offline e versionado de objetos, constraints, funções, policies,
   triggers, grants e invariantes de dados esperados;
2. revisão independente de segurança e arquitetura de banco;
3. missão separada e autorizada de captura somente leitura em cada ambiente;
4. comparação fail-closed entre manifesto e captura, sem inferir aplicação;
5. decisão humana explícita sobre o corte;
6. PR técnica separada para qualquer novo ledger, namespace ou mudança de
   runner;
7. autorização operacional separada para cada ambiente.

Qualquer ausência ou divergência mantém o processo bloqueado.

### Reconstrução do ambiente a partir do catálogo

É o fallback quando nem a história nem o estado estrutural puderem ser
atestados. Exige plano próprio para dados, indisponibilidade, rollback,
integridade, tenant, integrações e continuidade de negócio. Não está autorizada
por esta proposta.

## Contrato machine-readable

O arquivo
[`migration-history-divergence-remediation-proposal-v1.json`](../governance/migrations/migration-history-divergence-remediation-proposal-v1.json)
vincula os seis artefatos, os dois registros humanos opacos, os achados e os
gates futuros. Ele mantém todas as permissões operacionais em `false` e não é
entrada do runner.

`backend/scripts/apply_migrations.py` deve permanecer inalterado nesta missão.
O SHA-256 fixado do runner é
`36e63cde6751cd0cb33e1511091068b0b04f10029ace06703eead82e0e836c65`.
O verificador offline também permanece inalterado, no SHA-256
`9451cbe5054d8c0d7e2754d09dea7f3a9761e8585269ca783eea943dd785dfae`.
Nenhum novo subcomando, migration, marker ou bypass é criado.

## Limites desta missão

Esta preparação não acessa DEV ou PROD, não usa rede, não executa SQL ou DML,
não cria ou preenche ledger, não aplica migration, não faz backfill, não altera
runner, deploy, flag ou runtime. `OPERATIONAL_AUTHORIZATION=BLOCKED` permanece
o único estado operacional válido.

## Próximo gate único

Revisar esta proposta offline por segurança e arquitetura de banco. O gate pode
aprovar apenas a preparação do manifesto estático de expectativas do schema.
Ele não autoriza captura de ambiente, implementação de corte, alteração do
runner, migration, backfill, deploy, flag ou runtime.
