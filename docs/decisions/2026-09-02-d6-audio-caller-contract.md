# D6: contrato do chamador de áudio do turno do agente

Data: 2026-09-02

Status: `DRAFT_CONTRACT / NOT_APPROVED / NO_CODE_AUTHORIZED`

Baseline: `e5d07e60c2eb9dafae671323bde60d1fa1be5749`

## Resultado desta decisão

Esta decisão é somente texto. Ela descreve o contrato que um futuro chamador
de transcrição de áudio precisaria cumprir para ligar uma mensagem de voz
recebida ao turno do agente. Ela não cria código, migration, tabela, flag,
teste de runtime nem caller, e não habilita nada.

O inventário abaixo foi obtido por leitura do código no baseline citado.
Nenhuma parte desta decisão observou o pipeline executando em ambiente real,
com Evolution, Supabase, Redis ou provedor LLM. Onde o texto diz "hoje", o
sentido é "está escrito no código do baseline", não "foi visto executar".

## Inventário do estado atual confirmado

### Seleção de tenant a partir do webhook

`backend/app/domain/conversations.py:191` (`parse_message_event`) transforma o
corpo do webhook em `ParsedMessage`, descartando eventos que não sejam mensagem
de chat 1:1. O campo `instance` vem direto do corpo (`payload.get("instance")`)
e não é autenticado por essa função.

`backend/app/workers/queue_worker.py:741` (`ingest_message_event_ex`) marca a
sessão como cross-tenant (`mark_cross_tenant`, `source="worker_ingest"`) e
executa o único lookup permitido sem escopo:

```
select(WhatsappConnection).where(WhatsappConnection.instance == parsed.instance)
```

com `.scalar_one_or_none()`. Sem linha, a mensagem é descartada como
`SKIPPED_NOT_OFFICIAL`. Com linha, `igreja_id = connection.igreja_id` e
`promote_to_tenant(db, igreja_id, source="worker_ingest")` fixa o tenant.
`backend/app/db/models.py:2110` define o índice único parcial
`whatsapp_connections_instance_uidx` sobre `instance`, mais `UNIQUE` em
`igreja_id`.

### Armazenamento da mídia recebida

Ainda em `ingest_message_event_ex`, quando `parsed.media_kind` existe e há um
`media_resolver`, o worker chama o resolver dentro de `try/except Exception`;
uma falha é registrada em log e a ingestão continua sem mídia
(`backend/app/workers/queue_worker.py:908`).

`resolve_media_via_evolution`
(`backend/app/workers/queue_worker.py:2556`) chama
`get_media_base64(parsed.instance, _key_from(parsed))`
(`backend/app/services/evolution.py:498`), decodifica com
`raw = base64.b64decode(base64_data)` e envia a `SupabaseStorage().upload(...)`
com `object_id=parsed.provider_message_id`.

`backend/app/services/storage.py:134` (`upload`) recusa vazio, recusa acima de
`MAX_MEDIA_BYTES = 16 * 1024 * 1024`, deriva o nome do objeto de
`sha256(object_id)` sob o prefixo `{igreja_id}/provider/` e retorna
`StoredMedia(path, mime, nome, tamanho)` com `mime = mime or
"application/octet-stream"` e `tamanho = len(data)`.

### Proveniência condicional de `media_mime` e `media_tamanho`

`backend/app/workers/queue_worker.py:919` grava a linha `Message` com:

- `media_mime = (stored.mime if stored else parsed.media_mime) if
  parsed.media_kind else None`;
- `media_tamanho = stored.tamanho if stored else None`.

Portanto a proveniência é condicional e precisa ser lida assim:

- com armazenamento bem-sucedido, `media_mime` é o `mimetype` devolvido pela
  Evolution em `get_media_base64`, com fallback para `parsed.media_mime` do
  webhook quando a Evolution não devolve `mimetype`, e com fallback final para
  `"application/octet-stream"` dentro de `upload`. Em todos os casos é um
  rótulo declarado por terceiros, **não atestado** contra os bytes: nenhuma
  função no baseline inspeciona o conteúdo para confirmar o tipo;
- `parsed.media_mime` para áudio, quando o webhook não traz `mimetype`, é o
  literal `"audio/ogg"` embutido em `backend/app/domain/conversations.py:164`;
- com armazenamento bem-sucedido, `media_tamanho` é `len(data)` dentro de
  `upload`, e `data` é exatamente o `raw` do resolver, ou seja `len(raw)`;
- sem armazenamento (resolver ausente ou exceção engolida), `media_tamanho` é
  nulo e `media_mime` cai para o rótulo do webhook. Uma linha com `tipo`
  `"audio"`, `media_path` nulo e `media_tamanho` nulo é o estado normal de
  degradação, não uma anomalia.

### Transcrição

`backend/app/services/llm.py:331` (`transcribe_audio`) valida provedor,
credencial não vazia, `mime_type` dentro de `SUPPORTED_AUDIO_MIME_TYPES`,
payload não vazio e `len(audio_bytes) <= MAX_AUDIO_BYTES = 25 * 1024 * 1024`,
tudo antes de qualquer I/O. Se `external_sends_allowed()` for falso, registra
`log_suppressed("LLM", "transcribe_audio")` e devolve um
`AudioTranscriptionResult` com texto simulado marcado, `duracao_segundos = 0.0`
e `custo = 0.0`, sem chamar o provedor. No caminho externo usa
`TRANSCRIPTION_MODEL = "whisper-1"` com `response_format="verbose_json"`, lê
`response.text` e `response.duration`, e calcula
`custo = round((duracao / 60.0) * TRANSCRIPTION_USD_PER_MINUTE, 6)`.

O commit `b7eb171` que introduziu essa função declara explicitamente que ela
não está ligada a router, webhook ou worker. A leitura do baseline confirma:
não há chamador de `transcribe_audio` em `backend/app` fora do próprio módulo.

### Identidade do turno e contexto confiável

`backend/app/agent/turn_identity.py:236` define `AgentTurnIdentity`, frozen,
com `igreja_id`, `conversation_id`, `inbound_message_id`, `provider` e
`provider_message_id`, derivando `turn_id`. O docstring do módulo declara que o
contrato é puro, sem I/O, e que validação estrutural não prova proveniência.

`backend/app/workers/queue_worker.py:2340` (`run_agent_for_message`) constrói a
identidade via `_build_trusted_inbound_turn_identity(outcome)` somente quando
`agent_trusted_inbound_identity_enabled` está ligado, e
`backend/app/agent/runtime.py:498` (`process_inbound_message`) revalida com
`_require_bound_turn_identity` sob a mesma flag.

O escopo de tenant confiável hoje é um efeito de sessão, não um valor: a dupla
`promote_to_tenant` / `mark_tenant_scoped` (`app/db/tenant_session.py`) mais a
verificação `require_tenant_scope` (`backend/app/db/rls_observability.py:119`),
que devolve um `TenantScopeSignal` (`backend/app/db/rls_observability.py:37`).
**Não existe no baseline nenhum tipo
chamado `TrustedTenantScope`**; esse nome é introduzido por esta decisão como o
valor futuro, imutável e explicitamente construído, que carregaria o
`igreja_id` promovido junto com a prova de que a sessão foi escopada. Enquanto
ele não existir, qualquer texto abaixo que o cite descreve trabalho futuro.

### Lease de execução atual

`backend/app/workers/queue_worker.py:560` define `_AgentExecutionLease`. Em
PostgreSQL ele toma `pg_try_advisory_lock` numa conexão dedicada, faz commit
mantendo a conexão em uso e libera no `close()`. Fora de PostgreSQL usa um
`threading.Lock` de processo único, descrito no próprio docstring como
mecanismo de teste, não de fencing entre processos.

Esse lease **não tem TTL, não tem owner persistido e não tem fencing token**.
Ele é escopado à sessão física; se o processo morrer, o banco derruba o lock e
outro worker pode adquiri-lo sem saber o que o anterior chegou a executar. Por
isso `run_agent_for_message` recarrega o intent após adquirir o lease e, se
encontrar `ia_executando`, chama `_quarantine_agent_execution` em vez de
reexecutar.

