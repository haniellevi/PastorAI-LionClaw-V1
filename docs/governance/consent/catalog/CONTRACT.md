# Catálogo imutável de consentimento — proposta técnica v1

## Evolução local: payload congelado v2

Proposta offline sobre `48941f2ac05addbd7c7c105776f81eeb5a385991`.
As seções v1 abaixo permanecem históricas e normativas somente para
`consent-catalog/design-v1`. O exemplo sintético e seus digests não mudam.
O schema admite dois perfis fechados, sem flexibilizar o v1.
Nenhuma entrada real é criada nesta rodada.

O perfil `consent-catalog/frozen-payload-v2` aceita `synthetic_only=false`
e `controller_approved=true` como registro humano externo, não uma aprovação
feita pelo schema. Exige `human_packet_complete=false`, `catalog_ready=false`,
`writer_eligible=false`, `operational_authorization=false` e
`next_stage_authorized=false`, mesmo com todas as referências resolvidas.

### Custódia e preservação

`source_payload` e `decision_payload` são apontadores idênticos contendo
somente `custody_ref` e `content_digest`. Não embutem nem transformam payload.
`approval_custody_ref` identifica separadamente a custódia da assinatura.
As refs de custódia aceitam exclusivamente `ref:sha256:<64 hex minúsculos>`,
sem caminhos, nomes, PDF, telefone ou e-mail. Identificam manifestos privados
de custódia, não hashes de dados pessoais de baixa entropia. Hash não anonimiza
PII. Não inventar um identificador real se seu manifesto ainda não existir.

O esquema não autentica assinatura, competência do signatário ou manifestos.
A futura custódia deve ligar assinatura, digest aprovado e tenant/finalidade/
pacote/versão por fonte independente autenticada. Uma ref bem formada não é
evidência de aprovação. A prova documental recebe separadamente payload
fictício e digest aprovado fictício e verifica seus vínculos e SHA-256/JCS.
Nenhum payload real é lido, alterado ou recalculado nesta evolução.

### Resolução sem substituir referências aprovadas

`resolved_refs` cobre exatamente as refs do payload congelado, sem duplicatas,
em ordem ASCII e até 128 aliases. Não substitui strings do payload. O digest
do payload fixa strings, não comprova conteúdo externo. Referências Git
históricas permanecem no SHA aprovado; não se troca por main atual.

- `PENDING_EXTERNAL`: formato v1, conteúdo/hash/bound_ref nulos e motivo
  não vazio. Status `APPROVED_PAYLOAD_PENDING_EXTERNAL`.
- `RESOLVED_FROZEN`: source_ref, content_ref opaca por SHA-256,
  content_sha256 dos bytes externos exatos, pending_reason nulo.
  A validação recebe bytes separadamente e confere hash/endereço; nunca busca
  rede ou arquivos automaticamente. Para documentos Git, a custódia deve
  identificar commit, caminho e seção/escopo exatos. Sem conteúdo verificável,
  manter pendente; hash não prova adequação jurídica.

Todas resolvidas: `APPROVED_PAYLOAD_REFERENCES_BOUND`, nunca autorização
`CATALOG_BOUND` operacional. Conteúdo privado permanece fora do Git.

Em ambos os estados v2, content_digest conserva o digest aprovado.
entry_digest = SHA-256/JCS da entrada excluindo somente entry_digest.
Pendências não anulam o digest de payload já aprovado nem passam a significar
completude. Assinatura do payload não assina automaticamente a entrada:
exige-se âncora independente própria para imutabilidade/autenticidade.

Este primeiro perfil real admite somente supersedes nulo e payload sem
predecessor. Depois de fixada uma entrada, não editar/recalcular para fechar
pendências. Sucessão real exige contrato posterior; sucessão sintética v1
permanece preservada.

### Aceite e limites

Testes fictícios cobrem preservação v1, pendências v2, gates falsos,
custódia inválida, divergência de payload/digest/tenant, refs ausentes e
duplicadas, adulteração de bytes externos e rehash contra âncora anterior.
Não há writer, API, evidence store operacional, runtime, banco ou envio.
Rollback: não adotar a proposta local, preservando payload e histórico.
Próximo gate: revisão humana deste contrato antes da primeira entrada real.

