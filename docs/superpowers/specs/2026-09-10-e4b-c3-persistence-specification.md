# E4b C3: especificação de persistência isolada

## Estado, escopo e vínculo de fonte

Status: C3-SPEC R4, source-only. Esta fase documental fixa o contrato físico da persistência E4b antes de qualquer draft TENANT. A fase C3-SPEC não cria migration, SQL executável, modelo, adapter ativo, teste, banco, role, grant efetivo, caller, runtime ou efeito externo.

| Campo | Valor |
| --- | --- |
| Missão | M-2026-09-10-e4b-c3-persistence |
| Ambiente da especificação | local, sem banco iniciado |
| Worktree | e4b-c3-persistence-v1 |
| Branch | feat/e4b-c3-persistence-v1 |
| SHA base | 66d672af6650ade36ada6baf7333c9ec30417242 |
| Horário do preflight | 2026-09-10T09:05:48-03:00 |
| Input R1 corrigido | SHA-256 03b49243eaaf344a79fcaae4c41f334f194cc4c321051df3ad1269483a1e0d49 |
| Pareceres R1 incorporados | NEXO 474568c43116cdb88b2e7f69cb546f2cda791b2a094eebdf59a7f511ee03b913; LENTE 9d7bc55e48ed816ee78159122594284e4c45bfac353a7da4f8d51bc2288bb268 |
| Input R2 corrigido | SHA-256 c96ff8097106e86dcc914d90e6d825e17c365f149d6f2d852c92d89d40c83f08 |
| Parecer NEXO R2 incorporado | SHA-256 adca5a5fecc359e6512d16f973b537e7dda8b6abaa382c5cb143391fb944d3f4 |
| Aceite LENTE R2 preservado | SHA-256 3102bd210fc611778a897fa5de9e47ffa1882fc040a74053ba8b7758bfd5b7c5 |
| Input R3 corrigido | SHA-256 5d72e694b56c6c1b304daf5b5d132bf9f27f8a3ae183f23c3b15663fe1baafe1 |
| Parecer NEXO R3 incorporado | SHA-256 f6f1f363652d4975f454e3120874188fdf06bc6c4e237a2fbea96a4c13379f92 |
| Fonte de autoridade | decisão do Orquestrador, ficha da missão, C1, C2, domínio E4b, contrato durável, protocolo de serialização e plano LENTE C3 |

O documento resolve somente relações e controles E4b no schema public. Não assume que qualquer objeto exista em banco, que uma migration esteja aplicada, que ACL histórica continue atual ou que exista caller para a porta futura.

Permanecem bloqueados: mutador, arquivamento ou exclusão de Pessoa; exclusão de Igreja; aplicação operacional de migration; DEV; PROD; banco compartilhado; caller; runtime; WhatsApp; envio; credencial; flag; push; PR; merge; deploy e ativação. O freeze documental preliminar é um commit local técnico já autorizado, contém somente esta especificação e não é gate humano. Depois dele, draft catalogado, registro do basename, implementação C3, prepare-head, replay PG17 local descartável e revisão final são subetapas técnicas autorizadas. O único próximo gate humano é o commit local do candidato C3 completo e exato, somente depois de implementação, replay PG17 e revisão final; ele não autoriza aplicação operacional ou ambiente compartilhado.

## Decisões normativas fechadas

| Símbolo | Decisão persistida |
| --- | --- |
| I | operation_id: UUID opaco, server-owned, imutável, único no tenant e identidade da operação confirmada. Não é lock de idempotência. |
| K | idempotency_key: texto opaco server-owned no namespace e4b:consent-operation:v1:. É a chave de idempotência e só é reidratável por lookup E4b autorizado e tenant-scoped. |
| C | correlation_id: UUID opaco, server-owned, imutável, único no tenant e não reassociável. |
| F | par fingerprint_version e fingerprint: digest hexadecimal canônico versionado da intenção fechada, calculado pelo servidor. |
| R | receipt_id: UUID opaco, server-owned, imutável, único por I confirmado. A projeção de receipt é uma relação própria e minimizada. |

K é a correção normativa da terminologia antiga que tratava I como barreira de repetição. C1, o contrato durável e esta especificação prevalecem: I identifica a operação, e K é adquirido para idempotência.

Uma cadeia confirmada é composta por I, seus campos C e F, a projeção de concessão no stream E4b, a retenção identificável e exatamente um R. A cadeia não consulta, referencia, converte, compara ou completa consentimento_finalidade_evento, pc:v1:, ce:v1:, ConsentReceipt, ConsentLedgerReceiptOperation ou qualquer dado, resultado, correlação, receipt, chave, evento ou ausência do legado. A ausência de artefato legado não é decisão E4b.

## Âncoras parentais e inventário físico

As únicas relações E4b novas ficam em public:

1. e4b_consent_operations
2. e4b_consent_streams
3. e4b_consent_receipts
4. e4b_consent_retentions
5. e4b_consent_holds
6. e4b_consent_hold_events

Não há tabela de lock, sequência E4b, view, função exposta, enum PG, materialized view ou relação de compatibilidade com legado. Estados usam text limitado por CHECK, para que o conjunto permitido seja visível e não exista tipo global reutilizável por acidente.

No SHA base, a fonte local confirma public.igrejas(id) como raiz de tenant, public.pessoas(igreja_id, id) com unique composta pessoas_igreja_id_id_key, e public.app_users(igreja_id, id) com unique composta app_users_igreja_id_id_key. Isso é âncora de fonte do SHA acima, não afirmação sobre ambiente vivo. Antes do draft, o fluxo de migration deve falhar fechado se esses pais ou suas chaves compostas divergirem.

Toda relação E4b contém igreja_id uuid NOT NULL. A FK para igrejas(id) é simples porque a raiz é o próprio tenant. Toda FK para relação tenant-scoped é composta e começa com igreja_id. Todas as FKs usam ON UPDATE RESTRICT e ON DELETE RESTRICT. CASCADE, SET NULL e reassociação de tenant são proibidos.

## Relação 1: public.e4b_consent_operations

Finalidade: registro imutável e confirmado de I, incluindo K, C, F, autoridade interna, ação, origem E4b e os dados mínimos para receipt. É a única relação que guarda identificadores internos de Pessoa necessários para reidentificação autorizada. Ela não contém mensagem, telefone, endereço, texto livre, conteúdo pastoral, token, segredo ou payload externo.

A serialização canônica de F usa os campos fechados do contrato C0 e C2, inclusive titular, manifestante, papel de manifestação, responsável, operator_id, operator_kind, operator_role_links, finalidade_id, origem, C, versões e content_digest. A coluna operator_role_links preserva a lista ordenada necessária para reidratar E4bHistoricalOperationIdentity sem inferir papel a partir de UUID igual.

| Coluna | Tipo PG17 | Nula | Default | Finalidade e regra |
| --- | --- | --- | --- | --- |
| igreja_id | uuid | não | nenhum | Tenant obrigatório. |
| operation_id | uuid | não | nenhum | I, emitido pelo servidor. |
| idempotency_key | text | não | nenhum | K opaca, namespaced e server-owned. |
| correlation_id | uuid | não | nenhum | C opaca e não reassociável. |
| action | text | não | nenhum | ACCEPT ou WITHDRAW. |
| origin | text | não | E4B | Origem fechada da cadeia. Nunca aceita valor legado. |
| origin_accept_operation_id | uuid | sim | NULL | I do ACCEPT E4b de origem da retirada. |
| origin_action | text | sim | NULL | Constante ACCEPT somente quando há origem. Fecha a FK auto-referente por ação. |
| titular_pessoa_id | uuid | não | nenhum | Titular interno e chave do stream. |
| manifestante_pessoa_id | uuid | não | nenhum | Pessoa que manifestou a ação. |
| responsavel_pessoa_id | uuid | sim | NULL | Responsável interno, obrigatório somente para manifestação por responsável. |
| manifestant_role | text | não | nenhum | TITULAR ou RESPONSAVEL, com o mesmo nome do contrato C0 e C2. |
| manifestant_relation_valid | boolean | não | true | Atestação server-owned persistida somente como verdadeira. |
| operator_id | uuid | não | nenhum | Identidade opaca do operador. Não é interpretada como Pessoa ou AppUser por igualdade de UUID. |
| operator_kind | text | não | nenhum | HUMAN ou TECHNICAL. |
| operator_role_links | text[] | não | array vazio | Papéis explícitos e ordenados que explicam eventual igualdade entre operator_id e as pessoas internas. |
| server_resolved | boolean | não | true | Atestação histórica fechada; qualquer valor diferente de verdadeiro é inválido. |
| finalidade_id | text | não | nenhum | Finalidade E4b server-owned, não é FK nem identificador legado. |
| contract_version | text | não | nenhum | Versão do contrato E4b aplicado. |
| policy_version | text | não | nenhum | Versão da política aprovada. |
| term_version | text | não | nenhum | Versão do termo ou artefato aprovado. |
| content_digest | text | não | nenhum | Digest hexadecimal de 64 caracteres do conteúdo aprovado. |
| fingerprint_version | text | não | e4b-fingerprint:v1 | Versão canônica de F. |
| fingerprint | text | não | nenhum | F, digest hexadecimal de 64 caracteres calculado pelo servidor. |
| concession_state | text | não | nenhum | ACTIVE para ACCEPT e WITHDRAWN para WITHDRAW. É o estado histórico da operação, não a leitura atual do stream. |
| operation_state | text | não | CONFIRMED | Único estado persistível de operação. |
| confirmed_at | timestamp with time zone | não | nenhum | Instante PG17 canônico, capturado uma única vez depois dos locks e da revalidação final, imediatamente antes do staging. |

