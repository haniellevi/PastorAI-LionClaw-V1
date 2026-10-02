# Paridade U25–U40: administração, gestão e console

Snapshot histórico de auditoria. Correções posteriores, QA e evidência de publicação estão no [registro de execução v3](../sprints/2026-10-01-ux-expressiva-v3.md). Os achados abaixo descrevem a árvore e o horário registrados nesta captura.

Captura de fonte: 2026-10-01T22:08:05+00:00. Revisão local, sem banco, produção, provedores, envio, cobrança ou leitura de caminhos protegidos.

- Base verificada: `origin/main` = `342b255e309f49b03177d31259d92bb87cc3c1f9`.
- Árvore candidata: `/home/raniel-linux/.codex/worktrees/ux-global-v2-final/PastorAi-1.0`, branch `codex/ux-global-v2-final`, HEAD `d46d765c0e2853a38b3f484140e281da643f73de` com alterações não commitadas.
- SHA256 do diff binário dos caminhos de apresentação inventariados: `d40579c92a5a4519a957a8c274ef6151f8363114eec33fd5d08443a2bbaa366b`.
- SHA256 do manifesto abaixo, incluindo contratos de apoio: `a524c5bfea7afe97b7ef3fc0a217554d266efca048cde7ea1ab526762e22e33e`.

A comparação não encontrou remoção de campo transacional ou ação real nas superfícies U25–U39. Há quatro grupos de conteúdo sob demanda, descritos adiante, e uma remoção deliberada de exemplos estáticos de UV/CD em U40. A ausência de integração de `PublicAgentProfile` no roteamento já existia na base e continua na candidata; não é possível apresentar esse componente como uma tela operacional entregue. A nova direção visual e motion v3 ainda depende do delta que o coordenador está preparando.

A confirmação é limitada à fonte comparada. A primeira rodada de navegador revelou seletores incorretos e um problema real no abandono da matriz; uma rodada integrada após o último build continua necessária. A comparação de fontes não fecha rollout global ou produção.

## Inventário antigo → atual

