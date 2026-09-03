# PastorAI / Igreja 12: registro central de missões pós-V1

Atualizado em 2026-09-03 (America/Sao_Paulo) com D2B2a, D2B2b1, D2B2b3A, o
`bootstrap-ledger` integrados e inativos, as entregas M1A-M1E e M1I do catálogo
integradas pela PR #361 e a reconciliação M1J-R5 encerrada pela PR #363
(merge `c2fb16ad`). A D2B2b3A existe
somente como superfície draft-only do Console Master. A V1 permanece `V1_ENCERRADA`, mas a visão
integral WhatsApp-first ainda não está concluída. Este documento não altera a tag
`v1.0.0`, não autoriza novo canário, rollout amplo ou abertura de gates de
produção.

## Baseline obrigatório

- último SHA do backend em produção preservado em evidência versionada anterior:
  `c525d6a3897a12c6c287f9fc79a88b32b34cd452`. O relato operacional do canário
  ativo não contém um artefato versionado que permita reconstituir o SHA exato
  servido durante a janela; ele deve ser revalidado antes de qualquer rollout;
- frontend Vercel `pastorai-frontend-prod`: a evidência GitHub/Vercel registrada
  na integração da PR #363 correlacionou o deployment Production automático
  `6251268132` ao SHA `c2fb16ad9a6b028c317c56a0b02c4362ae903e26`, criado em
  `2026-09-03T19:29:12Z` e concluído com `state=success`. Esta prova aplica-se
  exclusivamente ao frontend Next.js e não revalida backend, banco de dados ou
  runtime. O deployment correlacionado a `8aacf98d` permanece evidência
  histórica da PR #361;
- Supabase PROD: `pffafnchtxbimpwyaczq`, último estado preservado em evidência
  versionada anterior `ACTIVE_HEALTHY`, não revalidado nesta atualização;
- Clerk: instância PROD preservada em evidência versionada anterior por
  prefixos `sk_live_` e `pk_live_`, não revalidada nesta atualização, issuer
  `https://clerk.igreja12.com.br` e JWKS
  `https://clerk.igreja12.com.br/.well-known/jwks.json`;
- ao final do canário, no último registro operacional/histórico preservado, o operador confirmou `AgentConfig.ativo=false` e as
  flags externas restauradas para `ALLOW_REAL_SENDS=false`,
  `ASAAS_BILLING_ENABLED=false`, `BREVO_SEND_MODE=off` e
  `BROADCAST_ASYNC_ENABLED=false`. Este é um relato operacional preservado, não
  uma leitura atual de produção feita por esta atualização documental;
- baseline do preflight PROD anterior, preservada como evidência histórica:
  `15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`. Esse SHA não é tratado como
  ponteiro móvel de `origin/main`. A implementação D2B2b3A veio do merge #320
  `947d891c2ea278b7a3231fecd9ca1c90cfe29a1f`; merge em `main` não comprova
  backend ou banco, por isso o estado versionado e o estado operacional são
  registrados separadamente;
- baseline histórico da PR #323, preservada como evidência histórica de
  reconciliação anterior: `3a5789c784017ab15a43e28c4270d25af8618359`, merge da
  PR #323;
- base histórica da reconciliação M1J-R5:
  `8aacf98d9abbfd945226afb652ef38efa2fc6cfa`, merge da PR #361;
- snapshot versionado desta reconciliação e referência observada de
  `origin/main`: `c2fb16ad9a6b028c317c56a0b02c4362ae903e26`, merge da PR
  #363. Ele prova o código integrado e as evidências de CI associadas, sem
  provar bootstrap, migration, backend implantado, banco ou runtime
  compartilhado.

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

### Riscos residuais e gate financeiro adiado

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

**Gate histórico de broadcast, não atual:** fornecer um único número autorizado
e a mensagem exata do canário WhatsApp, seguido de autorização humana no
momento de abrir temporariamente `ALLOW_REAL_SENDS` e
`BROADCAST_ASYNC_ENABLED`. Esse gate permanece adiado, as flags seguem fechadas
e ele não pode ser executado a partir deste registro.

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

O commit da fundação foi integrado pela PR #294. O `origin/main` resultante é
`7a0f55ea1414d58020f426fe8d66d3dc97563e37`; os cinco workflows da PR e os cinco
workflows posteriores ao merge passaram.

## Preparação do canário do agente da Filadélfia (2026-08-25)

- o preflight identificou uma única configuração de agente em Supabase PROD,
  pertencente à Igreja Batista Filadélfia Internacional de Corrente;
- a configuração estava com `ativo=true`, em desacordo com o gate desta missão.
  A contenção mínima alterou somente `AgentConfig.ativo` para `false`; uma
  consulta separada confirmou que nenhuma igreja permanece com agente ativo;
- a BYO existente permaneceu ativa, com provedor `openai` e modelo
  `gpt-5.6-luna`. Nenhum segredo ou ciphertext foi selecionado, exibido ou
  alterado;
- o comportamento estritamente estilístico do runbook foi salvo pelo console
  master com `AgentConfig.ativo=false`. Uma nova leitura da API e o painel da
  própria igreja confirmaram nome, tom, comportamento e status `Desativado`;
- a auditoria do console registrou `agente_editar`, alvo Filadélfia e
  `ativo:false` em 2026-08-25, corrigindo a ausência de trilha da contenção
  direta inicial;
- a PR #296 acrescentou à tela `Revalidar credencial`, usando somente
  `PUT /agent/model` com o modelo já salvo e sem reenviar a chave;
- o preflight anterior ao deploy comprovou que
  `/opt/pastorai-current` aponta para o release
  `e8b06d0afa167790b068e262be10669b21d28e08`;
- backend, queue worker, cron worker e broadcast worker anteriores estavam
  saudáveis e usavam a mesma imagem `pastorai-backend:latest`, ID
  `c9133e194e39`;
- `/health` respondeu `ok` e `/ready` respondeu `ready`, com banco, Redis,
  Evolution, operações de billing e os três workers em estado `ok`;
- a leitura efetiva dentro do contêiner backend confirmou
  `ALLOW_REAL_SENDS=false`, `ASAAS_BILLING_ENABLED=false`,
  `BREVO_SEND_MODE=off` e `BROADCAST_ASYNC_ENABLED=false`;
- a BYO do PastorAI continua no único provedor suportado pelo produto nesta
  versão, sem ampliar o escopo do primeiro canário;
- o runbook `docs/ops/EVOLUTION-AGENT-CANARY-RUNBOOK.md` define comportamento,
  preflight, roteiro sintético, critérios de aborto, evidências e rollback;
- validação local da branch: 2.627 testes backend passaram e 239 foram pulados
  por dependerem da infraestrutura RLS separada; 819 testes frontend, lint,
  typecheck e build de produção passaram no Node 24.19.0;
- a PR #296 foi integrada no commit
  `cba0fdf9c6eb815e15fa5a1502499c5b0d332732`. Os cinco workflows pós-merge
  passaram, o deploy Vercel terminou com sucesso e o artefato servido em
  produção contém o botão seguro de revalidação;
- a PR #297 documentou a revalidação e foi integrada no commit
  `03696efc8ff1466b8ddcfdc1b993455f98493bc3`. Os cinco workflows pós-merge e o
  status de deployment da Vercel passaram;
- a PR #299 documentou a prova da VPS e foi integrada no commit
  `d65cdd6c6b0fb1b772ef7fcd9311dfd5f889531c`. Os cinco workflows pós-merge e o
  status de deployment da Vercel passaram;
- a BYO foi revalidada em produção como `openai` e `gpt-5.6-luna`, mantendo o
  campo de chave vazio. A operação terminou sem erro e, após recarregar a tela,
  o painel confirmou `Credencial ativa`, modelo Luna e status do agente
  `Desativado`;
- o catálogo retornado pelo backend ainda exibiu a referência de preços de
  2026-08-08. A leitura direta no contêiner confirmou a mesma referência;
- a comparação de ancestralidade confirmou que o release ativo
  `e8b06d0afa167790b068e262be10669b21d28e08` antecede tanto a base integrada da
  PR #294, `7a0f55ea1414d58020f426fe8d66d3dc97563e37`, quanto a PR #296. Assim, o
  backend antigo não atendia ao gate do canário;
- o artefato limpo do SHA
  `d65cdd6c6b0fb1b772ef7fcd9311dfd5f889531c`, checksum SHA-256
  `4d5263705c523869f342b923b88828cd76a7d3d3cc90b9a11a41583bdd4b6b32`, foi
  extraído em um novo diretório imutável. Não havia migration nem alteração do
  Compose entre o release anterior e o candidato;
- a imagem anterior foi preservada como rollback no ID `c9133e194e39`. A nova
  imagem `pastorai-backend:latest`, ID `9cf099a1413e`, foi aplicada somente ao
  backend, queue worker, cron worker e broadcast worker, sem recriar Redis,
  Evolution ou volumes;
- `/opt/pastorai-current` aponta para
  `/opt/pastorai-releases/d65cdd6c6b0fb1b772ef7fcd9311dfd5f889531c`;
- os quatro processos usam a imagem `9cf099a1413e` e ficaram saudáveis.
  `/health` respondeu `ok` e `/ready` respondeu `ready` local e publicamente,
  com banco, Redis, Evolution, billing e os três workers em estado `ok`;
- cada um dos quatro contêineres confirmou `ALLOW_REAL_SENDS=false`,
  `ASAAS_BILLING_ENABLED=false`, `BREVO_SEND_MODE=off` e
  `BROADCAST_ASYNC_ENABLED=false`;
- o catálogo dentro do contêiner confirmou `PRICING_UPDATED_AT=2026-08-25`, e
  as portas 8000 e 8080 continuaram inacessíveis externamente;
- o console master confirmou novamente a Filadélfia com `AgentConfig.ativo=false`
  após o deploy. A chave SSH temporária foi revogada, o teste posterior negou
  acesso, e os pacotes e chaves temporários foram removidos;
- nenhuma migration, ativação do agente, mudança de flag, mensagem externa ou
  canário foi realizada nessa rodada de deploy.

### Preflight operacional e smoke inativo de 2026-08-26

- a VPS servia o release
  `c525d6a3897a12c6c287f9fc79a88b32b34cd452`; backend, queue worker, cron
  worker e broadcast worker estavam saudáveis, assim como banco, Redis e
  Evolution;
- os quatro processos confirmaram `ALLOW_REAL_SENDS=false`,
  `ASAAS_BILLING_ENABLED=false`, `BREVO_SEND_MODE=off` e
  `BROADCAST_ASYNC_ENABLED=false`;
- a instância Evolution da Filadélfia respondeu `online`, com número pareado,
  sem imprimir instância ou telefone oficial;
- havia exatamente um `AgentConfig` da Filadélfia, inativo, nenhuma igreja
  com agente ativo e uma BYO ativa e validada. Nenhum segredo ou ciphertext
  foi lido;
- fila de entrada e processamento estavam vazias. A dead-letter continha um
  item legado após cinco tentativas, sem `stage`, `error_class`,
  `first_failed_at` ou `last_failed_at`. O payload não foi lido e o item
  não foi reprocessado;
- uma chave SSH temporária identificada foi criada para o preflight, removida
  da Hostinger ao final e testada como incapaz de autenticar. A chave privada
  local foi destruída;
- o smoke inativo recebeu um único inbound controlado. A interface mostrou
  `IA pausada pela igreja`; o ledger criou um `ia_sem_resposta`, com zero
  envio de IA confirmado, zero envio legado posterior e zero estado não
  terminal;
- o número apresentado não é elegível para o primeiro canário ativo: ele está
  ligado a uma Pessoa ativa com papel privilegiado e a uma conversa operacional
  anterior. Nenhum telefone completo foi registrado neste documento;
- o runbook agora diferencia `ia_sem_resposta` de envio Evolution confirmado,
  exige número sintético novo e define quarentena atômica, sem leitura, para
  dead-letter legada;
- durante uma indisponibilidade crítica do GitHub Actions, Backend, Frontend e
  E2E passaram no `main`. Uma PR temporária em draft, sem diff final e com a
  mesma árvore de `2262fba647fd788979a5c09fde6881086c9ee41f`, confirmou os
  cinco workflows verdes. A PR foi fechada sem merge e a branch temporária
  foi removida;
- a dead-letter legada foi movida com `RENAMENX` para
  `pastorai:webhooks:dead:quarantine:20260826T165417Z:994de6119f3664c4`.
  O preflight e a validação posterior confirmaram origem vazia, destino do
  tipo `list`, comprimento `1` e ausência de TTL. O payload não foi lido,
  apagado ou reprocessado;
- a chave SSH temporária usada exclusivamente nessa contenção foi removida da
  Hostinger, teve a autenticação negada após a revogação e seus arquivos
  locais foram destruídos.

