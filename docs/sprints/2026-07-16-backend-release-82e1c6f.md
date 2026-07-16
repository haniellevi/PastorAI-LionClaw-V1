# Release de backend — 82e1c6f — 2026-07-16

**Commit:** `82e1c6f` (`origin/main`)  ·  **Deploy:** sim, produção

> Escopo deste registro: só o fato do release e as confirmações abaixo. Não
> inclui hostname, IP, caminho local/remoto, nome de container, comando de
> implantação, URL interna ou qualquer outro detalhe operacional.

## Escopo funcional

Release de backend em produção no commit `82e1c6f`, que inclui as seguintes
correções (já mergeadas em `origin/main`, ancestrais do commit do release —
confirmado via `git merge-base --is-ancestor`):

- **MSG-IDEMP-1** — dedupe de mensagem inbound (índice único).
- **PIPE-1** — leitura de etapa `NULL` no pipeline pastoral.
- **CONSOL-1** — impede consolidação aberta duplicada por pessoa.
- **SLA-ALIGN-1** — alinhamento do contrato `SLA_CONNECTION` para 24h.

## Verificação

- Health check público: **200**, confirmado pelo responsável após o release.
- Runtime das 4 correções acima verificado em produção pelo responsável.
- Migrations **MSG-IDEMP-1** (`backend/migrations/20260715_204540_msg_idemp1_messages_inbound_provider_id_uidx.sql`)
  e **CONSOL-1** (`backend/migrations/20260715_204541_consolidacao_aberta_unica_por_pessoa.sql`)
  aplicadas e verificadas em produção **antes** deste deploy de backend —
  confirmado pelo responsável.
- Nenhuma exposição de segredo identificada neste release (sem credencial,
  token ou chave em diff, log ou documento).

## Pendente / próximo passo

Nenhum item de código pendente vinculado a este release.
