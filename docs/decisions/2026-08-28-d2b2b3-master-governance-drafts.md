# D2B2b3A: rascunhos governados no Console Master

Data: 2026-08-28

Status: `APPROVED_FOR_IMPLEMENTATION / DRAFT_ONLY`

Baseline documental de entrada:
`f249408f5bf7a14c0badb91d705e13cf4d1f7ea1`

## Decisao

O Admin Master autenticado no Console da plataforma pode preparar e manter, por
igreja, um rascunho independente para cada uma das quatro finalidades
canonicas:

1. `atendimento_solicitado`;
2. `cuidado_pastoral`;
3. `tarefas_operacionais`;
4. `comunicados`.

O Console e a superficie administrativa para organizar esse trabalho. Nenhum
e-mail, inclusive o do operador que iniciou a configuracao, integra o contrato
de autorizacao, o schema ou o codigo. A identidade do Master vem da sessao
autenticada e da allowlist server-side ja existente; igreja e ator sao
vinculados pelo backend, nunca por um valor de autoridade aceito do formulario.

Esta decisao autoriza somente a implementacao de rascunhos. Ela nao materializa
aprovacao humana ou juridica, nao constitui parecer e nao concede autoridade ao
runtime.

## Separacao entre preparar e decidir

O Master pode registrar e atualizar informacoes administrativas e fatos ainda
nao atestados para que os responsaveis da igreja executem o fluxo governado
posterior. Cada registro permanece explicitamente
`DRAFT_NOT_APPROVED`, mesmo quando todos os campos editaveis estiverem
preenchidos.

O Master nesta superficie nao pode:

- escolher hipotese juridica para dados comuns ou sensiveis;
- declarar que a operacao depende de consentimento;
- decidir a aplicabilidade das regras para criancas e adolescentes;
- atestar fatos, emitir parecer, aprovar, rejeitar ou mudar estado;
- agir como dono factual, encarregado, revisor de privacidade, juridico ou
  representante autorizado do controlador;
- preencher, importar ou fabricar registros nominais de aprovacao;
- calcular ou registrar digest como se fosse conteudo atestado;
- liberar catalogo, evidence store, writer ou qualquer caller downstream de
  aprovacao, ledger ou runtime.

Uma mesma pessoa somente podera desempenhar outro papel em etapa futura quando
essa designacao existir de forma autentica, nominal e auditavel no fluxo da
igreja. O papel de Admin Master, isoladamente, nunca implica essa designacao.

## Schema fechado do rascunho operacional

O rascunho D2B2b3A e material preparatorio separado do `decision_payload`
imutavel do pacote aprovado. Ele aceita somente oito campos opcionais de texto:

1. agentes reais do processamento;
2. operacoes e dados minimos;
3. avaliacao operacional da sensibilidade, sem classificacao juridica;
4. necessidade operacional;
5. sistemas e destinatarios;
6. inventario de retencao e descarte, sem aprovacao da politica;
7. instrucoes operacionais;
8. questoes em aberto.

Cada campo tem limite de 4.000 caracteres e o conjunto, limite de 16.000. Texto
vazio e normalizado para nulo e caracteres de controle nao permitidos sao
recusados. Chaves adicionais falham fechadas. Uma etapa humana posterior deve
revisar e transpor o material aplicavel para uma nova versao governada do
`decision_payload`; a aplicacao nao promove o rascunho automaticamente.

## Superficies permitidas nesta fatia

A D2B2b3A pode adicionar somente:

- migration imperativa versionada para persistencia de rascunhos;
- ORM e servico interno limitados ao estado de rascunho;
- API autenticada do Console Master para consultar o estado, inicializar os
  quatro rascunhos vazios e atualizar uma finalidade em uma igreja
  explicitamente selecionada;
- aba de governanca na pagina da igreja no Console, com quatro finalidades e o
  aviso permanente `RASCUNHO, NAO APROVADO`;
- auditoria administrativa com metadados minimos, sem copiar o payload do
  pacote, parecer, contato pessoal ou conteudo restrito para o log.

A disponibilidade da superficie usa
`PURPOSE_CONSENT_GOVERNANCE_DRAFTS_ENABLED`, com default `false` em todos os
ambientes. Essa flag libera somente o workspace de rascunhos e nunca implica
aprovacao, catalogo, writer, agente ou efeito externo.

A migration faz parte do artefato de codigo e deve ser validada em PostgreSQL
17 descartavel. Ela nao autoriza aplicacao em Supabase DEV, Supabase PROD ou
outro banco compartilhado.

## Contrato de persistencia e concorrencia

Cada igreja possui no maximo um envelope ligado por chave estrangeira e
unicidade a `igreja_id`. O envelope contem exatamente as quatro chaves de
finalidade, sem chaves adicionais, e uma revisao positiva independente para
cada rascunho. A finalidade vem da rota tipada; o backend revalida igreja,
Master e escopo antes da leitura ou escrita. O ator gravado e o identificador
interno derivado da sessao, nunca um e-mail fornecido pelo cliente.

