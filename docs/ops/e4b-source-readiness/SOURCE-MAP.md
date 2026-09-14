# E4b: mapa estático da fonte para tarefas operacionais

| Campo | Evidência |
|---|---|
| Missão | M-E4B-TAREFAS-OPERACIONAIS-SOURCE-READINESS |
| Candidato | docs/e4b-tarefas-operacionais-source-readiness-20260914 |
| Worktree | e4b-tarefas-operacionais-source-readiness-20260914 |
| Branch | docs/e4b-tarefas-operacionais-source-readiness-20260914 |
| SHA base e HEAD consultado | 7b0b6bfd0e1b842d214576a3a1a7eff02acbb307 |
| Ambiente | local, leitura estática, sem runtime, banco, rede, import de produto ou efeito externo |
| Janela de coleta | 2026-09-14T08:24:11-03:00 a 2026-09-14T08:32:26-03:00 |
| Método | leitura dos pins de OPENING.json e verificação SHA-256 dos bytes permitidos |

## Conclusão de prontidão

Não há, entre as fontes permitidas, fonte externa concreta, aprovada, auditável e vinculada à finalidade "tarefas_operacionais" que prove consentimento vigente e possa alimentar o gate do coordenador D6. A ausência é coerente com o deny-all atual. Ela não autoriza aproximar C0, C2, C3, legado, papel, liderança ou opt-out como substitutos.

Consentimento vigente exigiria, na mesma transação tenant-scoped, igreja e pessoa exatas, finalidade exata, termo e política vigentes, não revogação, ausência de opt-out prevalente, proveniência aprovada, evidência durável e binding à solicitação operacional. Um snapshot, uma classificação, uma linha staged ou um recibo de reconciliação isolado não satisfazem a conjunção.

## Classes de prova

| Classe | Significado nesta missão |
|---|---|
| Forma estática | O código define tipos, validações ou sequência. Não afirma que dado ou autorização existam. |
| Staging | Há DML ou resultado interno dependente de commit pelo owner externo. Não prova durabilidade nem autorização operacional. |
| Reconciliação | Há leitura de cadeia E4b por porta abstrata. Não prova autorização por finalidade nem disponibiliza permit ao coordenador. |
| Consentimento vigente | Exigiria fonte concreta e atual com todos os vínculos acima. Nenhum pin atingiu esta classe. |

## Matriz de requisitos

| Requisito cumulativo | Evidência estática | Estado observado |
|---|---|---|
| Igreja e pessoa exatas | backend/app/services/purpose_consent.py:340-404 exige tenant e pessoa e exige escopo tenant. | Forma existe; não houve leitura viva nem fonte aprovada. |
| Finalidade exata | backend/app/domain/purpose_consent.py:25-55 contém "tarefas_operacionais". C0 aceita finalidade_id textual em backend/app/domain/e4b_consent.py:283-300. | Não há vínculo direto de C0 ao enum purpose_consent. |
| Termo vigente | backend/app/services/purpose_consent.py:340-368 exige versões confiáveis; docs/decisions/2026-08-28-d2b2-purpose-consent-ledger.md:50-54 prevê reaceite por versão divergente. | Não há catálogo aprovado que forneça a versão atual. |
| Não revogado e sem opt-out | backend/app/domain/purpose_consent.py:294-357 e backend/app/services/purpose_consent.py:376-422 projetam eventos e opt-out. | A lógica é estática; nenhum estado atual foi lido. |
| Concessão admissível | backend/app/services/purpose_consent.py:96-142 rejeita CONCEDIDO; backend/app/domain/purpose_consent_security.py:280-340 nega GRANT. | Não há writer aprovado que crie concessão. |
| Pacote e evidência aprovados | docs/decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md:65-93 e :101-142 exigem pacote por finalidade e evidência correlacionada. | O material atual é template ou rascunho. |
| Proveniência e durabilidade | docs/decisions/2026-08-28-d2b2-purpose-consent-ledger.md:88-111 declara que o ledger isolado não autoriza tool, mensagem ou efeito externo. | Nenhuma ponte aprovada ao gate D6 foi localizada. |
| Binding operacional | Fonte D6 externa backend/app/services/cell_report_whatsapp_coordinator.py:231-279 e :651-727 exige igreja, ator, conversa, inbound, reunião, turno, operação e finalidade. | O protocolo existe, mas não há gate concreto. |

## Classificação dos artefatos

