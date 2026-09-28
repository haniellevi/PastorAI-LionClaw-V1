# Agenda V2b pelo WhatsApp, 2026-09-27

**Branch:** feat/whatsapp-agenda-outbox · **Base original:** 58bcd1808aa511cdfafc7957d5c36a9c0f8ee348 · **Base atual:** main@87e13da06eee047419b583d87545ee44326e1a28 · **Deploy:** não

## O que foi feito

Lembretes de agenda, outbox única e dispatcher para agenda, EVT-7 interno e V1a. Cutover sem dupla escrita/consumo e sem replay, preservando terminais e ambíguos. [Contrato e evidências](../ops/v2b-agenda-20260927/README.md).

## Decisões

Unicidade por tenant, destinatário, ocorrência e finalidade; janela 08:00-21:00 exclusiva no fechamento; teto agenda dois/dia. Termo LGPD versionado, parada determinística, reativação confirmada. Claim/lease confirmado antes de HTTP; ambiguidade não reenvia. Migration aditiva idempotente sem DELETE; gates vazios e release None, sem alteração dos SQLs congelados.

## Verificação

PR434 integrada em `87e13da`: nomes dos E2E de membro/líder conferidos no job RLS da V2a, 643 testes sem skips. No snapshot V2b anterior `4a3fd616`, 5.918 testes offline e 683 da suíte RLS completa passaram sem skips; esses resultados não atestam o candidato atual após retarget e correções. E2E por finalidade, RLS, quota concorrente, PARAR/SAIR, reativação só de nova ocorrência, lock de origem e expiração foram exercitados no snapshot histórico com transporte simulado. [Manifesto atual](../ops/v2b-agenda-20260927/CANDIDATE-FILES.json) e [resultados históricos](../ops/v2b-agenda-20260927/LOCAL-VALIDATION.json).

## Próximo passo

Concluir CI PG/RLS do head final e nova revisão Sarah após o NO-GO do head `930a6a1`. Nenhum merge, aplicação compartilhada, deploy ou ativação nesta missão.