Estado em 2026-08-26: **CONTENÇÃO PASS / QUARENTENA PASS / CANÁRIO ATIVO
BLOCKED**. Esse estado histórico foi superado pela execução controlada registrada
abaixo.

### Primeiro canário ativo controlado da Filadélfia (2026-08-27)

Classificação da evidência: os resultados desta subseção foram confirmados pelo
operador durante a execução e reconciliados nesta atualização. Não existe no
repositório um pacote imutável de logs, consultas ou SHA de runtime que permita
reproduzir a prova de forma independente. Por isso, o resultado operacional não
é usado para inferir deploy nem ampliar autorização.

- foi usado um único número sintético previamente validado. O número não é
  registrado em claro;
- o roteiro recebeu, nesta ordem, `Olá`, `Aceito` e
  `Quero conhecer a igreja`;
- foram observadas exatamente três entradas e três saídas, com autoria de IA
  corretamente classificada;
- as filas canônicas de entrada e processamento e a dead-letter canônica
  terminaram vazias. O item legado preservado na quarentena continua sujeito à
  revisão de retenção de 2026-09-25 e não é reclassificado como resolvido;
- ao final, `AgentConfig.ativo=false` foi restaurado para a Filadélfia e os
  quatro gates globais foram confirmados fechados pelo operador;
- nenhum telefone, token, chave, ciphertext ou conteúdo pessoal foi incluído
  neste registro.

Resultado técnico: **PASS CONTROLADO** para roteamento, cardinalidade das
mensagens, autoria e fechamento dos gates.

Resultado de produto: **QUALIDADE INSUFICIENTE**. O operador identificou tom
robótico e repetição de perguntas. O canário comprovou a contenção técnica da
fundação, mas não aprovou a experiência conversacional nem autoriza rollout para
outras igrejas.

Estado atual: **PRIMEIRO CANÁRIO TÉCNICO PASS / QUALIDADE FAIL / ROLLOUT AMPLO
BLOCKED / GATES FECHADOS**.

### D1 e hardening D1A (2026-08-27)

A PR #310 integrou a documentação D0 em
`253d23000a2afefa60210081904eb6b7f081acdd`. A auditoria D1 local desse SHA
confirmou quatro gaps antes da expansão do agente: tenant opcional em um caminho
do runtime, instância Evolution sem unicidade global, relações críticas sem FK
composta por igreja e CI RLS baseado em allowlist.

A PR #311 integrou a D1A no `origin/main`
`01265fc7dfe239e487b5cddb6d9f6714128e3c84`. A migration foi aplicada somente
no Supabase DEV `cxmjojnocigekgcxhubi`, seguida de post-check de constraints,
índices e advisors. Produção, VPS, flags, agente e envios não foram alterados.

### D2A, fronteira privada inativa do agente (2026-08-27)

A PR #313 integrou a primeira fatia D2 no `origin/main`
`1fbe1f499e81d22102d6f0507e31a59816a93055`. A D2A continua
deliberadamente inativa: cria uma role `agent_runtime` sem login, um schema
privado e um helper de tenant por GUC, além de uma factory exclusiva sem
fallback para a conexão privilegiada. Worker, LangGraph e checkpointer
continuam desconectados dessa factory.

O candidato incorporado passou em PostgreSQL 17 descartável com 278 testes RLS
e na suíte offline com 2.688 testes. O módulo D2A passou em 11/11 casos, dez RLS
e um contrato estático. Essas evidências validam a implementação incorporada;
não provam aplicação em Supabase, provisionamento ou execução do runtime em
ambiente compartilhado.

Na integração de 2026-08-27 em `America/Sao_Paulo`, os cinco workflows da PR
#313 (`33136716048`, `33136716106`, `33136715981`, `33136716033` e
`33136716067`) e os cinco workflows pós-merge (`33136878052`, `33136878082`,
`33136878068`, `33136878076` e `33136878079`) concluíram verdes no merge commit
`1fbe1f499e81d22102d6f0507e31a59816a93055`. O preview automático da PR não
constituiu deploy manual, deploy do backend ou promoção a produção, nem prova
de execução do backend em ambiente compartilhado.

Esta fatia não cria memória, tabelas de checkpoint, consentimentos por
finalidade, propostas, ferramentas ou especialistas. A integração também não
provisionou credencial, não aplicou migration em ambiente compartilhado, não
conectou o runtime, não fez deploy manual ou do backend, não promoveu a produção
e não ativou o agente. Universidade da Vida e Capacitação Destino ficam fora da
missão atual.

A PR #314 integrou a reconciliação documental D2-RECONCILE no `origin/main`
`1029e1b0adb9479a2a23d60e27e9215a6ae6a10e`. Essa integração apenas atualizou
fontes documentais e não mudou o estado operacional da D2A.

### D2B1, contexto confiável v1 integrado no código (2026-08-28)

A PR #315, com HEAD `5b6a171a3afc5f2df4ea60465a7c1cf3f98b7a4b`, foi
integrada no merge commit `84c5b71b415340868c1b0664e892b8b0350d91f4` em
`2026-08-28T04:34:56Z`. A D2B1 separa o contexto confiável do `AgentState`
mutável. O servidor monta um
`TrustedAgentContext` imutável e tipado; o LangGraph o recebe por
`StateGraph.context_schema`; entrada, caminho compilado, caminho direto e cada
node revalidam a fronteira. A entrada e o snapshot de Pessoa recusam chaves de
autoridade, IDs, telefone e campos não necessários ao turno. A mesma
instância de `PrivilegeContext` chega ao executor de tools.

A implementação passou em 224 testes focais e recebeu duas passagens
adversariais com os achados P1 fechados e parecer `GO`. A evidência final do
merge registrou 2.770 testes offline aprovados e 278 desselecionados; a suíte
RLS registrou 278 aprovados e zero skips. O monitor registrou 62 aprovados e
três skips; a validação Node registrou quatro aprovados.

Os cinco workflows da PR concluíram verdes: Backend Tests `33142034809`,
Tooling Static Checks `33142034808`, Frontend CI `33142034840`, RLS Integration
`33142034827` e E2E Critical `33142034905`. Os cinco pós-merge também concluíram
verdes: Backend Tests `33142225870`, Tooling Static Checks `33142225884`,
Frontend CI `33142225883`, RLS Integration `33142225923` e E2E Critical
`33142225876`.

Esta é evidência de código integrado e testes, sem prova operacional. A D2B1
não adicionou migration ou schema, não acessou Supabase, não provisionou
credencial, não conectou a fronteira privada D2A, worker, fila ou checkpointer,
não fez deploy manual ou do backend, não promoveu a produção, não ativou o
agente e não executou canário. O preview automático da PR não prova execução do
backend. O LangGraph continua stateless e a D2A permanece inativa.

A PR #316 integrou a reconciliação documental pós-merge da D2B1 no
`origin/main` `3d5c1099734f5f7da28fc84c6d6bf42f7b57a876`. Essa integração
não mudou banco, runtime ou ambiente operacional.

### D2B2a, ledger integrado e inativo de consentimento por finalidade (2026-08-28)

A PR #317 integrou a D2B2a no `origin/main`. O HEAD da implementação foi
`8ba5c988e9169703c923b1f1a3e47d1c427531e1` e o merge foi
`bce5a9a434077e488cea8baae3e9dd7c7c4ba0f1`. A fatia adiciona
migration, ORM, tipos de domínio e serviço interno sem caller para
`public.consentimento_finalidade_evento`.

O contrato separa `atendimento_solicitado`, `cuidado_pastoral`,
`tarefas_operacionais` e `comunicados`. Cada evento possui estado
`concedido|retirado`, `versao_termo`, fonte
`whatsapp_inbound|painel_autenticado`, `chave_idempotencia`, `sequencia` e
instante do servidor. No INSERT inicial, `registrado_por_app_user_id` é
obrigatório somente para o painel autenticado e deve ser nulo no WhatsApp. A
exclusão referencial posterior do AppUser pode anonimizar o operador via
`ON DELETE SET NULL`, preservando o evento.

O ledger é append-only. A idempotência é isolada por tenant; a sequência é
atribuída por stream em trigger sob advisory lock transacional. A tabela
habilita e força RLS, usa barreira restritiva dependente somente do GUC
`app.tenant_igreja_id` e aplica ACL mínima. O registro não contém texto de
mensagem, telefone ou payload pastoral.

Não existe backfill: `consent_records` e `pessoas.consentimento` permanecem
legados e não concedem por inferência as novas finalidades. O opt-out global
continua prevalecendo. Termo desatualizado exige novo aceite.

A fundação não expõe API, router ou tela e não conecta webhook, WhatsApp,
painel, worker, LangGraph, tool, broadcast ou outro caller. Ela não foi aplicada
em Supabase DEV ou PROD, não fez deploy manual ou do backend, não ativou o
agente e não executou canário. O merge gerou deployment frontend automático
pela integração Vercel. Universidade da Vida e Capacitação Destino permanecem
fora.

Textos e versões, hipótese jurídica, prova, tratamento de menores, retenção,
eliminação, transferência internacional, opt-out e responsáveis por direitos e
incidentes continuam abertos. São decisões do responsável humano e da função
jurídica ou encarregado, não inferências do código. Esses contratos bloqueiam
qualquer caller e ambiente compartilhado.

Antes do merge, o módulo de contrato, incluindo a aplicação do SQL inalterado
duas vezes em `public`, passou em 11 de 11 no PostgreSQL 17 e na imagem Supabase
PG17. A suíte
RLS completa passou em 288 de 288, sem falhas ou skips, e os testes offline
D2B2a passaram em 32 de 32. Essas provas não acessaram nem alteraram Supabase
DEV ou PROD.

Os cinco workflows da PR #317 concluíram com `SUCCESS`: Backend Tests
`33145078616`, E2E Critical `33145078590`, Frontend CI `33145078637`, RLS
Integration `33145078608` e Tooling Static Checks `33145078672`. Os cinco
pós-merge também concluíram com `SUCCESS`: Backend Tests `33145205844`, E2E
Critical `33145205869`, Frontend CI `33145205852`, RLS Integration
`33145205864` e Tooling Static Checks `33145205854`.

Essa PR gerou Preview automático, deployment `6136192331`, e o merge gerou
deployment frontend Vercel automático classificado como Production,
`6136214234`. A integração não aplicou a migration em Supabase DEV ou PROD,
não fez deploy manual ou do backend, não ativou o agente e não executou
canário. A metadata prova o deployment do frontend no ambiente Production da
Vercel; não prova backend, banco ou Supabase.

### D2B2b1, fronteira de segurança integrada e inativa (2026-08-28)

A D2B2b1 é deliberadamente código puro, sem migration ou caller. A chave de
idempotência nasce opaca em componente confiável do servidor, sem telefone,
conteúdo de mensagem, identificador pastoral ou material escolhido pelo
cliente ou modelo. A autorização é deny-first: ausência da capacidade exata
nega. Enquanto o pacote humano e jurídico não existir, toda tentativa de
registrar `concedido` é recusada, mesmo com tenant, papel, fonte e chave
sintaticamente válidos. A fatia não reidrata chave por valor; retry entre
processos depende de futuro recibo durável autenticado que prove a origem da
chave. Os indicadores puros de escopo ainda não são autorização operacional:
antes de qualquer caller, um builder server-side deve vinculá-los na mesma
transação ao tenant, ator, Pessoa alvo e recurso canônico.

A fronteira não conecta API, painel, WhatsApp, worker, LangGraph, tool,
broadcast, banco ou Supabase. Limpar o opt-out não restaura consentimento e a
fonte `painel_autenticado` não prova manifestação do titular. D2C permanece
bloqueada.

O recorte focal D2B2b1 e suas fronteiras adjacentes passou em 1.114 de 1.114
testes. A suíte RLS completa passou em 288 de 288 contra PostgreSQL 17
descartável, sem falhas ou skips. O workflow Backend Tests aprovou a suíte
integral. Nenhum ambiente Supabase foi acessado ou alterado por essas provas, e
o PostgreSQL temporário foi removido.

A PR #318, HEAD `ede4797003e044f582da9f9a3ab86554f708a73a`, foi integrada no
merge `74951828f48994622a112d8e59eb978e5fb4f406`. Os cinco workflows da PR
concluíram com `SUCCESS`: Backend Tests `33147247668`, E2E Critical
`33147247632`, Frontend CI `33147247672`, RLS Integration `33147247645` e
Tooling Static Checks `33147247624`. Os cinco pós-merge também concluíram com
`SUCCESS`: Backend Tests `33147433974`, E2E Critical `33147434002`, Frontend
CI `33147433944`, RLS Integration `33147433941` e Tooling Static Checks
`33147433956`.

