# Runbook humano F1, observação DEV somente leitura

## Pré-condições obrigatórias

Este runbook é para Raniel. Agentes não abrem a sessão DEV, não recebem DSN,
host, usuário, credencial ou target binding. A execução não é um caminho de
aplicação e não autoriza alteração de migration, ledger, schema, deploy ou
flag.

Raniel não executa `DEV-READONLY-F1.sql` antes de OpenCode e CLAUDE conferirem
como `APTO` o candidato congelado, o manifesto e o SHA-256 exato do SQL. Essa
conferência conjunta, limitada a B1, B2 e regressão, é o próximo gate. O
candidato SQL `09eaa414ea222d4bb3c1675d799eba9124f81791c460e2fa5c4c7195b319d306`
foi julgado conjuntamente como `NAO_APTO` e qualquer `APTO` anterior foi
revogado. Ela não pode ser substituída por teste local, recibo anterior,
aprovação genérica ou conferência de arquivo diferente.

1. Confirme que o diretório candidato, a branch e a base são os registrados em
   [F1-REPORT.md](F1-REPORT.md).
2. Confira que OpenCode e CLAUDE declararam `APTO` para esse candidato, esse
   manifesto e `DEV-READONLY-F1.sql` de SHA-256
   `8829decd0f0101329058ad07900ce7b7ca8b1c4fe5695f4e3cec05cff4bf288c`.
   Sem os dois resultados para esses bytes exatos, pare antes de abrir psql.
3. Confira o SHA-256 de `DEV-READONLY-F1.sql` contra
   [F1-CANDIDATE-MANIFEST.md](F1-CANDIDATE-MANIFEST.md). Não use arquivo
   copiado, truncado ou com hash diferente.
4. Obtenha, pelo canal humano autorizado, um `f1_target_binding_sha256` novo,
   opaco e de 64 hexadecimais minúsculos. Ele não é credencial e não deve ser
   exibido, versionado, colado em evidência ou reutilizado em outra coleta.
5. Abra a sessão DEV já autenticada e vinculada pelo seu procedimento humano,
   com o histórico desabilitado antes de qualquer linha interativa. Prefira
   iniciar o cliente com `PSQL_HISTORY=/dev/null psql -n ...`, mantendo os
   parâmetros de conexão fora deste pacote. `-n` desabilita o readline e é a
   forma mais robusta. Não use `HISTFILE=...` como variável de ambiente, pois
   ela não configura o histórico do `psql`.
6. Se a sessão já estiver aberta, a primeira linha digitada nela precisa ser
   `\set HISTFILE /dev/null`; não execute nenhuma outra linha antes dela. Não
   dependa apenas de `\set HISTSIZE 0`.
7. Antes de executar, confirme que a transcrição será sanitizada e que nenhuma
   saída de terminal, histórico ou arquivo de evidência preservará binding,
   identificação de sessão, nome de role inesperada, statement ou linha de
   domínio.

## Execução exata dentro da sessão psql já autorizada

No `psql` autenticado, sem alterar `search_path` nem acrescentar consultas, a
ordem obrigatória é: desabilitar o histórico, silenciar o eco, pedir o binding
sem colocá-lo na linha de comando e incluir o arquivo hash-conferido. Para uma
sessão já aberta, execute exatamente:

```psql
\set HISTFILE /dev/null
\set ECHO none
\prompt 'binding: ' f1_target_binding_sha256
\i /caminho-local-conferido/docs/ops/dev-migration-history-remediation/DEV-READONLY-F1.sql
```

`\set HISTFILE /dev/null` deve ser a primeira linha da sessão. Quando o cliente
for iniciado com `PSQL_HISTORY=/dev/null psql -n ...`, o histórico já estará
desabilitado antes da sessão e a primeira linha interna será `\set ECHO none`,
seguida por `\prompt` e `\i`. Nunca informe o binding com `\set` de valor,
`psql -v`, argumento do shell ou variável escrita na linha de comando, pois
isso pode preservá-lo no histórico do `psql` ou do shell.

O arquivo executa, nesta ordem:

```sql
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '15000ms';
SET LOCAL lock_timeout = '2000ms';
SET LOCAL row_security = off;
ROLLBACK;
```

