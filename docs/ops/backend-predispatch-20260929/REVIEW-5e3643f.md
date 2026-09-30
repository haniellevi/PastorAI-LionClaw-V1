# Adendo LENTE: identidade PG17, SHA 5e3643f

GO source-only. Achado de expectativa fixa do endereço encerrado na revisão de fonte: a correção preserva e amplia a precisão da asserção. P0=0, P1=0, P2=0 abertos nos recortes revisados. Não foi executado ou simulado PG; CI deste SHA ainda precisa confirmar o comportamento.

Ambiente local, horário 2026-09-29T22:16:51-03:00. Papel LENTE, preferência nominal GPT-6.1 Sol low mantida. Worktree exclusiva `[synthetic-worktree]`, HEAD detached conservado na base `702c8353e8f76b629d857b0637046bf2a78b88b8`. Candidato exato confirmado pelo comando solicitado `git -C [synthetic-worktree] rev-parse HEAD`: `5e3643f7eb7ba97267af6c0aff60d1bda43a67f1`.

Arquivo incremental: `deploy/tests/test_backend_schema_pg17.py`. SHA256 local `1843ebccd0538681be6503cec06396a870750cad5fee3df78f9fe9a4546c9a18`. Blob Git local e no SHA candidato coincidem: `60b68957f10b99d6f7ef217b3206d1c9dc44fa49`. Comparação entre 2f00814 e o novo head confirma mudança somente desse arquivo; 15/15 blobs locais do escopo acumulado coincidem com o SHA final. Nenhum arquivo anterior ou parecer foi alterado por LENTE.

## Análise da asserção

Antes, o teste exigia substring `[synthetic-address]` na saída. A URL local identifica o ponto de conexão do runner; não determina que inet_server_addr devolva o mesmo endereço no processo PostgreSQL dentro de Docker. O delta remove apenas essa expectativa fixa e acrescenta import json e consulta independente na conexão target.

A conexão independente usa o mesmo target_url do banco sintético específico criado pelo teste. Consulta exatamente `current_database(), current_user, inet_server_addr()::text, inet_server_port()`, exige uma única linha com `.one()` e converte seus quatro campos para lista. A saída do dry-run é localizada pelo prefixo `database identity: `, decodificada por json.loads e comparada por igualdade exata a `[expected_identity]`.

Assim, banco, usuário, endereço e porta continuam obrigatórios e são comparados campo a campo, incluindo ordem, tipo JSON e cardinalidade externa. Endereço errado, porta/usuário/banco diferente, campo omitido ou estrutura extra não satisfazem a igualdade. Prefixo ausente ou JSON inválido também falham; não há fallback, substring alternativa, tolerância indiscriminada, skip ou aceitação de qualquer IP. As verificações de returncode zero, dry-run OK e presença do nome do banco sintético permanecem.

A consulta esperada não deriva da saída do checker nem reutiliza sua lista retornada: ela obtém os valores em sessão independente. A guarda existente continua exigindo URL host local e banco inicial `rls_disposable`. Os testes negativos de ledger, colunas e RLS/policies permanecem intactos. Nenhuma alteração em checker, release shell, gates, rollback, SQL operacional, requirements ou isolamento foi introduzida.

## Verificações e limites

Executados somente comandos locais de metadados, leitura e inspeção: SHA completo, diff incremental, hashes, igualdade de 15 blobs, `git diff --check` (exit 0) e parse AST do arquivo sem import nem execução (exit 0). Não foram chamados unittest, pytest, dry-run, SQLAlchemy, Docker ou banco. Sem rede, PROD, dispatch, commit, CLI Maestri, agentes, hooks/memória ou leitura de segredo.

O relato de suite RLS anterior aprovada e preflight falho pelo IP Docker foi fornecido pelo Orquestrador, sem consulta remota de LENTE. Encerramento aqui é do defeito de asserção na fonte, não confirmação de execução PG ou verde do novo CI. O parecer acumulado anterior continua aplicável aos demais arquivos preservados, com os limites já registrados.

Recomendo conferir no CI do SHA `5e3643f7eb7ba97267af6c0aff60d1bda43a67f1` o preflight com essa igualdade exata e todos os checks exigidos. Nenhuma flexibilização adicional da identidade é necessária na fonte revisada. Merge e operações futuras permanecem sujeitos aos gates nominais próprios.

Nota de publicação: cópia sanitizada de artefato operacional; nomes de operador, caminhos absolutos e endereço sintético foram substituídos. Originais preservados localmente. SHA/hashes de origem permanecem como evidência histórica, não como hash dos bytes desta cópia.
