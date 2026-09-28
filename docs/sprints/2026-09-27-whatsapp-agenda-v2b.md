# Agenda V2b pelo WhatsApp, 2026-09-27

**Branch:** feat/whatsapp-agenda-outbox · **Base:** 58bcd1808aa511cdfafc7957d5c36a9c0f8ee348 · **Deploy:** não

## O que foi feito

Lembretes de agenda, outbox única e dispatcher para agenda, EVT-7 interno e V1a. Cutover sem dupla escrita/consumo e sem replay, preservando terminais e ambíguos. [Contrato e evidências](../ops/v2b-agenda-20260927/README.md).

## Decisões

Unicidade por tenant, destinatário, ocorrência e finalidade; janela 08:00-21:00 exclusiva no fechamento; teto agenda dois/dia. Termo LGPD versionado, parada determinística, reativação confirmada. Claim/lease confirmado antes de HTTP; ambiguidade não reenvia. Migration aditiva idempotente sem DELETE; gates vazios e release None, sem alteração dos SQLs congelados.

## Verificação

PR434 congelada: nomes dos E2E de membro/líder conferidos no job RLS, 643 testes sem skips. V2b local: 5.915 testes offline, 66 PG integrados e nove PG do SQL byte-exato, todos verdes e sem skips. E2E por finalidade, RLS, quota concorrente, PARAR/SAIR, reativação só de nova ocorrência, lock de origem e expiração foram exercitados com transporte simulado. [Manifesto e resultados](../ops/v2b-agenda-20260927/LOCAL-VALIDATION.json).

## Próximo passo

Concluir CI do novo PR e revisão Sarah. Nenhum merge, aplicação compartilhada, deploy ou ativação nesta missão.
