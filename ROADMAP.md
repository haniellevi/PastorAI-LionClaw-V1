# Igreja 12 — roteiro único

Atualizado em 16/10/2026 sobre a `main` `79dfa534`. Esta é a única fonte ativa
de planejamento; substitui os planos de MVP e refatoração e seu acompanhamento.
O [PRD canônico](docs/Docs20260611_163530/PRD20260611_163530.md) conserva os
requisitos. As decisões de 15/10 prevalecem sobre os cortes antigos de escopo,
inclusive a entrada de Universidade da Vida e Capacitação Destino.

**Objetivo:** cuidar das pessoas e organizar a rotina G12 pelo WhatsApp oficial;
o painel serve à configuração, supervisão, exceções e ações sensíveis.
A V1 encerrou como piloto controlado; o produto completo ainda está em construção.

**Como ler:** **feito** = entrega delimitada implementada; **em andamento** =
entrega parcial; **falta** = trabalho ou decisão pendente. A coluna de produção
é separada: código e teste local não provam publicação ou ativação. Os testes e
publicações citados abaixo são registros anteriores, não repetidos nesta entrega.
Quando falta prova, usamos **não verificado**. Produção é o sistema em uso;
`main` é o código integrado; teste local exercita uma simulação no computador.

**Piloto:** Filadélfia, restrito a testadores internos. A decisão de 15/10 mantém
o agente ligado como está, sem ampliar o piloto. O registro informa resposta em
cerca de 28 s e monitor verde desde 14/10; o estado atual é **não verificado**.
O último backend registrado é `eb5a09b` (27/09); versão atual: **não verificado**.

## 1. Simplificação documental

