# Runbook humano, F2 PROD shape diagnostic v2

## Gate e finalidade

Raniel executa este procedimento somente depois de OpenCode e CLAUDE marcarem
`APTO` os mesmos bytes do SQL, deste runbook, do runner e do manifesto. Esta é
uma única sessão PROD, somente leitura e fora do pico. Ela descreve a forma
atual dos dois ledgers canônicos; não compara com DEV, não identifica causa de
drift e não autoriza remediação, migration, aplicação, epoch ou cutover.

O diagnóstico registra drift como resultado sanitizado. Somente falha de
fonte, privacidade, binding, sessão, timeout ou teto pode encerrar a coleta.
Um erro ou aborto encerra a operação: Raniel executa apenas `ROLLBACK;`, fecha
a sessão e envia o erro sanitizado. Não corrige, explora, troca alvo, amplia
timeout ou repete sem nova conferência conjunta dos dois conselheiros.

## Antes da conexão

1. Confirme o SHA-256 do SQL e reproduza o manifesto deste candidato no SHA
   declarado. Não use um arquivo copiado, editado ou com hash diferente.
2. Escolha janela fora do pico. Uma conexão e consultas de catálogo podem gerar
   alerta legítimo ou usar uma vaga. Confirme capacidade pelo procedimento
   humano, avise o monitor responsável e não suprima alerta, pool, firewall ou
   limite de conexões.
3. Crie um binding novo de 32 bytes, codificado em 64 hexadecimais minúsculos.
   Ele é exclusivo desta execução, não reutiliza F1 ou outra coleta e não entra
   em argv, variável de ambiente, arquivo, histórico, clipboard persistente ou
   transcrição.
4. Crie fora do repositório um diretório de evidência local com modo `0700`.
   O arquivo de captura deve terminar em `0600` e conter somente a saída
   redirecionada desta sessão.

## Abertura sem eco

Use terminal dedicado, sem histórico, e preserve o estado de TTY antes de abrir
o cliente. Host, usuário e database são inseridos somente no terminal local e
nunca entram na captura ou no repositório.

```bash
set +o history
f2_tty_state="$(stty -g)"
trap 'stty "$f2_tty_state"; unset f2_tty_state' EXIT HUP INT TERM
stty -echo
PSQL_HISTORY=/dev/null psql -n -X -q -A -t -F '|' -P pager=off -P null='[null]' \
  -h <host-local> -U <user-local> -d <database-local> -W
```

Dentro do `psql`, não execute `\conninfo`, consulta de teste ou qualquer SQL.
Digite as linhas na ordem abaixo. `ECHO none` vem antes do prompt, da captura e
do `\i`. O binding é recebido por `\prompt`, com o terminal ainda sem eco, e
não usa argv nem ambiente.

```psql
\set HISTFILE /dev/null
\set ECHO none
\prompt 'binding: ' f2_prod_diag_binding
\o <evidence-directory>/f2-prod-shape-diag-v2-cast.txt
\i <repo-root>/docs/ops/dev-migration-history-remediation/f2-prod-shape-diagnostic-v2/PROD-READONLY-F2-DIAG-v2.sql
```

O SQL faz `ROLLBACK` e encerra o cliente. Não envie mais linhas após o `\i`.
O único recibo de sucesso permitido, como última linha da captura, é
`ROLLBACK_COMPLETED_F2_PROD_DIAG`. Um código `F2_ABORT_*` não é sucesso e não
tem recibo terminal de sucesso.

## Fechamento e entrega sanitizada

Após a saída autocontida do cliente, restaure o terminal. Não limpe o
scrollback antes da conferência concreta abaixo:

```bash
stty "$f2_tty_state"
trap - EXIT HUP INT TERM
unset f2_tty_state
```

Fora da transcrição, use o bloco abaixo no mesmo terminal local. Ele recebe
binding, database, porta ou `UNIX_SOCKET` e versão por `read -s`; nada entra em
argv, ambiente ou histórico. Substitua somente o caminho local da captura. O
bloco recompõe exatamente o `TARGET_DIGEST` com o separador byte `0x1f`, testa
um prefixo sem imprimi-lo nos arquivos de captura e histórico, limpa todas as
variáveis e só então informa um estado sanitizado.