| Superfície | Dados, campos e ações reais preservados | Mudança de apresentação e limite |
|---|---|---|
| U25 Navegação da gestão | Os 11 destinos do menu, `perfil`, retorno ao app, sair, allowlist administrativa e gate `assinatura` owner-only continuam. Hashes e parâmetros são preservados. | Sidebar usa anchors nos destinos navegáveis. `AdminAppShell` e `ADMIN_NAV_SECTIONS` são iguais à base; os grupos atuais ainda são Gestão/Configurações/Sistema/Finanças, não a reorganização proposta no plano. |
| U26 Primeiros passos | Os seis IDs identidade/equipe/células/WhatsApp/agente/assinatura continuam vindos do mesmo checklist; cada ação mantém `resolveSetupNavAction`. Pendências seguem derivadas dos itens recebidos. | Lista semântica, estado opcional/configurado/pendente e atalhos com contexto. “Credencial configurada e ativa” foi corrigido para configuração da credencial, sem deduzir ativação do agente. |
| U27 Identidade | Nome da igreja somente leitura, logo salva, preview local, escolher/trocar/enviar/cancelar/remover logo, formatos PNG/JPG/WebP e limite 1 MB continuam. | Erro agora é alerta; remover exige confirmação com nome da igreja. Preview continua anterior ao salvamento. Nenhum crop ou redesenho foi acrescentado. |
| U28 Cadastro da igreja | Endereço institucional e horários dos cultos, dois campos até 400 caracteres, capability versão 1, GET/PUT, cancelamento e escopo da igreja continuam. | Somente estilo local e leitura dos campos. Falha mantém os valores; nenhum dado novo foi acrescentado ao contrato. |
| U29 Pessoas com acesso | Pessoa, e-mail, papéis acumulados e status da conta; convite de pessoa existente/nova; editar papéis, reenviar e revogar acesso permanecem. Travas de conta já vinculada, papel derivado, último admin e usuário atual permanecem. | Nome da seção distingue conta de cadastro da Pessoa. Formulário continua aberto pela ação Dar acesso ao painel, sem convite automático. Tabela mobile conserva colunas. |
| U30 Permissões | Sete responsabilidades editáveis e 12 destinos operacionais; administrador implícito, Hoje garantido e áreas centrais restritas. GET/PUT, salvar e descartar mantêm a mesma matriz. | Desktop semântico e mobile por responsabilidade usam o mesmo rascunho. Delta e guard de saída são novos. Cancelar hash/Back deve manter a edição; a primeira rodada encontrou perda do rascunho, e o coordenador alterou o hook para impedir publicação da rota antes do guard. O E2E negativo foi mantido para a repetição. O label `minha-celula` ainda cai no nome técnico já existente. |
| U31 Calendário e integrações | Estado/conta Google, seleção de calendário, revisão/importação/desconexão; destinatário com nome/telefone/ativo e incluir/editar/excluir continuam nos componentes originais. | Conta/importação e destinatários aparecem em seções próprias. Expandir/ler não conclui OAuth nem confirma evento. `CalendarConnectCard` e `AlertRecipientsCard` são byte a byte iguais à base. |
| U32 WhatsApp | Número, status, última sincronização, conectar/reconectar/desconectar, QR e geração numérica permanecem. Polling, relógio local de expiração e regeneração explícita permanecem. | O formulário de código numérico está sob demanda. Nenhuma nova validade foi inventada a partir da API; a validade local já existente não equivale a uma garantia adicional do provedor. Canal conectado continua distinto de assistente ativo. |
| U33 Assistente | Nome/tom/comportamento somente leitura na igreja, pedido ao master e histórico; provedor/modelo/chave protegida, revalidação; agendamento nome/frequência/gatilho/ação/ativo e editar/ativar/desativar continuam. | Estado confirmado do agente fica junto das abas. Falha de carregamento agora é indisponibilidade explícita também nos valores e no status interno. Criar/editar/ativar agendamento fica bloqueado sem configuração confirmada, inclusive no handler. Credencial e modelo não passam a ativar o agente. |
| U34 Assinatura | Plano, membros faturáveis/limite, próxima cobrança, taxa contratada e situação de setup, pendente/inadimplente/ativa, CPF/CNPJ quando exigido, catálogo e operações atuais de checkout/troca/retomada/recuperação continuam. | Visão geral e planos mantêm estados e valores; mobile muda disposição da tabela. Não foi adicionado histórico, cobrança, estimativa ou permissão para não-owner. |
| U35 Login da plataforma | E-mail, senha, login dedicado, validação de permissão de plataforma, falha/retry e sessão administrativa isolada continuam. | Layout compartilhado de acesso, mostrar senha e foco de erro são da fatia de acesso anterior. A correção do comentário `/auth/login` para `/admin/login` descreve o cliente já dedicado; `admin-api` e `admin-auth-context` são iguais à base desta comparação. |
| U36 Console | Igreja/status/plano/membros/pessoas e abertura do detalhe; atualizar/provisionar; Orquestrador/Jev/Planos/Auditoria/Sair. As seis métricas que já eram exibidas permanecem com as mesmas expressões e moedas. | Lista passa ao centro. Quatro contagens ficam visíveis e duas financeiras estão em disclosure nativo. Abrir igreja é um botão nativo com nome acessível que inclui o alvo. Campos de API que nunca eram exibidos, como `porPlano`, não viram novos indicadores. |
| U37 Detalhe da igreja | Dashboard conserva membros, pessoas, células, mensalidade, setup, custo IA, status da credencial e assinatura. Agente conserva nome/tom/comportamento/ativo, modelo padrão/restauração e pedidos; Admins conserva lista/dono/convidar/reenviar/remover/definir dono. Aprovar, editar nome/status/plano/taxa e excluir seguem presentes. | Cabeçalho mantém alvo/status/plano; edição repete o alvo; exclusão fica recolhida. No console, salvar a configuração pode aplicar o `ativo` explicitamente escolhido quando as travas permitem, como na base. A frase “salvar não ativa” se refere à credencial/modelo da igreja, não a esse formulário do master. |
| U38 Provisionamento e planos | Nome da igreja, plano, taxa personalizada e nome/e-mail do admin inicial; catálogo código/nome/limite/preço/ativo/ordem/em uso; editar, criar e excluir continuam. Exclusão de plano em uso permanece bloqueada; taxa padrão e mensalidade continuam distintas. | Resumo de criação e aviso igreja criada/convite falho são separados. O novo resumo mostra quatro valores e ainda não repete a taxa personalizada, que permanece no campo original. Incluir esse valor no resumo é melhoria revisável para v3, não remoção de contrato. |
| U39 Auditoria/Jev/Orquestrador | Auditoria mantém ação/alvo/autor/horário/detalhes. Jev mantém origem/status da chave, integração, gate de envios, modelo/timeout/DPA/igrejas/IDs inválidos, configuração e teste. Orquestrador mantém nome/tom/comportamento e salvar modelo. | CSS/seções/descritivos tornam os contextos mais legíveis. Teste Jev continua indisponível sem chave utilizável e gate retornado. A chave permanece entrada somente, sem exposição em status. Ler não ativa o runtime. |
| U40 UV/CD e governança | UV/CD continuam bloqueados e sem operação de turma/presença/certificado. Governança conserva quatro finalidades, oito campos de fatos/propostas, revisão, inicialização e salvar rascunho, inclusive conflito 409. | Exemplos ilustrativos de módulos/livros/assiduidade foram removidos; não eram dados reais ou ações implementadas. Retorno ao Hoje foi acrescentado. Governança permanece DRAFT_NOT_APPROVED e todos os gates de aprovação/catálogo/writer ficam no mesmo contrato. |

