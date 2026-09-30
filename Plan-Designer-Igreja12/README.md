# Plan Designer Igreja 12

Este diretório é o centro de planejamento integrado de UX, produto e experiência do PastorAI / Igreja 12.

## Regra de precedência

1. Produto atual comprovado por código, dados e smoke autenticado.
2. Decisões mais recentes aprovadas pelo dono do produto.
3. Este planejamento consolidado.
4. Documentos históricos e textos originais, usados como intenção e rastreabilidade.

Um requisito antigo nunca deve apagar uma evolução já existente. Quando houver conflito, registrar a divergência, validar a operação atual e decidir conscientemente se há algo melhor a incorporar.

## Referência atual, 30/09/2026

O [design system canônico](../DESIGN.md) incorpora a prévia v2 aprovada por Raniel: contraste mais forte, corpo de 15 px, uma ação principal por cuidado e detalhes secundários sob demanda. [Design system e qualidade](07-DESIGN-SYSTEM-E-QUALIDADE.md) e [fluxos](10-FLUXOS-E-WIREFRAMES.md) conectam esse padrão ao planejamento.

O primeiro recorte de Hoje e Conversas está implementado no candidato `66a56cc0b601bf14f8e3036e9cede11f54b32087`, na [PR #447](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/447), ainda em rascunho. Os quatro checks de produto passaram nesse SHA. A [F02 de acesso](../docs/sprints/2026-09-30-ux-acesso-v2.md) aplica a direção a login, recuperação, senha, convite e entrada do console, em candidato local próprio. A aplicação global permanece parcial; navegação, gestão da igreja e operação da plataforma continuam nas suas fatias de implementação e validação.

O [registro v2](../docs/sprints/2026-09-30-ux-contraste-fluxo-v2.md) contém evidência e limites. O estado geral do produto permanece na [Wiki](../docs/WIKI-IGREJA12.md) e na [matriz de cobertura](../docs/ai/PRD-COVERAGE.md). Esta atualização do designer não registra um novo estado de produção.

## Histórico do programa, snapshot de 11/08/2026

Os estados abaixo pertencem ao registro de agosto e não são uma consulta atual às respectivas PRs ou ao ambiente.

- Planejamento inicial: concluído em 2026-08-10 sobre a base `3f085ec7228d770649b0d9041f0e16154fe37629`.
- Fatias 01, 02 e 03: integradas à `main` pelos PRs [#247](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/247), [#248](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/248) e [#250](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/250).
- Fatia 04: aprovada visualmente e publicada no PR [#253](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/253), ainda sem merge ou produção.
- Fatia 05: implementação local do novo Painel de Hoje em `codex/redesign-dashboard-diamante`, empilhada sobre a Fatia 04 e aguardando aceite visual do preview.
- Grafo: não usado nesta fatia; decisões usam leitura direta, testes e inspeção visual.
- Produção: não revalidada por esta fatia visual; nenhuma mudança desta branch foi publicada.
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
- [14-IMPLEMENTACAO-FATIA-04-OPERACAO-PASTORAL-GUIADA.md](14-IMPLEMENTACAO-FATIA-04-OPERACAO-PASTORAL-GUIADA.md): direção Diamante Lapidado aplicada à primeira fatia visual de Minha Célula.
- [15-IMPLEMENTACAO-FATIA-05-FAROL-DE-HOJE.md](15-IMPLEMENTACAO-FATIA-05-FAROL-DE-HOJE.md): Painel de Hoje reorganizado como farol operacional, com prioridades por responsabilidade e caminho G12 vivo.
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

As aprovações de cada fatia ficam no seu registro. Em 30/09, a prévia de Hoje e Conversas v2 e a atualização do designer foram aprovadas. Próximo gate deste recorte: autorização nominal para liberar a PR #447 do rascunho para revisão. Merge e publicação seguem o runbook e a autorização da entrega; aprovação visual não abre gates de banco, provedores, envio ou ativação do agente.
