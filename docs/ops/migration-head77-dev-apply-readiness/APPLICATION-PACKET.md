# Pacote de decisão para aplicação futura em DEV

## Decisão executável atual

`DECISION=NO_GO_DEV_LEDGER_DIVERGENCE_AND_NO_AUTHORIZED_APPLY_RUNNER`

Não autorizar aplicação do head 77 em DEV no estado observado. O ledger
público contém 33 nomes, deixa de ser prefixo do catálogo na posição 25 e tem
44 arquivos do catálogo ausentes. Aplicar somente o último SQL ignoraria a
cadeia; aplicar os 44 por inferência poderia repetir efeitos já existentes.
Além disso, não existe runner catalog-bound autorizado para essa operação.

| Campo fixado | Valor |
| --- | --- |
| Release alvo | `5e2082e94db2b6af6b34cfe351d81cf54b85aa76` |
| Branch | `docs/migration-head77-dev-apply-readiness-readonly-20260915` |
| Parent Git | `615408514103be1d67bcafa182b5b3b05f1c3e73` |
| Catálogo público | 77 migrations |
| Digest do catálogo | `162854e0f753f5ad867aacae6b450d46d5c4bd68f8c3089be144d133ddc73801` |
| SHA-256 do head atual | `88e588660f995f774fe298d2bd4e5ea80d399006379661156b7eff28a6940a57` |
| SHA-256 do head aprovado anterior, 76 | `38aac6b4349c168f38d24a1f1cfc81843139dce938f596cd92d30b261dbe3dd3` |
| SQL E4b | `20260910_142830_add_e4b_consent_persistence.sql` |
| SHA-256 do SQL E4b | `64c031beea4d74feed83337ea623173d0f8d848c685ffcf5365b279a6ea7d1fd` |
| Estado de autorização da fonte | bloqueado |

## Estado DEV observado

| Evidência | Resultado |
| --- | --- |
| Ambiente | `Igreja12-dev`, atribuição humana de Raniel; target binding técnico não compartilhado |
| Coleta | PostgreSQL 17.6, TLS ativo, `REPEATABLE READ READ ONLY`, rollback concluído |
| Ledger público | 33 entradas; todas conhecidas; posições 0 a 24 coincidem; posições 25 a 32 divergem |
| Ledger nativo | seis versões independentes; nenhum mapeamento inferido |
| Diferença catálogo para ledger público | 44 arquivos, incluindo evidence store e E4b |
| Relações E4b | seis ausentes |
| Alteração produzida | nenhuma |

A reconciliação completa, incluindo as oito posições divergentes e os 44
arquivos ausentes do ledger público, está em
`DEV-LEDGER-RECONCILIATION.md`.

## Bloqueio técnico demonstrado

O wrapper V2 permite somente `list` e bloqueia `status`, `bootstrap-ledger`,
`harden-ledger` e `apply` antes da conexão. O V3 permite somente `describe` e
`validate`, não possui leitura de arquivo, driver, descritor, conexão, SQL ou
caminho de apply. Sua ligação literal aponta para o snapshot C3 integrado
`36999c2f9bfca8035afb886509440fc3760d9154`, ancestral alcançável do release
fixado acima, conforme o desenho source-only; ela não autentica por si só o
release nem o alvo DEV. `apply_migrations.py` é legado e não é entrypoint
autorizado.

Não há runner catalog-bound seguro disponível para aplicar este candidato em
DEV. Mesmo o runner legado recusaria o estado antes de SQL porque exige um
prefixo íntegro e no máximo uma migration pendente. Cada um desses dois
bloqueios é suficiente para abortar.

## Pré-condições fechadas para uma missão futura

Todas devem ser verdadeiras, verificadas no mesmo candidato e anexadas como
evidência sanitizada. Uma lacuna bloqueia a aplicação inteira.

1. A fonte privada do SHA exato foi materializada e autenticada pelo mecanismo
   aprovado, sem depender de checkout compartilhado.
2. O verificador canônico do catálogo confirma 77 entradas, o digest e o prior
   76 acima, com `OPERATIONAL_AUTHORIZATION=BLOCKED` preservado até a decisão
   externa.
3. A saída VPS foi completada em `2026-09-15T01:56:43+00:00`: release
   `c525d6a`, quatro containers saudáveis e image ID
   `sha256:833d51b5ff40b6bcb576d90449054da342cdfda24d5b93046033c466cda2b1f7`.
   A cronologia é coerente, mas não substitui proveniência criptográfica de
   build. A coleta DEV e as linhas sanitizadas dos dois ledgers foram recebidas.
