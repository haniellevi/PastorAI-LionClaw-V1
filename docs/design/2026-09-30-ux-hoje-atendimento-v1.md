# UX v1: Hoje e atendimento humano

## Aprovação e origem

Raniel aprovou o conjunto v1 com a mensagem literal `ok, parovado`, em
30/09/2026, após escolher `Visão geral e atendimento humano (recomendado)` e
consultar a proposta de animação. A aprovação foi aplicada à implementação
local de referências, copy, design e motion apresentada na revisão v1.

Proposta preservada em
`/home/raniel-linux/.codex/visualizations/2026/09/30/01a0f344-ad36-7e90-9939-0cdb2272066f/revisao-ux-v1.md`.
O texto de aprovação pendente desse documento pertence à fase anterior;
este registro documenta a aprovação posterior. A prancha era uma ilustração
conceitual com dados sintéticos. Não era uma captura do produto nem um vídeo.

Base original da revisão: `108cb4eb80f3ff1a7d2de2d3f9eeeba74ac2a27b`.
Branch: `codex/ux-hoje-atendimento-v1`.
Worktree: `/home/raniel-linux/.codex/worktrees/ux-hoje-atendimento-v1/PastorAi-1.0`.
O checkout original foi preservado.

Em 30/09/2026, após validar a prévia, Raniel escreveu `está otimo, pode avançar`.
O candidato foi formalizado localmente e retargetado para a `main`
`226fa6b85dad3f30e400f8ecf8396412571d6c2a`, sem conflitos. Foram preservadas as
mudanças já integradas na fila sem responsável e no mock de identidade/perfil
público. Dependências foram reinstaladas pelo lockfile dessa nova base. Os
860 testes abaixo pertencem à revisão original; no candidato atualizado
passaram 947 testes em 104 arquivos, com Node v24.19.0 e Next 15.5.25.

Na mesma data, Raniel autorizou produção com `pode colocar em produção, mas
veja se consegue melhorar usando Sites`. As orientações de superfície de
trabalho e acessibilidade do Sites foram aplicadas à avaliação, preservando
a hospedagem e a autenticação existentes. O ajuste adicional conserva um
destino de teclado quando o botão da última página desaparece e anuncia a
conclusão numa região de status; não rouba foco de outro campo. Não houve
redesign, migração para Sites ou alteração de identidade. Um teste negativo
falhou antes do ajuste; depois, passaram 949 testes em 104 arquivos e o build.

A revisão automática da PR #445 apontou timeout inicial de histórico tratado
como cancelamento. A correção distingue os casos antes de consultar o sinal
abortado: timeout da visita atual mostra erro e retry; troca de conversa não
contamina a visita nova. Um teste negativo reproduziu o achado. A árvore final
passou em 951 testes, em 104 arquivos, e no build local.

## Resultado e limites do contrato

A fila de cuidados permanece como entrada de Hoje. O título passa a explicitar
as pendências que precisam de atenção. Conversas informa estado, responsável
humano e cobertura parcial da lista. A busca continua local às conversas
carregadas; o usuário pode carregar a próxima página da API existente.

Rascunhos ficam na memória da sessão, separados por conversa. Um envio de
texto só limpa o rascunho depois de resposta bem-sucedida; falha preserva o
texto e envio incerto exige conferência antes de nova tentativa. O frontend
bloqueia submissão concorrente do mesmo texto/conversa. Não há repetição
automática. Trocar identidade, igreja, token ou papéis recria a sessão e
descarta seus rascunhos. Isso não substitui autorização do backend/RLS.

Uma resposta tardia de A não limpa o rascunho de B. A rolagem acompanha novas
mensagens apenas quando o leitor já está no fim; falha no carregamento inicial
do histórico mostra erro e nova tentativa. Conversa selecionada que sai do
filtro permanece aberta com aviso explícito. Vazios distinguem ausência de
conversas, resultado do filtro e ausência de seleção.

Identidade Diamante Lapidado, rotas, capacidades, estados `ia`, `humano` e
`aguardando`, endpoints e payloads foram preservados. O cliente passa a usar
o parâmetro `page` do GET já existente. Não há alteração de backend, schema,
migration, RLS ou gate operacional. O painel Hoje mantém seus filtros
existentes, sem acrescentar o filtro conceitual `Sem responsável` da prancha.
Não foi criado vínculo de navegação entre pendência e conversa sem contrato.