| Artefato | Prova estática | Classe | O que não prova |
|---|---|---|---|
| C0, backend/app/domain/e4b_consent.py | Domínio puro sem I/O ou adapter, em :1-7. A intenção ainda não está confirmada ou persistida, em :359-404. Elegibilidade não produz efeito, em :535-595. | Forma estática. | ELIGIBLE não é consentimento vigente. O snapshot confirmado serve apenas a replay e projeção, em :439-532, e build_confirmed_operation não persiste nem confirma transação, em :803-815. |
| C0, autoridade e legado | Rejeita artefato legado e exige fatos resolvidos no servidor, em backend/app/domain/e4b_consent.py:658-689. | Proteção de forma. | A recusa do legado não cria fonte de finalidade ou autorização real. |
| C2, backend/app/services/e4b_consent_boundary.py | O módulo é em memória, sem adapter concreto; atestações não provam autenticação, autorização ou persistência, em :1-7. As portas são abstratas e read-only, em :748-764. | Reconciliação. | CONFIRMED exige receipt E4b no snapshot, em :791-805 e :1478-1552. Não é permit de tarefas_operacionais, não lê purpose_consent e não aciona o coordenador. |
| C2, indisponibilidade | Porta ausente, erro ou snapshot indisponível retornam SOURCE_UNAVAILABLE, em backend/app/services/e4b_consent_boundary.py:1386-1426 e :1478-1521. | Deny-first de leitura. | Não há fallback, retry ou conversão de ausência em autorização. |
| C3, backend/app/services/e4b_consent_persistence.py | Não abre sessão, não escolhe principal ou GUC e não confirma, reverte ou fecha transação, em :1-8. O resultado é não durável até commit externo, em :80-144. | Staging. | STAGED ou operation_state CONFIRMED, em :465-507 e :768-815, não provam commit, fonte vigente de finalidade ou permit. |
| Runbook C3 | O adapter recebe sessão, tenant e transação do owner e nunca devolve confirmação de commit, em docs/ops/e4-implementation/e4b-c3-persistence.md:59-71. | Staging documentado. | O runbook fixa OPERATIONAL_AUTHORIZATION=false e NEXT_STAGE_AUTHORIZED=false, em :11-14. |
| purpose_consent | Há enum, eventos e projeção; a leitura produz snapshot tenant-scoped, em backend/app/domain/purpose_consent.py:25-55, :172-357 e backend/app/services/purpose_consent.py:340-426. | Modelo de fonte futura. | O serviço é inativo, sem caller, e grants são bloqueados, em backend/app/services/purpose_consent.py:1-8 e :138-142. Não prova uma linha atual nem autoridade de tool. |
| purpose_consent_security | Valida contexto resolvido no servidor e falha fechada; GRANT retorna false, em backend/app/domain/purpose_consent_security.py:1-10, :234-277 e :280-340. | Leitura e retirada deny-first. | Papel ou capacidade de leitura não concedem finalidade nem liberam operação. |
| governance | Só representa DRAFT_NOT_APPROVED, em backend/app/domain/purpose_consent_governance.py:1-7 e :29-37. Todos os indicadores de aprovação, catálogo e writer são false, em :303-329. | Preparação de rascunho. | Não é aprovação do controlador, catálogo, evidence store ou writer. |
| D2B2a e D2B2b2 | D2B2a está inativa e sem caller, em docs/decisions/2026-08-28-d2b2-purpose-consent-ledger.md:15-24 e :88-111. D2B2b2 é template, não pacote aprovado, em docs/decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md:9-39. | Governança e limite. | Texto, template, merge ou teste não constituem autoridade de runtime, em D2B2b2:17-19. |
| Gate D6 externo | Declara que não há fonte durável aprovada e usa DenyAllOperationalConsentGate, em backend/app/services/cell_report_whatsapp_coordinator.py:1-15 e :271-295. Proposta e confirmação chamam o gate antes do serviço ou staging, em :740-817 e :820-952. | Gate operacional deny-all. | OperationalConsentPermit é process-local, não durável e não serializável, em :231-279. Não existe adaptador concreto. |
| Contrato D6 externo | Tarefas operacionais é precondição externa, não inferível de papel, liderança, opt-out, texto inbound ou estado local, em docs/decisions/2026-09-13-d6-cell-report-operational-contract.md:25-37. | Contrato de bloqueio. | Mesmo alvo de reunião não libera C09 ou C10, em :88-104. |
| Recibo histórico C3 externo | É evidência documental histórica, não nova execução, em docs/missions/M-2026-09-10-e4b-c3-replay-77.md:18-29, e declara OPERATIONAL_AUTHORIZATION=BLOCKED, em :62-72. | Histórico local de catálogo. | Não prova finalidade, runtime, ambiente compartilhado ou autorização operacional, em :31-48 e :104-121. |

## Fronteiras preservadas

