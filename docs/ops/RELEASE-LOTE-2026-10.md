# Release em lote, outubro de 2026

Este runbook prepara a janela de release das migrations acumuladas e do
backend. Ele não autoriza nem executa acesso a PROD. Use também o
[runbook de produção](PRODUCTION-RUNBOOK.md), o
[runbook de backup](BACKUP-FIREWALL-RUNBOOK.md), o
[manual do release de backend](../../deploy/BACKEND-RELEASE-MANUAL.md) e o
[aplicador de migrations](../../backend/migrations/README.md).

## Estado e gates

O registro de 14/10 informa 78 migrations aplicadas e quatro pendentes:
`20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql`,
`20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql`,
`20260925_183811_preserve_platform_admins_on_tenant_deletion.sql` e
`20260926_120446_platform_jev_settings.sql`. O ROADMAP atualizado em 22/10
marca o estado vivo como não verificado e ainda pede decisão sobre o destino
dessas quatro. Raniel, como dono, precisa decidir nominalmente se cada uma
entra neste lote ou permanece pendente. Não inferir aplicação pelo número 78.

As migrations com `OPERATIONAL_AUTHORIZATION=BLOCKED` continuam fora da
seleção de `migrate.py`; não remover o marcador nem aplicá-las neste release.
O preflight e o deploy precisam usar o SHA exato aprovado da `main` e o ledger
`public.schema_migrations` do banco correto. Estado atual de PROD, pendências,
backup e gates: não verificado neste preparo.

Manter fechados em todos os quatro serviços (`backend`, `queue-worker`,
`cron-worker` e `broadcast-worker`):

- `ALLOW_REAL_SENDS=false`;
- `ASAAS_BILLING_ENABLED=false`;
- `BREVO_SEND_MODE=off`;
- `BROADCAST_ASYNC_ENABLED=false`;
- `AgentConfig.ativo=false` para cada igreja incluída;
- Jev sem `TYPESAFE_API_KEY` e sem igrejas em
  `JEV_SHADOW_TRIAGE_IGREJA_IDS`.

Não alterar gates durante o lote. Confirme configurações e processos sem
imprimir `.env`, credenciais ou valores secretos. O script de deploy existente
confere os quatro gates de serviço; `AgentConfig.ativo` e Jev continuam sendo
verificações independentes. Nenhum resultado local prova PROD.

## Autorizações nominais

Cada ação de PROD exige autorização própria de Raniel, com ambiente, SHA,
escopo e operador registrados. A autorização para uma etapa não se estende à
seguinte.

| Etapa | Quem autoriza | Quem executa e registra |
|---|---|---|
| Gerar e validar backup | Raniel, dono | Operador nominal da janela, com acesso autorizado à VPS e ao projeto Supabase |
| Consultar estado e rodar preflight | Raniel, para uma leitura somente leitura no alvo identificado | Operador nominal, usando role com `BYPASSRLS` e sem imprimir a URL |
| Reconciliar um achado | Raniel e admin/pastor nominal da igreja afetada | Responsável autorizado pelo fluxo administrativo aprovado para aquele registro |
| Aplicar migrations | Raniel, para a lista exata aprovada e SHA | Operador nominal, uma migration por invocação de `migrate.py` |
| Deploy do backend | Raniel, para o SHA completo e janela | Operador nominal pelo workflow manual existente |
| Smoke pós-deploy | Raniel, para o SHA e janela | Operador nominal, somente com chamadas sem efeitos externos |
| Plano de volta | Raniel, para a volta ao SHA anterior | Operador nominal; script de release, sem rollback de schema |

Registrar autorizações e recibos fora deste repositório, sem PII ou segredos.
Este documento e o merge do código não são autorizações operacionais.

## Sequência do release

1. **Backup verificado.** Com autorização nominal de Raniel, o operador executa
   o procedimento instalado `/usr/local/sbin/pastorai-backup.sh` conforme o
   runbook de backup. Confere que o manifesto sanitizado informa
   `status=verified`, que o SHA-256 do pacote confere e que o pacote contém o
   dump `supabase-prod-public.dump` e os demais itens previstos. Registra hora,
   nome do artefato e SHA-256, sem copiar o pacote ou conteúdo de PROD para este
   workspace. Se o pacote ou o checksum falhar, parar.
