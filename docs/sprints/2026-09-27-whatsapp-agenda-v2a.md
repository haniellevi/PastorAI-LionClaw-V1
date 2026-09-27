# Consulta da agenda pelo WhatsApp V2a, 2026-09-27

**Branch:** `feat/whatsapp-agenda-readonly` · **Base:** `3e8306e9dfd5e3dec3097f3e8a701829b4d7aa36` · **Deploy:** não.

## O que foi feito

Fatia V2a autorizada após parecer conjunto dos conselheiros sobre o [plano V2](../ops/mvp-v2-agenda-whatsapp-plano.md). A consulta usa identidade/papel do servidor, dados `Event` do próprio tenant e resposta determinística, sem ampliar o catálogo de ações mutantes S3.

## Decisões

- Separar consultas V2a de lembretes/outbox/cutover V2b, que terá PR própria. Sem migration ou frontend nesta fatia.
- `publico_alvo` não é uma permissão pública. Sem vínculo ativo, manter somente o perfil público da S2b; rascunho exige pastor/admin e prova Clerk.
- Não exibir título legado só porque origem/status parecem humanos. Exigir confirmação persistida por usuário autorizado e validação conservadora; ausência de prova ou conteúdo duvidoso usa tipo/data/hora.
- Eventos e papéis podem mudar depois da escolha da ferramenta. Reconsultar antes do transporte e suprimir respostas pendentes incompatíveis, inclusive em retry.
- Manter flags vazias/release `None` e PR433 intacta. PROD só por release em lote; novo modelo de desenvolvimento local não autoriza reset ou provider real nesta missão.

## Pendente / próximo passo

Implementação e provas locais concluídas. O [README](../ops/v2a-agenda-20260927/README.md) registra limites da projeção e da operação. Próximo gate humano: revisão Sarah do candidato final. Teste painel/simulador depende da PR432 e da disponibilidade do simulador, ainda pendente no guia consultado.

## Verificação

O [plano QA](../ops/v2a-agenda-20260927/QA-PLAN.md) cobre RLS/tenant, papéis/Clerk, títulos, recorrência, limites e retry pós-revogação. Passaram 5.881 testes offline e 117 PG17 (V2a, S3, V1a e V1b), sem skips, no patch backend `2397128ed04e53732a6d034a8c1836435e444965b7437b0eeb7f07b3fbd4c0bb`. [Recebimento técnico](../ops/v2a-agenda-20260927/TEST-RESULTS.json) liga resultados aos blobs exatos, sem inferir deploy ou ambiente real. As quatro migrations congeladas permanecem intactas.
