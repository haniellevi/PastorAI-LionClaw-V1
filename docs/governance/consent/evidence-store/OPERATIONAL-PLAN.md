# Plano técnico: evidence store operacional de consentimento

Estado: PROPOSTA OFFLINE PARA REVISÃO — NÃO IMPLEMENTADO NESTA MISSÃO.
Base: `08c459982e38eb0340bca2ea663ea7040ab06dfc` (PR #386).
Nenhuma migration, writer, API ou runtime é criado por este documento.
Nenhum pacote, assinatura ou indicador de autorização é alterado.

## 1. Resultado pretendido e definição de pronto

Guardar prova mínima de qual aviso foi apresentado e qual escolha explícita
a pessoa fez, vinculada à igreja, finalidade e versão corretas. Repetições
não podem duplicar eventos; outra igreja não pode ler nem escrever a prova.
O recibo só existe como resultado confirmado depois do commit.

Esta fase estará tecnicamente pronta quando contrato operacional, código
interno, migration catalog-bound, testes unitários e PG17/cross-tenant,
retenção/eliminação, observabilidade e revisão independente tiverem evidência
no mesmo SHA. Isso não autoriza ambiente compartilhado, canais ou envio.
Implantação e habilitação do writer têm critérios adicionais na seção 9.

Fontes:
- [Desenho documental do evidence store](CONTRACT.md).
- [Template e condições de elegibilidade](../d2b2b2-decision-packet.template.json).
- [Pacote de tarefas operacionais](../d2b2b2-decision-packet-tarefas-operacionais.md).
- [Catálogo e sucessão de evidências](../catalog/CONTRACT.md).
- [Ledger D2B2a](../../../decisions/2026-08-28-d2b2-purpose-consent-ledger.md).
- [Fronteira D2B2b1](../../../decisions/2026-08-28-d2b2b1-consent-security-boundary.md).
- `backend/app/services/purpose_consent.py`, em especial
  `append_purpose_consent_event` e `load_purpose_consent_snapshot`.

Os estados históricos DRAFT/SEM APROVAÇÃO nos desenhos originais são limites
daquelas entregas. Não anulam o registro humano integrado posteriormente.
Por outro lado, aprovação do controlador não é consentimento de cada pessoa.

## 2. Escopo e exclusões

Inclui desenho de armazenamento e serviços internos tenant-bound para desafio,
observação de apresentação, manifestação explícita, correlação/idempotência e
recibo durável. Reutiliza o ledger existente; não cria segundo ledger de estado.

Primeira implementação proposta: adulto agindo em nome próprio. Menor, idade
desconhecida ou representação sem vínculo verificável devem ser encaminhados
ao fluxo humano aprovado, sem inferir idade adulta, aceitar consentimento ou
armazenar documentos como atalho. As avaliações anexadas ao catálogo não
implementam esses fluxos. Uma extensão posterior deve tratar menores de forma
específica, sem declarar sua política inaplicável ao produto.

Fora desta implementação inicial: sender Evolution, worker vivo, UI pública
de aceite, OpenAI/BYO, ferramentas de domínio, ativação de AgentConfig,
Asaas/Brevo/broadcast, dados reais em fixtures e aplicação em banco compartilhado.
Interfaces desses canais serão contratos de entrada/saída, não wiring automático.
O atendimento solicitado e tarefas operacionais têm finalidades independentes.

## 3. Separação de componentes e dados

Nomes de tabelas abaixo são propostas, a confirmar na revisão de migration.

| Componente | Dados mínimos propostos | Mutabilidade e restrições |
|---|---|---|
| `consentimento_desafio` | id opaco, igreja_id, pessoa_id, finalidade, catálogo/digest/versão, canal/idioma, correlação e vínculo autenticado opacos, criado_em, expira_em, estado, consumido_em | Identidade e conteúdo imutáveis; somente transição condicional OPEN → CONSUMED/EXPIRED/CANCELLED e timestamp pelo serviço autorizado |
| `consentimento_evidencia` | id, igreja_id/pessoa_id/finalidade, desafio_id, tipo PRESENTATION/MANIFESTATION, ação tipada quando aplicável, aviso e digests, ator/recurso autenticado opacos, horários do servidor, correlação/idempotência e evidence_digest | Append-only, sem JSON livre; PRESENTATION não recebe escolha, MANIFESTATION exige referência à prova anterior |
| `consentimento_recibo` | id, igreja_id, evidência de manifestação, escolha, instante/fuso, canal, versão e chave idempotente opaca | INSERT/SELECT apenas; conteúdo mínimo, sem copiar envelope interno; sem campos que aleguem envio |
| `consentimento_finalidade_evento` (existente) | estado concedido/retirado por stream e termo | Não duplicar ou alterar regras existentes; vínculo transacional à evidência quando a escrita de estado for autorizada |

Colunas e enums exatos, nulabilidade por tipo de evento e versão do schema
operacional serão fechados na etapa E1. O desenho sintético
`consent-evidence/design-v1` permanece imutável e não será silenciosamente
transformado em schema operacional. Aprovação do pacote não será coluna
editável pelo cliente em nenhuma dessas tabelas.

Toda FK de domínio deve incluir igreja_id e o ID referenciado; cada tabela
nova terá chave única composta correspondente. Se o ledger precisar de índice
único composto adicional para FK, declarar explicitamente essa relação como
afetada na intent. Não inferir escopo tenant por FK simples de UUID.

Proibidos: telefone, e-mail pessoal, CPF/CNPJ/documento civil, nome, texto de
mensagem, áudio, transcrição, relatório pastoral, motivo íntimo, prompt,
payload bruto de provedor, chave ou segredo. Não usar hash de telefone como
identificador pseudônimo. UUIDs vinculáveis continuam privados e não entram
em Git, CI ou logs com a justificativa de serem “sanitizados”.

## 4. Fonte confiável, aviso e autenticidade

O servidor resolve igreja, pessoa, ator, acesso/papel, canal e recurso a partir
de sessão/identidade autenticada e dados persistidos. Modelo, webhook bruto
ou cliente nunca escolhem tenant, finalidade, capacidade ou versão aprovada.

Um adapter operacional revisado deverá obter uma fonte aprovada por tenant e
finalidade, com cadeia de catálogo e âncora externa autenticada, validade,
estado e registros humanos exigidos. Hash, ref opaca, DTO ou booleano enviados
pelo cliente não substituem essa fonte. Trocar entrada “latest” sem verificação
é proibido. Os indicadores false da entrada documental não serão editados para
liberar operação: elegibilidade futura precisa de decisão/capacidade derivada
server-side, versionada e revogável, sem reinterpretação do catálogo imutável.

Conservar os domínios dos hashes:
- content_digest: payload aprovado, não conteúdo de mensagem ou envelope.
- catalog_entry_digest: entrada exata e sua cadeia.
- notice_text_digest: bytes exatos do aviso por canal/idioma.
- evidence_digest: envelope operacional fechado, excluindo apenas seu hash.

Formato de canonicalização e tipos operacionais precisam de contrato próprio
testado, sem estender silenciosamente o subconjunto JCS sem números.
Autenticidade da prova requer contexto independente/âncora protegida; hash
autorrecalculado é só consistência. Chaves operacionais, rotação e custódia
ficam fora do repositório, sem provisionamento nesta fase.

## 5. Fluxo transacional e semântica da escolha

1. Preparar desafio server-side ligado à tupla completa e fonte vigente.
   A criação pode preceder a entrega. O identificador opaco sozinho não dá
   autoridade; canal/sessão e interação precisam ser autenticados.
2. Apresentar aviso fora da transação. Registrar observação de apresentação
   somente quando o adapter puder comprovar origem/correlação. Falha/estado
   desconhecido de entrega não vira prova de leitura ou vontade.
3. Receber escolha por controle explícito e parser determinístico do fluxo
   aprovado. Silêncio, “sim” isolado, emoji, leitura ou inferência do LLM
   não são ACCEPT. Desafio expirado, encaminhado ou de outra sessão é negado.
4. Abrir UoW tenant-scoped; revalidar fonte, pessoa/ator/recurso e estado
   corrente. Reservar idempotência e bloquear pessoa/stream e desafio na
   ordem comum revisada. Persistir evidência, consumir desafio e criar
   recibo; evento no ledger somente quando aplicável e autorizado.
5. Commit único. Só depois observar o recibo durável e devolver confirmação.
   Nenhuma chamada de provedor ocorre dentro dessa transação.

O limite técnico documental de desafio é de no máximo 30 minutos, sem
prorrogação por retry; validade da sessão também é necessária. Isso não define
prazo jurídico de retenção nem substitui a configuração aprovada do pacote.

| Entrada e pré-condição | Efeito permitido no fluxo futuro revisado |
|---|---|
| REFUSE_INITIAL com stream ausente | Evidência + recibo, nenhum evento concedido ou retirado |
| ACCEPT com prova/capacidades completas | Evidência + recibo + evento concedido atomicamente, somente na fase de writer autorizada |
| ACCEPT sem elegibilidade | Negar concessão antes de escrita autorizadora; não persistir recibo de sucesso |
| WITHDRAW com concessão anterior verificada | Evidência + recibo + retirado ligado ao evento anterior, conforme contrato revisado |
| Desafio/chave já usados com mesma intenção | Recuperar resultado original no escopo autorizado, sem nova escrita ou envio |
| Recusa inicial quando já existe concessão | Não apagar/reclassificar; exigir fluxo explícito de retirada |

Recusa/retirada não autorizam automação. Não condicionar o canal de exercício
de direitos à pessoa conceder consentimento. Preservar os caminhos existentes
de retirada/opt-out enquanto o novo estiver bloqueado; um pacote expirado não
deve silenciar o pedido de retirada. A autenticação e a correlação adequadas
para esse fluxo terão contrato próprio antes do wiring.

A função atual append_purpose_consent_event faz flush, não commit, e continua
recusando concedido. A implementação não pode inserir diretamente no ledger
para contornar essa negação. A revisão de concessão pertence à etapa E4;
E1–E3 não retiram esse bloqueio.

## 6. Concorrência, replay e falhas

Idempotência aleatória gerada no servidor, UNIQUE por igreja_id e chave,
compatível com a granularidade do ledger existente. Reidratação entre processos
exige registro durável autenticado; não converter string enviada pelo cliente
em OpaquePurposeConsentIdempotencyKey por construtor alternativo.

Desafio e interação têm unicidade de consumo adicional: trocar a chave não
permite aceitar novamente a mesma interação. Comparar intenção inteira,
tenant/pessoa/finalidade/digests/decisão; conflito nunca sobrescreve evidência.
Advisory lock por chave de tenant seguido de lock da Pessoa é a ordem atual do
ledger; qualquer novo lock de desafio/recibo deve respeitá-la em todos os
callers. Fechar a ordem exata em E1 e provar ausência de inversão com testes
concorrentes, incluindo os writers existentes.

Rollback em falha antes do commit remove todas as inserções da tentativa.
Commit ambíguo retorna UNKNOWN, nunca sucesso nem autorização de retry cego.
Uma consulta de reconciliação tenant-scoped procura o registro original pela
identidade server-owned e valida evidência/recibo/ledger antes de recuperar o
resultado. O módulo não dispara envio nem cria nova chave para escapar conflito.
Entrega futura do recibo exige mecanismo separado de deduplicação/estado.

## 7. RLS, ACL, retenção e observabilidade

- Todas as novas relações: igreja_id obrigatório, RLS habilitada e forçada,
  barreira restritiva de tenant usando app.tenant_igreja_id fixado pelo backend
  dentro da transação. GUC ausente/malformado ou tenant diferente: negar.
- Owner/papel de migration não é conexão de runtime. PUBLIC, anon,
  service_role e agent_runtime sem acesso direto às novas tabelas.
- A proposta reaproveita o papel de aplicação já usado pelo ledger
  (authenticated) com privilégios mínimos de coluna, sem ampliar privilégios
  existentes. Não criar papel global em migration TENANT como atalho.
- Evidência/recibo: SELECT/INSERT somente; sem UPDATE/DELETE/TRUNCATE comuns.
  Desafio: UPDATE só das colunas de transição, com USING/WITH CHECK e
  enforcement server-side/DB da máquina de estados e imutabilidade das demais.
- RLS não substitui RBAC: ler prova exige capacidade específica para o recurso,
  não apenas ser membro/admin genérico. Nunca expor tabelas livremente pela API.
- FORCE RLS não protege contra superuser/BYPASSRLS. Grants, memberships,
  ownership, funções e default ACLs devem ser inventariados no ambiente correto.

Prazos reais por finalidade/superfície não serão inventados neste plano.
Antes de uso vivo: retenção aprovada, responsável, expurgo de evidência/recibo/
desafios, conservação excepcional, cópias/backups e trilha mínima de eliminação.
Append-only de domínio não significa retenção infinita. Exclusão autorizada
terá canal/role separados, auditados e não disponíveis ao writer comum.
Não acrescentar CASCADE/SET NULL/RESTRICT ao acaso: E1 deve comparar o ciclo
de vida já existente da Pessoa/igreja/operador com as políticas aprovadas.
Enquanto essa decisão estiver aberta, bloquear aplicação compartilhada.

Logs/métricas somente categorias e contagens agregadas; sem payload, identidade,
chave idempotente ou segredos. Redação de erros antes de log e teste de
falhas de driver. Métricas: rejeição por escopo, conflito, expiração, resultado
incerto e latência. Não logar evidência inteira mesmo “sanitizada”.

## 8. Etapas técnicas e testes de aceite

| Etapa | Entrega | Evidência exigida |
|---|---|---|
| E1 | Revisão deste plano e contrato operacional versionado, schema/DTO fechado, tabelas/constraints/FKs, ordem de locks e ciclo de vida | Matriz de ameaças, fonte de autoridade, plano de rollback e lista exata de relações |
| E2 | Domínio/validação/UoW em laboratório, sem caller ou concessão | Unitários sintéticos: campos proibidos, fonte/tenant/ator inválidos, recusa, expiração, conflito, flags fechadas |
| E3 | Migration pelo fluxo catalog-bound e persistência em PG17 descartável | RLS/ACL reais, duas igrejas, concorrência/restart/commit ambíguo/rollback; zero skips |
| E4 | Integração interna revisada evidence + ledger + recibo | Concedido continua negado sem autoridade completa; atomicidade e reconciliação, sem bypass do serviço existente |
| E5 | Avaliação de prontidão técnica e custódia/humana | Matriz da seção 9 comprovada no SHA exato, revisão independente; sem abrir canais |
| Posterior | Preflight/aplicação compartilhada e caller/canário | Autorizações próprias; não incluídos na implementação local |

Autoria de migration: somente new_migration.py draft e prepare-head, ligados
ao SHA e à árvore exatos. Intent TENANT declara todas as relações/controles
afetados e nodeids PG17 realmente coletados. Não alterar verificador histórico
byte-pinado nem invocar apply_migrations.py. Usar snapshot privado do SHA
exato via trusted_repository_snapshot.py para captura/atestação/replay conforme
o contrato vigente. Não criar SQL/migration/head nesta missão documental.

Matriz mínima de testes E2–E4:
- Igreja A nunca lê/escreve/associa Pessoa, desafio, evidência, recibo ou ledger
  de B; repetir o mesmo identificador entre tenants não retorna prova alheia.
- GUC ausente/malformado, role proibida, SELECT por coluna, DML, TRUNCATE,
  funções auxiliares/default ACLs e fluxo normal do papel permitido.
- PRESENTATION/DELIVERED sem manifestação não concede; recusa deixa ledger
  ausente; retirada não reativa; menor/idade desconhecida/representação negados.
- Aviso/digest/versão/canal/idioma trocado, fonte revogada, desafio expirado,
  identidade cruzada, repetição com outra chave e replay conflitante.
- Duas transações concorrentes: exatamente uma manifestação/recibo/evento;
  rollback parcial, deadlock controlado, reinício e commit desconhecido.
- Sessão externa não autorizada/fallback privilegiado recusados; nenhuma
  chamada LLM, Evolution, rede ou envio durante a transação ou seus retries.
- Regressão do ledger, catálogo/evidence store documental e pacote existentes.
  Integração com canário exige depois regressão própria daquele WIP.

Rollback/compensação: em laboratório descartar somente recursos próprios.
Antes de eventual aplicação real, revisar compatibilidade do código, suspensão
de callers e recuperação; não DROP de evidências reais como rollback rápido.
Falha de rollout não pode apagar manifestação ou emitir concessão fictícia.
Nenhuma aplicação real autorizada por este plano.

## 9. Matriz de pré-requisitos e limites atuais

| Requisito | Estado comprovado nesta base | Próxima comprovação |
|---|---|---|
| Registro humano do pacote | Integrado pela PR #383 | Não solicitar aprovação duplicada; verificar adequação de cada papel exigido |
| Catálogo v1 → v2 | Integrado; 23 refs resolvidas, digests preservados | Verificação de confiança/custódia no adapter operacional |
| Conteúdo do payload | Imutável; campos de menores continuam nulos | Decisão competente sobre completude/representação, sem preenchimento retroativo |
| human_packet_complete | false | Todos os requisitos do template, não somente contagem de refs |
| Registros nominais | Registro humano integrado não equivale à comprovação de todos os papéis | Evidências por papel vinculadas ao mesmo digest; exceção jurídica formal quando aplicável |
| Menores | Âncoras complementares existentes, fluxo operacional não implementado | Avaliação de completude e contrato específico; não inferir adulto |
| Custódia/apresentação/manifestação | Contratos/âncoras documentais | Adapter autenticado e observação independente, não DTO |
| Retenção/eliminação/validade | Não atestadas operacionalmente nesta missão | Política efetiva e procedimentos testados antes de dados reais |
| Evidence store operacional | Não implementado no main por estas entregas | E1–E4 |
| Binding e recibo durável de consentimento | Exigidos; não provados operacionais por recibo sintético de relatório | E4–E5, sem confundir os dois tipos de recibo |
| writer_eligible | false | catalog_ready, consent_based_operation, CATALOG_BOUND, seis registros conforme template, evidência/binding/recibo implementados e autorização técnica separada |
| Ambiente/credencial/destino/janela | Não consultados nem autorizados nesta missão | Preflight/canário separados |

CATALOG_BOUND do ciclo operacional é diferente de
APPROVED_PAYLOAD_REFERENCES_BOUND do catálogo documental. A implementação
pode ser testada com fixtures completas e sintéticas sem declarar o pacote
real completo. Não há dependência circular: primeiro provar implementação em
laboratório; depois avaliar elegibilidade para permitir os callers reais.
Não é necessário coletar consentimento de pessoa real para testar o código.

## 10. Revisão, próximos passos e ausência de efeitos

Próximo gate único: OWNER_AUTHORIZE_REVIEW_CONSENT_EVIDENCE_STORE_OPERATIONAL_PLAN.
Revisar escopo adulto, tabelas/ACLs, atomicidade, ciclo de vida e matriz de
autoridade. Revisão do plano não é autorização de migração em DEV/PROD,
ativação de writer, catálogo operacional, envio ou nova aprovação humana.
Depois da revisão, uma ordem técnica delimitada poderá autorizar E1–E3 offline.

Este documento não contém dados reais de pessoas, SQL executável, configuração
de segredo, aplicação de migration ou mudança de flag. Cofre não consultado.
Apenas branch/worktree próprias e documentos; sem rede, commit, push, PR,
merge, banco ou efeito operacional nesta missão.