### Chaves, FKs, unicidades e checks

- PK e4b_consent_operations_pkey: (igreja_id, operation_id).
- FK e4b_consent_operations_igreja_fkey: igreja_id para igrejas(id).
- FK e4b_consent_operations_titular_fkey: (igreja_id, titular_pessoa_id) para pessoas(igreja_id, id).
- FK e4b_consent_operations_manifestante_fkey: (igreja_id, manifestante_pessoa_id) para pessoas(igreja_id, id).
- FK e4b_consent_operations_responsavel_fkey: (igreja_id, responsavel_pessoa_id) para pessoas(igreja_id, id), quando não nulo.
- FK auto-referente e4b_consent_operations_origin_accept_fkey: (igreja_id, origin_accept_operation_id, origin_action, titular_pessoa_id, finalidade_id) para a unique (igreja_id, operation_id, action, titular_pessoa_id, finalidade_id) da própria relação. Ela exige origem ACCEPT no mesmo tenant, titular e finalidade.
- Unique e4b_consent_operations_tenant_k_key: (igreja_id, idempotency_key).
- Unique e4b_consent_operations_tenant_c_key: (igreja_id, correlation_id).
- Unique e4b_consent_operations_stream_action_key: (igreja_id, operation_id, action, titular_pessoa_id, finalidade_id). É alvo das FKs de stream e origem de retirada.
- Unique e4b_consent_operations_confirmation_key: (igreja_id, operation_id, confirmed_at). É alvo da âncora de retenção.
- Unique e4b_consent_operations_receipt_projection_key: (igreja_id, operation_id, correlation_id, action, origin, manifestant_role, concession_state, confirmed_at, contract_version, policy_version, term_version, content_digest, fingerprint_version, fingerprint). É alvo do receipt e impede divergência da projeção.
- Unique parcial e4b_consent_operations_one_accept_per_stream_key: (igreja_id, titular_pessoa_id, finalidade_id) quando action=ACCEPT. Não existe segundo ACCEPT para o stream, inclusive após WITHDRAWN.
- Check e4b_consent_operations_action_check: somente ACCEPT e WITHDRAW.
- Check e4b_consent_operations_origin_check: origin=E4B; ACCEPT exige campos de origem nulos e concession_state=ACTIVE; WITHDRAW exige origin_accept_operation_id não nulo, distinto de operation_id, origin_action=ACCEPT e concession_state=WITHDRAWN.
- Check e4b_consent_operations_manifestation_check: TITULAR exige manifestante igual ao titular e responsável nulo. RESPONSAVEL exige manifestante distinto do titular, responsavel igual ao manifestante. manifestant_relation_valid e server_resolved devem ser verdadeiros.
- Check e4b_consent_operations_operator_check: operator_kind é HUMAN ou TECHNICAL; operator_role_links contém somente TITULAR, MANIFESTANTE e RESPONSAVEL, em ordem canônica, sem duplicidade.
- Check e4b_consent_operations_fixed_values_check: fingerprint_version=e4b-fingerprint:v1, operation_state=CONFIRMED, origin=E4B, finalidade_id não vazia de até 128 caracteres e versões com formato seguro de até 128 caracteres. K tem prefixo e4b:consent-operation:v1: e sufixo de 1 a 128 caracteres em A-Z, a-z, 0-9, dois-pontos, ponto, sublinhado ou hífen.
- Check e4b_consent_operations_digest_check: content_digest e fingerprint são texto hexadecimal minúsculo de exatamente 64 caracteres.

### Índices e imutabilidade

Além dos índices de PK e uniques, existem:

- e4b_consent_operations_origin_lookup_idx em (igreja_id, origin_accept_operation_id);
- e4b_consent_operations_subject_timeline_idx em (igreja_id, titular_pessoa_id, confirmed_at DESC);
- e4b_consent_operations_tenant_action_idx em (igreja_id, action, confirmed_at DESC).

Depois da primeira inserção, todas as colunas são imutáveis. UPDATE, DELETE, mudança de tenant, troca de sujeito, troca de origem ou alteração de digest devem falhar. A guarda interna de imutabilidade complementa a ausência de grants operacionais de UPDATE e DELETE.

### Tempo canônico da confirmação

Na implementação C3, depois de K, L, C e stream terem sido adquiridos e de toda revalidação final ter passado, a porta captura de PG17 exatamente uma chamada de `clock_timestamp()` em um valor `timestamptz`, chamado `confirmed_at`. Nenhuma outra amostragem de relógio pode ser usada para a mesma cadeia. Esse valor é copiado com igualdade exata para a operação, o receipt, `state_changed_at` do stream criado ou retirado e `retention_anchor_at` e `state_changed_at` da retenção criada.

`confirmed_at` torna-se visível e autoritativo somente se o owner externo confirmar a transação que contém a cadeia inteira. Ele não é, nem pretende ser, timestamp físico de commit de WAL, futuro instante de commit, `pg_xact_commit_timestamp`, nem sucesso antes do commit. Rollback ou falha diferida elimina todas as cópias.

## Relação 2: public.e4b_consent_streams

Finalidade: projeção de concessão E4b para (igreja_id, titular_pessoa_id, finalidade_id). A linha nasce ACTIVE com um ACCEPT E4b e pode fazer uma única transição para WITHDRAWN pelo WITHDRAW E4b que referencia aquele ACCEPT. Não é ledger legado e não é reaceitável neste recorte.

| Coluna | Tipo PG17 | Nula | Default | Finalidade e regra |
| --- | --- | --- | --- | --- |
| igreja_id | uuid | não | nenhum | Tenant obrigatório. |
| titular_pessoa_id | uuid | não | nenhum | Sujeito do stream. |
| finalidade_id | text | não | nenhum | Mesma finalidade E4b server-owned da operação. |
| accept_operation_id | uuid | não | nenhum | I da única operação ACCEPT do stream. |
| accept_action | text | não | ACCEPT | Coluna constante que torna a FK de aceitação verificável. |
| stream_state | text | não | ACTIVE | ACTIVE ou WITHDRAWN. |
| withdraw_operation_id | uuid | sim | NULL | I da retirada, se houver. |
| withdraw_action | text | sim | NULL | Constante WITHDRAW quando há retirada. |
| state_changed_at | timestamp with time zone | não | nenhum | Instante UTC da criação ou transição permitida. |

### Chaves, FKs, checks, índices e mutabilidade

- PK e4b_consent_streams_pkey: (igreja_id, titular_pessoa_id, finalidade_id).
- FK e4b_consent_streams_igreja_fkey: igreja_id para igrejas(id).
- FK e4b_consent_streams_titular_fkey: (igreja_id, titular_pessoa_id) para pessoas(igreja_id, id).
- FK e4b_consent_streams_accept_fkey: (igreja_id, accept_operation_id, accept_action, titular_pessoa_id, finalidade_id) para e4b_consent_operations_stream_action_key. Ela exige ACCEPT da mesma igreja, titular e finalidade.
- FK e4b_consent_streams_withdraw_fkey: (igreja_id, withdraw_operation_id, withdraw_action, titular_pessoa_id, finalidade_id) para a mesma unique de operação quando houver retirada. A FK de origem da operação retirada e a unique parcial de ACCEPT fecham que ela parte do único ACCEPT daquele stream.
- Check e4b_consent_streams_state_check: ACTIVE exige campos de retirada nulos; WITHDRAWN exige withdraw_operation_id não nulo e withdraw_action=WITHDRAW.
- Check e4b_consent_streams_accept_check: accept_action=ACCEPT e finalidade_id é texto server-owned não vazio de até 128 caracteres.
- Índice parcial e4b_consent_streams_active_lookup_idx em (igreja_id, finalidade_id, titular_pessoa_id) quando stream_state=ACTIVE.

