# Parecer Sarah recebido via Conselheiro Claude

SHA: `5e3643f7eb7ba97267af6c0aff60d1bda43a67f1`.
Base: `702c8353e8f76b629d857b0637046bf2a78b88b8`.
Patch SHA256: `9a886365bbdc2f936751e934f8a824008425da325d830a8fcbd30ebf2958b860`.

MERGE: GO. DISPATCH, deploy, banco, VPS e PROD: NO-GO.
P0=0, P1=1, P2=5. OPERATIONAL_AUTHORIZATION=BLOCKED.

Este artefato é o registro sanitizado do retorno final do Conselheiro Claude pela CLI Maestri, após encaminhamento do pacote solicitado por Conselheiro Opencoded com aval operador humano. Não é revisão realizada pelo Orquestrador. Claude informou que não gerou arquivo próprio de parecer. O retorno recebido confirmou o SHA e o hash do patch; informou teste local de 38 casos de deploy e 18 do runbook, sem revisão viva de GitHub, banco, VPS ou PROD. Contagens de CI foram conferidas separadamente pelo Orquestrador.

P1 residual informado: as operações Compose novas em `deploy/backend-release.sh:132` e `:167` foram exercitadas somente contra dublê. Compatibilidade operacional precisa ser verificada e registrada no manual antes de qualquer futuro deploy, mediante missão e gate próprios. Sarah classificou esse P1 como pré-deploy e declarou GO somente para merge. A contagem P2=5 foi recebida; a enumeração dos cinco itens não veio no retorno final disponível, portanto não é reconstruída nem presumida encerrada.

O pacote source-only não prova compatibilidade da VPS. Nenhum teste operacional é autorizado por este parecer. O Orquestrador mantém merge e dispatch bloqueados; próximo gate humano único é autorização nominal de operador humano para `merge #440`, seguida de preflight vivo completo antes de qualquer execução. Dispatch e fechamento do P1 são etapas posteriores independentes.

Resultado encaminhado por `maestri ask "Conselheiro Opencoded"`, com GO/NO-GO, P0/P1/P2, SHA completo e limites. Não foram criados cabos, removidos artefatos ou recrutados especialistas.

Recebido e registrado em UTC: 2026-09-30T01:51:19.606749+00:00

Nota de publicação: cópia sanitizada de artefato operacional; nomes de operador, caminhos absolutos e endereço sintético foram substituídos. Originais preservados localmente. SHA/hashes de origem permanecem como evidência histórica, não como hash dos bytes desta cópia.

## Complemento recebido posteriormente por artefato

Extrato recebido de Conselheiro Claude; SHA256 da fonte de transporte 534466deb144e01a9cd48c4b98cf5b24fd8e7a0a3b91f6d5832c10ec640a6865 conferido antes da cópia. O retorno anterior só continha contagem. A transcrição abaixo preserva os achados atribuídos à Sarah, sem transformá-los em validação independente do Orquestrador nem declarar achados encerrados. Títulos tiveram apenas pontuação normalizada.

# Achados Sarah : PR #440 / SHA 5e3643f

Fonte: parecer Sarah via Conselheiro Claude (extrato de transporte).
Escopo revisado: SHA `5e3643f7eb7ba97267af6c0aff60d1bda43a67f1`, base
`702c8353e8f76b629d857b0637046bf2a78b88b8`, patch sha256
`9a886365bbdc2f936751e934f8a824008425da325d830a8fcbd30ebf2958b860`.
Veredito: GO apenas para MERGE; NO-GO explícito para dispatch, deploy, banco,
VPS e PROD. `OPERATIONAL_AUTHORIZATION=BLOCKED`.
Contagem: P0=0, P1=1, P2=5.

Nenhum achado é fechado por transcrição. Este arquivo é artefato de transporte,
não deliverable versionado: sanitizar e revisar antes de qualquer entrada em Git.
Caminhos abaixo são relativos ao repositório de propósito.

## P1-1 : Compatibilidade Compose no caminho de release e rollback

Arquivos/linhas: `deploy/backend-release.sh:132`
(`docker compose start --wait --wait-timeout 180`) e
`deploy/backend-release.sh:167`
(`docker compose run --rm --no-deps -T -e EXPECTED_MIGRATIONS=… --entrypoint python backend -`).

Evidência: são duas invocações Compose que o caminho anterior em `main` não
usava, exercitadas apenas contra dublê de shell em
`deploy/tests/test_backend_release.py:45-82`, onde `docker` e `curl` são
scripts falsos. O suporte a `start --wait` foi confirmado somente no binário do
ambiente de revisão, nunca na VPS. O `compose run` age sobre serviço que declara
`container_name: pastorai_backend` em `deploy/docker-compose.yml:115`,
combinação historicamente tratada pelo Compose como incompatível.

Consequência: se o ambiente recusar qualquer uma das duas, o rollback já
executou `docker compose stop` em `deploy/backend-release.sh:154` antes de
tentar reerguer os serviços, e o código anterior não volta. O risco é de
indisponibilidade, não de envio indevido: os quatro gates permanecem fechados.