A PR gerou Preview automático, deployment `6136583334`, e o merge gerou
deployment frontend Vercel automático classificado como Production,
`6136622236`, ambos com `SUCCESS`. Não houve deploy manual ou do backend,
migration, Supabase, ativação ou canário.

O pacote humano e jurídico obrigatório deve definir, por finalidade,
controlador e operadores reais, dados e operações mínimas, texto e versão,
hipótese jurídica, prova correlacionada, menores, retenção e eliminação,
transferência internacional, opt-out, direitos, incidentes e aprovadores. O
contrato técnico e as fontes primárias consultadas estão na
[`decisão D2B2b1`](../decisions/2026-08-28-d2b2b1-consent-security-boundary.md);
o documento não constitui parecer jurídico.

O formulário vazio está no
[`contrato D2B2b2`](../decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md)
e permanece `TEMPLATE_ONLY / NOT_APPROVED`. Teste, revisão e merge desse
template não constituem aprovação nem autorização de runtime.

### D2B2b3A, rascunhos governados pelo Console Master (2026-08-28)

A PR #320 integrou migration versionada, persistência, API e aba de governança
no Console Master somente para preparar
rascunhos por igreja. O Master autenticado organiza fatos e campos permitidos;
tenant e ator são derivados no servidor e nenhum e-mail é usado como regra de
autorização ou configuração versionada.

O Master não pode escolher hipótese jurídica, declarar que uma operação
depende de consentimento, decidir política para menores, atestar, aprovar,
representar outro papel ou preencher registros nominais. Todo rascunho
operacional permanece `DRAFT_NOT_APPROVED`, com os indicadores de aprovação,
catálogo e writer fechados. A migration foi comprovada somente em PostgreSQL 17
descartável. Supabase compartilhado, painel do tenant, aprovações, catálogo,
evidence store, writer, WhatsApp, agente, deploy manual ou do backend e D2C não
estão autorizados.

A leitura anterior somente leitura no Supabase DEV `cxmjojnocigekgcxhubi`,
projeto `Igreja12-dev`, confirmou estado `ACTIVE_HEALTHY` em PostgreSQL
`17.6.1.127`. Na sessão, `current_user` e `session_user` eram `postgres`; a role
era `NOSUPERUSER`, `BYPASSRLS`, `CREATEROLE`, `CREATEDB`, `LOGIN` e `INHERIT`.
O schema `public` pertencia a `pg_database_owner`, e o executor tinha `CREATE` e
`USAGE`; `igrejas` e `app_users` existiam, pertenciam a `postgres` e concediam
`SELECT` e `REFERENCES` ao executor. As roles `anon`, `authenticated` e
`service_role` não alcançavam esse executor, e `agent_runtime` estava ausente
nesse projeto. A tabela alvo, o validator e o registro da migration
`20260828094914` da D2B2b3A estavam ausentes. Naquele preflight, o conector
listou somente projetos da conta DEV; PROD não estava acessível e não foi
consultado naquele momento.

Essa evidência DEV anterior comprova somente a identidade do executor MCP e a
ausência da D2B2b3A naquele projeto. Ela não prova
`M06_MIGRATION_DATABASE_URL`, `DATABASE_URL` nem a VPS e não aplicou migration.

A implementação integrada e inativa não prova o wiring do banco. No baseline
`15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`, o preflight PROD somente leitura
confirmou `DATABASE_URL` presente e `M06_MIGRATION_DATABASE_URL` ausente.
O preflight ocorreu em 2026-08-28; o horário exato da consulta não foi capturado
e não foi reconstruído por inferência.
`current_user` e `session_user` convergiram para a mesma identidade sanitizada;
a role runtime possui `NOSUPERUSER`, `BYPASSRLS`, `LOGIN` e `INHERIT`, é owner
de `public.igrejas` e `public.app_users` e possui `SELECT` e `REFERENCES`
efetivos nessas tabelas-pai. A tabela alvo D2B2b3A, o validator e a própria
`public.schema_migrations` estavam ausentes. Isso comprova identidade, ownership
e ACL do caminho runtime atual, mas não o comportamento da tabela futura sob
`FORCE RLS`; o caminho de migration permanece bloqueado pela ausência de
`M06_MIGRATION_DATABASE_URL` e do ledger público.

A PR #321 integrou a reconciliação documental anterior no merge
`15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`; esse merge gerou o deployment
automático Vercel frontend Production `6141449639`, com `SUCCESS`, em
2026-08-28T12:53:35Z. Essa metadata prova somente o frontend, sem provar backend,
banco ou Supabase.

O contrato está em
[`2026-08-28-d2b2b3-master-governance-drafts.md`](../decisions/2026-08-28-d2b2b3-master-governance-drafts.md).

A PR #320, HEAD `66ce06d9a356a52e63366b3a6528b0b83170d12e`, foi integrada no
merge `947d891c2ea278b7a3231fecd9ca1c90cfe29a1f`. Os cinco workflows da PR
concluíram com `SUCCESS`: Backend Tests `33165481522`, E2E Critical
`33165481590`, Frontend CI `33165481546`, RLS Integration `33165481561` e
Tooling Static Checks `33165481549`. Os cinco workflows pós-merge também
concluíram com `SUCCESS`: Backend Tests `33167430903`, E2E Critical
`33167430935`, Frontend CI `33167430953`, RLS Integration `33167430898` e
Tooling Static Checks `33167430895`.

O merge gerou o deployment automático Vercel frontend Production `6140373952`,
com `SUCCESS`. Essa metadata prova somente o frontend nesse ambiente; não prova
backend, banco ou Supabase. No recorte da PR #320 não houve deploy manual ou do
backend, wiring, ativação ou canário. Esta missão não aplicou a migration D2B2b3A; DEV e PROD
confirmaram a ausência. A flag versionada
`PURPOSE_CONSENT_GOVERNANCE_DRAFTS_ENABLED` permanece `false`.

O preflight PROD somente leitura não abriu arquivo de configuração nem exibiu
valor de conexão. A chave SSH temporária de auditoria foi cadastrada, usada
exclusivamente nessa leitura, revogada e testada após a revogação, quando o
acesso foi negado. Os arquivos temporários locais foram removidos. O preflight
VPS em si não executou deploy manual ou do backend, migration, restart, alteração
da flag ou outra mutação de estado.

### LEDGER-BOOTSTRAP, integrado e comprovado offline, não aplicado (2026-08-28)

Desenvolvida e comprovada offline sobre a base versionada
`b43ad92028374fa6763ef10f5eb7a379afd3e7a2`, a implementação foi integrada
pela PR #323. O subcomando explícito e fail-closed `bootstrap-ledger` é separado de
`harden-ledger`. Ele exige `--confirm BOOTSTRAP_LEDGER` antes da conexão e lê o
destino somente de `M06_MIGRATION_DATABASE_URL`. Em PostgreSQL 17, cria em uma
transação `SERIALIZABLE` exclusivamente o ledger vazio
`public.schema_migrations`, com colunas, chave primária e defaults exatos,
owner estável, RLS, policy deny e ACL owner-only. Objeto ou tipo homônimo,
default privilege ou grant de schema perigoso, membership, ownership ou forma
física divergente aborta com rollback. Reaplicar o contrato exato e vazio não
produz mutação.

A validação concluiu 42/42 testes unitários, 87/87 em PostgreSQL 17-alpine
descartável em duas execuções independentes e 87/87 em Supabase PG17
17.6.1.159 descartável em duas execuções independentes. A revisão de segurança
resultou em `GO`. A suíte RLS completa, em execução serial limpa no PostgreSQL
17 descartável, passou em 326/326, com 3803 deselecionados e 2 warnings
preexistentes, em 162.77s. A suíte offline integral foi interrompida após 5
min sem saída ou progresso; o resultado é `INCONCLUSIVO`, não verde nem falha
e não foi reclassificado. Os workflows Backend Tests da PR #323 e do pós-merge
concluíram com `SUCCESS`. O bootstrap não descobre o catálogo local, não consulta,
copia ou altera `supabase_migrations`, não reconcilia, não faz backfill e não
aplica ou registra migration. O ledger vazio mantém `status` e `apply`
bloqueados até uma reconciliação histórica humana formar o prefixo íntegro do
catálogo, com no máximo uma migration pendente.

A PR #323, HEAD `74d3f2d87a7ffad501432b2d9fc4163bd3b4ada4`, foi integrada em
`main` pelo merge `3a5789c784017ab15a43e28c4270d25af8618359` em
`2026-08-28T15:24:58Z`. Os cinco workflows da PR concluíram com `SUCCESS`:
Backend Tests `33184817567`, Frontend CI `33184817526`, RLS Integration
`33184817442`, E2E Critical `33184817428` e Tooling Static Checks
`33184817512`. Os cinco pós-merge também concluíram com `SUCCESS`: Frontend CI
`33185027149`, RLS Integration `33185027115`, Tooling Static Checks
`33185027132`, Backend Tests `33185027091` e E2E Critical `33185027090`.

A Vercel registrou o Preview automático frontend `6143773477`, com `SUCCESS`,
em `2026-08-28T15:22:43Z`, e o Production automático frontend `6143819601`,
com `SUCCESS`, em `2026-08-28T15:25:43Z`. Essas metadatas provam somente o
frontend, sem provar backend, banco ou runtime. O bootstrap está integrado, mas
continua não aplicado. Não houve deploy manual ou do backend, acesso aos bancos
DEV ou PROD, bootstrap ou migration compartilhada, provisionamento de
`M06_MIGRATION_DATABASE_URL`, restart ou alteração de flag, runtime, agente ou
canário. O preflight PROD da seção anterior e o deployment automático frontend
da PR #321 permanecem evidências históricas separadas e não foram revalidados
nesta missão.

### MIGRATION-HISTORY-RECONCILIATION, integrada e comprovada offline

O pacote deny-state versionado e o verificador stdlib separado do runner,
desenvolvidos e comprovados offline sobre a base auditada
`cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7`, foram integrados pela PR #325,
HEAD `d9595c3958fec98a875d15de2b6647d6b1de435e`, no merge
`ab7d09f07db96d5c63a2cc32dddf3f910e23bac2` em
`2026-08-28T20:18:08Z`, conforme
[`2026-08-28-migration-history-reconciliation-contract.md`](../decisions/2026-08-28-migration-history-reconciliation-contract.md).
O estado é `INTEGRADO / COMPROVADO OFFLINE / DECISÕES HUMANAS PENDENTES / NÃO
APLICADO`. Nenhuma decisão humana está aprovada. A integração não acessou DEV
ou PROD, não materializou inventário de ambiente e não reconciliou nenhum ledger. O
verificador não acessa banco, rede, ambiente ou variáveis de ambiente, não
executa SQL, DML ou escrita e não infere migration aplicada. Os ledgers nativo
e público permanecem independentes e todo sucesso estrutural conserva
`OPERATIONAL_AUTHORIZATION=BLOCKED`.

Os workflows da PR concluíram com `SUCCESS`: Backend `33207468055`, E2E
`33207468044`, Frontend `33207468014`, RLS `33207468132` e Tooling
`33207468082`. Os pós-merge também concluíram com `SUCCESS`: Backend
`33207645381`, E2E `33207645348`, Frontend `33207645362`, RLS `33207645399` e
Tooling `33207645340`. A Vercel registrou o Preview automático frontend
`6147914118`, com `SUCCESS`, em `2026-08-28T20:16:00Z` no HEAD, e o Production
automático frontend `6147952424`, com `SUCCESS`, em `2026-08-28T20:18:55Z` no
merge. Essas metadatas provam somente o frontend, sem provar backend, banco ou
runtime. Não houve deploy manual ou do backend, migration, bootstrap,
hardening, restart, credencial, flag, runtime, agente ou canário.

A prova local preservada é `98/98` testes do verificador, `26/26` testes
documentais e `42/42` testes offline do runner: agregado de
`166 passed/45 skipped`. O template deny-state terminou bloqueado com exit `8`.

