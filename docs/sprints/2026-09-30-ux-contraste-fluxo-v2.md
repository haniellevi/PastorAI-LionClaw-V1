# Contraste e clareza v2: Hoje e Conversas

## Aprovação e proveniência

Em 30/09/2026, Raniel aprovou a implementação do planejamento global v2:
"pode fazer, acho que precisa ter mais constraste, textos precisam ser encontrados
facilmente, da impressao que é muita informação e o usuario se esforça para entender
o fluxo de uso do sistema". A direção aprovada está no pacote local
`ux-global-v2-planejamento`, com plano, inventário de 42 unidades e pranchas.

Este primeiro recorte aplica contraste na fundação compartilhada e clareza no
fluxo Hoje → Conversas. Base `88ea8d96008159245df74845521b54878b0db4a3`, branch
`codex/ux-contraste-fluxo-v2`, worktree `/tmp/igreja12-ux-contraste-v2-20260930`.
O checkout original e a versão v1 permanecem preservados.

## Aceite e resultado

Pessoa, motivo e ação principal devem ser reconhecíveis na primeira leitura;
ações adicionais continuam disponíveis por teclado. Textos operacionais precisam
atingir AA, foco visível e controles principais de 44 px. O retorno mobile deve
preservar busca e rascunho.

- Tokens: texto secundário em ink-600 a 46% de luminosidade, foco diamond-600,
  borda de controle reforçada; corpo 15 px, rótulo 14 px e metadado 13 px.
- Hoje: uma ação principal por cuidado; Assumir, Atribuir e Mensagem permanecem
  disponíveis conforme capacidade em "Mais ações". Agenda imediata continua
  visível; Jornada e responsáveis ficam sob demanda. Abrir conversas respeita RBAC.
- Conversas: estado e responsável junto à pessoa; Transferir e Ver pessoa com
  texto visível e nome acessível coerente. Excluir continua restrito e confirmado.
- Sem alteração de autenticação, API de produto, schema, tenant ou autorização.

## Verificação local

Node 24.19.0 e versões fixadas do frontend; Chromium 151.0.7922.34, revisão 1234
exigida pelo Playwright 1.62.1. Laboratório exclusivamente em `127.0.0.1:3120`
e `127.0.0.1:8020`, com contatos fictícios e requisições externas bloqueadas.

O E2E novo exerce disclosure por teclado, atribuição, abertura/cancelamento de
mensagem sem envio, foco de retorno, navegação autorizada, rascunho e busca no
mobile. Também mede contraste renderizado e largura em 390/768/1024/1440 px.
A primeira execução detectou seletor textual ambíguo no helper e `tiposFila`
ausente no mock de equipe; ambos foram corrigidos sem enfraquecer asserts.

Medição em Chromium: texto de contexto/fundo 6,91:1, texto/ação 6,36:1 e
foco/fundo 4,16:1. Essas medições são dos pares exercitados, sem representar
uma auditoria completa de todas as telas, estados ou conteúdos reais.
Resultados finais, screenshots e hashes ficam no recibo da implementação.

Em 30/09, 21:00 UTC, passaram 951 testes em 104 arquivos do frontend, lint e
typecheck. Build final passou; os três E2E de clareza passaram após o último
ajuste do placeholder ("Assuma primeiro"). Sete E2E críticos passaram antes
desse ajuste exclusivamente textual. O teste novo comprova encaixe da instrução,
foco de 2 px por Tab/Shift+Tab e transição reduzida nos quatro tamanhos.
Zoom real de 200%, leitor de tela e backend real não foram exercitados.

## Limites e rollback

O recorte não implementa as demais fatias da evolução global. Não existe
`conversationId` no WorkItem: Abrir conversas abre a lista autorizada sem afirmar
que seleciona a conversa da pessoa do cuidado. Não se infere esse vínculo por
nome ou telefone. O teste mobile usa uma conversa sintética sem pessoa vinculada.

Nenhum envio real, banco, migration, provedor, deploy ou ativação foi realizado.
O rollback deste recorte é reverter o patch de frontend e os registros associados,
sem compensação de dados. A versão anterior continua na base citada.

Próximo gate da entrega: CI de produto e revisão do PR no SHA candidato,
antes de merge/publicação. A autorização de desenvolver
este recorte não atesta o funcionamento com backend ou provedores reais.
