# Revisão independente, roteador S3 WhatsApp

Candidato: `S3-WHATSAPP-ROUTING.patch`
SHA-256 conferido: `a336fc4a4506e778900583be5ff3a06b9b3e3b502b8ca189c54b5c990e8a301e`
Escopo lido: `llm.py`, `semantic_routing.py`, `agent_privilege_routing.py` e os três módulos de teste novos.

## Resultado

**NÃO APTO enquanto o P2 abaixo permanecer.** Não encontrei P0 ou P1 no patch congelado.

## P2

### Gate que lança em vez de falhar fechado

`backend/app/services/semantic_routing.py:435-442` chama `s3_routing_egress_allowed` antes do `try` que normaliza timeout e falhas HTTP. Uma exceção de `tier_a_egress_allowed` ou de `external_sends_allowed` atravessa `run_choice_b`, `run_choice_c` ou `run_choice_d`; a API pública do transporte deixa de produzir um `ChoiceDecision` enumerado e o chamador direto pode reexecutar o inbound, em vez de seguir para handoff.

Reprodução mínima sem HTTP: deixar os release IDs coincidentes, substituir `tier_a_egress_allowed` por função que lança `RuntimeError` e chamar `asyncio.run(run_choice_b(...))`. A exceção sai de `_run_choice` antes de qualquer transporte. O `JevChoiceAdapter` externo converte esse caso em `ValueError` e o orquestrador atual o converte em handoff, mas esse tratamento incidental não protege os entry points públicos `run_choice_*`.

Correção mínima: envolver a avaliação de gate, retornando `RoutingError.GATE_FECHADO` para qualquer erro de leitura de gate, e acrescentar teste que prove zero chamadas HTTP.

## Itens conferidos

- O enum do LLM aceita somente schema `s3_route`, `s3_tool` e `s3_handle`, opções deduplicadas e limitadas; recusa tool/function call, refusal, resposta não `stop`, JSON duplicado e conteúdo maior que 32 KiB.
- B, C e D limitam catálogo, texto, handles sequenciais `hN`, summaries e resposta HTTP. O corpo Jev é limitado a 64 KiB, usa `Accept-Encoding: identity`, prazo externo máximo de 0,6 s e não tenta retry.
- Retorno malformado, enum fora do conjunto, timeout e HTTP retornam erro tipado; o orquestrador B/C/D não avança após handoff, `nenhuma` ou handle forjado.
- O release S3 é `None` por padrão. A construção do adaptador não abre egress; o gate exige release S3, release Tier A, allowlist, configuração, DPA e guard externo.
- `registrar_decisao` e `marcar_presenca` são as duas ações de escrita. `consultar_vinculo` e `consultar_celulas` permanecem como consultas readonly previstas pela matriz esclarecida pelo responsável; este módulo não resolve papéis, tenant ou alvos, portanto a prova desses gates pertence à integração server-side do catálogo e executor.

Não executei provider, banco, corpus ou ambiente externo. Os 154 testes focais informados pelo autor não substituem a correção e a prova do P2 acima.

## Rechecagem do delta P2

Delta conferido: serviço `46a3aa4185d7cfe878e70339164448b46a8a2ff80fe10c5b38973a321530793c`; teste `64beca0969b59c472e44f027e0e05eefdca5ee4ecd2017eac4510a70d2e08186`; agregado informado `1e64ad41a958aa25ed2fefc49b2e37f2aa354259b057662cec710c71bc224e7f`.

O P2 está fechado. `_run_choice` agora transforma qualquer exceção de avaliação de gate em `gate_allowed = False` antes de considerar orçamento ou transporte. O novo teste cobre B, C e D contra falha de `tier_a_egress_allowed` e de `external_sends_allowed`, exige `gate_fechado`, escolha nula e zero HTTP. O comportamento preserva a inércia do release e não amplia egress.

**Parecer atualizado: APTO tecnicamente para o patch do roteador, limitado aos seis arquivos e aos testes sintéticos informados.** A integração ainda deve provar separadamente o catálogo server-side, papéis, escopo de alvo, revalidação e executor.
