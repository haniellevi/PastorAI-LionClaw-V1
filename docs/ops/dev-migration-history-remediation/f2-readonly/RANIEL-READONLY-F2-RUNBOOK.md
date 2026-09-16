# Runbook humano F2, coletas PROD e DEV somente leitura

## Uso e limites

Este runbook é executado somente por Raniel, depois de OpenCode e CLAUDE
marcarem `APTO` os hashes exatos do manifesto, dos dois SQLs e deste arquivo.
Agentes não abrem sessão PROD ou DEV. A coleta não autoriza aplicação,
remediação, epoch, cutover, executor, migration, recriação DEV, deploy, envio,
billing, broadcast, Brevo, credencial ou mudança de flag.

PROD e DEV são duas operações independentes. Use terminais, sessões, bindings e
arquivos de captura diferentes. Feche e congele PROD antes de abrir DEV. Não
compare os resultados até os dois arquivos sanitizados terem hash e recibo
validados separadamente.

## Aviso operacional antes de PROD

Execute PROD fora do horário de pico. Uma conexão nova e consultas de catálogo
podem gerar alerta legítimo de monitoramento ou consumir uma vaga do limite de
conexões. Antes da sessão, Raniel confirma por procedimento humano que há
capacidade para uma conexão curta. Não suprima alerta, não eleve limite, não
reinicie serviço e não altere firewall, pool ou monitor.

Se houver alerta inesperado, dúvida sobre capacidade ou dúvida sobre o alvo,
não abra a sessão. Se o alerta surgir durante a coleta, execute somente
`ROLLBACK;`, encerre e devolva o motivo sanitizado. Não repita sem nova
conferência dos dois conselheiros.

## Pré-condições comuns

1. Trabalhe a partir do SHA e diretório declarados em
   `F2-CANDIDATE-MANIFEST.md`.
2. Reproduza o manifesto e confirme `RESULT=PASS_F2_MANIFEST_REPRODUCIBLE`.
3. Confirme o SHA-256 do SQL do ambiente antes de iniciar o `psql`.
4. Crie fora do repositório um diretório de evidência com modo `0700`; cada
   arquivo de captura deve terminar em modo `0600`.
5. Gere um valor aleatório novo de 32 bytes, representado por 64 caracteres
   hexadecimais minúsculos. Não o registre. PROD e DEV usam valores diferentes;
   nenhum reutiliza o binding F1.
6. Não coloque o binding em argv, variável de ambiente, linha de comando,
   `psql -v`, arquivo, clipboard persistente, histórico ou transcrição.
7. Não use SQL Editor. Use `psql` compatível com os meta-comandos do pacote.

## Abertura segura de uma sessão

Use um terminal dedicado. Antes de digitar host, usuário ou database, desligue
o histórico do shell. Preserve o estado do terminal e desligue o eco antes de
abrir o `psql`. A senha continua sendo digitada no prompt do cliente e nunca é
transcrita.

O bloco abaixo é um modelo operacional. Substitua os marcadores somente no
terminal local, sem salvar o comando e sem copiar a saída para a evidência:

```bash
set +o history
f2_stty_state="$(stty -g)"
trap 'stty "$f2_stty_state"; unset f2_stty_state' EXIT HUP INT TERM
stty -echo
PSQL_HISTORY=/dev/null psql -n -X -q -A -t -F '|' -P pager=off -P null='[null]' \
  -h <host> -U <user> -d <database> -W
```

Com `stty -echo`, nada digitado na sessão aparece no scrollback. O `trap`
restaura o terminal se o shell sair. Se o `psql` não abrir, restaure com
`stty "$f2_stty_state"`, encerre e não tente outro alvo.

## Sessão PROD

A primeira linha dentro do `psql` precisa ser `\set HISTFILE /dev/null`. Não
execute consulta de teste, `\conninfo` ou qualquer linha antes dela. Digite
exatamente, usando caminhos locais previamente conferidos:

```psql
\set HISTFILE /dev/null
\set ECHO none
\prompt 'binding: ' f2_target_binding_sha256
\o <evidence-dir>/f2-prod-cast.txt
\i <repo>/docs/ops/dev-migration-history-remediation/f2-readonly/PROD-READONLY-F2.sql
\o
\q
```

O binding é recebido enquanto o terminal está sem eco. O SQL aceita somente a
forma PROD declarada: `public.schema_migrations` ausente e ledger nativo
presente, com seis entradas e a forma exata revisada. Qualquer diferença produz
somente `F2_ABORT_PROD_LEDGER_SHAPE_DRIFT`, executa `ROLLBACK`, encerra sem recibo de sucesso e devolve apenas o código de aborto. Não adapte o arquivo e não continue parcialmente.

Depois que o `psql` sair, restaure o terminal antes de qualquer outra ação:

```bash
stty "$f2_stty_state"
trap - EXIT HUP INT TERM
unset f2_stty_state
```

## Sessão DEV

A sessão DEV só começa depois de a evidência PROD estar fechada, sanitizada e
hash-conferida isoladamente. Abra outro terminal dedicado e repita a abertura
segura com outro binding. Dentro do novo `psql`, digite:

