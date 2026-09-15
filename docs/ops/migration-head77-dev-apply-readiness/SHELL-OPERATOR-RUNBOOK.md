# Runbook humano para as duas saídas sanitizadas

Status: leitura somente. Este runbook não autoriza aplicação, SSH pelo agente,
alteração de VPS, banco, credencial, deploy, restart, flag ou acesso a PROD.

O operador é Raniel. A missão é vinculada ao SHA
`5e2082e94db2b6af6b34cfe351d81cf54b85aa76` e ao catálogo público de 77
migrations, digest
`162854e0f753f5ad867aacae6b450d46d5c4bd68f8c3089be144d133ddc73801`.

## Regra de parada

Pare sem tentativa de reparo se o release, a imagem, o SHA, a versão do banco,
a identidade sanitizada, qualquer ledger ou qualquer metadado E4b divergir do
esperado. Não use SQL Editor, `apply_migrations.py`, V2, V3, `db push`, DDL
manual, `DROP`, backfill, reconciliação ou cópia de ledger.

## Saída 1: observação mínima da VPS

Somente Raniel, em uma sessão VPS já autorizada, pode executar estes quatro
comandos. Este é o conjunto completo de comandos VPS permitido por este
runbook:

```bash
date --iso-8601=seconds
readlink -f /opt/pastorai-current
docker ps --no-trunc --format 'table {{.Names}}\t{{.Image}}\t{{.ID}}\t{{.Status}}' | grep -E 'pastorai-(backend|queue-worker|cron-worker|broadcast-worker)'
docker image ls --no-trunc --format 'table {{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.CreatedAt}}' pastorai-backend:latest
```

Registre somente o horário, a resolução do symlink, os nomes de containers, os
IDs e identidades de imagem mostrados e o status. Não use `docker inspect`, `docker compose`,
logs, variáveis de ambiente, arquivos `.env`, conexão remota adicional ou
qualquer comando de banco.

A saída identifica o release e a imagem observados, mas não demonstra sozinha
que a imagem veio do SHA desta missão. A ligação entre ambos requer revisão
humana e evidência externa própria.

## Saída 2: preflight DEV manual

Em uma sessão DEV já autenticada por canal seguro fora deste pacote, execute
integralmente `DEV-READONLY-PREFLIGHT.sql`. O arquivo abre uma transação
`REPEATABLE READ READ ONLY`, fixa timeouts, consulta apenas versão, identidade
sanitizada, ledgers e catálogos de sistema, e termina o caminho normal com
`ROLLBACK`.

Não acrescente parâmetros, não altere o `search_path`, não habilite
`row_security` em sentido permissivo e não inclua credenciais, host, IP, banco,
role nominal, DSN, `system_identifier` ou payload de domínio na transcrição
compartilhada. Se houver erro antes do `ROLLBACK`, rode apenas `ROLLBACK;` na
sessão atual e encerre a coleta. Não tente corrigir nem repetir com outro
principal.

## Conteúdo admissível das saídas sanitizadas

Pode permanecer na evidência:

- versão PostgreSQL e propriedades da transação;
- relações booleanas da identidade sanitizada e flags de privilégio;
- estado, colunas e entradas de ledger de migration;
- nomes, colunas, constraints, índices, policies, ACLs e triggers das seis
  relações E4b;
- caminho de release, nome de container, imagem e status.

Deve ser removido antes de compartilhar:

- credenciais, certificados, tokens, variáveis, DSNs, endpoints, hosts, IPs e
  nomes reais de banco ou usuário;
- qualquer linha de `pessoas`, `app_users`, `igrejas` ou relação E4b;
- mensagens, telefones, conteúdo pastoral, dumps, logs e dados de runtime.

## Entrega e interpretação

Anexe as duas saídas apenas como evidência pendente nos documentos desta
missão. Elas podem fechar ou confirmar bloqueios, mas não criam autorização de
aplicação. O `APPLICATION-PACKET.md` permanece bloqueado enquanto não existir
um executor catalog-bound de aplicação seguro, vinculado ao SHA exato e
autorizado em missão separada.
