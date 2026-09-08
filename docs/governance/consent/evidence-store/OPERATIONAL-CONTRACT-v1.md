# Evidence store operacional — contrato E1 v1

Estado: E1/E2/E3 C concluídas em laboratório local; FREEZE, sem liberação operacional.

Fatia versionada da PR #388: código isolado, testes não-PG e contratos.
Migration, dois testes PG17 e head candidato permanecem congelados localmente,
fora desta árvore versionada, e preservados no commit completo `c48a62f`.
Publicação do catálogo e provas de banco exigem o gate de transição separado;
este contrato não afirma que as três novas tabelas existem no schema integrado.
Base de revisão: `d0df9a4feaf9a234705cea256858906de528f834`.
Este contrato não concede consentimento, não é caller e não autoriza aplicação.

## 1. Fronteira e autoridade

Primeira fatia: adulto autenticado agindo em nome próprio. PRESENTATION e
REFUSE_INITIAL são os únicos eventos persistíveis em E1–E3. ACCEPT e WITHDRAW
são reconhecidos e negados antes de qualquer escrita neste novo módulo.
O caminho existente de retirada permanece intacto. Não escrever no ledger,
nem direta nem indiretamente; append_purpose_consent_event continua negando
concedido. E4 terá revisão separada, sem antecipar seu writer.

Tenant, Pessoa, ator, recurso, sessão, idade adulta, finalidade, versão e
âncoras vêm de adapter server-owned revalidado dentro da UoW. Entrada bruta,
UUID, DTO, hash ou booleano não é credencial. A implementação de laboratório
recebe somente uma fonte sintética explícita; não fornecer factory operacional,
rota HTTP ou import no runtime. Sem fonte, negar. Fixtures não aprovam igreja.

Uma observação de apresentação autentica origem/correlação; não prova leitura
nem vontade. A manifestação deve referenciar a apresentação da mesma tupla e
o controle explícito autenticado. Idade desconhecida, representante, tenant
cruzado ou fonte revogada negam antes da escrita. Não consultar o cofre.

## 2. Relações e shape fechado proposto

Intent TENANT: somente public.consentimento_desafio,
public.consentimento_evidencia e public.consentimento_recibo.
Pessoa, igreja, AppUser e ledger são dependências de leitura/FK, sem ALTER.
A migration histórica já cria UNIQUE (igreja_id,id) no ledger; não é preciso
alterá-lo para antecipar E4. Não publicar migration/head antes de E3 validada.

Todos os identificadores abaixo são UUIDs não nulos; timestamps são UTC,
serializados RFC3339 com precisão fixa de microssegundos. Hashes são SHA256
hexadecimal minúsculo, 64 caracteres. Nenhum campo livre, JSON arbitrário,
telefone, nome, documento, token, mensagem ou hash de telefone é aceito.

| Relação | Colunas obrigatórias | Colunas condicionais |
|---|---|---|
| consentimento_desafio | id, igreja_id, pessoa_id, finalidade, package_id, package_version, content_digest, catalog_entry_digest, notice_text_digest, binding_id, interaction_id, canal, idioma, criado_em, expira_em, estado | encerrado_em: nulo em OPEN, obrigatório nos estados terminais |
| consentimento_evidencia | id, igreja_id, desafio_id, tipo, chave_idempotencia, registrado_em, evidence_digest | apresentacao_id e acao: ambos nulos em PRESENTATION; ambos obrigatórios em MANIFESTATION |
| consentimento_recibo | id, igreja_id, evidencia_id, chave_idempotencia, registrado_em, acao, schema_version | nenhuma |

Tipos fechados: finalidade = atendimento_solicitado/cuidado_pastoral/
tarefas_operacionais/comunicados; canal = WHATSAPP/PANEL;
idioma = pt-BR; package_version = identificador ASCII versionado, sem texto
livre; package_id UUID; estado = OPEN/CONSUMED/EXPIRED/CANCELLED;
tipo = PRESENTATION/MANIFESTATION; acao persistida = REFUSE_INITIAL;
schema_version de recibo = consent-receipt/lab-v1. Rejeitar extras e coerção
de booleano/string/número. ACCEPT/WITHDRAW não são valores persistíveis E3.

Chaves: PK id e UNIQUE (igreja_id,id) em cada relação; UNIQUE
(igreja_id,chave_idempotencia) em evidência e recibo. UNIQUE
(igreja_id,desafio_id,tipo) limita apresentação e manifestação a uma de cada.
UNIQUE (igreja_id,binding_id,interaction_id) no desafio impede mudar chave
para reutilizar interação. UNIQUE (igreja_id,evidencia_id) no recibo.

