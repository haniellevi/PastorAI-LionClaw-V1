# PastorAI / Igreja 12 — evidência de fechamento da V1

Atualizado em 2026-08-22 (UTC). Este registro não contém credenciais, tokens,
identificadores de usuários nem destinatários de canário.

## Estado deste registro

**V1_ENCERRADA**. Os gates operacionais foram aprovados no SHA de código
`281e69c2fef80cfbcb27eab5ca4f85981e4adc0c`. Este registro foi integrado pela
PR #274 em `ea40cda3dbe596b1d17035c242762df257068cf0`; a tag anotada e o
GitHub Release `v1.0.0` foram publicados no SHA de código; a declaração final e
o housekeeping foram integrados pela PR #275 em
`ba9dba77a464101fc8eb5a67a9bcd42de17d429d`.

## Revalidação independente pós-encerramento

Revalidado em 2026-08-22 entre 01:50 e 02:03 UTC, sem escrita em produção:

- GitHub: PRs #274 e #275 estão `MERGED`; a referência remota `v1.0.0` resolve
  para o objeto anotado `08eada056490a26af758ddcf712df34c07079f99`, que aponta
  para o SHA de código; o Release é público, não é draft nem prerelease.
- CI do RC: `Backend Tests`, `Frontend CI`, `E2E Critical`, `RLS Integration`
  e `Tooling Static Checks` terminaram com `success` no HEAD da PR #271, cujo
  merge commit é o SHA de código da V1.
- Monitor público: a execução agendada `32544604262`, já na `main` documental
  final, terminou com `success`. Sondas externas posteriores retornaram
  `/health = ok` e `/ready = ready`, com database, Redis, Evolution,
  queue-worker, cron-worker e broadcast-worker em `ok`.
- Vercel: `dpl_CdwTcTE8HZHvxs9t92Ak6sHxebAp` continua como deployment de
  produção mais recente, em estado `READY`, com `gitCommitSha` igual ao SHA de
  código. `app.`, `admin.` e `painel.igreja12.com.br` retornaram HTTP 200 com
  CSP `frame-ancestors 'none'`, Referrer-Policy e Permissions-Policy. Não houve
  erro de runtime agregado na janela de 24 horas consultada.
- Supabase PROD `pffafnchtxbimpwyaczq`: projeto `ACTIVE_HEALTHY`, PostgreSQL
  17; 53/53 tabelas públicas com RLS. As quatro tabelas fechadas mantêm uma
  única policy restritiva exata e nenhuma ACL efetiva de tabela ou coluna para
  `anon`/`authenticated`. A função M01 continua excluindo preço zero e existem
  zero operações automáticas `prepared` inválidas. Os recibos M06/M01 seguem
  no ledger.
- Advisors do Supabase: um `WARN` de segurança intencional e já aceito para
  `current_igreja_id()`; 75 recomendações `INFO` de performance (51 FKs sem
  índice de cobertura e 24 índices ainda sem uso), sem finding P0--P2 novo.

O acesso SSH temporário foi revogado no fechamento. Por isso, esta revalidação
não releu o symlink, os contadores de restart, as flags nem o manifesto de
backup na VPS; esses itens continuam sustentados pela prova de fechamento
abaixo. Os planos de controle públicos, Vercel e Supabase não indicaram
regressão posterior.

## Release candidate e CI

- `origin/main`: `281e69c2fef80cfbcb27eab5ca4f85981e4adc0c`.
- Backend Tests, Frontend CI, E2E Critical, RLS Integration e Tooling Static
  Checks passaram no RC.
- Validação local do RC: 2.534 testes backend, 786 testes frontend, cinco E2E,
  22 testes RLS em PostgreSQL 17, lint, typecheck, build, Compose e auditorias.
- CRG: raiz `/home/raniel-linux/workspace/PastorAi-1.0-dev-ledger-ops`, build e
  HEAD no RC, `head_matches_build=true`.
- Graphify: `NAO_COMPROVADO` para esta evidência; não foi usado como prova.

## Backend e frontend publicados

- Backend ativo: `/opt/pastorai-releases/281e69c2fef80cfbcb27eab5ca4f85981e4adc0c`.
- `/opt/pastorai-current` resolve para o release acima.
- Backend, queue-worker, cron-worker e broadcast-worker saudáveis, com zero
  restart após o roll-forward final.
- Frontend Vercel: projeto `pastorai-frontend`, time
  `raniel-levis-projects`, deployment
  `dpl_CdwTcTE8HZHvxs9t92Ak6sHxebAp`.
- Metadado Vercel `gitCommitSha`:
  `281e69c2fef80cfbcb27eab5ca4f85981e4adc0c`.
- `app.`, `admin.` e `painel.igreja12.com.br` apontam para o mesmo deployment.
- As três superfícies retornam HTTP 200, sem referências a localhost ou ao
  projeto DEV, com `frame-ancestors 'none'`, `Referrer-Policy` e
  `Permissions-Policy` esperadas.
- A consulta de erros agregados da Vercel não encontrou erro de runtime na
  janela pós-deploy.

## Clerk DEV controlado

A auditoria sanitizada encontrou seis usuários em PROD. Todos tinham identidade
correspondente no Clerk DEV, senha habilitada e e-mail primário verificado; os
seis IDs DEV eram diferentes dos IDs LIVE.

Após autorização nominal:

1. foi criado backup fresco;
2. a configuração LIVE e os seis vínculos antigos foram preservados em arquivos
   root-only na VPS, com hash do mapa de rollback;
3. exatamente os seis vínculos auditados foram atualizados em uma transação;
4. secret key, publishable key, issuer e JWKS foram trocados como conjunto
   coerente para Clerk DEV;
5. os quatro processos foram recriados e as flags externas permaneceram
   fechadas;
