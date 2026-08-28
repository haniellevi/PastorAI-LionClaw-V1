# D2B2a: ledger de consentimento por finalidade

Data: 2026-08-28

Status: candidata inativa, aguardando validação e integração

Baseline: `3d5c1099734f5f7da28fc84c6d6bf42f7b57a876`

## Contexto

A arquitetura WhatsApp-first aprovou quatro consentimentos independentes. O
estado legado, formado por `consent_records`, `pessoas.consentimento` e pelo
opt-out global, não representa concessão separada por finalidade e não pode ser
promovido por inferência.

A D2B2a cria somente a base persistente e interna do novo contrato. Ela não
autoriza coleta, comunicação, ação pastoral ou envio, não muda o LangGraph e
não conecta nenhum caller.

## Decisão

### Ledger append-only

A fonte canônica candidata é
`public.consentimento_finalidade_evento`, um ledger append-only por igreja,
Pessoa e finalidade. Cada evento registra:

- `finalidade`: `atendimento_solicitado`, `cuidado_pastoral`,
  `tarefas_operacionais` ou `comunicados`;
- `estado`: `concedido` ou `retirado`;
- `versao_termo`, sem reutilizar o nome legado `termo_versao`;
- `fonte`: `whatsapp_inbound` ou `painel_autenticado` na versão 1;
- `registrado_por_app_user_id`, no INSERT inicial necessariamente nulo para
  `whatsapp_inbound` e obrigatório para `painel_autenticado`;
- `chave_idempotencia`, `sequencia` e `registrado_em` gerado no servidor.

O registro não guarda texto de mensagem, telefone, nome, documento, conteúdo
pastoral ou payload livre. A relação composta com Pessoa e, quando aplicável,
com o operador impede reassociação entre igrejas.

Uma exclusão referencial posterior do AppUser pode anonimizar o operador por
`ON DELETE SET NULL`, preservando o evento no histórico.

A projeção interna de cada finalidade é uma entre `ausente`, `concedido`,
`retirado`, `reaceite_necessario` e `bloqueado_optout_global`. O evento de maior
sequência determina o fato registrado; versão de termo divergente rebaixa uma
concessão para `reaceite_necessario`, e opt-out prevalece como
`bloqueado_optout_global`.

### Ordem e idempotência

`chave_idempotencia` é única dentro do tenant. Repetir a mesma intenção não
cria outro evento; reutilizar a chave com conteúdo divergente falha fechado.

`sequencia` é monotônica dentro do stream
`(igreja_id, pessoa_id, finalidade)`. Um trigger de banco calcula a próxima
sequência sob advisory lock transacional do próprio stream. A unicidade do
stream permanece a barreira final contra corrida. O lock é liberado no commit
ou rollback e nenhuma chamada externa ocorre dentro dessa transação.

Não existe UPDATE ou DELETE de domínio para corrigir histórico. Uma mudança de
estado produz um novo evento. Cascatas de chaves estrangeiras continuam sendo
ações de integridade do ciclo de vida da Pessoa ou igreja, não writers comuns
do ledger.

### Tenant, RLS e privilégios

A tabela fica em `public`, com RLS habilitada e forçada. A barreira de tenant é
restritiva e aceita somente o UUID fixado pelo backend em
`app.tenant_igreja_id` na mesma transação. JWT, claim ou
`public.current_igreja_id()` sem esse GUC não liberam acesso.

O contrato revoga privilégios amplos de `PUBLIC`, `anon`, `service_role` e
`agent_runtime`. A role `authenticated` recebe apenas SELECT e INSERT nas
colunas de entrada necessárias. UPDATE, DELETE e TRUNCATE não são concedidos.
Policies separadas permitem SELECT e INSERT somente para o tenant do GUC; RLS
não substitui ACL nem autorização de aplicação.

Owner e `postgres` continuam sendo limites operacionais por poderem contornar
RLS. Eles não pertencem ao caminho normal da aplicação.

### Domínio e serviço interno

A candidata inclui migration imperativa, modelo ORM
`ConsentimentoFinalidadeEvento`, tipos e projeções de domínio e os serviços
internos `append_purpose_consent_event` e
`load_purpose_consent_snapshot`. O writer valida tenant, Pessoa, finalidade,
estado, fonte, versão do termo, operador e idempotência antes de persistir. A
projeção considera termo desatualizado como ausência de concessão vigente até
novo aceite e mantém o opt-out global prevalente.

