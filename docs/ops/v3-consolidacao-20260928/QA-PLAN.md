# QA Plan V3: consolidação WhatsApp

**Data:** 2026-09-28
**Base revisada:** `342f0ced7af53d2d7e708d99e3b92d54e7a3e22c` (worktree detached)
**Escopo:** planejamento independente de QA para V3. Não aprova código, migration, envio externo, link externo ou release.

## Critério de pronto para revisão do candidato

O candidato só estará pronto para parecer se provar, no SHA exato, que uma decisão abre e opera uma consolidação sem duplicar efeitos, expor dados de terceiros, reativar histórico ou contornar autorização humana. Alertas proativos percorrem a origem real, serviço transacional, `notification_outbox` único, dispatcher e provedor falso. Respostas inbound e recibos S3 permanecem no caminho real já existente de `queue_worker`, com proposta, identidade e recibo persistidos.

O plano aprovado é a fonte de comportamento. Esta matriz transforma seus contratos em provas negativas e concorrentes; não redefine papéis, prazos, finalidades nem mecanismo de entrega.

## Invariantes que os testes devem tornar observáveis

| Contrato | Evidência mínima no candidato |
| --- | --- |
| Decisão canônica | `registrar_decisao` continua a fonte da decisão e retorna sem `commit`; a criação da consolidação e pendência `fonovisita` ocorre no limite transacional externo quando aplicável. Um scheduler pós-commit pode criar alertas a partir da origem canônica, desde que seja idempotente. |
| Vínculo correto | Uma pendência/alerta V3 pertence à **consolidação canônica**, não apenas à `Pessoa`. O identificador de origem deve sobreviver ao histórico de uma pessoa e impedir que uma consolidação nova reutilize ou altere uma antiga. |
| Uma pendência por consolidação | Replay, concorrência e repetição de confirmação não criam segunda decisão, consolidação aberta, pendência `fonovisita`, proposta, intenção ou recibo. |
| Prazo de conexão | Visitante recebe prazo persistido de 24 horas; pessoa já vinculada preserva o fluxo sem prazo inventado. Alerta de deadline usa o prazo armazenado. |
| Estado verdadeiro | Resposta humana só confirma etapa, atribuição ou envio depois do `commit` e do recibo correspondente. Proposta, texto do modelo, intenção pendente e claim não são prova de conclusão. |
| Destinatário atual | Antes de criar, adiar, reclamar ou enviar uma intenção, o serviço revalida tenant, Pessoa/AppUser ativo, papel, preferência, responsabilidade, estágio e origem. A mesma regra vale para resposta inbound já persistida e entregue depois por worker: autorização no ingresso não autoriza transportar uma resposta personalizada após mudança de estado. |
| Nome e dados | Em alerta 1:1, somente primeiro nome normalizado, tipo e prazo saem do servidor para o template. Para toda tarefa em que o consultante atua como coordenação, sem ser o responsável daquela tarefa, a projeção contém somente códigos e contagens. Nenhum nome completo, telefone, sobrenome, contexto pastoral ou identificador de origem sai para o LLM, URL ou grupo. |
| Transporte único | Todo alerta proativo V3 usa somente `notification_outbox` e o dispatcher V2b. Não há produtor, cron ou consumidor paralelo para alertas. Respostas inbound e recibos S3 permanecem no `queue_worker` existente e não são movidos para o outbox. |
| Segurança | Contexto, escopo, código, alvo, estado e papel são obtidos no servidor sob RLS. Link e código não conferem acesso; S3 não pode aceitar destino, Pessoa, responsabilidade ou prazo fornecidos pelo modelo/cliente. |

## Condição de integração já identificada

O painel atual de consolidação permite acesso a `admin`, `pastor` e `lider_consol`, enquanto a atribuição humana legada preserva o destino como qualquer `AppUser` ativo. Essa compatibilidade não concede catálogo S3, link de painel utilizável ou projeção personalizada a um destino sem o papel V3. A prova deve separar a atribuição humana legada da elegibilidade V3 imediatamente antes de proposta, confirmação e transporte.

Não se deve ampliar silenciosamente os papéis do frontend para acomodar a atribuição. Se surgir uma superfície humana distinta, ela precisará de autorização equivalente, link fixo sem PII e testes próprios. Até lá, a atribuição legada permanece no painel existente, e qualquer caminho WhatsApp falha fechado para destino inelegível.

## Limite entre alertas e respostas inbound

O outbox unificado cobre somente alertas proativos V3. O scheduler pode observá-los após o `commit` da decisão e criar a intenção a partir de origem canônica, com unicidade e cutover que impeçam replay. A matriz não exige enqueue do alerta na mesma transação da decisão.