FKs de domínio compostas: desafio→Pessoa (igreja_id,pessoa_id),
evidência→desafio (igreja_id,desafio_id), evidência→apresentação
(igreja_id,desafio_id,apresentacao_id), recibo→evidência (igreja_id,evidencia_id).
Desafio→igrejas por igreja_id. Checks/triggers confirmam que apresentação e
manifestação têm o MESMO desafio; recibo aponta para MANIFESTATION e repete
ação/chave/instante. Não basta a FK indicar que a linha existe.

Pessoa/finalidade/digests/canal/versão são herdados do desafio imutável, não
copiados em colunas editáveis divergentes. Para leitura autorizada e digest,
o envelope inclui a tupla completa resolvida; JOIN sempre tenant-bound.
Ator é a própria Pessoa. A referência opaca binding_id não armazena AppUser
ou dado pessoal e não autentica por si: exige fonte independente vigente.

## 3. Retenção e exclusão: decisões recebidas do controlador

Fonte: instrução do controlador identificada como 2026-09-09 nesta conversa,
complementando a seção 14 do pacote. Registro de decisão fornecida, não parecer
jurídico independente, nova assinatura ou alteração do payload aprovado.

| Caso | Início da contagem | Prazo máximo / destinação |
|---|---|---|
| Evidência vinculada a evento do ledger (aceite/retirada, etapa futura) | Último entre retirada, expiração, substituição ou encerramento do vínculo, conforme 14.1 | 5 anos; excluir com prova de descarte |
| REFUSE_INITIAL, sem evento no ledger | Instante do registro da recusa | 5 anos; excluir com prova de descarte |
| PRESENTATION sem manifestação | Instante de abandono ou expiração do desafio aplicável | 90 dias; excluir com prova de descarte |
| Recibo de recusa | Instante da recusa confirmada, não da reemissão do recibo | Mesmo vencimento da evidência de recusa |
| Recibo de aceite/retirada (etapa futura) | Marco aplicável ao evento correspondente no ledger | Mesmo vencimento da evidência confirmada |

Retry, replay ou reemissão não reiniciam a contagem. Os 180 dias de não
insistência são regra comportamental distinta; 30 minutos continuam sendo
validade técnica do desafio. Não criar evento no ledger para datar a recusa.
Aceite/retirada constam somente da matriz futura, sem writer E1–E3.

Decisão de exclusão das novas tabelas aceita, sem reabertura em E2–E3:
FK composta desafio→Pessoa ON DELETE CASCADE; evidência→desafio ON DELETE
CASCADE; recibo→evidência ON DELETE CASCADE. Todas incluem igreja_id.
A exclusão da Pessoa remove as três superfícies operacionais, mesmo antes
do vencimento ordinário. A futura intent declara as três relações, esse
comportamento e os testes A/B; não altera relação do ledger ou pai.

### Trade-off de exclusão confirmado pelo controlador

Correção recebida em 2026-09-09: manter o ledger inalterado, sem alegar prova
anonimizada após exclusão da Pessoa. Na base d0df9a4, a migration
`backend/migrations/20260828_045213_d2b2_consentimento_finalidade_evento.sql`
define `consentimento_finalidade_evento_tenant_pessoa_fkey` e
`consentimento_finalidade_evento_igreja_fkey` com ON DELETE CASCADE.
O modelo `ConsentimentoFinalidadeEvento` espelha essa regra. O trigger
append-only permite ações referenciais aninhadas, não cria cópia anonimizada.
SET NULL aplica-se ao operador AppUser, não à Pessoa titular do evento.

Excluir a Pessoa remove a cadeia completa: desafio, evidência, recibo e
eventos do ledger. Recusa inicial sequer cria evento no ledger. A alternativa
de preservação anonimizada da seção 14.1 (excluir OU anonimizar) não está
implementada: missão futura separada, com PRD e gate próprios. Não criar
ledger paralelo, modificar FK/trigger histórico ou prometer prova sobrevivente.
Esse trade-off é consciente e não será reaberto em E2–E3.

## 4. Ordem transacional e reconciliação

Uma operação por transação externa, tenant-scoped READ COMMITTED, sem fallback
privilegiado. Validar current role authenticated e GUC app.tenant_igreja_id
canônico igual ao tenant antes de ler domínio; ausente/malformado nega.
Nenhum SET de correção pelo serviço. Deadline e fonte revalidados após locks.