As chaves, accept_operation_id, accept_action e o instante de criação são imutáveis. A guarda de stream tem dois ramos distintos: em BEFORE INSERT só permite ACTIVE, campos de retirada nulos e `state_changed_at` exatamente igual ao `confirmed_at` de accept_operation_id; em BEFORE UPDATE só permite ACTIVE para WITHDRAWN, uma vez, com todas as chaves e campos de ACCEPT inalterados, retirada E4b do mesmo stream e `state_changed_at` exatamente igual ao `confirmed_at` de withdraw_operation_id. Não há reversão, inserção direta em WITHDRAWN, nova aceitação, DELETE ou mudança de sujeito ou finalidade.

## Relação 3: public.e4b_consent_receipts

Finalidade: receipt R minimizado, imutável e único por operação confirmada. Esta é a única projeção que poderá ser devolvida ao fluxo operacional futuro. Ela não é chave de idempotência, credencial de reidentificação nem prova de autoridade.

| Coluna | Tipo PG17 | Nula | Default | Finalidade e regra |
| --- | --- | --- | --- | --- |
| igreja_id | uuid | não | nenhum | Tenant necessário à verificação. |
| receipt_id | uuid | não | nenhum | R opaco e server-owned. |
| operation_id | uuid | não | nenhum | I correspondente. |
| correlation_id | uuid | não | nenhum | C correspondente. |
| action | text | não | nenhum | Enum de ação E4b. |
| origin | text | não | E4B | Origem E4b fechada, sem expor I de origem. |
| manifestant_role | text | não | nenhum | TITULAR ou RESPONSAVEL. |
| concession_state | text | não | nenhum | ACTIVE ou WITHDRAWN, conforme a operação histórica. |
| confirmed_at | timestamp with time zone | não | nenhum | Cópia exata da operação confirmada. |
| contract_version | text | não | nenhum | Versão permitida. |
| policy_version | text | não | nenhum | Versão permitida. |
| term_version | text | não | nenhum | Versão permitida. |
| content_digest | text | não | nenhum | Digest hexadecimal de conteúdo aprovado. |
| fingerprint_version | text | não | nenhum | Versão de F projetada, para tornar a cópia de fingerprint verificável. |
| fingerprint | text | não | nenhum | Digest F permitido. |

### Chaves, FKs, checks, índices e imutabilidade

- PK e4b_consent_receipts_pkey: (igreja_id, receipt_id).
- Unique e4b_consent_receipts_tenant_operation_key: (igreja_id, operation_id). Há exatamente um R por I.
- FK e4b_consent_receipts_igreja_fkey: igreja_id para igrejas(id).
- FK e4b_consent_receipts_operation_fkey: (igreja_id, operation_id) para e4b_consent_operations(igreja_id, operation_id).
- FK e4b_consent_receipts_projection_fkey: todos os campos de projeção, exceto receipt_id, apontam para e4b_consent_operations_receipt_projection_key. A cópia não pode divergir de I.
- Check e4b_consent_receipts_fixed_values_check: origin=E4B; ação, manifestação e concession_state pertencem aos conjuntos fechados; fingerprint_version=e4b-fingerprint:v1.
- Check e4b_consent_receipts_digest_check: content_digest e fingerprint são texto hexadecimal minúsculo de exatamente 64 caracteres.
- Índice e4b_consent_receipts_tenant_c_idx em (igreja_id, correlation_id).

Nenhuma coluna de receipt pode se chamar ou conter identificador direto de Pessoa, manifestante, responsável, operador ou finalidade. Em particular, são proibidos titular_pessoa_id, manifestante_pessoa_id, responsavel_pessoa_id, operator_id, operator_role_links, finalidade_id, idempotency_key, nome, telefone, endereço, texto livre, mensagem, conteúdo pastoral, motivo de hold, token, segredo, payload externo e evidência de autoridade. A allowlist é exatamente operation_id, correlation_id, receipt_id, igreja_id, action, concession_state, origin, manifestant_role, confirmed_at, contract_version, policy_version, term_version, content_digest, fingerprint_version e fingerprint. Receipt não tem receipt_state, CHECK de estado ou estado próprio: ele é CONFIRMED somente por derivação da operação CONFIRMED ligada pela FK, e essa derivação só é visível se o owner confirmar a transação. Todas as colunas são imutáveis após inserção e DELETE é proibido.

## Relação 4: public.e4b_consent_retentions

Finalidade: projeção mutável e tenant-scoped da retenção identificável de cada operação. Ela inicia com prazo de 24 meses de calendário a partir de confirmed_at, pausa enquanto houver hold E4b ativo e não aciona anonimização, exclusão, cascata, cron ou descarte automático.

| Coluna | Tipo PG17 | Nula | Default | Finalidade e regra |
| --- | --- | --- | --- | --- |
| igreja_id | uuid | não | nenhum | Tenant obrigatório. |
| operation_id | uuid | não | nenhum | Operação retida. |
| retention_state | text | não | RETENTION_RUNNING | RETENTION_RUNNING, RETENTION_HELD ou RETENTION_ELIGIBLE. |
| retention_anchor_at | timestamp with time zone | não | nenhum | Cópia exata de confirmed_at. |
| retention_due_at | timestamp with time zone | não | nenhum | Vencimento efetivo, inicialmente âncora mais 24 meses. |
| active_hold_count | integer | não | 0 | Quantidade de holds E4b ativos da operação. |
| suspension_started_at | timestamp with time zone | sim | NULL | Início da pausa agregada, somente enquanto há hold ativo. |
| last_hold_event_at | timestamp with time zone | sim | NULL | Último evento E4b de hold considerado. |
| state_changed_at | timestamp with time zone | não | nenhum | Instante UTC da criação ou última transição. |

### Chaves, FKs, checks, índices e mutabilidade

- PK e4b_consent_retentions_pkey: (igreja_id, operation_id).
- FK e4b_consent_retentions_igreja_fkey: igreja_id para igrejas(id).
- FK e4b_consent_retentions_operation_fkey: (igreja_id, operation_id) para a operação E4b.
- FK e4b_consent_retentions_anchor_fkey: (igreja_id, operation_id, retention_anchor_at) para e4b_consent_operations_confirmation_key. A âncora não pode divergir de I.
- Check e4b_consent_retentions_count_check: active_hold_count maior ou igual a zero.
- Check e4b_consent_retentions_due_check: retention_due_at maior ou igual a retention_anchor_at.
- Check e4b_consent_retentions_state_check: RETENTION_RUNNING e RETENTION_ELIGIBLE exigem contagem zero e suspensão nula; RETENTION_HELD exige contagem positiva e suspensão não nula.
- Índice e4b_consent_retentions_due_idx em (igreja_id, retention_state, retention_due_at) para futura avaliação humana de elegibilidade, sem worker nesta fase.

No instante de confirmação, a porta conceitual grava RETENTION_RUNNING, zero holds, `retention_anchor_at=confirmed_at`, `state_changed_at=confirmed_at` e `retention_due_at=add_24m_utc(confirmed_at)`. RETENTION_ELIGIBLE é estado persistível futuro, nunca instrução de exclusão e nunca transição automática nesta C3.

### Fórmula UTC de 24 meses e pausa

Para `u=confirmed_at`, represente `u` como a tupla civil UTC `(Y, M, D, h, m, s, microssegundo)`. `add_24m_utc(u)` é a mesma hora UTC no mês `M` do ano `Y+2`, com dia `min(D, último_dia_gregoriano(Y+2, M))`. Esse instante é convertido de volta para `timestamptz` como UTC. A fórmula não lê nem depende de `TimeZone` da sessão, de locale, de DST ou de conversão local. Assim, 29 de fevereiro usa o último dia de fevereiro dois anos depois, e 29, 30 ou 31 de qualquer mês sem dia correspondente usam o último dia do mês-alvo, preservando hora, minuto, segundo e microssegundo UTC.

Seja `B=add_24m_utc(retention_anchor_at)`. Cada hold RESOLVED produz o intervalo fechado de pausa de `applied_at` a `resolved_at`; cada hold ACTIVE produz o intervalo de `applied_at` até infinito. União de intervalos que se sobrepõem ou se tocam forma uma única pausa contínua. `retention_due_at` é exatamente `B` mais a soma das durações das componentes finitas dessa união. Enquanto houver componente aberta, ela não é adicionada prematuramente ao prazo, `retention_state=RETENTION_HELD` e `suspension_started_at` é o início dessa componente aberta. Quando a última hold que a mantém aberta é resolvida, sua duração inteira é adicionada uma única vez ao prazo e `suspension_started_at` fica nulo. Holds sobrepostas jamais somam duração em duplicidade.

