# Pontos de melhoria fora da refatoração visual

Este documento registra oportunidades encontradas durante a auditoria. Nenhum item abaixo faz parte do ciclo visual atual. Cada um exige discovery, decisão de produto e validação própria antes de implementação.

## Critério de prioridade

- **P0:** bloqueia a operação ou causa risco sério.
- **P1:** gera suporte, abandono ou retrabalho frequente.
- **P2:** melhora eficiência e confiança.
- **P3:** evolução futura.

## P1. Validar o onboarding real de uma igreja nova

`SetupChecklistScreen` já existe, mas a documentação anterior descreve um fluxo circular entre Pessoa, aptidão, primeira célula e convite de equipe. É preciso executar o primeiro dia completo em staging com uma igreja vazia e verificar se a Configuração Inicial atual realmente elimina o gargalo.

**Pergunta:** um dono recém-ativado consegue chegar à primeira célula e ao primeiro usuário convidado sem suporte externo?

## P1. Resolver a dependência célula antes de convite

O fluxo documentado exige célula para convidar equipe, enquanto criar célula exige líder apto e Pessoa cadastrada. Isso pode obrigar uma ordem que não corresponde ao modelo mental do administrador.

**Decisão necessária:** manter a regra e explicá-la, permitir convite sem célula, ou permitir escolher papel/célula em etapa posterior.

## P1. Confirmar governança real do agente

A documentação de onboarding indica possível divergência entre `AgentConfig.ativo` e o runtime, que pode responder assim que uma credencial válida é cadastrada.

**Decisão necessária:** definir quem ativa o agente e qual estado é a fonte de verdade.

## P1. Estado explícito para módulos desativados por flag

Quando `CELULAS_REQUESTS_ENABLED` está desligada, operações podem retornar 503 sem uma experiência específica de “módulo indisponível”.

**Melhoria possível:** estado de indisponibilidade com motivo, impacto e orientação, sem parecer erro inesperado.

## P2. Busca global ou paleta de comandos

O número de telas e objetos continuará crescendo. Uma busca por pessoa, célula, conversa, evento ou tela pode reduzir navegação para usuários recorrentes.

**Risco:** exige autorização por papel, escopo tenant-safe e resultados bem definidos. Não é apenas visual.

## P2. Atalhos para tarefas recorrentes

Exemplos: abrir fila, nova pessoa, planejar reunião, relatar célula e assumir conversa.

**Risco:** atalhos precisam respeitar contexto, permissões e frequência real. Validar telemetria ou entrevistas antes.

## P2. Rascunho e recuperação de formulários longos

Planejamento de reunião, relatório, comunicado e configuração do agente podem ser interrompidos no mobile.

**Melhoria possível:** preservar rascunho local ou servidor e avisar antes de sair com alterações não salvas.

## P2. Ações em lote

Pessoas, permissões, solicitações e comunicação podem ganhar eficiência com seleção e ações em lote.

**Risco:** aumenta severidade de erro, exige confirmação, undo e autorização rigorosa.

## P2. Histórico de atividade compreensível

Usuários precisam entender quem atribuiu, aprovou, enviou ou alterou algo sem depender de logs técnicos.

**Melhoria possível:** timeline por objeto com linguagem pastoral e eventos relevantes.

## P2. Ajuda contextual por tarefa

O `InfoTip` explica telas, mas decisões complexas podem exigir ajuda no ponto exato.

**Melhoria possível:** explicações curtas junto a ações sensíveis, com link para documentação operacional.

## P2. Persistência da última posição na Jornada

O atalho mobile “Jornada” abre Ganhar. Um usuário que trabalha mais em Consolidar ou Central pode esperar retornar ao último contexto.

**Risco:** persistência é comportamento novo. Definir se será por usuário, dispositivo ou sessão.

## P2. Notificações e central de pendências

Existem prazos, solicitações, relatórios, conversa aguardando e eventos. O sistema pode precisar de uma política unificada de notificação, não apenas badges dispersos.

**Risco:** evitar duplicar a fila do Painel de Hoje e criar fadiga de alerta.

## P3. Personalização por igreja além do logo

A identidade visual por igreja já existe. No futuro, pode haver configuração restrita de nome curto, imagem institucional ou tonalidade dentro de limites de contraste.

**Risco:** não permitir que customização quebre acessibilidade ou coerência do produto.

## P3. Telemetria de usabilidade

Registrar de forma privada e agregada tempo para completar tarefas, abandono de formulários e erros recorrentes pode orientar as próximas decisões.

**Requisitos:** LGPD, minimização de dados, consentimento e ausência de conteúdo pastoral sensível.

## P3. Importação assistida de Pessoas

A documentação aponta cadastro manual um a um como possível gargalo de implantação.

**Melhoria possível:** importação CSV com preview, validação, deduplicação e rollback.

**Risco:** alto impacto em integridade, multi-tenant e dados pessoais. Exige projeto próprio.

## Próximo passo recomendado para este backlog

Depois da refatoração visual, realizar entrevistas e testes com três perfis: pastor, administrador recém-chegado e líder de célula mobile. Pontuar cada item por frequência, impacto, risco e esforço antes de criar roadmap funcional.
