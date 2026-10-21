# Pedido de exclusão privada — candidato desligado

Pessoa com identidade única, vínculo ativo e termo vigente pode solicitar seu
próprio acervo privado com o comando exato (texto puro):

`QUERO SOLICITAR EXCLUSAO DO MEU CONTEUDO PRIVADO`

O catálogo e o roteador são determinísticos. A identidade vem do inbound
persistido e da conversa oficial, nunca do texto ou do modelo. A fatia não aceita
alvos de terceiros nem razões livres. Não cria um canal de pedido pela equipe.

## Estado e decisão

O pedido fica `pendente`; não apaga conteúdo. Há no máximo uma pendência por
igreja/pessoa. Reentrega do inbound não reabre pedido encerrado. Nova solicitação
após decisão exige novo inbound. A trilha guarda IDs, estado, datas, admin decisor
e referência do recibo; não copia conversa, telefone, áudio, resumo ou motivo.

A pendência suspende leitura de resumos/fontes, enfileiramento e publicação de
novos resumos, inclusive se o pedido chegar durante a chamada simulada do
provedor. RLS restritiva e `private_summary_origin_valid` revalidam a suspensão.
Consumidores de retomada devem usar essa mesma validade no uso e na entrega.
A #531 está em integração separada; sua compatibilidade **não foi verificada**
nesta branch e precisa ser testada antes da integração conjunta/ativação.

O admin decide pelo painel autenticado, nos pedidos do painel do contato.
Aprovar exige confirmação explícita e aciona `private_delete_scope` por pessoa:
conversas, áudio, transcrições e derivados são removidos no mesmo fluxo/fila
existente. Decisão e exclusão operacional são atômicas. O recibo diferencia
pendência externa, envio em andamento e conclusão operacional; o painel permite
atualizar. Backups e cópias de provedor continuam fora do alcance desse recibo.
Cadastro, opt-out e prova de consentimento sem conteúdo seguem as regras da
exclusão existente. Não há envio automático da decisão à pessoa.

Recusar remove somente a suspensão: não recria resumos invalidados por mudança
de fonte, identidade ou acesso. Correções vigentes em fontes ainda válidas são
preservadas. Repetir decisão idêntica é seguro; trocar decisão encerrada é
recusado. Fechar admissão de pedidos não impede o admin de resolver pendências.

## Gates e futura release

`APPROVED_RELEASE_ID=None`, `APPROVED_IGREJA_IDS=frozenset()` no serviço
`private_erasure_requests`; tabela `private_erasure_request_settings` sem seed,
`enabled=false` por padrão. Agente, piloto, consentimento, opt-out, conexão,
credencial e gate global continuam exigidos pelo caminho existente. Os testes
ligam apenas configurações sintéticas e passam transporte falso; nenhum provedor
real é chamado. O comando não executa exclusão, mesmo com admissão autorizada.

Migration `20261022_100000_private_erasure_requests.sql`, na reserva da faixa A.
Aplicar com `backend/scripts/migrate.py` **antes** do backend/frontend novos:
o endpoint administrativo e o helper de resumo dependem do novo schema mesmo
com o canal desligado. Somente PG17 local descartável é autorizado nesta entrega.
Conferir proprietário/BYPASSRLS das funções SECURITY DEFINER na futura release;
a identidade worker por ausência de `sub` é herdada da exclusão/resumos e ainda
precisa de endurecimento. Revisão RLS/migration da Sarah pendente.

Rollback está comentado no SQL: fechar gates/parar consumidores, resolver
pendências e preservar trilha/recibos antes de retirar a barreira. Nunca remover
uma suspensão pendente por rollback. Não há migration remota, ativação, deploy,
restart, nova liberação de igreja ou alteração do ROADMAP nesta fatia.