retention_anchor_at é imutável. `active_hold_count` é a contagem exata de holds ACTIVE da mesma operação; `last_hold_event_at` é nulo sem evento e, caso contrário, é exatamente o maior `occurred_at` de seus eventos. Sem hold ACTIVE, RETENTION_RUNNING ou RETENTION_ELIGIBLE exige contagem zero e suspensão nula; RETENTION_ELIGIBLE só pode ser marcada por futura capability humana server-owned depois de prazo vencido, sem ação automática. Com hold ACTIVE, RETENTION_HELD exige contagem positiva e suspensão não nula. Em cada mudança de hold, `state_changed_at` é exatamente o instante do evento que causou a nova projeção. Não existe grant operacional de DELETE, e elegibilidade não remove FK para Pessoa, operação, receipt ou hold.

## Relação 5: public.e4b_consent_holds

Finalidade: metadado E4b de cada legal hold. O registro não armazena motivo jurídico, texto livre, telefone, conteúdo pastoral ou dados de canal. Esta relação não cria caller nem capability humana; a porta de hold definida adiante continua source-only e inativa em C3.

| Coluna | Tipo PG17 | Nula | Default | Finalidade e regra |
| --- | --- | --- | --- | --- |
| igreja_id | uuid | não | nenhum | Tenant obrigatório. |
| hold_id | uuid | não | nenhum | Identificador opaco E4b do hold. |
| operation_id | uuid | não | nenhum | Operação cuja retenção é suspensa. |
| hold_state | text | não | ACTIVE | ACTIVE ou RESOLVED. |
| policy_version | text | não | nenhum | Política vigente no HOLD_APPLIED. |
| applied_at | timestamp with time zone | não | nenhum | Instante do hold aplicado. |
| resolved_at | timestamp with time zone | sim | NULL | Instante da resolução, se existir. |

### Chaves, FKs, checks, índices e mutabilidade

- PK e4b_consent_holds_pkey: (igreja_id, hold_id).
- Unique e4b_consent_holds_identity_key: (igreja_id, hold_id, operation_id). É o alvo completo dos eventos.
- FK e4b_consent_holds_igreja_fkey: igreja_id para igrejas(id).
- FK e4b_consent_holds_operation_fkey: (igreja_id, operation_id) para e4b_consent_retentions(igreja_id, operation_id). Um hold sem retenção E4b não existe.
- Check e4b_consent_holds_state_check: ACTIVE exige resolved_at nulo; RESOLVED exige resolved_at maior ou igual a applied_at.
- Check e4b_consent_holds_policy_version_check: policy_version tem formato seguro de até 128 caracteres.
- Índice parcial e4b_consent_holds_active_operation_idx em (igreja_id, operation_id, applied_at) quando hold_state=ACTIVE.

Identidade, operação, política e aplicação são imutáveis. A única mudança é ACTIVE para RESOLVED, preenchendo uma vez resolved_at no mesmo staging conceitual que o evento de resolução e a projeção de retenção. Não há DELETE, reabertura, expiração automática ou substituição de hold_id.

## Relação 6: public.e4b_consent_hold_events

Finalidade: trilha imutável de eventos mínimos dos holds. Ela preserva que autoridade humana server-owned aplicou ou resolveu hold, sem expor identidade no receipt ou guardar motivo livre.

| Coluna | Tipo PG17 | Nula | Default | Finalidade e regra |
| --- | --- | --- | --- | --- |
| igreja_id | uuid | não | nenhum | Tenant obrigatório. |
| hold_event_id | uuid | não | nenhum | Identificador opaco do evento. |
| hold_id | uuid | não | nenhum | Hold E4b correspondente. |
| operation_id | uuid | não | nenhum | Operação retida, redundante apenas para fechar a FK composta. |
| event_kind | text | não | nenhum | HOLD_APPLIED ou HOLD_RESOLVED. |
| event_sequence | smallint | não | nenhum | 1 para aplicado e 2 para resolvido. |
| authority_app_user_id | uuid | não | nenhum | Admin humano interno que a capability futura validou. |
| authority_resolution_version | text | não | nenhum | Versão da capability server-owned usada no evento. |
| authority_resolution_sha256 | bytea | não | nenhum | Digest de 32 bytes da resolução, nunca projetado no receipt. |
| policy_version | text | não | nenhum | Versão de política no evento. |
| occurred_at | timestamp with time zone | não | nenhum | Instante UTC do evento. |

### Chaves, FKs, checks, índices e imutabilidade

- PK e4b_consent_hold_events_pkey: (igreja_id, hold_event_id).
- FK e4b_consent_hold_events_igreja_fkey: igreja_id para igrejas(id).
- FK e4b_consent_hold_events_hold_fkey: (igreja_id, hold_id, operation_id) para e4b_consent_holds_identity_key.
- FK e4b_consent_hold_events_authority_fkey: (igreja_id, authority_app_user_id) para app_users(igreja_id, id).
- Unique e4b_consent_hold_events_kind_key: (igreja_id, hold_id, event_kind).
- Unique e4b_consent_hold_events_sequence_key: (igreja_id, hold_id, event_sequence).
- Check e4b_consent_hold_events_kind_sequence_check: HOLD_APPLIED usa sequência 1; HOLD_RESOLVED usa sequência 2.
- Check e4b_consent_hold_events_digest_check: o digest de autoridade tem 32 bytes.
- Check e4b_consent_hold_events_versions_check: authority_resolution_version e policy_version têm formato seguro de até 128 caracteres.
- Índice e4b_consent_hold_events_timeline_idx em (igreja_id, hold_id, occurred_at).

Todas as colunas são append-only e imutáveis. Não há evento de remoção, expiração ou exclusão.

### Igualdades fechadas de hold, eventos e retenção

Para cada `(igreja_id, hold_id, operation_id)`, existe exatamente um `HOLD_APPLIED` com `event_sequence=1`. Seu `occurred_at` é exatamente `e4b_consent_holds.applied_at`, e seu `policy_version` é exatamente `e4b_consent_holds.policy_version`. HOLD_APPLIED é o único evento que pode corresponder a hold ACTIVE sem resolução.

Hold ACTIVE possui exatamente esse HOLD_APPLIED, nenhum HOLD_RESOLVED, `resolved_at IS NULL` e intervalo aberto. Hold RESOLVED possui exatamente um HOLD_APPLIED e um HOLD_RESOLVED com `event_sequence=2`; `HOLD_RESOLVED.occurred_at` é exatamente `e4b_consent_holds.resolved_at`, que é maior ou igual a `applied_at`. O `policy_version` de HOLD_RESOLVED é a versão server-owned resolvida no instante de resolução e pode diferir da versão do HOLD_APPLIED; nenhuma igualdade implícita entre as duas versões é permitida.

Para cada `(igreja_id, operation_id)`, a guarda diferida compara a contagem, a união de intervalos e o prazo descritos acima: `active_hold_count=COUNT(hold_state=ACTIVE)`; `retention_state=RETENTION_HELD` se e somente se essa contagem é positiva; `suspension_started_at` é nulo se e somente se não existe componente aberta e, quando existe, é exatamente seu início; `last_hold_event_at=MAX(occurred_at)` entre todos os eventos da operação; `retention_due_at=B+duracao(componentes_finitas)`; e `state_changed_at` é o `occurred_at` do último evento que mudou a projeção. A guarda também exige `retention_anchor_at=operations.confirmed_at`, que todo evento pertença ao mesmo tenant, hold e operação da FK composta, e que não exista retenção sem operação ou hold sem retenção.

## Guardas de imutabilidade e integridade inter-relação

FKs, uniques e checks são o mínimo declarativo. Cinco famílias de guardas da implementação C3 completam invariantes que envolvem mais de uma linha. Seus nomes, funções internas e triggers fazem parte do contrato de migration e dos testes PG17. A fase C3-SPEC não cria função ou trigger; a implementação C3 autorizada deverá criar exatamente os objetos internos abaixo. Eles não são funções expostas, não criam role e não recebem grant operacional ou EXECUTE direto.

| Guarda da implementação C3 | Momento | Regra fechada |
| --- | --- | --- |
| e4b_consent_immutable_guard | BEFORE UPDATE ou DELETE | Recusa qualquer alteração em operações, receipts e eventos; limita streams, retenções e holds às transições descritas. |
| e4b_consent_historical_authority_guard | antes da inserção de operação | Confere operator_role_links contra operator_id, titular, manifestante e responsável; a lista contém exatamente os papéis cujos IDs coincidem e preserva o shape histórico C2 sem inferência por igualdade. |
| e4b_consent_stream_transition_guard | BEFORE INSERT e BEFORE UPDATE em stream | Em INSERT só aceita ACTIVE sem campos de retirada; em UPDATE só aceita ACTIVE para WITHDRAWN uma vez, com igualdade de state_changed_at e confirmed_at da operação correspondente. |
| e4b_consent_hold_projection_guard | constraint trigger diferida no commit | Confere cada igualdade de hold, evento, contagem, suspensão, prazo e estado da projeção de retenção no mesmo tenant. |
| e4b_consent_chain_completeness_guard | constraint trigger diferida no commit | Exige um receipt e uma retenção para cada operação; exige stream ACTIVE para ACCEPT e atualização do mesmo stream para WITHDRAW. Uma cadeia parcial nunca pode ser confirmada. |