O capturador e o materializador foram integrados pela PR #327, HEAD
`c4f7a25b81a8091a0d74783c816a168bb7adf44d`, no merge
`f9201a06495fad138e313e4149ad9275ff896900`. A PR #328 integrou o hotfix, HEAD
`2cbdfaf39ae11d984f0aa27dfcf0910c25984840`, no merge
`04e5c1720bf89313718c4159a2ac9d0eeeed3c25`. O catálogo de base
`656d1d9eebe90ad4b2cbb35c21939a6796c46bfe` contém 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`; o SQL
allowlisted tem SHA-256
`8b589e5dda722691fead34cbd63cab75a7a22f32e0cf4bdfe64d6cef603866ee`.

O estado é `INVENTÁRIOS DEV E PROD CAPTURADOS / REVISÃO INDEPENDENTE BLOQUEADA
CONCLUÍDA / DECISÃO OWNER-01 REGISTRADA / NÃO APLICADO`. Em PostgreSQL 17, DEV registrou
33 linhas no ledger público e 6 no nativo em
`2026-08-28T22:43:11.454382Z`; PROD registrou o ledger público
`ABSENT_CONFIRMED`, com 0 linhas, e 32 linhas no nativo em
`2026-08-28T22:47:43.965243Z`. `native.name` permaneceu sempre `null`. Os dois
pacotes estão em `EVIDENCE_CAPTURED_UNREVIEWED`; cada verificação terminou com
exit `8`, `HUMAN_EVIDENCE_BLOCKED`, e a checagem conjunta terminou
`CROSS_PACKAGE_OK`. A matriz focal offline pós-captura passou com `163 passed,
2 skipped` em `1.40s`; isso não é suíte integral nem reexecução PostgreSQL.

Foram originalmente materializados localmente seis artefatos sanitizados, com
modo `0600` e `O_EXCL`: um pacote e os recibos público e nativo de DEV, mais um
pacote e os dois recibos de PROD, em
`docs/governance/migrations/packets/`. Depois do versionamento, sua proteção
depende da sanitização e da ACL do repositório, não do modo do checkout. A
captura ocorreu somente em
leitura e não executou DML, runner, `bootstrap-ledger`, `harden-ledger`,
`status`, `apply`, deploy, flag ou runtime. Os artefatos não provam decisão
humana, migration aplicada, prefixo reconciliado ou autorização operacional.

A PR #329, HEAD `c5ae430aa865dbd6371953d43e4a4447ca8e6618`, integrou e
versionou os seis artefatos no merge
`341f38a7f1c6993c74d85e99748cb60046cd4501` em `2026-08-29T00:04:50Z`. Os
workflows da PR concluíram com `SUCCESS`: Backend `33222301288`, E2E
`33222301419`, Frontend `33222301331`, RLS `33222301296` e Tooling
`33222301367`. Os pós-merge também concluíram com `SUCCESS`: Backend
`33222447467`, E2E `33222447447`, Frontend `33222447518`, RLS `33222447506` e
Tooling `33222447495`.

O merge gerou o deployment automático Vercel frontend Production `6150482852`,
com `SUCCESS`, em `2026-08-29T00:05:33Z`. Essa metadata prova somente o
frontend, sem provar deploy manual ou do backend, banco ou runtime. A integração
versiona a evidência sanitizada já capturada, mas não revisa os inventários,
não altera `EVIDENCE_CAPTURED_UNREVIEWED` ou `HUMAN_EVIDENCE_BLOCKED`, não
aplica migration e não libera o runner nem qualquer autorização operacional.

Em `2026-08-29`, `REVIEWER-01` concluiu a revisão independente e classificou
DEV como `BLOCKED_LEDGER_DIVERGENCE` e PROD como
`BLOCKED_EVIDENCE_INSUFFICIENT`. O registro externo sanitizado tem SHA-256
`18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133` e não
foi versionado. `OWNER-01` aceitou o bloqueio, manteve
`operational_authorization=false` e autorizou somente a preparação offline da
correção. O registro externo dessa decisão tem SHA-256
`0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240` e não
foi versionado. Nenhum pacote foi alterado e nenhum comando do runner foi
liberado.

O manifesto estático de expectativas da fonte foi criado sobre a base
`7f18f7e8b44cd50e6f6033867fb97bfa9eb9c9e6`. Ele fixa 75 migrations e o
digest `84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`,
mas declara `SOURCE_LEVEL_EXPECTATION_ONLY`: não prova o schema final de DEV ou
PROD. O verificador terminou em
`SCHEMA_EXPECTATION_MANIFEST_VERIFIED_SOURCE_ONLY`, com
`OPERATIONAL_AUTHORIZATION=BLOCKED` e
`ENVIRONMENT_ATTESTATION_COMPLETE=false`. A revisão técnica foi feita pelo
mesmo executor e não é independente.

A derivação canônica foi reproduzida e verificada somente offline, duas vezes,
em PostgreSQL 17 descartável, sobre a base
`07d2c05c687d1a0e8deeacbb7f8b16fbdd0e4e86`. As execuções A e B produziram os
mesmos 388390 bytes, o SHA-256
`7040a54d80c0ee4f37e1986ff0a579db275e45c129f4fdafcd66788e22a3eb3e` e o
fingerprint `8ac17d4352a77fb3c5885f9c1a55813a5b7dfcd6fb84c4bd4e9117c1c7883370`.
A evidência e os limites estão na
[`decisão de derivação offline`](../decisions/2026-08-29-offline-canonical-schema-derivation.md).
Isso não atesta DEV, PROD, Data API ou Realtime; `OPERATIONAL_AUTHORIZATION=BLOCKED`
permanece obrigatório.

A PR #334, HEAD `a864730f0b678cca39cebfa6bb378243ba031cd6`, foi integrada no
merge `c8427b1a505c0aad2a5f675d3bf456ee33716690`; o Git registra
`commit date=2026-08-29T21:21:15Z`, e o GitHub registra
`mergedAt=2026-08-29T21:21:16Z`. Os seis checks da PR e os seis pós-merge
concluíram com `SUCCESS`; os detalhes da API do deployment automático Vercel
frontend Production `6160229001` estão na evidência detalhada em
[`decisão de derivação offline`](../decisions/2026-08-29-offline-canonical-schema-derivation.md).
Os checks provam apenas o comportamento exercitado naquele SHA; a metadata do
deployment prova somente o frontend e não prova backend, banco, migration,
runtime ou atestação de ambiente.

A ferramenta separada de atestação read-only foi implementada no commit técnico
`be958ce96e65d3d497923b7f5f912676634e9587`, sobre a base
`1072e6a8e85d201a1c82f37a8ddeac5417300c49`. A prova focal offline passou em
`81/81`, a seleção relacionada terminou em `367 passed, 47 skipped` e a prova
focal em PostgreSQL 17 TLS descartável passou em `82/82`. Sarah/Terra concluiu
`GO`; o healthcheck do Claude Opus passou, mas a revisão completa travou com
`Execution error` e não foi reclassificada como revisão concluída.

A PR #337, HEAD `abf6f823336b81e93ec1c942dcd5a357d8ac797c`, integrou o tooling
no merge `278afb205a3b4735d4aeb66e2e585f71fd562ef7`, com
`mergedAt=2026-08-30T11:38:16Z`. Os sete workflows do push em `main`
concluíram com `SUCCESS`: Environment Attestation PG17 `33309430738`, Frontend
CI `33309430763`, Canonical Schema Derivation `33309430775`, Backend Tests
`33309430797`, Tooling Static Checks `33309430744`, E2E Critical `33309430731`
e RLS Integration `33309430799`.

A Vercel registrou o deployment frontend Production `6166209567`, com
`state=success`; o deployment e seu status registraram
`created_at=2026-08-30T11:39:02Z`. Essa metadata prova somente o frontend e não
prova backend, banco ou runtime. O estado corrente é
`INTEGRADO E COMPROVADO OFFLINE / AMBIENTES NÃO CONSULTADOS / OPERAÇÃO BLOQUEADA`.

O tooling integrado permanece fail-closed, conforme a
[`decisão de atestação read-only`](../decisions/2026-08-30-read-only-environment-attestation-tooling.md).
Nenhum DEV ou PROD foi consultado e nenhum artefato ambiental foi produzido.
O schema JSON valida somente o envelope; o verificador Python continua
obrigatório. O HMAC serve para correlação e anti-swap, sem substituir
autorização humana nem observar diretamente o project ref. Data API e Realtime
permanecem `PLATFORM_SURFACES_UNATTESTED`.

`OPERATIONAL_AUTHORIZATION=BLOCKED` e
`environment_attestation_complete=false` permanecem invariantes. Runner, DML,
migration, reconciliação, backfill, deploy, flag e runtime continuam
bloqueados.

Sobre a base versionada `fe7dcd394bd1cfdc96204ad994bcba9f0c96adb4`, o runner
DEV preflight-only foi implementado e comprovado offline antes da integração.
Os SHA-256
congelados são: runner
`1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f`, testes
unitários `d96fab1afe99531e3cee0f84bc285876de303ed0265fa41c51f8da9a7bcab0a0`,
prova PG17 `ceecfe9afa09066e4863e93be556b8f92c00a2992e0a0aef3b4253458f6fc318`,
testes de atestação existentes
`68f9790a734f8adf78db8a716a5c2d99adad165f00737f922db90afa614b4ed8` e
workflow `80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf`.
Os unitários passaram em `210/210`; duas provas locais sequenciais no
PostgreSQL 17 TLS passaram em `1/1` para a atestação existente e `1/1` para o
runner com CA por FD.

A PR #340, HEAD `b29d3f494eabc3a04fe7f2c434758ad274f03930`, integrou o
runner no merge `82413edb884125d4d8f6e7946ffcaaf48ed8491c`, com
`mergedAt=2026-08-30T13:55:11Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: E2E `33315460948`, Frontend `33315460933`, Tooling
`33315460941`, RLS `33315460942`, Backend `33315460949`, Environment
Attestation PG17 `33315460934` e Canonical Schema Derivation `33315460939`.
A Vercel registrou o deployment frontend Production `6167369343`, com
`state=success`, em `2026-08-30T13:55:56Z`. Essa metadata prova somente o
frontend e não prova backend, banco ou runtime.

O contrato usa `TLS_MODE=VERIFY_FULL_EXPLICIT_CA` e exige que o digest da CA,
`TLS_CA_CERTIFICATE_SHA256`, esteja vinculado à autorização. O escopo
`PROCESS_INVOCATION_ONLY` exige nova autorização nominal para cada invocação.
O HMAC serve somente correlação e anti-swap e não substitui autorização humana.
O resultado produz zero arquivo, zero recibo, zero captura e zero
materialização. Os buffers de chave e nonce são zerados, os descritores são
fechados e os certificados TLS temporários são removidos após a prova. DEV e
PROD não foram consultados. PROD está explicitamente
fora. PROD continua fora. Estado:
`INTEGRADO E COMPROVADO OFFLINE / DEV/PROD NÃO CONSULTADOS / OPERAÇÃO
BLOQUEADA`.

Em 2026-08-30, já no `main`
`64cc157d649256a4a9819741f4276c0420590fd1`, duas invocações DEV foram feitas
sob autorizações humanas nominais distintas e exclusivas, cada uma limitada a
`PROCESS_INVOCATION_ONLY`. O timestamp operacional preciso não foi preservado;
nenhum horário UTC foi inferido. Ambas terminaram com exit `7`,
`RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED`, `ROLLBACK_CONFIRMED=false` e
`CONNECTION_CLOSED=true`. Em ambas, `OPERATIONAL_AUTHORIZATION=false`,
`NEXT_STAGE_AUTHORIZED=false`, `CAPTURE_EXECUTED=false`,
`MATERIALIZATION_EXECUTED=false` e `PROD_ACCESSED=false`. Esses campos não
provam se houve conexão, não provam sucesso ou falha de autenticação e não
identificam a causa raiz.

O diagnóstico posterior passou em `2/2` no caminho full-main sobre PostgreSQL
17 TLS descartável e em `97/97` no foco offline. O runner permaneceu intacto,
SHA-256 `1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f`,
assim como o workflow, SHA-256
`80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf`.
A prova PG17 ampliada tem SHA-256
`ddbc092216604e65cf86070d409837c7d328da96116ae5ea8d0947195b421b9e`.
Essa prova local não reclassifica DEV nem determina a causa do bloqueio. A
evidência detalhada está em
[`diagnóstico do preflight de identidade de DEV`](../decisions/2026-08-30-dev-identity-preflight-diagnostics.md).
Estado: `DUAS INVOCACOES DEV BLOQUEADAS / CAUSA NAO DETERMINADA / PROD NAO
CONSULTADO / OPERACAO BLOQUEADA`.

