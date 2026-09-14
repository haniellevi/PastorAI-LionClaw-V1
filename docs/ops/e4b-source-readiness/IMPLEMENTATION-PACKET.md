# Pacote de implementação da fonte E4b para tarefas operacionais

| Campo | Evidência |
|---|---|
| Missão sucessora proposta | M-E4B-TAREFAS-OPERACIONAIS-SOURCE-IMPLEMENTATION |
| Candidato analisado | docs/e4b-tarefas-operacionais-source-readiness-20260914 |
| SHA base do diagnóstico | 7b0b6bfd0e1b842d214576a3a1a7eff02acbb307 |
| Aprovação humana reconciliada | docs/decisions/2026-09-09-filadelfia-tarefas-operacionais-approval.md no commit 108cb4e |
| Base da publicação | a7ca283875f3ec594477805ecd4a6b0a334312f2 |
| Branch da publicação | docs/e4b-source-readiness-closure-20260914 |
| Ambiente do diagnóstico | local, estático e sem efeito externo |
| Data de elaboração | 2026-09-14T08:32:26-03:00 |
| Estado reconciliado | SOURCE_READINESS_FECHADA / IMPLEMENTATION_BLOQUEADA |

## Objetivo delimitado

Quando as dependências existirem e houver autorização nominal nova, implementar somente uma fonte backend offline que consuma os contratos já existentes e responda ao OperationalConsentGate do coordenador D6. A fonte deve negar quando qualquer vínculo ou evidência estiver ausente, incompleto, revogado, fora do tenant ou desatualizado.

Este pacote não cria contrato novo, writer, API, endpoint, migration, caller, runtime, worker, webhook, outbox, envio, cobrança, canário ou ativação. C09 e C10 permanecem BLOCKED_BY_E4B. A missão sucessora não está autorizada por este documento.

## Pré-condições reconciliadas com a aprovação Filadélfia

A decisão humana incorporada à `main` altera a conclusão sobre aprovação do
controlador, mas mantém fechados todos os indicadores técnicos. O SOURCE-MAP
preserva a fotografia anterior no SHA `7b0b6bf`; esta matriz é a classificação
vigente para a abertura de qualquer missão sucessora.

| Pré-condição | Classificação | Estado observado | Evidência arquivo:linha |
|---|---|---|---|
| `controller_approved=true` | **SATISFEITA** | O representante autorizado aprovou o pacote, com os três papéis humanos e digest sob custódia externa. | docs/decisions/2026-09-09-filadelfia-tarefas-operacionais-approval.md:10-22 e :28 |
| `human_packet_complete=false` | **PARCIAL** | Há pacote e digest aprovados, mas as avaliações de menores e regiões conservam incertezas; `UNCERTAIN` bloqueia catálogo e writer. | docs/decisions/2026-09-09-filadelfia-tarefas-operacionais-approval.md:19-22 e :29; docs/decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md:103-142 |
| `catalog_ready=false` | **FALTANTE** | As referências e o `entry_digest` ainda não foram materializados no catálogo imutável. | docs/decisions/2026-09-09-filadelfia-tarefas-operacionais-approval.md:30 e :42-46 |
| `writer_eligible=false` | **FALTANTE** | Não há evidence store operacional nem autorização técnica; o serviço continua recusando `CONCEDIDO`. | docs/decisions/2026-09-09-filadelfia-tarefas-operacionais-approval.md:31 e :36-40; backend/app/services/purpose_consent.py:96-142 |
| `operational_authorization=false` | **FALTANTE** | A aprovação é insumo de governança e não autoridade de runtime ou envio. | docs/decisions/2026-09-09-filadelfia-tarefas-operacionais-approval.md:32-40 |

## Cobertura material ainda faltante