## Conteúdo sob demanda, sem perda de dado ou ação

| Origem | Destino atual | Conteúdo e efeito |
|---|---|---|
| MRR e custo de IA, antes junto das quatro contagens | `Financeiro da plataforma`, após a lista | MRR continua `brl(metrics.mrr)` com referência às igrejas ativas; custo continua `formatAiCostUsd(metrics.custoIaTotal)`, acumulado em USD. Expandir não chama endpoint novo. Fonte: [AdminConsole.tsx](/home/raniel-linux/.codex/worktrees/ux-global-v2-final/PastorAi-1.0/frontend/src/components/admin/AdminConsole.tsx:302). |
| Código de pareamento, antes aberto ao lado do QR | `Conectar com código numérico` | Número e Gerar código continuam os mesmos; apenas abrir não conecta. Fonte: [WhatsappScreen.tsx](/home/raniel-linux/.codex/worktrees/ux-global-v2-final/PastorAi-1.0/frontend/src/components/whatsapp/WhatsappScreen.tsx:580). |
| Exclusão, antes no formulário de edição aberto | `Exclusão da igreja` | Botão e confirmação destrutiva original continuam, com alvo da igreja. Fonte: [EditIgrejaModal.tsx](/home/raniel-linux/.codex/worktrees/ux-global-v2-final/PastorAi-1.0/frontend/src/components/admin/EditIgrejaModal.tsx:188). |
| Alterações da matriz e revisão de criação, antes sem resumo | `Revisar alterações de acesso` e `Conferir dados de criação` | São leituras derivadas dos campos/rascunhos existentes. Não representam status de aprovação ou persistência. A revisão de criação ainda deve repetir a taxa personalizada para ser completa. |

## Achados e correções rastreadas

