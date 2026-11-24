# Recibo operacional: tentativa 5.4 abortada e janela fechada (24/11/2026)

Autorização final: SIM do Raniel no cartão `t11s23` (19:54 America/Sao_Paulo)
para recriar o `broadcast-worker` solto, tentar o 5.4 uma última vez e, se
travar de novo, fechar a janela e religar o backup. Tentativas anteriores no
mesmo dia: `t11s11`, `t11s15`, `t11s19`. **Não houve J6. Não houve 5.5.**
PR #703 permanece aberto, sem merge.

Horários em America/Sao_Paulo (UTC-3).

## 1. Resultado

O `run` (J3–J6) recusou de novo, desta vez em contenção parcial do J4, antes
do `ddl-marker` (J5). `resume-legacy` não era permitido pelo próprio
classificador (`containment-partial`). Não houve nova tentativa. A janela foi
fechada: o cron de backup da Igreja 12 voltou a `/etc/cron.d/pastorai-backup`
(`root:root` 0644), o snippet nginx de manutenção residual foi removido, a
API pública e local voltaram a 200, e os quatro gates de envio seguem
fechados. Ledger de produção continua em 78. Sem migrations aplicadas.

## 2. O que o `run` exige e só ele confere (descobertas de 24/11)

Estes pontos não aparecem (ou não bastam) em `prepare` / `check` /
`check-bindings` / `rehearse-backup`. São pré-requisitos do `run` /
`_readiness` / `contain()`, encontrados hoje:

1. **Layout com IDs atuais.** `prepare-layout` grava `reserved_legacy` e
   recusa sobrescrever um layout divergente. IDs velhos (pilha `j12…`)
   produzem `layout-mismatch` antes do diário. Correção: mover o layout,
   rodar `prepare-layout` de novo; não apagar o antigo.

2. **Imagens de dump/clone sem `Labels`.** O `docker inspect` com
   `{{with .Config.Labels}}` falha (`template parsing error`) na imagem
   oficial `postgres@sha256:00bc8661…`, e o `run` mapeia isso para
   `window-prerequisite`. Correção já no #703, commit
   `966d0ec565be22dfba732de5ff2372f995af9524`: usar
   `{{with index .Config "Labels"}}` e tratar null como vazio, com teste de
   imagem sem labels. Instalar essa ferramenta como T; **ainda não está em
   main**.

3. **`broadcast-worker` tem de ser solto.** O contrato exige
   `compose_project` e `compose_service` ausentes
   (`observed-host-broadcast-must-be-standalone`). Recriá-lo com labels do
   Compose `pastorai` (feito no 5.3 para o Compose não derrubar
   redis/evolution) faz o `contain()` recusar **antes** de
   `observed-host-init`. Correção em `t11s23`: `docker run` com a mesma
   imagem `sha256:4a65f30e…`, env/rede/comando do inspect pré-5.3
   (`ccfa5bc6…`, gates fechados), sem labels de projeto/serviço. ID novo:
   `dec7911b27e6080f3d6058c6cbf804861e52f64104163ee044b916f3f671c601`.
   O container rotulado anterior ficou como
   `pastorai_broadcast_worker__pre_t11s23` (não apagado). Não mexer em
   backend/cron/queue/redis/evolution.

4. **IDs, `bindings.scope` e `window_digest` andam juntos.** Ao trocar um
   ID em `host.service_ids` e em `writers.declared_containers`,
   `bindings.scope` tem de ser o novo `HostManifest.digest`, o layout tem
   de ser regravado, e o `window_digest` muda. O diário com `window-init`
   antigo **não pode ser adotado** (`window-inputs-changed`). O runbook
   exige diário vazio no início: mover (não apagar) o diário velho. O
   `plan_digest` só muda se mudarem fontes do adaptador, SHA ou migrations.

5. **`plan_digest` inclui as fontes do adaptador.** Qualquer edição em
   `first_transition_window.py` (o item 2) altera `plan_digest` e, por
   consequência, `window_digest`. Os `--expect-*` do `run` têm de ser os
   valores do `prepare` da T instalada.

6. **Contenção de ingress é efeito real e pode ficar pela metade.** Nesta
   última tentativa o `contain()` passou do `observed-host-init` e gravou
   `observed-host-intent` (`step=ingress`). Escreveu
   `/etc/nginx/igreja12-window/maintenance.conf` (o site já inclui esse
   glob) e recusou em seguida. Estado: `containment-partial`; procedimento
   do classificador: repetir o `run` (sem re-sinalizar); `legacy_resume_allowed=false`.
   Os quatro processos continuaram `running` / `restart=always`; o nft da
   ponte Evolution→backend não chegou a aparecer; a API pública ficou 503
   (`X-Igreja12-Window: maintenance`) enquanto `127.0.0.1:8000` seguia 200.
   Não se deve improvisar `resume-legacy` nesse estado. Ao abortar a janela,
   o snippet residual foi removido e o nginx recarregado para devolver 200
   no público; cópia em
   `/var/lib/pastorai-first-transition/e53-20261124/receipts/`.