A PR #342, HEAD `5076c47b19fffe503e823d68c6dadfc59b11ed5d`, integrou a
prova diagnóstica no merge `bc202da6c0ef83e03ded4392e508441cd4d6a188`, com
`mergedAt=2026-08-30T15:24:45Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Canonical `33319560819`, Environment Attestation PG17
`33319560923`, E2E `33319560908`, RLS `33319560769`, Backend `33319560836`,
Frontend `33319560781` e Tooling `33319560786`. A Vercel registrou o
deployment frontend Production `6168185324`, com status `17531418022`,
`state=success` e `created_at=updated_at=2026-08-30T15:25:32Z`. Essa metadata
prova somente o frontend e não prova backend, banco ou runtime.

A integração não repetiu o preflight, não consultou logs, não fez novo acesso a
DEV ou PROD e não determinou a causa do exit `7`. Runner e workflow permanecem
intactos. Estado: `INTEGRADO E COMPROVADO OFFLINE / DUAS INVOCACOES DEV
BLOQUEADAS / CAUSA NAO DETERMINADA / PROD NAO CONSULTADO / OPERACAO
BLOQUEADA`.

Sobre a base `3685bbcaf11d5a20b3492953d897cb6a459701a8`, o candidato
pré-merge adiciona o enum estático `PREFLIGHT_FAILURE_PHASE` com dez valores:
`PRECONNECT_GUARDS`, `CONNECT_TLS_AUTH`, `SERVER_VERSION`, `SESSION_GUARDS`,
`IDENTITY_VALIDATION`, `ROLLBACK`, `CURSOR_CLOSE`, `CONNECTION_CLOSE`,
`POSTCONNECT_TLS_CA_REVALIDATION` e `POST_IDENTITY_FINALIZATION`. A fase é
somente a última fronteira operacional iniciada, nunca a causa; em especial,
`CONNECT_TLS_AUTH` não prova nem separa rede, TLS ou credencial. Cada saída
`BLOCKED` contém exatamente uma linha de fase, o sucesso não a contém e a
primeira falha vence quando há falhas posteriores.

Os SHA-256 congelados são runner
`8da631fbb602488bb8c82ce1529c9d8ba17acbae8a318ea9b0fc24cdd8f65cd2`,
unitários `c55726f0ad8abf7680de868cba155388f7e56773aa8054e556be89dc87aa90a8` e
PG17 `d86037d759d254581d2259026585ac768e4b2d68595473371ec65daf6c6de5a9`.
Passaram `109 passed, 2 skipped` offline, `2/2` em PostgreSQL 17 TLS
descartável e `222 passed, 2 skipped` no agregado relevante; `pycompile` e
`diff-check` ficaram verdes, os recursos temporários foram removidos e Sarah
concluiu `GO`, sem P0, P1 ou P2. As duas execuções DEV históricas com exit `7`
não podem ser retroclassificadas. A única `query_logs` anterior retornou vazio
e continua `EVIDENCE_INSUFFICIENT`. Esta missão não repetiu a consulta e não
acessou DEV ou PROD. A evidência detalhada está na
[`decisão de fase sanitizada`](../decisions/2026-08-30-dev-preflight-failure-phase-diagnostics.md).

O enum sanitizado foi integrado pela PR #344 no `main`
`bab031a7e0067a257eedb4a24c786cc925801463`. Em `2026-08-31`, uma terceira e
única invocação DEV `PROCESS_INVOCATION_ONLY` nesse `main` terminou com exit
`7`, `RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED` e
`PREFLIGHT_FAILURE_PHASE=CONNECT_TLS_AUTH`. A autorização era válida entre
`2026-08-31T11:03:30Z` e `2026-08-31T11:18:30Z`; essa janela não é o horário
da execução. O timestamp operacional preciso não foi preservado nem inferido.
DNS, TCP, TLS, CA, senha, autenticação, endpoint, disponibilidade, conexão,
transação e identidade permanecem `UNKNOWN`. A autorização foi consumida;
nenhum log foi consultado e não houve retry, captura, materialização, DML,
migration, backfill, deploy, flag, runtime ou acesso a PROD.
A limpeza removeu o diretório temporário de autorização, o launcher e a
worktree operacionais temporários; o checkout ficou limpo, sem `__pycache__` ou
`.pyc`, e o registro Git obsoleto da worktree foi removido.

O probe para separar somente DNS, TCP e TLS foi preparado offline e permanece
`execution_disabled=true`; ele não foi executado e não possui autorização viva.
O contrato e os limites estão na
[`decisão de 2026-08-31`](../decisions/2026-08-31-dev-connect-tls-auth-transport-probe.md).
`OPERATIONAL_AUTHORIZATION=false` e `NEXT_STAGE_AUTHORIZED=false` permanecem
obrigatórios.

A PR #346, HEAD `0c63dc29dc903e0e7012b9fb811b7b2ddb05ab51`, foi integrada no
merge `fb776e270bf3e2ffde0cbb28e400960591b74420`, com
`mergedAt=2026-08-31T13:02:07Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Tooling `33394774001`, Environment Attestation PG17 `33394774013`,
Canonical `33394773986`, E2E `33394774109`, Frontend `33394774063`, RLS
`33394773965` e Backend `33394774029`. A Vercel registrou o deployment
frontend Production `6181597461`, status `17569033825`, `state=success`, em
`2026-08-31T13:02:53Z`. Essa metadata prova somente o frontend e não prova
saúde funcional, backend, banco, DEV, PROD, probe ou migration. A integração
versionou apenas o plano offline: `execution_disabled=true`, implementação e
capacidade de rede ausentes, probe não executado e operação bloqueada.

A PR #347, HEAD `0a257e9aa1985860d5ea0a4506d4f7e84c7b2312`, foi integrada no
merge `36f8d13284a8f4964d0258a2a3b845323a80fe7e`, com
`mergedAt=2026-08-31T14:26:10Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`, e o deployment automático Vercel frontend Production `6183047421`,
status `17572803614`, terminou com `state=success` em
`2026-08-31T14:26:57Z`. Essa metadata prova somente o frontend.

Sobre esse merge, o candidato implementa o probe transport-only em
`backend/scripts/probe_dev_connect_tls_auth_transport.py`, SHA-256
`4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9`, e sua
matriz adversarial, SHA-256
`b79ff9d7473fdafd0a4fcd6ceba98b2c46f5470ef517b6663898812fe8b1296e`.
Passaram `90/90` testes exclusivamente offline, incluindo loopback TLS
sintético descartável. O runner recebe seis descritores privados, fixa o hash
do project-ref DEV e do registro de autorização, envia somente o SSLRequest
PostgreSQL de oito bytes, exige `S`, valida CA e hostname e fecha antes de
StartupMessage. Não recebe senha, usuário, banco ou DSN e não tenta
autenticação nem SQL. O plano JSON permanece histórico e byte-idêntico; seus
campos `execution_disabled=true` e `implementation_present=false` descrevem a
etapa anterior já consumida. A única rede desta rodada foi o `git fetch`
nominal autorizado para obter o merge; nenhum probe vivo, DEV, PROD, banco ou
log foi acessado. `operational_authorization=false` e
`next_stage_authorized=false` permanecem.

A PR #348, HEAD `af91e5218f9317a730aa29ad8d8c645312b30f19`, foi integrada no
merge `1e727cd2ea90ccfb68961174b802d595c71f355b`, com
`mergedAt=2026-08-31T15:22:49Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Tooling `33408103314`, Environment Attestation PG17 `33408103217`,
Canonical `33408103386`, Frontend `33408103193`, E2E `33408103279`, Backend
`33408103254` e RLS `33408103282`. A Vercel registrou o deployment automático
frontend Production `6184050276`, status `17575418445`, `state=success`, em
`2026-08-31T15:23:35Z`. Essa metadata prova somente o deployment do frontend,
não sua saúde funcional, e não prova backend, banco, DEV, PROD ou o probe. O
estado naquele recorte, antes do consumo do gate de execução, era
`IMPLEMENTADO / INTEGRADO / COMPROVADO OFFLINE / PROBE NÃO EXECUTADO /
OPERAÇÃO BLOQUEADA`. O estado corrente inclui a única execução registrada
abaixo, bloqueada em `TLS_HANDSHAKE`; não houve nova tentativa.

**Gate consumido em 2026-08-31:**
`SEPARATE_NOMINAL_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE_AUTHORIZATION`. Seu
consumo exige nova autorização humana nominal para exatamente uma invocação
`PROCESS_INVOCATION_ONLY` no checkout de `main` `1e727cd2`, com runner SHA-256
`4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9` e o
`source_main_git_sha=36f8d13284a8f4964d0258a2a3b845323a80fe7e` exigido pelo
contrato interno. Não autoriza retry, senha, autenticação, sessão de banco,
SQL, logs,
captura, materialização, DML, migration, reconciliação, backfill, deploy manual
ou Production, flag, runtime e PROD continuam bloqueados.

Uma única invocação terminou com exit `7`, fase `TLS_HANDSHAKE` e
`RESULT=BLOCKED_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE:TRANSPORT_BLOCKED`.
DNS, política de endereço, TCP e a resposta `S` ao SSLRequest foram
confirmados; handshake e hostname não foram confirmados. Não houve retry,
senha, autenticação, sessão de banco, SQL, logs ou PROD. A causa permanece
indeterminada e o resultado não recebe categoria retroativa. A evolução
offline adiciona somente uma categoria estática de falha TLS, com runner
SHA-256 `0ac585b86dd1c96446622e9a46bccda8a1e43eb0bceb0dcc19226892cb88d191`,
testes SHA-256
`70334dfc33505ea0b5ddb85a6406672fe0d9154e105134da164c773978459489` e
`95/95` testes verdes.

A PR #350, HEAD `58af39b760b8b5be85723d3ea693abd20fe3f3cf`, foi integrada no
merge `0f8c6a77bf489f9080743ab3f7ce71097d361aea`, com
`mergedAt=2026-08-31T16:38:27Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Backend `33415223927`, Canonical `33415223885`, E2E `33415223922`,
Environment Attestation PG17 `33415223904`, Frontend `33415223881`, RLS
`33415223955` e Tooling `33415223892`. A Vercel registrou o deployment
automático frontend Production `6185328714`, status `17578739446`, com
`SUCCESS`. Essa metadata prova somente o deployment do frontend, sem provar
saúde funcional, backend, banco, DEV, PROD, probe, migration ou runtime.

O gate `REVIEW_AND_CI_DEV_TLS_HANDSHAKE_FAILURE_CATEGORY_PR` foi consumido pela
PR #350. A categoria TLS está integrada e comprovada offline; o resultado
histórico não recebe categoria retroativa e a causa permanece indeterminada.
A árvore do merge é idêntica à do HEAD da PR.

O desenho `migration-epoch v3` deverá tratar como `KNOWN_UNVERIFIED_DRIFT`, sem nova
consulta nem inferência de migration aplicada, os sete índices observados por
evidência operacional anterior: `idx_pessoas_igreja_ativa_created`,
`idx_pessoas_igreja_ativa_tipo`, `idx_celulas_igreja_ativo_lider`,
`idx_work_queue_igreja_status_responsavel`,
`idx_conversations_igreja_assumido`, `idx_app_users_igreja_nome` e
`idx_user_roles_igreja_user`. Essa observação não foi revalidada nesta missão
e não prova o estado atual de DEV. A atestação v1 valida somente envelopes que
continuam bloqueados; ela não comprova conclusão e não pode ser reinterpretada
como `environment_attestation_complete=true`. Os artefatos históricos v1 e v2
permanecem byte-idênticos e fora do escopo.

O pacote candidato `migration-epoch v3` está congelado como
`OFFLINE_EPOCH_CUTOVER_DECISION_PACKAGE_BLOCKED`. O verificador
`backend/scripts/verify_migration_history_divergence_remediation_proposal_v3.py`
tem SHA-256 `8d7712be4f63ead2eff2c9e7af236e610b0c148acb07c85ebcd81db1f6d0877d`;
o teste `backend/tests/test_migration_history_divergence_remediation_v3.py`
tem SHA-256 `b34bd0677feb9d4453477d7503dc19beffcaf6cc8648acb85be56113b7578e24`;
a proposta
`docs/governance/migrations/migration-history-divergence-remediation-proposal-v3.json`
tem SHA-256 `076d04ed179c5128c4707c07cacd8240896101a9bea62e328d2d0569900cd10e`;
e seu schema
`docs/governance/migrations/migration-history-divergence-remediation-proposal-v3.schema.json`
tem SHA-256 `88f7972780f07c7071bb4e4292e1f21c258fff47daf2ab207fc709ff34631b38`.
A matriz nova passou `87/87`, a focal estável passou `138/138`, e o verificador
terminou fail-closed com exit `8` e
`RESULT=BLOCKED_MIGRATION_EPOCH_V3:PENDING_SEPARATE_EVIDENCE`. O estado é
`RECOMMENDATION_ONLY_NOT_APPROVED`; isso comprova somente o desenho offline e
não autoriza evidência viva, cutover, migration ou runtime.

No batch offline depois integrado pela PR #351, a correção de precedência classifica
`TimeoutError` e `socket.timeout` como `DEADLINE_EXCEEDED` antes de `OSError`
genérico em cada fronteira de rede. O batch integrado tem runner SHA-256
`2e2208bfbca1214c0cec024c58716eeac7c05789c33ce36d812c0265c3810809`, teste
SHA-256 `d7161cd7dd7c63935c07431193b0d916222e5341088edbdc6d4ef85ad3063689` e
`102/102` testes verdes. Nenhum probe vivo foi executado. Os hashes da PR #350
`0ac585b86dd1c96446622e9a46bccda8a1e43eb0bceb0dcc19226892cb88d191` e
`70334dfc33505ea0b5ddb85a6406672fe0d9154e105134da164c773978459489`
permanecem evidência histórica e não são substituídos.

