# Revisão S3, persistência de privilégios

## Escopo e identidade revisados

Revisão estática do seam de persistência, RLS, identidade e catálogo do candidato ainda não agregado em um único manifesto final:

- `20260927_170000_whatsapp_privilege_actions.sql`: `d087013e0da83c7d80a1e3df05307861314eaaf2195bcd83149fe8927c2a50cc`
- `agent_action_proposals.py`: `c153ac3fe16d4b144be74361c3c37a9aadd9568b882d64efaca3e7d2c8cfb537`
- `agent_privilege_catalog.py`: `db45cde3a01d38cedf9eae979b7f32dca19037055dc40ac280dee00c0c292016`
- `test_s3_migration_exact_pg.py`: `0b6ad4deeffd69d33c018fe72a2532d0021ee03ba0be0aa8d3f68c195d1deb0d`
- `test_agent_action_proposals_pg17.py`: `9fa67dd1290888e8b05293c052dd08e26bb5a584cf030021537ac635845ec79d`
- `test_agent_privileged_turn_pg.py`: `20b9bd667401bd60004f102bc2b81ed642022c8ef6f90423c7273e16392079ed`

Arquivos do snapshot anterior mantidos na revisão: `models.py` `e57bc6d1247379b8093b0975cc618b099a2f7bb5ef9a7f5a3bfb2cfe83916583`, `main.py` `99f134344e441e94319df06d42dc137e34a4cc57144d7a474ab1a90474528e97`, `agent_identity.py` `c73a9a52cceecf380a33e234809218b3e6cfc3f2372de68890c2b48385dbda44`, `routers/agent_identity.py` `56acb713b11f4ca091cc8c6c5c2debb618fe37c1dd5a4d06a22ad5655c4371c7` e `whatsapp_privilege.py` `d07763056ddeb4711cadeb21302987c6293fd299d710916036e8e9cc7bb23517`.

## Parecer

**APTO técnico delimitado.** Não restou P0, P1 ou P2 aberto no seam revisado.

A migration usa chaves compostas para manter igreja, conversa, pessoa e âncora coerentes; ativa e força RLS nas novas relações; restringe grants; e preserva a remoção por cascata. Propostas e recibos são vinculados a anchors confirmadas, têm transição terminal atômica e impedem novo efeito após recibo. O serviço revalida o contexto operacional e o fingerprint antes de executar a ação humana equivalente.

O painel não consegue mais emitir challenge: a policy de inserção exige `sub` ausente, destinada ao worker autenticado. O painel somente confirma seu vínculo atual. Isso fecha o bloqueio indevido entre pessoas da mesma igreja que existia quando o painel podia atrelar uma conversa alheia a seu challenge.

O catálogo agora elimina homônimos antes de emitir handles, normalizando rótulos e omitindo pessoas, células e encontros cuja descrição não é única. Os handles continuam opacos e não incluem telefone nem identificadores de domínio.

O teste exato de migration lê o SQL bruto, confere o SHA e o executa por DBAPI em banco descartável nomeado. Ele não transforma `public` em schema auxiliar. A prova comportamental em schema isolado continua complementar, e não substitui essa prova literal.

## Evidência informada pelo root

Não executei banco nesta revisão. Foram informados como concluídos no candidato acima: SQL literal e exato `6/6` aprovados, integração PG do worker `18/18` aprovada e testes focais anteriores de propostas, revalidação de termo, privacidade de histórico, homônimos, rollback e TTL aprovados. Esses resultados sustentam o candidato somente nos hashes indicados.

## Limites materiais

Esta aprovação não cobre o candidato integrado completo de `privileged_turn`, transporte LLM, UI, release, deploy, nem envio externo. Também não mede qualidade do modelo. O catálogo é deliberadamente limitado às primeiras 8 pessoas, 16 handles, 64 células, 4 encontros em janela de 14 dias e 10 células em consultas readonly; alvo fora dessa janela exige novo pedido ou encaminhamento humano. O rollback de tabelas de auditoria não desfaz um efeito ministerial já consumado.
