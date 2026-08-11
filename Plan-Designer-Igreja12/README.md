# Plan Designer Igreja 12

Este diretório é o centro de planejamento integrado de UX, produto e experiência do PastorAI / Igreja 12.

## Regra de precedência

1. Produto atual comprovado por código, dados e smoke autenticado.
2. Decisões mais recentes aprovadas pelo dono do produto.
3. Este planejamento consolidado.
4. Documentos históricos e textos originais, usados como intenção e rastreabilidade.

Um requisito antigo nunca deve apagar uma evolução já existente. Quando houver conflito, registrar a divergência, validar a operação atual e decidir conscientemente se há algo melhor a incorporar.

## Estado do programa

- Planejamento inicial: concluído em 2026-08-10 sobre a base `3f085ec7228d770649b0d9041f0e16154fe37629`.
- Fatia 01: publicada no PR rascunho [#247](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/247), sem merge ou deploy.
- Fatia 02: publicada no PR rascunho [#248](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/248), empilhado sobre a Fatia 01.
- Fatia 03: validada localmente na branch `codex/ux03-cell-access-leadership`; PR rascunho pendente, sem merge ou deploy.
- Grafo: fresco, mas estruturalmente não comprovado; decisões usam leitura direta, testes e revisão do diff.
- Produção: nenhuma das fatias locais foi implantada.
- Data da última atualização: 2026-08-11.

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
- [11-IMPLEMENTACAO-FATIA-01-ESCOPO-E-POLISH.md](11-IMPLEMENTACAO-FATIA-01-ESCOPO-E-POLISH.md): escopos, segurança operacional e quick wins visuais já publicados em PR rascunho.
- [12-IMPLEMENTACAO-FATIA-02-DASHBOARD-RESPONSABILIDADES.md](12-IMPLEMENTACAO-FATIA-02-DASHBOARD-RESPONSABILIDADES.md): composição do Painel de Hoje por papéis acumulados, contexto real e critérios de aceite.
- [13-IMPLEMENTACAO-FATIA-03-ACESSO-LIDERANCA-CELULA.md](13-IMPLEMENTACAO-FATIA-03-ACESSO-LIDERANCA-CELULA.md): separação entre acesso, vínculo e liderança, invariantes transacionais e auditoria pré-implantação.
- [auditorias/03-acesso-lideranca-celula-readonly.sql](auditorias/03-acesso-lideranca-celula-readonly.sql): consultas somente leitura para medir divergências legadas antes de qualquer reparo.
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

O dono do produto aprovou o avanço das Fatias 01, 02 e 03. Essa aprovação não autoriza merge,
migration, alteração de banco, configuração externa, envio real, deploy ou
produção. Cada um desses passos permanece um gate humano separado.
