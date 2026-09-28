# PR432: correções de revisão P1 e P2

Data: 2026-09-28T09:01:33-03:00

Ambiente: local sintético, sem Docker, Supabase, DEV ou PROD ativos.

Base e candidato: `847baab35301f3b588fc28d51316266aef53552b`.

## Resultado

P1 restringe `DATABASE_URL` ao PostgreSQL local canônico, exige recibo de
identidade emitido externamente pelo `dev.sh` e confere
`pg_control_system().system_identifier` na mesma conexão antes de DDL ou DML.
O seed deixa de usar o engine global cacheado e cria a sessão a partir da URL
validada. Cada conexão nova de migration recebe a mesma conferência.

O recibo é emitido pelo `dev.sh` por `docker exec` no container PostgreSQL local
conhecido, montado somente para leitura no backend e tem modo `0644` porque seu
conteúdo não é segredo e o processo do container usa `appuser` sem o UID do
operador. Não há acesso adicional a `.env.dev`, credenciais ou socket Docker.
Nenhuma variável de ambiente escolhe ou substitui o recibo. Antes de preparar a
stack, o `dev.sh` resolve e fixa exclusivamente um socket Unix local permitido,
inclusive os caminhos legítimos de Docker Desktop e rootless; host TCP, SSH e
contexto que os aponte são recusados. Os comandos Docker posteriores recebem o
endpoint fixado com o contexto removido.

As variáveis libpq que podem desviar a conexão, inclusive `PGHOSTADDR`,
`PGSERVICE` e `PGSERVICEFILE`, são recusadas antes de abrir `psycopg2` ou criar
o engine do seed.

P2 deixa de ignorar a falha de descoberta por `compose ps` ou de `compose up`
após `./dev.sh reset`: a saída do log é mostrada, o processo retorna não zero e
a mensagem de sucesso não é emitida. Lista vazia continua sendo um estado
normal, e o reinício saudável continua retornando sucesso.

## Testes executados

- Python 3.13.14 do venv runtime: 35 regressões sintéticas de P1 e P2.
- `bash -n dev.sh`.
- `git diff --check`.

Os dublês não iniciaram containers, não abriram banco e não leram arquivos de
ambiente.

## Limitações e rollback

O recibo evita destino acidental errado, inclusive um túnel loopback, mas não é
uma atestação criptográfica contra um operador que possa adulterar o host, o
container, um socket local permitido ou o arquivo de recibo. A operação real de
banco permanece fora desta fatia. Para rollback, reverta os arquivos desta fatia
em um commit posterior; nenhuma migration, dado, credencial ou estado externo
foi alterado.
