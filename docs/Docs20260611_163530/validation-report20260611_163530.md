# Relatorio de Validacao — Stories e Requisitos PastorAI

> Fonte de verdade do PRD Validator. Status por problema: [PENDENTE] / [APLICADO] / [REJEITADO].
> Documento validado: stories-requisitos20260611_163530.md
> Base de comparacao: discovery20260611_163530.md

## Problemas identificados

- **P1** [APLICADO] [Lacunas] "Assistente no painel". Decisao do usuario: assistente geral do sistema (MVP) que conhece o usuario logado e suas permissoes, responde no chat, tira duvidas, orienta preenchimento e explica regras do sistema. Criada US-41 + RF-47 (dominio Assistente do Sistema), respeitando isolamento por tenant.

- **P2** [APLICADO] [Lacunas] Nascimento da igreja. Decisao do usuario: existe um nivel SUPER-ADMIN (operador do SaaS) que controla todo o negocio, ve as igrejas cadastradas (cada uma tenant isolado, com IA e dados proprios), verifica o pagamento e provisiona a nova igreja preenchendo os dados iniciais. Criada persona Admin do Sistema (Super-Admin) + dominio "Administracao da Plataforma (Super-Admin)" com US-42/US-43 e RF-48/RF-49.

- **P3** [APLICADO] [Lacunas] "Decisoes por Jesus" sem desdobramento. Resolvido junto com P12: criado dominio Consolidacao (US-37 a US-40, RF-43 a RF-46) e link em US-24 (decisao por Jesus pode iniciar a consolidacao via US-37). Consolidacao definida como MVP.

- **P4** [APLICADO] [Lacunas] Captura do consentimento. Decisao do usuario: consentimento concedido automaticamente quando a pessoa inicia a conversa com a igreja (sem spam; igreja nunca inicia espontaneamente); opt-out a qualquer momento (para comunicados em massa, mantendo conversas normais); para a base existente, contato inicial perguntando se aceita comunicados. US-31 e RF-36 ajustados.

- **P5** [APLICADO] [Lacunas] Gestao de membros / transicao visitante->membro. Decisao do usuario: visitante sem celula = "em acompanhamento" (responsabilidade da consolidacao); ao vincular a uma celula vira "membro". US-18, US-20 e RF-23 ajustados.

- **P6** [APLICADO] [Ambiguidades] "Registrar acompanhamento" vs "vincular a celula". Resolvido junto com P5: acompanhamento = enquanto sem celula; a unica acao que tira o visitante da lista e o vinculo a uma celula (US-20), que o promove a membro. US-18 reescrita.

- **P7** [APLICADO] [Ambiguidades] Painel = fila de trabalho. Decisao do usuario: e um painel unico de tarefas/pendencias a fazer (nao historico), visivel apenas a usuarios com privilegio; US-16 e US-17 sao visoes do mesmo painel. Acoes sao no sistema (nao via WhatsApp); notificacoes saem pelo WhatsApp da igreja alertando os responsaveis; baixa do item via confirmacao do orquestrador no WhatsApp ou update manual no sistema. US-15 e US-16 ajustados.

- **P8** [APLICADO] [Conflitos] Visibilidade das conversas do WhatsApp. Decisao do usuario: Lider e demais papeis NAO veem as conversas do WhatsApp da igreja; apenas Pastor/Admin, secretaria e usuarios liberados ao atendimento humano. US-11 e US-12 ajustados para "Pastor/Admin ou usuario autorizado ao atendimento humano (ex.: secretaria)" + criterio explicito em US-11.

- **P11** [PENDENTE] [Lacunas/Organizacao] RBAC hierarquico completo (novo escopo trazido pelo usuario). Modelo informado: hierarquia "quem esta acima ve o que esta abaixo; quem esta abaixo nao ve o que esta acima". Papeis e visoes: Visitante (nao acessa o sistema, so recebe WhatsApp); Membro (dashboard da sua celula com visao de membro: avisos da igreja, proxima celula, ultimas celulas, membros da celula, solicitar conversa com pastor/lider, bate-papo da celula, detalhes de Universidade da Vida / Capacitacao Destino onde participa); Lider (sua celula + celulas abaixo, ministerios que participa, relatorios com discipulos seus, sua celula G12, aba de gestao de celula com materiais da central, comunicados, planner de celula, agente de IA de gestao da celula, metas, planejamento de multiplicacao); Lider de ministerio (gestao do seu ministerio); Pastor (tudo sob sua responsabilidade). DECISAO DO USUARIO: opcao (B) — marcar como roadmap pos-MVP. US-04 ajustada para registrar o principio hierarquico e limitar o MVP a Pastor/Admin, Lider e atendente autorizado; criada secao "Roadmap pos-MVP" com Portal do Membro, Trilhas (Universidade da Vida/Capacitacao Destino), Aba de Gestao de Celula, Agente de IA de celula, Ministerios e RBAC hierarquico completo. [APLICADO]

- **P12** [PENDENTE] [Lacunas] Consolidacao (P3 desdobrado pelo usuario). Processo: pessoa decide por Jesus; (a) se ja esta em celula/visitando uma celula, o lider lanca e assume a consolidacao e o sistema alerta o ministerio de consolidacao; (b) se e visitante sem vinculo, a equipe de consolidacao a lanca e tem ate 24h para conecta-la a uma celula. Dashboard de Consolidacao com acesso restrito (equipe/privilegiados) mostrando dados da pessoa, celula que participa e etapas da consolidacao. [APLICADO] Dominio Consolidacao criado (US-37 a US-40, RF-43 a RF-46) + persona Equipe de Consolidacao. Refinamentos do usuario: consolidacao = Universidade da Vida; concluir NAO matricula automaticamente na CD (Capacitacao Destino) — a pessoa entra na lista de aptos a proxima turma da CD, refletida no cadastro; estatisticas de consolidacoes concluidas ficam no roadmap; fonovisita tambem gera pendencia (US-40).

- **P9** [APLICADO] [Criterios fracos] US-10 (onboarding de contato/visitante). Esclarecido pelo usuario: visitantes nao usam o sistema nem se autocadastram. O orquestrador do WhatsApp conduz a conversa coletando nome, endereco, interesse em acompanhamento, necessidade de oracao e se ja veio a igreja; as informacoes sao notificadas a consolidacao; a pessoa e cadastrada como "contato (precisa de acompanhamento)" se ainda nao foi a igreja, ou "visitante" se ja foi a igreja/celula. US-10 reescrita.

- **P10** [APLICADO] [Criterios fracos] US-23 (alertas). Decisao do usuario: alertas configuraveis via gatilhos (regras), nao lista fixa; "tratado" = responsavel baixa a acao. Refinamento adicional: a configuracao (de alertas e tambem do fluxo de onboarding) pode ser editada a qualquer momento, nao apenas no setup. US-23, RF-26 e US-10 ajustados; inteligencia de priorizacao/sugestao automatica marcada como refinamento futuro.
