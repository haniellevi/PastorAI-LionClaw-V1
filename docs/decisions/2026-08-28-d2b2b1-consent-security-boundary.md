# D2B2b1: fronteira de segurança do consentimento

Data: 2026-08-28

Status: integrada e inativa, sem migration, caller ou efeito operacional

Base da implementação: `bce5a9a434077e488cea8baae3e9dd7c7c4ba0f1`

Merge integrado: `74951828f48994622a112d8e59eb978e5fb4f406`

## Contexto

A PR #317 integrou a D2B2a no `origin/main`: HEAD da implementação
`8ba5c988e9169703c923b1f1a3e47d1c427531e1`, merge
`bce5a9a434077e488cea8baae3e9dd7c7c4ba0f1`. O ledger por finalidade está no
código, mas continua inativo, sem caller e sem aplicação em Supabase DEV ou
PROD.

O ledger sozinho não resolve o contrato de consentimento. Uma versão textual,
uma fonte e um instante não demonstram qual aviso foi apresentado, qual
manifestação corresponde àquele aviso nem qual política autorizava o
tratamento. A D2B2a também não decide texto, base jurídica, retenção,
eliminação, tratamento de menores, transferência internacional ou papéis dos
agentes de tratamento.

Essas decisões pertencem ao controlador de cada operação e exigem responsável
humano e validação jurídica ou do encarregado. O código pode exigir que a
decisão exista, esteja vigente e tenha sido aprovada; não pode criar seu
conteúdo nem chamar uma hipótese jurídica de consentimento por conveniência.
Esta decisão é um contrato técnico de contenção, não um parecer jurídico.

## Fontes primárias consideradas

Links oficiais conferidos em 2026-08-28:

- [Lei nº 13.709/2018, texto compilado](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709compilado.htm):
  arts. 5º a 11, 14 a 16, 18, 37 e 46, sobre conceitos, princípios, hipóteses
  de tratamento, consentimento, transparência, dados sensíveis, crianças e
  adolescentes, término, direitos, registros e segurança;