7. **A pilha viva do `run` tem de ser o projeto `pastorai`.** A conferência
   de transporte do `run` não aceita mistura j12-app / pastorai-suporte
   (visto no 5.2/5.3).

## 3. O que falta corrigir antes de outra janela

- Merger o #703 (ou instalar em T um commit que já tenha o
  `IMAGE_TEMPLATE` tolerante) antes de um novo `run`.
- Manter o `broadcast-worker` **solto** (`docker run`, sem labels
  `com.docker.compose.project` / `service`). O compose oficial do lionclaw
  não declara esse serviço; um `-f` extra com labels volta a quebrar o
  item 3.
- Se um container reservado for recriado: atualizar IDs, recomputar
  `bindings.scope`, mover e refazer o layout, conferir `window_digest` e
  só então decidir o diário (vazio se o digest mudou).
- Investigar por que o bloco de ingress recusou depois de gravar o
  snippet (a ponte nft não foi criada). Ensaiar esse caminho fora da
  janela, se houver modo seguro, para não deixar 503 pública pela metade.
- Definir no runbook o aborto humano de `containment-partial` quando
  `resume-legacy` é negado e não se deve repetir o `run` (como remover o
  snippet, religar o cron, preservar o diário).
- Qualquer nova tentativa precisa de SIM novo, kit conferido e diário
  compatível (o diário atual em
  `/var/lib/pastorai-first-transition/state/journal` é o da recusa
  `containment-partial` e não serve para um `run` novo).

## 4. Linha do tempo desta tentativa (`t11s23`)

| Quando | O quê |
|---|---|
| 19:54 | SIM `t11s23`. Restavam ~65 min (fim 21:00:30). |
| 19:55–19:58 | `pastorai_broadcast_worker` recriado solto, imagem `4a65f30e…`, gates fechados, API 200. ID `dec7911b…`. |
| 19:59:19 | Backup do kit oficial em `window.bak-20261124T195919-0300-pre-t11s23-ids`. IDs e `scope` (`ef4453fb…`) atualizados. |
| 19:59:29–19:59:33 | Layout anterior movido; `prepare-layout` ok (145 ficheiros). `plan_digest` inalterado `d86c83f4…`. |
| 19:59:45–20:00:04 | `prepare` / `check` / `check-bindings` ok. Novo `window_digest`: `a12b3cfe460a9e3d0283fb938de871b0e212e9549a1833f9ab3f3ae5f818f03f`. Ledger 78, 52 pendentes, bindings abertos, `unknown_writers=0`. |
| 20:00:23–20:02:16 | V9 no clone: 105,988 s, aplicadas 52, ledger 130, `final_schema_digest` `ab271f3a…`, `max_migration_seconds=0,372`. |
| 20:02:33 | Diário `not-started` anterior (digest `b80b1f43…`) **não adotável**; movido para `e53-20261124/receipts/journal.not-started-pre-t11s23-ids-…`. |
| 20:02:48–20:03:19 | `run` rc=2, `window-transition-refused`. J3 ok (20:03:00–20:03:07). `observed-host-init` + intent `ingress` às 20:03:13. Sem `ddl-marker`. Estado `containment-partial`. |
| 20:06:12–20:06:15 | Snippet nginx residual removido, reload, API pública e local 200, workers ok (incluindo broadcast). Cron restaurado. Serviço `cron` permanece active. |

T instalada: `966d0ec565be22dfba732de5ff2372f995af9524`.
`plan_digest`: `d86c83f4edf0cd97d43c5ab07bfde695eafa91e87c9e4c74e3501446465a5702`.

## 5. Estado ao fechar

- API `https://api.igreja12.com.br/ready` e `http://127.0.0.1:8000/ready`: 200; workers ok.
- Imagem de tráfego: ainda o legado `sha256:4a65f30e…`. Sem troca de tráfego para A.
- Gates fechados nos quatro processos de aplicação.
- `/etc/cron.d/pastorai-backup` presente, `root:root` 0644 (cópia do arquivo
  pausado no J2). `/root/pastorai-backup.cron.pausado` mantido como registro;
  outra cópia em `/root/pastorai-backup.cron.pausado.restored-t11s23-…`.
- Diário da recusa preservado em
  `/var/lib/pastorai-first-transition/state/journal` (6 eventos, sem
  `ddl-marker`). Não reutilizar.
- Produção: ledger 78, catálogo `b561d41f…`, identidade `9b48b837…`.