| Família | Função interna SECURITY INVOKER | Triggers físicos obrigatórios |
| --- | --- | --- |
| Imutabilidade | e4b_consent_immutable_guard_fn | e4b_operations_immutable_guard_trg, e4b_streams_immutable_guard_trg, e4b_receipts_immutable_guard_trg, e4b_retentions_immutable_guard_trg, e4b_holds_immutable_guard_trg e e4b_hold_events_immutable_guard_trg. |
| Autoridade histórica | e4b_consent_historical_authority_guard_fn | e4b_operations_historical_authority_guard_trg. |
| Transição de stream | e4b_consent_stream_transition_guard_fn | e4b_streams_transition_guard_trg. |
| Projeção de hold | e4b_consent_hold_projection_guard_fn | e4b_retentions_hold_projection_guard_ctrg, e4b_holds_hold_projection_guard_ctrg e e4b_hold_events_hold_projection_guard_ctrg, com a matriz de eventos abaixo. |
| Completude da cadeia | e4b_consent_chain_completeness_guard_fn | e4b_operations_chain_completeness_guard_ctrg, e4b_streams_chain_completeness_guard_ctrg, e4b_receipts_chain_completeness_guard_ctrg e e4b_retentions_chain_completeness_guard_ctrg, com a matriz de eventos abaixo. |

| Constraint trigger físico | Relação | Eventos exatos | Forma física obrigatória | Motivo de cada evento |
| --- | --- | --- | --- | --- |
| e4b_retentions_hold_projection_guard_ctrg | e4b_consent_retentions | INSERT, UPDATE | AFTER, CONSTRAINT, DEFERRABLE, INITIALLY DEFERRED, FOR EACH ROW | INSERT valida a projeção inicial; UPDATE valida toda reprojeção causada por hold. |
| e4b_holds_hold_projection_guard_ctrg | e4b_consent_holds | INSERT, UPDATE | AFTER, CONSTRAINT, DEFERRABLE, INITIALLY DEFERRED, FOR EACH ROW | INSERT agenda a aplicação; UPDATE agenda a única resolução permitida. |
| e4b_hold_events_hold_projection_guard_ctrg | e4b_consent_hold_events | INSERT | AFTER, CONSTRAINT, DEFERRABLE, INITIALLY DEFERRED, FOR EACH ROW | Cada HOLD_APPLIED ou HOLD_RESOLVED é append-only e agenda a conferência da trilha e da projeção. |
| e4b_operations_chain_completeness_guard_ctrg | e4b_consent_operations | INSERT | AFTER, CONSTRAINT, DEFERRABLE, INITIALLY DEFERRED, FOR EACH ROW | Toda operação nova precisa chegar ao commit com stream, receipt e retenção correspondentes. |
| e4b_streams_chain_completeness_guard_ctrg | e4b_consent_streams | INSERT, UPDATE | AFTER, CONSTRAINT, DEFERRABLE, INITIALLY DEFERRED, FOR EACH ROW | INSERT agenda a cadeia ACCEPT; UPDATE agenda a única transição WITHDRAWN. |
| e4b_receipts_chain_completeness_guard_ctrg | e4b_consent_receipts | INSERT | AFTER, CONSTRAINT, DEFERRABLE, INITIALLY DEFERRED, FOR EACH ROW | A criação de R agenda a confirmação de que sua cadeia não permanece parcial. |
| e4b_retentions_chain_completeness_guard_ctrg | e4b_consent_retentions | INSERT | AFTER, CONSTRAINT, DEFERRABLE, INITIALLY DEFERRED, FOR EACH ROW | A retenção inicial agenda a confirmação de que sua operação possui os demais elos. |

DELETE não é evento de nenhum desses sete constraint triggers: a tentativa de DELETE é recusada antes, pelo trigger de imutabilidade BEFORE da própria relação, e é provada pelos oráculos de imutabilidade. UPDATE tampouco é evento dos três registros append-only, operações, receipts e eventos de hold; a atualização de retenção pertence exclusivamente à projeção de hold. A ausência de cada evento não listado é deliberada, deve constar do catálogo e não pode ser ampliada sem migração de protocolo E4b versionada. Os seis triggers de imutabilidade são BEFORE UPDATE OR DELETE em suas relações. O trigger histórico é BEFORE INSERT em operações. O trigger de stream é BEFORE INSERT OR UPDATE em streams. As guardas não consultam legado, Pessoa mutadora, canal, mensagem, credencial ou dados externos. Todas as funções internas são SECURITY INVOKER, nunca SECURITY DEFINER, e não recebem EXECUTE direto de PUBLIC, anon, authenticated, service_role, agent_runtime ou harness. Não existe BYPASSRLS, fallback de owner ou caminho privilegiado em qualquer guarda.

## Cadeia, resultados e estados permitidos

Para ACCEPT, a porta futura encena no mesmo tenant: operação confirmável I com K, C e F; stream ACTIVE; retenção RETENTION_RUNNING; e receipt R. Para WITHDRAW, ela encena nova operação I cuja FK de origem aponta para ACCEPT E4b no mesmo stream, muda o stream para WITHDRAWN, cria retenção própria da retirada e cria seu R. A operação e o receipt do ACCEPT nunca são modificados.

| Relação | Estados persistíveis |
| --- | --- |
| e4b_consent_operations | somente CONFIRMED |
| e4b_consent_streams | ACTIVE, WITHDRAWN |
| e4b_consent_receipts | nenhum estado próprio; CONFIRMED é derivado exclusivamente da operação CONFIRMED ligada. |
| e4b_consent_retentions | RETENTION_RUNNING, RETENTION_HELD, RETENTION_ELIGIBLE |
| e4b_consent_holds | ACTIVE, RESOLVED |
| e4b_consent_hold_events | HOLD_APPLIED, HOLD_RESOLVED |

NEW, AUTHORIZED, LOCKED, STAGED, EXACT_REPLAY, CONFLICT, DENIED, NOT_FOUND, UNKNOWN, REJECTED e FAILED_ROLLED_BACK são fases ou resultados de serviço. Eles não são estados persistidos E4b. STAGED nunca significa CONFIRMED: somente o commit do owner externo torna a cadeia visível.

Para a mesma tupla (igreja_id, K), F idêntico reidrata somente operação e receipt históricos E4b como EXACT_REPLAY; F ou dimensão fechada divergente retorna CONFLICT, sem escrita nova. Colisão de C que não seja a mesma identidade fechada também é CONFLICT. Autoridade ausente, stream incompatível, origem ausente, origem de outro tenant, outro titular, outra finalidade, ACCEPT já existente ou stream WITHDRAWN resulta em DENIED ou falha interna sanitizada antes de staging. Nenhuma classificação consulta ou infere legado.

## RLS, GUC e ACL mínimos

### GUC e predicado obrigatório

O tenant de sessão é exclusivamente app.tenant_igreja_id. Antes de a porta ser chamada, o owner externo já abriu a transação e já fixou essa GUC para a transação. A porta não a cria, corrige, troca, limpa ou recebe de caller.

O predicado tenant de toda policy E4b segue estes passos exatos: ler `current_setting('app.tenant_igreja_id', true)`; negar se o resultado for nulo ou vazio; converter para UUID somente o valor presente; e comparar esse UUID ao igreja_id da linha. GUC malformada produz erro de parsing; GUC ausente, vazia ou divergente produz negação. Nenhum caso equivale a tenant público, NULL, tabela vazia confirmada ou ausência de operação.

O oráculo de GUC separa admissão de negação. Em cada uma das seis relações e para SELECT, INSERT, UPDATE e DELETE, a matriz registra relação, operação, tenant da linha-alvo, modo da GUC, papel efetivo, resultado e SQLSTATE ou contagem sanitizada. Com GUC A válida, o harness pode ler somente linhas A e executar apenas o DML de ciclo de vida E4b permitido para A; com GUC B válida, vale a mesma regra somente para B. Em ambos os ramos positivos, uma linha do outro tenant é invisível e não pode ser mutada. GUC ausente, vazia, malformada, A contra linha B ou B contra linha A produz erro ou zero leitura e zero efeito de DML. DML que a própria imutabilidade ou guarda de domínio proíbe para o mesmo tenant continua recusado pelo seu motivo normal; isso não substitui nem mascara a prova de isolamento por GUC e RLS.

Cada uma das seis relações deve receber ENABLE ROW LEVEL SECURITY e FORCE ROW LEVEL SECURITY. Para cada relação haverá duas policies FOR ALL TO PUBLIC, ambas com USING e WITH CHECK no predicado tenant acima:

