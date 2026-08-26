# Retenção de artefatos de recuperação

Este runbook governa tabelas temporárias criadas durante intervenções manuais de
produção. Ele não autoriza leitura de conteúdo, restauração, exclusão nem mudança
em produção. Cada uma dessas ações exige um gate humano específico.

## Inventário controlado

| Artefato | Finalidade | Acesso esperado | Revisar a partir de |
|---|---|---|---|
| `public._clerk_migration_rollback_20260823_032220` | Reverter o vínculo de identidades da migração Clerk de 2026-08-23 | Proprietário e `service_role`; `anon` e `authenticated` sem privilégios e sob policy restritiva | 2026-11-21 |
| `recovery.encrypted_credentials_backup_20260805` | Preservar o estado cifrado anterior à intervenção de 2026-08-05 | Somente o proprietário `postgres`; schema privado e policy restritiva | 2026-11-03 |

A migration
`backend/migrations/20260826_094317_harden_recovery_artifacts_retention.sql`
é forward-only, opcional por ambiente e não remove nem move esses objetos. Ela
preserva a quantidade de linhas, adiciona comentários operacionais, habilita RLS,
cria a policy restritiva `recovery_artifact_deny_all` e aplica o princípio do
menor privilégio.

SHA-256 da migration revisada:
`a6fa9abccbfec240ceb460d52f5bcbbda677c18691230d0e0c4f047fdd603fb0`.

## Regra de retenção

As datas do inventário abrem uma revisão. Elas não disparam exclusão automática.
Um artefato só pode ser removido quando todos os itens abaixo estiverem
documentados na mesma missão:

1. O responsável funcional confirma que a janela de rollback encerrou.
2. Existe backup recente e uma restauração descartável foi concluída com sucesso.
3. Nenhuma função, trigger, constraint, view, rotina operacional ou script de
   recuperação depende do objeto.
4. A contagem e o checksum estrutural foram registrados sem consultar conteúdo
   pessoal ou credenciais.
5. A exclusão possui autorização humana nominal e migration forward-only própria.

Se qualquer item falhar ou ficar inconclusivo, o artefato permanece retido e a
revisão recebe uma nova data. Nunca colocar `DROP TABLE` em job, cron ou rotina de
limpeza automática para esses objetos.

## Auditoria sem conteúdo

A revisão periódica deve consultar somente catálogo, ACL, RLS, contagens e
dependências. Não selecionar e não imprimir colunas de identidade, e-mail,
credenciais ou payload.

Critérios mínimos:

- nenhuma tabela em schema exposto com RLS desabilitada;
- nenhuma tabela pública sem policy, salvo exceção documentada e fail-closed;
- nenhum privilégio efetivo de `anon` ou `authenticated` nos artefatos fechados;
- nenhuma permissão de `USAGE` ou `CREATE` para papéis de aplicação no schema
  `recovery`;
- nenhuma mudança no `service_role` do rollback Clerk sem revisão do roteiro de
  recuperação;
- advisors de segurança do Supabase sem achado novo de severidade superior.

## Próxima revisão

Na data aplicável, executar somente o preflight read-only. Se ele concluir que o
artefato pode ser descartado, preparar uma PR separada com a exclusão e o teste de
restauração. A aplicação dessa PR em produção continua sendo outro gate.
