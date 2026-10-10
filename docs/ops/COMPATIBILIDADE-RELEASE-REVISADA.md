# Compatibilidade entre releases

T10 prepara uma opção estrita de `backend-release.sh`. Sem bundle, o checker e
o ledger continuam com o comportamento anterior. Esta opção não aplica SQL,
publica frontend, abre gate, autoriza PROD ou substitui preflight/backup da
operação de release.

## Evidência necessária antes da operação

Reconstruir independentemente o schema da versão anterior e do candidato pelas
migrations ativas de cada artefato, incluindo o bootstrap nominal da plataforma
(roles, grants e defaults do Supabase). Um PostgreSQL vazio com roles mínimas
não representa automaticamente o catálogo do projeto hospedado. Nunca capturar
PROD e simplesmente rotular o resultado como expectativa aprovada.

O bundle JSON tem `previous_sha`, `candidate_sha`, `previous` e `candidate`.
Cada referência tem `catalog` e `migrations` no formato do módulo
`schema_compatibility.py`. Os SHAs precisam corresponder aos releases exatos;
as listas precisam corresponder aos manifestos selecionados pelos runners de
cada versão. O proprietário/revisor examina o catálogo e aprova seu SHA256.
Esse hash associa o conteúdo revisado, sem provar sua origem por si só.

Confirmar nominalmente o alvo vivo, versão do PostgreSQL compatível com as
consultas de catálogo, imagem/digest e código do backend implantado. O marcador
PASTORAI_RELEASE_SHA deve corresponder ao SHA anterior. ENV e label isolados não
são prova completa da procedência da imagem. Não falsificar o marcador para
passar o verificador quando o release implantado for desconhecido.

O verificador de produção só admite o projeto nominal
`pffafnchtxbimpwyaczq`, host e usuário diretos ou do pooler correspondentes,
dbname postgres e porta explícita 5432/6543. Query de conexão exige exatamente
`sslmode=verify-full&sslrootcert=system`; service, host e options extras são
recusados. Identidade, TLS ou catálogo desconhecido impedem o passo. Não
alterar credencial ou routing de PROD como efeito implícito deste preparo.

## Uso na futura janela autorizada

Fornecer ao release `RELEASE_SCHEMA_BUNDLE` (arquivo JSON absoluto, não symlink)
e `RELEASE_SCHEMA_BUNDLE_SHA256` (o hash revisado), além do SHA candidato exigido
pelo comando existente. Consultar o runbook operacional e obter as autorizações
nominais de banco, backup, release e efeitos; essas variáveis não as concedem.

Antes da troca, o verificador emitido roda uma transação read-only no backend
anterior. O catálogo vivo deve corresponder integralmente à reconstrução do
candidato, o ledger deve ser exatamente o conjunto candidato e todos os
contratos anteriores devem permanecer compatíveis. Novo grant/policy/constraint
em objeto anterior, mudança de role, ownership, coluna obrigatória sem default,
índice único novo ou objeto anterior removido/redefinido são recusados.

Somente depois dessa prova o checker anterior recebe o manifesto completo do
candidato, mantendo suas exigências de colunas e a recusa de migrations
desconhecidas. Não existe um modo de aceitar extras indiscriminadamente. A
recuperação repete a prova antes de iniciar código anterior. Erro mantém a
contenção e exige recuperação humana; banco e dados não são restaurados pelo
script.

O caminho legado continua restrito aos gates fechados que já exigia e não os
fecha como estratégia de pausa. A contenção física sem perda de fila foi
ensaiada no executor DEV sintético. A promoção real precisa preparar a janela
com consumidores contidos e artefatos nominais, publicar frontend compatível e
conferir prontidão/aceite. Não usar fechamento de gate para contornar uma
pendência: outbox pode cancelar itens, e reabrir o gate não os recupera.

## Provas locais

PostgreSQL17 descartável com migrations ativas exercita migração aditiva,
backfill e catálogo/ledger, rejeita drift de RLS, SHA/manifesto divergente, hash
não revisado e o alvo loopback no verificador emitido para PROD. A regressão do
release conserva recusas e ordem do modo padrão. Esta evidência não é prova de
compatibilidade ou disponibilidade de PROD hoje.

Frontend é construído por alvo, com NEXT_PUBLIC incorporado no build, e a
imagem final do ensaio DEV foi validada em processo separado. Publicação
Vercel, troca de branch de produção, autenticação/Storage online e recuperação
dos dados de um alvo real continuam operações próprias, depois do preparo e
da autorização. A sequência dos PRs precisa ser integrada e revalidada antes.
