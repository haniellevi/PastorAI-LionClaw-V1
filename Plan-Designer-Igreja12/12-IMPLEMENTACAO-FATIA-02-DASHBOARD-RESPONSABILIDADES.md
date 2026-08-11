# Implementação local, Fatia 02: Painel de Hoje por responsabilidades

Data: 2026-08-11

Status: `PASS LOCAL`, pronto para PR rascunho empilhado sobre a Fatia 01

Base: `fd90ccb9676eaee017be8f2bd7c023280c93e7c4`

Branch local: `codex/ux02-dashboard-responsabilidades`

Grafo: fresco, porém `NÃO COMPROVADO` por integridade estrutural; validação por
leitura direta, testes completos, build e revisão independente

## Objetivo executado

Substituir o Painel de Hoje binário, que tratava qualquer líder como pastor e
qualquer outro papel como membro comum, por uma composição determinística das
responsabilidades acumuladas do usuário.

A fatia preserva os contratos atuais de escopo do backend. Ela não cria novas
funções, não estreita silenciosamente permissões e não inventa dados para
preencher o dashboard.

## Matriz implementada

| Papel efetivo | Ações principais | Contexto complementar | Título seguro |
|---|---|---|---|
| Admin | Fila ampla e atribuição | Agenda, Jornada, operação e Admin | Ações da igreja |
| Pastor | Fila ampla e atribuição | Agenda, Conversas, Pessoas e Jornada | Fila pastoral da igreja |
| Líder G12 | Fila ampla pelo contrato atual | Jornada, Células e Agenda | Ações da igreja sob sua responsabilidade |
| Líder de consolidação | Fila ampla pelo contrato atual | Consolidação, Pessoas e Agenda | Ações de consolidação |
| Líder de célula | Própria célula e atribuições explícitas | Próxima reunião, avisos, Minha Célula e Agenda | Ações sob seus cuidados |
| Líder de multiplicação | Sem fila operacional atual | Multiplicação, Jornada, Enviar, Minha Célula e Agenda | Sua responsabilidade: Multiplicação |
| Operador | Sem fila pastoral | Conversas atribuídas, Ganhar e avisos | Seus atendimentos |
| Membro | Sem ações sobre terceiros | Próximos eventos, própria célula e própria Jornada | Para você |

Papéis acumulados são compostos por união. Um papel amplo preserva seu escopo,
`membro` não apaga responsabilidades adicionais e uma mesma pendência é
renderizada uma única vez.

## Entregue

### Composição e linguagem

- uma função pura centraliza capacidades, títulos e atalhos por conjunto de papéis;
- somente o papel pastor recebe linguagem pastoral;
- líder de multiplicação não recebe fila pastoral vazia;
- operador não recebe boas-vindas genéricas de membro;
- atalhos aparecem somente quando navegação e permissão já existem;
- a primeira visão limita a fila a três ações e oferece expansão acessível.

### Contexto real do dia

- próximos eventos por leitura futura leve, sem baixar o histórico da Agenda;
- eventos `a_confirmar` aparecem como pendência somente para pastor e admin;
- membro usa a própria célula; líder usa as células que realmente lidera;
- células inativas ficam fora do contexto atual do líder;
- múltiplas células lideradas são agregadas com escolha determinística da próxima reunião;
- avisos da igreja, da célula pessoal ou das células lideradas conforme responsabilidade;
- atalhos por responsabilidade, sem criar módulos ou ações novas;
- falha parcial preserva os blocos que carregaram com sucesso.

### Escopo e consistência de dados