Seleção usa o token existente de 140 ms. Diálogos de ação destes fluxos usam
entrada de 200 ms com opacity/transform. A preferência de movimento reduzido
remove animação e transição desses elementos. Polling não anima a lista.

## Verificação local

| Critério | Evidência e limite |
| --- | --- |
| Testes negativos | Seis novos cenários falharam antes da implementação. O conjunto final cobre falha de envio, draft A/B com envio pendente, mudança de sessão, página 101, seleção fora do filtro, scroll durante polling, falha inicial de histórico e falha da segunda página. |
| Suíte frontend | 860 testes passaram, em 96 arquivos, em 30/09/2026 às 14:42 BRT. São testes locais, com dados e APIs simulados. |
| Build | Build de produção Next passou, incluindo lint/typecheck e geração de oito páginas. Node fixado: v24.19.0. URL de API do build da prévia aponta exclusivamente para loopback. |
| Responsivo | DOM exercitado em 390, 768, 1024 e 1440 px sem overflow horizontal do documento. Lista/thread alternam no mobile. Composer permaneceu no viewport. As capturas CDP de desktop apresentaram repetição de superfície e foram descartadas; capturas nativas ilustram o resultado, sem provar todas as dimensões. |
| Ações e foco | Abertura do diálogo de transferência, foco inicial, Escape e retorno ao botão exercitados. Assumir atendimento exercitado somente no mock. A confirmação de transferência não foi exercitada no navegador. |
| Movimento | Computed styles confirmaram seleção 0.14 s e diálogo 0.2 s. Com reduced-motion, animation/transition ficam removidas; a regra global conserva duração computada mínima de 0.01 ms. |
| Contraste | Sete pares amostrados de cores CSS obtiveram 4.87:1 ou mais. Cálculo localizado; não constitui auditoria integral WCAG. |
| Zoom/leitor de tela | Tentativa de zoom por teclado não alterou a escala no navegador disponível. Zoom real de 200% e uso com leitor de tela permanecem sem verificação. |
| Limites operacionais | Nenhuma prova de CI, backend real, RLS, provider, envio real, deploy ou produção foi produzida. Nenhum desses efeitos foi executado. |

Logs, capturas, métricas e diff ficam em
`/home/raniel-linux/.codex/visualizations/2026/09/30/01a0f344-ad36-7e90-9939-0cdb2272066f/implementacao-v1/`.
O recibo externo `entrega-v1.json` identifica o candidato original sem commit.
A formalização posterior recebe um recibo separado, `formalizacao-v1.json`,
com SHA do commit e base atualizada. Não se deve usar o recibo original como
prova da nova árvore.

## Prévia reproduzível

O laboratório existente recebe a opção `M09_UX_FIXTURE=1`, com 103 contatos
sintéticos, estados de atendimento e histórico em memória. A opção ausente
preserva o cenário padrão. A API rejeita URLs fora de loopback. Login do
laboratório: `admin.e2e@example.test` / `local-only`, ambos fictícios. Nenhum
provedor ou banco participa. O prazo distante exibido na pendência é um
fixture histórico do laboratório, sem equivalência com uma tarefa real.

Use Node 24 na pasta `frontend`. Em terminais separados:

```sh
M09_UX_FIXTURE=1 M09_APP_URL=http://127.0.0.1:3119 M09_API_URL=http://127.0.0.1:8019 node e2e/support/mock-api.mjs
NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_API_URL=http://127.0.0.1:8019 node node_modules/next/dist/bin/next build
NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_API_URL=http://127.0.0.1:8019 node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3119
```

Abra `http://127.0.0.1:3119/#inbox`, alterne a seleção entre Contato A/B/C
para ver a transição e abra `Transferir conversa` para ver a entrada do
diálogo. A prévia da sessão atual usa processos temporários locais.

## Rollback e próximo gate

Rollback: reverter somente o commit desta branch, preservando o checkout
original. Não há migração ou estado de banco a compensar. Pare os dois
processos locais para encerrar a prévia.

A ordem de produção autoriza push, PR, integração e publicação do frontend
desta fatia. A execução depende dos cinco checks exigidos pela main e da
verificação do SHA publicado. Rollback frontend: deployment anterior
`dpl_BDsG4TXaEM19J6BFPnSAYQi1gN4a`, SHA
`226fa6b85dad3f30e400f8ecf8396412571d6c2a`, conferido READY antes da ação.
Essa ordem não altera backend, banco, ativação ou gates de envio.
