# E1–E3: evidence store de consentimento em laboratório

Base: `d0df9a4feaf9a234705cea256858906de528f834`.
Estado: candidata local em revalidação C; bloqueio de desenho resolvido pela
decisão do controlador, sem ampliar ACL. Aplicação não autorizada.

O [contrato E1](../governance/consent/evidence-store/OPERATIONAL-CONTRACT-v1.md)
fecha o desenho conforme o plano revisado e as decisões/correção do controlador
identificadas como 2026-09-09. Esse registro não altera payload, catálogo,
aprovação humana ou indicadores de elegibilidade.

## Escopo da intent

TENANT: public.consentimento_desafio, public.consentimento_evidencia,
public.consentimento_recibo. Somente essas relações são novas/alteradas.
igrejas/pessoas/ledger são dependências existentes, sem ALTER, backfill ou DML
de domínio pela migration. Sem novo papel global ou SECURITY DEFINER.
RLS ENABLE/FORCE, barreira restritiva GUC app.tenant_igreja_id, grants/revokes
enumerados e FKs compostas vinculam todas as relações à igreja.

Exclusão da Pessoa: ON DELETE CASCADE em desafio→Pessoa,
evidência→desafio e recibo→evidência. A cadeia operacional é removida; o
ledger histórico já sofre cascata e não é modificado. Não há promessa de
prova anonimizada sobrevivente. A alternativa de anonimização da seção 14.1
exige missão posterior com PRD e gate próprios.

Prazos: recusa inicial 5 anos do registro; apresentação abandonada 90 dias
do abandono/expiração; recibo acompanha a evidência confirmada. Expiração do
desafio não renova por retries. Nenhuma rotina viva de expurgo é instalada.

## Recuperação e rollback

FORWARD_COMPENSATION: nenhuma aplicação compartilhada autorizada. Descartar
somente o laboratório próprio após a prova; não DROP de dados reais. Eventual
rollout requer suspensão dos callers, preservação da integridade e migration
compensatória revisada, sem reescrever histórico nem conceder ficticiamente.

## Prova e limites

Prepare-head apenas renderiza candidato, nunca modifica/publica o head
canônico. Testes devem cobrir recusa sem ledger, source/actor/GUC inválidos,
isolamento A/B, cascata A sem afetar B, concorrência, rollback, replay e
reconciliação pós-commit. Registrar resultados reais ao concluir E2/E3.
Não atribuir aos mocks prova PG17 ou aos testes prova de fonte real autenticada.

concedido permanece bloqueado no serviço original; módulo de laboratório sem
caller, worker, runtime, API ou envio. Nenhuma consulta ao cofre. Gates técnicos
e operacionais false; sem push/PR/merge ou banco compartilhado.

## Bloqueio comprovado no replay canônico

Após as 75 migrations e o candidato, authenticated não tem SELECT/UPDATE
em pessoas para cumprir o lock exigido. A intent não amplia essa relação e
o plano veda ampliar privilégios existentes. Não foi concedido acesso no
schema canônico, removido lock ou adotado owner como alternativa.
Testes do laboratório mínimo com grants de fixture não substituem essa prova.
Ver E1-E3-LAB-REPORT.md e seção 9 do contrato para evidência e decisão pendente.

## Decisão C aceita e implementação local autorizada

O controlador aceitou C e rejeitou A, B e C-linha-final. Novo protocolo:
idempotência → desafio novo/FK ou lock de desafio existente → advisory do
stream idêntico ao trigger do ledger → leitura do ledger → evidência/recibo.
Não há lock posterior de Pessoa, outra chave ou outro stream. Falha após
staging exige rollback externo. O serviço não controla o commit.
Pessoas/ledger permanecem dependências sem GRANT, policy ou ALTER novos;
intent mantém as três relações. A limitação do writer antigo no replay puro
é preservada e separada da prova cruzada com pré-condições históricas.
