# V1b: relatório de célula por áudio

Implementação inicial validada sobre `a8bf21da8d57493564d59f9923eca3ffbbc90a9c`, em `feat/whatsapp-cell-report-audio`. Em 28/09, a PR foi retargetada para `main` e atualizada sobre o merge da PR430, `a2b4d19e7d2ad37f3191624371a839f59bd4680f`; as provas históricas abaixo continuam vinculadas aos respectivos candidatos. [Plano aprovado](../mvp-v1-relatorio-celula-whatsapp-plano.md) e [matriz de aceite](ACCEPTANCE.md).

## Contrato aprovado

Aceite separado, versionado e revogável para transcrição pela OpenAI da igreja, além do termo LGPD vigente. A pessoa pode usar texto. Áudio anterior ao aceite não é reaproveitado. Texto transcrito nunca concede consentimento nem confirma a proposta S3; a confirmação exige novo inbound textual após o resumo entregue.

Limites: 5 MiB e 120 segundos por áudio, até três áudios por relatório, deadline de transcrição de 180 segundos e nenhum retry automático após chamada ambígua. O orçamento é compartilhado com a extração: US$0,10 por relatório e US$2 por igreja/dia UTC, incluindo reservas conservadas após erro.

A ingestão cria a mensagem real e a intenção durável antes de novo I/O. O processamento exige claim/fence próprio, validação de conteúdo e duração, origem tenant-bound e revalidação de autorização. Nenhuma transação permanece aberta durante download, storage ou OpenAI. A transcrição chega ao fluxo V1a com proveniência explícita, preservando resumo/correção, confirmação e finalizador humano compartilhados.

## Retenção e falha

Binário em storage privado e conteúdo de trabalho duram no máximo 24 horas desde a recepção, com descarte antecipado no encerramento/cancelamento. A âncora de limpeza sobrevive à exclusão da mensagem/conversa, e falha física no storage conserva a tarefa para nova tentativa com métrica de atraso. Não se afirma eliminação física durante indisponibilidade do provedor. O relatório confirmado e seu comprovante não dependem do binário ou da transcrição.

Fechar flags impede novo processamento. Recuperação de handoff pendente e purga já devida continuam, nessa ordem, sem repetir o provedor. Uma contenção no banco conserva o claim para nova tentativa de conclusão local. O aviso distingue retenção local e retenção externa; esta implementação não autoriza envio real, ativação ou mudança de política.

## Limites de compatibilidade e da prova

O decoder usa ffmpeg limitado por CPU, memória, bytes e tempo, sem arquivos temporários. WAV, OGG/Opus, MP3 e WebM têm provas sintéticas. MP4/M4A que exija seek pode ser recusado; o fluxo falha fechado e oferece texto/humano. A nova imagem inclui ffmpeg e util-linux; o build sem publicação é verificado pelo CI.

O timeout HTTPX do upload é por fase, sem garantia de interrupção física global de um socket lento. O deadline monotônico, o fence de resultado tardio e a tarefa de purga protegem o estado após essa fronteira. Isso não comprova latência real de provedores. Os testes não usam chaves, áudio ou mensagens reais.

## Entrega e gates

`CELL_REPORT_AUDIO_APPROVED_RELEASE_ID=None` e `CELL_REPORT_AUDIO_ENABLED_IGREJA_IDS` vazia mantêm áudio inerte, cumulativamente com os gates da V1a e S3. Colocar somente uma igreja na variável de ambiente não ativa o fluxo. Migration nova, deploy, ativação e merge exigem gates próprios. A PR agora tem base `main`, que contém a V1a; a atualização exige nova conferência dos hashes, testes e revisão Sarah após resolução documental manual.

A [observação Sarah sobre `pg_get_expr`](../v1a-cell-report-20260927/README.md) foi registrada somente nesta branch: o SQL430 foi preservado. A comparação textual foi exercitada em PG17; outra representação pode abortar de forma segura e requer replay antes de adoção.

## Evidências

O [registro inicial](FINAL-VALIDATION.json), head `481f1ca`, vincula hashes de fonte e SQL a 5.858 testes de backend e 632 testes RLS verdes, sem skips. A revisão do robô depois revelou queda do áudio consentido no roteador textual. O [delta corrigido](QUEUE-TURN-DELTA.json) passou 5.859 testes de backend e 114 PG V1a/V1b; agora todos os fluxos de áudio da prova atravessam também o turno síncrono real antes do dispatcher. O CI integral deve ser conferido novamente no head do delta. Os 19 casos críticos de concorrência, prazo e upload tardio também passaram isoladamente. A [revisão independente inicial](REVIEW.md) e a [revisão do delta](REVIEW-QUEUE-TURN.md) cobrem os respectivos candidatos e não substitui Sarah nem o CI do head publicado. Os registros `*-PARTIAL.json` preservam falhas e correções intermediárias; não descrevem o estado final. Dados exclusivamente sintéticos, PostgreSQL descartável e provedores falsos. Próximo gate humano: Sarah revisar o head final da PR com CI verde.