2. **Preflight inicial.** Na cópia exata do SHA aprovado, com acesso de banco
   fornecido pelo canal autorizado e nunca por argumento ou log, executar:

   ```bash
   python3 backend/scripts/release_preflight.py
   ```

   O comando lê `MIGRATION_DATABASE_URL` do ambiente seguro, inicia transação
   `REPEATABLE READ READ ONLY`, recusa role que não contorne RLS e executa
   somente `SELECT`. Guarda a saída sanitizada. As migrations são listadas em
   `migrate.py::migration_files()`; `APLICADA` e `PENDENTE` preservam a ordem
   lexical do aplicador. `sem_arquivo` conta entradas do ledger sem arquivo
   ativo. Qualquer achado de FK, duplicidade, tabela ausente ou entrada sem
   arquivo interrompe o lote até decisão humana nominal. Pendências só são
   aplicadas depois da decisão sobre as quatro antigas e sobre a lista nova.
   Exit `0` significa apenas ausência desses achados; não significa schema
   liberado, migrations concluídas ou release pronto. Exit `1` exige
   reconciliação; exit `2` indica que o preflight não conseguiu verificar o
   alvo.
   A checagem da FK reproduz o par `(igreja_id, celula_id)` que será validado
   pela migration `20261018_080000`; a checagem de duplicidade usa
   `(igreja_id, pessoa_id)` não nulo, como o índice da #543.
3. **Reconciliação manual, se necessária.** O operador entrega ao dono e ao
   admin/pastor da igreja afetada somente contagens e UUIDs. A reconciliação é
   feita por fluxo administrativo autorizado, sem exclusão em lote, SQL de
   escrita, merge automático ou escolha do agente. Depois, repetir o preflight
   inicial. Só seguir com zero violações de FK e de unicidade, zero tabela
   ausente e destino explícito para cada entrada `sem_arquivo` e migration
   pendente que afete o lote.
4. **Migrations por `migrate.py`.** Com a lista aprovada, conferir primeiro
   `python3 backend/scripts/migrate.py status`. Aplicar uma migration por vez,
   na ordem apresentada e com registro nominal da saída:

   ```bash
   python3 backend/scripts/migrate.py apply <arquivo.sql> --yes
   ```

   Não usar `apply_migrations.py`, SQL manual, wrappers catalog-bound,
   `--no-transaction` sem requisito explícito da migration, nem tentar fazer um
   teste passar abrindo gate. Em erro, parar no primeiro arquivo e preservar o
   estado para decisão de Raniel. Depois da lista aprovada, repetir `status` e
   o preflight somente leitura. Nenhum item aprovado deve permanecer pendente;
   resolver nominalmente qualquer divergência antes do deploy. O segundo
   preflight verifica também se as tabelas criadas pelas migrations já
   registradas desde 15/10 existem em `public`, schema inteiro coberto pelo
   dump de backup.
5. **Deploy do backend.** Depois do banco e dos preflights, Raniel autoriza
   separadamente o SHA completo de 40 caracteres. O operador usa o workflow
   manual **Backend release** da `main`; ele chama
   `deploy/backend-release.sh` na VPS. Manter o mesmo SHA que foi aprovado e
   inspecionado. Não disparar workflow durante esta preparação.
6. **Smoke sem efeitos.** Com os gates acima fechados, conferir `/health` e
   `/ready` públicos e no loopback, `docker compose ps`, CORS e isolamento das
   portas 8000/8080, seguindo a seção 8 do runbook de produção. Usar somente
   GETs e conta de teste previamente aprovada. Não testar envio, cobrança,
   broadcast, recuperação que possa contatar usuário, WhatsApp nem Jev. Se
   saúde ou readiness falhar, seguir o plano de volta sem reabrir gates.
7. **Gates continuam fechados.** Conferir os quatro processos depois do
   restart, `AgentConfig.ativo=false` por igreja e Jev inativo. Registrar
   confirmação sem mostrar valores secretos. O smoke não autoriza ativação.
8. **Plano de volta.** Em falha, Raniel decide nominalmente a recuperação e o
   operador usa o rollback de código do `deploy/backend-release.sh`, que
   verifica a compatibilidade do SHA anterior antes de retomar os serviços.
   Migrations não são desfeitas automaticamente. Preservar banco, backup e
   evidências. Corrigir adiante ou preparar uma compensação de banco revisada
   sob autorização própria. Nunca restaurar dump por cima de PROD como
   rollback improvisado.