Correção mínima: declarar em `deploy/BACKEND-RELEASE-MANUAL.md` a versão mínima
de Docker Compose e duas pré-checagens bloqueantes a executar na VPS dentro da
janela autorizada : `docker compose start --help | grep -q -- --wait` e smoke
`docker compose run --rm --no-deps -T --entrypoint true backend`. Alternativa
equivalente e preferível a médio prazo: eliminar a dependência de `compose run`
no rollback, usando `up --no-start` seguido de `start`.

Critério de fechamento: (a) versão mínima declarada no manual e (b) as duas
pré-checagens registradas como precondição bloqueante com resultado observado na
VPS, dentro de janela com gate de deploy próprio; ou (c) o script deixar de usar
`compose run`, com os testes de dublê atualizados provando a nova ordem.
Nenhuma dessas alternativas pode ser concluída nem inferida offline.

## P2-1 : Evidência não versionada e ficha ausente

Caminhos: pacote `docs/ops/backend-predispatch-20260929/` e
`docs/missions/M-2026-09-29-backend-predispatch-hardening.md`.
Evidência: `git ls-tree -r 5e3643f` não lista nenhum dos dois; a worktree
candidata ficava em diretório temporário volátil.
Correção mínima: versionar o recorte canônico em PR doc-only sanitizada, com o
sha256 de cada arquivo registrado no corpo do commit.
Observação: registrado como P2 a pedido do encaminhamento; concordo que não
bloqueia, ressalvando que é o único achado com prazo de decadência.

## P2-2 : Identidade de banco no log de deploy

Arquivo/linhas: `deploy/check_backend_schema.py:121-124`.
Evidência: o preflight imprime `database identity: …` com `current_database()`,
`current_user`, `inet_server_addr()` e `inet_server_port()`, e essa saída
trafega pelo log do workflow de deploy. Não é credencial; é identidade de
infraestrutura.
Correção mínima: declarar em `deploy/BACKEND-RELEASE-MANUAL.md` que o log de
deploy passa a conter banco, usuário, endereço e porta, e restringir quem tem
acesso a esse log.

## P2-3 : Teste que lê texto de documento e de fonte

Arquivo/linhas: `backend/tests/test_production_runbook.py:21-33`.
Evidência: `_release_activation_block()` lê `docs/ops/PRODUCTION-RUNBOOK.md`,
afirma substrings de seção e devolve o texto de `deploy/backend-release.sh`,
sobre o qual outros testes afirmam ordem por `str.index`.
Tensão: o AGENTS.md proíbe criar testes que congelam hash de arquivo ou leem
texto de documento.
Correção mínima: preservar as asserções comportamentais legítimas (extrair e
executar o predicado de gate) e substituir as asserções de ordem textual por
verificação de comportamento, ou assumir a exceção explicitamente no AGENTS.md.
Estado: os 18 testes passam neste SHA; o achado é fragilidade e coerência de
regra, não falha.

## P2-4 : PyJWT não verificável offline

Arquivos: `backend/requirements.txt` (`PyJWT[crypto]>=2.14,<3.0`) e
`backend/requirements.lock` (`pyjwt==2.14.0` com dois hashes).
Evidência: revisão sem rede; não validei os hashes contra índice público nem a
afirmação de auditoria sem vulnerabilidades conhecidas, e o venv local do
projeto tem 2.13.0, portanto nenhum teste local exercitou 2.14.0.
Mitigação: uso restrito a HS256 em `backend/app/services/clerk.py:141` e `:343`
(`jwt.encode` e `jwt.decode` com `algorithms` explícito), sem PyJWKClient, logo
risco de quebra de API é baixo.
Correção mínima: registrar no recibo que a validação de hash e de auditoria
dessa dependência é prova de CI, não desta revisão.

## P2-5 : Runbook sem procedimento de recuperação próprio

Arquivo/linhas: `docs/ops/PRODUCTION-RUNBOOK.md:377-390`.
Evidência: o procedimento manual de build e `up` foi removido e substituído por
ponteiro para `deploy/BACKEND-RELEASE-MANUAL.md`. Somado ao P1-1, não resta
procedimento de recuperação humana no próprio runbook caso o caminho scriptado
seja recusado pelo ambiente.
Correção mínima: incluir esse procedimento no manual, sem reabrir gate.

## Ressalva de custódia sobre o handoff

O sha256 `a6d8a584c46ab0ea22ed92ce516525c012cfa83e2bb4c8e57c494a23693ac760`
refere-se aos bytes de `SARAH-HANDOFF.md` que eu efetivamente li durante a
revisão. Se o arquivo na worktree de controle agora apresenta
`d13d1046b829f0522666ba2e3a65341833306f601f8e0150a5068c3bb636d984`, então ele
foi alterado depois da revisão: os dois valores não devem ser equiparados nem
substituídos um pelo outro. Registrar na ficha o hash dos bytes efetivamente
publicados, e declarar separadamente que a versão lida pela revisão tinha outro
hash.