| Item | Classificação | O que existe e o que falta | Evidência arquivo:linha |
|---|---|---|---|
| Termo e pacote humano | **PARCIAL** | Existe digest de conteúdo aprovado; faltam fechar as incertezas jurídicas sobre menores e regiões e, se o conteúdo mudar, emitir nova versão e digest. | docs/decisions/2026-09-09-filadelfia-tarefas-operacionais-approval.md:19-22 e :29; docs/decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md:83-93 e :103-142 |
| Catálogo imutável | **FALTANTE** | Falta materializar referências e calcular `entry_digest`; esse é o gate nominal imediatamente seguinte. | docs/decisions/2026-09-09-filadelfia-tarefas-operacionais-approval.md:30 e :42-46 |
| Evidence store | **FALTANTE** | Não há store operacional purpose-bound que correlacione termo, manifestação, versão, tenant, pessoa e proveniência durável. | docs/decisions/2026-09-09-filadelfia-tarefas-operacionais-approval.md:31 e :36-40; docs/decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md:105-118 |
| Fonte externa de `tarefas_operacionais` | **FALTANTE** | O contrato D6 exige fonte externa e mantém a recusa padrão; aprovação documental não materializa uma fonte transacional. | docs/decisions/2026-09-13-d6-cell-report-operational-contract.md:25-28 e :88-101; backend/app/services/cell_report_whatsapp_coordinator.py:282-295 |
| Ponte C0/C2/C3 para o gate D6 | **FALTANTE** | C0 classifica, C2 reconcilia e C3 apenas prepara staging no snapshot histórico; nenhum deles emite o permit opaco exigido pelo gate D6. O coordenador integrado continua deny-all por default. | docs/ops/e4b-source-readiness/SOURCE-MAP.md:46-58 e :70; backend/app/services/cell_report_whatsapp_coordinator.py:232-295 e :745-826 |

Enquanto qualquer item permanecer PARCIAL ou FALTANTE, a implementação não
começa e `DenyAllOperationalConsentGate`, C09/C10 `BLOCKED_BY_E4B` e
`operational_authorization=false` permanecem.

## Allowlist concreta da missão sucessora

Os caminhos abaixo são uma allowlist futura. Eles não autorizam alteração na missão de diagnóstico.

| Caminho | Alteração máxima permitida | Restrição |
|---|---|---|
| backend/app/services/e4b_tarefas_operacionais_source.py | Criar resolvedor interno purpose-bound, sem endpoint e sem owner de sessão ou transação. | Só consome autoridade aprovada e dados já abertos pelo caller. Ausência, divergência ou erro negam. |
| backend/app/services/cell_report_whatsapp_coordinator.py | Integrar, dentro do módulo D6 revisado, implementação concreta do OperationalConsentGate que use a fonte acima. | Mantém gate padrão deny-all. Não expõe mint, não aceita permit de teste e não chama proposta, confirmação, UoW, commit ou dispatch. |
| backend/tests/test_e4b_tarefas_operacionais_source.py | Criar testes offline negativos da fonte e integração de gate. | Sem writer falso, permit fabricado, staging, C09/C10 positivo, rede ou banco compartilhado. |
| docs/ai/PRD-COVERAGE.md | Atualizar classificação factual depois de implementação e evidência executada. | Não converter documentação em prova de fonte viva. |
| docs/WIKI-IGREJA12.md | Atualizar estado, SHA, testes e limite. | Não registrar dados reais, credenciais ou conteúdo pastoral. |
| docs/ops/e4b-source-readiness/IMPLEMENTATION-EXECUTION-RECORD.md | Criar recibo sanitizado da missão sucessora. | Incluir ambiente, horário, SHA base, candidato, diff, hashes, limites e próximo gate. |
| docs/ops/e4b-source-readiness/FINAL-REPORT.md | Atualizar fechamento factual da missão sucessora. | Não declarar ativação, ambiente compartilhado ou permit fora da evidência executada. |

Todos os demais caminhos ficam fora da allowlist, sobretudo migrations, modelos de banco, rotas, workers, webhooks, scripts operacionais, flags, serviços de envio e qualquer caminho de legado.

## Reuso obrigatório e fronteiras

| Componente existente | Reuso permitido | Limite obrigatório |
|---|---|---|
| backend/app/domain/purpose_consent.py:25-55 e :294-357 | PurposeConsentPurpose.TAREFAS_OPERACIONAIS e projeção pura de estado. | Não converter evento legado em consentimento por finalidade. |
| backend/app/services/purpose_consent.py:340-426 | Leitura tenant-scoped do snapshot quando termo vier de fonte aprovada. | Não chamar append para criar concessão. O serviço bloqueia CONCEDIDO, em :138-142. |
| backend/app/domain/purpose_consent_security.py:280-340 | Avaliação deny-first de ação e escopo. | Permissão de leitura não emite permit operacional; GRANT continua false. |
| backend/app/services/e4b_consent_boundary.py:748-764 e :1478-1552 | Reconciliação E4b somente como leitura de cadeia, se decisão aprovada exigir correlação. | Não tratar CONFIRMED como autorização purpose-bound nem ampliar a porta abstrata para esconder a fonte ausente. |
| backend/app/services/e4b_consent_persistence.py:1-8 e :123-144 | Nenhum reuso para emitir permit. | C3 é staging e depende de commit externo; não é fonte de vigência. |
| Fonte D6, backend/app/services/cell_report_whatsapp_coordinator.py:231-295 e :669-727 | OperationalConsentRequest, OperationalConsentGate e revalidação no mesmo contexto transacional. | Permit é opaco e privado ao coordenador. Não criar API paralela, fabricá-lo ou contornar o gate. |

