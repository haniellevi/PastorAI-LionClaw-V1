# Manutenção da API legada, outubro de 2026

Este perfil atende à autorização do proprietário em 02/10/2026 para corrigir o
backend e publicar as otimizações de desempenho. A rota é restrita à API
compatível com o schema ativo. O release integral continua sujeito ao contrato
de `BACKEND-RELEASE-MANUAL.md`; seu workflow e suas proteções não são alterados.

## Motivo e escopo

O preflight privado de 02/10, entre 15:35Z e 15:54Z, encontrou a API legada
`eb5a09b975160f993a3c31bd3c28edc89d9a38ff`, 70 entradas no ledger e ausência de
`notification_outbox`, `cell_report_reminders` e
`consolidation_whatsapp_activation`. O backend da main exige essas estruturas.
Aplicar migrations de funcionalidades futuras para publicar performance
misturaria operações com requisitos diferentes.

O candidato é um backport sobre esse SHA legado. Mantém modelos, migrations,
workers, protocolo de fila e webhook fixados na versão antiga. As dependências
PyJWT 2.15.0 e urllib3 2.8.0 vêm dos locks corrigidos da main
`b3b93de934e515f7bdb51a5d4393611707089b10`; a atualização se limita à nova API,
pois os workers preservam sua imagem anterior.
Publica apenas consultas, paginação, bootstrap, pools e observabilidade da API.
O perfil versionado fixa ambos os manifestos e a lista exata de arquivos
alterados. O SHA do orquestrador na main difere do SHA do aplicativo publicado.

## Prova do ambiente e limites

A comparação da imagem ativa com snapshot privado do SHA legado conferiu 145
arquivos Python de aplicação e `requirements.lock`, sem diferenças, ausências
ou extras. A inspeção SQL usou a conexão já existente na VPS, com transação
read-only, timeout e rollback; nenhuma linha de domínio foi lida.

O contrato de manutenção contém exatamente as 70 migrations observadas, sem
inserir ou apagar ledger. Seu digest canônico é
`b72354391819a5d890be6029f88c8d9dc09d765d44c5d9dedf45ebf873d5396a`.
As oito migrations selecionadas pela árvore antiga e ausentes nesse ledger
continuam pendentes: dois backfills de julho, D1a, três frentes D2 pausadas,
preservação de platform admins e configurações Jev. Essa divergência não é
reclassificada como migration aplicada.

O checker confere presença e tipos de 153 colunas de 13 tabelas usadas pelos caminhos otimizados,
RLS habilitada, SELECT de `authenticated`, ausência de propriedade por essa
role, conjunto completo de policies dessas tabelas e a função de resolução
do tenant, inclusive linguagem SQL. Preserva a configuração legada de FORCE RLS, desativada nas 13 relações
desse recorte; o papel `authenticated` não é proprietário nem bypass. Não é auditoria de todo o banco nem prova de
consistência dos dados históricos. Testes cross-tenant de comportamento usam
PostgreSQL 17 descartável com dados sintéticos.

O status sanitizado de backup indicava `verified`, concluído em
`2026-10-02T06:16:05Z`, com 32.634.046 bytes. O arquivo foi conferido às
16:01Z: tamanho e SHA-256 coincidem com o status. Isso não equivale a um
teste de restauração do Supabase. Esta manutenção não escreve
schema e usa a imagem anterior, preservada localmente, para recuperação.

## Preparação e publicação

1. Fixar candidato completo, CI, revisão, arquivo de transporte e digest em
   `maintenance-profile.json`. Campos ausentes ou provisórios bloqueiam execução.
2. Integrar o perfil e o driver na main após revisão e CI. Criar snapshot privado
   desse SHA exato para obter os digests dos três arquivos operacionais.
3. Pelo console Hostinger autenticado, baixar driver, checker e perfil do SHA
   exato. Conferir seus SHA-256 antes de executar qualquer um deles. Baixar o
   arquivo do aplicativo do SHA e digest fixados no perfil, sem refs móveis.
4. Executar o preflight do driver, que verifica fonte da imagem antiga,
   configuração, workers, arquivo de transporte e schema antes de substituir
   serviços. O checker deve passar também na imagem candidata.