## Migrations candidatas desde o registro de 14/10

As 34 migrations ativas abaixo estão no checkout que originou este runbook.
Origem identificada pelo PR que adicionou cada arquivo. Isso não prova que
alguma delas esteja aplicada em PROD. `migrate.py` continua sendo a fonte da
ordem; não ordenar por PR.

| PR de origem | Arquivos |
|---|---|
| #484 | `20261016_180000_prayer_requests.sql` |
| #487 | `20261017_180000_visit_events.sql` |
| #488 | `20261017_180100_consolidacao_atribuicoes_aceite.sql` |
| #492 | `20261017_210500_uv_turmas.sql` |
| #493 | `20261017_220000_uv_presencas.sql` |
| #494 | `20261017_230000_uv_marcos_conclusao.sql` |
| #497 | `20261018_010000_cd_catalogo_turmas.sql` |
| #498 | `20261018_020000_cd_matriculas.sql` |
| #499 | `20261018_030000_cd_presencas.sql` |
| #500 | `20261018_040000_cd_conclusoes_certificados.sql` |
| #503 | `20261018_050000_enviar_avaliacoes.sql` |
| #504 | `20261018_060000_enviar_nomeacao.sql` |
| #505 | `20261018_070000_enviar_abertura.sql`, `20261018_080000_enviar_reforcos.sql` |
| #509 | `20261018_090000_exclusao_privada.sql` |
| #510 | `20261018_100000_enviar_reencontro.sql` |
| #511 | `20261018_110000_cd_equivalencias_versoes.sql` |
| #515 | `20261018_120000_prayer_message_privacy.sql` |
| #513 | `20261018_130000_conhecimento_oficial.sql` |
| #516 | `20261018_140000_conhecimento_trechos.sql` |
| #518 | `20261019_090001_exclusao_privada_pessoa_igreja.sql` |
| #524 | `20261019_110001_conhecimento_exclusao.sql` |
| #526 | `20261019_120001_private_conversation_summaries.sql` |
| #529 | `20261020_100000_prayer_audio_privacy.sql` |
| #531 | `20261020_200000_private_resume.sql` |
| #530 | `20261021_100000_responsabilidades_setor.sql` |
| #535 | `20261022_100000_private_erasure_requests.sql` |
| #544 | `20261023_100000_ai_usage_force_rls.sql`, `20261023_100001_ai_usage_tenant_created_idx.sql` |
| #543 | `20261025_100000_team_pessoa.sql` |
| #541 | `20261027_100000_reset_settles_erasure_requests.sql` |
| #546 | `20261028_100000_private_memory_overview.sql`, `20261028_100001_private_erasure_requests_overview_idx.sql`, `20261028_100002_private_resume_delivered_overview_idx.sql` |

## Ensaio de restauração sintética

O ensaio não lê nem toca backups reais. Usa apenas a imagem PostgreSQL 17 já
presente na máquina, container com rede desabilitada e diretório de dados em
`tmpfs`. Cria um dump custom do schema `public` com UUIDs e linhas fictícias,
restaura em outro banco do mesmo container descartável e exige as contagens
`synthetic_private_records=2` e `synthetic_team_events=1`.

```bash
bash backend/scripts/release_restore_synthetic.sh
```

Saída esperada: `RESTORE_SINTETICO=OK tabelas=2 contagens=2:1`. A ausência da
imagem local interrompe o ensaio; não baixar imagem automaticamente na janela
de produção. O script remove o container e os arquivos temporários ao terminar.

## O que não fazer

- Não conectar a PROD, VPS, banco remoto, deploy ou serviço externo durante a
  preparação deste runbook.
- Não abrir `ALLOW_REAL_SENDS`, `ASAAS_BILLING_ENABLED`, `BREVO_SEND_MODE`,
  `BROADCAST_ASYNC_ENABLED`, `AgentConfig.ativo` ou qualquer gate Jev.
- Não aplicar migrations fora da lista e da ordem aprovada por `migrate.py`.
- Não automatizar reconciliação, apagar duplicidades, ignorar RLS ou mascarar
  achado com migration manual.
- Não copiar PII, dados pastorais, dumps reais, URLs, credenciais, chaves ou
  conteúdo de `.env` para relatório, chat, log, teste ou commit.
- Não usar backup real no ensaio local nem restaurar backup sobre banco de
  produção.