| Entrega | Estado | O que falta |
|---|---|---|
| Roteiro único e regras de agentes coerentes | feito | [PR #480](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/480), merge `a812b9a6`; quatro checks pós-merge aprovados. Isso não conclui o produto. |
| Registrar entregas na descrição da PR | feito | Regra definida aqui; sem novos sprints ou atualização obrigatória do painel paralelo. |
| Arquivar documentação antiga sem perder histórico | em andamento | Lote 1 feito: [PR #481](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/481), merge `79dfa534`. Lote 2 em andamento: 87 documentos/registros de governança, missões e planos temáticos preservados em `archive/docs-2026-10-lote2` (`79dfa534`), com referências históricas em SHA fixo. Faltam revisão, quatro checks e integração do lote 2. Insumos de verificadores, runbooks duvidosos e demais conjuntos ficam preservados para decisão. |

## 2. Organização do checkout

| Entrega | Estado | O que falta |
|---|---|---|
| Limpeza recuperável de worktrees e branches locais | em andamento | Recuperação dos 37 worktrees conferida em 15/10, com 0 divergências; referências `refs/archive/worktrees-20261015/`. Isso é evidência registrada daquela conferência, não uma nova validação nesta entrega. Resta preservar trabalhos úteis e tratar os remanescentes. |
| Voltar o checkout principal à main | feito | Checkout em `main` `63a1b798` em 16/10. Estado anterior preservado na referência **local** `refs/archive/checkout-principal-20261016` (`6d75e085788fc9d0612217830010433b7fa45ce6`): 23 alterações/arquivos soltos conferidos, 0 divergências, e os dois commits locais preservados por ancestralidade. `chore/neon-dev-setup` mantida. Configuração local e `output/` permanecem no disco para decisão; `output/` não foi lido nem arquivado. Outros worktrees intactos. |
| Decidir o destino dos arquivos locais restantes | falta | Revisão do proprietário: dois exemplos de ambiente alterados somente na referência local acima; `.claude/settings.json` arquivado e mantido no disco; 18 arquivos em `output/` fora do arquivo Git e sem leitura. Artefatos locais de ferramentas também permanecem no disco, sem limpeza autorizada. |

Nenhum trabalho não salvo pode ser preservado apenas criando uma referência ao
HEAD: é preciso guardar também as alterações e arquivos novos, conferir a
recuperação e excluir segredos/dados reais de qualquer snapshot Git. Worktrees
Codex são arquivadas pela ferramenta responsável. Nada de limpeza global ou de
branches remotas sem ordem própria. Não apagar migrations para organizar pastas.

## 3. Próximas funcionalidades

| Entrega | Estado | Implementação / teste | Produção |
|---|---|---|---|
| Pedido de oração pelo WhatsApp (V4) | feito | Primeira versão de texto e pedido próprio integrada na main pela [PR #484](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/484), merge `2d408d92`; implementação e testes registrados. DESLIGADO por igreja e por trava de release; sem produção. Esconder no inbox e áudio ficam para depois. | não verificado em produção |
| Indicar células próximas | feito | Indicação guiada somente por bairro integrada na main pela [PR #486](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/486), merge `1caf4a36`; implementação e testes registrados. Só células ativas com divulgação autorizada, sem endereço ou dados do líder; sem cálculo de distância ou vínculo automático. DESLIGADO por igreja e por trava de release; sem produção. | não verificado em produção |
| Fluxo G12: ganhar, consolidar e célula | em andamento | Implementado na main, desligado e sem produção: evento real de visita de célula ligado à Pessoa ([PR #487](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/487), merge `05eb07b9`); aceite explícito da fonovisita com convite de 24h, troca após aceite e autoatribuição ([PR #488](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/488), merge `8d3d13f2`); primeira visita sugere vínculo com a célula, confirmado por pastor/admin ([PR #489](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/489), merge `b3fdd6fc`). G12 PR 5 em andamento na [PR #490](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/490): percurso reunião → atraso → lembrete → baixa comprovado pelo agente e painel com provedor simulado; supressão terminal registrada só para igrejas da release/lista V1a; handoff e conexão indisponível são transitórios; nenhum gate aberto. Falta aceitar com o piloto o caminho completo. | Fluxo completo: não verificado |
| Aceite pastoral do atendimento | falta | Aprovar 20 conversas reais, incluindo visitante, oração, horário, opt-out e crise; corrigir os problemas encontrados. | não verificado |

## 4. Demais funcionalidades e qualidade

Modularizar a área quando ela for tocada, preservando os serviços existentes.
Sem reescrita geral, renomeio em massa ou refatoração como pré-requisito de tudo.

| Entrega | Estado | Implementação / teste | Produção |
|---|---|---|---|
| Atendimento básico, consentimento, opt-out, passagem para humano e informações públicas | feito | Resposta de IA ao texto atual, contexto curto da conversa e consultas determinísticas registrados; isolamento e controles mantidos. | Piloto registrado; estado atual não verificado. |
| Ações por papel (S3) | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Relatório por texto (V1a) | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Relatório por áudio (V1b) | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Agenda V2 | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Consolidação V3 | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Presença própria (V4) | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Expectativa de visitante (V4) | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Simulador e prova integrada de visitante | feito | Transporte falso, fila Redis, worker, catálogo, autorização, banco com isolamento entre igrejas e acesso autenticado; testes locais/CI registrados (#462/#466). Não prova aceite online pelo navegador nem lembretes com gates fechados. | Simulador não se destina a PROD. |
| Ferramentas de desenvolvimento e testes | feito | Versões alinhadas ao CI; `test-local.sh` recusa alvo desconhecido (#464), com teste registrado. Corrige o falso sucesso sem executar testes. | Ferramenta de desenvolvimento. |
| Refatorações de visitante e leitura da resposta | feito | Validação de nome no domínio e leitura fora do worker, com regressão registrada (#465/#467). | não verificado |
| Universidade da Vida | em andamento | Desenho aprovado em 5 fatias; PR 1 integrada (merge `265a0397`): contrato tipado de entrada, oito aulas com reposição registrada, Encontro/batismo validados e confirmação do responsável. Conexão à célula é pendência independente. Conclusão individual operacional não comprova UV nem concede nova aptidão à CD; aptidão legada preservada com origem identificada no contrato, sem conclusão retroativa. PR 2 em andamento na [PR #492](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/492): persistência, turmas, calendário de oito aulas + Encontro, responsáveis e matrículas explícitas, API e painel mínimos; gestão de responsáveis e encerramento/reabertura restritos à coordenação, autoria por igreja e exclusão em cascata. PR 2 aguarda integração (#492). PR 3 em andamento, encadeada à PR 2: chamada das aulas 1 a 8, reposição, correção com histórico, API e painel mínimos; pendências calculadas pelo contrato, sem concluir UV nem alterar aptidão à CD ou etapa da Pessoa. PR 4 em andamento, encadeada à PR 3: marcos únicos de Encontro/batismo na Pessoa (inclusive anteriores à turma, com data e validador), conclusão humana após oito aulas e ambos os marcos, transição sem rebaixamento para discipular e aptidão à CD na mesma transação, com origem própria e legado preservado sem UV retroativa. Responsável ativo da turma ou coordenação validam; conexão à célula não bloqueia e não há matrícula automática em CD. PR 5 em andamento, encadeada à PR 4: consulta mínima de turmas/matriculados, aulas cumpridas/pendentes e marcos pelo WhatsApp; proposta de presença e confirmação literal SIM, usando os mesmos serviços e autorizações do painel, com resposta após commit e recuperação pelo ledger existente. Matrícula, conclusão e marcos continuam exclusivos do painel autenticado. DESLIGADA: `UV_WHATSAPP_APPROVED_RELEASE_ID=None` e lista `UV_WHATSAPP_ENABLED_IGREJA_IDS` vazia por padrão; nenhum gate aberto. Falta revisão, quatro checks e integração da cadeia. | não verificado |
| Capacitação Destino | falta | Definir e implementar módulos/livros, turmas, frequência, pré-requisitos e certificação. | não verificado |
| Enviar e multiplicação | em andamento | Existem partes de células e solicitações; falta jornada de aptidão, edição/aprovação sensível e integração com formação. | não verificado |
| Memória privada durável | falta | Resumos e retomada privados, com exclusão de derivados. | não verificado |
| Conhecimento oficial | falta | Documentos aprovados, versionados e com público autorizado; busca segura. Conversas nunca viram conhecimento oficial automaticamente. | não verificado |
| Ferramentas e especialistas por área | em andamento | Ampliar rotinas pelo WhatsApp usando os mesmos serviços do painel; comportamento global versionado, dados e execução por igreja, credencial OpenAI própria da igreja. | não verificado |
| Pessoas, responsabilidades, Minha Célula, Central e Hoje | em andamento | Base existente; faltam responsabilidades temporais/por setor, planejamento, alertas e composição das pendências. | Cobertura completa: não verificado. |
| Triagem semântica Jev | em andamento | S1 implementada/testada com simulações; falta avaliar qualidade real, crise/humano e falsos opt-outs, contrato de tratamento de dados e autorização específica. Jev B/C/D continuam condicionados. | não verificado; não autoriza ativação. |
| Comunicados, assinatura/Asaas e e-mail/Brevo | em andamento | Bases implementadas; faltam aceite por finalidade, domínio/remetente e canários separados. Não envolver a igreja em cortesia em cobrança real. | não verificado |
| Onboarding da igreja, equipe, permissões e console | em andamento | Há telas/serviços; faltam fechamento do fluxo de responsáveis/aprovações e validação das lacunas de acesso. Assistente no painel respeita igreja/papel. | Cobertura completa: não verificado. |
| Exclusão da pessoa, exclusão da igreja e reset | em andamento | Exclusão de conversa existe; falta alcançar transcrição, resumo, checkpoint e vetores. Candidato de reset/exclusão precisa reconferência de integração e recuperação. | não verificado |
| UX, acessibilidade e desempenho do painel | em andamento | Hoje/atendimento e UX v3 implementados; proteção do microfone ao trocar de conversa em candidato. Faltam teclado, leitor de tela, zoom, mobile e métricas autenticadas de campo; integração atual desse candidato: não verificado. | Frontend publicado conforme registros; backend/telemetria e operação completa: não verificado. |
| Agenda completa e importação Google | em andamento | Base de cadastro/consulta existe; falta fechar o especialista, entrega de avisos e integração com credencial isolada por igreja antes de usar Google. | não verificado |
| Observabilidade de IA e operação | em andamento | Há logs/custos/filas; faltam métricas por igreja/rota, retenção, metas de serviço e alertas de fluxos presos. | não verificado |

**Segurança e decisões que permanecem abertas:**

- **falta:** tratar os achados da auditoria de 03/10: segredo em URL de log,
  escopo de igreja em cron/SLA, MFA no console e logout no servidor. A auditoria
  está fora da main; correções e reprodução atual: **não verificado**.
- **em andamento:** dependências corrigidas e triadas (#463/#469/#470);
  auditorias das dependências de produção registradas como limpas em 10/10, mas permaneciam cinco
  alertas altos nas ferramentas ligados a `braces`. Situação atual **não verificado**.
- **falta:** decidir a divergência de acesso customizado ao inbox, opt-out no
  envio humano e expectativa de visitante em reunião passada (backlog técnico
  B3/B4). Preservar opt-out global e regras por canal até decisão; refatoração
  não muda comportamento silenciosamente.
- **falta:** reconferir os bugs históricos de classificação CSIM, primeiro
  consentimento e interpretação de relatório (B5/B7/B15 do MVP); não declarar
  resolvidos pela presença em auditoria. B1/B2/B3/B4/B14/B16 têm correções
  registradas, com disponibilidade atual em produção **não verificado**.
- **falta, quando houver necessidade concreta:** diagnóstico de configuração
  sem segredos, registro de ações sem relaxar autorizações e retirada individual
  de código/testes com proteção equivalente (B1/B2/B5 do backlog técnico).
  Medir ganho real por fatia na PR, sem percentuais inventados (B6).

**Trabalhos a preservar fora da main, conforme inventário de 15/10:** medições,
ferramentas de avaliação da interpretação e demonstração V1a de 13/10 em
`integracao-incremental-20261013`; auditoria em
`arquitetura-performance-seguranca-20261003`. Integração desse material e estado
dos arquivos não salvos: **não verificado**. Nenhuma cópia ou descarte nesta entrega.

## 5. No final: banco, latência, infraestrutura e release

| Entrega | Estado | O que falta |
|---|---|---|
| Banco Supabase e histórico de migrations | em andamento | Registro de 14/10: 78 aplicadas, backup e quatro pendentes de propósito (`20260711_023515`, `20260711_152127`, `20260925_183811`, `20260926_120446`). Estado atual **não verificado**. Decidir destino das pendentes e eventual consolidação do histórico sem impedir recriação local; Neon cancelada. |
| Reconciliação da virada da agenda V2b | falta | Visibilidade/inventário de usuários, gates e entrega dos 11 eventos EVT-7: **não verificado**. Conciliar com provedor/logs antes de decidir qualquer reenvio, que pode duplicar. |
| Resposta rápida (B17), capacidade e estabilidade | falta | Meta abaixo de 10 s adiada para esta etapa; medir região de servidor/banco e decidir infraestrutura. Investigar incidentes e falhas de prontidão da API: monitor verde registrado não prova causa resolvida. |
| DEV online isolado | em andamento | Preparação integrada e ensaio sintético registrados (#468/#471); ambiente disponível **não verificado**, registrado como ainda inexistente. Faltam executor exclusivo, região, teto de custo, recursos e aceite de login/Storage/navegador com duas igrejas. Local continua opcional para depuração/testes. |
| Publicação coordenada de backend/frontend e recuperação | em andamento | Preparação e ensaio integrados (#472/#473; merge de #473 confirmado no Git). Falta pacote validado, versão viva anterior, compatibilidade de banco, contenção dos consumidores, janela e autorização nominal. Não prometer rollback universal. |
| Publicação automática no DEV e explícita em PROD | falta | Operar o caminho preparado e acertar a publicação do frontend com a API (B9/B13). Não alterar agora a automação atual ou gates. |
| Backup diário e restauração | falta | Verificar rotina, restaurar em alvo isolado e incluir novas tabelas privadas. Pré-checagens de rede/backup, Compose e recuperação ainda exigem aceite no alvo. |
| Revisão antes de ampliar o piloto ou lançar | falta | Conferir autenticação/Clerk Production, configurações, gates e privacidade; canários Asaas/Brevo/broadcast/agente independentes. Governança pausada não é reativada automaticamente. |

**Preservar para esta etapa:** pré-checagem de backup em
`vps07a-source-20261005`, guarda de rede em `vps04a-network-guard`,
`lock_timeout` em `elastic-kirch-0de4a3` e scripts de backup externo cifrado
(`deploy/offsite-encrypt-backup.sh` e `deploy/pull-offsite-backup.sh`). Os scripts,
a avaliação Jev de 26/09 e as evidências de 04/10 estão somente na referência
local `refs/archive/checkout-principal-20261016`, nos caminhos originais;
preservação conferida, integração e funcionamento **não verificados** nesta
entrega. Os demais candidatos continuam sem nova conferência de recuperação;
não são correções declaradas entregues.

Governança E4B/D3/D6/D2A, atestações, catálogos e F1/F2 de governança permanecem
pausados; reavaliação somente por necessidade e decisão próprias. Isso não
adianta banco/infra nem impede desenvolver UV/CD após a etapa 3.

## Evidências e manutenção

A consolidação usa os dois planos agora históricos
([MVP histórico](https://github.com/haniellevi/PastorAI-LionClaw-V1/blob/a812b9a6ef68b8757fda9e776e4f149cc2913722/docs/ops/MVP-PLANO-SIMPLIFICACAO.md) e
[refatoração histórica](https://github.com/haniellevi/PastorAI-LionClaw-V1/blob/a812b9a6ef68b8757fda9e776e4f149cc2913722/docs/ops/refatoracao-modular-plano.md)), os 22 itens do
[acompanhamento arquivado](https://github.com/haniellevi/PastorAI-LionClaw-V1/blob/a812b9a6ef68b8757fda9e776e4f149cc2913722/docs/ops/acompanhamento/tarefas.json), a [cobertura do PRD](docs/ai/PRD-COVERAGE.md) e o Git da base.
O [registro V2b](docs/sprints/2026-10-15-v2b-verificacao-pos-cutover.md) mantém
explícitos os limites da consulta anterior; ele não declara o banco consistente.
Não houve consulta à produção nesta entrega. Os documentos históricos são
evidência, não instruções para retomar suas sequências ou manter seu painel.

Daqui para frente, atualizar somente este roteiro quando o estado/escopo mudar
e registrar entrega, testes e limites na descrição da PR. Requisitos e runbooks
continuam sendo referências técnicas; sem novo sprint, painel ou plano paralelo.
Integração exige `backend-tests`, `frontend-ci`, `e2e-critical` e
`rls-integration`; produção e efeitos reais exigem autorização nominal própria.