```bash
set +o history
f2_capture_path='<evidence-directory>/f2-prod-shape-diag-v2-cast.txt'
f2_shell_history_path="${HISTFILE:-}"
f2_psql_history_path=/dev/null
IFS= read -r -s -p 'binding: ' f2_digest_binding; printf '\n'
IFS= read -r -s -p 'database: ' f2_digest_database; printf '\n'
IFS= read -r -s -p 'porta ou UNIX_SOCKET: ' f2_digest_port; printf '\n'
IFS= read -r -s -p 'server_version_num: ' f2_digest_version; printf '\n'
f2_binding_format_ok=false
[[ "$f2_digest_binding" =~ ^[0-9a-f]{64}$ ]] && f2_binding_format_ok=true
f2_local_target_digest="$(printf '%s\x1f%s\x1f%s\x1f%s' \
  "$f2_digest_binding" "$f2_digest_database" "$f2_digest_port" "$f2_digest_version" \
  | sha256sum | awk '{print $1}')"
f2_captured_target_digest="$(awk -F'|' '
  $1 == "TARGET_DIGEST" { count += 1; value = $2 }
  END { if (count == 1 && value ~ /^[0-9a-f]{64}$/) print value }
' "$f2_capture_path")"
f2_binding_prefix="${f2_digest_binding:0:12}"
f2_prefix_present=false
for f2_scan_path in "$f2_capture_path" "$f2_shell_history_path" "$f2_psql_history_path"; do
  if [[ -n "$f2_scan_path" && -f "$f2_scan_path" ]] \
    && LC_ALL=C grep -Fq -f <(printf '%s\n' "$f2_binding_prefix") "$f2_scan_path"; then
    f2_prefix_present=true
  fi
done
f2_digest_match=false
[[ "$f2_local_target_digest" == "$f2_captured_target_digest" ]] && f2_digest_match=true
unset f2_digest_binding f2_digest_database f2_digest_port f2_digest_version
unset f2_binding_prefix f2_local_target_digest f2_captured_target_digest
unset f2_capture_path f2_shell_history_path f2_psql_history_path f2_scan_path
if [[ "$f2_binding_format_ok" != true || "$f2_prefix_present" == true ]]; then
  unset f2_binding_format_ok f2_prefix_present f2_digest_match
  printf '%s\n' 'F2_ABORT_BINDING_PREFIX_OR_FORMAT'
  exit 1
fi
if [[ "$f2_digest_match" != true ]]; then
  unset f2_binding_format_ok f2_prefix_present f2_digest_match
  printf '%s\n' 'F2_ABORT_TARGET_DIGEST_MISMATCH'
  exit 1
fi
unset f2_binding_format_ok f2_prefix_present f2_digest_match
printf '%s\n' 'F2_TARGET_DIGEST_VERIFIED_PREFIX_ABSENT'
```

Somente após esse resultado sanitizado, limpe o scrollback conforme o
procedimento humano local. A limpeza reduz exposição, mas não é prova retida do
buffer visual. Se o prefixo ou o digest falharem, preserve o arquivo somente
para encaminhar o erro sanitizado e não execute outra tentativa sem nova
conferência conjunta.

Entregue somente a transcrição sanitizada, seu SHA-256, horário, confirmação do
recibo ou aborto e a declaração humana de que não houve leitura de domínio.
Não entregue comparação com DEV, conclusão causal, conteúdo de statements,
linhas de ledger, credencial, binding ou dados de conexão.

## Limites de interpretação

O resultado positivo prova apenas que estes bytes foram executados uma vez na
sessão humana declarada e que a forma observada coube nos tetos. Ele não prova
identidade PROD por si só, aplicação de migrations, origem do drift, segurança
de outro ambiente ou autorização para qualquer escrita. A identificação do
ambiente permanece atestação humana; F2 ou PROD futuro exige âncora confiável
externa antes de ampliar o uso da evidência.