6. a pós-condição confirmou seis vínculos únicos, sem duplicidade ou vínculo
   cruzado.

A troca invalida sessões LIVE anteriores e exige novo login, comportamento
esperado para o piloto. O rollback preservado restaura configuração LIVE e os
vínculos anteriores em conjunto.

## Supabase PROD e ledger

Alvo único: `pffafnchtxbimpwyaczq`, PostgreSQL 17.

- 53/53 tabelas públicas com RLS habilitado.
- M06: quatro policies restritivas `service_role_bypass_only` exatas e zero ACL
  efetiva de `anon`/`authenticated` nas tabelas fechadas.
- M01: função `fn_subscription_autoupgrade()` presente com exclusão de planos de
  preço zero; zero operação automática `prepared` apontando para plano
  inexistente ou de preço zero.
- Hash M06:
  `1524fa0944dd3f4c259fa81f528570f8a4be5cff010515d4c44ac30a8df063c6`.
- Hash M01:
  `31f1f26f62594e19d6bd1cee3b4e8a4665da8207188192764d09272d880367d1`.

O DDL já estava aplicado e **não foi reaplicado**. Sob transação serializable e
advisory lock, o ledger oficial `supabase_migrations.schema_migrations` recebeu
somente recibos de metadados:

- versão `20260810031050`, M06;
- versão `20260810042300`, M01.

Os recibos incluem nome e SHA-256 e usam `created_by` igual a
`pastorai-v1-ledger-reconciliation`.

## Backup e restauração

Backup usado na prova final:

- arquivo: `pastorai-backup-20260821T213637Z.tar.gz`;
- SHA-256:
  `940e14a331838cd1499c47d7bc2adea3bd897cc2f292e6e3f326f67612459c0e`;
- manifesto: `verified`.

Restauração real em containers descartáveis e sem portas públicas:

- Supabase em PostgreSQL 17: 53 tabelas, 11 funções, 9 triggers e 225
  constraints restaurados;
- Evolution em PostgreSQL 16: 37 tabelas restauradas;
- dumps passaram em `pg_restore --exit-on-error`;
- arquivos de volumes Evolution/Redis passaram na inspeção estrutural;
- manifesto de Storage foi parseado e validado.

Uma cópia externa à VPS foi transferida para a estação Linux, cifrada com
AES-256-CBC/PBKDF2, teve checksum próprio gerado e foi descriptografada em
stream para comprovar a leitura do tar. A chave ficou em diretório separado com
modo 0700/0600. O pacote em claro temporário foi removido.

## Smokes PROD e isolamento

Os cinco perfis foram autenticados manualmente em janela isolada, encerrando a
sessão entre perfis. A inspeção automatizada via CDP não registrou 5xx nem erros
de console inesperados.

- administrador: Painel de Hoje e Gestão permitidos; Console master bloqueado;
- pastor: Painel e Central de Célula permitidos; Gestão bloqueada;
- líder de célula: Painel e Minha Célula permitidos; Central e Gestão bloqueadas;
- membro: Painel permitido; Central e Gestão bloqueadas;
- master: Console, igrejas, planos e auditoria permitidos; sessão master não foi
  herdada pela superfície tenant.

Nenhum dado pastoral foi criado, editado, enviado, faturado ou excluído.

## Brevo

O sistema foi promovido temporariamente para `BREVO_SEND_MODE=canary` com
exatamente um destinatário em allowlist. Os quatro consumidores foram
recriados, um único convite transacional foi aceito pelo Brevo e o recebimento
foi confirmado pelo responsável. Em seguida:

- `BREVO_SEND_MODE=off`;
- `BREVO_CANARY_RECIPIENTS` vazio;
- quatro processos recriados;
- gates globais permaneceram fechados.

O destinatário e o message ID não são registrados; somente o prefixo do hash do
message ID foi preservado na evidência operacional da sessão.

## Rollback e roll-forward

- Backend anterior: `f2c3132b2a1d5060c4ba236374f0475416973be2`.
- Frontend anterior: `dpl_3Xs4JwQa588DZqXRYTQCAwZEnN6c`.
- O rollback trocou somente código/imagens e deployment; banco, volumes e
  arquivo de ambiente não foram alterados.
- Health, readiness e login manual foram aprovados no release anterior.
- O roll-forward restaurou backend `281e69c...` e frontend
  `dpl_CdwTcTE8HZHvxs9t92Ak6sHxebAp`.
- Após o roll-forward, health, readiness, aliases, headers, login e flags foram
  revalidados.

## Estabilidade e flags finais

Duas execuções locais consecutivas do monitor retornaram `healthy`. Os
workflows GitHub `32543076877` e `32543098661`, disparados após o roll-forward,
passaram. Os quatro processos ficaram saudáveis, com zero restart e zero padrão
grave nos logs inspecionados.

Flags finais:

```text
ALLOW_REAL_SENDS=false
ASAAS_BILLING_ENABLED=false
BROADCAST_ASYNC_ENABLED=false
BREVO_SEND_MODE=off
BREVO_CANARY_RECIPIENTS=
```

Asaas real, broadcasts, WhatsApp/envios globais e Brevo live permanecem
desligados.

## Riscos e pós-V1

- Clerk DEV permanece restrito ao piloto; Clerk Production é missão pós-V1.
- PR #257 e transferência/remoção de membros de Células permanecem pós-V1.
- Cobrança real Asaas permanece pós-V1.
- O único WARN de segurança aceito é a execução de `current_igreja_id()` por
  `authenticated`, necessária às policies RLS. Dívidas de índices são
  informativas e pós-V1.
- A tag remota, o GitHub Release e o housekeeping foram concluídos. A PR #275
  integrou a declaração final; o estado canônico é `V1_ENCERRADA`.