### Pipeline do agente e resposta

`run_agent_for_message` reserva o intent durável
(`_reserve_agent_reply_intent`), adquire o lease, transiciona
`ia_reservada -> ia_executando`, revalida a posse (`ownership_guard()`)
imediatamente antes do efeito, e só então chama `process_inbound_message` com
`texto=outcome.texto`. Qualquer `BaseException` na chamada leva a quarentena.
`backend/app/domain/agent_reply.py:18` define
`AGENT_REPLY_SUPPRESSED = "ia_suprimida"`, e uma resposta suprimida não é
enviada.

Note-se que o argumento passado é `outcome.texto`. Para uma mensagem de áudio,
`parsed.texto` vem de `_extract_text(message)` e tipicamente é vazio; nenhum
caminho no baseline substitui esse texto por transcrição.

### Exclusão

`backend/app/routers/conversations.py:760` chama `storage.remove(media_paths)`
ao excluir uma conversa. `backend/app/services/storage.py:233` documenta o
método como best-effort e silencioso em falha: o objeto órfão é aceito como
custo menor do que quebrar a exclusão. Não há no baseline job de
reconciliação de órfãos, política de retenção por tempo, nem varredura que
compare o bucket `whatsapp-media` com as linhas `messages`.

`backend/app/db/models.py:2652` define `AiUsageLog` (igreja, modelo, tokens,
`custo`, ferramenta, `created_at`). É um log append-only de consumo já
ocorrido: não tem reserva, não tem agregado por período, não tem chave única e
não impõe teto.

## Costura futura: exatamente uma, em `run_agent_for_message`

Esta decisão fixa **uma única costura**, dentro de `run_agent_for_message`, no
trecho já cercado pelo intent durável e pelo lease, imediatamente antes da
chamada a `process_inbound_message`. Nenhum outro ponto do sistema pode
transcrever áudio para alimentar um turno automático.

A costura separa três naturezas de operação, e o contrato exige que essa
distinção fique explícita: nenhum passo que lê ou escreve o próprio banco pode
ser chamado de "puro" só por não chamar o provedor terceiro. Validação local
pura, efeitos transacionais locais (no próprio banco do tenant, nunca no
provedor) e a borda externa são categorias diferentes; a lista abaixo segue a
ordem cronológica real da costura, e cada item declara a que categoria
pertence.

Exatamente duas etapas desta lista são funções puras nomeadas: o passo 4
(`_prepare_audio_transcription_decision`) e o passo 10
(`_finalize_audio_transcription_outcome`). Nenhuma outra etapa recebe nome de
função pura adicional — em particular, o validador estrutural e o parser de
duração usados dentro do passo 4 são etapas internas dessa função, não
funções adicionais da costura.

1. **Efeito transacional local — leitura da mensagem.** Carregar a
   `Message` sob RLS, na sessão já escopada ao tenant. Um efeito real, ainda
   que só de leitura, inteiramente dentro do perímetro do tenant. Nenhum byte
   de mídia é obtido neste passo.
2. **Efeito transacional local — criação idempotente do registro.**
   Imediatamente após o passo 1 e **antes de qualquer tentativa de obter os
   bytes ou de validar o conteúdo**, obter ou criar, por chave única
   `(igreja_id, message_id)`, a linha `TranscriptionRecord/v1` no estado
   `recebida`, com `igreja_id`, `message_id`, `conversation_id`, `turn_id` e o
   timestamp de criação. Nesse estado nenhum orçamento foi reservado, nenhuma
   credencial foi resolvida e nenhum `fencing_token` foi emitido — não existe
   `TranscriptionLease/v1` ainda. Se a chave já existir num estado terminal, a
   costura para aqui: o desfecho já gravado é devolvido como replay, sem
   repetir os passos seguintes e sem nova validação. Se já existir em
   `recebida` (retomada da mesma mensagem antes de qualquer decisão), a linha
   existente é reaproveitada.
3. **Efeito transacional local — obtenção dos bytes.** Só agora, com o
   registro já criado em `recebida` pelo passo 2, obter do próprio Storage do
   sistema (não do provedor de transcrição) os bytes já armazenados para essa
   mensagem. Ausência de mídia armazenada ou falha de leitura transiciona
   `recebida -> suprimida`, condicional apenas ao estado esperado (nenhum
   `fencing_token` existe ainda para cercar essa escrita), e a costura
   termina para essa mensagem sem credencial resolvida, sem orçamento
   reservado e sem qualquer lease.
4. **Validação local pura — uma única função,
   `_prepare_audio_transcription_decision`.** Esta é a primeira das exatas
   duas funções puras da costura (a segunda é a do passo 10): uma única
   função determinística, sem tocar banco nem rede, que recebe tudo que os
   passos 1 a 3 já obtiveram — os bytes lidos, `media_mime`/`media_tamanho`
   declarados, a `AgentTurnIdentity` do turno, o `TrustedTenantScope`
   vigente e a chave `(igreja_id, message_id)` gravada no passo 2 — e
   devolve **um único valor**: a decisão validada completa. O gate
   `external_sends_allowed` não é lido aqui, não é entrada desta função e não
   participa desta decisão; ele só é lido, uma única vez, dentro da API
   futura da borda no passo 9 (ver "Resultado discriminado da borda"), nunca
   antes. Internamente, como etapas dessa mesma função e
   não como funções adicionais da costura, ela: monta o
   `StoredAudioDescriptor/v1` por composição pura dos valores já obtidos
   (nenhuma leitura nova); roda o validador estrutural bounded, que decide
   se os bytes comprovam uma faixa de áudio de formato aceito; roda o
   parser de duração bounded, que calcula a duração comprovada; e compara
   por igualdade, em memória, o `StoredAudioDescriptor/v1` montado, a
   `AgentTurnIdentity`, o `TrustedTenantScope` e a chave do passo 2. O
   parsing estrutural e o parsing de duração são etapas internas de
   `_prepare_audio_transcription_decision`, não funções adicionais da
   costura. A decisão devolvida é: o alvo de rejeição (`recusada` ou
   `suprimida`, com a causa) caso qualquer regra acima falhe, ou a
   aprovação com a duração comprovada caso todas tenham sucesso. Esta
   função não escreve nada por si só — a escrita correspondente é feita
   pelos passos 5 a 7, que leem a decisão que ela devolveu.
5. **Efeito transacional local — resolução da rejeição, condicional a
   partir de `recebida`.** Lê a decisão pura do passo 4. Se rejeitou,
   aplica exatamente uma escrita condicional ao estado esperado, sem
   nenhum `fencing_token` disponível ainda: transiciona `recebida ->
   recusada` ou `recebida -> suprimida`, conforme a causa, e a costura
   termina para essa mensagem sem credencial resolvida, sem orçamento
   reservado e sem qualquer lease. Se o passo 4 aprovou, nenhuma escrita
   ocorre aqui — a linha permanece em `recebida` — e a costura segue para o
   passo 6.
6. **Efeito transacional local — resolução da credencial BYO, antes da
   reserva e antes de qualquer `TranscriptionLease/v1` ou transição para
   `executando`.** Só alcançado quando o passo 4 aprovou. Resolver a
   credencial OpenAI BYO exclusiva do `igreja_id` fixado pelo
   `TrustedTenantScope` vigente — a linha `LlmCredential`
   (`backend/app/db/models.py:2622`, única por `igreja_id`) cujo `igreja_id`
   é igual ao do `TrustedTenantScope`, exigindo `validado` e `ativo` ambos
   verdadeiros — e descriptografá-la localmente (`decrypt_secret`), no mesmo
   padrão de `_active_credential` (`backend/app/agent/runtime.py:131`).
   Linha ausente, `validado` ou `ativo` falsos, ou descriptografia
   malsucedida transicionam `recebida -> suprimida`, **sem reserva**: nenhum
   orçamento chegou a ser comprometido neste ramo, então não há nada para
   compensar, e a costura termina antes de alcançar `reservada` ou
   `executando`. Sucesso não escreve nada ainda — a linha permanece em
   `recebida` —, a credencial descriptografada é mantida só em memória, para
   uso exclusivo no passo 9, e a costura segue para o passo 7.