1. **Estado não comprovado do assistente:** o resumo já tratava falha como indisponível, mas o cartão interno ainda dizia Desativado/Ainda não configurado usando defaults. Dois negativos falharam antes da correção. Na árvore inventariada, nome/tom/comportamento/status e operações de agendamento respeitam `configLoaded`. Os testes negativos também submetem a form por evento e comprovam que nenhum create/updateCron ocorre. Fonte: [AgenteScreen.tsx](/home/raniel-linux/.codex/worktrees/ux-global-v2-final/PastorAi-1.0/frontend/src/components/config/AgenteScreen.tsx:449).
2. **Abandono da matriz:** a primeira execução deixou `#setup` após cancelar. O coordenador diagnosticou que o render motivado por `popstate` podia ler o hash novo antes da confirmação e desmontar o guard. O hook foi ajustado por ele. O teste não foi relaxado: cancelar hash e Back deve preservar o valor editado, aceitar deve sair e nenhuma saída deve fazer PUT implícito. Ainda requer repetição no build atual.
3. **Ausência antiga do perfil público na navegação:** a busca de uso em componentes de produto encontrou somente a própria definição `PublicAgentProfile.tsx` tanto em 342b255 quanto na candidata. Os campos endereço/horários/células públicas existem no componente/cliente, mas não têm entrada de produto nessa árvore. Não registrar como tela entregue nem introduzir integração nesta auditoria.
4. **Consistência de apresentação pendente:** menu da gestão mantém os rótulos históricos e o label técnico `minha-celula` permanece na matriz; revisar na proposta v3 com os mesmos destinos. Nenhum campo, dado ou capacidade foi removido por esses textos.

## Evidência local e limite

- Node 24.19.0, instalado pelo lock do projeto pelo coordenador.
- Após a correção factual final, rodada direcionada de configuração/admin/perfil e APIs setup/WhatsApp/broadcast: **154 PASS em 19 arquivos**, início 2026-10-01 19:05:32 America/Sao_Paulo, duração 5,23s, exit0.
- `AgenteScreen.credential.test.ts`: **5 PASS** após negativos RED para falha de configuração/modelos; inclui positivo ativo=true/false e revalidação sem revelar/reenviar chave.
- Lint direcionado passa. Descoberta Playwright enumera **14 casos** em 390px e 1440px, dono/não-dono e sessão master sintética. A enumeração não é execução.
- Primeira rodada administrativa do coordenador: quatro casos passaram e dez falharam. Os seletores identificados foram corrigidos às mensagens reais, sem remover asserções de valor preservado, gate, alvo, ausência de mutação, foco, teclado ou overflow. A falha de abandono era de produto e segue com negativo exigente na nova rodada.
- O spec mantém bloqueio de solicitações externas e mocks por origem/endpoint. Adicionou leitura por teclado do financeiro (BRL/USD) e acesso à exclusão recolhida sem acionar exclusão. Nenhum teste executa billing, convite externo, WhatsApp real, Google real, Jev real, aprovação de governança ou ativação de agente real.
- Os 16 contratos/contextos auxiliares abaixo são byte a byte iguais a342b255; nenhuma mudança de endpoint ou payload foi encontrada neste recorte. Isso preserva a ligação existente, mas não substitui teste de autorização backend/RLS, dados reais, provedor ou operação em produção.
- Não houve nova edição estética/motion v3 nesta auditoria. A correção factual acima pertence à fatia v2 já autorizada.

Próxima validação: repetir build e E2E integrados na árvore final, mantendo os negativos de matriz/Back e os erros de navegador sem supressão; revisar depois o delta visual/motion v3 junto do mesmo inventário de dados e ações.

## Manifesto da captura de fonte

O manifesto inclui hashes de conteúdo local. `igual` significa byte a byte com a base. `novo` significa ausência na base. A captura não é um commit nem um freeze de toda a equipe; qualquer edição posterior invalida o hash afetado.

