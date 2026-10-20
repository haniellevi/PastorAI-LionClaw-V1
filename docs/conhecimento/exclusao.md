# Exclusão de conhecimento oficial

No painel, o admin confere título, assunto e total de versões e digita o título
exato para habilitar a confirmação. A API recebe `EXCLUIR DOCUMENTO` em POST
`/conhecimento/documentos/{id}/excluir`, com `operacao_id` UUID. A mesma operação
recupera o recibo após falha de rede; outro ator/alvo não pode reutilizá-la.
O servidor e a função SQL revalidam subject web, papel ativo e igreja.
A resposta sai após commit. O admin não ganha leitura do conteúdo restrito.

Uma transação bloqueia o documento no mesmo caminho editorial e apaga todas as
versões, trechos, tsvector e entradas GIN (FK CASCADE). Recibos editoriais
preservam os IDs e metadados; seus fingerprints derivados do payload são
substituídos por um valor fixo sem conteúdo dentro da mesma função SQL. A FK
à versão é retirada para preservar os IDs de auditoria. Replay editorial de
documento apagado retorna 410, sem recriar snapshots. O novo recibo guarda
somente IDs, contagens e data.
Não há embeddings, vetores externos, uploads ou Storage neste domínio.
Futuros derivados precisam integrar a exclusão antes de habilitados; camadas
externas exigirão fila durável/recibo pendente como #509/#518.

As mensagens com marcador interno `kind=conhecimento` e fonte vinculada ao
documento ou a suas versões têm a citação inteira redigida e o reenvio
suprimido na mesma transação. A leitura da fonte mantém lock compartilhado
até persistir a citação, serializando com a exclusão. As demais mensagens são
preservadas. A FK composta do recibo para `app_users` é diferível, validada
no commit e compatível com a cascata da igreja.

Aplicar `20261019_110001_conhecimento_exclusao.sql` via `backend/scripts/migrate.py`
em PG sintético antes dos callers. Dono SECURITY DEFINER exige BYPASSRLS ou
superusuário, sem associação dos papéis de aplicação. `search_path=pg_catalog`,
relações qualificadas, revokes, RLS ENABLE/FORCE e guarda do caminho privilegiado.
DELETE direto é recusado; UPDATE imutável não recebe exceção.
Cascata cadastral privilegiada da igreja continua possível. Rollback comentado
recusa recibos existentes e não recupera conteúdo apagado.

Sarah revisa RLS, função/migration e autorização antes da integração.
Sem merge, migration remota, deploy, envio real ou abertura de gates.
Produção, aplicação remota e cópias em backups: não verificadas.

A prévia `conversations.ultima_mensagem` recebe o marcador antes da redação,
quando coincide com o texto removido na conversa ou quando sua última mensagem
(ordenada por `criado_em`, `id`) está entre as redigidas. Com a #526 instalada,
o resumo privado inteiro e sua correção humana são removidos nas conversas
afetadas, com fontes em cascata; o trigger `private_summary_source_changed`
continua disparando no UPDATE e invalida as tarefas na mesma transação.
O caminho tipado de conhecimento não grava o texto citado em
`agent_conversation_logs`; o grafo está compilado sem checkpointer/store durável.
Isso não atesta logs externos ou acervos de versões anteriores.

Cópias já entregues ao WhatsApp do usuário ou ao provedor não são apagadas.
Uma mensagem já lida da fila antes da exclusão pode ser enviada fora da
transação: a supressão persistida não recolhe texto já carregado pelo consumidor.
Backups e sua eventual retenção do conteúdo não foram verificados.

Se o `app_user` autor de uma exclusão precisar ser removido depois, a FK
`conhecimento_exclusoes_ator_fk` diferida impede o commit da remoção isolada.
No procedimento atual, preserve esse registro e inative o acesso pelo fluxo
administrativo, revogando seus papéis/sessões; confira a inativação no servidor.
Não apague recibos, não substitua o ator por outra pessoa e não desabilite a FK
para contornar o bloqueio. Hard delete individual exige uma mudança revisada
que permita anonimização sem perder o recibo; ainda não está implementado.
A cascata da igreja remove ambos na mesma transação e não autoriza, por si só,
exclusão cadastral ou operação remota.