O update de uma finalidade exige a revisao esperada desse rascunho e incrementa
as revisoes correspondentes no servidor sob lock do envelope. Uma revisao
obsoleta falha sem sobrescrever trabalho concorrente. Nao existe delete na API
desta fatia. O payload aceita apenas campos conhecidos, tipados e limitados;
chaves arbitrarias, campos de autoridade, estados de ciclo e registros nominais
sao recusados.

Se a tabela ficar em schema exposto, a migration deve habilitar e forcar RLS e
revogar privilegios de `PUBLIC`, `anon`, `authenticated`, `service_role` e
`agent_runtime`. Nao existe policy de Data API para esses rascunhos. O acesso
ocorre exclusivamente pelo caminho privilegiado e auditado do Console Master,
com tenant explicito. RLS e privilegios sao barreiras independentes.

A candidata inativa nao prova esse wiring. Antes de qualquer aplicacao em banco
compartilhado, ativacao da flag ou wiring do backend compartilhado, um preflight
separado deve comprovar, sem expor a credencial, que o `DATABASE_URL` do plano
Master usa o owner esperado com acesso efetivo sob `FORCE RLS` ou um papel
explicitamente autorizado com `BYPASSRLS`. Esse requisito nao autoriza nenhuma
dessas acoes.

## Contrato da interface

A tela deve explicar, em linguagem operacional, que o Master prepara somente o
rascunho operacional e que os responsaveis designados pela igreja revisam esse
material, formam o pacote governado e o atestam e aprovam em etapa posterior.
Completude de rascunho e apenas uma ajuda de preenchimento e nao pode usar
rotulos como aprovado, valido, consentido, apto ou liberado.

Campos fora da competencia do Master aparecem bloqueados ou ficam ausentes da
edicao. A interface nao oferece botoes de atestar, aprovar, registrar parecer,
vincular assinatura, mudar status, publicar, ativar ou enviar.

## Invariantes que permanecem fechados

- `controller_approved=false`;
- `human_packet_complete=false`;
- `catalog_ready=false`;
- `writer_eligible=false`;
- nenhum evento `concedido` e criado;
- nenhum estado do ledger D2B2a e alterado;
- nenhuma configuracao, gate ou credencial e alterada;
- nenhum payload e lido pelo WhatsApp, webhook, worker, LangGraph, tool ou
  agente;
- nenhum acesso e concedido ao painel do tenant nesta fatia;
- nenhuma migration e aplicada em ambiente compartilhado;
- nenhum deploy manual ou do backend, ativacao ou canario e executado;
- D2C, memoria, conhecimento e outbox continuam bloqueados;
- Universidade da Vida e Capacitacao Destino permanecem fora da missao atual.

## Criterios de aceite da PR

1. O schema e o backend falham fechados para tenant ausente, finalidade
   invalida, Master nao autorizado, campo proibido e revisao obsoleta.
2. Testes com ao menos duas igrejas comprovam que um rascunho nunca aparece ou
   e alterado pela selecao de outro tenant.
3. A migration e idempotente, explicita RLS, grants e revokes e passa em
   PostgreSQL 17 descartavel sem acessar Supabase compartilhado.
4. A API nao aceita e-mail, identidade, papel, igreja, status, aprovacao ou
   digest como autoridade enviada no payload.
5. A tela preserva o aviso de rascunho e nao oferece transicao humana ou
   operacional.
6. A auditoria registra igreja, finalidade, ator, revisao e instante, sem
   copiar conteudo do pacote.
7. Testes e documentacao nao usam PII ou dados reais.

## Itens explicitamente posteriores

Uma nova decisao e uma nova PR serao necessarias para o fluxo nominal de
atestado, revisao de privacidade, revisao juridica quando designada e aprovacao
final do controlador. Continuam posteriores tambem catalogo imutavel, evidence
store, digest e recibos governados, writers, WhatsApp, runtime do agente e
qualquer ambiente compartilhado.

A abertura desta PR pode gerar Preview automatico, e o merge pode gerar
deployment frontend Production automatico pela integracao Vercel do
repositorio. O merge exige revisao humana consciente desse efeito. Isso nao
autoriza deploy manual ou do backend, migration em ambiente compartilhado,
mudanca de flag, runtime, ativacao ou canario e nao constitui evidencia de que
algum deployment desta candidata ja ocorreu.

## Proximo gate unico

Revisar e integrar a PR D2B2b3A draft-only, comprovando migration em
PostgreSQL 17 descartavel, isolamento entre tenants, concorrencia por revisao e
ausencia de caminhos de aprovacao ou runtime. Nao aplicar a migration em
Supabase DEV ou PROD como parte desse gate.