1. Advisory transacional da chave tenant usando exatamente o namespace
   purpose-consent-idempotency:<igreja_id>:<chave> e hashtextextended(...,0).
2. Desafio novo: inserir desafio antes do advisory de stream, obtendo a
   proteção referencial da Pessoa por sua FK. Desafio existente: bloquear
   (igreja_id,id) FOR UPDATE e reler. Não executar SELECT FOR UPDATE em Pessoa.
   ON CONFLICT sem inserção não comprova proteção: recuperar e bloquear o
   vencedor, comparar identidade/vínculo e rejeitar divergência antes do
   stream. Se o vencedor desaparecer, negar; nunca reinserir após o stream.
3. Advisory transacional do stream, exatamente como o trigger histórico:
   hashtextextended(igreja_id::text || ':' || pessoa_id::text || ':' || finalidade, 0).
4. Revalidar fonte/relógio; consultar ledger, apresentação e resultado no mesmo
   tenant/desafio. Stream ausente continua sendo requisito da recusa inicial.
5. Persistir evidence/receipt ou recuperar replay, e transição OPEN→CONSUMED.

Não adquirir posteriormente lock de Pessoa, outra chave ou outro stream.
Uma operação lógica por transação externa; o adapter recusa mudança de chave
ou stream na mesma transação. Não combinar este writer com outro writer que
introduza locks fora da ordem. E1–E3 adquirem o advisory, nunca INSERT no ledger.
O ledger permanece byte-pinado e usa sua ordem histórica. Esta mudança não
libera seu writer antigo no replay sem as pré-condições ACL históricas.

Serviço faz flush, nunca begin/commit/rollback externo ou chamada de provedor.
REFUSE_INITIAL exige stream ausente sob advisory de stream; stream existente não
é reclassificado como recusa inicial. Mesmo replay exige autoridade de leitura.
Replay exato retorna identidade original; qualquer intenção divergente nega.
Sem renovar deadline, criar nova chave ou produzir duplicata para resolver erro.
Qualquer falha após inserir o desafio exige rollback integral pelo chamador;
não capturar a exceção e commitar staging parcial. A criação da referência
precede o stream para impedir o ciclo ledger(Pessoa→stream) versus
evidence(stream→Pessoa). Exclusão usa Pessoa→desafio; após o stream o evidence
store não volta a buscar locks de Pessoa. Prova limitada aos writers conformes,
não a SQL arbitrário ou transações compostas fora deste contrato.

Resultado de staging não é recibo confirmado. Observação independente em
nova transação lê evidence/receipt/desafio e valida envelope/chave/estado.
O adapter exige READ ONLY e ausência de xid de escrita atribuído, impedindo
usar a transação de staging como observação independente. Não se presume que
PostgreSQL permita converter para READ ONLY uma transação após escrita.
Falha ou commit ambíguo = UNKNOWN; ausência = NOT_FOUND, nunca autorização
de retry cego. Reinício não reidrata a classe opaca do ledger por string.
Não há delivery status nem envio nesta fatia.

## 5. Integridade e ACL

Canonicalização operacional versionada: objeto fechado com nomes ASCII,
valores string ASCII, booleanos/nulos e sem números, JSON UTF8 compacto,
chaves ordenadas. evidence_digest cobre a evidência (sem o próprio digest)
e toda a tupla imutável do desafio, inclusive seus três digests de conteúdo;
estado/encerramento mutáveis do desafio ficam fora. Timestamps
e UUIDs em forma canônica; testar vetores e alterações de todos os campos.
Essa restrição é subconjunto explícito, não implementação JCS geral nem
recálculo do content_digest real. Hash consistente não prova autenticidade.

RLS ENABLE/FORCE e policy restritiva por GUC estrito em todas as relações;
policies permissivas separadas de SELECT/INSERT e UPDATE de transição.
Authenticated: SELECT/INSERT de colunas enumeradas; UPDATE somente estado e
encerrado_em do desafio. Sem UPDATE evidence/receipt, DELETE ou TRUNCATE.
Revogar PUBLIC/anon/service_role/agent_runtime. Nenhum papel global novo,
SECURITY DEFINER ou abertura de API. Triggers invoker, search_path fixo,
EXECUTE não público. Owner/BYPASSRLS não representam o aplicativo.

## 6. Matriz de ameaças e provas exigidas