Respostas a inbound, entrega do resumo S3 e seus recibos continuam no `queue_worker` já existente. A exigência P1 é revalidar autorização e projeção de dados imediatamente antes do HTTP desse caminho, sem introduzir novo consumidor ou mover esses efeitos ao outbox.

## Matriz E2E por capacidade

Os casos abaixo exigem turno real: entrada persistida, identidade real de teste, catálogo/roteador, S3 quando houver escrita, serviço de domínio, RLS e recibo persistido. LLM e provedor podem ser falsos determinísticos. Mockar diretamente o roteador, a proposta, o serviço ou o dispatcher não satisfaz este plano.

| Capacidade | Fluxo E2E principal | Casos que devem falhar fechados | Prova persistida |
| --- | --- | --- | --- |
| `registrar_decisao` | Inbound autorizado gera a decisão canônica de visitante; no mesmo limite transacional abre ou encontra a consolidação canônica e cria uma pendência `fonovisita`. Após o `commit`, o scheduler idempotente pode derivar alertas V3 da origem canônica. | Replay da mesma mensagem; duas requisições concorrentes; relatório agregado V1; Pessoa de outro tenant; célula inválida; rollback após conflito; visitante já ligado a célula; duas execuções do scheduler. | Uma decisão, uma consolidação aberta por Pessoa, uma pendência vinculada àquela consolidação, prazo de 24h somente quando aplicável e nenhum recibo/HTTP antes de `commit`. O scheduler cria no máximo a intenção canônica posterior. |
| Consulta de pendências | Inbound chega ao catálogo fechado, resolve identidade e escopo e devolve a fila permitida. Responsável vê primeiro nome, tipo e prazo apenas das próprias tarefas; coordenação que não é responsável por uma tarefa recebe códigos e contagens dentro do escopo humano. | Telefone ambíguo; nickname de grupo/JID de grupo; Pessoa/AppUser inativo; papel revogado; escopo de outro tenant; código adulterado; consulta tentando obter contexto, telefone ou sobrenome; reatribuição ou revogação entre persistir `Message`/`reply` e o worker entregar a resposta. | Auditoria técnica sem conteúdo, resposta compatível com escopo e ausência de PII não autorizada no prompt, resposta, log e URL. A resposta personalizada já persistida não pode ser transportada depois de perder autorização; o teste deve provar zero PII no transporte atrasado. |
| `marcar_fonovisita_feita` | Responsável atual recebe resumo S3, responde `SIM` dentro do TTL e o serviço conclui somente a etapa canônica e baixa sua pendência de modo atômico. | Proposta expirada, já usada ou não entregue; `SIM` repetido; responsável substituído; papel revogado; pendência de outra consolidação da mesma Pessoa; estágio já concluído; conflito concorrente. | Recibo após `commit`, etapa com ator correto, somente item vinculado à consolidação baixado e demais tarefas abertas preservadas. |
| `atribuir_consolidacao` | Liderança autorizada pede atribuição por S3; o alvo é resolvido no servidor, elegível para V3 e do mesmo tenant; consolidação e tarefas abertas sincronizam sob lock. | Alvo enviado pelo cliente; destino humano legado sem papel V3 tentando executar pelo WhatsApp; alvo de outro tenant; alvo inativo; proposta obsoleta; dois gestores atribuindo em paralelo; reatribuição após arquivamento. | Um responsável final, todas as tarefas abertas alinhadas, auditoria do ator e alvo técnico, nenhuma alteração de papel, célula ou vínculo da Pessoa. |
| Link de painel | Mensagem 1:1 usa `frontend_url/#consolidar` sem parâmetros pessoais, de tarefa ou de autorização. Pessoa autenticada no Clerk abre apenas seu escopo. | Sem sessão Clerk; sessão de outro tenant; papel insuficiente; URL copiada; URL malformada, host/porta inválidos ou parâmetros pessoais; tentativa de inferir dados a partir de código ou fragmento. | Nenhuma PII na URL, link não altera estado nem eleva papel e entradas de URL inválidas retornam falha fechada, sem exceção. |
| Propostas S3 | Para cada escrita, o servidor deriva ação, origem, alvo e argumentos, entrega resumo e aceita `SIM` determinístico uma vez dentro de 10 minutos. | LLM enum inválido; handle alterado; timeout; resumo não entregue; `SIM` antes da proposta; alteração de estado entre resumo e resposta. | Hash de argumentos server-side, versão de termo, recibo único, ação executada uma vez ou handoff sem efeito. |
| Opt-in de lembretes | Usuário de equipe elegível pede explicitamente a ativação de lembretes de consolidação; o caminho real produz resumo S3, entrega-o e aceita `SIM` único para persistir preferência e termo vigentes. Só então uma origem posterior elegível pode gerar alerta proativo. | Consulta de pendências; papel; configuração de grupo; proposta não entregue; `SIM` vencido ou repetido; termo mudado; pessoa revogada; `PARAR LEMBRETES` ou `SAIR` entre resumo e `SIM`. | Preferência nasce apenas de opt-in explícito confirmado. `SIM` antigo depois de STOP não reativa; exige nova proposta e nova confirmação. |

