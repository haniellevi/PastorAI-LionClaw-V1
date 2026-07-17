# Release de backend - fd651f9 - 2026-07-17

**Commit:** `fd651f9` (`origin/main`)
**Deploy:** sim, producao

> Escopo deste registro: fato do release e confirmacoes abaixo. Nao inclui
> endereco de rede, caminho de servidor, nome de container, comando de
> implantacao, credencial, token ou chave.

## Escopo funcional

O release inclui a conclusao de **SEC-ALTO-004** (PR#186):

- `verify_session_token`, `verify_reset_token` e `verify_invite_token` passaram
  a delegar a validacao criptografica para `ClerkClient.verify_purpose_token`;
- algoritmo, segredo, issuer, expiracao e claims obrigatorias permanecem
  validados por fluxo;
- as assinaturas publicas e as mensagens externas de erro foram preservadas;
- a verificacao do state OAuth do Google Calendar continua usando a mesma
  politica compartilhada.

Nao ha migration neste release.

## Verificacao

- Health check publico: **200** apos o deploy.
- Backend iniciado e saudavel apos a atualizacao.
- Workers de fila e cron permaneceram em execucao, sem reinicio.
- Runtime confirmou a presenca de `verify_purpose_token` e o uso das mensagens
  de erro especificas dos fluxos session, reset e invite.
- `CENTRAL_ROLES` continuou centralizado em sua unica definicao.
- Nenhuma exposicao de segredo foi identificada no pacote, deploy ou neste
  registro.

## Evidencia de codigo e teste

O commit `9284038` da PR#186 esta contido no merge `fd651f9`. Os testes cobrem
roundtrip valido, expiracao, issuer incorreto, claim ausente e isolamento entre
os fluxos session, reset, invite e state em
`backend/tests/test_clerk_jwt_policy.py` e
`backend/tests/test_calendar_oauth.py`.

## Rollback

Foi preservado um backup do backend anterior e o pacote do commit publicado.
Nenhuma alteracao de schema ou dado exige reversao.
