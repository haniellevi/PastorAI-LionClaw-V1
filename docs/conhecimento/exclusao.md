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
