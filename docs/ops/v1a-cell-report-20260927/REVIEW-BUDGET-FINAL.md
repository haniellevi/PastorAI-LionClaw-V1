# Revisão delimitada V1a, orçamento, locks e finalização

## Candidato revisado

- `cell_report_whatsapp.py`: `013275411802e7eea295b93c6d23e6e2a48e24f5222705624c65fe267a72f100`
- `cell_report_v1a_service.py`: `4330f0d10194b3ee24ae60b7169f73a38bf0c22e012658f1cd885c80dbe3d605`
- `cell_report_finalizer.py`: `aadd06e17d866135a9e4c2d005108f1b9a843ec59a62f9c9c1930066107c0953`
- `routers/cell_meetings.py`: `6721548046c8b76eb7eb9368af098225bb30621d03d97b5f39a013ea10cca7cf`
- `agent/privileged_turn.py`: `58e157e6f3fed16269223138567fc9f29386296c19729bd81c99b26b5ab9a849`
- Testes revistos: `test_cell_report_finalizer_v1a.py` `1e9f4ae4867d1a644465226701a1fdc3fe2fff53009e13b36dab5e76cc88aa5e`; `test_cell_report_v1a_worker_pg.py` `48855e752ee7a581dfc8d5b231f3c8948ddc7ef96f46038dd1b1e69ad429f3be`.

Esta revisão foi somente leitura. Não executou banco, Git, provedor ou chamada externa.

## Resultado técnico

APTO no recorte de fonte. O root informou a rodada humana e de aplicação finalizada com 280/280 verdes para esta integração. A suíte PG integral pertence ao candidato completo posterior.

O orçamento diário passa a reler a identidade ORM sob `FOR UPDATE`, impedindo que uma sessão stale sobrescreva a reserva confirmada. O teto por relatório agora é calculado sobre todas as reservas associadas à mesma reunião, inclusive após cancelar um rascunho e iniciar novo ciclo. A junção trava somente `CellReportAiReservation`, evitando lock acidental dos rascunhos unidos.

Os três caminhos V1a que antes tomavam Draft antes de Meeting foram alinhados. O estágio lê apenas a referência sem lock sob a Conversation já travada, bloqueia Meeting/Cell e então bloqueia e revalida Draft. A confirmação e a revalidação antes de transporte partem da referência tipada, bloqueiam Meeting/Cell e só depois Draft. Isso converge com a purga, cujo prefixo relevante é Meeting/Cell antes de Draft. A reserva usa Meeting, Draft, reservas e orçamento diário. Não encontrei nova inversão nesse conjunto.

O finalizador preserva a mesma transição terminal para painel e V1a, sem commit ou transporte. O adaptador humano copia o snapshot legado e troca somente `relatorio_status` para `enviado`; timestamps e ator continuam nas colunas da reunião e na resposta de submit. O snapshot V2 permanece fechado e validável. O teste PG revisado cobre GET humano após submit e GET do painel após confirmação V1a.

`privileged_turn` mantém confirmações locais determinísticas antes de Tier A e coloca o gate Tier A ativo antes da coleta V1a. Assim, handoff e opt-out não são suprimidos por uma mensagem que pareça relatório.

## P1 corrigidos nesta rodada

1. Total diário stale podia aceitar uma segunda reserva acima de US$2 por igreja e dia.
2. Novo ciclo do mesmo relatório podia reiniciar teto de quatro chamadas e US$0,10.
3. Stage, retry e confirmação podiam formar ciclo Draft para Meeting contra a reserva Meeting para Draft.
4. Submit humano congelava `relatorio_status='pendente'` no read-model.
5. A primeira correção do item anterior contaminava o schema fechado V2 com chaves legadas; o candidato atual limita a alteração ao wrapper humano.

## Limites

Este parecer não aprova extração LLM, chamada paga, cron, compartilhamento do finalizador em módulos ainda não integrados, deploy, flags efetivas ou qualquer envio real. A suíte PG integral será reavaliada com o candidato completo.