O contrato D3 fail-closed integrado usa
`backend/app/agent/private_checkpoint.py`, SHA-256
`098d7186d59b2be9c231e3ca41e328b69901d4bc3e3f9b09651b902c07768f33`,
`backend/app/agent/context.py`, SHA-256
`b8d9ccea0041a81021cb2b4cf8edcbd8af0457ebf4401b021bd974edd29eea7d`, e
`backend/tests/test_agent_private_checkpoint_contract.py`, SHA-256
`2f91523e6a5daacd7c3ac08b933c7d9f857c3eec2a72b9f962c09c98d39f3c8b`.
A seleção `tests/test_agent*.py` terminou em `292 passed, 7 skipped`, com duas
advertências preexistentes. A classificação é `CONTRATO OFFLINE INTEGRADO E INATIVO`: não
há saver, migration ou wiring, e o LangGraph continua stateless.

A PR #351 foi integrada no merge
`bc97dd4e6f2fc9024e85afe8d611708699c8983a`. Os `7/7` checks pós-merge
concluíram com `SUCCESS`. A Vercel registrou o deployment automático do frontend
Production `6187006353`, status `17583083885`, com `SUCCESS`. Essa metadata prova
somente o frontend e não prova backend, banco ou runtime. A preparação D3 de
estado efêmero desta branch permanece candidata offline, sem saver, migration
ou retomada, e não integra a evidência pós-merge da PR #351.

A PR #352, HEAD `c5b2b4c775592641b308de6b2ac3cd069f34dcb3`, integrou essa
preparação no merge `6c807717010a41edf3bfd3d1b2405c2f3527a696`, cuja árvore é
idêntica à do HEAD da PR. Os `7/7` workflows pós-merge concluíram com
`SUCCESS`: Backend Tests `33428905043`, Canonical Schema Derivation
`33428905057`, E2E Critical `33428905042`, Environment Attestation PG17
`33428905234`, Frontend CI `33428905212`, RLS Integration `33428905114` e
Tooling Static Checks `33428905041`. A Vercel registrou o deployment automático
do frontend Production `6187746800`, status `17584957483`, com `SUCCESS`, em
`2026-08-31T19:09:09Z`. Essa metadata prova somente o frontend e não prova
saúde funcional, backend, banco, saver, migration, memória ativa, deploy do
backend, flag ou runtime. O estado permanece `PREPARAÇÃO D3 INTEGRADA E
INATIVA`.

Sobre esse merge, o commit técnico local
`14b3d7ba15e88032cd53714008d36badd4578e80` congela exclusivamente offline o
contrato puro `AgentTurnIdentity` e `AgentEffectIntent`. A identidade vincula
`igreja_id`, conversa, mensagem inbound persistida, provedor Evolution e ID do
provedor exato; `claim_id` não participa. O `effect_id` deriva do turno, do
slot semântico versionado e de um ordinal estável, enquanto um digest separado
vincula o payload JSON canônico. O ordinal ainda exige um futuro plano
determinístico e persistido, e a validação recebe a identidade esperada de uma
fonte confiável.

Na branch local, o commit
`f82f76927ba8a6a265478ad7f21eae07b0d6504c` adiciona somente o adaptador
confiável de entrada, protegido por
`agent_trusted_inbound_identity_enabled=false` por padrão. O `Message.id` da
entrada persistida agora chega em `IngestionOutcome` nos caminhos novo e
duplicado. Antes de sessão, reserva, lease, runtime ou qualquer outro I/O, o
worker constrói a identidade com igreja, conversa, mensagem e ID Evolution
persistidos. Antes da primeira consulta, o runtime rederiva a identidade com
quatro entradas confiáveis e separadas: `igreja_id`, `conversation_id`, o UUID
inbound persistido de `Message.id` e o `provider_message_id` exato. Ele exige
igualdade integral dos quatro vínculos com a identidade construída pelo worker;
qualquer divergência aborta.
`claim_id` permanece requisito separado de recuperação, nunca entra no
`turn_id`; o caminho legacy é preservado somente com a flag desligada. O
estado do grafo continua recusando aliases de autoridade e não recebe essa
identidade.

O mesmo lote incorpora em
`7d1ed00d0add18162a89f3a9c39da6039e74017c` o contrato puro e inativo
`turn_execution`, originalmente revisado em
`576de558983622146a91417c65a85a2a321f585b`. Ele define plano canônico,
ordem versionada de efeitos, escopo opaco por tenant e conversa, recibos
estruturais, máquina pura da futura outbox de resposta e chave atual `v2`.
Nada disso persiste plano ou recibo, autentica uma store, serializa turnos,
garante FIFO ou cria atomicidade entre commit de domínio e outbox. `ACCEPTED`
significa somente aceite do transporte; `AMBIGUOUS` é terminal. Evidência
legacy `v1` ou `v0` não é derivada nem autenticada pelo contrato.

Os pins atuais são `backend/app/agent/turn_identity.py`, SHA-256
`5be323d7fafa4a51d5c954749c8d2d5991e33313e269ee0a3b63bdfc9fb3923d`;
`backend/tests/test_agent_turn_identity.py`, SHA-256
`4072b76688552b6f870e89876426d3c608b34a362ec895315d733691dff101c5`;
`backend/app/agent/turn_execution.py`, SHA-256
`72a53515a835bac528280223e22f76a33f8606b5ce979dae11773d10ea6a1b2b`; e
`backend/tests/test_agent_turn_execution.py`, SHA-256
`7e22814f1715b7bdfc7f83431bf4e15cdf6d8f7d13d0d8d3afaa6811e95e0b2d`.
O wiring passou em `245/245` e em `401 passed, 7 skipped` na seleção
`tests/test_agent*.py`; o contrato de execução passou em `86/86`, na revisão
independente `190/190` e em `462 passed, 7 skipped` na mesma seleção. As duas
revisões terminaram `GO`, sem P0, P1 ou P2. A evidência é local e pré-PR.

Na mesma branch, o commit técnico local
`abafdffdc8252fa6dff7c9d1975cb6c241141971` adiciona o adaptador puro e
replay-only `turn_plan_adapter`. Ele projeta a saída fechada do grafo em um
plano determinístico, mas não oferece status `EXECUTABLE`, callback injetável
ou consumer de runtime. Plano armazenado ausente ou qualquer receipt terminal
ausente produz `FIRST_EXECUTION_UNSUPPORTED` e bloqueia a primeira execução.
Somente um plano armazenado estruturalmente exato e vinculado ao digest, junto
de um receipt terminal válido para cada efeito, retorna `REPLAY_TERMINAL`; esse
resultado não concede execução, persistência, transporte, retry ou mutação de
domínio. `tool_calls` permanecem bloqueados. A oferta do relatório é aceita
somente quando finita, não negativa e exata em centavos, sendo vinculada como
inteiro `oferta_centavos`.

Os novos pins são `backend/app/agent/turn_plan_adapter.py`, SHA-256
`c81dafec100734ee9a219d8c99a636636b6317b94c93c87cb89ba0f9af581002`;
`backend/tests/test_agent_turn_plan_adapter.py`, SHA-256
`328f3a2870fab8ea38f1901a02e640bec2f5bc9457c3d5261f350a45ef560d5e`.
A revisão integrada passou em `291/291`; a seleção `tests/test_agent*.py`
terminou em `625 passed, 7 skipped`. A revisão concluiu `GO`, com P0, P1 e P2
iguais a zero. Essa evidência é local e pré-PR.

O lote ampliado permanece exclusivamente offline. O wiring de identidade
continua inativo porque a flag fica desligada por padrão e nenhuma ativação
ocorreu. `turn_execution` e `turn_plan_adapter` não possuem consumer de runtime
e executam zero I/O. Não existem saver, checkpoint durável, migration, plano ou
receipt persistido, FIFO, bloqueio serial real, atomicidade entre efeitos,
retomada, primeira execução ou memória ativa. Estado: `LOTE D3 OFFLINE
AMPLIADO LOCALMENTE / REPLAY-ONLY / FLAG DEFAULT FALSE / CANDIDATO NÃO
INTEGRADO NO MAIN / RUNTIME NÃO ATIVADO`.

O commit técnico local `4988de11566f8f0675256b9958ca242e5a009fa3`
integra ao lote o snapshot agregado `cell-report/v2`. Ele preserva apenas os
totais de presentes, visitantes e decisões; `presencas`, `visitantes` e
`records` individuais precisam permanecer arrays vazios, portanto o snapshot
não inventa pessoas nem transforma totais em fatos individuais. Os pins são
`backend/app/domain/cell_report_snapshot.py`, SHA-256
`19adb057c9f002776e3ad99d87de636de4975f5cf602a8fb06d2d8401a7d2aaa`, e
`backend/tests/test_cell_report_snapshot.py`, SHA-256
`08464997fa55cb9319d095f672fe0d78693280104d8b4247390e3e75d80ad7f9`.

O commit técnico local `452aa6ff591b80dcbd3da90f1e5c18367cffd72b`
integra o workflow puro de coleta, revisão e confirmação do relatório. A
confirmação literal apenas correlaciona a revisão corrente; o workflow não
autentica o ator, não concede autoridade e não executa efeito. O estado
`COMMITTED` projeta uma comprovação externa futura, sem gravar ou enviar nada.
Os pins são `backend/app/domain/cell_report_workflow.py`, SHA-256
`87ec5691774eab1b2711fea0f07f9f311ddacf7f321fe36646730742b02569b5`, e
`backend/tests/test_cell_report_workflow.py`, SHA-256
`a5a542f6b0192964a0bdd238b8306a1b8ca162be4ec6e2f824773020300508c6`.

O hardening posterior foi composto pelos commits
`f40d39efeb847b84b30e495ba78f6d218437e8ad`,
`a84bb7d5f00bae6bb472d02c4a33d14442a294a2`,
`ef4aa00797e11bbbaa0189faa2c299bf9ace8a5b`,
`9ea14000065117bda4aa8e7627e78c07dd5d1b2a` e
`45323a64b17cd9f1fa4d4a86f3a32d769f525660`, sem reescrever os freezes
anteriores. Os pins finais são adaptador SHA-256
`2d2adde74dd2bea21aa7a1a3a0e3551ebc62ab269885531162ffc0681e3c7629`,
teste do adaptador SHA-256
`380bf43ea70020ad30134ac56b1ff42823c3219c1950ee3c46c508acdd3290b8`,
snapshot SHA-256
`95a9c4f5ea68b3027b42416d858c5cfc3eed858198bf38f8bab638c1b293a53f`,
teste do snapshot SHA-256
`21c9799aed4d79003c5b3d3018fa5c6c61ff11c6452409056309e5b74d3b76ee`,
workflow SHA-256
`3213bcc9949661bd3db56717492babfc7b9a9c0d79c20b8da9ddc039ab1b129d`
e teste do workflow SHA-256
`7887a930b8d2fbf7f508acae0d6b256927ab52534a726b2a54fec7224c897dd6`.

O hardening de paridade local centraliza `MAX_REPORT_COUNT=1_000_000` e o
limite E2 de oferta em `R$ 999.999,99`; builder e revalidação do snapshot
persistido usam os mesmos limites. O writer humano e o snapshot recusam zero
negativo; o writer também recusa `NaN`, infinito, booleano, string e mais de
duas casas decimais. Isso ainda é constante compartilhada mais validação
humana endurecida, não um serviço de aplicação compartilhado. Os pins
adicionais são
`backend/app/domain/cell_report_limits.py`, SHA-256
`cb0acd562ebd4e91f2f3170d59ff67cea3ac45f9b4a73f370b1c78522b330412`, e
`backend/tests/test_cell_report_limits.py`, SHA-256
`7f11003b18b0159815f54306002e87624045282d775de08d1ba47da1b6822e86`;
`backend/app/routers/cell_meetings.py`, SHA-256
`e72c1e8366a45ab487b38e1d04b110583b4825645daadaccf1957a04b913ddf5`; e
`backend/tests/test_cell_lider.py`, SHA-256
`07ffabd0260b573bad0fbd8ba572064d0acaaa3b361524dea06a35d8ac781b4d`.