5. Substituir somente `backend`, com parada graciosa, tag exclusiva e imagem
   identificada por digest. Não executar `up` da stack inteira nem reutilizar
   `pastorai-backend:latest`. A janela pode causar breve indisponibilidade da API
   e do recebimento de webhooks enquanto a porta é transferida.
6. Conferir `/health`, `/ready`, SHA de resposta, schema e invariantes dos três
   workers. Registrar recibo sanitizado distinguindo API e workers.

O driver não fecha ou reabre gates de envio, não altera `AgentConfig`, não
processa filas e não promove `/opt/pastorai-current`, pois os workers continuam
na árvore legada. A configuração privada existente é preservada. O estado
misto fica explícito no recibo de manutenção e deve ser considerado antes da
próxima operação com Compose ou atualização integral.

## Falha e recuperação

Falha anterior à troca preserva a API ativa. Falha posterior interrompe a API
candidata e recria somente o serviço `backend` com a imagem antiga capturada,
sem rebuild, download, migration ou alteração dos workers. A recuperação é
verificada por saúde, configuração e schema. Se também falhar, preservar os
artefatos privados e o recibo para intervenção, sem tentar alterações de banco.

Não remover imagem antiga, árvore legada, configuração ou volumes após sucesso.
Não provisionar credenciais SSH ou secrets de Actions para esta rota de console.
O perfil não aprova o Environment `backend-production`, não substitui sua revisão
e não abre a rota de release integral. A expansão V1a/V2b/V3 continua separada.

## Evidência automatizada

`deploy/tests/test_maintenance_release.py` exercita preflight, troca e recuperação
com falhas injetadas e invariantes de workers. `test_maintenance_schema.py`
rejeita ledger, policy, coluna, role e função divergentes.
`test_maintenance_schema_pg.py` verifica o catálogo real em PostgreSQL 17
descartável, inclusive policy permissiva extra e RLS desativada. Os workflows
de backend e RLS executam essas verificações. Resultados de produção devem ser
adicionados ao recibo de desempenho somente após execução confirmada.

Candidato fixado: `07a3f4d9a4fe510cf83fd48d5deaa52dcfbb7e02` (PR #455).
Validação local: 5.494 testes offline, 373 PostgreSQL 17 sem skips e 97 testes
focais independentes. Locks de runtime e auditoria sem vulnerabilidades
conhecidas na consulta de 02/10. Driver: 26 testes; contrato de schema:
18 unitários e 8 PostgreSQL 17. Uma transcrição inicial marcou FORCE em `celula_membro` incorretamente;
o checker vivo recusou o perfil antes de qualquer troca. O contrato corrigido
preserva a configuração observada, sem executar ALTER TABLE.
Os 153 tipos também coincidiram na inspeção read-only de produção às 16:10Z.

## Resultado de produção

As PRs [#455](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/455) e
[#456](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/456) concluíram
todos os checks com sucesso. O orquestrador integrado na main
`9f2e87da62255e2bc53a7052be3018c0b51c189b` publicou somente a API do candidato
`07a3f4d9a4fe510cf83fd48d5deaa52dcfbb7e02`. O driver terminou com código `0`
às `2026-10-02T16:45:01Z`; a pós-verificação ocorreu às `16:46:26.929711Z`.

A imagem publicada é
`sha256:4a65f30e1c2dfbcf84c88e9c88203a4176a8d10f7d1b345248bc367ec9a9b241`.
O checker read-only aprovou 70 entradas no ledger, 13 tabelas e 153 tipos de
coluna. Os seis serviços protegidos mantiveram IDs, imagens, início e reinícios;
gates e symlink da stack foram preservados. Houve breve indisponibilidade
observada na troca, sem medição exata de duração. Saúde e prontidão públicas
retornaram 200 e quatro rotas protegidas recusaram acesso anônimo com 401,
todas com o SHA esperado no header. Não houve migration ou rollback.

O [recibo sanitizado](../docs/performance/2026-10-02-backend-maintenance-production.json)
fixa CI, digests e observações; o
[registro de desempenho](../docs/performance/2026-10-02-fluidity-release.md)
mantém os limites. Os workers continuam com imagem e dependências legadas.
Latência autenticada, RNFs de campo e restauração do banco não foram validados
por essa publicação.