| Ameaça | Barreira | Prova E2/E3 |
|---|---|---|
| Tenant/ator/fonte forjados | Fonte revalidada + GUC + RBAC + FK composta | Dois tenants, recurso cruzado e fonte inválida |
| UUID/DTO tomado por autoridade | Adapter independente, default deny | Ausência, objeto forjado, flags fechadas |
| PII/raw payload | Shape fechado, enums, campos sem texto livre | Extras sensíveis e erros sanitizados |
| Entrega tomada por aceite | PRESENTATION sem ação; ACCEPT bloqueado | Zero concedido e zero chamada ledger |
| Recusa sobre concessão existente | Stream consultado sob advisory comum ao trigger | Conflito, sem reclassificação |
| Replay/corrida | Chave tenant + desafio/FK antes do stream + uniques | Threads/processos, chaves iguais/diferentes |
| Expiração durante espera | Relógio/fonte revalidados após lock | Expiração, fonte revogada, sem extensão |
| Commit parcial/ambíguo | Transação externa + observação independente | Rollback, desconexão e restart |
| Mutação/exclusão silenciosa | ACL/trigger + ciclo explicitamente aprovado | UPDATE/DELETE/TRUNCATE e ciclo dos pais |
| Privilégios indevidos | Grants enumerados, sem owner fallback | Roles, GUC ausente/malformado, cross-tenant |

## 7. Rollback, aceite e limites

Laboratório: descartar apenas recursos próprios, dados inteiramente sintéticos.
Futuro rollout compartilhado: suspender callers, preservar provas e corrigir
aditivamente; nunca DROP de prova como rollback rápido. Operação compartilhada
exige política de exclusão/conservação e testes próprios previamente aprovados.

E1 fechada com prazos e cascata decididos, incluindo o comportamento real do ledger.
E2/E3 exigem testes realmente executados, não a matriz acima.
Os artefatos executáveis de laboratório e seus resultados ficam registrados
em E3-STRATEGY-C-REPORT.md (C) e E1-E3-LAB-REPORT.md (histórico);
não constituem implementação operacional liberada.
human_packet_complete=false, catalog_ready=false, writer_eligible=false,
operational_authorization=false e next_stage_authorized=false permanecem.

## 8. Registro da continuação

Registro histórico da entrega E1; resultados posteriores E2/E3 C em
[E3-STRATEGY-C-REPORT.md](E3-STRATEGY-C-REPORT.md): 1.288 testes verdes,
incluindo 19 PG17 declarados, sem skips. Somente laboratório descartável.

EXECUTADO: fetch nominal da base, leitura local do plano/pacote/ledger e
rascunho deste contrato. Nenhuma consulta a banco ou cofre.
OBSERVADO: controlador corrigiu a premissa; ledger também sofre cascata e
permanecerá intacto. A leitura local não é consulta ao banco vivo.
INDISPONÍVEL nesta entrega E1: prova E2/E3, a registrar após execução.

A revisão de ciclo de vida foi atendida pela correção nominal do controlador.
E2/E3 locais autorizadas nesta ordem; nenhum efeito operacional autorizado.
Próximo gate humano único: revisão da entrega E2/E3 C, após provas locais;
sem autorização implícita de commit, publicação, aplicação ou envio.

## 9. Dependência ACL constatada no replay canônico

Registro histórico do bloqueio anterior. Decisão posterior do controlador,
identificada como 2026-09-09: C aceita; A, B e C-linha-final rejeitadas.
Nenhum GRANT ou policy novo em pessoas/ledger. A intent mantém somente as
três novas relações. As permissões não são supridas silenciosamente no replay.
O protocolo corrente está na seção 4; os parágrafos abaixo preservam a causa
do bloqueio anterior, não uma solicitação de reabrir a escolha.

No PG17 descartável reconstruído a partir do snapshot privado de d0df9a4,
authenticated não possui SELECT nem UPDATE (nem privilégios de coluna
equivalentes) sobre public.pessoas. SELECT FOR UPDATE exigido pelo lock
de Pessoa é negado. As quatro provas canônicas da UoW falharam nesse ponto;
não foram substituídas por mocks ou grants ocultos para obter sucesso.

Os testes históricos do ledger e o laboratório mínimo criam permissões
nas fixtures; isso não prova que as migrations canônicas forneçam essas
permissões. A seção 7 do plano proíbe ampliá-las nesta fatia, e a intent
atual declara somente as três novas relações. Alterar pessoas, trocar o
papel por owner/service_role ou retirar a serialização não é correção autorizada.

A revisão de acesso foi encerrada pela escolha C, sem ampliar a ACL.
O ledger permanece fora de alteração. O head candidato nunca é autorização
de publicação/aplicação. Resultados C são registrados separadamente no relatório.