Na revisão integrada final do HEAD
45323a64b17cd9f1fa4d4a86f3a32d769f525660, passaram 512 passed, 5 warnings;
633 passed, 7 skipped, 2 warnings; 398 passed, 18 warnings; e 34 passed
documentais. Links locais 89/89, matriz de pins e gates 13/13, py_compile,
secret scan e git diff --check ficaram verdes. O parecer foi GO, com P0, P1 e
P2 iguais a zero. A evidência é exclusivamente local e pré-PR; não prova
runtime, DEV, PROD, banco, deploy ou efeito vivo.

Ainda não existe bridge ou wiring entre `turn_plan_adapter`, workflow e
snapshot. `REPLAY_TERMINAL` não prova relatório persistido: o plano atual de
`report_capture` contém somente intake, auditorias e resposta, sem efeito de
gravação do relatório. Um adapter futuro, em código confiável, deverá derivar o
escopo vinculado ao tenant, mapear centavos e string sob o mesmo limite de
produto E2 do painel e marcar `COMMITTED` somente depois de um commit externo
atômico comprovado.

As duas fatias permanecem restritas ao lote local. Nenhum runtime ou worker foi
acionado; não houve acesso a banco, migration, rede, persistência, mensagem ou
qualquer efeito vivo. Estado: `FUNDAÇÃO OFFLINE DO RELATÓRIO DE CÉLULA
AMPLIADA LOCALMENTE / SNAPSHOT V2 AGREGADO / WORKFLOW PURO / CANDIDATO NÃO
INTEGRADO NO MAIN / EFEITOS VIVOS BLOQUEADOS`.

O gate histórico `REVIEW_AND_CI_OFFLINE_AGENT_FOUNDATION_BATCH_PR` foi consumido
pelo push, abertura, CI e Preview da PR #351. Ele não autorizou o merge
posterior, permanece somente como evidência histórica e não é um segundo gate
corrente.

O gate histórico `REVIEW_AND_CI_D3_EPHEMERAL_EFFECT_STATE_PR` foi consumido
pelo push, abertura, CI e Preview da PR #352. O merge e o deployment automático
do frontend Production foram autorizados separadamente; esse gate não os
autorizou. Após o consumo, ele permanece somente como evidência histórica e
não é um segundo gate corrente.

O gate anterior `REVIEW_AND_CI_D3_TURN_IDENTITY_OFFLINE_PR` foi substituído
localmente, sem consumo, pelo lote combinado. Não houve push, PR, CI ou Preview
sob esse gate, portanto ele não é evidência histórica de uma ação externa.

O gate anterior
`REVIEW_AND_CI_D3_TURN_EXECUTION_AND_TRUSTED_INBOUND_WIRING_OFFLINE_PR` foi
substituído localmente, sem consumo, pelo lote ampliado replay-only. Não houve
push, PR, CI ou Preview sob esse gate, portanto ele não é evidência histórica
de uma ação externa.

O gate anterior `REVIEW_AND_CI_D3_TURN_FOUNDATION_REPLAY_ONLY_OFFLINE_PR` foi
substituído localmente, sem consumo, pela fundação offline do relatório de
célula. Não houve push, PR, CI ou Preview sob esse gate, portanto ele não é
evidência histórica de uma ação externa.

A fatia offline posterior foi congelada no commit tecnico original
`c24b910bcd4bf4015eda14847e9695497b5b8ef6` e consolidada, sem alteracao da
arvore tecnica, no HEAD local
`bcabbae0cf96a9b6e2cd47e8ff041b5aeaffbc84`, sobre a reconciliacao
documental `e0cb280`. Ela acrescenta o envelope fechado
`cell-report-pending-proposal/v1` e o servico
`cell_report_application`. A proposta usa `relatorio_snapshot` apenas
enquanto o relatorio esta pendente, com bindings opacos de tenant, reuniao,
conversa e ator, expiracao maxima de 24 horas, no maximo 32 operacoes
estruturais e digest do estado-base. O JSONB nao guarda UUIDs brutos, mas os
hashes nao sao autenticadores e o conteudo privado nao pode ser logado.

O servico exige transacao tenant-scoped ja ativa e pertencente ao caller,
adquire locks em ordem canonica e revalida conversa oficial sem handoff,
reuniao passada e nao cancelada; novas propostas e materializacoes exigem
relatorio pendente, enquanto replay final exato e permitido para enviado;
celula, lider e Pessoa ativos, opt-out,
`sem_interesse`, exatamente um `AppUser` utilizavel e ao menos um papel
ministerial. Proposta e confirmacao exigem `AgentTurnIdentity` e
`AgentEffectIntent` com payload exato. A confirmacao literal corrente troca o
envelope por `cell-report/v2`, atualiza `celula_reuniao` e faz somente
`flush`. O caller continua responsavel por commit ou rollback.

O hardening final persiste o `submission_effect_id` original e o
`submission_payload_digest` separado. A dupla nao prova proveniencia,
autorizacao, primeira execucao nem unicidade global, e o historico limitado da
proposta nao substitui plano, receipt duravel autenticado ou outbox. Os limites
compartilhados fixam `MAX_CELL_REPORT_OBSERVATIONS_LENGTH=2_000` caracteres e
`MAX_CELL_REPORT_OBSERVATIONS_BYTES=8_000` bytes UTF-8. Fetch de rows, fetch
de scalars e `flush` sanitizam `SQLAlchemyError` sem encadear a excecao
privada.

Nao existe caller no grafo, worker, webhook, router humano ou
`turn_plan_adapter`; a primeira execucao do agente e `tool_calls` continuam
bloqueados. O router humano ainda nao compartilha o servico nem o lock. Papel,
lideranca e opt-out nao substituem o consentimento `tarefas_operacionais`: a
fonte juridica e do controlador segue nao aprovada, o ledger D2B2a permanece
sem caller e sem aplicacao, e esta fatia nao le nem grava consentimento. Nao
houve migration, banco compartilhado, DEV, PROD, rede, mensagem ou efeito vivo.

Pins integrais do HEAD: `backend/app/domain/cell_report_limits.py`
`8c7a81ee9a8f0a14125c5918aba6f149582e6392d129c9b37744ac3a1d12bf42`;
`backend/app/domain/cell_report_pending_proposal.py`
`53769d79835803dc8c294928047d2d8766de491e17aecc9d57edb239f06c4056`;
`backend/app/domain/cell_report_snapshot.py`
`24e93a2b6e8cbe92a849ba3ccc081ff6fbd092a347a605494464fddc6aa3bc51`;
`backend/app/domain/cell_report_workflow.py`
`da16186dc28f18261967e10800c5f300dae2b11552ed6dff389cbe9d7a3bf877`;
`backend/app/routers/cell_meetings.py`
`59de2e7b9d12a4c9d36e16edf28c8a74ea590244b778dae8da44ac8f47f49067`;
`backend/app/services/cell_report_application.py`
`7dc9d0d9cc7bf09c3d8963e956bd60500038004c5e8d882c7d37dd30c3a3389b`;
`backend/tests/test_cell_health_service.py`
`19fbe602a4943fa76a3583e1e9e61a3e7979169caba5de15e157072262c8be69`;
`backend/tests/test_cell_lider.py`
`a0265297ec29895399bf4ea0bfac37f554ec935ae5fd6e157c4f348bd69cc6a5`;
`backend/tests/test_cell_report_application.py`
`30139bffee6be9c00f7068255c6150ee8507506a14ccb9649bebadbf39dc136e`;
`backend/tests/test_cell_report_limits.py`
`c1d4c2b89e3863e10fed7a3e84eb27b2cece6447c8a63e05237d24fff26196aa`;
`backend/tests/test_cell_report_pending_proposal.py`
`299b23c0795d9a1e70ac0e6ed46b4124c64a94e567f2e8a6d03732fde6165a3c`;
`backend/tests/test_cell_report_snapshot.py`
`7cbd65505095c7821bbb8328da9b6d22760fce0544ab80861ca765c82bbd87fb`;
`backend/tests/test_cell_report_workflow.py`
`704f036d1fd5632c7c33dd5c446e80e6f303fa712adacee892dde822b83f53a9`;
e `backend/tests/test_reports.py`
`fb511601265dfa374a7d9fbec35f913a7e4bdbde615ce82c1c7996e2d51177d2`.

A focal passou em `292 passed`; `tests/test_agent*.py` terminou em
`633 passed, 7 skipped, 2 warnings`; e
`tests/test_cell*.py tests/test_reports.py` terminou em
`730 passed, 18 skipped, 35 warnings`. A suite ampla do backend, com
`migration_history` e Redis fora da selecao, chegou a
`4601 passed, 325 skipped, 499 deselected, 66 warnings`, sem classificacao
verde por uma assercao documental do pin anterior e duas falhas baseline de
modo group-writable `0664` no checkout `/tmp`. Apos esta reconciliacao, a
matriz documental passou em `34 passed`. A revisao independente repetiu
`729 passed` e `1363 passed, 25 skipped` e concluiu `GO`, com P0,
P1 e P2 iguais a zero. A evidencia e local e pre-PR.

Estado: `FRONTEIRA TRANSACIONAL OFFLINE DO RELATORIO AMPLIADA LOCALMENTE /
PROPOSTA PENDENTE FECHADA / FLUSH SEM COMMIT / CANDIDATO NAO INTEGRADO NO MAIN
/ RUNTIME E EFEITOS VIVOS BLOQUEADOS`.

O gate anterior `REVIEW_AND_CI_D3_CELL_REPORT_OFFLINE_FOUNDATION_PR` foi
substituido localmente, sem consumo, pela fatia offline do servico de aplicacao
do relatorio. Nao houve push, PR, CI ou Preview sob esse gate, portanto ele nao
e evidencia historica de uma acao externa.

A composicao transacional posterior esta no HEAD local
`dac3a14cdd2bf857f84609518dd96050e203b4b3`. A reserva V2 foi criada no
commit tecnico original `4d08e783c2de1bb20dfeb29ffb8ee6a43c7a444f` e
integrada como `d6ee2323d658a91bb92724aaa13adea7222538b4`; a UoW veio de
`58b77a84e38ba7be4d3968d32834ef1b415b3a89` e foi integrada como
`17305af54e52aea74948e275ad68fae50427ae67`; os locks dos writers vieram
de `83b4810008f37250b9a9d00f9c9a83f04a3d0399` e foram integrados como
`b6a763cbcab41a78815a7777f2c9b682a6af1ddb`. O commit
`dac3a14cdd2bf857f84609518dd96050e203b4b3` reconciliou nos testes o
`expected_replayed` explicito. A revisao tecnica consolidada posterior
concluiu `GO`; a evidencia exata esta registrada abaixo.

A reserva `AgentOutboundReplyReservationV2` e um contrato puro derivado
somente de `AgentTurnIdentity`, antes de payload ou plano. Ela fixa o slot
`OUTBOUND_REPLY` ordinal zero e produz a mesma chave de compatibilidade V2 do
efeito posterior, sem usar `claim_id`. O valor nao reserva linha, nao prova
outbox, autenticacao, idempotencia global, aceite do provedor ou envio.
Compatibilidade V1/V0 continua somente como drain: a UoW pode vincular a chave
exata observada numa linha legacy ja bloqueada, sem deriva-la nem promove-la.

Os seis writers humanos `edit_meeting`, `set_real_attendance`,
`register_visitor`, `add_record`, `save_report` e `submit_report`
passam pela mesma boundary sanitizada e serializam a reuniao, a celula e o
acesso do lider com locks tenant-bound. Um envelope pendente reconhecido pode
ser invalidado por takeover humano explicito; snapshot pendente desconhecido
falha fechado. O reconhecedor puro do snapshot humano legacy exige shape
completo, metadados coerentes e UUIDs canonicos nao nulos. Assim, um submit
humano concorrente vira `REPORT_CONFLICT` para o agente, enquanto shape
malformado continua `DATA_INTEGRITY`. Os writers web continuam separados do
servico de aplicacao do agente; compartilhar locks nao equivale a compartilhar
servico.

A `cell_report_turn_uow` exige uma transacao tenant-scoped externa, um plano
fechado com `TOOL_CALL`, `AUDIT_EVENT` e `OUTBOUND_REPLY`, e uma
`Message` de reply pre-reservada. Ela bloqueia a mensagem, valida a chave V2
antes do banco ou, para V1/V0, a evidencia exata depois do lock; exige
`expected_replayed` booleano no servico de confirmacao; e requer concordancia
entre relatorio, audit sem conteudo e reply em replay. No caminho novo, agrupa o
snapshot, um `AgentConversationLog` sem texto pastoral e a `Message` com
estado `ia_pendente` na transacao do caller. Todo sucesso da UoW retorna
`requires_caller_commit=true`, inclusive replay observado na transacao atual.
A boundary faz somente `flush`: nao inicia, confirma ou reverte transacao, nao
envia mensagem e nao chama runtime, worker, grafo ou rede.