7. **Efeito transacional local — reserva orçamentária atômica.** Só
   alcançado quando o passo 6 resolveu a credencial com sucesso. Reserva o
   orçamento atomicamente — `snapshot`, `periodo` e `valor_reservado`
   derivado da duração comprovada no passo 4 — e, só se a reserva couber no
   teto do período, transiciona `recebida -> reservada` na mesma transação
   da reserva. Se o agregado do período mais o valor reservado ultrapassar o
   teto, nada é reservado e a transição é `recebida -> suprimida` em vez de
   `recebida -> reservada`.

   Só a partir daqui existe orçamento reservado; `recebida` nunca implica
   reserva, e uma falha de credencial no passo 6 nunca chega a este passo —
   por isso, **nesta primeira execução**, uma reserva nunca precisa ser
   compensada por causa de credencial ausente ou inválida. Essa afirmação
   vale só para a resolução inicial do passo 6, antes de a reserva existir;
   quando a mesma credencial precisa ser re-resolvida depois que a reserva
   já existe — em renovação ou takeover de `reservada` —, uma falha nesse
   momento compensa a reserva já existente, como fixado em "Retry e
   replay".
8. **Efeitos transacionais locais de preparo da borda.** Só alcançado a
   partir de `reservada`. Adquirir e validar o `TranscriptionLease/v1`, que
   emite o `fencing_token` vigente para esta tentativa; a linha permanece em
   `reservada` neste momento, porque a credencial já foi resolvida no passo
   6 e não há mais nada além do lease para preparar antes da borda. Esta
   descrição cobre a primeira execução; quando este ponto é alcançado por
   renovação ou takeover de uma `reservada` já existente, o owner precisa
   antes re-resolver e descriptografar a credencial BYO de novo, conforme
   "Retry e replay", e uma falha nessa re-resolução desvia para `reservada
   -> suprimida` em vez de prosseguir para a transição abaixo.
   Imediatamente antes da chamada externa, e sem nenhuma outra operação no
   meio, o lease é relido e revalidado uma última vez — owner, token e
   expiração — e, só então, cercada por esse `fencing_token`, a linha
   transiciona `reservada -> executando`. Nenhum passo anterior marca
   `executando`: não a resolução da credencial (passo 6), não a reserva
   (passo 7), não a aquisição do lease neste mesmo passo — só o instante
   imediatamente anterior à chamada do passo 9.
9. **Uma única borda externa impura.** No máximo uma chamada por turno, à
   API futura da borda — `transcribe_audio` refatorada, ou uma função que a
   substitua, descrita em "Resultado discriminado da borda" — com os bytes
   já lidos no passo 3, o `mime_type` já comprovado no passo 4 e a
   credencial já resolvida no passo 6, feita imediatamente após a
   transição para `executando` no passo 8, sem nenhuma outra operação no
   meio. É essa própria chamada, e somente ela, que decide o gate
   internamente, no instante em que tenta o envio, e devolve diretamente o
   variant por ela mesma observado; o passo 9 não lê `external_sends_allowed`
   nem qualquer outro sinal do gate por conta própria, nem antes nem depois
   nem em paralelo a essa chamada, e não infere o variant a partir do texto
   devolvido. Esta é a única fronteira do contrato que sai do
   processo para um provedor terceiro; nenhum outro passo desta costura é
   essa borda, e ela não se repete dentro do mesmo turno. A chamada usa
   exclusivamente a credencial OpenAI BYO obtida no passo 6, pertencente ao
   `igreja_id` fixado pelo `TrustedTenantScope`: nunca uma credencial da
   própria plataforma, nunca a de outro tenant e nunca uma indicada por
   `parsed.instance` ou por qualquer outro campo do payload do webhook ou do
   resolver de mídia — o único determinante do `igreja_id` usado para essa
   credencial é o `TrustedTenantScope` já fixado antes da costura começar,
   nunca o payload. Como a borda só é alcançada depois dos passos 6, 7 e 8,
   qualquer registro que chegue a `executando` prova, por construção, que a
   credencial já estava resolvida e o orçamento já estava reservado; não há
   caminho em que `executando` seja alcançado sem os dois.
10. **Projeção final pura — a segunda e última função pura da costura,
    `_finalize_audio_transcription_outcome`.** Sobre o retorno bruto do
    passo 9, já em memória e sem nenhuma nova leitura, esta função
    determinística sanitiza o texto reconhecido (regras na seção
    "Sanitização do texto reconhecido" abaixo) e decide, num único valor
    devolvido, o estado terminal alvo (`real`, `falhou` ou `ambigua`) e o
    valor de liquidação — consumo ou compensação da reserva —, sem gravar
    nada ainda; a escrita é feita pelo passo 11. Se a sanitização rejeitar o
    texto devolvido pela borda, o alvo é `falhou`, nunca `real` — há prova
    durável do que ocorreu (a resposta chegou, mas o texto não passou na
    sanitização), então o desfecho não é `ambigua`, mesmo que a chamada HTTP
    tenha retornado sem erro de transporte. Nenhuma outra etapa desta
    costura é uma função pura nomeada: só existem estas duas —
    `_prepare_audio_transcription_decision` no passo 4 e
    `_finalize_audio_transcription_outcome` aqui.
11. **Liquidação, efeito transacional local.** Grava o resultado do passo
    10: o estado terminal do `TranscriptionRecord/v1`, cercado pelo mesmo
    `fencing_token` revalidado no passo 8, e o consumo ou a compensação da
    reserva orçamentária. Como os passos 2, 5, 6, 7 e 8, isto é um efeito
    persistente real no próprio banco, não uma operação pura — a diferença é
    que só pode escrever sob o token que sobreviveu até depois da borda, e é
    aqui, não antes, que o turno se torna definitivamente terminal para essa
    reserva.

A continuação do turno é **exclusivamente** `REAL_TRANSCRIPT.texto`. Somente um
desfecho `real`, gravado no passo 11, produz o `REAL_TRANSCRIPT` cujo `.texto`
substitui `outcome.texto` na chamada a `process_inbound_message`. Nenhum outro
valor — nem o texto simulado do gate fechado, nem um resumo, nem um
placeholder — pode chegar ao agente.

