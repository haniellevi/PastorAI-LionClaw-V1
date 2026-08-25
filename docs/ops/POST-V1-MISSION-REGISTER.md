# PastorAI / Igreja 12: registro central de missões pós-V1

Atualizado em 2026-08-24 (America/Sao_Paulo) após o deploy da PR #287, a
verificação pós-deploy do isolamento formal do Asaas, o canário financeiro
fim a fim no Asaas Sandbox e o preflight sem envios da Missão 5. A V1 permanece
`V1_ENCERRADA`; este documento não altera a tag `v1.0.0`, não autoriza
integrações externas e não abre gates de produção.

## Baseline obrigatório

- código do backend em produção: `e8b06d0afa167790b068e262be10669b21d28e08`;
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
- fonte de verdade do código: `origin/main`; produção serve o SHA imutável
  informado para cada camada acima. Commits exclusivamente documentais em
  `main` não alteram os artefatos implantados.

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
   - Estado: **HARDENING DEPLOYED / OPERAÇÃO NOT_READY / GATES FECHADOS**.
   - Código: a PR #284 endureceu os gates antes da rede e diferenciou bloqueio
     local de falha remota ambígua. A PR #287 acrescentou isolamento formal na
     conta compartilhada, propriedade revalidada, conciliação paginada, claim
     durável para restore, ledger de webhook, unicidade de IDs remotos e sinal
     de readiness. O SHA da PR #287 está implantado nos quatro processos de
     aplicação.
   - Preflight operacional de 2026-08-24: concluído somente leitura, sem
     cobrança, migration, canário ou alteração de flags. Ver a seção dedicada
     abaixo.
   - Canário Sandbox de 2026-08-24: **PASS** no código implantado, com
     assinatura recorrente, setup, confirmação, webhook autenticado, replay
     idempotente e limpeza. Não houve efeito financeiro real nem alteração em
     produção.
   - Decisão operacional: a conta Asaas atual será a conta oficial
     compartilhada. Somente recursos com `externalReference` no namespace
     reservado `pastorai-` pertencem à integração; os recursos existentes sem
     esse marcador são externos ou legados e permanecem intocados.
   - Migration aditiva aplicada em Supabase PROD como versão
     `20260824202348`, nome `asaas_formal_isolation_20260824`; não houve
     backfill nem adoção de legado.
   - Pré-requisitos ainda abertos para produção: novo inventário imediatamente
     antes do canário real e autorização nominal no momento de abrir
     simultaneamente `ALLOW_REAL_SENDS` e `ASAAS_BILLING_ENABLED` para um único
     teste financeiro controlado.
   - Pilotos: o plano gratuito `piloto_full` é atribuído somente pelo painel
     master. A igreja Filadélfia de Corrente está nessa cortesia; nenhuma
     cobrança Asaas deve ser criada enquanto permanecer nesse plano.

5. **Broadcast assíncrono e envios Evolution.**
   - Estado: **PREFLIGHT PASS / CANÁRIO PENDENTE / GATES FECHADOS**.
   - Evidência: migration, RLS e deduplicação aplicadas; Evolution e worker
     saudáveis; ledger sem execução aberta, lease vencida ou retry pendente;
     131 testes focados aprovados; interface autenticada confirma que os envios
     permanecem desativados.
   - Pré-requisito restante: destinatário único autorizado e mensagem exata do
     canário, com autorização humana no momento de abrir os dois gates.

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

- frontend serve `1e89e5867f535b47aaec813f5742298ca97e13c0` e backend
  serve `e8b06d0afa167790b068e262be10669b21d28e08`;
- `NEXT_PUBLIC_API_URL` aponta para `https://api.igreja12.com.br`; o deployment
  de produção não contém `localhost:8000`;
- Clerk PROD está comprovado no backend; nenhuma chave foi impressa;
- os artefatos sensíveis `clerk_*_prod.*`, `migrate_clerk_production.py` e
  `target_users*.json` não estão no worktree e permanecem excluídos localmente;
- nenhuma migration foi aplicada para a ativação dos fluxos diretos.

## Ativação técnica do isolamento Asaas (2026-08-24)

### Inventário local, Supabase PROD

- três igrejas no total: duas ativas e uma suspensa;
- uma linha em `subscriptions`, sem IDs Asaas e sem referências externas;
- zero linhas em `billing_payment_operations`,
  `billing_subscription_operations` e `billing_plan_change_operations`;
