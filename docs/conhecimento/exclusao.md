# Exclusão de conhecimento oficial

Admin web confirma `EXCLUIR DOCUMENTO` em POST
`/conhecimento/documentos/{id}/excluir`, com `operacao_id` UUID. A mesma operação
recupera o recibo após falha de rede; outro ator/alvo não pode reutilizá-la.
O servidor e a função SQL revalidam subject web, papel ativo e igreja.
A resposta sai após commit. O admin não ganha leitura do conteúdo restrito.

Uma transação bloqueia o documento no mesmo caminho editorial e apaga todas as
versões, trechos, tsvector e entradas GIN (FK CASCADE). Recibos editoriais
permanecem inalterados; a FK deles à versão é retirada para preservar IDs de
auditoria sem conteúdo. O novo recibo guarda somente IDs, contagens e data.
Não há embeddings, vetores externos, uploads ou Storage neste domínio.
Futuros derivados precisam integrar a exclusão antes de habilitados; camadas
externas exigirão fila durável/recibo pendente como #509/#518. Não se apagam
conversas privadas ao remover conhecimento oficial.

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
