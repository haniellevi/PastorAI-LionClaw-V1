# PastorAI / Igreja 12: registro central de missões pós-V1

Atualizado em 2026-08-24 (America/Sao_Paulo) após o deploy da PR #284 e o
preflight operacional somente leitura do Asaas. A V1 permanece
`V1_ENCERRADA`; este documento não altera a tag `v1.0.0`, não autoriza
integrações externas e não abre gates de produção.

## Baseline obrigatório

- código do backend em produção: `1e89e5867f535b47aaec813f5742298ca97e13c0`;
- frontend Vercel `pastorai-frontend-prod`: deployment
  `dpl_B1moarLm6raSzQU3DqMf33RvKiCo`, `READY`, target `production`, SHA
  `1e89e5867f535b47aaec813f5742298ca97e13c0`;
- Supabase PROD: `pffafnchtxbimpwyaczq`, estado `ACTIVE_HEALTHY`;
- Clerk: instância PROD confirmada por prefixos `sk_live_` e `pk_live_`, issuer
  `https://clerk.igreja12.com.br` e JWKS
  `https://clerk.igreja12.com.br/.well-known/jwks.json`;
- flags externas no backend, queue worker, cron worker e broadcast worker:
  `ALLOW_REAL_SENDS=false`, `ASAAS_BILLING_ENABLED=false`,
  `BREVO_SEND_MODE=off` e `BROADCAST_ASYNC_ENABLED=false`;
- fonte de verdade do código: `origin/main` em
  `ee3c24d8095df6f84439492a6eacccc212d1507c`; produção ainda serve o SHA
  informado para cada camada acima.

## Missões

1. **PR #257: fluxo da Central de Células.**
   - Estado: **MERGED** em `bae285b...` (squash merge a partir do HEAD
     `b969c9a1de170d9c48e0729a9f867e2c95bb9232`).
   - Evidência: 5/5 checks do GitHub Actions verdes; validações locais com 793
     testes, typecheck, lint, build e cinco E2E; a aba "Hoje" exibe a fila de
     exceções prioritárias sem duplicar multiplicações.

2. **Células: transferência e remoção de membros.**
   - Estado: **CONCLUÍDA E DEPLOYADA EM PROD**.
   - Evidência: as rotas `/cells/{cell_id}/membros/transferir` e
     `/cells/{cell_id}/membros/remover` estão ativas; o fluxo foi exercitado em
     produção com dados sintéticos, preservando a pessoa, sem vínculos
     duplicados e com eventos append-only em `celula_membro_evento`.
   - Validação automatizada: 33 testes de backend e 12 testes de frontend
     focados, além do typecheck. O smoke visual completo por perfil permanece
     como evidência operacional residual, sem reabrir a implementação direta.

3. **Clerk Production.**
   - Estado: **CONCLUÍDA E DEPLOYADA EM PROD**.
   - Evidência: prefixos e issuer/JWKS de produção confirmados sem expor chaves;
     o frontend usa a autenticação própria do PastorAI e não carrega
     `@clerk/nextjs` nem chave `pk_` em seus chunks.
   - Resíduo: a PR #280 corrigiu ativação e recuperação em links rastreados e
     foi incorporada ao baseline atual. Smokes autenticados por perfil e
     cross-tenant devem continuar compondo o checklist de regressão de cada
     release.

4. **Asaas real.**
   - Estado: **BLOCKED / CODE READY, OPERAÇÃO NOT_READY**.
   - Código: a PR #284 endureceu os gates antes da rede e diferenciou bloqueio
     local de falha remota ambígua. O backend completo passou com 2.582 testes
     e 239 skips antes do merge; o SHA está implantado nos quatro processos de
     aplicação.
   - Preflight operacional de 2026-08-24: concluído somente leitura, sem
     cobrança, migration, canário ou alteração de flags. Ver a seção dedicada
     abaixo.
   - Decisão operacional: a conta Asaas atual será a conta oficial
     compartilhada. Somente recursos com `externalReference` no namespace
     reservado `pastorai-` pertencem à integração; os recursos existentes sem
     esse marcador são externos ou legados e permanecem intocados.
   - Hardening candidato: propriedade revalidada antes de cada mutação, buscas
     conciliatórias paginadas, claim durável para restore, ledger de IDs de
     webhook, unicidade dos IDs remotos e sinal de readiness para operações
     presas. A migration é aditiva e não faz backfill nem adota legado.
   - Pré-requisitos ainda abertos: merge, migration e deploy do hardening com
     os gates fechados; verificação pós-deploy; inventário imediatamente antes
     do canário; autorização nominal no momento de abrir simultaneamente
     `ALLOW_REAL_SENDS` e `ASAAS_BILLING_ENABLED`.
   - Pilotos: o plano gratuito `piloto_full` é atribuído somente pelo painel
     master. A igreja Filadélfia de Corrente está nessa cortesia; nenhuma
     cobrança Asaas deve ser criada enquanto permanecer nesse plano.

5. **Broadcast assíncrono e envios Evolution.**
   - Estado: **FECHADO**.
   - Pré-requisito: Evolution saudável, heartbeat do worker, destinatário único
     autorizado, observabilidade e rollback antes de abrir os dois gates.

