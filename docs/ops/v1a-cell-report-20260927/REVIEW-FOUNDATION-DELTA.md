# Revisão delta V1a, fundação SQL e contratos

Data: 27/09/2026

## Escopo e integridade

Revisão limitada ao fechamento de dois achados anteriores e à prova RLS de escrita do worker. Não cobre o fluxo V1a completo, transporte, lembretes, extração, orçamento ou ativação.

- `agent_action_proposals.py`: `b742fe05473637e3342bf19609fee89fb6d4b03a522b23d8d8aba867bca64d28`, conferido.
- `cell_report_whatsapp.py`: `4e1ff01686030d34171b5770689bad1a7fda8f98fdffbfe591f67f0f60249773`, conferido.
- `models.py`: `37b2cb402f436d4ebd508f9d96987ce1af187b31fb40b912ea40e62daed7090e`, conferido.
- Migration permanece `d76ab1c6096d2c33781c5cd03a978c5a1cdd524c2a4bdc344b08c73df8abda50`, conferida.
- Os hashes recebidos dos testes de proposta e LGPD também coincidem com a árvore revisada.

## Fechamento dos achados

### Recibo por ação, fechado

`ActionEffect` aceita somente os dois recibos permitidos. `_new_receipt` deriva o texto esperado da ação persistida e rejeita a combinação cruzada antes de criar o recibo. A ação `enviar_relatorio_celula` exige `Relatório confirmado.`; as duas ações S3 anteriores exigem `Registro confirmado.`. O resolvedor continua sem commit nem transporte, portanto a validação fica dentro da mesma unidade transacional do efeito e do recibo.

Há cobertura positiva do fluxo V1a que confirma a persistência e o envio posterior de `Relatório confirmado.`. Seria útil manter também um teste unitário negativo para cada combinação cruzada, mas a implementação atual fecha o contrato e não encontrei P1 ou P2 neste ponto.

### Empate de consentimento, fechado conservadoramente

`current_v1a_lgpd_acceptance` agora exige exatamente um registro terminal antes de aceitar a versão vigente. O teste cobre dois `record_id` distintos com mesma versão e timestamp, que retorna `None`. A função também conserva a negação para revogação, termo divergente, timestamp ausente ou futuro e registro malformado.

O alimentador futuro da função deve continuar entregando todos os registros no timestamp terminal. Essa é uma pré-condição de integração, não uma falha na função pura revisada.

### Escrita do worker nas cinco relações privadas, coberta

A nova prova PG entra como `authenticated` com `sub` vazio antes de inserir os cinco registros encadeados. Ela demonstra `INSERT` válido em `cell_report_drafts`, `cell_report_reminder_preferences`, `cell_report_reminders`, `cell_report_ai_daily_budgets` e `cell_report_ai_reservations`, depois exerce `UPDATE` no mesmo tenant. As provas já existentes mantêm painel com `sub` sem leitura ou update, negação de escrita cross-tenant e FKs compostas contra reunião de outro tenant.

A evidência informada pelo root, 16 casos PG17 sem skip, é coerente com a parametrização visível. Não executei banco nesta revisão.

## Veredito

**APTO no recorte do delta.** Os dois achados e a lacuna SQL apontados na revisão anterior estão fechados no snapshot estável. Este veredito não aprova o fluxo completo nem qualquer gate de ativação V1a.
