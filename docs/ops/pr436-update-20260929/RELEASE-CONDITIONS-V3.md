# PR436: condições posteriores ao GO de merge

Fonte: parecer Sarah source-only no head `82f06d36220749a1c181494109d0ed2ce3d04491`, 2026-09-29, via Conselheiro Claude. GO somente para merge, P0=0, P1=0, P2=7. Nenhum item abaixo foi executado nesta missão; não há autorização de banco, PROD, deploy, envio ou ativação.

Atualização posterior: o P2-1 foi corrigido e integrado pela PR #438, merge commit `9697c9c6d34ff72eb30830cc4879c9f730a7c2f6`. A frase histórica abaixo registra o gate que existia no parecer da #436; ele não permanece pendente. A PR #436 também foi integrada em `0c2c91fdaec9fb1901a116594bc67fd28d6d6673`. Os sete P2 V3 abaixo continuam condicionantes da release conforme cada item.

Antes de qualquer migration em PROD, permanecia obrigatória a PR pequena P2-1 anterior: em `consolidation_workflow.py:136-141`, assumir fonovisita arrastava `conectar_celula` para `lider_celula` sem permissão; faltava teste com os dois tipos na mesma trilha. Esse gate foi fechado pela PR #438, sem operação de banco ou PROD.

Os sete P2 desta revisão V3 ficam registrados para a preparação da release:

1. Cron V3 sem retorno antecipado pelo gate em `notification_outbox.py:2998-3028`.
2. `conversations.py:225` emite WARN para todo `@g.us`/broadcast; avaliar volume e nível sem registrar identificadores.
3. Inventário LID no runbook V3, linhas 63-71/77, não inclui `p.sem_interesse` nem `c.assumido_por`; conferir também `assumido_em` ao preservar o atendimento humano.
4. Regex de 14-15 dígitos é triagem incompleta: considerar `length >= 13` e formatos não brasileiros, sem assumir que ausência de linhas prova ausência de LID.
5. Correspondência LID para telefone canônico ainda não tem método seguro prescrito; exigir prova privada e verificável para cada candidata antes de reconciliar.
6. Reconciliação de identidade implica DML em PROD, hoje descrito só em prosa. Exigir SQL versionado, revisão própria e verificação pós-operação **antes de qualquer autorização de banco**.
7. STOP do inventário está em prosa. Torná-lo executável e testado antes da janela de release.

O runbook V3 já exige migration antes de backend/workers, inventário read-only privado, decisão humana de reconciliação e preflight de schema antes do restart. A execução desses passos, a autorização de banco e a ativação permanecem gates separados. Este arquivo é apenas o registro versionado das condições, não autoriza execução.
