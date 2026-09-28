# Revisão parcial V2a, serviço de agenda

## Identidade

Base: `3e8306e9dfd5e3dec3097f3e8a701829b4d7aa36`.

| Arquivo | SHA-256 |
| --- | --- |
| `backend/app/services/whatsapp_agenda.py` | `6b40a7cb7a46f4bc1f14bbd6c1a82ae237426fd0192a01801262f129f71b6361` |
| `backend/tests/test_whatsapp_agenda.py` | `be064623c584564a5a17f8c0922897750d349d8afff3d00aee2ada4aa750d2d2` |

Escopo somente leitura. A unidade isolada passou com `env -i`: 12 testes aprovados. Catálogo, runtime, fila e testes PG ainda não fazem parte deste snapshot.

## P1

1. Eventos confirmados sem autoria verificável somem da consulta em vez de aparecer com fallback de `tipo`. O filtro em [whatsapp_agenda.py](/tmp/igreja12-v2a-agenda-review-20260927/backend/app/services/whatsapp_agenda.py:310) exige `confirmado_em`, `confirmado_por` e autor ativo pastor/admin para retornar a linha inteira. O contrato aprovado exige manter evento confirmado legado e esconder somente o título não comprovado. A correção mínima é separar elegibilidade do evento da autorização do título, com projeção de título nulo para o fallback.

2. Rascunhos autorizados por prova Clerk ainda podem passar por `project_institutional_title`, embora não tenham autoria de confirmação. O caminho `include_drafts` em [whatsapp_agenda.py](/tmp/igreja12-v2a-agenda-review-20260927/backend/app/services/whatsapp_agenda.py:308) não carrega uma marca que force fallback ou rótulo de rascunho. Isso contraria o contrato de título humano verificável. Rascunho deve ser explicitamente identificado e usar tipo fixo, salvo uma prova de autoria aprovada que o contrato ainda não oferece.

3. O leitor é invocável com flags inertes. `agenda_enabled_from_environment` é definido, mas não é usado fora dos testes, e `resolve_agenda_reply` começa pelo parser e SELECT sem esse gate em [whatsapp_agenda.py](/tmp/igreja12-v2a-agenda-review-20260927/backend/app/services/whatsapp_agenda.py:378). O chamador final também deve fechar o gate antes de abrir sessão, mas o serviço precisa negar por padrão para impedir uma integração futura de expor consulta com release `None`.

4. A matriz de papéis não preserva a leitura humana atual. `GET /events` aceita `get_current_user`, enquanto `_AGENDA_ROLES` limita V2a a membro e papéis ministeriais. O papel `operador`, já aceito no caminho humano, perde acesso sem decisão de produto. O leitor deve espelhar a política humana confirmada ou a mudança de audiência precisa de decisão explícita e teste de regressão.

## P2

1. Controles acima de dois dígitos são ignorados e caem no padrão. Reprodução na unidade: `parse_agenda_query('agenda 100 dias')` e `parse_agenda_query('agenda página 100')` retornam `AgendaQuery(days=7, page=1, include_drafts=False)`. O parser deve rejeitar controle reconhecido fora dos limites, sem reinterpretá-lo como pedido padrão.

2. A janela usa apenas data. Uma ocorrência de hoje às 08:00 ainda entra em uma consulta às 10:00 porque `resolve_agenda_reply` passa somente `start` e `end` para `occurrences_for_event`. Ocorrência com hora válida anterior ao instante atual deve ser excluída; hora ausente ou inválida não deve ser inventada.

3. O limite silencioso de 160 linhas em [whatsapp_agenda.py](/tmp/igreja12-v2a-agenda-review-20260927/backend/app/services/whatsapp_agenda.py:338) pode fabricar página vazia ou incompleta, principalmente quando recorrências e datas nulas ordenam antes das ocorrências relevantes. Buscar a linha 161 e negar ou sinalizar excesso é mais seguro que responder ausência incompleta.

4. `agenda_reply_still_authorized` não confirma que o `context` atual pertence à mesma igreja, conversa e inbound da `Message` ancorada. O caller final precisa re-resolver o `PrivilegeContext` sob RLS antes do retry, e o guard deve negar mismatch direto. O hash atual também não inclui `event_id`; incluí-lo apenas no material do hash, sem expô-lo, fortalece a detecção de substituição de fonte com projeção textual idêntica.

## Testes que faltam no próximo snapshot

- PG17 com evento confirmado legado, título não institucional, título de rascunho, autoria ativa e autoria revogada, sem projetar descrição ou mensagem.
- Papel `operador`, membro, líder, pastor/admin com e sem prova Clerk, contexto de outra igreja e conversa pública.
- Controle `100 dias` e `página 100`, ocorrência de hoje já passada, recorrência semanal, página alta e mais de 160 fontes elegíveis.
- Flag vazia e release `None` com sentinela que falha se houver SELECT de `Event`.
- Retry após edição, exclusão, revogação de papel, revogação de prova e mismatch de contexto, com nenhuma resposta stale ou transporte.

## Conclusão

**Não apto para integração.** Os quatro P1 e os P2 acima precisam de delta congelado e provas adicionais. Este não é parecer sobre o produto completo.
