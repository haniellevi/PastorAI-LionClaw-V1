# PastorAI / Igreja 12: registro central de missões pós-V1

Atualizado em 2026-08-28 (America/Sao_Paulo) com D2B2a, D2B2b1, D2B2b3A e o
`bootstrap-ledger` integrados e inativos, e o template D2B2b2 ainda não
aprovado. A D2B2b3A existe
somente como superfície draft-only do Console Master. A V1 permanece `V1_ENCERRADA`, mas a visão
integral WhatsApp-first ainda não está concluída. Este documento não altera a tag
`v1.0.0`, não autoriza novo canário, rollout amplo ou abertura de gates de
produção.

## Baseline obrigatório

- último SHA do backend em produção preservado em evidência versionada anterior:
  `c525d6a3897a12c6c287f9fc79a88b32b34cd452`. O relato operacional do canário
  ativo não contém um artefato versionado que permita reconstituir o SHA exato
  servido durante a janela; ele deve ser revalidado antes de qualquer rollout;
- frontend Vercel `pastorai-frontend-prod`, último estado preservado em
  evidência versionada anterior e não revalidado nesta atualização: deployment
  `dpl_Dycx4epdibk5xtW3svVerJT2cH7K`, `READY`, target `production`, SHA
  `cba0fdf9c6eb815e15fa5a1502499c5b0d332732`;
- Supabase PROD: `pffafnchtxbimpwyaczq`, último estado preservado em evidência
  versionada anterior `ACTIVE_HEALTHY`, não revalidado nesta atualização;
- Clerk: instância PROD preservada em evidência versionada anterior por
  prefixos `sk_live_` e `pk_live_`, não revalidada nesta atualização, issuer
  `https://clerk.igreja12.com.br` e JWKS
  `https://clerk.igreja12.com.br/.well-known/jwks.json`;
- ao final do canário, o operador confirmou `AgentConfig.ativo=false` e as
  flags externas restauradas para `ALLOW_REAL_SENDS=false`,
  `ASAAS_BILLING_ENABLED=false`, `BREVO_SEND_MODE=off` e
  `BROADCAST_ASYNC_ENABLED=false`. Este é um relato operacional, não uma
  leitura atual de produção feita por esta atualização documental;
- baseline do preflight PROD anterior, preservada como evidência histórica:
  `15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`. Esse SHA não é tratado como
  ponteiro móvel de `origin/main`. A implementação D2B2b3A veio do merge #320
  `947d891c2ea278b7a3231fecd9ca1c90cfe29a1f`; merge em `main` não comprova
  backend ou banco, por isso o estado versionado e o estado operacional são
  registrados separadamente;
- base versionada desta reconciliação pós-merge:
  `3a5789c784017ab15a43e28c4270d25af8618359`, merge da PR #323. Ela prova o
  código integrado e as evidências de CI associadas, sem provar bootstrap,
  migration, backend implantado, banco ou runtime compartilhado.

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

**Próximo gate único:** `SEPARATE_READ_ONLY_ENVIRONMENT_ATTESTATION`, em missão e autorização próprias,
somente leitura.
Ele não autoriza DML, reconciliação de ledger, corte de época, runner,
`bootstrap-ledger`, `harden-ledger`, `status`, `apply`, migration, backfill,
deploy, flag ou runtime. Universidade da Vida e Capacitação Destino permanecem
fora.

## Paralelismo seguro

Auditorias somente leitura podem ocorrer em sessões separadas. Migrations,
mudanças de identidade, flags, canários, deploys e merges permanecem seriais e
exigem preflight vivo no momento da ação.
