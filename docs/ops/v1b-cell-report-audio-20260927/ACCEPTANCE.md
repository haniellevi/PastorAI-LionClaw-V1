# V1b: critérios e plano de prova

Base `a8bf21da8d57493564d59f9923eca3ffbbc90a9c`, plano V1 aprovado. Esta matriz define resultados exigidos, ainda não declara implementação ou testes verdes.

| Cenário | Resultado exigido |
|---|---|
| Flag vazia, release None, gates V1a/S3/agente/envio fechados; tabelas V1b ausentes | Sem download/transcrição/efeito V1b ou query que dependa do schema novo; inbox legado preservado |
| Áudio sem aceite separado vigente ou LGPD inválido | Sem egress OpenAI; aviso curto versionado e alternativa por texto; novo áudio após aceite explícito |
| SIM comum ou voz dizendo SIM | Não concede aceite de áudio nem executa proposta S3 por inferência |
| Revogação de áudio, SAIR global, humano, alteração de líder/acesso/termo durante I/O | Suprime resultado/efeito; purga privada continua |
| MIME divergente, arquivo inválido, duração ilegível, >5MiB ou >120s | Recusa antes de OpenAI, com limites reais de decoder/CPU/memória/tempo |
| Caminho de outra igreja, URL arbitrária, inbound/mídia/hash trocados | Negação por origem e proveniência persistidas, tenant e RLS |
| Áudio válido até120s | Transcrição BYO com deadline180s, zero retries automáticos e nenhuma transação aberta durante HTTP |
| Quarto áudio, replay e áudios concorrentes | Máximo3 por relatório, sem cobrança duplicada; limites .10USD/relatório e2USD/igreja/dia compartilhados com extração |
| Texto transcrito, correção e novo SIM em texto | Mesma coleta V1a/S3; resumo entregue exige confirmação nova; sem Message texto fabricada |
| Crise/humano/opt-out na transcrição | Supressão segura; não transforma texto inferido em autoridade ou permissão |
| Cancelamento/término/24h | Remove conteúdo de trabalho; binário privado até24h da recepção; relatório oficial independe do binário |
| Crash antes/depois upload/delete; storage falha; flag desligada; Message removida | Purga durável/idempotente encontra intenção/órfão e retoma com fence; sem lock durante storage HTTP |
| Relatório confirmado e binário já purgado | Painel/recibo/registro oficial permanecem íntegros e não refazem transcrição |
| SQL novo aplicado duas vezes, cross-tenant, ACL | Sem rewrite ou perda, RLS/FORCE e FKs válidas; SQLs426/428/430 byte-idênticos |

Provas: fixtures sintéticas, mocks de Evolution/Storage/OpenAI, testes PG17 loopback descartável e CI do head exato. Sem uso de áudio/dados reais ou chamadas a provedores. Próximo gate humano da entrega: Sarah da futura PR; merge/ativação/migration compartilhada separados.


## Onde conferir

| Fronteira | Testes versionados |
|---|---|
| Consentimento, ingestão, origem, replay, flags e tenant | `test_cell_report_v1b_worker_pg.py`, `test_cell_report_audio_service_v1b.py` |
| Fluxo completo, orçamento, confirmação textual, retorno tardio, retenção e locks | `test_cell_report_v1b_dispatch_pg.py` |
| SQL exato, replay idempotente, ACL/RLS/FKs e concorrência | `test_cell_report_v1b_migration_pg.py` |
| Validação local do binário e transporte limitado | `test_cell_report_v1b_decoder_boundary.py`, `test_cell_report_v1b_download_boundary.py`, `test_cell_report_v1b_storage_boundary.py`, `test_cell_report_v1b_transcription_boundary.py` |
| Progresso limitado e ciclo cron | `test_cell_report_v1b_progress.py`, `test_cron_worker.py` |

Todos os caminhos da tabela são relativos a `backend/tests/`. Os resultados de cada snapshot estão separados das exigências; falhas intermediárias permanecem nos artefatos históricos para rastreabilidade.