Nenhuma API, router, tela, worker, tool, node, fila ou webhook chama esse
serviço nesta fatia. A existência de `whatsapp_inbound` e
`painel_autenticado` no contrato não habilita writers desses canais.

## Relação com legado e opt-out

- Não há backfill do consentimento geral para as quatro finalidades.
- `consent_records` e `pessoas.consentimento` permanecem legados até uma missão
  de transição aprovada.
- Ausência de evento novo significa ausência de concessão daquela finalidade.
- O opt-out global continua prevalecendo sobre qualquer evento `concedido` e
  bloqueia os envios alcançados por sua política.
- O ledger registra evidência; ele não é, isoladamente, autorização para uma
  tool, mensagem ou efeito externo.

## Bloqueios antes de qualquer writer

Os seguintes contratos precisam de aprovação jurídica e operacional antes de
conectar WhatsApp, painel ou outro caller:

1. texto apresentado à pessoa para cada finalidade e versão;
2. base jurídica e prova exigida para cada finalidade;
3. prazo de retenção, expiração e política de nova versão;
4. papéis e capacidades autorizados a registrar pelo painel;
5. semântica de retirada, opt-out e eliminação dos dados relacionados;
6. observabilidade sem PII nem conteúdo pastoral.

Enquanto esses pontos estiverem abertos, nenhum writer de canal e nenhum
ambiente compartilhado podem ser habilitados.

Esses contratos formam a fatia obrigatória `D2B2b`, que sucede a fundação
inativa `D2B2a` e precede qualquer trabalho `D2C`. A `D2B2b` deve fechar termos
e versões recuperáveis, base jurídica e prova, retenção e eliminação, RBAC de
leitura e escrita e callers server-side seguros. O caller gerará
`chave_idempotencia` opaca no servidor e rejeitará telefone, conteúdo de
mensagem ou identificador pastoral como parte dessa chave.

## Verificação obrigatória

Antes de integrar a candidata:

- aplicar a migration em PostgreSQL 17 descartável, inclusive uma segunda
  aplicação conforme o contrato de idempotência do projeto;
- provar isolamento entre dois tenants, GUC ausente ou inválido, pool
  reutilizado e tentativa por JWT sem GUC;
- provar ACL mínima, append-only, FKs compostas, sequência concorrente e replay
  de idempotência;
- executar as suítes focais, offline e RLS aplicáveis;
- obter revisão independente de arquitetura, segurança e código.

Teste verde em ambiente descartável não prova aplicação no Supabase DEV ou
PROD e não autoriza fazê-la.

Na candidata local, o módulo de contrato, incluindo a aplicação do SQL
inalterado duas vezes em `public`, passou em 11 de 11 no PostgreSQL 17 e na
imagem Supabase PG17. A suíte RLS completa passou em 288 de 288 e os testes
offline D2B2a, em 32 de 32. A suíte offline integral continua como gate
obrigatório do workflow Backend Tests antes do merge; nenhuma dessas provas
implica aplicação em ambiente compartilhado.

## Rollback e compensação

Durante a validação, o rollback é descartar integralmente o PostgreSQL
temporário. Como não existe backfill nem caller, nenhum dado de domínio precisa
ser revertido nesta fatia.

Se uma missão futura aplicar a migration em ambiente compartilhado, remoção do
ledger ou de seu histórico não será tratada como rollback automático. Qualquer
correção seguirá por migration compensatória forward-only, com backup,
inventário de linhas e gate nominal próprios.

## Fora do escopo

- backfill ou migração do legado;
- textos jurídicos, base legal e retenção definitivos;
- API, painel, webhook, LangGraph, worker, tool ou notificação;
- Supabase DEV ou PROD, deploy, ativação do agente ou canário;
- memória privada, conhecimento institucional ou propostas D2C;
- Universidade da Vida e Capacitação Destino.

## Próximo gate único

Revisar e integrar a PR candidata D2B2a somente depois de PostgreSQL
descartável, suítes aplicáveis e revisões independentes concluírem com `GO`.
Aplicação em Supabase DEV ou PROD exige outro gate nominal posterior.