| Cenário | Estado | Evidência |
|---|---|---|
| C09 | BLOCKED_BY_E4B | docs/decisions/2026-09-13-d6-cell-report-operational-contract.md:94-104 proíbe simular cenário positivo. |
| C10 | BLOCKED_BY_E4B | docs/decisions/2026-09-13-d6-cell-report-operational-contract.md:88-92 mantém a fonte E4B externa e ausente. |
| Gate padrão | Deny-all | Fonte D6 externa backend/app/services/cell_report_whatsapp_coordinator.py:282-295 retorna None. |

## Lacuna material

Faltam simultaneamente uma instância governada e aprovada de tarefas_operacionais, catálogo e evidence store, writer autorizado de concessão, fonte concreta tenant-scoped e transacional, e ponte revisada dessa fonte ao OperationalConsentGate. C0, C2 e C3 cobrem forma, leitura e staging da cadeia E4b; o ledger por finalidade cobre projeção futura; o coordenador D6 consome um permit opaco. Os pins não implementam o contrato que una esses domínios como fonte operacional.

## Fontes fixadas e verificadas

Todos os hashes foram conferidos por SHA-256 no ambiente local. Os itens locais usam SHA fonte 7b0b6bfd0e1b842d214576a3a1a7eff02acbb307.

| Fonte | SHA-256 |
|---|---|
| backend/app/domain/e4b_consent.py | 89c3044c6b13f55823add81a7ceb709e8ff525bd41f07e28cc0617faf9d14399 |
| backend/app/domain/purpose_consent.py | 80581f37227b3725b87354d1a3fcb1e9fab3db87da7db0afab1bb1b0ec25284e |
| backend/app/domain/purpose_consent_governance.py | a61a148749879606dc7187095fad5dc1525b1c83400a1cca72229c5b97a28037 |
| backend/app/domain/purpose_consent_security.py | d9efd69da83ad1aa04da66032852a93d0d674ad3fe58335d75f76b1d2edb74c8 |
| backend/app/domain/consent_ledger_receipt.py | 7c697130cceb5bc33b2ef6d9f59b9e4f1dda7f8559fb99263169e57e9fab2255 |
| backend/app/services/e4b_consent_boundary.py | b1bc5f6f4179f02b993b615c6a8a382eef17f38347c96818d6477e90e7042c00 |
| backend/app/services/e4b_consent_persistence.py | 77c161bfbb71eda1ce2b4a9d165c4b7fe56e8649a917dfb8d8a3f9403326694d |
| backend/app/services/purpose_consent.py | 65a859c5db03916791b07e1a68245ccc0b953a765fd63fa59d89616b73d9ef28 |
| backend/app/services/purpose_consent_governance.py | 6e66587af7bc14b5a9f8034585dc1553a87a9aedd14c59d8e7d8c55452d2116c |
| backend/app/services/consent_ledger_receipt.py | b9a6c14d61106bc4f11c35797708b516ca52d04704cd06ea33b93f149b82f0c3 |
| docs/ops/e4-implementation/e4b-c3-persistence.md | 357577c9aa3c146c78b52348cb3aaf15fda1210f178ec65152f3ba6c8f1c1514 |
| docs/decisions/2026-08-28-d2b2b1-consent-security-boundary.md | 1a1bd1dc017f0dac4dd9180e0909c9f22a24454bf35a0b34506179321a58a6f6 |
| docs/decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md | 39a309bd85f77abd870148ae7e208d53e9c9771ebadc32cb5abc5b49772599c0 |
| docs/decisions/2026-08-28-d2b2-purpose-consent-ledger.md | ccf61369f01f2e66f5b7e32e8024d436dd21fceba4202d343efedf89bc9a6962 |
| Fonte D6, contrato, SHA fonte e04bcf0342ef06b8d0016904d593be2616700aa3 | a6879c11b808b74558afeb1584f8beaaa2e2c16874e692e235d1e93a74baeacb |
| Fonte D6, coordenador, SHA fonte fea3964375890644b9839ece8f1f7ea30d26f55d | 5e1b3db5448d1532378a24c61e84cd55f8223033422de606f758bf6e33c15f2d |
| Fonte D6, FINAL-REPORT.md, SHA fonte fea3964375890644b9839ece8f1f7ea30d26f55d | a856bf8e58ffc6ec3a7d4725e66952f90a646fa2aa666036f7e6bf12188ec943 |
| Fonte replay, SHA fonte 67659a3c69d94af465e5d3994b060c5e8dd89547 | 8a401240e405f726785bad758440696bc18fb83920f1d2053adf548e538ca352 |

## Limites

Esta conclusão tem alta confiança para os bytes e linhas listados. Ela não afirma banco, migration aplicada, estado de pessoa, catálogo, evidence store, RLS viva, caller, runtime, ambiente compartilhado ou implantação. O arquivo docs/ops/MISSION-CONTROL.md não existe neste worktree; o controle aplicável lido foi docs/ops/e4b-source-readiness/MISSION-CONTROL.md.