Validação local desta evolução: 212 testes passaram, zero falhas/skips,
em 4.22s, incluindo catálogo, schema/digest de payload, pacote documental
e evidence store. Imagem existente
`pastorai-agent-local-validation-v1-backend:3799272`, sem pull/rede,
checkout read-only e dados exclusivamente fictícios. `git diff --check`
limpo. Não comprova CI remoto, custódia, assinatura ou runtime.

Estado: **DESENHO OFFLINE / EXEMPLO SINTÉTICO / SEM APROVAÇÃO**.
Base: `b3b35489436498fa234c74a6f835a572a0d89892` (PR #378).
Esta proposta não cria catálogo operacional, evidence store, writer, API,
painel, migration ou runtime. Não materializa uma igreja real.
`catalog_ready=false`, `writer_eligible=false`, `controller_approved=false`,
`operational_authorization=false`, `next_stage_authorized=false`.
O pacote humano permanece `DRAFT_NOT_APPROVED`.

## 1. Compatibilidade e problema resolvido

O [template existente](../d2b2b2-decision-packet.template.json) define:

`content_digest = lowercase_hex(SHA-256(UTF8(JCS(decision_payload))))`.

O digest **não inclui o envelope de governança**. Não vamos mudar a fórmula,
acrescentar silenciosamente documentos ao seu escopo ou chamar hash de uma
referência opaca de hash do documento que ela representa. O schema existente
`d2b2b2/decision-payload/v1` permanece inalterado.

Proposta: antes de calcular o digest final de conteúdo, resolver cada string
opaca `ref:...` e substituí-la, no payload materializado, por
`ref:catalog:sha256:<content_sha256>`. Esse endereço identifica exatamente os
bytes canônicos de um objeto de conteúdo. A entrada conserva a relação entre
referência original, endereço e conteúdo. Alterar o conteúdo altera o endereço,
o payload materializado e seu `content_digest`. Uma referência antiga não é
reapontada para conteúdo novo sob o mesmo digest.

Esse é um **protocolo proposto**, não uma transformação já autorizada de
payloads reais. O digest provisório de um payload com refs opacas não é
reutilizado nem promovido: a resolução muda o payload e exige novo cálculo e
futura revisão/assinatura contra a versão exata. Nenhum digest real foi lido
ou calculado nesta missão. Não há ciclo: primeiro conteúdos, depois endereços,
depois payload, depois entrada; assinaturas ficam fora dessa cadeia de hashes.

## 2. Diretórios e estrutura

Tudo nesta entrega está em `docs/governance/consent/catalog/`:

- `CONTRACT.md`: contrato proposto;
- `catalog-entry.schema.json`: envelope estrutural fechado, versão
  `consent-catalog/design-v1`, **somente exemplos sintéticos**;
- `examples/igreja-exemplo.synthetic-example.json`: uma entrada completa de
  ensaio, com payload original, payload resolvido e 31 resoluções concretas.

Para futura adoção revisada, layout proposto de entradas sanitizadas:
`entries/<tenant_binding>/<purpose>/<package_id>/<package_version>/<entry_digest>.json`.
Nenhuma entrada real desse diretório é criada agora. Conteúdo privado,
assinatura, contato pessoal ou contrato com dados reais **não pertence ao Git**.
Custódia privada e seu protocolo de integridade ainda dependem de missão própria.

| Campo | Significado |
|---|---|
| `schema_version` | Versão do envelope, não a versão do payload |
| `entry_id` | UUID opaco da entrada; não reutilizado em correção |
| `purpose`, `tenant_binding`, `package_id`, `package_version` | Exatamente os mesmos vínculos nos dois payloads; uma finalidade e igreja por entrada |
| `source_payload` | Payload de origem sintético, preservando aliases opacos |
| `decision_payload` | Payload materializado com endereços por conteúdo; é o único objeto de `content_digest` |
| `resolved_refs` | Uma resolução por alias encontrado; nenhuma ausência, duplicata ou resolução extra |
| `content_digest` | SHA-256 JCS do payload materializado, ou `null` se há pendência externa |
| `entry_digest` | SHA-256 JCS da entrada inteira **excluindo somente `entry_digest`**; inclui payloads, refs, status, vínculos e indicadores |
| `supersedes` | `null` ou tripla `entry_id`, `entry_digest`, `content_digest` da predecessora |
| `status` | `SYNTHETIC_FROZEN` ou `DRAFT_PENDING_EXTERNAL`; não são estados do ciclo de aprovação |

Todos os indicadores de aprovação/autoridade são booleanos estritos `false`.
`synthetic_only=true` limita o exemplo; não é prova automática de ausência de
dados reais. A revisão de conteúdo continua necessária. O schema desta proposta
não oferece estado `CONTROLLER_APPROVED`, `CATALOG_BOUND` nem transição de aprovação.

## 3. Resolução fechada de referências

Percorrer recursivamente objetos e arrays dos payloads. Cada string que
representa uma referência deve ser uma string inteira `ref:...`, nunca URL,
caminho de arquivo, fragmento de prosa ou instrução de acesso. Não executar,
buscar na rede ou abrir um arquivo indicado por ela. Refs em nomes de campos
são inválidas. Arrays preservam ordem; o máximo deste perfil é 128 aliases.

Cada resolução tem `source_ref`, `state`, `bound_ref`, `content_sha256`,
`content` e `pending_reason`. O array `resolved_refs` é ordenado por
`source_ref` ASCII crescente; ordem diferente é rejeitada mesmo com rehash:

1. `RESOLVED_SYNTHETIC`: conteúdo concreto embutido, objeto fechado
   `{synthetic_only, kind, text}`, com `kind=synthetic_governance_text`.
   `content_sha256=SHA-256(JCS(content))`, endereço exato por hash e
   `pending_reason=null`. Não é mero nome de documento ou hash sem conteúdo.
2. `PENDING_EXTERNAL`: `content`, `content_sha256` e `bound_ref` nulos;
   justificativa sanitizada obrigatória. A ref original permanece no payload.
   Qualquer pendência exige `DRAFT_PENDING_EXTERNAL` e ambos os digests nulos;
   o candidato não pode ser congelado nem apresentado como conteúdo pronto.

O conjunto de aliases deve coincidir exatamente com o extraído de
`source_payload`. O payload resolvido deve ser exatamente o resultado dessas
substituições, sem mudar nenhum outro fato. Conteúdos resolvidos não admitem
refs adicionais: ciclos e resoluções transitivas são recusados neste perfil.
Uma futura representação de anexos privados/binários precisa de outro contrato;
não se passa um apontador externo por conteúdo resolvido.

O exemplo reutiliza a estrutura sintética da PR #378, com denominação fictícia
“Igreja Exemplo” e UUIDs fictícios. Todas as 31 refs têm textos concretos de
ensaio. Uma ref de revisor contém somente uma descrição fictícia, **não uma
assinatura ou aprovação**. Não prova qualidade jurídica nem completude real.

## 4. Canonicalização, validação e imutabilidade

O perfil documental suporta somente objetos com chaves string, arrays,
strings Unicode válidas, booleanos e `null`. Números em qualquer profundidade,
surrogates isolados, chaves JSON duplicadas e tipos não JSON são recusados.
Objetos usam ordem de chaves UTF-16, UTF-8 sem escape desnecessário, separadores
compactos; não há normalização Unicode. É um subconjunto JCS, não um
canonicalizador genérico. Acrescentar números ou outro formato exige revisão.

Validação obrigatória em camadas:

1. schema fechado do catálogo;
2. ambos os payloads contra o schema já integrado na PR #378;
3. igualdade de tenant/finalidade/pacote/versão;
4. fechamento das refs, hashes dos conteúdos e endereços;
5. recomputação do `content_digest` e `entry_digest`;
6. comparação com **âncora anterior confiável**, independente do arquivo
   candidato, e preservação de todas as entradas anteriores.

Uma entrada congelada não é editada nem removida. Correção acrescenta nova
entrada com novo `entry_id`, versão maior e `supersedes`; o payload também
aponta `supersedes_content_digest` para a predecessora. A cadeia permanece no
mesmo tenant, finalidade e package_id. Predecessora ausente, auto-referência,
versão repetida ou substituição de outra igreja invalidam a cadeia. Não há
alias mutável `latest` que possa mudar o alvo de assinatura. Mudança de estado
operacional ou revogação não edita a entrada; seu registro autenticado futuro
pertence ao fluxo externo, não implementado aqui.

Este perfil de exemplo restringe `package_version` a três inteiros decimais
separados por ponto, comparados numericamente. O schema de payload original
também admite pré-releases; suportá-las no catálogo exige definir sua ordem
antes de ampliar este perfil. Não altera a validade do schema original.

Hash auto-recalculado **não prova imutabilidade ou autenticidade**: alguém
capaz de trocar conteúdo e todos os hashes produz outro arquivo internamente
consistente. A prova documental fixa o digest esperado do exemplo fora dele,
e compara snapshots anteriores para recusar edição/remoção mesmo após rehash.
Em futura adoção, Git revisado no SHA exato e âncoras autenticadas externas
devem preservar essa confiança; não foram configurados branch protection,
WORM, assinatura ou CI remoto nesta missão. O teste verifica imutabilidade
semântica do JSON; a proibição de editar inclusive formatação continua regra
de revisão Git. Um atacante que altere também testes/âncoras está fora dessa
prova local e exige a revisão independente/autenticação externa.

## 5. O que permanece externo e bloqueado

O catálogo não conhece nem atesta sozinho contatos institucionais, identidades
dos agentes de tratamento, contratos/suboperadores/regiões, base e pareceres,
política de menores, retenção por superfície, responsáveis por direitos e
incidentes ou registros de revisão. Sem materialização verificável e
sanitização/custódia adequada, as respectivas refs ficam `PENDING_EXTERNAL`.
O preenchimento da Igreja Exemplo não resolve nenhuma ref da igreja real.

Assinaturas dos responsáveis contra o payload final, identidade e competência
dos signatários, custódia, retenção/eliminação de evidências e elegibilidade
do writer continuam fora. O template vigente exige, inclusive para
`catalog_ready`, **human_packet_complete + entrada presa ao digest aprovado +
evidence_store_contract_implemented + separate_technical_authorization**.
Não reduzir essa condição apenas à existência de um arquivo/hash.

Próximo gate de governança preservado e fechado:
`OWNER_AUTHORIZE_REVIEW_CONSENT_PACKET_TAREFAS_OPERACIONAIS`.
Esta entrega não o consome. Não propõe autorização de writer ou envio.

## 6. Aceite, teste e reversão

Aceite: exemplo completo válido; drift de conteúdo/payload/endereço e rehash
contra âncora detectados; ref ausente, extra, duplicada, ciclo e pendência
externa tratados; sucessão append-only preservada; todos os gates falsos.
Teste: `backend/tests/test_consent_immutable_catalog.py`, somente memória e
leitura dos artefatos versionáveis. Reutiliza o interpretador restrito de
keywords do teste de schema da PR #378, sem instalar dependência ou resolver
schemas pela rede. Não é validator de produção nem meta-validador genérico.
Execução observada em `2026-09-07T23:26:04Z`: **108 passed in 3.76s**,
exit 0, sem skips. Inclui este teste e os três existentes:
`test_d2b2b2_decision_payload_schema.py`,
`test_d2b2b2_decision_payload_digest_synthetic_example.py` e
`test_d2b2b2_decision_packet_docs.py`. Imagem local existente
`pastorai-agent-local-validation-v1-backend:3799272`, `--pull never`,
`--network none`, filesystem read-only, `/tmp` efêmero, worktree montada `:ro`,
ambiente limpo e `pytest -o addopts= -q --tb=short -p no:warnings -p no:cacheprovider`.
Não houve instalação nem fetch: `origin/main` local já apontava para a base
exata. Revisão independente sem bloqueios; ordenação canônica acrescentada
após sua observação e coberta pela execução final.

Pins SHA-256 dos arquivos testados (distintos dos digests semânticos):

- Schema: `32afece8c9eae62fa082d8108caef6dff2aa1d65a69cc12ef48572809127d5de`.
- Exemplo: `e1375d28c50b1452237c3e33253033e3a70592b162bad23c7de52fe2042f0866`.
- Teste: `e8af072e2c0be269f9f4e6b37ab906e05310525f8c8ba78784bb67e0cc2c15f1`.

Worktree: `.worktrees/consent-immutable-catalog-v1`, branch
`docs/consent-immutable-catalog-v1`, HEAD preservado na base acima, sem commit.
`git diff --check` passou. Apenas contrato/schema/exemplo/teste e notas de
índice em PRD-COVERAGE/Wiki foram criados ou alterados. Nenhum template,
payload anterior, código runtime ou schema de banco foi alterado.
Resultado: **DONE técnico documental / FREEZE**, zero efeito externo e zero
dado real utilizado; não aprova consentimento nem destrava envio.

Reversão: não adotar os novos documentos da worktree isolada. Não apagar ou
reescrever o trabalho de outra sessão, o template, o schema de payload ou o
histórico. Nenhum conteúdo de igreja real foi solicitado, lido ou versionado.
