# Plan Designer Igreja 12

Este diretório é o centro de planejamento integrado de UX, produto e experiência do PastorAI / Igreja 12.

## Regra de precedência

1. Produto atual comprovado por código, dados e smoke autenticado.
2. Decisões mais recentes aprovadas pelo dono do produto.
3. Este planejamento consolidado.
4. Documentos históricos e textos originais, usados como intenção e rastreabilidade.

Um requisito antigo nunca deve apagar uma evolução já existente. Quando houver conflito, registrar a divergência, validar a operação atual e decidir conscientemente se há algo melhor a incorporar.

## Estado desta entrega

- Natureza: planejamento e acervo, sem alteração no código do produto.
- Base auditada: `3f085ec7228d770649b0d9041f0e16154fe37629`.
- Branch: checkout em `detached HEAD`, alinhado a `origin/main` no preflight.
- Grafo: não comprovado, leitura direta de documentação e código.
- Produção autenticada: não medida nesta entrega.
- Data: 2026-08-10.

## Índice

- [PLANEJAMENTO-MESTRE-IGREJA12.md](PLANEJAMENTO-MESTRE-IGREJA12.md): visão integrada, estado atual, arquitetura alvo, prioridades e gates.
- [01-ESTADO-ATUAL-E-GAPS.md](01-ESTADO-ATUAL-E-GAPS.md): inventário por capacidade, com implementado, parcial, ausente e não comprovado.
- [02-ARQUITETURA-EXPERIENCIA-E-PAPEIS.md](02-ARQUITETURA-EXPERIENCIA-E-PAPEIS.md): superfícies, navegação, dashboards e autorização por responsabilidade.
- [03-AGENTE-IA-WHATSAPP.md](03-AGENTE-IA-WHATSAPP.md): propósito, fluxo de dados, consentimento, memória e comunicação.
- [04-PESSOAS-E-JORNADA-G12.md](04-PESSOAS-E-JORNADA-G12.md): identidade da pessoa, CSIM, Ganhar, Consolidar, Discipular e Enviar.
- [05-AGENDA-E-COMUNICACAO.md](05-AGENDA-E-COMUNICACAO.md): Agenda, Google Calendar, planejamento e entregas.
- [06-CELULAS-E-CENTRAL.md](06-CELULAS-E-CENTRAL.md): Minha Célula, Central, reuniões, saúde, solicitações e multiplicação.
- [07-DESIGN-SYSTEM-E-QUALIDADE.md](07-DESIGN-SYSTEM-E-QUALIDADE.md): fundamentos visuais, acessibilidade, responsividade e critérios de qualidade.
- [08-ROADMAP-PRIORIZADO.md](08-ROADMAP-PRIORIZADO.md): implementação futura em fatias verticais, sem execução nesta fase.
- [09-DECISOES-PENDENTES.md](09-DECISOES-PENDENTES.md): escolhas de produto que não devem ser inferidas pelo time.
- [10-FLUXOS-E-WIREFRAMES.md](10-FLUXOS-E-WIREFRAMES.md): fluxos críticos e wireframes determinísticos desktop/mobile.
- [FONTES-E-RASTREABILIDADE.md](FONTES-E-RASTREABILIDADE.md): fontes, evidências, limites e método de atualização.

## Vocabulário de status

- `IMPLEMENTADO`: existe no SHA auditado com UI e contrato identificáveis.
- `PARCIAL`: existe uma base útil, mas falta parte relevante do fluxo, regra, autorização ou feedback.
- `AUSENTE`: não foi encontrada implementação correspondente após busca direta.
- `NÃO COMPROVADO`: pode existir ou estar ativo em produção, mas não há evidência suficiente nesta auditoria.
- `DECISÃO`: há mais de uma direção legítima e o dono do produto precisa escolher.

## Uso dos recursos

- `fontes-originais/`: cópias imutáveis dos quatro textos enviados pelo usuário.
- `assets/brand/`: cópias dos ativos canônicos encontrados no frontend atual.
- `assets/concepts/`: imagem conceitual, não representa implementação aprovada.
- `assets/research/`: capturas públicas e sanitizadas.
- `assets/references/`: referências históricas, não são fonte de verdade do produto atual.

## Gate permanente

Nada neste diretório autoriza implementação, migration, alteração de banco, configuração externa, envio real, commit, push, PR, merge ou deploy. A próxima etapa exige aprovação explícita da direção e das fatias escolhidas.