```psql
\set HISTFILE /dev/null
\set ECHO none
\prompt 'binding: ' f2_target_binding_sha256
\o <evidence-dir>/f2-dev-cast.txt
\i <repo>/docs/ops/dev-migration-history-remediation/f2-readonly/DEV-READONLY-F2.sql
\o
\q
```

O SQL DEV exige ledger público presente com 33 entradas e ledger nativo
presente com seis entradas, ambos com a forma exata revisada. Qualquer diferença
produz somente `F2_ABORT_DEV_LEDGER_SHAPE_DRIFT`, executa `ROLLBACK` e encerra.
A diferença é resultado operacional; não é algo para corrigir ou contornar na
mesma sessão.

Restaure o terminal com o mesmo bloco usado após PROD.

## Contrato dos arquivos SQL

Cada SQL começa com `BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY` e fixa:

- `statement_timeout = 5000ms`;
- `lock_timeout = 1000ms`;
- `idle_in_transaction_session_timeout = 15000ms`;
- `row_security = off` para falhar fechado.

As guardas de forma são silenciosas e precedem a evidência. Em sucesso, o
arquivo termina com `ROLLBACK` e um único recibo terminal escrito dentro do
canal redirecionado por `\qecho`:

- PROD: `F2_PROD_FINAL_RECEIPT=ROLLBACK_COMPLETED_F2_PROD`;
- DEV: `F2_DEV_FINAL_RECEIPT=ROLLBACK_COMPLETED_F2_DEV`.

`\echo` é proibido nos SQLs porque não acompanha `\o`. Ausência, duplicidade ou
posição não terminal do recibo invalida a coleta. Erro, timeout ou saída fora do
contrato exige somente `ROLLBACK;`, encerramento e relato sanitizado, sem nova
tentativa.

## TARGET_DIGEST

O primeiro registro após as guardas é `TARGET_DIGEST`. Ele usa exatamente:

```text
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

Recalcule fora da transcrição, reintroduzindo o binding sem eco. Não preserve
os quatro componentes nem o digest calculado localmente:

```bash
read -r -s -p 'binding opaco: ' f2_local_binding
printf '\n' >&2
read -r -s -p 'database: ' f2_local_database
printf '\n' >&2
read -r -s -p 'porta ou UNIX_SOCKET: ' f2_local_port
printf '\n' >&2
read -r -s -p 'server_version_num: ' f2_local_version
printf '\n' >&2
printf '%s\x1f%s\x1f%s\x1f%s' \
  "$f2_local_binding" "$f2_local_database" "$f2_local_port" "$f2_local_version" \
  | sha256sum | awk '{print $1}'
unset f2_local_binding f2_local_database f2_local_port f2_local_version
```

O valor precisa coincidir com o único `TARGET_DIGEST` da captura. Isso vincula a
saída ao alvo conectado sem revelar seus componentes; não prova, sozinho, que o
alvo recebeu o rótulo humano correto.

## Sanitização, histórico e scrollback

Antes de limpar o scrollback, procure silenciosamente os primeiros 12
caracteres do binding na captura e nos históricos. Informe o prefixo novamente
sem eco; não o escreva na linha de comando:

```bash
read -r -s -p 'primeiros 12 caracteres do binding: ' f2_history_probe
printf '\n' >&2
read -r -p 'arquivo de captura: ' f2_capture_file
for f2_history_file in \
  "$f2_capture_file" "$HOME/.psql_history" "$HOME/.bash_history"; do
  if [ -f "$f2_history_file" ]; then
    printf '%s ' "$f2_history_file"
    grep -F -c -- "$f2_history_probe" "$f2_history_file"
  else
    printf '%s 0\n' "$f2_history_file"
  fi
done
unset f2_history_probe f2_history_file
```

As três contagens devem ser zero. Se alguma for diferente, remova a ocorrência
local, invalide a evidência, descarte o binding e pare. Não repita a coleta sem
nova conferência. Em seguida, confirme modo `0600`, calcule o SHA-256 do arquivo
e use o comando próprio do terminal para apagar também o scrollback, pois
`clear` sozinho pode não removê-lo.

A captura aceita apenas categorias, booleanos, contagens, hashes e referências
opacas. Remova e não compartilhe host, usuário, database, porta, IP, DSN,
binding, certificado, segredo, PID, snapshot, statement bruto, definição bruta,
nome de objeto opaco, nome de role inesperada ou qualquer linha de domínio.

## Entrega separada por ambiente

Para cada ambiente, Raniel entrega separadamente:

- ambiente declarado e horário;
- SHA-256 do SQL executado;
- SHA-256 da captura sanitizada e modo `0600`;
- resultado da conferência do `TARGET_DIGEST`, sem o digest nem seus componentes;
- contagens de histórico `0/0` e binding ausente da captura;
- recibo terminal exato ou único código de aborto sanitizado;
- confirmação de que nenhuma comparação entre ambientes foi feita.

Depois de ambos os pacotes serem aceitos isoladamente, uma etapa documental
separada poderá comparar PROD e DEV. Essa comparação não autoriza escrita,
estratégia B, epoch, cutover, executor ou aplicação.
