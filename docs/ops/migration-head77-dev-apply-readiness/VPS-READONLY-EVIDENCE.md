# Evidência read-only da VPS

Status: `COMPLETA_PARA_O_CONJUNTO_AUTORIZADO / PROVENIENCIA_OBSERVACIONAL`.

Coleta completa executada manualmente por Raniel em
`2026-09-15T01:56:43+00:00`.
Esta evidência registra somente a saída sanitizada recebida; nenhum agente
abriu SSH, leu configuração, imprimiu segredo ou escreveu na VPS.

## Saída sanitizada recebida

```text
readlink -f /opt/pastorai-current
/opt/pastorai-releases/c525d6a3897a12c6c287f9fc79a88b32b34cd452

NAMES                       IMAGE                      ID                                                                STATUS
pastorai_cron_worker        pastorai-backend:latest    b56cac777e938580fd1906b95ac90b84ba9bd19da11e18ebf50c10a9604284ca  Up 10 days (healthy)
pastorai_backend            pastorai-backend:latest    1a8a6a80e44f8ebf097fdc680eba1611e5aabd376986538f86b9ef2fabc731fa  Up 13 days (healthy)
pastorai_queue_worker       pastorai-backend:latest    13e7b1747398d5d4c2fe20b3d240eddd2947859ab37dd1a7a33e8753fe9e5ca5  Up 20 hours (healthy)
pastorai_broadcast_worker   pastorai-backend:latest    314434ff50adba67d8a73cb0d850837622a9c6ea146fc9a02a3c2e651f724aa2  Up 2 weeks (healthy)

pastorai-backend:latest  sha256:833d51b5ff40b6bcb576d90449054da342cdfda24d5b93046033c466cda2b1f7  2026-08-26 04:53:43 +0000 UTC
```

## Reconciliação local

O release observado é o commit
`c525d6a3897a12c6c287f9fc79a88b32b34cd452`, de
`2026-08-26T00:22:43-03:00`, merge da PR `#303`. A verificação local
`git merge-base --is-ancestor` terminou com exit `0`: esse commit é ancestral
do SHA da missão `5e2082e94db2b6af6b34cfe351d81cf54b85aa76`.

O registro operacional versionado também identifica `c525d6a` como release
servido no preflight de `2026-08-26`. A leitura atual do symlink comprova que o
release continuava selecionado no horário desta coleta. A imagem local
`pastorai-backend:latest` foi observada com ID
`sha256:833d51b5ff40b6bcb576d90449054da342cdfda24d5b93046033c466cda2b1f7`
e criação em `2026-08-26T04:53:43Z`, cronologicamente coerente com o release.

## Limite da evidência

Os valores da coluna `ID` de `docker ps` são IDs de containers. O quarto
comando fixa o ID atual da imagem associada à tag local, mas o conjunto
autorizado não lê labels nem manifesto de build. Assim, a coleta está completa
para o runbook e demonstra release, tag, image ID e saúde observados; ela não
é uma atestação criptográfica de que os bytes da imagem derivam de `c525d6a`.

A saída DEV também permanece pendente. Nenhuma migration foi aplicada e esta
evidência não abre gate de deploy, runtime, envio, billing, broadcast ou
`AgentConfig.ativo`.