Ele usa apenas `pg_catalog`, mais leituras de
`public.schema_migrations` e `supabase_migrations.schema_migrations` que só
ocorrem depois da verificação da forma mínima de cada ledger. O ledger público
precisa ter exatamente 33 entradas e o nativo, exatamente 6. Divergência de
forma ou contagem é saída inesperada: Raniel executa somente `ROLLBACK;`,
encerra e envia o erro sanitizado, sem corrigir nem repetir, pois DEV pode ter
mudado desde 14/09. `SET LOCAL row_security = off` é deliberado para falhar
fechado se uma leitura dependesse de bypass de RLS. A leitura da coluna
`statements` retorna apenas hash, cardinalidade e padrão DDL não sensível.
Nenhum statement é selecionado ou impresso.

O primeiro registro da saída é `TARGET_DIGEST`, cujo segundo campo é o
SHA-256 hexadecimal desta fórmula, sem expor qualquer componente:

```sql
encode(
  sha256(
    convert_to(
      binding || chr(31) || current_database() || chr(31) ||
      COALESCE(inet_server_port()::text, 'UNIX_SOCKET') || chr(31) ||
      current_setting('server_version_num'),
      'UTF8'
    )
  ),
  'hex'
)
```

Se precisar conferir o digest localmente, faça-o fora da transcrição e sem
salvar a saída. O binding é lido sem eco, fica somente em memória de shell e é
apagado ao final. Informe `UNIX_SOCKET` literalmente no terceiro prompt quando
essa for a conexão, e não copie os quatro valores nem o digest para evidência,
histórico ou arquivo. O `printf` abaixo intercala exatamente o separador de
byte `0x1f` entre os quatro valores antes de chamar `sha256sum`.

```bash
read -r -s -p 'binding opaco: ' f1_local_binding
printf '\n' >&2
read -r -p 'database fora da transcrição: ' f1_local_database
read -r -p 'porta ou UNIX_SOCKET fora da transcrição: ' f1_local_port_or_socket
read -r -p 'server_version_num fora da transcrição: ' f1_local_server_version_num
printf '%s\x1f%s\x1f%s\x1f%s' \
  "$f1_local_binding" "$f1_local_database" "$f1_local_port_or_socket" \
  "$f1_local_server_version_num" | sha256sum | awk '{print $1}'
unset f1_local_binding f1_local_database f1_local_port_or_socket f1_local_server_version_num
```

O comando é apenas uma comparação manual com `TARGET_DIGEST`. Ele não confirma
identidade, host, autorização ou que o alvo seja DEV. Essas propriedades continuam
dependentes do procedimento humano autorizado, fora da transcrição.

Depois de encerrar o `psql`, ainda fora da transcrição, procure os primeiros 12
caracteres do binding em `~/.psql_history` e `~/.bash_history`. A contagem em
ambos deve ser zero. Faça a busca com o prefixo lido silenciosamente em uma
variável, sem escrever o valor na linha de comando:

```bash
read -r -s -p 'primeiros 12 caracteres do binding: ' f1_history_probe
printf '\n' >&2
for f1_history_file in "$HOME/.psql_history" "$HOME/.bash_history"; do
  if [ -f "$f1_history_file" ]; then
    printf '%s ' "$f1_history_file"
    grep -F -c -- "$f1_history_probe" "$f1_history_file"
  else
    printf '%s 0\n' "$f1_history_file"
  fi
done
unset f1_history_probe f1_history_file
```

Se qualquer contagem for diferente de zero, remova a ocorrência local, descarte
esse binding e gere um novo antes de outra coleta autorizada. Em todos os casos,
limpe o scrollback do terminal depois da sessão. Não copie a linha exibida pelo
prompt, o binding, seu prefixo ou o resultado detalhado da busca para a
transcrição sanitizada.

O arquivo termina com `ROLLBACK_COMPLETED_F1`. Se qualquer erro ou saída
inesperada ocorrer antes desse recibo, execute somente o comando abaixo na mesma
sessão, encerre a coleta e envie o erro sanitizado. Não tente corrigir, repetir
com outro principal, executar SQL Editor ou abrir uma segunda sessão. Uma nova
tentativa exige nova conferência de OpenCode e CLAUDE como `APTO` para o
candidato, manifesto e SQL exatos.