Esta fatia especifica fecha parte do staging atomico, mas nao cria outbox
generica, receipt global autenticado ou comprovante pos-commit. Nao existe
caller; consentimento `tarefas_operacionais`, `AgentConfig`, proveniencia
operacional, commit, send, primeira execucao generica pelo
`turn_plan_adapter`, migration, drain V1/V0 e efeitos vivos continuam
bloqueados. Nao houve banco compartilhado, DEV, PROD, rede, mensagem ou
deployment.

Pins SHA-256 integrais do HEAD:
`backend/app/agent/turn_execution.py`
`b729c3b25024cff41aa42b39aecd9d30712bf229c8f635c40fbd306cf52ac351`;
`backend/app/agent/turn_identity.py`
`59848ebee37c9be0c9488420c4634e1b323f611c22627328c8c4dd73d5e69998`;
`backend/app/domain/cell_report_legacy_snapshot.py`
`22dc8e5992f5661a5c110d6a4cc1ebedf7babfabfd45a56490b484de4695f869`;
`backend/app/routers/cell_meetings.py`
`9a04c1589f64179e7b60a8b18755a40ee21035a8e955f8ff5238c4c5eba3a18e`;
`backend/app/services/cell_report_application.py`
`0c8ddd4040b83e09fd496eeea3594c68309f0446b97b2466d5f32204babcc347`;
`backend/app/services/cell_report_turn_uow.py`
`1bdebab8fb70b081781fa0ace6152b1d83cdeb9161a125172b16ca5929795399`;
`backend/tests/test_agent_turn_execution.py`
`911cc7743b073c78b6d5eaffc29eee1171bdf25d1526bd94a32542302c92420e`;
`backend/tests/test_agent_turn_identity.py`
`6d60a2668810bf8c62e23658d95c54b886079e4e7ecf120f349e989de710e1cf`;
`backend/tests/test_cell_lider.py`
`0732667504127fb4bcdc163187b9b137e77f645e81a743413d8a7c4332f1ee0e`;
`backend/tests/test_cell_report_application.py`
`278e3d506ca5c0853b957529013991bb676320381727f33183afcadc7768f430`;
`backend/tests/test_cell_report_legacy_snapshot.py`
`57586f81accd27145d5877ce91fa9d98f82f29b1ee4f73828768cfe93134c354`;
e `backend/tests/test_cell_report_turn_uow.py`
`5ce3d8b37f672adfeaf04839183d43f7f67b51f5cf6d81b37b663bf9c2128db9`.

A revisao tecnica integrada no HEAD
`dac3a14cdd2bf857f84609518dd96050e203b4b3` concluiu `GO`, com P0, P1 e
P2 iguais a zero. A focal integrada terminou em `682 passed, 5 warnings`;
`tests/test_agent*.py` terminou em `649 passed, 7 skipped, 2 warnings`; e
`tests/test_cell*.py tests/test_reports.py` terminou em
`960 passed, 18 skipped, 35 warnings`. Tambem passaram 200 vetores da reserva
V2 e 8 casos de corrupcao legacy. As validacoes de AST e `git diff --check`
para `d37d528..dac3a14` ficaram verdes. A evidencia e local e pre-PR. Ela
confirma ainda a ausencia de caller em runtime, worker ou webhook, de migration,
rede ou send e de `begin`, `commit` ou `rollback` na UoW.

Estado: `STAGING TRANSACIONAL OFFLINE COMPOSTO E REVISADO LOCALMENTE / RESERVA
V2 CLAIM-INDEPENDENT / WRITERS SERIALIZADOS / FLUSH SEM COMMIT / GO TECNICO
P0=P1=P2=0 / SEM CALLER / RUNTIME E EFEITOS VIVOS BLOQUEADOS`.

O gate anterior
`REVIEW_AND_CI_CELL_REPORT_APPLICATION_SERVICE_OFFLINE_PR` foi substituido
localmente, sem consumo, pelo lote de staging transacional. Nao houve push, PR,
CI ou Preview sob esse gate, portanto ele nao e evidencia historica de uma acao
externa.

**Gate anterior consumido:**
O gate `REVIEW_AND_CI_CELL_REPORT_TRANSACTIONAL_STAGING_OFFLINE_PR` exigia
autorizacao humana posterior e separada que nomeie push, abertura da PR e
GitHub CI e aceite o Vercel Preview automatico. O gate cobre somente revisao e
CI do lote offline de staging transacional; nao autoriza merge, Vercel
Production, flag-on, caller, `AgentConfig`, primeira execucao do agente,
runtime, worker. Ele foi consumido pela autorizacao humana nominal da rodada
de PR. Na PR #354, o head
tecnico `69f9eecdfb95691b4633a42ef597452f63e82e48` contra `main`
`6c807717010a41edf3bfd3d1b2405c2f3527a696` permaneceu aberto,
`MERGEABLE/CLEAN`. Os sete workflows GitHub concluiram com `SUCCESS`: Backend
Tests `33456753518`, Canonical Schema Derivation `33456753672`, E2E Critical
`33456753444`, Environment Attestation PG17 `33456753406`, Frontend CI
`33456753394`, RLS Integration `33456753452` e Tooling Static Checks
`33456753430`. O Vercel Preview automatico do frontend, deployment
`6192384421`, status `17596918017`, tambem concluiu com `success`. Preview nao
e Vercel Production e esta evidencia nao prova runtime, banco ou efeito vivo.

**Próximo gate único daquele recorte histórico (consumido no merge da PR #354):**
O nome não constitui autorização já concedida. Naquele recorte histórico,
`REVIEW_AND_MERGE_CELL_REPORT_TRANSACTIONAL_STAGING_PR` era o sucessor fechado.
Posteriormente, ele foi consumido por autorização humana nominal exclusivamente
para o merge da PR #354, que ocorreu via squash no commit
`c24ea748ab5e484958590af481f08f1c2b185597` (`mergedAt=2026-09-01T02:27:21Z`), e
o deployment Vercel Production automático decorrente (`6193336784`). O deployment
Vercel Production automático decorrente prova somente o frontend. Seus limites
operacionais continuaram fechados: não autorizou caller, runtime, worker,
consentimento, banco, migration, commit, send, drain V1/V0,
receipt global, saver, probe vivo, DEV, PROD, logs, SQL, DML, outra rede,
deploy adicional, mensagem, tool call, flag ou qualquer efeito vivo, e o merge da
PR #354 não autorizou, alterou ou comprovou o estado vivo de `AgentConfig.ativo`.

Nenhum proximo passo funcional foi nomeado nesta sessao; a sequencia de PRs
D3/staging transacional (#337 a #354) nao define explicitamente a proxima
fatia, e essa decisao cabe ao dono do projeto. Separadamente, a auditoria de
reconciliacao de historico de migrations (contrato
`2026-08-28-migration-history-reconciliation-contract.md`) permanece com seu
proprio gate pendente, nao afetado por este merge: autorizacao para
investigar a causa do `exit 7` nas duas tentativas de preflight DEV.

### Fundação M1 do catálogo evolutivo de migrations (PR #361, 2026-09-03)

As entregas M1A-M1E e M1I foram integradas em `main` pela PR #361 via merge
commit `8aacf98d9abbfd945226afb652ef38efa2fc6cfa` (parent 1 `e5d07e60`, parent 2
`03d1cd2a`), com a árvore do merge coincidindo exatamente com a de `03d1cd2a`.
Durante a fase aberta observou-se `mergeStateStatus=CLEAN` e após o merge a API
retornou `mergeStateStatus=UNKNOWN`. Os 10 checks na PR e os oito workflows pós-merge
no GitHub Actions em `main` concluíram com sucesso (100% verde). O Vercel
Production automático concluiu com sucesso (`Ready`) e aplica-se exclusivamente ao
frontend Next.js. CI verde e deployment frontend não provam migration, banco de dados,
backend, DEV, PROD, flags ou runtime, e o merge não autorizou nem alterou a flag
`AgentConfig.ativo`.

O preflight e fetch pós-merge sob o gate
`OWNER_AUTHORIZE_REMOTE_READ_FETCH_M1J_POSTMERGE_BASE` foi inicialmente
bloqueado pela política shell do executor e concluído pelo supervisor Codex, que
atualizou `origin/main` localmente de `e5d07e60` para `8aacf98d` sem checkout e
sem alterar o working tree.

O gate `OWNER_AUTHORIZE_CREATE_WORKTREE_AND_EDIT_M1J_R2_CANONICAL_RECONCILIATION`
foi consumido com a criação da worktree `m1j-postmerge-reconciliation-v2` sobre
`8aacf98d` pelo supervisor Codex, e a edição exclusiva dos seis documentos
autorizados pelo executor Antigravity, sem commit, rede, banco, migration,
deploy ou efeito operacional, mantendo a worktree `migration-catalog-head-v1`
intacta.

O gate de commit `OWNER_AUTHORIZE_COMMIT_M1J_R2_CANONICAL_RECONCILIATION` não foi
consumido e foi substituído pela revisão corretiva R3.

O gate `OWNER_AUTHORIZE_EDIT_M1J_R3_CORRECT_CANONICAL_DRIFT` foi consumido para a
correção documental R3.

O gate de commit `OWNER_AUTHORIZE_COMMIT_M1J_R3_CANONICAL_RECONCILIATION` foi
proposto, não consumido e substituído após a revisão do Codex detectar
divergência entre os documentos canônicos e o teste.

O gate `OWNER_AUTHORIZE_EDIT_M1J_R4_DOC_TEST_CANONICAL_RECONCILIATION` foi
consumido para a correção documental ampliada e do teste.

O gate de commit `OWNER_AUTHORIZE_COMMIT_M1J_R4_CANONICAL_RECONCILIATION` foi
proposto, não consumido e substituído após duas falhas determinísticas
encontradas pelo Codex na execução do teste documental.

O gate `OWNER_AUTHORIZE_EDIT_M1J_R5_FINAL_DOC_TEST_ALIGNMENT` foi consumido
exclusivamente para esta correção final de alinhamento entre documentos e testes.

O gate `OWNER_AUTHORIZE_COMMIT_M1J_R5_CANONICAL_RECONCILIATION` foi consumido
para o commit local `2218049902635239280af141980a30c3c3477c4c`, filho direto
de `8aacf98d`, contendo exatamente os 15 arquivos autorizados. O gate
`OWNER_AUTHORIZE_REMOTE_READ_PREFLIGHT_M1J_R5_CANONICAL_RECONCILIATION`
confirmou `main` remoto em `8aacf98d` e a ausência da branch remota. Em seguida,
`OWNER_AUTHORIZE_PUSH_AND_PR_M1J_R5_CANONICAL_RECONCILIATION` autorizou o push
sem force e a abertura da PR #363; seus dez checks concluíram com sucesso e o
deployment da PR foi corretamente classificado como Preview (`6251176874`).

O gate `OWNER_AUTHORIZE_MERGE_PR_363_M1J_R5_CANONICAL_RECONCILIATION` foi
consumido para o merge por merge commit
`c2fb16ad9a6b028c317c56a0b02c4362ae903e26`, em
`2026-09-03T19:28:24Z`, com parents `8aacf98d` e `2218049`. Os nove
check-runs pós-merge, incluindo `public-health`, foram revalidados com sucesso
pelo supervisor nesta missão. A evidência GitHub/Vercel revalidada classificou
o deployment automático `6251268132` como Production
com `state=success`, prova exclusiva do frontend Next.js. Ela não comprova
backend, banco, migration, ambientes Supabase, flags ou runtime.

O gate `OWNER_AUTHORIZE_REMOTE_READ_FETCH_M1J_R5_POSTMERGE_STATE` avançou
somente `refs/remotes/origin/main` para `c2fb16ad`, confirmou os parents e a
igualdade entre as árvores de `c2fb16ad` e `2218049`, sem mover branch local ou
alterar o working tree. M1J está encerrada; `8aacf98d` permanece base histórica.

Os gates da PR #354 são estritamente históricos e já consumidos.
`operational_authorization=false` e `next_stage_authorized=false` continuam estritos.
A política de permissões sucessora foi implementada e comprovada offline pelo
snapshot privado do SHA exato descrito em
[`2026-09-03-trusted-repository-snapshot-policy.md`](../decisions/2026-09-03-trusted-repository-snapshot-policy.md),
sem alterar o checkout compartilhado.

O único estágio sucessor é
`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`, limitado
à implementação e aos testes offline/PG17 descartáveis do executor de
identidade e captura. Este registro não declara consumo e não autoriza
credencial, rede, banco compartilhado, DEV, PROD, migration ou cutover.

## Paralelismo seguro

Auditorias somente leitura podem ocorrer em sessões separadas. Migrations,
mudanças de identidade, flags, canários, deploys e merges permanecem seriais e
exigem preflight vivo no momento da ação.