## Matriz E2E por finalidade de alerta

| Finalidade | Gatilho e destinatário permitido | Casos de borda e negação | Resultado exigido |
| --- | --- | --- | --- |
| Abertura de conexão | Nova consolidação de visitante com pendência ainda válida; responsável atual elegível, ou coordenação elegível para a tarefa quando não houver responsável. | Pessoa já vinculada; consolidação histórica; sem elegível; responsável trocado antes do envio; preferência ausente/revogada; flags desligadas. | Uma intenção por destinatário/ocorrência/finalidade, criada pelo outbox, ou fila humana visível sem envio. Nunca escolhe destinatário arbitrário ou avisa o visitante. |
| Deadline de conexão | Prazo persistido de 24h ainda pendente. | Prazo inexistente; prazo já resolvido/arquivado; reprocessamento do cron; linha legada anterior ao cutover; execução tardia após expiração. | Intenção usa o prazo canônico, expira 24h após o instante planejado e não renova o prazo nem reconstrói recibo. |
| Pendência de fonovisita | Criação da pendência canônica vinculada à consolidação; responsável V3 elegível atual ou coordenação elegível quando não houver responsável. | Abertura duplicada; tarefa de consolidação anterior da mesma Pessoa; reassignment; tarefa concluída; estágio resolvido; destino legado sem elegibilidade V3. | Alerta identifica apenas primeiro nome normalizado, tipo e prazo quando houver; é 1:1 e cancelado quando perde elegibilidade. |
| Reatribuição | Mudança confirmada de responsável sob lock. | Stale proposal; destinatário anterior já tinha claim; nova pessoa sem LGPD/preferência; mesma pessoa reatribuída; quota já consumida. | Intenção antiga torna-se inelegível antes do HTTP; intenção nova respeita unicidade, quota e janela. |
| Coordenação | Consolidação no escopo humano de coordenação quando o consultante não é o responsável da tarefa. | Coordenação sem preferência; nenhum elegível; código resolvido por usuário não autorizado; tentativa de projetar detalhes na lista. | Somente códigos/contagens para essas tarefas, sem PII e sem envio se faltar destinatário autorizado. |

## Transporte, quota e interrupção global

| Prova | Cenário mínimo |
| --- | --- |
| Janela | Às 07:59 e 21:00 em São Paulo não há HTTP. Às 08:00 há tentativa elegível. Deferral não ultrapassa expiração nem altera o prazo canônico. |
| Quota compartilhada V3 | Duas entregas ou estados ambíguos V3 do mesmo destinatário e dia de reserva bloqueiam a terceira, independentemente da finalidade. A terceira fica na fila e não provoca rajada no dia seguinte. Verificar concorrência de claims e virada de dia. |
| Intenção e recibo | Unicidade inclui tenant, destinatário, ocorrência e finalidade. Retry comprovadamente pré-HTTP pode reutilizar a mesma intenção; qualquer resultado ambíguo nunca reenvia. Um recibo não cria vaga adicional de quota. |
| Lease e commit | Claim, reserva de quota e mudança de estado são persistidos antes do HTTP. Após lease perdido, origem removida, responsabilidade trocada, preferência revogada ou estágio concluído, não há chamada ao provedor. |
| Inbound atrasado | Uma consulta que gerou `Message`/`reply` personalizada e ficou na fila de entrega é revalidada pelo worker antes do HTTP. Se responsabilidade, papel, tenant, identidade ou escopo mudarem, o conteúdo persistido não é enviado; qualquer resposta posterior deve nascer de autorização atual e não carregar PII antiga. |
| STOP | `PARAR LEMBRETES` e `SAIR` cancelam intenções V3 pendentes e propostas S3 de reativação no mesmo limite transacional. `SIM` antigo não revive pendência, alerta, consentimento nem atribuição. |
| Sem elegível | A pendência permanece acessível no painel/fila autorizada. Não há fallback para grupo, visitante, dono antigo ou qualquer membro aleatório. |
| Gates | Flags vazias, release `None`, notificação desligada, agente inativo, piloto ausente ou `ALLOW_REAL_SENDS` desligado impedem o efeito e preservam a fila. Testes usam provedor falso. |