```sql
ROLLBACK;
```

## Conteúdo permitido na transcrição sanitizada

Pode retornar ao Orquestrador somente:

- `record_type`, booleanos de transação, versão major/número do PostgreSQL e
  estados categóricos do binding;
- hashes MD5 de identificadores de ledger e de definições de catálogo;
- `TARGET_DIGEST` como um único SHA-256 de 64 hexadecimais, sem binding,
  database, porta, transporte, usuário ou outro componente da tupla;
- nomes de objetos estáticos do catálogo quando não forem mascarados pelo
  próprio script, tipos, flags, contagens, hashes de definição e estado RLS;
- classificação `PUBLIC`, `ALLOWLIST_ROLE`, `PLATFORM_ROLE` ou
  `UNEXPECTED_CUSTOM_GRANTEE`; `grantee_ref` pode ser `PUBLIC` ou o nome da
  role somente quando sua classe for `ALLOWLIST_ROLE` ou `PLATFORM_ROLE`, e
  permanece `UNEXPECTED_CUSTOM_GRANTEE` sem nome ou OID para role inesperada;
- referências opacas de relação, função, constraint, índice, policy e trigger
  quando o próprio script marcar a relação como mascarada;
- posição opaca e fingerprints de ledger, sem statement text.

Remova e não compartilhe:

- target binding, host, porta, DSN, database, current user, session user,
  certificado, token, IP, PID, snapshot ou identificador reutilizável;
- statement do ledger nativo, definição bruta de policy, function, trigger,
  índice, constraint ou default;
- qualquer linha, contagem, identificador ou conteúdo de domínio;
- nome ou OID de role classificada como `UNEXPECTED_CUSTOM_GRANTEE`.

## Como interpretar sem inferir

- `UNEXPECTED_CUSTOM_GRANTEE` bloqueia classificação positiva de ACL até
  revisão humana. O nome não deve ser solicitado por este pacote.
- `PLATFORM_ROLE` identifica somente as cinco roles de plataforma previstas na
  allowlist. Não reduz a detecção de uma role customizada.
- O MD5 da coluna `statements` serve apenas para comparar duas coletas
  sanitizadas DEV/PROD do mesmo protocolo. Nunca o compare com SQL do
  repositório, hash de migration, nome de arquivo ou conteúdo de statement.
- O regex de classificação DDL ignora um comentário inicial antes do padrão
  não sensível. Ele não imprime o comentário nem o statement.
- Um objeto existente com tipo, hash, RLS, policy, trigger ou ACL divergente é
  `PARTIAL_OR_CONFLICTING`.
- Ausência de objeto pode ser `PHYSICAL_EFFECTS_ABSENT`, mas nunca prova que o
  arquivo não foi executado. O efeito pode ser condicional, compensado ou
  removido por mudança posterior.
- Para as nove linhas marcadas `NOT_SCHEMA_DECIDABLE`, não faça consulta de
  dados para tentar concluir backfill, seed, label ou reconciliação. A lacuna
  exige decisão humana separada.
- O ledger nativo é evidência secundária de fluxo por fingerprint e não pode
  ser associado a migration pública por versão, ordem ou data.

## Entrega humana

Depois de execução normal, Raniel entrega dois artefatos separados à ficha
operacional fora deste worktree:

1. a transcrição sanitizada, com seu hash, ambiente `DEV`, horário, SHA base,
   hash do candidato e resultado `ROLLBACK_COMPLETED_F1`;
2. uma declaração independente com exatamente um dos valores definidos na ficha:
   `DEV_DATA_DISPOSITION=NO_VALUE_NO_PII`,
   `DEV_DATA_DISPOSITION=VALUE_OR_PII_PRESENT` ou
   `DEV_DATA_DISPOSITION=UNKNOWN`.

Não inclua a declaração na transcrição, não a derive de schema ou ledger e não a
combine com o conteúdo da transcrição. Nenhum agente preenche, infere ou junta
esses dois entregáveis. Em falha, entregue somente o erro sanitizado após
`ROLLBACK;`; não emita os dois entregáveis normais e não tente novamente sem
nova conferência dos dois conselheiros. Mesmo uma execução normal desbloqueia
apenas a classificação documental 44/44, não executor, epoch, cutover ou
aplicação.
