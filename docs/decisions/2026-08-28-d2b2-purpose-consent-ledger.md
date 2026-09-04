# D2B2a: ledger de consentimento por finalidade

Data: 2026-08-28

Status: integrada no código e inativa, sem aplicação em ambiente compartilhado

Baseline de implementação: `3d5c1099734f5f7da28fc84c6d6bf42f7b57a876`

HEAD da implementação: `8ba5c988e9169703c923b1f1a3e47d1c427531e1`

Merge no `origin/main`: `bce5a9a434077e488cea8baae3e9dd7c7c4ba0f1`

## Contexto

A arquitetura WhatsApp-first aprovou quatro consentimentos independentes. O
estado legado, formado por `consent_records`, `pessoas.consentimento` e pelo
opt-out global, não representa concessão separada por finalidade e não pode ser
promovido por inferência.

A D2B2a cria somente a base persistente e interna do novo contrato. A
PR #317 integrou essa fundação no código, mas ela não
autoriza coleta, comunicação, ação pastoral ou envio, não muda o LangGraph e
não conecta nenhum caller. A integração não aplicou a migration em Supabase
DEV, PROD ou outro banco compartilhado.

## Decisão

### Ledger append-only

A fonte canônica integrada e inativa é
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

A fatia integrada inclui migration imperativa, modelo ORM
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

Os seguintes contratos precisam de aprovação humana, jurídica e operacional antes de
conectar WhatsApp, painel ou outro caller:

1. texto apresentado à pessoa para cada finalidade e versão;
2. base jurídica e prova exigida para cada finalidade;
3. prazo de retenção, expiração e política de nova versão;
4. papéis e capacidades autorizados a registrar pelo painel;
5. semântica de retirada, opt-out e eliminação dos dados relacionados;
6. observabilidade sem PII nem conteúdo pastoral.

Enquanto esses pontos estiverem abertos, nenhum writer de canal e nenhum
ambiente compartilhado podem ser habilitados. A D2B2b1 integrada adiciona
apenas uma fronteira pura de segurança, deny-first e sem migration; ela não preenche essas
decisões. O contrato detalhado está em
[`2026-08-28-d2b2b1-consent-security-boundary.md`](2026-08-28-d2b2b1-consent-security-boundary.md).

Essa sequência tem a D2B2b1 integrada e inativa como fronteira pura de
segurança. O gate seguinte é materializar e aprovar o pacote humano e jurídico
por finalidade a partir do
[`template D2B2b2`](2026-08-28-d2b2b2-consent-decision-packet-contract.md).
Somente uma missão posterior pode propor catálogo imutável,
evidência correlacionada, retenção, RBAC e callers server-side seguros. D2C
permanece bloqueada. Um caller futuro deverá gerar `chave_idempotencia` opaca no
servidor e rejeitar telefone, conteúdo de mensagem ou identificador pastoral
como parte dessa chave. A D2B2b1 não permite reidratação por valor: retry entre
processos permanece bloqueado até um recibo durável autenticado provar a origem
e reutilizar a chave sem aceitar material do cliente.

## Verificação concluída antes da integração

A integração exigiu:

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

Antes do merge, o módulo de contrato, incluindo a aplicação do SQL
inalterado duas vezes em `public`, passou em 11 de 11 no PostgreSQL 17 e na
imagem Supabase PG17. A suíte RLS completa passou em 288 de 288 e os testes
offline D2B2a, em 32 de 32. A suíte offline integral passou no workflow Backend
Tests; nenhuma dessas provas implica aplicação em ambiente compartilhado.

A PR #317 concluiu Backend Tests `33145078616`, E2E Critical `33145078590`,
Frontend CI `33145078637`, RLS Integration `33145078608` e Tooling Static
Checks `33145078672` com `SUCCESS`. Depois do merge, os runs `33145205844`,
`33145205869`, `33145205852`, `33145205864` e `33145205854`, respectivamente,
também concluíram com `SUCCESS`. A PR gerou Preview automático, deployment
`6136192331`, e o merge gerou deployment frontend Vercel automático
classificado como Production, `6136214234`; não houve deploy manual ou do
backend nem aplicação em banco compartilhado.

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

## Próximo gate específico daquele recorte de consentimento

Materializar uma instância governada do template por igreja, com quatro
pacotes independentes, e obter o atestado do dono factual, a revisão de
privacidade ou do encarregado, a revisão jurídica quando designada e a decisão
final do representante autorizado do controlador, todos vinculados ao digest
exato de cada pacote. Catálogo, evidence store, writer, Supabase DEV ou PROD e
D2C permanecem bloqueados até esse gate ser concluído.

Esse passo jurídico continua obrigatório no domínio de consentimento, mas não
é o estágio global corrente da frente de migrations. Em 2026-09-03, esse
estágio global é
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`,
restrito ao preflight remoto, push, abertura de PR e observação dos checks do
candidato local `1b299e7`; ele não autoriza merge, banco compartilhado, DEV,
PROD, migration, runner ou alteração de flags.