## Concorrência e falsos relatos de estado

1. Disparar duas decisões idênticas em transações concorrentes e forçar uma falha após criar a pendência. Ao final, o banco deve conter somente o conjunto canônico da transação vencedora, sem decisão, tarefa, intenção ou recibo órfão da perdedora.
2. Criar duas consolidações em momentos distintos para a mesma Pessoa, mantendo a primeira histórica. A segunda precisa obter sua própria pendência e origem; concluir, arquivar ou alertar uma não pode mudar a outra. Esta prova identifica implementações que procuram tarefa somente por `pessoa_id`.
3. Tentar registrar alerta `fonovisita` com a fila de uma consolidação e o `consolidacao_id` de outra, inclusive quando ambas pertencem ao mesmo tenant. A relação deve falhar no banco antes de qualquer scheduler ou dispatcher; FKs isoladas que aceitem o par desencontrado não satisfazem a origem canônica.
4. Abrir uma proposta S3 de conclusão ou atribuição, mudar responsabilidade, preferência, papel ou estágio antes do `SIM` e confirmar que a ação é recusada sem texto de êxito falso.
5. Executar conclusão e atribuição concorrentes. A combinação final deve corresponder a uma ordem serializável: item concluído não volta a aberto, responsável não é sobrescrito por proposta obsoleta e nenhuma notificação sai para dono inelegível.
6. Segurar o lock da origem enquanto o dispatcher tenta processar a intenção. O processo não deve chamar o provedor sob lock, consumir envio, manter lease zumbi ou superar a expiração; após liberar o lock, revalida e terminaliza ou processa uma única vez conforme o estado atual.
7. Testar falha de LLM, schema inválido, queda entre resumo e `SIM`, falha de commit e falha de recibo. Todos precisam resultar em handoff ou rollback, jamais em “fonovisita concluída”, “atribuído”, “lembretes ativados” ou “aviso enviado” sem efeito persistido.
8. Persistir uma consulta 1:1 autorizada, alterar a responsabilidade ou revogar o papel antes do `queue_worker` transportar a resposta e executar o retry. Nenhuma resposta persistida com primeiro nome, prazo, código relacionado, telefone ou contexto pode sair. Repetir com JID de grupo, nickname de grupo e identidade ambígua para provar que nenhum deles seleciona destinatário ou projeta PII.

## Privacidade, RLS e autorização

| Vetor | Teste obrigatório |
| --- | --- |
| Tenant | Dois tenants com Pessoas, consolidações, tarefas, códigos, preferências e outboxes semelhantes. Toda leitura, atribuição, conclusão, recibo e dispatcher cruzado falha sem revelar existência ou conteúdo. |
| Papel e estado vivo | Cobrir admin, pastor, `lider_consol`, responsável sem papel de coordenação, destino humano legado sem papel V3, usuário revogado e AppUser inativo. A compatibilidade de atribuição humana não autoriza proposta, confirmação, projeção personalizada ou transporte WhatsApp; esses caminhos revalidam a política V3, não somente a conta ativa. Identidade ambígua, JID de grupo e nickname de grupo não podem ser tratados como identidade humana autorizada. |
| RLS e ACL | Testar sessão humana autenticada sem `BYPASSRLS`, sessão de worker e papel sem privilégio. Humanos recebem apenas o mínimo para fluxo autorizado; worker não ganha `DELETE`; o candidato não usa função definer que ignore o tenant. |
| Consentimento | Papel, presença na fila, decisão, número de telefone ou configuração de grupo não contam como opt-in. O teste E2E cria `preference_kind=consolidation` somente por pedido explícito, resumo S3 entregue e `SIM` vigente. Preferência, termo e revogação precisam ser consultados na criação da intenção e imediatamente antes do envio. |
| Projeção | Inspecionar prompt LLM, payload de provider falso, resposta ao usuário, URL, auditoria e exceções. Para cada tarefa em que a coordenação não é responsável, só código e contagem. Para alerta 1:1, somente primeiro nome normalizado, tipo e prazo. |
| Eliminação | Excluir Pessoa em cenário descartável e verificar o alcance das propostas e dados derivados conforme contrato já existente, sem preservar conteúdo que permita reconstrução de alertas ou recibos pessoais. |

## Cutover, histórico e migration

