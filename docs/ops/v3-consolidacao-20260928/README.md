# V3: consolidação pelo WhatsApp

Fatia autorizada sobre PR435 `342f0ced7af53d2d7e708d99e3b92d54e7a3e22c`, preservado congelado. O [plano aprovado](../mvp-v3-consolidacao-whatsapp-plano.md) e a [matriz de QA](QA-PLAN.md) definem o contrato. O candidato foi validado localmente no commit de código `db3a4b8f136c6ca9f802b4dd494e806027f485a4`; CI e revisão humana continuam gates separados.

## Domínio e confirmação

Uma decisão individual usa o serviço canônico e abre sua consolidação. Visitante sem vínculo conserva o prazo de conexão de 24 horas; uma pessoa já vinculada não recebe esse prazo por inferência. Cada nova consolidação tem sua própria fonovisita. Totais agregados de decisões em relatórios não identificam pessoas e não abrem consolidações individuais automaticamente.

Consulta, confirmação de fonovisita e atribuição usam identidade e permissões derivadas no servidor. As escritas compartilham o serviço humano e a plataforma S3: resumo enviado, confirmação explícita, prazo de dez minutos, uso único e comprovante depois do commit. A etapa de fonovisita e sua tarefa são baixadas juntas; isso não conclui toda a consolidação. No painel, consolidações antigas sem tarefa canônica conservam o avanço humano da etapa, sem criar fila ou alerta retroativo. O WhatsApp continua exigindo a tarefa canônica. A atribuição sincroniza as tarefas abertas e invalida propostas baseadas em uma revisão anterior, inclusive se o responsável mudar de A para B e voltar para A.

O suporte de consentimento é uma proposta S3 para ativar os próprios lembretes de consolidação. Consultar a fila, aceitar um termo genérico ou possuir papel não ativa essa preferência. PARAR LEMBRETES e SAIR prevalecem e invalidam propostas antigas de ativação.

## Privacidade e elegibilidade

Somente o responsável atual recebe primeiro nome normalizado, tipo e prazo, em conversa individual. A identidade e a atribuição são revalidadas na consulta e antes do HTTP, inclusive em respostas inbound persistidas que aguardam entrega ou retry. O nome não entra no prompt do roteador. Coordenação sem atribuição àquela tarefa recebe somente contagens e códigos. Uma consulta pode combinar detalhes das próprias tarefas com códigos das demais, respeitando o escopo humano.

A resposta tem limite determinístico de dez pendências, prioriza as próprias e informa quantas restam no painel. O código técnico permite selecionar a tarefa sem transmitir nomes ao roteador. Para comandos V3, texto residual que não caiba integralmente na intenção validada leva a atendimento humano, sem encaminhar o texto livre ao modelo. Essa restrição evita apagar sinais de risco durante a projeção; os comandos determinísticos de opt-out continuam prioritários.

Telefone, sobrenome e contexto pastoral permanecem no painel autenticado. O link curto usa a tela existente `/#consolidar`, sem token, identificador ou PII na URL; o usuário seleciona o registro no painel. O link não concede acesso. Não existe encurtador externo ou login automático.

Coordenação e atribuição permanecem restritas a `admin`, `pastor` e `lider_consol`. O responsável atual também pode consultar e confirmar suas próprias tarefas conforme a permissão humana por tipo: `lider_celula` pode fonovisita; `lider_g12` pode fonovisita e conexão à célula. Esses papéis não recebem códigos de tarefas alheias nem poder gerencial. AppUser, Pessoa, papel e atribuição são revalidados no servidor; o link do painel conserva suas permissões Clerk existentes.

## Comandos da primeira fatia

Os exemplos abaixo documentam a gramática restrita do candidato, não autorizam ativação. Use o código exibido na consulta; o marcador `CODIGO` deve ser substituído pelo valor completo `P-` seguido de dez caracteres.

| Ação | Mensagem |
| --- | --- |
| Registrar decisão | `registrar decisão de NOME`, com pessoa e vínculo resolvidos sem ambiguidade no servidor |
| Consultar | `quais pendências de consolidação` |
| Concluir fonovisita | `confirmar fonovisita CODIGO` |
| Atribuir a si | `atribuir consolidação CODIGO para mim` |
| Atribuir a outra pessoa | `atribuir consolidação CODIGO para NOME`, com nome completo resolvido de forma única entre responsáveis elegíveis da igreja |
| Ativar os próprios lembretes | `ativar lembretes de consolidação` |

Toda escrita ainda exige o resumo entregue e uma mensagem separada `SIM` em até dez minutos. `PARAR LEMBRETES` desativa lembretes, e `SAIR` mantém precedência global. Formas não cobertas ou mensagens mistas podem exigir atendimento humano; esta fatia não promete compreensão irrestrita de texto livre.

## Alertas e transporte

Os alertas de abertura e prazo de conexão e de fonovisita usam apenas a outbox e o dispatcher V2b. Respostas inbound e recibos S3 conservam o worker existente. Não há transporte paralelo. Cada aviso vence 24 horas após seu instante previsto; a janela é 08:00 inclusive até 21:00 exclusive, em São Paulo, com teto V3 de dois avisos por destinatário/dia.