- zero linhas em `asaas_webhook_receipts`;
- zero operações abertas ou presas há mais de uma hora e zero notificações de
  upgrade pendentes;
- zero divergências entre plano de igreja e assinatura e zero divergências na
  contagem faturável;
- os índices únicos parciais de IDs Asaas e referências `pastorai-`, os
  índices de operações abertas e a proteção RLS do ledger de webhook estão
  aplicados;
- zero recursos legados adotados pela migration ou pelo deploy.

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

O inventário agregado foi repetido após o deploy e permaneceu em 15 clientes,
duas assinaturas `ACTIVE`, 232 cobranças e zero `externalReference` com prefixo
`pastorai-`. Nenhum `POST`, `PUT` ou `DELETE` foi enviado ao Asaas.

### Deploy e verificação pós-deploy

- backend, queue worker, cron worker e broadcast worker executam a mesma imagem
  do SHA `e8b06d0afa167790b068e262be10669b21d28e08`;
- os quatro processos estão saudáveis, sem reinícios e sem marcadores de erro
  nos primeiros vinte minutos;
- `/health` e `/ready` locais e públicos responderam com sucesso;
  `billing_operations=ok`, banco, Redis, Evolution e workers estão saudáveis;
- CORS respondeu corretamente para `app.`, `admin.` e
  `painel.igreja12.com.br`; as portas públicas 8000 e 8080 permanecem
  fechadas;
- `ALLOW_REAL_SENDS=false`, `ASAAS_BILLING_ENABLED=false`,
  `BREVO_SEND_MODE=off` e `BROADCAST_ASYNC_ENABLED=false` foram confirmados
  após o restart nos quatro processos;
- o monitor `pastorai-monitor.timer` permanece ativo; o timer de backup segue
  intencionalmente desabilitado porque o cron legado executa o backup diário;
- arquivos de transferência da VPS foram excluídos após a ativação do release;
- a chave SSH temporária `pastorai-deploy-20260824` foi removida da Hostinger e
  a chave privada local foi excluída após as verificações.

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

### Canário financeiro Asaas Sandbox (2026-08-24)

- executado com a imagem construída do SHA exato de produção
  `e8b06d0afa167790b068e262be10669b21d28e08`, em PostgreSQL e Redis
  descartáveis, sem conexão com Supabase PROD;
- somente o ambiente local do canário usou `ALLOW_REAL_SENDS=true` e
  `ASAAS_BILLING_ENABLED=true`, apontando para
  `https://api-sandbox.asaas.com/v3`; as flags de produção permaneceram
  fechadas;
- utilizados igreja, usuário, e-mail e documento de teste sintéticos; foram
  criadas uma mensalidade de R$ 5,00 e uma taxa de setup de R$ 5,00;
- o inventário remoto confirmou exatamente um customer, uma assinatura, uma
  cobrança de setup e uma cobrança mensal correspondentes ao canário;
- quatro eventos autenticados foram recebidos pelo endpoint temporário; a
  assinatura local ficou `ativa`, o setup ficou pago e as operações duráveis
  permaneceram em exatamente uma criação de assinatura e uma criação de
  pagamento;
- o replay de um evento preservou integralmente o snapshot e a quantidade de
  recibos, comprovando a idempotência do ledger `asaas_webhook_receipts`;
- o webhook temporário, a assinatura e o customer sintéticos foram removidos;
  as referências listáveis ficaram zeradas. O Asaas preservou dois registros
  de pagamentos confirmados do Sandbox como histórico do provedor;
- o webhook antigo `PastorAI DEV`, já desativado, interrompido e apontando para
  um domínio ngrok expirado, também foi removido. O túnel HTTPS, os quatro
  contêineres, a rede e a imagem local descartável foram encerrados e removidos;
- a chave `Sandbox Temporaria` foi revogada no painel após a confirmação por
  Token SMS; o arquivo local de credencial e todo o diretório temporário do
  canário foram excluídos definitivamente.

### Riscos residuais e próximo gate

- a conta Asaas contém duas assinaturas ativas não pertencentes ao inventário
  local conhecido;
- o hardening formal está mergeado, migrado, implantado e validado no Sandbox,
  mas ainda não foi exercitado por um canário financeiro na conta oficial;
