# Igreja 12 — contexto de produto

## Register

product

## Propósito

O Igreja 12 é o sistema operacional pastoral da igreja. Ele reúne a fila de trabalho do dia, conversas no WhatsApp oficial, pessoas, agenda, células, consolidação, discipulado, multiplicação e configuração administrativa sem obrigar a liderança a reconstruir o contexto em várias ferramentas.

O produto não é um painel de BI. Sua principal função é mostrar o que precisa de atenção, por quem, até quando e qual é a próxima ação segura.

## Usuários

- Pastor e pastora: supervisionam a operação, cuidam de exceções, prazos e saúde ministerial.
- Administrador e dono da igreja: configuram pessoas, acessos, integrações, identidade e assinatura.
- Líder G12 e líder de célula: operam sua responsabilidade ministerial com rapidez e pouco treinamento.
- Consolidador e outras lideranças: acompanham tarefas e pessoas dentro do seu escopo.
- Discípulo ou membro: consulta e participa da própria célula em uma experiência muito mais simples que a área administrativa.

Os usuários variam bastante em domínio digital. O sistema deve ser compreensível para alguém usando um software de gestão pela primeira vez e eficiente para quem o acessa todos os dias, muitas vezes pelo celular e entre interrupções.

## Modelo mental do produto

- `app.` é a operação cotidiana da igreja.
- `admin.` é a configuração da igreja.
- `painel.` é o console master do SaaS.
- A primeira tela da operação é uma fila de trabalho, não um relatório executivo.
- `Minha Célula` atende membro e líder; `Central de Célula` atende pastor e administração central.
- Célula é comunidade e reunião. Árvore Ministerial é liderança e cobertura. As duas estruturas se relacionam, mas não são a mesma coisa.
- A Jornada G12 organiza Ganhar, Consolidar, Discipular e Enviar, sem obrigar o usuário a compreender toda a arquitetura antes de agir.

## Personalidade

Calma, humana, confiável e pastoral. O sistema deve transmitir cuidado e competência sem parecer religioso de forma decorativa, corporativo demais ou uma demonstração genérica de tecnologia com IA.

O texto é direto, acolhedor e específico. A interface evita jargão técnico, frases promocionais, excesso de explicação e tom infantil.

## Experiência desejada

- A ação principal de cada tela é reconhecida em até 5 segundos.
- Tarefas frequentes exigem poucas decisões e poucos deslocamentos.
- O usuário sempre entende onde está, o que aconteceu e o que fazer depois.
- Complexidade aparece progressivamente, apenas quando necessária.
- Desktop favorece supervisão e comparação; mobile favorece uma tarefa por vez e alcance com o polegar.
- Estados vazio, carregando, sucesso, erro, bloqueio e permissão negada orientam a próxima ação.
- Beleza vem de hierarquia, ritmo, tipografia, superfícies e precisão, não de decoração.

## Direção visual

Minimalismo pastoral contemporâneo, com superfícies claras frias, tinta verde-petróleo e teal usado com disciplina. O produto deve parecer construído para a Igreja 12, não um dashboard SaaS genérico.

O sistema preserva a identidade já reconhecível, mas reduz gradientes decorativos, sombras promocionais, grades de cartões idênticos, pílulas em excesso e cores de estágio competindo com a tarefa.

## Princípios estratégicos

1. Ação antes de informação.
2. Uma tela, uma prioridade dominante.
3. Reconhecimento antes de memorização.
4. Familiaridade nas interações; personalidade na composição.
5. Menos camadas de navegação simultâneas.
6. Estado e urgência não dependem apenas de cor.
7. Componentes compartilhados têm comportamento e aparência previsíveis.
8. Acessibilidade e mobile fazem parte da qualidade visual.
9. Nenhuma refatoração visual altera RBAC, RLS, regras G12, APIs ou estados de domínio.
10. Toda decisão visual precisa de evidência por screenshot e breakpoint.

## Anti-referências

- Dashboard genérico de IA com gradientes, brilho, glassmorphism e cards iguais.
- Tela de BI que enterra as pendências sob métricas.
- Interface eclesiástica ornamental, solene ou carregada de símbolos.
- Aplicação mobile que apenas empilha a versão desktop.
- Minimalismo que remove contexto, rótulos, estados ou orientação.
- Animação decorativa, lenta ou que atrasa tarefas.

## Limites desta refatoração

- Não criar funcionalidades, endpoints, rotas, papéis, telas ou regras de negócio.
- Não desbloquear Universidade da Vida ou Capacitação Destino.
- Não misturar Minha Célula com Central de Célula.
- Não reabrir decisões ministeriais já travadas.
- Melhorias funcionais descobertas durante a auditoria devem ser registradas em `docs/design/pontos-melhoria.md`, não implementadas no ciclo visual.

## Fontes de verdade

- `SPEC.md`
- `docs/Docs20260611_163530/PRD20260611_163530.md`
- `docs/Docs20260611_163530/design/design-brief.md`
- `docs/design/RECONCILIACAO-igreja12.md`
- `docs/design/REDESIGN-UX-AJUSTES-POS-F4.md`
- `docs/design/CONTRATO-UX-CELULAS-CENTRAL.md`
- PRDs de Minha Célula e Central de Célula em `docs/design/`
- Código atual em `frontend/src/`