- [Guia Orientativo para Definições dos Agentes de Tratamento e do
  Encarregado](https://www.gov.br/anpd/pt-br/centrais-de-conteudo/materiais-educativos-e-publicacoes/guia_agentes_de_tratamento_e_encarregado___defeso_eleitoral.pdf/%40%40display-file/file):
  o papel de controlador ou operador depende da atuação real em cada operação;
- [Resolução CD/ANPD nº 19/2024](https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd/resolucao-cd-anpd-no-19-de-23-de-agosto-de-2024):
  transferência internacional, mecanismos válidos e transparência.

O repositório não fixa interpretação jurídica definitiva dessas fontes.

## Decisão técnica D2B2b1

A D2B2b1 introduz somente objetos e funções puras para fechar a fronteira antes
de qualquer catálogo ou writer:

1. **Idempotência opaca:** a chave nasce em componente confiável do servidor.
   Telefone, texto de mensagem, ID do provedor, conteúdo pastoral, nome,
   documento e identificador escolhido pelo modelo ou cliente são recusados
   como autoridade ou matéria da chave. Esta fatia não oferece construtor por
   valor nem reidratação: uma prova efêmera liga a chave ao processo que a
   gerou. Retry entre processos continua bloqueado até um recibo durável e
   autenticado provar a origem e reutilizar a mesma chave sem aceitar entrada
   do cliente.
2. **RBAC deny-first:** a ausência de uma capacidade exata nega leitura ou
   escrita. Papel amplo, admin implícito, fonte `painel_autenticado` ou autoria
   do operador não provam manifestação do titular.
3. **Concessão sempre negada:** enquanto o pacote humano e jurídico não existir,
   a política pura e o sink interno recusam `concedido` antes de qualquer I/O,
   ainda que tenant, papel, fonte e chave sejam sintaticamente válidos. O
   ledger continua capaz de representar eventos históricos concedidos para
   projeção, mas não há caminho de escrita concedida nesta fatia.
4. **Retirada não reativa nada:** uma retirada ou opt-out nunca produz nova
   concessão. Limpar o booleano legado `pessoas.optout` não restaura evento
   anterior e não equivale a novo aceite.
5. **Sem decisão pelo LLM:** modelo, prompt, agente, mensagem livre e cliente não
   escolhem finalidade, base jurídica, versão, prova, retenção, capacidade ou
   elegibilidade.
6. **Nenhuma ativação implícita:** não há migration, banco, API, painel,
   webhook, worker, LangGraph, tool, broadcast, envio, deploy ou mudança de
   flag. O contrato não é aplicado em Supabase.
7. **Identidade de painel vinculada:** o sujeito Clerk autenticado deve ser
   idêntico ao `clerk_user_id` persistido no único acesso ativo resolvido pelo
   servidor. Ausência, duplicidade ou divergência esvazia todas as capacidades.

O resultado seguro desta fatia é negar concessões. Ele não declara que uma
operação está juridicamente autorizada.

Os indicadores de conversa atribuída, célula ativa e responsabilidade no
contexto puro ainda são evidência abstrata, sem resource ID próprio. Como não
existe caller, eles não autorizam acesso operacional nesta fatia. Antes de
qualquer wiring, um builder server-side deverá vinculá-los na mesma transação ao
tenant, ator, Pessoa alvo e recurso canônico, ou substituí-los por evidência
estruturada equivalente. Payload, cliente, modelo e argumento de tool jamais
podem preencher esses indicadores.

## Pacote humano e jurídico obrigatório

Antes de catálogo, evidence store ou writer, o responsável humano designado
para a operação, com validação jurídica ou do encarregado, deve aprovar para
cada uma das quatro finalidades:

- identidade e contato do controlador, além da classificação real de
  controlador, operador e suboperadores por operação;
- finalidade específica, operações, dados mínimos, titulares, destinatários e
  compartilhamentos;
- classificação de dados comuns ou sensíveis e hipótese jurídica aplicável,
  sem usar consentimento como rótulo genérico;
- texto exato por canal e idioma, consequências da recusa, direitos e forma
  gratuita e facilitada de retirada;
- evidência mínima de apresentação e manifestação, incluindo a regra para ação
  registrada no painel;
- política de criança, adolescente, idade desconhecida e responsável legal;
- mudança material, vigência, expiração, reaceite e tratamento de recusa;
- retenção e destino de ledger, evidência, mensagens, mídia, transcrição,
  resumo, checkpoint, vetores, logs, dead-letter e backups;
- semântica de opt-out, retirada, pedido de eliminação, legal hold e
  reativação;
- inventário e mecanismo de transferência internacional;
- responsáveis por aprovação, atendimento de direitos, incidentes e revisão
  periódica.

Uma igreja pode aderir a um template de plataforma previamente aprovado, mas a
versão materializada precisa conter os dados do controlador daquela operação.
Admin comum não edita livremente base jurídica, prazo ou texto publicado.

## Contrato futuro, ainda bloqueado

Depois do pacote aprovado, uma missão própria poderá propor catálogo imutável
de avisos, binding por tenant, política de tratamento versionada, desafio
correlacionado, evidência mínima e política de retenção. Linhas publicadas não
serão alteradas; nova redação cria nova versão. `sim` ou `ok` sem desafio
pendente e ligado ao aviso exato nunca será concessão.

Um único avaliador server-side deverá proteger agente, tools, broadcast,
eventos e outbox. Ausência, ambiguidade, expiração, tenant divergente, termo
inativo ou política não aprovada resultam em negação.

## Relação com o legado e o opt-out

- o trigger legado que marca consentimento na primeira mensagem não concede as
  quatro finalidades;
- `consent_records` e `pessoas.consentimento` não serão promovidos por backfill;
- o opt-out global permanece piso conservador para outbound automatizado;
- retirada por finalidade, opt-out e eliminação são fatos diferentes;
- reativação administrativa sem prova da manifestação do titular não concede
  `comunicados`;
- a semântica de atendimento solicitado após opt-out permanece decisão humana
  pendente e não será relaxada nesta fatia.

## Evidência da D2B2a integrada

Na PR #317, os cinco workflows concluíram com `SUCCESS`:

- Backend Tests: `33145078616`;
- E2E Critical: `33145078590`;
- Frontend CI: `33145078637`;
- RLS Integration: `33145078608`;
- Tooling Static Checks: `33145078672`.

Após o merge `bce5a9a434077e488cea8baae3e9dd7c7c4ba0f1`, os cinco workflows também
concluíram com `SUCCESS`:

- Backend Tests: `33145205844`;
- E2E Critical: `33145205869`;
- Frontend CI: `33145205852`;
- RLS Integration: `33145205864`;
- Tooling Static Checks: `33145205854`.

A PR gerou Preview e o merge gerou deployment frontend Vercel automático
classificado como Production. Essa evidência prova o deployment do frontend no
ambiente Production da Vercel; não prova backend, banco, aplicação de migration
ou Supabase, e não houve deploy manual, ativação ou canário.

## Evidência da D2B2b1 integrada

O recorte focal D2B2b1 e suas fronteiras adjacentes passou em 1.114 de 1.114
testes. A suíte RLS completa passou em 288 de 288 contra PostgreSQL 17
descartável, sem falhas ou skips. A suíte offline integral passou no workflow
Backend Tests. O PostgreSQL temporário não era Supabase DEV ou PROD e foi
removido ao final da validação.

A PR #318, HEAD `ede4797003e044f582da9f9a3ab86554f708a73a`, foi integrada no
merge `74951828f48994622a112d8e59eb978e5fb4f406`. Os cinco workflows da PR
concluíram com `SUCCESS`: Backend Tests `33147247668`, E2E Critical
`33147247632`, Frontend CI `33147247672`, RLS Integration `33147247645` e
Tooling Static Checks `33147247624`. Os cinco pós-merge também concluíram com
`SUCCESS`: Backend Tests `33147433974`, E2E Critical `33147434002`, Frontend
CI `33147433944`, RLS Integration `33147433941` e Tooling Static Checks
`33147433956`.

A PR gerou Preview automático, deployment `6136583334`, e o merge gerou
deployment frontend Vercel automático classificado como Production,
`6136622236`, ambos com `SUCCESS`. Essa metadata não prova deploy do backend,
migration, acesso ao banco, Supabase, ativação ou canário.

## Fora do escopo

- texto, base jurídica, prazo ou aprovação definitivos;
- catálogo, evidence store, migration, API, caller ou integração;
- Supabase DEV ou PROD, produção, deploy, agente ou canário;
- D2C, memória, conhecimento, outbox ou notificação;
- Universidade da Vida e Capacitação Destino.

## Próximo gate único

Materializar uma instância governada do
[`template D2B2b2`](2026-08-28-d2b2b2-consent-decision-packet-contract.md) por
igreja, com quatro pacotes independentes, e obter o atestado do dono factual, a
revisão de privacidade ou do encarregado, a revisão jurídica quando designada e
a decisão final do representante autorizado do controlador, todos vinculados
ao digest exato de cada pacote. Catálogo,
writer, Supabase e D2C permanecem bloqueados até esse gate ser concluído.