| Relação | Policy permissiva, FOR ALL TO PUBLIC | Policy restritiva, FOR ALL TO PUBLIC |
| --- | --- | --- |
| e4b_consent_operations | e4b_operations_tenant_permissive | e4b_operations_tenant_restrictive |
| e4b_consent_streams | e4b_streams_tenant_permissive | e4b_streams_tenant_restrictive |
| e4b_consent_receipts | e4b_receipts_tenant_permissive | e4b_receipts_tenant_restrictive |
| e4b_consent_retentions | e4b_retentions_tenant_permissive | e4b_retentions_tenant_restrictive |
| e4b_consent_holds | e4b_holds_tenant_permissive | e4b_holds_tenant_restrictive |
| e4b_consent_hold_events | e4b_hold_events_tenant_permissive | e4b_hold_events_tenant_restrictive |

Uma policy somente restritiva não permite acesso em PostgreSQL. A permissiva existe somente para viabilizar o predicado de tenant; a restritiva duplicada mantém a barreira exigida para todo FOR ALL. TO PUBLIC não concede ACL, não seleciona principal operacional e não torna caller possível. Nenhuma policy usa identidade, tenant, papel ou capability fornecidos por modelo, DTO, receipt, K, C, F, valor legado ou caller.

Cada policy com sufixo permissive é declarada AS PERMISSIVE; cada policy com sufixo restrictive é declarada AS RESTRICTIVE. Não há helper SECURITY DEFINER, fallback de owner, valor padrão de tenant ou policy complementar para outro papel.

RLS não substitui autorização de domínio. O backend revalida igreja, identidade humana, papel, capability, estado de Pessoa, finalidade e origem por serviços de domínio antes e depois dos locks. A policy impede travessia de tenant. Ela não transforma conexão bruta, receipt ou GUC em autorização humana.

### Revokes, ausência de grant operacional e harness PG17

A migration C3 revoga explicitamente ALL em cada uma das seis relações, inclusive SELECT, INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES e TRIGGER, de PUBLIC, anon, authenticated, service_role e agent_runtime. Também revoga EXECUTE nas cinco funções internas de guarda desses mesmos papéis e concede EXECUTE a ninguém. Ela não concede DML operacional a papel algum. Também não concede privilégios em schema, sequência, trigger, tabela parental ou membership, nem cria role, papel privilegiado ou papel com BYPASSRLS. As policies permanecem defesa de tenant para qualquer ACL futura, mas não reabrem a ACL fechada desta C3.

| Objeto | PUBLIC | anon | authenticated | service_role | agent_runtime | Grant operacional C3 |
| --- | --- | --- | --- | --- | --- | --- |
| e4b_consent_operations | ALL revogado | ALL revogado | ALL revogado | ALL revogado | ALL revogado | nenhum |
| e4b_consent_streams | ALL revogado | ALL revogado | ALL revogado | ALL revogado | ALL revogado | nenhum |
| e4b_consent_receipts | ALL revogado | ALL revogado | ALL revogado | ALL revogado | ALL revogado | nenhum |
| e4b_consent_retentions | ALL revogado | ALL revogado | ALL revogado | ALL revogado | ALL revogado | nenhum |
| e4b_consent_holds | ALL revogado | ALL revogado | ALL revogado | ALL revogado | ALL revogado | nenhum |
| e4b_consent_hold_events | ALL revogado | ALL revogado | ALL revogado | ALL revogado | ALL revogado | nenhum |

O seam backend existente neste SHA, [backend/app/db/tenant_session.py](../../../backend/app/db/tenant_session.py), continua sendo apenas a âncora técnica que combina `app.tenant_igreja_id` transacional com `SET LOCAL ROLE authenticated`. C3 não escolhe authenticated como principal operacional e não lhe concede acesso E4b. C4 deverá escolher principal operacional, ACL e contrato de admissão antes de qualquer caller. Não há alegação sobre rota real de cliente, Data API, worker, runtime, owner, superuser ou qualquer papel vivo com BYPASSRLS.

Antes do replay, o bootstrap local e descartável exige que `anon`, `authenticated`, `service_role` e `agent_runtime` já existam na instância vazia. PUBLIC é o grantee implícito de PostgreSQL e não é uma role a criar. A ausência de qualquer uma das quatro roles nomeadas faz a rodada inteira falhar fechada antes do replay; a migration, o harness e o controlador não podem criá-las, recriá-las, renomeá-las ou suprir sua ausência. Essa pré-condição existe somente para tornar verificáveis os revokes candidatos e não infere atributos de papéis vivos.

Fora da migration, o bootstrap cria somente para a instância PG17 local descartável os papéis efêmeros `e4b_pg17_harness` e `e4b_pg17_controller`, destruídos com a instância. O harness é NOLOGIN, NOINHERIT, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION e NOBYPASSRLS, sem membership em outro papel. Recebe exatamente USAGE em `public`, nunca CREATE nesse schema, e SELECT, INSERT, UPDATE e DELETE somente nas seis relações E4b. Não recebe privilégio em Pessoa, AppUser, tabela parental, sequência, função, trigger, TRUNCATE, REFERENCES ou papel.

O controlador é o único principal local de teste autorizado a assumir papéis de oráculo. Ele é LOGIN somente na instância descartável, NOINHERIT, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION e NOBYPASSRLS; não recebe ACL operacional, admin, schema, tabela, função, sequência, trigger ou parental. Possui exatamente cinco memberships de bootstrap, todas com SET permitido, INHERIT falso e ADMIN falso, para `e4b_pg17_harness`, `authenticated`, `anon`, `service_role` e `agent_runtime`; não possui outra membership. Essas memberships não concedem grants de tabela, não alteram atributos das cinco roles alvo e o controlador não herda seus privilégios. Cada DML de oráculo ocorre somente após assunção explícita da role-alvo e registra a role efetiva. O administrador técnico da instância pode somente criar e destruir esse bootstrap fora do sujeito de teste; nunca executa DML E4b, não é fallback de owner e não satisfaz oráculo algum. Esses papéis, memberships, USAGE e grants existem somente no bootstrap, não entram no SQL candidato, não são ACL operacional e são destruídos com a instância.

O oráculo negativo local usa o controlador para assumir explicitamente authenticated, anon, service_role e agent_runtime, sempre sem GUC e sem ACL E4b, e registra a role efetiva em cada tentativa de SELECT e DML nas seis relações. Todas devem ser negadas. Esse é o substituto de teste para Data API nesta C3: não inicia Data API, não testa portal ou caller real e não afirma que qualquer rota exista ou não exista.

## Locks próprios E4b e ordem transacional

Não há lock em Pessoa, FOR UPDATE de Pessoa, lock de ledger ou alegação de ordem comum com legado. L é barreira advisory transacional própria do E4b e não substitui RLS, FKs, checks, uniques, revalidação ou autorização.

O protocolo é `e4b-advisory-lock:v1`. Cada texto de entrada é montado em UTF-8 canônico, sem BOM, NUL ou normalização implícita: rótulos ASCII literais, UUIDs já validados em formato minúsculo canônico, digest SHA-256 da codificação UTF-8 canônica de K em hexadecimal minúsculo e `finalidade_id` no formato canônico server-owned da intenção fechada. Cada classe usa seu seed público fixo, passa o texto e o seed diretamente a `hashtextextended` de PostgreSQL 17, recebe seu resultado `bigint` assinado sem recorte ou conversão para par de integers e chama `pg_advisory_xact_lock` com esse único `bigint`.

| Ordem de consentimento | Classe | Texto UTF-8 canônico | Seed público fixo | Uso obrigatório |
| --- | --- | --- | --- | --- |
| 1 | K | e4b:consent-operation:v1:<igreja_id>:<sha256(K)> | 2026091001 | `hashtextextended` e `pg_advisory_xact_lock`, depois lookup por (igreja_id, K). |
| 2 | L | purpose-consent-person-v1:<igreja_id>:<titular_pessoa_id> | 2026091002 | `hashtextextended` e `pg_advisory_xact_lock` por sujeito. |
| 3 | C | e4b:consent-correlation:v1:<igreja_id>:<correlation_id> | 2026091003 | `hashtextextended` e `pg_advisory_xact_lock`, depois lookup por (igreja_id, C). |
| 4 | stream | e4b:consent-stream:v1:<igreja_id>:<titular_pessoa_id>:<finalidade_id> | 2026091004 | `hashtextextended` e `pg_advisory_xact_lock`, depois bloqueio da linha E4b do stream se existir. |

