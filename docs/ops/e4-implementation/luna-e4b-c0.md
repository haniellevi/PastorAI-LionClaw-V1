# E4b C0, domínio puro

## Escopo da entrega

Implementação delimitada em `backend/app/domain/e4b_consent.py`, com testes
sintéticos em `backend/tests/test_e4b_consent_domain.py`. A worktree é
`/home/raniel-linux/workspace/PastorAi-1.0/.worktrees/e4b-domain-c0-luna-v1`, na
branch `feat/e4b-domain-c0-luna-v1`, baseada em
`c76b14b06188f33b2421b3ad426e359dc0ef487e`.

O módulo é somente Python padrão. Ele modela ações `ACCEPT` e `WITHDRAW`,
origem E4b fechada, concessão `ACTIVE` ou `WITHDRAWN`, vínculos explícitos de
titular, manifestante, responsável e operador, fingerprint canônico,
classificação `ELIGIBLE`, `REPLAY`, `CONFLICT` e `DENIED`, acesso administrativo
no mesmo tenant, receipt minimizado por allowlist, retenção UTC de 24 meses e
legal holds sobrepostos.

Os fatos de autoridade são entregues por `E4bAuthorityResolution`, já
resolvidos pelo servidor. `classify_e4b_intent` recebe somente snapshots E4b e
não chama storage, ORM, migration, banco, caller ou runtime. Artefato legado é
rejeitado antes de qualquer decisão de replay, origem ou concessão. A
construção de uma operação confirmada e a projeção do receipt são funções puras
para futura integração, sem persistência ou envio.

## Cobertura C0

| Caso | Evidência unitária |
| --- | --- |
| C0-U01 | `test_c0_u01_own_accept_is_only_eligible_for_staging` |
| C0-U02 | `test_c0_u02_operator_overlap_without_server_owned_link_is_denied` |
| C0-U03 | `test_c0_u03_withdraw_requires_same_active_e4b_accept` |
| C0-U04 | `test_c0_u04_invalid_withdraw_origin_is_denied` |
| C0-U05 | `test_c0_u05_overlapping_roles_need_explicit_server_owned_links` |
| C0-U06 | `test_c0_u06_same_key_replays_exact_fingerprint_and_conflicts_on_difference` |
| C0-U07 | `test_c0_u07_only_same_tenant_server_owned_admin_can_read` |
| C0-U08 | `test_c0_u08_retention_uses_calendar_24_months_and_never_discards` |
| C0-U09 | `test_c0_u09_overlapping_holds_pause_once_until_last_resolution` |
| C0-U10 | `test_c0_u10_person_delete_is_denied_during_retention_or_hold_and_deferred_after` |
| C0-U11 | `test_c0_u11_receipt_is_an_explicit_allowlist_without_direct_person_ids` |
| C0-U12 | `test_c0_u12_legacy_artifact_is_denied_before_replay_or_origin` |
| C0-U13 | `test_c0_u13_withdraw_then_new_accept_denies_but_old_accept_replays_without_reactivation` |

O complemento QA acrescenta `P1-01` para `ACCEPT` diante de concessão ativa,
replay e conflito de `WITHDRAW`, o caso de calendário iniciado em 29 de
fevereiro, rejeições de hold por tenant/operação, receipt de `WITHDRAW` e
escopo `READ` do administrador no mesmo tenant.

## Verificação

Comando focal executado em ambiente local, com Python 3.12.3, plugins externos
desabilitados e o ambiente virtual já disponível no workspace:

```text
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 backend/.venv/bin/python -m pytest -q tests/test_e4b_consent_domain.py
..........................                                               [100%]
26 passed
```

`PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile` também compilou os dois
arquivos Python sem erro. `git diff --check` passou. O estado final permanece
limitado aos três caminhos autorizados e a worktree segue sem commit:

```text
## feat/e4b-domain-c0-luna-v1
?? backend/app/domain/e4b_consent.py
?? backend/tests/test_e4b_consent_domain.py
?? docs/ops/e4-implementation/luna-e4b-c0.md
```

Âncora de conteúdo atual, calculada nesta ordem, é a soma SHA-256 de
`path_utf8 || NUL || conteúdo || NUL` para
`backend/app/domain/e4b_consent.py`, seguida de
`backend/tests/test_e4b_consent_domain.py`:
`71aeb1838fb9f2eee5ad2f20a0ab62cb48f23e952af7ce713bac571e1978031c`.

O algoritmo inclui o caminho relativo codificado em UTF-8, um byte zero, os
bytes exatos do arquivo e outro byte zero para cada arquivo. Não há hash de
diff, commit ou publicação. A nota é o registro operacional correspondente;
esta evidência é local e não representa estado de ambiente compartilhado.

## Limites e rollback

Não há store, schema, migration, SQL, aplicação de banco, ACL/RLS, caller,
router, runtime, flag, credencial, rede, publicação, commit ou push nesta
entrega. Não há descarte automático de registros elegíveis, nem capability de
hold criada pelo domínio. O rollback de C0 é remover o patch desta worktree;
nenhum dado persistido é alterado.

## Evidência coletada

A verificação foi feita contra o SHA base informado acima, em ambiente local,
em 2026-09-09. A nota não atesta qualquer ambiente compartilhado ou produção.