| Caminho | Base → candidata | SHA256 candidata |
|---|---|---|
| `frontend/src/components/shell/AdminAppShell.tsx` | igual | `e7761c493bbd90fc1308ba0c7c4b87f1c844d7f1634cb544b93338e3715eb335` |
| `frontend/src/components/shell/Sidebar.tsx` | alterado | `df968ed7790589b512cab77fac1f45d82437dc13054d742d4a2fdd2c98d063a2` |
| `frontend/src/lib/navigation.ts` | igual | `24511276118fcbc3a331ccaa66a8e3d9a6d41534f70c4347e8a85d2106f34c15` |
| `frontend/src/lib/use-hash-route.ts` | alterado | `a528754a271fc4d128a24ec59e5d620b83f085d2bff9644068291535573dbaf8` |
| `frontend/src/components/config/SetupChecklistScreen.tsx` | alterado | `379ac4e1ca24115b7a10b86f728801fbf27d907aed8d9e5f2341fd1f0ed04b76` |
| `frontend/src/components/config/IdentidadeVisualScreen.tsx` | alterado | `fb45a71609d3beaefe440b749f61e807f1cf5221060da91a93bcd562dbae4e1e` |
| `frontend/src/components/config/CadastroIgrejaScreen.tsx` | alterado | `4ffe63d4b2da28419fb82e1b61affb93c2d3e8b055e5340314b38bbe6533abfb` |
| `frontend/src/components/config/EquipeScreen.tsx` | alterado | `cedb9bed7a34dbbb61ae27cc2949ba3c945648752e54c9ebcabfa9f754eda684` |
| `frontend/src/components/config/RolePick.tsx` | igual | `c0483e0fce6a9abce6a5533254751ac3da5b64d7a9a7ef9ef007c9c2ad99b597` |
| `frontend/src/components/config/PermissoesScreen.tsx` | alterado | `3036ac39935574707cbcf1a75bc27b5517c697609c89a485fce1d29a3f3a34b9` |
| `frontend/src/components/config/IntegracoesScreen.tsx` | alterado | `06618696508cb94f3469416146c29ce9e209a02ff0b90dbd4daf6f1a6df7d195` |
| `frontend/src/components/calendario/CalendarConnectCard.tsx` | igual | `70819ea4b93a83c0d81bbc8ad4e27e1665042c5f5bd7d7f172f2cf4a3746cefc` |
| `frontend/src/components/calendario/AlertRecipientsCard.tsx` | igual | `d92786f0285ee54a877cfe732fd31915343b6ad2d8b7983ca5cfc01eb13e0cb0` |
| `frontend/src/components/whatsapp/WhatsappScreen.tsx` | alterado | `ed3b0f9bd935472e102695aeb4114edf0f9de1ddf92df3a3c4cc049cb6914f13` |
| `frontend/src/components/config/AgenteScreen.tsx` | alterado | `53ff5b467d30bb22ae7741916afa3dfdc73c9d6e6d631e288a416af186dd864e` |
| `frontend/src/components/config/PublicAgentProfile.tsx` | alterado | `2dc1877980034f3c453077f0320ec2bdc73de240908298682190af584029380b` |
| `frontend/src/components/config/AssinaturaScreen.tsx` | alterado | `19011b5a5485970aed3e4e40eafd87d6a99aea68a16e703793f23a7e72e59752` |
| `frontend/src/components/admin/AdminLoginScreen.tsx` | alterado | `d84a99a900d2c5ed35a73498288c9f499ac0bb88793156b63bb8aadc9cd9b08b` |
| `frontend/src/components/admin/AdminConsole.tsx` | alterado | `906f9768fc8fb293ab67f392fca7b18c2baad2be9e4db4b72152b75d75268674` |
| `frontend/src/components/admin/ChurchPage.tsx` | alterado | `fab96ea4f269d3a07cb82eb81a8fc34fb364fc01d7e1d555b043e9208f2d5a63` |
| `frontend/src/components/admin/CreateIgrejaModal.tsx` | alterado | `a3422119c7b0ba54ab8f6611f0b00047350cf4e3d34c1a4c952c33ed5f2b1eda` |
| `frontend/src/components/admin/EditIgrejaModal.tsx` | alterado | `96779b82feadcbda0269ffc3a6a4eae7716ae4d306be04e509ac38a5dc476c7d` |
| `frontend/src/components/admin/PlanosManagerModal.tsx` | alterado | `153b9b1870e793abd4cc1a2a4dc046298bff41a4e3e899c0c5eb3021d8a16328` |
| `frontend/src/components/admin/AuditModal.tsx` | alterado | `b51834dc8bedd9f9520abd4a765728abafacaa6e914a737749ce78ba98333982` |
| `frontend/src/components/admin/JevModal.tsx` | alterado | `260ccfe333bb115a8271311bd44c1ecf2389f5482ddf0fd93d7d9d7986775554` |
| `frontend/src/components/admin/OrquestradorModal.tsx` | alterado | `51e6be1a93fa880d28a14e9c8d5a4719f374a5ae5849231e80b963c7dc4d365c` |
| `frontend/src/components/admin/ConsentGovernanceDraftTab.tsx` | alterado | `69846f04be4f85152ab24e04498b565fcc545bd7e20d4202c0d2c296407ec672` |
| `frontend/src/components/consolidacao/LockedScreen.tsx` | alterado | `463947c79af37c6a7ea3ac4248c5b3f0a677529aad9e547e673bfbb44065b9b7` |
| `frontend/src/components/config/administration-ux-v2.css` | novo | `120ed11ceaa8d100828bca68f9e30776d840c8fdf502c5cd99a99d7df1e77cd5` |
| `frontend/src/components/config/AgenteScreen.credential.test.ts` | alterado | `31985f812bbfc3d0b2db90094cc3f8d652aa46fa5c0d5bf44371538636a6a43d` |
| `frontend/e2e/ux-administration.spec.ts` | novo | `c544ed89d3a03935e5da11e0e64552a4324f94e1296b23666bfc4b75fba1b923` |
| `frontend/src/lib/admin-api.ts` | igual | `1daea6f62d4123dc1ffbc0904992c1b54a3e615d3a93c9f1cceb77b7af238648` |
| `frontend/src/lib/admin-auth-context.tsx` | igual | `0fae1c804a587837919d4aa2b345c5573777518379d93c3ea42176dfc633687a` |
| `frontend/src/lib/api.ts` | igual | `f684af486055f7aca2cdbe5699ac744436e1720301ebc0fe2810ca276f02128c` |
| `frontend/src/lib/auth-context.tsx` | igual | `0c17fc5fd5315cf5683d8f5781886a93fff60db764959e144261c37e21170e31` |
| `frontend/src/lib/agent-api.ts` | igual | `c0338b117b546526d9c59c7cef72c909612d27e9978a8018d09d64cd9cee2f20` |
| `frontend/src/lib/branding-api.ts` | igual | `9c5cd478d1be7c90a84c21a07ef10e1b825e938b27c94e3cf47341ceb20408f4` |
| `frontend/src/lib/church-cadastro-api.ts` | igual | `988585cf771edc44046ed0978b296e60947f4863bc091a22e696f3e366e1ef7b` |
| `frontend/src/lib/calendar-api.ts` | igual | `049b446ee188aa17fcc39650d8712b66a125809ceda0db4462cbdaf413443f42` |
| `frontend/src/lib/whatsapp-api.ts` | igual | `941f3d33de9c0358d66a9d0ead13a5e8110917c91aaea793fefecc7ec0f506be` |
| `frontend/src/lib/roles-api.ts` | igual | `72d0a22453f5d38f8b9e55aa592897286ce27dc1bd6081afd4b0d394fb884035` |
| `frontend/src/lib/permissions.ts` | igual | `1e69a6bba26c0771b21c281fe5fcd8275191b9fc4860f813fbd85269ab803599` |
| `frontend/src/lib/roles.ts` | igual | `7bded7bdab1a472eabcd6f63aa6209862e3e4cfe19effa848cece6cdd0a95f06` |
| `frontend/src/lib/subscription-api.ts` | igual | `1d38954cd962c774ad47ad0ad3d8ea1686ae3e81558af3311c666f6a0e4a9b09` |
| `frontend/src/lib/broadcasts-api.ts` | igual | `65032672887df2760c1b4cad1af9924b47282efd71117dfc4fa2736d41926b21` |
| `frontend/src/lib/setup-api.ts` | igual | `e11f7bf9622021b126817c5fa4913456f7f9a567d459796a0920c207a832b4ac` |
| `frontend/src/lib/setup-nav.ts` | igual | `0b8f3629d218a34752c3eaa29a65768abda737b2b77961e81fcb99f35485fd29` |