Colisão de hash advisory pode somente serializar recursos não relacionados; nunca dispensa igreja_id, FKs, uniques, F, C ou stream. Uma transação de consentimento aceita exatamente um K, um sujeito, um C e um stream. Operação que toque dois sujeitos falha antes de adquirir lock. O owner externo fixa `lock_timeout` local em cinco segundos antes de qualquer aquisição, e a porta falha fechada se o valor local não estiver presente e exato; ela não o amplia nem desabilita.

A sequência de consentimento é: validar tenant, transação, entrada fechada e estado de sessão; K; L; C; stream; revalidar autoridade, Pessoa, origem, ação, F e estado sob todos os locks; capturar o único confirmed_at; encenar cadeia; fazer no máximo flush; devolver controle ao owner. Timeout, deadlock, erro de lock, FK, RLS, check, trigger ou revalidação fazem o owner reverter toda a transação; não há retry cego, unlock manual, commit parcial, receipt especulativo ou envio. Advisory locks são liberados pelo commit ou rollback do owner.

O caminho de hold não toma K, C ou stream. Ele toma somente L da mesma fórmula e seed, bloqueia com FOR UPDATE e relê a retenção E4b correspondente, revalida a autoridade server-owned e só então encena uma aplicação ou resolução de hold. Isso serializa hold por sujeito sem alegar serialização, progresso, ordem ou prova bilateral com legado, mutador de Pessoa ou exclusão.

`e4b-advisory-lock:v1` está vinculado à semântica de `hashtextextended` em PG17. Upgrade de major, alteração de encoding, seed, texto canônico, função de hash ou forma do argumento exige migração de protocolo E4b separada e versionada antes de uso: ela deve preservar exclusão mútua durante a transição, provar compatibilidade entre versões e nunca substituir v1 silenciosamente no mesmo candidato.

## Contratos source-only das portas de staging

C2 contém somente E4bReplayReadPort e E4bReconciliationReadPort, abstratas e read-only. C3-SPEC não altera C2. C3 fecha dois contratos de staging para a implementação source-only, mas o adapter permanece inativo: não há principal operacional, ACL operacional, caller, runtime ou DML operacional em C3. C4 deverá escolher principal, ACL e admissão de caller antes de qualquer ativação.

### E4bConsentStagingPort

| Entrada fechada | Exigência |
| --- | --- |
| Transação externa | Já aberta, tenant-scoped e pertencente ao owner. A porta nunca abre, fecha, confirma ou reverte transação. |
| Sessão futura | GUC app.tenant_igreja_id exata, RLS habilitada e forçada, lock_timeout local de cinco segundos e principal operacional ainda não escolhido. O harness usa somente e4b_pg17_harness. |
| Intenção resolvida | I, K, C, F, ação, origem E4b quando houver, finalidade, versões e digests calculados pelo servidor. Não recebe DTO livre. |
| Autoridade resolvida | Titular, manifestante, responsável quando aplicável, operador, capability e estado de domínio rederivados pelo servidor. Nenhum booleano ou identificador de caller é prova. |
| Receipt | Projeção derivada internamente conforme a allowlist deste documento. Não é entrada de caller. |

Sob K, L, C e stream, a porta relê K, C, stream e origem E4b, revalida tudo, captura o único confirmed_at e só então encena operação, stream, receipt e retenção. Ela devolve somente resultado interno de staging: STAGED, EXACT_REPLAY, CONFLICT, DENIED ou falha interna sanitizada. STAGED não confirma commit. A porta não emite CONFIRMED, não faz reconciliação, não reenvia, não chama WhatsApp, não consulta legado, não cria caller e não inicia runtime.

### E4bConsentHoldStagingPort

Esta porta é separada da porta de consentimento e também é source-only e inativa em C3. Recebe transação externa já aberta, tenant e autoridade humana server-owned rederivados, operação E4b e hold resolvidos internamente. Ela não recebe DTO de caller, não cria capability humana e não abre, fecha, confirma ou reverte transação.

Sua sequência é: validar sessão e entrada fechada; tomar somente L do sujeito da operação; bloquear com FOR UPDATE e reler a linha correspondente de e4b_consent_retentions; revalidar autoridade e estado; capturar uma vez hold_event_at; encenar exclusivamente um HOLD_APPLIED ou um HOLD_RESOLVED, a mudança permitida de hold e a projeção de retenção; fazer no máximo flush; devolver controle ao owner. Ela não toma K, C ou stream, não bloqueia Pessoa, não faz FOR UPDATE de Pessoa, não cria ou executa mutador ou exclusão de Pessoa e não toca Igreja.

Em falha, ambas as portas propagam erro sanitizado ao owner, que decide rollback. Após acknowledgement perdido ou commit incerto, sessão nova tenant-scoped usa somente porta C2 read-only de reconciliação e retorna CONFIRMED, NOT_FOUND ou UNKNOWN; não faz DML ou retry cego. O único DML físico exercitável em C3 é o do harness PG17 descartável, sob o papel temporário não operacional descrito na ACL.

## Retenção, reidentificação e limites de exclusão

O vínculo identificável entre operação e titular_pessoa_id permanece interno na operação e stream durante, no mínimo, 24 meses efetivos. Receipt não desempenha reidentificação. Somente fluxo administrativo futuro, com admin da mesma igreja rederivado pelo backend e capability própria, pode usar relações internas para reidentificar.

Hold é somente metadado E4b de retenção. Aplicar ou resolver hold, mutar ou excluir Pessoa, arquivar Pessoa, excluir Igreja, dispor registro elegível ou remover cadeia são missões separadas. Esta especificação não cria cascade, DELETE, anonimização, expiração automática ou mutador. Enquanto retenção estiver RETENTION_RUNNING ou RETENTION_HELD, futura exclusão de Pessoa deve falhar fechado ou ser adiada pelo fluxo que adquirir sua barreira própria. Mesmo em RETENTION_ELIGIBLE, esta C3 não autoriza disposição.

## Sequência autorizada e replay técnico PG17 local descartável

O freeze documental preliminar é commit local técnico já autorizado, contém somente esta especificação R4 e não é gate humano. A sequência técnica autorizada é: revisão independente; freeze documental; `new_migration.py draft` TENANT no SHA congelado; registro do basename; implementação C3; `prepare-head`; replay técnico em PostgreSQL 17 local descartável; e revisão final. O único próximo gate humano é o commit local do candidato C3 completo e exato, somente depois dessas subetapas. Ele não autoriza aplicação operacional de migration, DEV, PROD, banco compartilhado, caller, runtime, integração ou efeito externo.

O replay roda uma única vez em PostgreSQL 17 local, vazio, identificado e descartável. Não chama aplicador operacional, não recebe DSN compartilhado, não acessa DEV ou PROD e usa somente tenants e identificadores sintéticos. Antes do replay, o bootstrap comprova as quatro roles revogadas e cria harness, controlador e suas cinco memberships conforme a ACL desta especificação; os papéis efêmeros e essas memberships são destruídos com a instância. Ausência de pré-condição, SQL candidato, função interna, trigger, papel de harness, controlador, membership ou oráculo bloqueia a rodada inteira; não autoriza skip, xfail, xpass, dublê em memória ou inspeção manual substitutiva.