6. **Brevo live.**
   - Estado: **FECHADO** (`BREVO_SEND_MODE=off`).
   - Pré-requisito: domínio/remetente, monitoramento, novo canário autorizado e
     promoção separada para `live`, recriando todos os consumidores da flag.

7. **Dívida de performance do Supabase.**
   - Estado: **BACKLOG MEDIDO, SEM MUDANÇA DE SCHEMA NESTA MISSÃO**.
   - Pré-requisito: medir consultas e crescimento real antes de criar ou
     remover índices. O `WARN` de `current_igreja_id()` permanece aceito
     enquanto necessário às policies RLS.

## Fechamento da ativação pós-deploy de Células

- frontend e backend servem o baseline atual
  `1e89e5867f535b47aaec813f5742298ca97e13c0`;
- `NEXT_PUBLIC_API_URL` aponta para `https://api.igreja12.com.br`; o deployment
  de produção não contém `localhost:8000`;
- Clerk PROD está comprovado no backend; nenhuma chave foi impressa;
- os artefatos sensíveis `clerk_*_prod.*`, `migrate_clerk_production.py` e
  `target_users*.json` não estão no worktree e permanecem excluídos localmente;
- nenhuma migration foi aplicada para a ativação dos fluxos diretos.

## Preflight operacional Asaas (2026-08-24)

### Inventário local, Supabase PROD

- três igrejas no total: duas ativas e uma suspensa;
- uma linha em `subscriptions`, sem `asaas_customer_id` e sem
  `asaas_subscription_id`;
- zero linhas em `billing_payment_operations`,
  `billing_subscription_operations` e `billing_plan_change_operations`;
- zero operações abertas ou presas há mais de uma hora e zero notificações de
  upgrade pendentes;
- zero divergências entre plano de igreja e assinatura e zero divergências na
  contagem faturável;
- não existe índice único no schema aplicado para
  `subscriptions.asaas_subscription_id`. Esse endurecimento exige migration
  futura e autorização separada.

### Inventário remoto, Asaas produção

Consulta paginada exclusivamente por `GET` em `api.asaas.com`, sem imprimir
IDs, nomes, documentos, e-mails, telefones ou chave de API:

- 15 clientes, um deles com `externalReference`;
- duas assinaturas `ACTIVE`, ambas sem `externalReference`;
- 232 cobranças: 223 `RECEIVED` e nove `PENDING`;
- oito cobranças com `externalReference`, nenhuma com prefixo `pastorai-`;
- 35 cobranças ligadas às duas assinaturas listadas;
- zero correspondências entre recursos remotos e IDs Asaas locais;
- zero correspondências dos clientes das assinaturas ativas com e-mails ou
  telefones existentes no PastorAI PROD;
- as assinaturas ativas foram criadas entre 2024-04-29 e 2026-04-08 e possuem
  próximas cobranças entre 2026-10-06 e 2026-10-09.

Conclusão: os recursos existentes devem ser tratados como externos ou legados
até identificação humana. Nenhum deles pode ser adotado, alterado, cancelado ou
usado em canário por inferência.

### Backup, restauração e monitoramento

- backup lógico diário concluído em `2026-08-24T06:15:54Z`, com 23.877.499
  bytes; arquivo presente, tamanho coincidente e SHA-256 recalculado com
  resultado idêntico ao manifesto;
- pacote com 26 entradas, incluindo dump Supabase/PostgreSQL 17, dump
  Evolution/PostgreSQL 16, volume Redis e checksums internos;
- cron legado ativo diariamente às 06:15 UTC; o timer de backup permanece
  intencionalmente desabilitado para impedir agendamento duplicado;
- monitor de produção habilitado e ativo, com última execução bem-sucedida em
  `2026-08-24T14:33:50Z`;
- Hostinger mantém dois backups semanais: 8,35 GB de 2026-08-19 e 8,64 GB de
  2026-08-12;
- último teste de restauração isolada em 2026-08-07: Supabase com 53 tabelas,
  11 funções e nove gatilhos; Evolution com 105 tabelas e 5.372 linhas
  estimadas; pacote externo com 28 entradas verificado. A cadência mensal ainda
  está dentro do prazo.

### Riscos residuais e próximo gate

- a conta Asaas contém duas assinaturas ativas não pertencentes ao inventário
  local conhecido;
- o hardening formal ainda precisa ser mergeado, migrado e implantado antes de
  qualquer teste financeiro;
- o novo sinal `billing_operations=stale` depende da migration e do release
  correspondentes para entrar no monitoramento de produção;
- a cópia semanal da Hostinger e o backup diário local estão saudáveis, mas o
  teste mensal de restauração deve ser repetido até 2026-09-07.

**Próximo gate único:** merge, migration e deploy do hardening formal com todas
as flags financeiras fechadas. O canário financeiro continua proibido até uma
confirmação humana específica no momento da ação.

## Paralelismo seguro

Auditorias somente leitura podem ocorrer em sessões separadas. Migrations,
mudanças de identidade, flags, canários, deploys e merges permanecem seriais e
exigem preflight vivo no momento da ação.