O pacote não autoriza modificar C0, C2, C3, purpose_consent, segurança de purpose ou governança para forçar compatibilidade. Se os contratos existentes forem insuficientes, a implementação para e a lacuna vira decisão arquitetural explícita.

## Sequência de execução futura

1. Repetir preflight no worktree autorizado: repositório, branch, SHA, estado, hashes D6 e E4b, documentação de governança e ausência de mudança concorrente.
2. Validar documentalmente as pré-condições, sem abrir ambiente compartilhado, dados reais, credenciais ou caminhos protegidos. Ausência conserva bloqueio.
3. Implementar apenas a allowlist, usando a solicitação fechada do coordenador. Antes de qualquer resultado permissivo interno, exigir igualdade de igreja, pessoa, finalidade, termo, cadeia aplicável e contexto da solicitação.
4. Executar somente testes autorizados naquela missão. A integração não chama staging, proposta, confirmação, UoW, commit, outbox ou dispatch.
5. Registrar bytes, SHA, ambiente, horário, escopo exercitado e limites. Teste verde prova somente o SHA e o comportamento exercitado.

## Matriz de testes proposta

Nenhum teste abaixo foi executado nesta missão. A matriz é negativa por desenho e não autoriza cenário positivo de C09 ou C10.

| Caso | Resultado exigido |
|---|---|
| Fonte de autoridade ausente, porta C2 ausente ou erro de leitura | Negação, sem fallback, permit, staging ou retry. |
| Finalidade diferente de tarefas_operacionais | Negação. |
| Evento ausente, retirado, termo desatualizado ou opt-out global | Negação. |
| Pacote, catálogo, evidência, digest ou vigência ausentes ou divergentes | Negação. |
| Recibo C2 CONFIRMED sem vínculo purpose-bound aprovado | Negação. |
| Resultado C3 STAGED, replay ou dependente de commit do owner | Negação. |
| Igreja, pessoa, conversa, inbound, reunião, turno ou operação divergentes do OperationalConsentRequest | Negação. |
| Pessoa.consentimento, ConsentRecord, papel, liderança, texto inbound ou opt-out isolado | Negação. |
| Gate padrão sem integração explícita | DenyAllOperationalConsentGate retorna None. |
| C09 e C10 | BLOCKED_BY_E4B, sem proposta, confirmação, UoW, commit ou envio. |

Verificação transacional e RLS em PostgreSQL 17 descartável só pode ser proposta por autorização específica posterior. Não pertence a este pacote e não pode ser substituída por teste de unidade.

## Rollback, responsáveis e próximo gate

O rollback de eventual missão sucessora será apenas reversão do patch de código e documentação dela. Não há migration, dado de domínio ou rollback de ambiente compartilhado neste pacote.

- **Jurídico:** fechar as avaliações de menores e regiões, completar o pacote
  humano e indicar se o digest aprovado permanece válido.
- **Técnico:** após gate próprio, materializar catálogo e `entry_digest`; em
  etapas posteriores e independentes, produzir evidence store, fonte externa,
  writer elegível e ponte revisada C0/C2/C3 para o gate D6.
- **Raniel:** emitir as autorizações nominais por etapa e preservar
  `operational_authorization=false` até a evidência técnica correspondente.

O único próximo gate é Raniel autorizar nominalmente
`OWNER_AUTHORIZE_CATALOG_MATERIALIZATION_FILADELFIA_TAREFAS_OPERACIONAIS`,
limitado à materialização documental do catálogo e cálculo do `entry_digest`.
M-E4B-TAREFAS-OPERACIONAIS-SOURCE-IMPLEMENTATION não foi iniciada nem
autorizada. O gate não abre C09, C10, caller, runtime, banco, migration,
credencial, envio ou ativação.
