# V1b: relatório de célula por áudio, 2026-09-27

**Branch:** `feat/whatsapp-cell-report-audio` · **Base:** `a8bf21da8d57493564d59f9923eca3ffbbc90a9c` · **Deploy:** não

## O que foi feito

Fatia de áudio implementada e validada localmente conforme [plano aprovado](../ops/mvp-v1-relatorio-celula-whatsapp-plano.md), separada da V1a congelada. Ingestão e processamento duráveis reutilizam o fluxo de relatório e comprovante da V1a/S3. Quatro tabelas privadas: aviso, eventos de aceite/revogação, tarefa de áudio e reserva de custo. A tarefa conserva a âncora de limpeza quando a mensagem, conversa ou pessoa é removida; referências vivas compostas por tenant são anuladas sem apagar o registro da purga.

## Decisões

Aceite de áudio separado e versionado, subordinado ao LGPD vigente. Áudio pré-aceite não é reaproveitado. Transcrição nunca confirma consentimento ou proposta; o relatório exige novo texto após resumo entregue.

Processamento fora do webhook, por tarefa durável no cron existente. Limites aprovados: 5 MiB, 120 segundos de mídia, 180 segundos de transcrição, três áudios e quatro extrações. Tetos monetários comuns de US$0,10 por relatório e US$2 por igreja/dia UTC. Erro ambíguo conserva reserva e não repete a chamada.

Releases `None` e listas vazias mantêm a entrega inerte. Dados temporários privados duram no máximo 24 horas, com tarefa durável para falhas de remoção física; o relatório confirmado independe do binário. Fechar flags não suspende a purga.

Migration aditiva datada própria, idempotente, com RLS/FORCE RLS, ACL sem DELETE, FKs tenant-bound, `lock_timeout=2s` e rollback comentado. SQLs426/428/430 preservados. Registrada somente nesta branch a observação Sarah: comparação textual de `pg_get_expr` na migration V1a depende da versão PostgreSQL e aborta de forma segura quando a representação diverge.

## Pendente / próximo passo

Sarah revisar o head final da PR com CI verde. Releases permanecem `None`, allowlists vazias e gates de migration/deploy/ativação separados. Nenhuma operação compartilhada ou merge foi executado.

## Verificação

`test-local.sh backend`: 5.858 PASS. Suíte `rls_integration` completa em PostgreSQL17.6 descartável: 632 PASS. Ambas sem falhas ou skips, no mesmo candidato. Incluem SQL exato/replay, ACL/RLS/cross-tenant, captura/consentimento, WAV/OGG sintético, resumo/correção/novo SIM textual, comprovante, orçamento, concorrência e retenção. Os 19 casos críticos de deadline, contenção, flags fechadas, recuperação após 24h e upload/ACK tardios passaram também isoladamente.

[Validação final](../ops/v1b-cell-report-audio-20260927/FINAL-VALIDATION.json) fixa hashes, comandos, ambiente e limites; [revisão independente](../ops/v1b-cell-report-audio-20260927/REVIEW.md) não encontrou P1/P2 remanescente. Registros parciais preservam as falhas encontradas e as correções, inclusive distinção entre consulta segura de catálogo e acesso a dados e o ajuste dos dois relógios da fixture.

Retenção só pode ser antecipada, nunca estendida. Handoff que espera um lock sobrevive ao deadline e às flags fechadas, sem repetir I/O; recuperação local precede purga. MP4/M4A que exija seek pode ser recusado com alternativa textual. Timeout HTTPX é por fase; deadline/fence do job e purga cobrem retorno tardio. Latência real e eliminação física durante indisponibilidade do storage não foram comprovadas. CI, incluindo build da imagem sem publicação, deve ser conferido no head exato da PR.