1. Executar a migration duas vezes em PostgreSQL descartável e provar que não exclui linhas nem concede `DELETE` ao worker. FKs, índices, políticas, grants/revokes e dados preexistentes permanecem íntegros. A migration não cria nem move o marco de ativação V3.
2. Preparar decisão, consolidação, tarefa e estados legados antes da primeira ativação efetiva do runtime, executar a migration e manter flags desligadas. Eles continuam legíveis para a superfície humana e não geram alerta V3, intenção nova, recibo reconstruído ou replay de etapa durante o intervalo migration-flag.
3. Habilitar todos os gates requeridos num cenário controlado e registrar a primeira ativação efetiva da época de runtime. Só origens posteriores a esse marco durável, no escopo de igreja correspondente, podem gerar intenção canônica. Durante uma época aberta e ao fechá-la, o instante é preservado. Na reabertura observada `false→true`, o worker pode renovar o instante de forma monotônica para iniciar nova época, sem retroceder, editar a época aberta ou recategorizar dados do intervalo fechado.
4. Testar Pessoa com histórico fechado e uma consolidação posterior. A coluna/FK/origem usada para a pendência deve separar explicitamente as duas consolidações. Não basta uma busca por Pessoa, telefone ou nome.
5. Testar tenant criado depois da migration e a primeira ativação efetiva posterior. O comportamento prospectivo deve ser determinístico, sem ativar legado inexistente nem depender de backfill que altere dados históricos.
6. Sob sessão worker sem `sub`, criar época aberta em `T0`; tentar editar o instante em aberto, alterar o instante no fechamento e reabrir com instante menor que `T0`, todos negados. Fechar preservando `T0` e reabrir em `T1>T0` devem passar; instante igual deve ser rejeitado. Repetir sob sessão humana e tenant alheio, ambos negados.

## Controles adicionados durante a revisão

- A consulta limita a resposta a dez itens, informa o restante e mantém código técnico também nas próprias pendências; cenário com duas consolidações próprias prova seleção por código.
- A projeção V3 não pode apagar sinais de risco: comando misto ou residual não reconhecido gera handoff sem modelo. A prova inspeciona zero egress e preservação de SAIR/PARAR e confirmações determinísticas.
- O hash da resposta inclui política de apresentação e fila autorizada completa; mudança de atribuição em outra sessão suprime resposta pendente no transporte real, mesmo com sessão ORM reaproveitada.

## Cobertura técnica mínima

| Camada | Evidência exigida |
| --- | --- |
| Unitária | Normalização segura em NFC do primeiro nome, inclusive entrada decomposta equivalente, enum/handles fechados, construção de template 1:1, parser de link inválido que falha fechado, cálculo de janela/expiração/quota, decisão de elegibilidade e cancelamento de intenções. |
| Serviço transacional | Criação conjunta de decisão, consolidação e pendência; atribuição sincronizada; conclusão atômica; cancelamento STOP; rollback sem commits internos. Scheduler pós-commit idempotente deriva alertas da origem persistida, e cada caminho revalida antes do seu HTTP. |
| PostgreSQL 17 | Constraints, FKs tenant-scoped, RLS/ACL, policy humana e worker, conflito concorrente, cutover/replay, quota e lease. Sem fixture superuser como única prova da rota humana. |
| E2E inbound | Cada uma das três capacidades V3, mais `registrar_decisao` reutilizado, percorre `TestClient` ou equivalente até resposta/recibo persistidos. Exercitar identidade autenticada real de fixture e provedor/LLM falsos. Cobrir também a fila real de entrega de `Message`/`reply`: consulta persistida, mudança de responsabilidade ou escopo e retry não podem transportar PII obsoleta. |
| E2E por finalidade | Opt-in explícito por S3 até o primeiro alerta, abertura, deadline, fonovisita, reatribuição, STOP/PARAR, quota, janela, expiração, mudança de dono e resultado ambíguo. Verificar zero HTTP em todas as negações. |
| Regressão | Preservar ou transferir cobertura dos fluxos existentes de decisão, consolidação, fila humana, S3 e V2b. A remoção de teste legado é aceitável apenas se o comportamento correspondente aparecer numa prova mais real e específica. |

## Limites deste parecer de planejamento

Este plano não afirma que o candidato implementa os contratos. Ele não autoriza migration, envio, alteração de papel do frontend, encurtador, acesso Clerk, provider, banco compartilhado ou produção. A revisão seguinte deve usar um manifest com hashes de cada pós-imagem, comparar o delta ao SHA congelado e executar os testes somente no ambiente descartável autorizado.

O próximo gate humano permanece a revisão de Sarah do candidato e suas evidências depois de implementação, revisão independente e CI do SHA exato. Merge, release e qualquer envio real continuam fora deste gate.
