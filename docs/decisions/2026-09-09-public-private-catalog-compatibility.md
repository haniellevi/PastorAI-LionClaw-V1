# Compatibilidade público × privado — autoria A+C

Estado: implementação candidata em validação, sem autorização operacional.
Base de autoria: `2ae100c30ed29cac32c3fd14e09a3f6002b8c2df`.

## Decisão e fronteiras

A âncora do stream privado permanece no prefixo público imutável de 75
migrations. O head público completo deve ser validado contra seus arquivos
antes de conferir o prefixo; a validação longitudinal contra a base Git
autenticada permanece obrigatória. Esta transição admite um append público
TENANT; não altera o head, schema ou SQL do stream privado.

A entrega é coordenada na mesma árvore: SQL público, head candidato,
consumidores, compatibilidade de fonte/CI/replay/recibo e testes. Nenhum
verificador histórico byte-pinado é modificado. Não é permitido simplesmente
aceitar contagem maior, ignorar appends ou produzir um catálogo truncado.

O replay completo deve comprovar 76 públicas + 1 privada = 77, com delta
RLS/ACL público e controles privados finais. A segunda ordem de prova é
75 públicas + privada + append público; não presume que instalações antigas
possuíam a ordem de um banco criado do zero. Uma ordem verde não substitui a
outra. O recibo distingue a âncora histórica do head corrente e vincula SHA,
digests, contagens e ordem. Recibo histórico de 75+1 não prova 76+1.

## Re-vinculação e preservação

Original congelado, fora desta PR:
`20260908_175522_consent_evidence_store_lab.sql`, SHA-256
`99818c24e9d41ad0e28f4d97b870da4f857b6a2fb35d53b28d14bf922d871302`.
Novo arquivo criado por `new_migration.py draft`:
`20260909_004005_consent_evidence_store_lab.sql`.
Somente a primeira linha de metadados foi re-vinculada (base e basename).
Todo o restante foi comparado byte a byte; SHA-256 do corpo:
`63ff766ade1671bb18faba5292daf00ddb6075bd8d24b47fa56ecce27f70ea59`.
Hash do novo arquivo completo:
`caccfbbcdfc3f57d5adc0ee9d9016e92e8fa1bc05929059966d86292ddb43b1a`.

`prepare-head` renderizou um append terminal, sem publicação operacional.
Hash do head candidato:
`38aac6b4349c168f38d24a1f1cfc81843139dce938f596cd92d30b261dbe3dd3`.
Digest público corrente candidato:
`9942997137c34f807dbc9d0800add85ae3c74940df20f27e42361d0ce43c3fdc`.

O adapter PostgreSQL mantém o hash congelado
`c1336a890c5c3672c7940bb5523049f5f3e39212134bac5b7d56cad990bb34a6`.
A cópia do teste PG17 mínimo muda somente o nome da migration: hash anterior
`09672083f08da9f58ffdd8bb329b915c56bf1bf8c9c16ee536c08c44b984192c`, novo
`9bbc9a967c23407ccdf9ca8bd4d8ac3378e21c842f166c513b465544835a8e6b`.
A cópia do teste canônico adapta exclusivamente as fixtures de preparação:
usa o banco de manutenção autorizado pelo launcher para criar seu banco
descartável via replay do snapshot privado do commit. Não depende do banco
de outro job. As asserções de comportamento não mudam. Originais permanecem
congelados na worktree anterior.

## Segurança e aceite

- A exceção D2B2 permite somente o adapter exato, autenticado por hash, que
  observa o ledger. Não autoriza escrita no ledger nem um novo caller.
- Recusa inicial não é concessão. `concedido` continua bloqueado.
- Retenção e cascatas são as do contrato E1–E3; não há promessa de prova
  anonimizada após exclusão. Permissões históricas de laboratório permanecem
  explícitas e separadas do replay canônico puro.
- Fonte para replay/atestação: snapshot privado do SHA exato via
  `trusted_repository_snapshot.py`; nunca o checkout compartilhado.
- Testes devem rejeitar prefixo adulterado, append inválido, base incorreta,
  recibo antigo/adulterado e regressões RLS/ACL em ambas as ordens.
- Manifestos de expectativa histórica de 75 não são reescritos como se
  atestassem 76. Consumidores distinguem prefixo, head e evidência histórica.

## Reversibilidade e limite

Esta é autoria revisável, sem aplicação compartilhada. Não existe rollback
operacional a executar nesta missão. Alteração futura do catálogo exige nova
revisão longitudinal; não se remove um append já aprovado para esconder sua
história. O plano de compensação da migration permanece o da intent.

Não há writer/caller operacional, ativação, dados reais, envio ou acesso a
DEV/PROD. `operational_authorization=false` e `next_stage_authorized=false`.
Próximo gate humano: revisão e autorização separada de merge desta árvore;
merge não constitui autorização de aplicação.