- preload e tela usam a mesma decisão de responsabilidades;
- a matriz personalizada é carregada ao autenticar e usada pelo shell, dashboard e preload;
- leitura da matriz é autenticada e explicitamente filtrada pela igreja; edição continua admin-only;
- falha de leitura usa matriz mínima `dashboard` e nunca reabre telas revogadas;
- o papel Operador é preservado na normalização da matriz;
- papéis sem fila deixam de buscar fila e overview desnecessariamente;
- troca ou revogação de papel limpa dados, modal e contexto residual;
- overview de líder usa vínculo canônico ativo em `CelulaMembro`, dentro de
  célula ativa, e deixa de depender do espelho legado `Pessoa.celula_id`;
- pessoas arquivadas deixam de entrar no overview;
- a primeira página da fila libera ações rapidamente e as páginas restantes hidratam em segundo plano;
- total, filtro `Meus`, expansão, deduplicação e falha tardia permanecem honestos;
- a âncora da fila é revalidada e a hidratação reinicia quando a paginação muda;
- vincular à célula encerra atomicamente apenas a pendência `conectar_celula` correspondente;
- o seletor de célula percorre todas as páginas sem truncar em 100 itens.

### Estados e acessibilidade

- carregamentos operacionais expõem `aria-busy` e escondem skeleton decorativo;
- erro da fila principal é acionável e não aparece como fila vazia;
- erros complementares degradam apenas o bloco afetado;
- erro persistente usa alerta com fechamento explícito;
- controles da Jornada, agente, contexto e expansão têm alvo mínimo de 44 px e foco visível;
- destinos de Agenda, Minha Célula e módulos usam links hash reais, inclusive nova aba;
- resumo móvel muda de composição para não comprimir rótulos em 360 e 390 px;
- estados continuam descritos por texto e não dependem apenas de cor.

## Decisão de produto preservada

O planejamento recomenda que líderes especializados vejam somente sua própria
responsabilidade. O contrato vigente, porém, concede fila e overview amplos a
`lider_g12` e `lider_consol`.

Esta fatia mantém o comportamento atual para evitar uma quebra de autorização
disfarçada de mudança visual. O eventual estreitamento deve ser decidido e
implementado em uma fatia própria de produto e backend, com migração de
expectativas e testes por papel.

## Validação consolidada

- frontend: `73` arquivos e `665/665` testes PASS;
- frontend focal consolidado: `95/95` testes PASS;
- frontend: build Next.js `15.5.22` PASS;
- backend: suíte integral com exit code 0;
- backend: `compileall` PASS;
- backend focal do overview: `9/9` PASS;
- backend focal consolidado de Agenda, overview e permissões: `27/27` PASS;
- regressão relacionada ao overview e escopos: `91/91` PASS;
- `git diff --check`: PASS;
- revisão independente final: `PASS`, sem P0, P1 ou P2 remanescente;
- nenhuma migration, alteração de banco, deploy ou produção.

## Medido, inferido e não comprovado

### Medido

- composição por papéis isolados e acumulados em testes;
- carregamento, falha parcial, erro principal, troca de papel e dados residuais;
- contexto distinto para célula pessoal e células lideradas;
- hidratação progressiva da fila e leitura futura da Agenda;
- matriz personalizada por igreja em sessões de usuário comum;
- contrato canônico do overview por célula ativa;
- suíte completa, compilação e build de produção.

### Inferido

- o primeiro viewport fica mais orientado a ação ao limitar a fila a três itens;
- a linguagem por responsabilidade reduz a percepção de que todo líder é pastor;
- a degradação por bloco melhora a confiança em conexão instável.

### Não comprovado nesta fatia

- captura autenticada do código local em 360, 390, 768, 1024 e 1440 px;
- uso com leitor de tela real e zoom de 200% em navegador;
- comportamento em produção, pois não houve deploy;
- adequação do escopo amplo de G12 e Consolidação à decisão final do produto.

## Gate de aceite

O código pode seguir para PR rascunho empilhado sobre a Fatia 01. Revisão,
merge, migration, deploy, smoke de produção e ativação permanecem gates
separados. A recomendação é revisar primeiro a linguagem e a matriz por papel,
depois executar smoke autenticado local com contas representativas.
