# Consolidação pelo WhatsApp: V3, 2026-09-28

**Branch:** `feat/whatsapp-consolidation-v3` · **Commits:** código `42cab69eaebceb425ac461493921c665d04769b4` · **Deploy:** não.

## O que foi feito

A V3 reutiliza decisão, fila e etapas humanas com consulta de pendências,
atribuição e fonovisita pelo WhatsApp. Escritas exigem resumo entregue, SIM,
TTL de dez minutos, uso único e comprovante após commit. Os três alertas usam
a outbox comum, sem transporte alternativo ou replay de histórico.

## Decisões

Somente o responsável atual recebe primeiro nome, tipo e prazo em 1:1,
revalidados antes do HTTP. Outras tarefas aparecem por código/contagem;
sobrenome, telefone e contexto ficam no painel com Clerk. Respostas têm
limite de dez itens. Comandos V3 usam gramática restrita e projeção opaca;
residual, homônimo e identidade revogada resultam em handoff sem modelo.

Uma fonovisita por consolidação nova; ativação prospectiva durável, sem
backfill. A/B/A não reabre alertas terminais. Opt-in requer confirmação
própria; PARAR LEMBRETES e SAIR prevalecem. Janela 08h–21h, teto dois por
destinatário/dia, expiração fixa de 24h e locks liberados antes do HTTP.

A migration aditiva/idempotente mantém RLS e grants mínimos sem DELETE;
`lock_timeout=2s`, compensação comentada, hash `267f6197…`. Os 86 SQLs da base
PR435 `342f0ce` seguem intactos. A classificação do domínio permanece PARCIAL.

## Pendente / próximo passo

CI do head publicado e revisão Sarah. Flags/release permanecem inertes.
Sem autorização de merge, banco compartilhado, deploy ou envio real.
A base não contém o ambiente local do PR432; não houve teste de painel/simulador.

## Verificação

5.982 testes offline e 750 RLS passaram, zero falhas/skips, em Python3.13.14
e PostgreSQL17 sintético. A revisão independente repetiu 12 E2E de turno,
21 de entrega e 15 de migration, além dos focais de modelo. O E2E começa no
inbound persistido e usa gates sintéticos/providers falsos.
[Contrato, hashes, resultados e revisão](../ops/v3-consolidacao-20260928/README.md).
