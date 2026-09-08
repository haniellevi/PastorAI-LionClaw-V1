# Evidence store de consentimento — desenho documental v1

Estado: **PROPOSTA LOCAL / SINTÉTICA / SEM APROVAÇÃO / SEM RUNTIME**.
Base: `939e90fe634ffd72f682665f62670d3e9fd7e87e` (PR #380).
O pacote continua `DRAFT_NOT_APPROVED`, `controller_approved=false`,
`catalog_ready=false`, `writer_eligible=false`, `operational_authorization=false`
e `next_stage_authorized=false`. Um contrato/teste documental pronto não
significa `presentation_and_manifestation_evidence_implemented=true` nem
`durable_receipt_implemented=true` em operação. Não há backend novo nesta entrega.

Fontes: [pacote, seções 9–14](../d2b2b2-decision-packet-tarefas-operacionais.md),
[template](../d2b2b2-decision-packet.template.json),
[catálogo proposto](../catalog/CONTRACT.md).

## 1. Três superfícies, três responsabilidades

| Superfície | Guarda/prova | Não prova |
|---|---|---|
| ledger D2B2a | Eventos de estado `concedido` ou `retirado`, por igreja/pessoa/finalidade | Qual aviso apareceu e qual interação correspondeu à escolha |
| evidence store | Metadados sanitizados da apresentação, desafio individual e manifestação correlacionada | Estado vigente do ledger, aprovação jurídica ou autorização de ação de domínio |
| recibo | Representação mínima da escolha, entregue ao titular somente após commit confirmado | Leitura, vontade, aprovação do pacote ou sucesso de transporte só por existir um identificador |

O catálogo congela conteúdo/versão, não registra a manifestação de uma pessoa.
Nenhuma dessas superfícies isolada autoriza automação. O exemplo referencia o
catálogo fictício da **Igreja Exemplo**; não aponta para uma igreja real.

## 2. Dados mínimos sanitizados

O envelope fechado de [evidence.schema.json](evidence.schema.json) contém:

- Identidade: `evidence_id`, `tenant_ref`, `controller_ref`, `person_ref`,
  `purpose`. São UUIDs opacos; tenant/pessoa/controlador precisam vir de fonte
  server-side autenticada, não do texto, modelo ou cliente.
- Conteúdo: `package_id`, `package_version`, `catalog_entry_digest`,
  `content_digest`, `notice_version`, `notice_text_digest`, `language`, `channel`.
  Versão e canal vinculam o aviso exato, sem copiá-lo para o registro individual.
- Apresentação: `presented_at`, `timezone`, `renderer_version`, `delivery_state`,
  `correlation_id`.
- Desafio: `challenge_ref`, `created_at`, `expires_at`, `single_use_state`.
- Manifestação: `selected_action`, `manifested_at`, `actor_ref`,
  `authentication_method_ref`, `interaction_ref`.
- Sujeito: faixa etária mínima e slots de vínculo de responsável; ver o limite
  adulto deste perfil abaixo. Nunca documento civil ou data de nascimento.
- Idempotência/correlação: `idempotency_key`, `durable_receipt_ref`,
  `previous_event_ref`, `withdrawn_event_ref`.
- Integridade: `schema_version`, `integrity_algorithm`, `evidence_digest`,
  `immutable_storage_ref`; flags invariavelmente falsas e marcador sintético.

Todos os objetos têm `additionalProperties=false`. Não existe campo genérico
`metadata`, texto livre de evento, justificativa ou payload de provedor. Não
guardar CPF, documento/imagem civil, telefone em claro, e-mail pessoal,
endereço, texto de mensagem/conversa, áudio, transcrição, relatório pastoral,
motivo íntimo, prompt, token, segredo, credencial ou biometria. Não guardar
hash simples de telefone/documento como suposta anonimização: é reversível por
enumeração. Referências são aleatórias e a associação fica em custódia privada.

Sanitizado **não significa anônimo**. UUIDs vinculáveis à pessoa e finalidade
religiosa continuam privados; nunca publicar evidência real em Git, CI,
issues, logs ou chat. Os únicos arquivos exemplificativos aqui são sintéticos.
Regex/allowlist não detectam todo segredo disfarçado em um identificador válido;
origem controlada, minimização e revisão de conteúdo continuam obrigatórias.

## 3. Perfil documental e limites explícitos

Versão `consent-evidence/design-v1`, `artifact_state=SYNTHETIC_EXAMPLE_NOT_OPERATIONAL`.
O perfil cobre adulto em escolha própria, `age_band=ADULT`, `actor_ref=person_ref`.
Slots de responsável e aviso infantil são nulos, `minor_view_state=NOT_APPLICABLE`.
Menor, idade desconhecida, representante ou evidência de vínculo ausente são
recusados. Isso não declara política de menores implementada ou inaplicável ao
produto: extensão específica precisa cumprir o pacote antes de aceitar esses
casos, incluindo interesse da pessoa menor e participação do responsável.

O exemplo aceita somente UTC em timestamps completos e versões fictícias de
aviso/renderer. Datas devem existir no calendário. O schema é uma forma mínima
de ensaio, não um schema operacional já apto a receber qualquer pacote real.
Não há leitura automática de arquivo externo, URL, assinatura ou segredo.

## 4. Vínculo ao conteúdo e à fonte confiável

1. Validar a entrada de catálogo contra schema, resolução de refs, hashes e
   âncora independente confiável. Não aceitar a âncora que vier no próprio
   registro como fonte de verdade.
2. Conferir tenant, finalidade, pacote, versão e `content_digest` entre fonte
   server-side, catálogo e evidência. `content_digest` mantém a fórmula já
   aprovada estruturalmente: SHA-256 JCS apenas de `decision_payload`.
3. `notice_text_digest` é SHA-256 dos bytes UTF-8 do texto exato selecionado em
   `notice_texts_by_channel_and_language`, sem trim ou normalização. Não é o
   hash da mensagem individual. Não rebatizar esse hash como `content_digest`.
4. Conferir pessoa/ator, controlador, canal, idioma, versão de aviso, interação,
   método de autenticação, correlação, desafio e horários contra observação
   independente. Os testes usam uma fixture confiável separada do registro.
5. `evidence_digest` é SHA-256 JCS do envelope inteiro excluindo apenas
   `evidence_digest`. Usa o subconjunto canônico do catálogo: strings válidas,
   booleanos, nulos, arrays/objetos; números e chaves duplicadas são recusados.
   Um hash recalculado prova somente consistência. Autenticidade e imutabilidade
   exigem âncora anterior autenticada/custódia, não implementadas aqui.

Em execução futura, o renderer/canal precisa provar a observação ligada a essa
tupla. Preencher um DTO com `presented_at` ou um digest não prova apresentação.
O schema documental não autentica provedor, sessão ou pessoa. O catálogo
sintético está congelado somente para o teste, não aprovado operacionalmente.

## 5. Apresentação, entrega e manifestação

Entrega de mensagem não prova leitura ou vontade. Nem `DELIVERED`, `READ`,
autenticação prévia, ausência de erro, silêncio, `sim`, `ok`, emoji ou reação
sem escolha explícita e desafio ativo equivalem a `ACCEPT`.

`delivery_state` descreve somente transporte/renderização: `PRESENTED`,
`DELIVERED`, `UNKNOWN`, `FAILED`. Estado `UNKNOWN` não invalida por si só uma
escolha cuja apresentação/interação foi independentemente comprovada; nunca
preenche essa prova ausente. `FAILED` não satisfaz este perfil de manifestação
concluída. O perfil não possui estado de vontade derivado de leitura.

O desafio é individual, de uso único e vinculado à mesma tupla de contexto.
Criado antes da apresentação, expira após no máximo 30 minutos. A manifestação
deve ocorrer depois da apresentação e **antes** da expiração. O ensaio adota
limite absoluto de 30 minutos também no painel, mais restrito que o limite
de inatividade do pacote. Sessão expirada/desconhecida continua negada pelo
futuro autenticador; não se presume duração de sessão a partir do timestamp.
Mudança material de aviso exige outro conteúdo/digest e novo desafio.

Encaminhamento, edição posterior, origem/sessão divergente e interação ambígua
negam a correlação. Enum `selected_action` somente pode ser obtido por controle
explícito e parser determinístico confiável do roteiro aprovado, não inferido
por LLM. O registro de exemplo tem desafio `CONSUMED`, mas isso é dado fictício,
não consumo durável realizado pela missão.

## 6. Recusa inicial, retirada e ledger

`REFUSE_INITIAL` exige projeção anterior `ausente`, sem evento anterior nem
retirada referenciada. Produz somente evidência da recusa e futuro recibo,
**nenhum evento `concedido` ou `retirado`**. O ledger permanece ausente e a
automação não é autorizada. Evitar insistência depende da política de UX e
retenção aprovada; o catálogo não inventa um prazo para igreja real.

Recusa inicial não é retirada de concessão existente. Se houver concessão,
esse perfil não a apaga nem a reclassifica como ausência: exige fluxo explícito
de retirada. `WITHDRAW` vincula evento anterior concedido observado server-side;
uma implementação futura registraria `retirado`. Aceitação explícita é apenas
evidência candidata a concessão, nunca um writer ou uma aprovação humana.

O teste retorna categorias prospectivas em memória, como `NO_LEDGER_EVENT` e
`FUTURE_CONCESSION_REQUIRES_WRITER`. Não contém SQL, INSERT, ledger em memória
apresentado como persistência real ou chamada ao serviço de concessão.

## 7. Idempotência e atomicidade futuras

Chave aleatória server-side, não derivada de telefone ou mensagem, escopada por
tenant/pessoa/finalidade. Desafio/interação são também de uso único nesse escopo.
Retry exato retorna evidência e recibo originais; mesma chave/desafio/interação
com decisão, digest ou vínculo diferente causa conflito, sem sobrescrever.
Trocar apenas a chave não reutiliza um desafio consumido. Escopos de igrejas
diferentes são independentes e acesso cruzado deve ser negado pelo backend/RLS.

A prova documental compara fixtures: não cria índice único, trava, storage,
transação ou recibo durável. A implementação posterior precisará serializar
desafios/retries, provar isolamento cross-tenant e atomicidade entre evidência,
recibo e evento de ledger quando aplicável. Para recusa inicial, atomicidade
envolve evidência+recibo, sem evento de estado.

Somente após commit comprovado o recibo pode ser apresentado ao titular. Commit
ambíguo não autoriza retry cego ou mensagem de sucesso; requer reconciliação
durável. `durable_receipt_ref` e `immutable_storage_ref` no exemplo são UUIDs
fictícios, não provas de existência de storage/commit/entrega. O campo
`receipt_delivery_state=NOT_SENT` permanece fixo neste perfil.

O recibo destinado à pessoa mostrará apenas escolha, horário/fuso, canal,
versão, identificador opaco e orientação para direitos/retirada. Não copiar o
envelope interno inteiro: ele contém vínculos privados de pessoa, ator e
custódia que não pertencem ao recibo público.

## 8. Custódia, assinatura, retenção e pendências

Dependem de materialização externa: payload real final, refs concretas,
assinaturas e registros nominais contra o digest correto, identidade e
competência dos responsáveis, política por finalidade/idade, prova da
apresentação e interação, autenticação de origem e armazenamento privado.
Não solicitar nem versionar essas evidências reais nesta missão.

Custódia deve prever acesso mínimo tenant-scoped, criptografia/chaves fora do
repositório, ancoragem/integridade verificáveis, auditoria sem conteúdo, prazos
e eliminação das cópias/backups, e eventual conservação excepcional aprovada.
Imutabilidade não significa retenção infinita nem revoga exclusão aplicável;
o procedimento de eliminação/atestado sanitizado exige contrato posterior.
Nenhum prazo ou mecanismo de custódia foi provisionado aqui.

O template exige seis registros de papéis nominais para elegibilidade do writer,
observando a exceção formal de revisor jurídico não designado. Além disso,
exige consent_based_operation, estado CATALOG_BOUND, binding server-side,
evidência/recibo duráveis e autorização técnica separada. Este desenho não
satisfaz implementação operacional desses componentes. Portanto não é prova
de que só falta o lado humano ou de que o agente está pronto para enviar.

Próximo gate de governança preservado e fechado:
`OWNER_AUTHORIZE_REVIEW_CONSENT_PACKET_TAREFAS_OPERACIONAIS`.
Sem consumo nesta missão, sem outro gate operacional proposto.

## 9. Verificação e reversão

Arquivos: este contrato, `evidence.schema.json`,
`examples/igreja-exemplo-refusal.synthetic-example.json` e
`backend/tests/test_consent_evidence_store.py`, mais notas de índice em
PRD-COVERAGE/Wiki. O interpretador restrito de JSON Schema e o subconjunto JCS
existentes nos testes do catálogo são reutilizados offline. Sem instalar
dependência, resolver schema pela rede ou criar validator de produção.

Aceite: evidência sintética válida; dados sensíveis/campos livres negados;
refusa sem concessão; digest/tenant/pessoa/aviso divergentes negados; entrega
sem escolha insuficiente; desafio expirado e reuso conflitante recusados;
todos os gates falsos. Não se infere segurança em produção desses testes.

Reversão: não adotar os arquivos desta worktree isolada; preservar arquivos,
branches e trabalho de outras sessões. Nenhuma migration ou estado de banco
exige rollback porque nenhum banco será acessado.

### Evidência local desta proposta

Verificado em `2026-09-08T00:43:16Z`, na worktree
`consent-evidence-store-design-v1`, sobre a base
`939e90fe634ffd72f682665f62670d3e9fd7e87e`, com alterações locais sem commit.
Os cinco arquivos de testes documentais (evidence store, catálogo imutável,
schema do payload, exemplo de digest e decision packet docs) concluíram com
**181 passed, zero falhas e zero skips**, em 3,97 segundos.

Execução na imagem local `pastorai-agent-local-validation-v1-backend:3799272`,
com `--pull never --network none --read-only`, fonte montada somente leitura,
ambiente explícito sem credenciais, caches desabilitados e sem banco.
`git diff --check` terminou com exit 0. A revisão independente documental
não identificou bloqueador; o teste inclui colisão de chaves entre tenants
sem reaproveitamento de recibo de outra igreja.

Hashes SHA-256 dos artefatos exercitados (não são digest oficial de igreja):

- Schema: `e29c941db4c8792258ed26790e08734c33e7e5fb04f82cebc35ea79c7d3b67a9`.
- Exemplo: `e8b0dfc4e85e8c3aafb3235cf15ae1412fc15a9da97380f86e1f86ab25d60e14`.
- Teste: `0dc071022b24f52eea7a0ffe2163abe5a3a6ee8aa34a695d2d959777903d8441`.

A base já estava disponível localmente: nenhum fetch ou acesso à rede foi
necessário. Somente branch/worktree próprias e os arquivos desta proposta
foram criados/alterados; sem efeito externo, dado real, aprovação ou envio.