- a cópia semanal da Hostinger e o backup diário local estão saudáveis, mas o
  teste mensal de restauração deve ser repetido até 2026-09-07.

O canário financeiro real foi adiado pelo operador. `ALLOW_REAL_SENDS` e
`ASAAS_BILLING_ENABLED` permanecem fechados até uma autorização futura e
específica.

## Preflight da Missão 5: broadcast assíncrono e Evolution (2026-08-24)

- código auditado no `origin/main` `28cedaf0b9ab06a0b7c0e271a9fcc1eaa4208f29`;
  o backend em produção serve o mesmo código de broadcast no SHA
  `e8b06d0afa167790b068e262be10669b21d28e08`, pois os commits posteriores são
  exclusivamente documentais;
- 131 testes focados de domínio, API assíncrona, delivery, worker, Evolution,
  heartbeat e readiness aprovados, sem falhas;
- migration `broadcast_delivery_20260805` aplicada em Supabase PROD como versão
  `20260805172749`;
- RLS ativa nas três tabelas de broadcast, uma policy por tabela, constraints de
  status e telefone e índices únicos de idempotência e pessoa aplicados;
- produção contém cinco broadcasts históricos, todos com `status=enviado`;
  quatro execuções históricas, todas finalizadas; duas entregas `aceito` e duas
  `falhou_permanente`, criadas em 2026-08-07 e 2026-08-08;
- zero execução aberta, zero lease vencida e zero retry pendente. O histórico
  anterior permanece imutável e não será reutilizado no canário;
- uma conexão oficial Evolution está `online`; `/health` respondeu `ok` e
  `/ready` respondeu `ready`, com banco, Redis, Evolution, queue worker, cron
  worker e broadcast worker saudáveis;
- a interface autenticada de Comunicação recebeu da API o motivo
  `envios_externos_desabilitados` e exibiu o bloqueio de produção, comprovando
  `ALLOW_REAL_SENDS=false` sem expor configuração sensível;
- o rollback específico fecha primeiro `BROADCAST_ASYNC_ENABLED`, recria os
  quatro processos consumidores e preserva o ledger. Resultados
  `desconhecido` nunca são reenviados automaticamente.

**Próximo gate único:** fornecer um único número autorizado e a mensagem exata
do canário WhatsApp, seguido de autorização humana no momento de abrir
temporariamente `ALLOW_REAL_SENDS` e `BROADCAST_ASYNC_ENABLED`. As flags seguem
fechadas até essa confirmação.

## Fundação do agente Evolution (2026-08-25)

- decisão arquitetural: Evolution é o único transporte do agente nesta fase;
  Hermes e BotConversa permanecem fora do caminho;
- identidade: tenant deriva da instância, telefone é normalizado e somente
  Pessoas ativas participam da resolução; duplicidade ativa falha fechada,
  segue retry/dead-letter e não executa agente ou ferramenta;
- autorização: papéis vêm de um único AppUser ativo vinculado à Pessoa e ao
  Clerk; cada ferramenta reproduz os papéis do endpoint humano, ferramentas
  desconhecidas falham fechadas e `marcar_presenca` permanece desabilitada;
- efeitos: as ferramentas atuais só podem alterar a própria Pessoa reconhecida;
  relatório agregado não registra decisão contra o remetente;
- comportamento: configuração ausente ou inativa impede resposta automática;
  apenas onboarding pode receber refino de linguagem, sem texto bruto do
  usuário no prompt do LLM;
- consentimento: opt-out explícito é persistido antes de credencial,
  configuração e handoff, com padrões contextuais para evitar confundir ações
  administrativas comuns;
- validação local: 2.627 testes backend fora de RLS e 239 testes RLS em
  PostgreSQL descartável passaram, sem falhas; revisão independente resultou
  em `GO`;
- nenhuma migration, deploy, conexão Evolution, envio externo ou mudança de
  flag foi realizada. `ALLOW_REAL_SENDS` e a configuração do agente continuam
  fechadas.

**Próximo gate único:** revisar e integrar o commit da fundação; configurar o
comportamento e a credencial da igreja piloto continuará em missão separada,
com `AgentConfig.ativo=false` até novo canário autorizado.

## Paralelismo seguro

Auditorias somente leitura podem ocorrer em sessões separadas. Migrations,
mudanças de identidade, flags, canários, deploys e merges permanecem seriais e
exigem preflight vivo no momento da ação.