Claim e lease são persistidos antes do HTTP. O envio revalida origem, responsável, papel, consentimento, preferência, gates e prazo. A validação usa a barreira existente imediatamente antes da chamada ao provedor; o commit libera os locks antes do HTTP. Há um intervalo inevitável entre esse commit e o provedor, sem promessa de atomicidade entre PostgreSQL e a rede. Resultado ambíguo continua terminal; a reserva diária é preservada. A fonovisita identifica sua consolidação exclusivamente pela tarefa canônica; a outbox não aceita um segundo vínculo de pai. Nenhuma troca de responsável reabre uma intenção já terminalizada para aquele destinatário. Se A voltar a ser responsável, a pendência continua consultável, mas a mesma finalidade/ocorrência não é reenviada automaticamente para A.

## Ativação prospectiva e rollback

A migration não cria nem preenche marcos de ativação. O worker registra o corte durável quando observa todos os gates abertos; tarefas anteriores continuam consultáveis e não geram alertas retroativos. A abertura de uma nova época exige um ciclo anterior comprovado com gates fechados, que feche o marcador e cancele a elegibilidade pendente. Um ciclo posterior aberto registra um corte estritamente posterior. O banco rejeita alterações do corte enquanto a época estiver aberta ou sendo fechada e rejeita retrocesso na reabertura.

Limite causal: se nenhum processo observou uma troca de flag de fechado para aberto, não há prova de uma nova época. Reiniciar ou editar a env não substitui a observação persistida exigida no runbook de ativação. Essa disciplina integra o gate futuro de release, fora desta missão local.

Rollback fecha os gates V3, confirma o marcador fechado e preserva históricos, resultados ambíguos e comprovantes; nunca reativa um consumidor antigo. Migrations anteriores congeladas permanecem byte a byte. A migration V3 é aditiva/idempotente, com FKs de tenant, RLS e permissões mínimas nas relações novas, sem conceder DELETE. As permissões de exclusão das tabelas legadas não são reclassificadas por esta fatia.

## Migration candidata

Arquivo: `backend/migrations/20260928_080000_whatsapp_consolidation_v3.sql`.
SHA-256: `267f619713f1e2c3ece030227ec387bcef3b76cfbba237f00568e1e347c5b82d`.
Os 86 arquivos SQL da base foram comparados byte a byte e permanecem intactos.
A prova local exercita aplicação e reaplicação do SQL candidato em PostgreSQL 17 descartável; não é evidência de aplicação em ambiente compartilhado.

## Verificação local do candidato

| Prova | Resultado |
| --- | --- |
| Suíte offline integral, Python 3.13.14 | 5.998 passaram, zero falhas ou skips |
| Suíte RLS integral, PostgreSQL 17 descartável | 770 passaram, zero falhas ou skips |
| E2E V3 de turno real, incluídos na RLS | 22 passaram; repetidos na revisão independente |
| Entrega V3 pelo dispatcher comum, incluída na RLS | 25 passaram; repetidos na revisão independente |
| Migration literal, incluída na RLS | 15 passaram; repetidos na revisão independente |

[Resultados sanitizados](VALIDATION.json) e [39 pós-imagens verificadas](SOURCE-SNAPSHOT.json) vinculam a rodada ao commit de código. O [parecer independente final](REVIEW-FINAL-V3-INTEGRATED-ROUTING.md) foi emitido durante a rodada RLS, concluída depois com o resultado acima. O parecer inicial está preservado em `REVIEW.md`; os manifests intermediários estão em `review-inputs/` e o manifesto final reúne as pós-imagens após os deltas.

O E2E começa na mensagem inbound persistida, atravessa worker, identidade, catálogo, roteador, confirmação e persistência reais. Gates usam configuração sintética e provedores são simulados. Essa prova não cobre HTTP de ingresso, parser ou piloto real; o parser/JID e os gates inertes têm testes focais separados. O CI do head publicado ainda precisa passar antes de encaminhar a Sarah.

## Limites de entrega

Gates de V3 e notificações ficam desligados; allowlist vazia e release aprovada `None`. S3, agente ativo, piloto e envio real são cumulativos. Nenhuma execução local autoriza ativação, aplicação compartilhada, merge ou deploy. A base ainda não contém o ambiente local do PR432; não se afirma execução de `dev.sh reset` nem prova de painel/simulador nesta missão.

Próximo gate humano: Sarah revisar código, migration e evidências do candidato exato após CI verde.

## Delta das threads da PR436

O painel conserva o avanço de fonovisita legada sem criar tarefas retroativas. O responsável líder usa a permissão humana por tipo e somente sua atribuição atual; coordenação permanece separada. Comando V3 reconhecido sem capacidade leva a humano antes de qualquer modelo, inclusive após revogação de papel. A migration permanece intacta.

A revisão do delta repetiu 24 testes PG de domínio, 25 de entrega e 48 unitários de catálogo junto com 22 PG de turno. Na primeira repetição houve uma falha G12, com a tarefa ainda aberta após SIM e sem diagnóstico suficiente no teste. O autor não a reproduziu no módulo completo nem na mesma ordem. O teste foi reforçado para verificar proposta entregue, execução, âncora e recibo; a repetição independente dos 70 testes passou. A ocorrência fica registrada sem causa atribuída; não se apresenta a assertiva reforçada como correção de um defeito de produção comprovado.