4. O preflight DEV terminou em `REPEATABLE READ READ ONLY` e `ROLLBACK`, em
   PostgreSQL 17.6, sem erro relatado. A atribuição a `Igreja12-dev` é humana;
   um target binding técnico e os booleanos sanitizados de privilégio do
   principal não constam do resumo recebido.
5. Os ledgers público e nativo foram capturados separadamente e reconciliados
   sem igualá-los. O resultado atual é `BLOCKED_LEDGER_DIVERGENCE`: 33 entradas
   públicas fora do prefixo canônico e seis versões nativas sem mapeamento.
   Nenhuma delas pode ser preenchida, reordenada ou reparada por inferência.
6. As seis relações E4b estão todas ausentes, antes de uma aplicação ainda não
   realizada, ou todas presentes com a forma exata esperada depois de uma
   aplicação já comprovada. Presença parcial, objeto homônimo, metadado
   divergente, RLS não forçada, policy incompleta ou ACL adicional abortam.
7. Uma missão separada entregou um executor catalog-bound de aplicação que
   autentica o snapshot, os bytes do SQL e do head, o alvo DEV, o principal,
   PostgreSQL 17, TLS e a decisão de cutover antes de qualquer SQL.
8. A mesma missão recebeu autorização humana nominal autenticável, runtime e
   dependências atestados externamente, anti-replay durável e canal seguro de
   descritores. Nenhum desses requisitos pode ser substituído por texto deste
   documento, HMAC local ou flag.
9. Revisão humana do SQL E4b, do escopo `TENANT`, de RLS, ACL, funções,
   triggers e limites não cobertos pelo replay foi concluída para o SHA exato.

## Critérios de aborto

Aborte antes de qualquer aplicação se ocorrer qualquer condição abaixo:

- SHA, digest, head, SQL ou release observado diferente dos valores fixados;
- PostgreSQL fora da major 17, transação não read-only no preflight ou saída
  sanitizada incompleta;
- papel privilegiado ou identidade de sessão incompatível com o principal que
  uma futura decisão tiver aprovado;
- ledger ausente, com forma inválida, mais de 2048 entradas, divergência sem
  decisão humana, ou tentativa de reparo automático;
- ledger público fora do prefixo canônico, mais de uma migration ausente ou
  qualquer tentativa de tratar os 44 arquivos como fila de aplicação;
- um subconjunto, uma relação extra, RLS não forçada, policy fora de
  `app.tenant_igreja_id`, grant inesperado ou trigger, constraint ou índice
  divergente nas relações E4b;
- ausência de executor seguro, trust anchor, autorização externa, anti-replay
  ou decisão de cutover;
- qualquer pedido de `apply_migrations.py`, SQL Editor, copy/paste de DDL,
  bootstrap, hardening, `db push`, backfill, downgrade ou PROD.

## Mecanismo humano mínimo permitido agora

As duas coletas foram concluídas sem alteração. A decisão segura disponível a
Raniel neste pacote é manter a aplicação bloqueada. Se quiser prosseguir, o
único gate seguinte é autorizar nominalmente uma missão própria de remediação
do histórico DEV e do executor catalog-bound, preservando os ledgers sem
backfill ou reordenação. Essa missão precisa produzir evidência de schema para
cada lacuna, decisão de epoch/cutover, target binding e um runner revisado antes
de pedir autorização de aplicação. Este pacote não concede esse gate.

## Sequência futura DEV, condicionada a nova missão e gate

1. Congelar o SHA exato e criar snapshot privado autenticado.
2. Reexecutar a validação canônica source-only e registrar a ligação completa.
3. Vincular a captura DEV a um target binding técnico sanitizado e atestar o
   principal sem expor sua identidade.
4. Determinar, com evidência de schema e decisão humana por item, o estado dos
   44 arquivos ausentes do ledger, sem copiar ou alterar nenhum ledger.
5. Aprovar uma decisão de epoch/cutover que preserve os dois históricos e
   transforme o estado resultante em uma fila explícita, nunca inferida.
6. Parar se qualquer pré-condição ou critério de aborto falhar.
7. Somente o executor catalog-bound futuro e aprovado poderá iniciar a fase de
   aplicação, sob a autorização nominal daquela missão.
8. Depois de uma decisão de commit comprovada, repetir o preflight read-only e
   comparar ledger e metadados com os bytes fixados, sem consultar payload de
   domínio.

## Verificação pós-aplicação futura

O sucesso futuro só poderá ser afirmado após evidência separada de ledger,
metadados físicos das seis relações, RLS habilitada e forçada, policies
permissiva e restritiva, revokes, constraints, índices e triggers. O preflight
não prova Data API, runtime, caller, recebimento de consentimento, efeito de
domínio ou aplicação em PROD.