Esta projeção é a mesma, sem exceção, tanto na primeira execução da costura
(passos 1 a 11 acima) quanto no replay de um `TranscriptionRecord/v1` já
terminal (ver "Retry e replay"): `real` projeta `REAL_TRANSCRIPT` nos dois
casos, e cada um dos quatro terminais não `real` — `suprimida`, `recusada`,
`falhou` e `ambigua` — projeta exclusivamente `SUPPRESSED` nos dois casos, sem
gradação entre eles. `SUPPRESSED`, vindo de qualquer um desses quatro estados,
encerra o auto-turno de áudio sem chamar `process_inbound_message`, seja na
primeira execução, seja no replay (ver "Regra de encerramento por
`SUPPRESSED`" abaixo).

## Resultado discriminado da borda: `TRANSCRIBED` ou `SUPPRESSED`

Hoje `transcribe_audio` (`backend/app/services/llm.py:331`) devolve sempre o
mesmo tipo, `AudioTranscriptionResult` (`texto`, `duracao_segundos`,
`custo`), tanto no caminho real quanto no caminho de gate fechado. A única
diferença observável entre os dois casos é o conteúdo de `texto` — no
caminho fechado, o literal `"[Transcrição simulada — envios externos
desativados neste ambiente.]"`. Esse tipo, como existe hoje, não é uma
união discriminada: nada no formato do valor devolvido impede, por
construção, que um consumidor trate o resultado simulado como uma
transcrição real. Por isso `transcribe_audio`, como existe hoje, não pode
ser usada como o passo 9 sem refatoração: seu contrato de retorno atual
não expõe nenhum discriminante de tipo, só um campo de texto que varia por
convenção.

A costura futura fixa **uma única decisão autoritativa do gate**, tomada
inteiramente **dentro** da própria API futura da borda — seja uma versão
refatorada de `transcribe_audio`, seja uma função que a substitua — no
instante exato em que essa API tenta, ou deixa de tentar, o envio ao
provedor. É essa API, e somente ela, que lê `external_sends_allowed()`
nesse instante e decide, internamente, se o envio ocorre. A própria API
devolve diretamente, como seu próprio tipo de retorno, uma de duas
variantes de um tipo soma observado internamente por ela mesma:
`TRANSCRIBED` (carregando o texto bruto do provedor, a duração reportada e
o custo, presentes porque o envio de fato ocorreu) ou `SUPPRESSED`
(carregando um motivo estruturado, sem nenhum campo de texto reconhecido,
porque o envio não ocorreu). O passo 9 apenas invoca essa API e recebe de
volta o variant já decidido por ela; ele **proíbe** qualquer pré-leitura
independente do gate feita pelo próprio passo 9 (antes, depois ou em
paralelo à chamada), inclusive reaproveitar a leitura já feita no passo 4
— que serviu só para a decisão pura daquele passo, nunca para esta
classificação —, e **proíbe** inferir o variant a partir do conteúdo de
`texto` devolvido: comparar prefixo, substring ou qualquer outro trecho do
texto para decidir entre as duas variantes é uma implementação inválida
deste contrato. O passo 9 nunca classifica um `AudioTranscriptionResult`
bruto depois do fato; a única decisão do gate que conta é a tomada pela
própria chamada da borda, no seu próprio instante de execução.

Como o passo 4 nunca lê nem decide o gate, todo turno aprovado pela decisão
pura alcança o passo 8 e, a partir dele, o passo 9: não existe caminho em
que a costura termine em `recebida -> suprimida` por causa do gate antes de
chamar a borda. Dentro do passo 9, no instante em que a própria API da
borda tenta o envio, ela encontra o gate aberto ou fechado e decide ali
mesmo:

- **gate aberto.** A chamada ao provedor ocorre e a API devolve
  `TRANSCRIBED`, com o texto bruto, a duração reportada e o custo.
- **gate fechado.** É a própria chamada da API — nunca uma releitura feita
  pelo passo 9 — que encontra o sinal fechado internamente e devolve
  `SUPPRESSED` diretamente como seu próprio tipo de retorno, sem jamais
  materializar ou expor um `AudioTranscriptionResult` simulado como
  candidato a `TRANSCRIBED`. Como a borda já foi alcançada (o registro já
  está em `executando`, cercado pelo `fencing_token` do passo 8; a chamada
  ocorreu, apenas não produziu envio), o passo 10 trata essa `SUPPRESSED`
  como prova durável de que nenhuma chamada de rede partiu — o alvo é
  `falhou`, nunca `real` e nunca `ambigua`, pela mesma regra já fixada para
  rejeição de sanitização: há certeza do que não ocorreu, então o desfecho
  não é indeterminado. Como se sabe, com certeza, que nenhum custo real foi
  incorrido, a liquidação do passo 11 compensa a reserva neste caso, em vez
  de consumi-la.

Somente um valor `TRANSCRIBED`, devolvido diretamente pela API da borda,
com texto que sobreviva integralmente à sanitização do passo 10, pode
produzir o alvo `real`. Qualquer `SUPPRESSED` devolvido diretamente pela
própria API da borda no passo 9 nunca produz `real`; o desfecho final
projeta `SUPPRESSED` na continuação do turno (ver "Regra de encerramento
por `SUPPRESSED`").

## Sanitização do texto reconhecido, bounded e fail-closed

`_finalize_audio_transcription_outcome` (passo 10) sanitiza `response.text`
antes de decidir que o desfecho é `real` — ou seja, antes que esse texto
possa ser persistido como `REAL_TRANSCRIPT` no passo 11 ou encaminhado como
`texto` a `process_inbound_message`. A sanitização é **bounded** (opera só
sobre a string já em memória, sem nova leitura) e **fail-closed** (qualquer
violação rejeita o texto inteiro; não existe correção parcial, truncamento
silencioso ou escape que produza um `REAL_TRANSCRIPT` diferente do texto
originalmente devolvido):

- **codificação**: o texto precisa ser uma `str` Unicode válida, sem
  caractere de substituição (`U+FFFD`) nem substituto (*surrogate*) mal
  formado introduzido por uma decodificação com perda; qualquer ocorrência
  rejeita o texto inteiro;
- **controles**: qualquer ponto de código da categoria Unicode `Cc` além de
  `\n` (LF) e `\t` (TAB) — incluindo `NUL`, `ESC` e demais controles C0/C1 —
  rejeita o texto inteiro; não há remoção seletiva de controles seguida de
  aceitação do restante;
- **vazio**: depois de remover espaços nas bordas, uma string vazia é
  rejeitada; um resultado vazio do provedor não pode virar um
  `REAL_TRANSCRIPT` vazio nem continuar o agente com texto em branco;
- **tamanho**: um texto acima de um teto fixo de caracteres é rejeitado sem
  truncamento — o contrato não define aqui o valor exato do teto, apenas que
  ele precisa existir, ser finito e ser aplicado antes de qualquer
  persistência ou uso do texto.

Qualquer uma dessas rejeições faz `_finalize_audio_transcription_outcome`
devolver o alvo `falhou`, nunca `real` (ver passo 10). Não existe caminho em
que um texto reprovado na sanitização chegue, de forma integral, truncada ou
modificada, ao `TranscriptionRecord/v1` no campo reservado a `real` ou à
chamada a `process_inbound_message`.

## Regra de encerramento por `SUPPRESSED`

`SUPPRESSED` é a única projeção possível para os quatro terminais não `real`
— `suprimida`, `recusada`, `falhou` e `ambigua` —, tanto quando a costura os
alcança pela primeira vez quanto quando o replay os lê de um
`TranscriptionRecord/v1` já gravado nesse estado. Qualquer desfecho
`SUPPRESSED`, por qualquer motivo (gate externo fechado, formato
inconclusivo, duração não comprovada, credencial BYO ausente ou inválida na
resolução inicial ou na re-resolução exigida em renovação e takeover,
orçamento indisponível, lease perdido, mídia ausente, descritor divergente,
texto reprovado na sanitização, ausência de prova durável do que ocorreu na
borda), **encerra o auto-turno de áudio** sem chamar
`process_inbound_message`.

Em particular, um turno suprimido:

- não injeta texto sintético, marcador, transcrição simulada ou string vazia
  no lugar da fala;
- não gera resposta automática ao contato pelo número oficial;
- não cria uma resposta de erro visível ao remetente;
- registra o estado terminal para operação e auditoria, e nada mais.

O silêncio é o comportamento correto. Um relatório de célula falado que não
pôde ser comprovadamente transcrito precisa ser tratado por uma pessoa, não
por um turno degradado.

## `parsed.instance` é seletor não confiável

`parsed.instance` chega de um corpo HTTP e não carrega autoridade. Ele é
apenas um **seletor de busca**. O contrato exige:

- o lookup cross-tenant em `WhatsappConnection.instance` deve resultar em
  **exatamente uma** linha; zero linhas e múltiplas linhas são igualmente
  fatais para o turno;
- somente o `igreja_id` **persistido** nessa linha promove e fixa o tenant;
- nenhum campo do corpo do webhook pode escolher, corrigir, sobrescrever ou
  reconfirmar o tenant depois da promoção;
- depois da promoção, `parsed.instance` só pode ser usado como argumento de
  chamada ao provedor, nunca como chave de leitura ou escrita de dados de
  tenant.

## `StoredAudioDescriptor/v1`

Valor imutável, montado por composição pura no passo de validação local pura
da costura, com no mínimo:

- `message_id`;
- `igreja_id`;
- `conversation_id`;
- ponteiro de armazenamento (`media_path`), rótulo `media_mime` declarado e
  `media_tamanho` declarado;
- os bytes efetivamente lidos e o comprimento observado desses bytes.

O descritor só é válido se todos os identificadores forem iguais, campo a
campo, aos da `AgentTurnIdentity` do turno, aos do `TrustedTenantScope`
vigente e aos da `Message` carregada sob RLS na mesma sessão escopada.
Qualquer divergência é `SUPPRESSED`.

O rótulo `media_mime` e o `media_tamanho` persistidos entram no descritor como
metadados declarados, para conferência e log. Eles nunca substituem a
verificação estrutural dos bytes descrita adiante, e uma divergência entre
`media_tamanho` e o comprimento observado é `SUPPRESSED`.

## Validador estrutural local, bounded e fail-closed

Antes da borda, um validador local, sem rede, decide se os bytes são
comprovadamente uma **faixa de áudio** de um dos formatos aceitos, com um
codec explicitamente permitido para o respectivo contêiner:

- `audio/ogg` — página Ogg com `capture_pattern` `OggS`, cabeçalho de
  identificação Opus (`OpusHead`) e a mesma serial number consistente até a
  última página. `OpusHead` é o único codec permitido neste contêiner; uma
  página Ogg cujo cabeçalho de identificação não seja `OpusHead` (por
  exemplo `\x01vorbis` ou qualquer outro) prova um codec não permitido, não
  um Ogg genérico aceitável;
- `audio/mpeg` — quadros MP3 sincronizados e encadeados, com versão,
  bitrate e sample rate válidos e coerentes entre quadros, e o campo
  `layer` do cabeçalho MPEG igual a **Layer III** em todos os quadros
  percorridos. Layer III é o único codec permitido neste contêiner; layer I,
  layer II ou o valor reservado provam um codec não permitido;
- `audio/mp4` — árvore ISO-BMFF com `ftyp` de marca compatível e uma trilha
  cujo `hdlr` seja `soun`, cuja **sample entry** dentro de `stsd`
  (`stbl/stsd`) prova o codec da trilha. `mp4a` com configuração AAC lida do
  `esds`/`DecoderConfigDescriptor`, ou `alac` com o bloco de configuração
  ALAC presente, são os únicos codecs permitidos neste contêiner; qualquer
  outro código de sample entry (por exemplo um codec de vídeo, ou um código
  de áudio fora dessa allowlist), `stsd` sem entradas, ou `esds`/bloco de
  configuração ilegível, prova um codec não permitido ou inconclusivo;
- `audio/wav` — contêiner RIFF/WAVE com `fmt ` coerente e `data` cujo
  tamanho declarado caiba nos bytes presentes. O **format tag** de `fmt `
  prova o codec: `WAVE_FORMAT_PCM` (`0x0001`) ou `WAVE_FORMAT_IEEE_FLOAT`
  (`0x0003`) são os únicos codecs permitidos; quando o tag é
  `WAVE_FORMAT_EXTENSIBLE` (`0xFFFE`), o **subformat** (GUID) do bloco de
  extensão de `fmt ` precisa corresponder a um desses dois formatos PCM,
  senão prova um codec não permitido. Qualquer outro format tag, ou um
  `fmt ` cujo bloco de extensão declarado não caiba nos bytes presentes,
  prova um codec não permitido ou inconclusivo;
- `audio/webm` — EBML/Matroska com `DocType` `webm` ou `matroska` e uma
  faixa cujo `TrackType` seja áudio, cujo elemento **`CodecID`** prova o
  codec da faixa. `A_OPUS` ou `A_VORBIS` são os únicos codecs permitidos
  neste contêiner; qualquer outro `CodecID`, uma faixa sem `CodecID`, ou um
  `CodecID` truncado dentro dos limites do parser, prova um codec não
  permitido ou inconclusivo.

A allowlist acima é fechada: nenhum outro par contêiner/codec além dos
listados é aceito, mesmo que o codec seja legítimo em outro contexto (por
exemplo AAC solto em ADTS fora de MP4, ou Opus fora de Ogg/WebM, não são
reconhecidos por este validador).

Regras do validador:

- é **fail-closed**: só um resultado positivo explícito permite prosseguir.
  Erro, ambiguidade, formato desconhecido, contêiner sem faixa de áudio,
  faixa de vídeo presente, múltiplas faixas incompatíveis, truncamento ou
  estouro de limite resultam em `SUPPRESSED`;
- o codec provado pelo campo estrutural (`OpusHead` em Ogg, `layer` de
  quadro MP3, sample entry de `stsd` em MP4/M4A, format tag/subformat de
  `fmt ` em WAV, `CodecID` em WebM) precisa ser compatível, simultaneamente,
  com o contêiner comprovado, a faixa de áudio identificada e o MIME
  canônico associado a esse contêiner nesta lista. Codec **ausente** (o
  campo que o comprovaria não existe na faixa), **desconhecido** (valor que
  não corresponde a nenhum codec conhecido), **não permitido** (valor
  reconhecido, mas fora da allowlist fechada acima para aquele contêiner) ou
  **inconclusivo** (campo truncado, ilegível ou ambíguo dentro dos limites
  do parser) resulta em `SUPPRESSED` **antes da borda**, do mesmo modo que
  qualquer outra falha estrutural;
- o rótulo `media_mime` não decide nada. Se a estrutura provada — contêiner
  ou codec — divergir do rótulo, o turno é `SUPPRESSED`, não "corrigido
  silenciosamente";
- o `mime_type` passado adiante para a borda é o comprovado pela estrutura,
  já com o codec verificado contra a allowlist;
- ele não executa código do arquivo, não invoca binário externo, não segue
  referências para outros arquivos ou URLs e não descomprime dados.

## Limites explícitos do parser

O validador opera sob limites fixos e verificados a cada passo, sempre
**dentro do teto de mídia** já vigente (`MAX_MEDIA_BYTES = 16 MiB` em
`app/services/storage.py`), que é menor que `MAX_AUDIO_BYTES = 25 MiB` em
`app/services/llm.py`:

- **bytes**: no máximo 16 MiB inspecionados; um objeto maior que o teto de
  mídia é `SUPPRESSED` sem parsing;
- **tempo**: orçamento de CPU por arquivo, fixado em 250 ms; estouro é
  `SUPPRESSED`;
- **profundidade**: no máximo 8 níveis de aninhamento de contêiner (boxes
  ISO-BMFF, elementos EBML, chunks RIFF);
- **quantidade de elementos**: no máximo 4096 elementos estruturais por
  arquivo (páginas Ogg, quadros MP3, boxes, elementos EBML, chunks),
  somados, e no máximo 64 faixas declaradas.

Nenhum tamanho declarado dentro do arquivo pode ser confiado acima desses
limites nem acima do comprimento real dos bytes lidos.

**Prefixo não é suficiente.** Ler apenas o cabeçalho, os primeiros quilobytes
ou uma amostra não comprova nada para este contrato. O validador precisa
percorrer a estrutura até o fim do intervalo que sustenta sua conclusão. Se
os limites acima impedirem esse percurso completo, o resultado é
`SUPPRESSED`, não uma conclusão parcial.

## Duração confiável antes da borda

A duração precisa ser conhecida **antes** da chamada externa, porque é ela que
dimensiona a reserva orçamentária. Ela é obtida por parsing local bounded, sob
os mesmos limites acima:

- Ogg/Opus: pela granule position final, com o pre-skip do `OpusHead`;
- MP3: pela soma das durações dos quadros efetivamente percorridos;
- MP4/M4A: pelos campos `duration` e `timescale` da trilha de áudio,
  confirmados contra a tabela de amostras;
- WAV: pelo tamanho de `data` dividido pela taxa de bytes de `fmt `;
- WebM: pelo `Duration` do `Info` com o `TimestampScale`, confirmado contra o
  último cluster percorrido.

`duracao_segundos` devolvido pelo provedor é usado apenas para conferência
posterior; ele chega tarde demais para autorizar gasto. Uma divergência
relevante entre a duração local e a reportada é registrada e trava o consumo
da reserva na faixa reservada.

Se a duração **integral** não puder ser comprovada localmente — arquivo de
duração desconhecida, streaming sem índice, granule ausente, contêiner
truncado, formato cuja duração só se conheceria decodificando tudo — o turno é
`SUPPRESSED` **sem nenhuma chamada externa**.

## `TranscriptionRecord/v1`

Registro durável, tenant-scoped, com:

- `igreja_id`, `message_id`, `conversation_id`, `turn_id`;
- estado, `fencing_token` vencedor (nulo enquanto o estado é `recebida`,
  porque nenhum `TranscriptionLease/v1` foi adquirido ainda), timestamps de
  criação, de reserva e de término;
- digest dos bytes de entrada, `mime` comprovado, duração comprovada
  localmente e duração reportada;
- referência à reserva orçamentária e ao valor efetivamente consumido;
- o texto reconhecido, quando e somente quando o estado é `real`;
- motivo terminal estruturado, sem conteúdo do áudio, quando não é `real`.

Requisitos de armazenamento: coluna `igreja_id` obrigatória, `ENABLE ROW LEVEL
SECURITY` mais `FORCE RLS` na tabela, policies mínimas por tenant, e índice
**único por `(igreja_id, message_id)`**, garantindo no máximo um registro de
transcrição por mensagem por igreja.

Nada disso existe no baseline. Não há tabela, migration, modelo ou teste
correspondente. Esta seção descreve o alvo, e escrevê-la não implementa nem
autoriza implementar.

## Estados e transições

Estados terminais e não terminais do `TranscriptionRecord/v1`:

- `recebida` — linha durável criada idempotentemente por `(igreja_id,
  message_id)`, identidade do turno gravada, **antes de qualquer validação
  terminal**. Nenhum orçamento reservado, nenhuma credencial BYO resolvida,
  nenhum `TranscriptionLease/v1` adquirido, nenhum `fencing_token` emitido.
  A obtenção dos bytes, a validação terminal e a resolução da credencial BYO
  ocorrem enquanto o registro ainda está neste estado, antes de qualquer
  reserva. Não terminal;
- `reservada` — a validação terminal aprovou (estrutura comprovada, duração
  íntegra comprovada, descritor conferido), a credencial BYO já foi
  resolvida e descriptografada com sucesso, e o orçamento correspondente
  foi reservado atomicamente; borda ainda não iniciada; o gate ainda não foi
  lido, porque só a API do passo 9 o lê. Em renovação ou takeover do lease
  (ver "Retry e replay"), o owner que assumiu precisa re-resolver e
  descriptografar a credencial BYO de novo antes de avançar; se essa
  re-resolução falhar, o registro sai daqui direto para `suprimida`, com a
  reserva compensada na mesma transação, sem nunca alcançar `executando`.
  Não terminal;
- `executando` — a borda foi iniciada. Não terminal e não presumível: só é
  alcançado a partir de `reservada`, e todo registro que chega aqui prova,
  por construção, que a credencial já estava resolvida e o orçamento já
  estava reservado (ver passo 9 da costura);
- `real` — transcrição obtida do provedor real. Terminal. Único estado que
  produz `REAL_TRANSCRIPT`;
- `suprimida` — o turno de áudio foi encerrado, antes da borda, sem
  transcrição utilizável, inclusive quando o teto orçamentário seria
  ultrapassado. Terminal;
- `recusada` — a entrada foi rejeitada por conteúdo, formato, tamanho,
  duração ou descritor divergente. Terminal;
- `falhou` — a borda foi iniciada e devolveu erro comprovadamente antes de
  qualquer efeito utilizável. Terminal;
- `ambigua` — a borda foi iniciada e não há prova durável do que ocorreu.
  Terminal e definitivo: exige tratamento humano.

Toda transição a partir de `reservada` ou de `executando` é condicional ao
**estado esperado** e ao **fencing token vigente**, aplicada como escrita
condicional única. Uma transição cujo predicado de estado ou de token não
case não escreve nada e faz o chamador reler o registro. As transições que
saem de `recebida` são condicionais apenas ao **estado esperado**, porque
nesse ponto nenhum `TranscriptionLease/v1` foi adquirido e nenhum
`fencing_token` existe ainda para cercar a escrita.

Transições permitidas: `recebida -> recusada`, `recebida -> suprimida`,
`recebida -> reservada`, `reservada -> executando`, `reservada ->
suprimida`, `executando -> real`, `executando -> falhou`, `executando ->
ambigua`. Nenhuma transição sai de um estado terminal. Nenhuma transição
entra em `executando` a partir de um estado que não seja `reservada`, e
nenhuma transição entra em `reservada` a partir de um estado que não seja
`recebida`. A partir de `reservada` existem exatamente duas transições
possíveis: `reservada -> executando`, o avanço normal cercado pelo
`fencing_token` vigente quando a re-resolução da credencial BYO exigida em
todo retry (ver "Retry e replay") tem sucesso; e `reservada -> suprimida`,
igualmente cercada pelo `fencing_token` vigente e com liquidação
(compensação) da reserva na mesma transação, quando essa re-resolução
falha. Nenhuma transição sai de `reservada` diretamente para `falhou` ou
para `ambigua`: os dois exigem primeiro passar por `executando`, porque
`falhou` é reservado a casos em que a borda já foi iniciada.

## Reserva orçamentária atômica antes da borda

Antes da borda, e depois da duração comprovada, uma reserva atômica registra:

- `snapshot` — a política de teto lida no momento, com sua versão, para que a
  decisão seja auditável mesmo se a política mudar depois;
- `periodo` — a janela de agregação (por exemplo o mês corrente do tenant),
  explícita na linha;
- `valor_reservado` — derivado da duração comprovada localmente e do preço
  vigente, arredondado para cima.

A linha `TranscriptionRecord/v1` já existe em `recebida` desde antes da
validação terminal; esta reserva não a cria, apenas grava `snapshot`,
`periodo` e `valor_reservado` e transiciona `recebida -> reservada`, tudo na
mesma transação. Se o agregado do período mais o valor reservado ultrapassar
o teto, nada é reservado, a transição é `recebida -> suprimida` em vez de
`recebida -> reservada`, e o turno é `SUPPRESSED` sem borda.

Esta reserva só é tentada depois que a credencial OpenAI BYO do `igreja_id`
foi resolvida e descriptografada com sucesso (passo 6 da costura). Se a
credencial falhar, a costura já terminou em `recebida -> suprimida` antes de
chegar a este passo, e não existe nada reservado para compensar; a reserva e
a sua eventual compensação só existem no ramo em que a credencial já estava
confirmada.

Cada reserva termina exatamente uma vez, por **consumo terminal** (o valor
real substitui o reservado, limitado ao reservado) ou por **compensação** (a
reserva é liberada). Consumo e compensação são idempotentes e cercados pelo
`fencing_token` vigente no momento dessa escrita — o emitido na primeira
aquisição do lease, no passo 8, ou o novo token emitido por uma renovação sem
troca ou por um takeover, conforme o caso —, de modo que uma retomada não
cobra duas vezes nem libera uma reserva já consumida. Em `ambigua`, o valor
reservado é consumido, não compensado: não há prova de que a borda não
gastou. A compensação por falha de re-resolução de credencial em `reservada`
(ver "Retry e replay") segue esta mesma regra de idempotência e cercamento,
cercada pelo `fencing_token` vigente após a renovação ou o takeover que
motivou a re-resolução.

## `TranscriptionLease/v1`

Lease persistido, distinto do `_AgentExecutionLease` atual, com:

- `owner` — identificador durável do processo/tentativa detentor;
- `fencing_token` — inteiro monotônico, emitido pelo banco, que só cresce;
- `expiracao` — instante absoluto de validade, com TTL curto;
- renovação explícita, que estende a expiração **sem** alterar o
  `fencing_token`;
- validação **imediatamente antes da borda**, relendo o registro e conferindo
  owner, token e expiração; nada pode acontecer entre essa validação e a
  chamada externa;
- **escrita cercada**: toda escrita de finalização carrega o `fencing_token`
  no predicado, de modo que um detentor expirado que volte a rodar não
  consegue escrever sobre o trabalho do sucessor.

Este lease só é adquirido a partir de `reservada` (passo 8 da costura), ou
seja, depois que a credencial BYO já foi resolvida com sucesso em `recebida`
(passo 6). O lease nunca decide sobre credencial: sua única responsabilidade
é a exclusividade de execução entre `reservada` e a chamada à borda.

A diferença em relação ao que existe hoje é deliberada e precisa ficar
registrada: `_AgentExecutionLease` é um advisory lock de sessão, sem TTL, sem
owner persistido e sem fencing; ele impede concorrência simultânea enquanto a
conexão viver, mas não permite decidir, depois de uma queda, quem tinha
direito de escrever.

## Reconciliação de lease expirado em `executando`

Um registro pode ficar preso em `executando` sem que o dono original do
`TranscriptionLease/v1` jamais volte a escrever nele — o processo pode ter
sido encerrado, a rede pode ter caído entre a chamada e a resposta, ou o
owner pode simplesmente não renovar o lease a tempo. Este contrato define
exatamente um caminho seguro de recuperação para esse caso, executado por um
**reconciliador**: um processo separado da costura de `run_agent_for_message`,
que só age depois da expiração, nunca dentro do mesmo turno que criou o
registro. Como o próprio `TranscriptionLease/v1`, este reconciliador não
existe no baseline; esta seção descreve o alvo futuro, e escrevê-la não
implementa nem autoriza implementar.

- **Seleção.** O reconciliador só considera candidatos em `executando` cujo
  `TranscriptionLease/v1` associado tem `expiracao` no passado e não foi
  renovado desde então. Um registro em `executando` cujo lease ainda está
  dentro do TTL não é candidato — pertence ao dono atual, e o reconciliador
  não interfere.
- **Transação atômica única: novo lease, CAS e liquidação.** O reconciliador
  executa, numa única transação atômica, as quatro operações a seguir sobre
  o `TranscriptionLease/v1` e o `TranscriptionRecord/v1` associados:
  emite um novo `fencing_token`, estritamente maior que o anterior — a
  mesma monotonicidade descrita acima —, condicional ao owner, ao
  `fencing_token` anterior e à `expiracao` já vencida do lease; compara-e-
  troca (CAS), no `TranscriptionRecord/v1`, o estado esperado (`executando`)
  e o `fencing_token` que estava vigente antes da expiração — nunca o novo
  token, porque nenhuma escrita da costura original jamais ocorreu sob ele;
  grava, sob esse CAS, a transição `executando -> ambigua` cercada pelo
  novo `fencing_token` vencedor; e consome idempotentemente a reserva
  orçamentária associada sob esse mesmo novo token — nunca compensa,
  seguindo a mesma regra já fixada para todo desfecho `ambigua` em "Reserva
  orçamentária atômica antes da borda". As quatro operações confirmam
  (`commit`) juntas ou nenhuma delas persiste: não existe estado
  intermediário gravado em que o lease já tenha um novo dono mas o registro
  ainda esteja em `executando`, nem estado em que o registro já esteja em
  `ambigua` sem a reserva liquidada — não há hipótese de falha persistente
  entre operações que esta transação declara atômicas.
- **CAS que não bate aborta sem escrever nada.** Se o estado esperado
  (`executando`) e o `fencing_token` anterior não conferirem no instante do
  CAS — porque o dono original voltou e já finalizou o registro, ou porque
  outro reconciliador venceu primeiro —, a transação inteira aborta sem
  escrever nada, incluindo sem trocar a posse do lease; o desfecho já
  gravado por quem venceu prevalece, e este reconciliador para. `ambigua` é
  o único alvo possível quando o CAS bate: sem prova durável de que a
  chamada ao provedor terminou ou do que ela devolveu, o registro não pode
  ser declarado `real` nem `falhou` só por o lease ter expirado. Se esta
  mesma transação for tentada de novo depois de já ter confirmado — por
  este reconciliador ou por outro —, encontra o registro em `ambigua` sob o
  novo token, não mais em `executando` sob o antigo; o CAS falha, nada é
  escrito de novo e a reserva não é consumida uma segunda vez.
- **Nunca repete a borda.** O reconciliador não chama `transcribe_audio` nem
  qualquer outra borda externa, sob nenhuma condição. Repetir a chamada
  arriscaria uma segunda cobrança e uma segunda transcrição para o mesmo
  turno, sem nenhuma forma de saber, a partir do lado do sistema, se a
  primeira chamada já chegou ao provedor. O passo 9 da costura é a única
  chamada permitida por turno; o reconciliador nunca invoca esse passo.

Depois deste ponto, o registro é `ambigua`, terminal e definitivo: a seção
"Retry e replay" a seguir já cobre o resto — `ambigua` nunca é repetida, sob
nenhuma condição, e qualquer replay devolve `SUPPRESSED`.

## Retry e replay

Em `reservada`, existem exatamente dois caminhos seguros para obter ou manter
o direito de acionar a borda, e ambos exigem, antes de qualquer concessão,
**prova durável de que a reserva nunca transicionou para `executando`** sob o
`fencing_token` anterior:

- **renovação pelo mesmo owner.** Enquanto o `TranscriptionLease/v1` vigente
  ainda está dentro do TTL, o mesmo `owner` que o detém pode renová-lo,
  estendendo a `expiracao` **sem** trocar o `fencing_token` — a mesma
  renovação já descrita em "`TranscriptionLease/v1`" acima. Como nenhuma
  troca de posse ocorre, nenhum novo `fencing_token` é emitido, e a escrita
  de finalização que eventualmente seguir continua cercada pelo token já
  vigente;
- **takeover por outro owner, só após expiração comprovada.** Somente depois
  que a `expiracao` do lease vigente já ficou no passado, um owner — o mesmo
  ou outro — pode adquirir um novo `TranscriptionLease/v1` atomicamente, por
  comparar-e-trocar (CAS) sobre quatro condições simultâneas: o estado
  esperado do `TranscriptionRecord/v1` é `reservada`, o `owner` do lease
  confere com o anterior, o `fencing_token` do lease confere com o anterior,
  e a `expiracao` do lease anterior já está comprovadamente vencida no
  instante do CAS. Um CAS bem-sucedido emite um `fencing_token` novo,
  estritamente maior que o anterior — a mesma monotonicidade descrita para o
  reconciliador de `executando` —, e só esse novo token cerca qualquer
  escrita subsequente feita pelo novo detentor.

Nos dois casos, a prova durável de ausência de transição para `executando` é
condição prévia, não consequência: sem ela, nem a renovação nem o takeover são
concedidos, e a reserva não é reutilizada por este caminho — cabe à
quarentena do lease, não a um retry automático, tratar um registro para o
qual essa prova não existe.

Falha do CAS de renovação (o `owner` ou o `fencing_token` já não conferem
mais com o lease relido) e falha do CAS de takeover (o estado deixou de ser
`reservada`, o `owner` ou o `fencing_token` anteriores já mudaram, ou a
`expiracao` ainda não está vencida no instante do CAS) têm a mesma
consequência em ambos os casos: **não escrevem nada** — nem no
`TranscriptionLease/v1` nem no `TranscriptionRecord/v1` —, não emitem
`fencing_token` novo, não deixam o requisitante como dono simultâneo ao
antigo (não há dupla autoridade sobre o mesmo lease) e **não chamam a borda
externa** sob nenhuma hipótese. O chamador cujo CAS falhou apenas relê o
registro; nenhuma tentativa de renovação ou de takeover, bem-sucedida ou não,
é, por si só, uma chamada à borda.

Somente quando a renovação ou o takeover acima foi concedida é que a mesma
reserva pode ser reutilizada para acionar a borda, sob o `fencing_token`
vigente após essa concessão — o original, no caso de renovação, ou o novo, no
caso de takeover.

**Re-resolução obrigatória da credencial BYO antes de `reservada ->
executando`, em qualquer retry.** Nem a renovação nem o takeover, por si só,
autorizam a chamada à borda. A credencial descriptografada no passo 6 nunca é
persistida — ela existe só na memória do processo que a resolveu naquela
tentativa — e o owner que renovou, ou o novo owner que venceu o takeover, não
é presumivelmente o mesmo processo vivo que ainda guarda esse segredo em
memória: o processo original pode ter morrido, e é exatamente por isso que a
renovação ou o takeover foram necessários. Por isso, antes de qualquer
escrita `reservada -> executando`, o owner que efetivamente vai chamar a
borda — o mesmo owner que renovou, ou o novo owner que venceu o takeover —
precisa re-resolver e descriptografar, de novo, a credencial OpenAI BYO do
`igreja_id` fixado pelo `TrustedTenantScope` vigente, com as mesmas
condições do passo 6 (`validado` e `ativo` ambos verdadeiros, descriptografia
bem-sucedida), e nunca reutiliza um segredo mantido na memória de outro
processo ou de uma tentativa anterior. Essa re-resolução precisa terminar com
sucesso **antes** da escrita `reservada -> executando`; nenhuma chamada à
borda ocorre com uma credencial não re-resolvida por quem está prestes a
chamá-la.

Se, nesse retry, a credencial estiver ausente, revogada (`validado` ou
`ativo` falsos), inválida ou a descriptografia falhar, o owner aplica
exatamente uma escrita condicional, cercada pelo `fencing_token` vigente
após a renovação ou o takeover: transiciona `reservada -> suprimida` — nunca
`falhou`, porque a borda ainda não foi iniciada — e, na mesma transação,
liquida (compensa) a reserva orçamentária já existente. `reservada ->
suprimida` entra na lista fechada de transições permitidas ao lado das
demais (ver "Estados e transições"), condicional ao estado esperado
(`reservada`) e ao `fencing_token` vigente, do mesmo modo que qualquer outra
escrita cercada depois da aquisição do lease. Este é o único caso em que uma
reserva já constituída é compensada por causa de credencial: a afirmação do
passo 7 de que uma reserva nunca precisa ser compensada por credencial vale
só para a resolução inicial do passo 6, antes de a reserva existir; aqui, no
retry, a reserva já existe quando a credencial falha de novo, e por isso a
compensação é necessária e ocorre na mesma transação da transição. `falhou`
continua reservado exclusivamente a casos em que a borda já foi iniciada
(sempre a partir de `executando`); uma falha de re-resolução de credencial
em `reservada`, por definição, ocorre antes de a borda ser tentada, então
nunca produz `falhou`.

Todo estado que prove, ou que apenas não consiga excluir com prova durável,
que a borda foi iniciada é terminal e irrepetível, **sem nenhuma exceção**:

- `executando` sem prova durável de que a transição nunca ocorreu não
  autoriza retry sobre a mesma reserva: a ausência dessa prova já basta para
  bloquear a reutilização; a apuração cabe à quarentena do lease, não a um
  retry automático;
- `real` nunca é repetido: já produziu `REAL_TRANSCRIPT`, e repetir arriscaria
  nova cobrança sem novo ganho;
- `falhou` **nunca** é repetido, mesmo quando o motivo estruturado registrado
  parece indicar que o provedor rejeitou a requisição antes de processá-la.
  `falhou` só existe depois de `executando` — a borda foi, por definição,
  iniciada — e isso por si só encerra a reserva de forma irreversível; nenhuma
  leitura do motivo estruturado reabre uma tentativa que já cruzou a
  fronteira externa;
- `ambigua` **nunca** é repetida, sob nenhuma condição;
- `recusada` por conteúdo, formato, tamanho, duração ou descritor divergente
  nunca é repetida: a rejeição ocorre inteiramente antes da borda e antes de
  qualquer reserva (`recebida -> recusada`), a entrada é a mesma e a decisão
  é determinística;
- `suprimida` originada em `recebida` — mídia ausente, formato inconclusivo,
  duração não comprovada, orçamento indisponível ou credencial BYO
  ausente/inválida — também nunca é repetida: essas transições saem de
  `recebida` sem nunca criar reserva, sem lease e sem tocar a borda, então
  não há reserva para reutilizar nem borda para reexecutar;
- `suprimida` originada em `reservada` — falha da re-resolução obrigatória
  da credencial BYO durante renovação ou takeover, depois que a reserva já
  existia — também nunca é repetida: essa transição já liquidou (compensou)
  a reserva na mesma transação cercada pelo `fencing_token` vigente após a
  renovação ou o takeover, então não sobra reserva para reutilizar nem borda
  para reexecutar; ela se distingue de `suprimida` originada em `recebida`
  só pela existência prévia de uma reserva a compensar, nunca por autorizar
  novo retry;
- de forma geral, nenhuma reserva cuja transição para `executando` tenha sido
  confirmada — ou cuja ausência de transição não possa ser provada de forma
  durável — é reaproveitada por um retry, independente do desfecho reportado
  ou do custo aparente de tentar de novo.

Replay reutiliza estados terminais: reprocessar a mesma mensagem lê o
`TranscriptionRecord/v1` existente por `(igreja_id, message_id)` e devolve o
mesmo desfecho, sem nova borda e sem nova cobrança. Replay de um registro
`real` devolve o mesmo `REAL_TRANSCRIPT`; replay de qualquer terminal não
`real` devolve `SUPPRESSED`.

## Privacidade, exclusão e lacunas conhecidas

Áudio, transcrição e derivados (digests, durações, motivos) são dados pessoais
do remetente e permanecem privados e tenant-scoped. A transcrição nunca é
publicada como conhecimento oficial da igreja por este caminho; ela existe
para alimentar um turno e para auditoria.

O bucket `whatsapp-media` é acessado por service-role e servido por URL
assinada com TTL de uma hora (`SIGNED_URL_TTL`), nunca por link público. O
caminho do objeto é derivado do `igreja_id` e do hash do id do provedor.

Estado atual da exclusão, sem embelezamento:

- excluir uma conversa remove as linhas e chama `storage.remove(...)`, que é
  best-effort e silencioso em falha (`app/services/storage.py:233`);
- **lacuna de órfãos**: um objeto cuja remoção falhou permanece no bucket sem
  linha correspondente, e nada o detecta depois;
- **lacuna de reconciliação**: não há job que compare bucket e banco, nem
  relatório de divergência;
- **lacuna de retenção**: não há política de expiração por tempo para mídia
  nem para transcrição, e a decisão sobre prazo é do controlador, não do
  repositório.

Um futuro `TranscriptionRecord/v1` herda essas lacunas e precisa ser incluído
na mesma exclusão por conversa, por pessoa e por igreja, com `ON DELETE
CASCADE` a partir de `igrejas` e de `messages`, antes de qualquer ativação.

## Portão humano

`GATE-D6-AUDIO-CALLER-ACTIVATION` nomeia a autorização humana nominal, futura
e pendente, necessária para que qualquer parte deste contrato vire código
executável ligado ao pipeline real. A autorização precisa ser dada por pessoa
identificada, responsável pelo produto e pelo tratamento de dados, com data e
escopo explícitos, fora deste arquivo.

Este identificador **não autoriza** código, migration, teste, flag, ativação
de flag, chamada a provedor, gasto, nem qualquer outra ação. Ele é um rótulo
de rastreamento de uma decisão que ainda não foi tomada. Merge desta decisão,
revisão de PR ou teste verde não constituem essa autorização.

## Escopo desta decisão

Esta decisão altera somente este arquivo. Ela não modifica código, migration,
teste, configuração ou schema, não liga `transcribe_audio` a nenhum chamador,
não cria `TrustedTenantScope`, `StoredAudioDescriptor/v1`,
`TranscriptionRecord/v1`, `TranscriptionLease/v1`,
`_prepare_audio_transcription_decision`,
`_finalize_audio_transcription_outcome`, o tipo soma `TRANSCRIBED`/
`SUPPRESSED` nem o processo reconciliador, e não muda o comportamento de
`run_agent_for_message` ou `process_inbound_message`.
