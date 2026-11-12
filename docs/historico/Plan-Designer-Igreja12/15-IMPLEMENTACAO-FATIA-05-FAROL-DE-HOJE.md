# Implementação local, Fatia 05: Farol de Hoje

Data: 2026-08-11

Status: `IMPLEMENTAÇÃO LOCAL VALIDADA, AGUARDANDO ACEITE VISUAL DO PREVIEW`

Base: `87a03d9ad48731418b65724dbb1cf7fd3c52db57` (cabeça do PR #253)

Branch local: `codex/redesign-dashboard-diamante`

Grafo: `NÃO USADO`; a fatia foi definida por leitura direta dos contratos do
Dashboard, dos documentos de produto, dos testes e da interface local.

## Objetivo

Transformar o Painel de Hoje em um farol operacional: a pessoa deve reconhecer
em poucos segundos o que precisa de atenção, qual é o próximo passo e como seu
papel participa do cuidado da igreja. A interface preserva dados, permissões,
rotas e ações existentes. Nenhuma métrica ou capacidade foi inventada.

## Direção visual aplicada

- marinho profundo e azul mineral preservam o reconhecimento da Igreja 12;
- o diamante aparece uma vez no farol e reaparece discretamente no caminho G12;
- superfícies claras, bordas minerais e faixas semânticas separam contexto,
  urgência e progresso sem transformar tudo em cards iguais;
- âmbar sinaliza atenção real, azul indica ação e o verde permanece restrito ao
  sucesso sem se tornar cor principal;
- movimento é curto, funcional e removido quando `prefers-reduced-motion` está
  ativo; não há gradiente decorativo.

## Arquitetura implementada

### Primeira dobra

1. farol compacto com saudação humana, data e estado real do dia;
2. fila de ações em largura útil, com três prioridades antes da expansão;
3. ações com nome acessível contextual, estado ocupado e feedback persistente.

A saudação prefere o nome de conversa e remove títulos como `Pr.` ou `Pastor`,
evitando frases artificiais como “Boa noite, Pr.”.

### Prioridade por responsabilidade

- pastor e administrador: fila operacional primeiro;
- líder de célula: cuidados da célula e contexto local;
- operador: Conversas e Ganhar antes do contexto geral;
- líder de multiplicação: Enviar e Jornada G12 antes dos atalhos genéricos;
- membro: próxima reunião, Agenda e avisos antes de áreas administrativas.

Papéis acumulados continuam sendo compostos. A ordem visual não concede novas
permissões e não substitui o gate do backend.

### Camada de apoio

Depois da fila ficam:

- `Hoje no seu contexto`, com falha local distinguida de vazio real;
- `Caminho vivo`, mostrando Ganhar → Consolidar → Discipular → Enviar como
  sequência conectada e com números reais;
- `Pendências por responsável` e `Visão geral do seu cuidado` como informação
  secundária, sem disputar a primeira ação.

Não há rail lateral persistente. Em tablet e mobile, a mesma ordem se mantém em
uma coluna; títulos e ações podem quebrar em blocos sem gerar largura fixa.

## Acessibilidade incorporada

- lista de trabalho exposta como lista semântica;
- botões repetidos incluem a pessoa ou tarefa no nome acessível;
- controles anunciam estado ocupado durante requisições;
- atualização da fila tem mensagem de início e conclusão fora da região
  `aria-busy`;
- prazos deixam de disparar anúncios periódicos a cada atualização do relógio;
- foco retorna à fila após a ação que remove o item;
- controles têm 40 px no desktop e 44 px nos breakpoints de toque;
- skeleton estático no Dashboard, sem shimmer contínuo.

Pendências transversais do shell, como link de pular para o conteúdo e foco após
troca de rota hash, ficam para uma fatia própria porque afetam todo o sistema.

## Estados honestos

- falha parcial de Agenda, reunião ou avisos mostra `indisponível agora` apenas
  na fonte afetada;
- vazio real continua orientando a pessoa sem simular carregamento;
- a primeira página da fila aparece cedo e a hidratação posterior preserva
  total, expansão, alterações locais e resposta obsoleta;
- falha tardia mantém o conteúdo já carregado e informa que a visão é parcial.

## Arquivos principais

- `frontend/src/components/dashboard/DashboardScreen.tsx`;
- `frontend/src/components/dashboard/TodayContext.tsx`;
- `frontend/src/components/dashboard/NextActions.tsx`;
- `frontend/src/components/dashboard/WorkQueueItem.tsx`;
- `frontend/src/components/dashboard/DeadlineBadge.tsx`;
- `frontend/src/components/ds/Button.tsx`;
- `frontend/src/lib/dashboard-responsibilities.ts`;
- `frontend/src/app/globals.css`;
- testes focais e de contrato visual correspondentes.

## Evidência e limites

Medido nesta fatia:

- typecheck, 101 testes focais e a suíte completa com 712 testes do frontend;
- build otimizado do Next.js 15.5.22;
- inspeção visual local com sessão simulada do Dashboard em desktop;
- estrutura, nomes acessíveis e links reais pelo navegador interno;
- ausência de rail persistente, gradientes e animação obrigatória por contrato
  estático;
- `git diff --check`.

Inferido por CSS e testes, ainda não medido em dispositivo real:

- comportamento em 360, 390–414, 768 e 1024 px;
- ergonomia com leitor de tela e teclado em navegador real.

Não comprovado nesta fatia:

- desempenho de rede em produção;
- comportamento autenticado em produção para todos os papéis;
- impacto de dados de igrejas com filas muito extensas.

## Mutação e gates

- backend, banco, migrations, integrações e produção: nenhuma alteração;
- merge e deploy: não autorizados por esta fatia;
- próximo gate: aceite visual do preview e revisão do PR empilhado;
- após merge do PR #253, a base desta fatia deve ser atualizada para `main`
  antes de qualquer merge próprio.