| Nodeid físico obrigatório | Oráculo PG17 local, binário e sem skip |
| --- | --- |
| E4B-PG17-CATALOG-001 | Compara pg_catalog ao manifesto R4: exatamente as seis relações, nenhuma relação E4b extra, tabela de lock, sequência E4b, view, enum, materialized view ou função exposta; todas as colunas, tipos PG17, nulidade, defaults, PKs, FKs compostas, ON UPDATE e ON DELETE RESTRICT, checks, uniques, índices, policies, funções internas e triggers físicos nomeados. Para cada um dos sete constraint triggers, confere a lista exata de eventos INSERT, UPDATE e DELETE, inclusive ausência deliberada, timing AFTER, marca CONSTRAINT, DEFERRABLE, INITIALLY DEFERRED e FOR EACH ROW. Confirma a allowlist exata do receipt, ausência de identificador direto de Pessoa e de receipt_state. |
| E4B-PG17-PARENT-001 | Em fixture sintética, confirma igrejas(id), pessoas(igreja_id,id) e app_users(igreja_id,id) com as chaves parentais exigidas; uma variação sem âncora falha antes do DDL E4b. |
| E4B-PG17-RLS-001 | Para cada relação, confirma ENABLE e FORCE RLS e as doze policies pelo nome, AS PERMISSIVE ou AS RESTRICTIVE, FOR ALL TO PUBLIC, USING, WITH CHECK e predicado de current_setting com missing_ok. |
| E4B-PG17-GUC-001 | Sob `e4b_pg17_harness`, executa a matriz por relação e por SELECT, INSERT, UPDATE e DELETE. GUC A válida admite somente leitura e DML de ciclo de vida permitidos em A, sem leitura ou mutação B; GUC B válida faz o análogo somente em B. Para GUC ausente, vazia, malformada e divergente A contra B ou B contra A, exige erro ou zero leitura e zero efeito. Registra relação, operação, tenant-alvo, modo GUC, papel efetivo, resultado e SQLSTATE ou contagem sanitizada; não credita negação por imutabilidade como prova de RLS. |
| E4B-PG17-ACL-001 | Antes do replay, confirma que anon, authenticated, service_role e agent_runtime existem, ou bloqueia a rodada. Confirma ALL revogado de PUBLIC e das quatro roles em cada relação; ausência de grants em parentais, funções, triggers e sequências; ao harness somente USAGE em public sem CREATE e os quatro grants de tabela nas seis relações; atributos, ausência de memberships e NOBYPASSRLS do harness. Inspeciona que o controlador único NOINHERIT, sem ACL operacional ou admin, possui exatamente cinco memberships, para harness, authenticated, anon, service_role e agent_runtime, todas com SET permitido, INHERIT falso e ADMIN falso, sem membership adicional. Registra a role efetiva em cada tentativa sob cada uma das cinco roles-alvo, confirma ausência de grants de tabela ou alteração de atributos nas quatro roles negativas e prova que papéis e memberships efêmeros são destruídos com a instância. Também confirma nenhuma SECURITY DEFINER, owner fallback, EXECUTE direto em guarda ou SELECT ou FOR UPDATE em Pessoa. Não infere atributos de papéis vivos fora do candidato. |
| E4B-PG17-DATAAPI-001 | Sem iniciar Data API, assume authenticated, anon, service_role e agent_runtime sem GUC e sem ACL E4b e exige negação de SELECT e de cada DML nas seis relações. O nodeid não afirma nem testa rota real, portal, caller ou runtime. |
| E4B-PG17-CHAIN-001 | ACCEPT sintético completo devolve STAGED e cria, no mesmo commit, operação CONFIRMED, stream ACTIVE, receipt derivado e retenção; ele aciona INSERT de operations, streams, receipts e retentions. WITHDRAW sintético válido aciona INSERT de operations, receipts e retentions e UPDATE de streams. Cada omissão ou cadeia parcial falha no commit diferido pela e4b_consent_chain_completeness_guard e deixa zero estado. O nodeid registra o agendamento e a validação no commit de cada evento listado para a família; verificações de DELETE e UPDATE não listados permanecem em imutabilidade. Verifica todas as cópias de confirmed_at. |
| E4B-PG17-CHAIN-002 | WITHDRAW válido devolve STAGED e referencia ACCEPT ativo da mesma igreja, titular e finalidade; origem de outro tenant, titular ou finalidade, origem ausente, stream WITHDRAWN, inserção direta de stream WITHDRAWN ou novo ACCEPT devolvem DENIED ou falha interna sanitizada, sem escrita adicional. |
| E4B-PG17-REPLAY-001 | Mesmo K e F devolve EXACT_REPLAY sem nova linha; K com F ou dimensão fechada divergente e C colidida com identidade distinta devolvem CONFLICT, sem nova operação, receipt, stream ou retenção. Nenhuma decisão consulta legado. |
| E4B-PG17-IMM-001 | Exercita a e4b_consent_immutable_guard com UPDATE e DELETE de operação, receipt e hold_event; cada tentativa falha. |
| E4B-PG17-IMM-002 | Exercita a e4b_consent_stream_transition_guard e somente as transições permitidas: INSERT de stream ACTIVE, ACTIVE para WITHDRAWN uma vez, hold ACTIVE para RESOLVED uma vez e projeção de retenção derivada. Recusa reversão, reabertura, troca de chave, sujeito, finalidade, operação ou state_changed_at divergente. |
| E4B-PG17-AUTH-001 | Exercita a e4b_consent_historical_authority_guard para todas as coincidências e não coincidências de operator_id, titular, manifestante, responsável e operator_role_links, incluindo ordem, duplicidade, papel omitido e papel excedente. |
| E4B-PG17-RET-001 | Confirma confirmed_at capturado uma vez após locks e antes de staging, visível somente no commit, e add_24m_utc em TimeZone UTC e não UTC, anos bissextos e todas as bordas de mês, sem auto-disposição. |
| E4B-PG17-HOLD-001 | Exercita a e4b_consent_hold_projection_guard e E4bConsentHoldStagingPort com somente L: a cadeia inicial aciona INSERT de retentions; aplicar hold aciona INSERT de holds e hold_events e UPDATE de retentions; resolver hold aciona UPDATE de holds, novo INSERT de hold_events e novo UPDATE de retentions. O nodeid registra o agendamento e a validação no commit de cada evento listado para a família. Também cobre primeiro hold, holds sobrepostas, eventos 1 e 2, igualdade de instantes e política, contagem, componente aberta, componente finita, prazo acumulado sem duplicidade, última resolução, estados e trigger diferida. Duas sessões concorrentes na mesma operação demonstram serialização pela retenção bloqueada. |
| E4B-PG17-LOCK-001 | Com duas sessões e barreira determinística, confirma para consentimento K, L, C e stream na ordem, texto UTF-8, seeds, hashtextextended, bigint assinado, pg_advisory_xact_lock, lock_timeout local de cinco segundos, uma tupla por transação, ausência de FOR UPDATE em Pessoa e liberação por commit ou rollback. Confirma que hold toma apenas L. |
| E4B-PG17-ROLLBACK-001 | Induz falha após operação, stream, receipt, retenção, hold, evento e validação diferida; após rollback verifica zero cadeia ou projeção parcial e locks liberados. |
| E4B-PG17-COMMIT-001 | Separa falha pré-commit de acknowledgement perdido pós-decisão; em sessão nova tenant-scoped somente leitura, reconciliação retorna apenas CONFIRMED, NOT_FOUND ou UNKNOWN e não faz DML. |
| E4B-PG17-NOSKIP-001 | Coleta e executa todos os nodeids desta tabela no mesmo SHA candidato, com skipped=0, xfail=0, xpass=0, sem seleção oculta ou dublê em memória. |

Cada nodeid registra pré-condições sintéticas, resultado esperado binário, SQLSTATE ou contagem sanitizada quando aplicável, hash de SQL, hash de patch, SHA candidato, versão PG17, papel efetivo, matriz objeto por privilégio, horário com fuso e destruição da instância. Teste verde prova somente os nodeids executados nesse candidato e nessa instância.

## Rollback e gate

Nesta C3-SPEC, rollback é abandonar o arquivo documental não commitado ou revertê-lo em revisão posterior. Não há migration, banco, dado, role, grant efetivo, processo, ambiente ou efeito a compensar.

Depois do freeze técnico, rollback da continuidade autorizada significa descartar o draft não aplicado e destruir somente a instância PG17 descartável identificada pela missão. A migration não é aplicada operacionalmente. Mudança compartilhada exigirá migration forward-only e gate próprio; esta especificação não autoriza rollback por DDL manual, DROP, aplicação reversa, DEV ou PROD.

O freeze documental preliminar não é gate humano. O próximo gate humano único continua sendo autorização nominal para o commit local do candidato C3 completo, exato e revisado, após implementação, PG17 e revisão final. Ele não autoriza aplicação operacional de migration, DEV, PROD, banco compartilhado, caller, runtime, integração ou efeito externo; qualquer admissão de caller permanece para C4.

## Critérios de revisão da C3

- Existem somente seis relações E4b declaradas, e cada uma tem colunas, tipos PG17, nulabilidade, defaults, chaves, FKs, checks, índices e regra de imutabilidade explicitados.
- I, K, C, F e R têm semânticas distintas, cadeia tenant-scoped, idempotência e receipt minimizado fechados.
- Toda relação carrega igreja_id; vínculos com Pessoa e AppUser são compostos; deletes e cascades E4b permanecem proibidos.
- RLS, GUC, ENABLE, FORCE, policies FOR ALL TO PUBLIC com WITH CHECK, revokes totais e ausência de grant operacional estão declarados por relação; o bootstrap descartável falha se as roles revogadas não existirem, e a única exceção local é USAGE sem CREATE mais grants de tabela ao harness, assumido explicitamente por controlador NOINHERIT com exatamente cinco memberships de bootstrap sem herança ou administração.
- Locks E4b, ordem, timeout, transação externa e ausência de alegação bilateral com legado estão explícitos.
- As portas source-only de consentimento e hold fecham a lacuna C2 sem criar caller, runtime, principal operacional ou ownership de commit ou rollback.
- Retenção de 24 meses e hold existem somente como metadados E4b, sem delete ou disposição implementados.
- Cada constraint trigger de projeção ou completude tem eventos, timing, marca CONSTRAINT, deferrability, initial deferment e granularidade FOR EACH ROW fechados e exercitados pelo respectivo nodeid.
- Replay PG17 local descartável, limites e rollback técnico estão definidos sem inferir aplicação operacional.
