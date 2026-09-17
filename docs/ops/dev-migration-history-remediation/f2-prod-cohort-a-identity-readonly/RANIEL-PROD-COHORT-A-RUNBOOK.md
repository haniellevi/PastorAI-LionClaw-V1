# Runbook humano proposto, F2 PROD coorte A

## Estado do gate

Este runbook não pode ser executado enquanto
`OWNER_AUTHORIZE_PROD_UNMATCHED_IDENTITY_EVIDENCE_READ_ONLY` estiver fechado.
O briefing, o APTO dos conselheiros, commit, CI, PR ou merge não substituem a
frase nominal de Raniel para esse gate.

A execução futura pertence ao Raniel. Agentes não abrem sessão PROD. Um erro ou
aborto encerra a tentativa; execute somente `ROLLBACK;`, feche a sessão e
entregue o código sanitizado. Não repita, amplie timeout, explore o alvo ou
troque a consulta sem nova conferência.

## Preflight fora do pico

1. Use os bytes exatos aprovados e reproduza o manifesto.
2. Confirme, sem abrir conteúdo, arquivo regular, não-symlink, modo e SHA-256
   das três fontes em `SOURCE-PINS.md`. A captura e o JSON exigem `0600`.
3. Confirme que a saída será criada fora do repositório em diretório `0700`,
   arquivo novo `0600`. Rejeite caminho existente com outro modo ou symlink.
4. Avise o monitor responsável. A sessão única usa uma conexão e pode gerar
   alerta ou consumir uma vaga; não suprima monitor, pool, firewall ou limite.
5. Gere binding novo de 32 bytes em 64 hexadecimais minúsculos. Ele não reutiliza
   qualquer coleta anterior e não entra em argv, ambiente, histórico ou arquivo.

## Abertura sem histórico e sem eco

No terminal dedicado:

```bash
set +o history
f2_tty_state="$(stty -g)"
trap 'stty "$f2_tty_state"; unset f2_tty_state' EXIT HUP INT TERM
stty -echo
PSQL_HISTORY=/dev/null psql -n -X -q -A -t -F '|' -P pager=off -P null='[null]' \
  -h <host-local> -U <user-local> -d <database-local> -W
```

Dentro do `psql`, nenhuma linha vem antes destas:

```psql
\set HISTFILE /dev/null
\set ECHO none
\prompt 'binding: ' f2_cohort_a_binding
\o <evidence-directory>/f2-prod-cohort-a-identity-cast.txt
\i <repo-root>/docs/ops/dev-migration-history-remediation/f2-prod-cohort-a-identity-readonly/PROD-READONLY-F2-COHORT-A.sql
```

O SQL encerra o cliente após `ROLLBACK`. O último registro precisa ser
`ROLLBACK_COMPLETED_F2_PROD_COHORT_A_IDENTITY`. Qualquer `F2_ABORT_*`
reprova a tentativa e não autoriza repetição.

## Validação fora da transcrição

Restaure o terminal e confirme o arquivo antes de qualquer limpeza:

```bash
stty "$f2_tty_state"
trap - EXIT HUP INT TERM
unset f2_tty_state

f2_cast='<evidence-directory>/f2-prod-cohort-a-identity-cast.txt'
[[ -f "$f2_cast" && ! -L "$f2_cast" ]] || exit 1
[[ "$(stat -c '%a' "$f2_cast")" == 600 ]] || exit 1
sha256sum "$f2_cast"
```

Recalcule `TARGET_DIGEST` fora da transcrição usando a fórmula já aprovada,
com separador byte `0x1f`, e confirme prefixo do binding igual a zero na
captura, em `~/.psql_history` e no histórico do shell. Não imprima binding,
database, porta, versão ou digest em documentação. Limpe o scrollback somente
depois dessas conferências.

## Entrega permitida

Entregue separadamente:

- arquivo sanitizado `0600`, fora do repositório;
- SHA-256, tamanho e horário;
- confirmação de um TARGET_DIGEST, zero abortos e recibo terminal único;
- confirmação humana do alvo PROD e de que não houve linha de domínio;
- resultado do validador futuro da membresia, sem copiar hashes por entrada.

Não entregue binding, conexão, versão ou nome crus, statements, rollback,
idempotency_key, created_by, TARGET_DIGEST ou compromissos individuais no
repositório, PR, issue ou canvas.

## Limite de interpretação

O recibo prova somente que os bytes aprovados terminaram em rollback no alvo
atestado. Mesmo 22 compromissos únicos não provam correspondência com catálogo
nem aplicação. A análise de bijeção é outra etapa offline e permanece fechada.

O único próximo gate deste briefing é
`OWNER_AUTHORIZE_PROD_UNMATCHED_IDENTITY_EVIDENCE_READ_ONLY`.
