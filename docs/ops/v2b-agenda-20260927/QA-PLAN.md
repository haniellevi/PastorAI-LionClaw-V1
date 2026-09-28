# QA plan V2b: outbox única para Agenda, EVT-7 e V1a

## Controle da revisão

- Objetivo: refutar entrega duplicada, replay de cutover, vazamento entre
  tenants, consentimento inferido, corrida de transporte e reativação sem
  confirmação antes de aceitar o candidato V2b.
- Worktree de revisão: `/tmp/igreja12-v2b-agenda-review-20260927`.
- Base inspecionada: `58bcd1808aa511cdfafc7957d5c36a9c0f8ee348`, destacada,
  limpa, sem branch.
- Controle da missão: `codex/maestri-astra-workspace-plan` em
  `bc75b1518f037d51fae4df6e79945a0ce6e58bc7`, com alterações preexistentes
  preservadas.
- Ambiente de prova: local, PostgreSQL 17 descartável, fixtures sintéticas e
  provider fake. Não usar credenciais, rede, DEV, PROD, banco compartilhado ou
  dados reais.
- Papel solicitado: revisor independente Terra Max, esforço máximo. A
  configuração efetiva de modelo e esforço não é exposta nesta sessão, portanto
  esta linha registra o pedido, não uma confirmação por role.
- Fontes lidas: `AGENTS.md`, `docs/ai/AI-BOOTSTRAP.md`,
  `docs/ai/PRD-COVERAGE.md`, `docs/WIKI-IGREJA12.md`,
  `docs/ops/MAESTRI-PERSISTENCE-MANIFEST.md`,
  `docs/ops/MISSION-CONTROL.md`, `backend/migrations/README.md`,
  a ficha `docs/missions/M-2026-09-27-v2b-agenda-outbox.md` e o plano
  aprovado `docs/ops/mvp-v2-agenda-whatsapp-plano.md`, presente no worktree
  documental da missão.

Critério de sucesso: o candidato demonstra, no SHA congelado, no máximo uma
entrega possível por intenção válida, com retries limitados somente quando o
resultado comprovar pré-envio, sempre após autorização atual, commit da posse e
revalidação, sem replay histórico ou conteúdo privado persistido.

## Invariantes que o candidato precisa preservar

1. Existe uma única relação de outbox e um único dispatcher para lembretes de
   Agenda, aviso EVT-7 e lembretes V1a. Broadcast, cobrança e respostas
   inbound permanecem fora.
2. A chave durável é
   `UNIQUE(igreja_id, pessoa_id, origin_kind, origin_id, occurrence_at, purpose)`.
   A Pessoa é canônica em toda finalidade. Identidade telefônica não pode
   aparecer em claro na chave, no recibo ou na telemetria.
3. O fluxo de confirmação de evento grava a confirmação e a intenção EVT-7 na
   mesma transação. Nenhuma chamada de provider pode ocorrer antes desse commit.
4. Claim, lease, revalidação e renovação da cerca são commits separados e
   concluídos antes do HTTP. Resultado após início do HTTP que não seja
   comprovadamente pré-envio é terminal ambíguo.
5. A janela é `08:00 <= hora_local < 21:00` em
   `America/Sao_Paulo`. O limite de transporte compartilhado entre Agenda e
   EVT-7 é dois por Pessoa e dia local. `delivery_reservation_day` registra de
   forma durável o dia da reserva antes do HTTP. Claims concorrentes e
   resultados ambíguos consomem a vaga reservada; retry comprovadamente
   pré-envio conserva a intenção, mas ao atravessar o dia concorre por vaga no
   novo dia de transporte.
6. Todo envio revalida tenant, Pessoa, vínculo, opt-out global, handoff,
   consentimento LGPD versionado, preferência, gates, evento ou reunião, alvo
   e instância antes do transporte. O `origin_fingerprint` técnico também é
   revalidado e qualquer divergência suprime a linha.
7. `PARAR LEMBRETES` cancela Agenda e V1a para a Pessoa. `SAIR` global
   prevalece. Ambos são comandos determinísticos processados antes de LLM,
   roteador ou proposta pendente.
8. Inscrição e reativação pedidas no WhatsApp exigem uma proposta S3 entregue,
   confirmação nova vinculada a tenant, ator, conversa, ação, argumentos,
   versão do termo e TTL de dez minutos, uso único, commit e comprovante.
   Consulta de agenda, seleção de audiência ou telefone nunca cria opt-in.
9. A migration é aditiva e idempotente, não executa exclusão de linhas, conserva
   SQLs congelados, instala RLS forçada, FKs compostas tenant-bound, grants
   mínimos sem `DELETE` ao worker e rollback comentado. Referências vivas de Evento, reunião e configuração
   usam `SET NULL`, preservando `origin_id`; Pessoa usa `CASCADE` para
   exclusão integral.
10. Cutover não transforma estado legado em confirmação de entrega. Estados
    `enviado` e `ambiguo` preservam sua terminalidade e não são reenviados.

## Achados legados que orientam a revisão

- `event_notify.notify_event_confirmed` chama
  `EvolutionClient.send_text` de forma síncrona e grava
  `events.notificado_em` depois do transporte. O router confirma o evento em
  commit anterior. V2b precisa retirar esse caminho de qualquer confirmação
  nova e persistir uma intenção transacional.
- `cell_report_reminders` já possui claim, lease e fence antes do transporte,
  mas é uma outbox separada. A janela atual admite exatamente 21:00, pois usa
  limite superior inclusivo. A regra V2b precisa substituir essa semântica no
  dispatcher comum.
- `event_recipients` aceita um alvo individual sem `pessoa_id` e o trata
  sem opt-out. Esse formato não prova termo versionado, revogação ou preferência
  e não pode autorizar lembrete de Agenda.
- `cell_report_reminder_preferences` representa somente recusa por presença
  da linha. Reativação não pode apagar, mudar ou ignorar essa preferência por
  comando livre; deve passar pela confirmação S3 e por uma trilha auditável
  mínima.
- Uma migration não consegue desfazer HTTP já iniciado nem impedir um binário
  antigo que comitou claim antes do corte de chamar o provider depois dele.
  A fence SQL reduz o risco para ações iniciadas após o corte, mas não substitui
  retirada dos processos antigos e espera superior ao lease máximo.

## Matriz de provas obrigatórias

| Área | Prova adversarial | Resultado exigido |
| --- | --- | --- |
| Schema e migration | Aplicar a migration duas vezes em PostgreSQL 17 novo, comparar catálogo, constraints, policies, grants e ausência de exclusão de linhas. Verificar FKs vivas `SET NULL`, `origin_id` sem FK destrutiva, Pessoa `CASCADE` e revogação explícita de `DELETE` ao worker. | Segunda aplicação não altera dados nem permissões; novas relações têm RLS habilitada e forçada, FKs tenant-bound e nenhuma permissão `DELETE` ao papel worker. |
| Isolamento | Criar tenant A e B, tentar inserir ou consultar intenção, preferência, claim, recibo e alvo cruzando IDs. Executar também consulta direta sob RLS de A. | A operação cruzada falha ou retorna zero linhas; nenhuma intenção de A aparece para B. |
| Chave de intenção | Concorrer duas transações para a mesma `igreja_id,pessoa_id,origin_kind,origin_id,occurrence_at,purpose`; repetir confirmação HTTP e cron. Comparar origens distintas no mesmo timestamp, finalidades distintas na mesma origem e mesmo origin após retry. | Uma única linha canônica para a chave exata e uma única chamada fake. Origens ou finalidades distintas não colidem só pelo timestamp. A tentativa perdedora observa o mesmo estado, nunca cria segunda intenção. |
| Evento EVT-7 | Confirmar evento com provider fake que falha se chamado antes do commit; fazer rollback da transação de confirmação; repetir a confirmação idempotente. | Commit bem-sucedido deixa exatamente uma intenção EVT-7; rollback não deixa intenção; o router não chama o helper síncrono legado; retry não duplica. |
| Agenda e recorrência | Materializar evento pontual e recorrente, editar, cancelar, remover ou mover a ocorrência entre schedule, claim e fence. | Uma intenção por ocorrência válida; alteração obsoleta cancela ou suprime antes de HTTP; não há recuperação em massa de ocorrência antiga. |
| Limite e fuso | Exercitar 07:59:59, 08:00:00, 20:59:59 e 21:00:00 em São Paulo, com retry e relógio avançado entre claim e fence. Concorrer EVT-7 e Agenda para a mesma Pessoa, persistindo `delivery_reservation_day` antes do HTTP. Depois de duas reservas ou envios, inserir uma linha antiga tardia e verificar que ela não desloca os dois já enviados. Fazer retry comprovadamente pré-envio atravessar meia-noite, com disputa por duas vagas do novo dia. Repetir com resultado ambíguo e com origem removida após a reserva. | Só o intervalo semiaberto envia; 21:00 adia ou expira conforme a ocorrência. No máximo duas entregas possíveis, somando EVT-7 e Agenda, usam o mesmo dia local de transporte. Linha tardia preserva sua reserva e não altera as duas já consumidas. Retry pré-envio mantém a mesma intenção, porém disputa a quota do novo dia. Ambígua e origem removida preservam a reserva do dia correspondente; nenhum desses casos libera vaga ou cria nova intenção. |
| Gates independentes | Variar, um por vez, allowlist Agenda vazia, release Agenda `None`, `AGENDA_NOTIFY_ENABLED=false`, S3 fechada, `AgentConfig.ativo=false`, guard de envio fechado, piloto fechado e gates V1a fechados. | Cada gate bloqueia a finalidade que governa sem abrir outra. Agenda ligada não abre V1a; V1a ligada não abre Agenda ou EVT-7. Manutenção pode suprimir, nunca enviar. |
| Consentimento e audiência | Usar termo ausente, desatualizado, revogado, timestamp futuro, empate ambíguo, opt-out, Pessoa arquivada, telefone ambíguo e alvo individual só com telefone. Para EVT-7, resolver configuração por telefone apenas até uma Pessoa única e então repetir LGPD e preferência. | Zero enqueue elegível e zero HTTP. Audiência, telefone ou papel nunca equivalem a consentimento e EVT-7 nunca cria consentimento. |
| Inscrição e reativação | Entrada real sintética “me lembre”, resumo S3 entregue, `SIM` novo, replay de `SIM`, confirmação expirada, troca de termo, troca de papel e mudança de conversa. Repetir após consulta de agenda e após seleção de audiência. | Somente o `SIM` vinculado à última proposta entregue, ainda válida e de uso único reativa ou inscreve; replay e qualquer alteração cancelam. Consulta, audiência e telefone não criam opt-in. Comprovante surge depois do commit. |
| PARAR e SAIR | Inbound real sintético para `PARAR LEMBRETES` e `SAIR`, com uma linha pendente e outra em envio. Repetir com flags e releases Agenda, V1a e S3 fechados. Substituir LLM por sentinela que falha se invocada. | Os comandos são resolvidos antes da sentinela mesmo com gates fechados. Pendentes Agenda e V1a são canceladas, em envio vira ambígua, e `SAIR` mantém opt-out global superior a qualquer reativação. |
| Claim e concorrência | Dois dispatchers e dois cron workers concorrem na mesma fila. Interromper após claim, antes da fence, durante lease e após erro do fake. Em paralelo, prender `confirm_event` e dispatcher em barreiras que tentem as ordens Evento→Pessoa e Pessoa→Evento. Com o Evento bloqueado, exercitar `FOR UPDATE SKIP LOCKED`; repetir com origem realmente ausente. Para EVT7 criado fora da janela, repetir fonte bloqueada e instância indisponível depois do deadline imutável derivado da abertura seguinte mais dez minutos. | Só um worker chama o fake. Claim e fence ficam commitados antes de HTTP. Lease expirada e erro incerto terminam ambíguos; apenas classificação comprovada pré-envio recebe retry limitado. A implementação usa ordem única de locks ou try-lock com retry controlado: não há deadlock, timeout vazado, confirmação parcial ou nova intenção duplicada. Origem lockada libera a claim e volta a retry pré-envio, sem tentativa de provider ou consumo de tentativa do provider; para EVT7 ela não prolonga o deadline, termina `pre_envio_expirado` e não deixa fila zumbi. Origem ausente fica terminalizada. |
| Exclusão e origem | Excluir ou alterar Evento, reunião e configuração depois de enqueue e antes da fence; excluir a Pessoa em outro caso. Alterar o `origin_fingerprint` sem trocar a chave. | A origem viva fica `NULL`, mas `origin_id`, quota e recibos técnicos da origem sobrevivem sem reenvio. Fingerprint divergente suprime. Exclusão da Pessoa remove outbox, preferências e recibos relacionados por cascade, sem resíduo consultável. |
| PII e payload | Inserir marcadores sintéticos de conteúdo livre em título, descrição, mensagem, nome e contato. Serializar intenção, recibo, erro, log estruturado e payload do provider fake. | A outbox e seus recibos contêm somente identificadores, finalidade, ocorrência, estado, tempos e hashes técnicos permitidos. Marcadores privados não aparecem em persistência, telemetria ou exceções. |
| Cutover V1a | Preparar linhas legadas `pendente`, `retry`, `em_envio`, `enviado` e `ambiguo`; iniciar dispatcher legado e novo contra o mesmo banco depois da migration. | Pendentes e retries ficam fenced, em envio permanece ambíguo, terminais não são importados como novas tentativas, e ambos dispatchers fazem zero entrega duplicada. |
| Cutover EVT-7 | Preparar evento histórico com e sem `notificado_em`; confirmar um evento novo por caminho atual e por objeto ORM legado materializado antes do corte. | Histórico não gera outbox nem replay. Confirmação nova gera apenas a nova intenção. O marcador usado para bloquear helper legado é registrado como fence, não como receipt de entrega. |
| E2E por finalidade | Agenda: inbound sintético, roteador real, resumo S3 entregue, `SIM`, outbox, dispatcher, provider fake e recibo. EVT-7: `confirm_event` com claims reais de pastor ou admin sob `authenticated` NOBYPASSRLS, outbox, dispatcher e fake. V1a: scheduler vigente, outbox única, dispatcher e fake, comprovando que entrypoints legados fazem zero HTTP. Não substituir catálogo, roteador, autorização ou dispatcher por helpers ou stubs. | Para cada finalidade há entrada ou gatilho real sintético, decisão e serviço reais, outbox, claim, fence, fake provider e recibo. O texto recebido pelo fake coincide com a mensagem reconstruída autorizada e a prova cobre o efeito real, não só um mock de roteador. |

## Sequência de execução

1. Congelar o candidato com SHA, hash SHA-256 do patch, árvore limpa e lista
   exata de arquivos. Comparar a mudança somente contra
   `58bcd1808aa511cdfafc7957d5c36a9c0f8ee348`.
2. Revisar a migration antes de executá-la: ordem datada, aditividade,
   idempotência, RLS, `FORCE ROW LEVEL SECURITY`, FKs, grants e rollback.
   Rejeitar alteração nos SQLs congelados.
3. Rodar primeiro testes puros de estados, horário, idempotência, privacy,
   flags, S3 e classificação de transporte. Todo caso da matriz deve começar
   com uma asserção que falha no comportamento legado relevante.
4. Rodar PostgreSQL 17 descartável: migration duas vezes, RLS cross-tenant,
   concorrência real, lease, cutover e E2E. Conservar XML ou JSON sanitizado
   com número de testes, zero skips no recorte V2b e hora.
5. Rodar a regressão offline requerida pelo candidato, incluindo S3, V1a, V1b,
   Agenda V2a, EVT-7 e cron. Rodar CI no head exato depois da revisão local.
6. Revisar manualmente o diff de cada chamada ao provider. Deve existir um
   único ponto de transporte comum e nenhuma chamada direta remanescente de
   `event_notify` ou `cell_report_reminders` para as finalidades migradas.

## Protocolo de cutover

O teste distingue três fatos que não podem ser fundidos:

1. Uma **fence** é uma transição durável que impede novo claim ou nova escrita
   pelo caminho legado. Não prova entrega, não autoriza retry e não é recibo.
2. Um **recibo** só é gravado após resultado classificado do provider. Aceite
   de transporte não prova entrega ao destinatário; resultado incerto é
   ambíguo e terminal.
3. Um **gate operacional** é necessário para retirar todos os cron workers
   antigos e aguardar lease máximo mais margem antes de qualquer ativação. SQL
   não revoga uma chamada já iniciada ou um objeto em memória de processo antigo.

Para V1a, a fence proposta deve impedir futuras linhas legadas elegíveis,
cancelar `pendente/retry` e preservar `em_envio` como `ambiguo`. Para
EVT-7, um `notificado_em` escrito exclusivamente para bloquear o helper
legado precisa ter marcador separado de razão de cutover e documentação clara:
não é prova de envio. O dispatcher novo não pode transformar esse carimbo em
intenção, retry ou recibo.

## Rollback e evidência

- Rollback técnico: fechar flags, suprimir pendências novas e reconciliar
  ambíguas antes de retirar consumidor. Não reativar dispatcher legado,
  reaproveitar estados ou reenviar histórico automaticamente.
- Rollback de migration: seguir somente o comentário revisado da migration,
  depois de confirmar que não há pendência ou conteúdo privado a perder. Não
  aplicar rollback em ambiente compartilhado nesta missão.
- Evidência mínima: SHA base e candidato, hash do patch, horário, ambiente,
  comandos, contagem de testes, artefatos sanitizados de PG17 e CI. Não anexar
  payloads, números, nomes, texto livre, credenciais ou logs brutos.
- Limite explícito: esta revisão local não prova deploy, migration aplicada,
  worker em execução, gate aberto, provider real ou entrega real.

## Condições de bloqueio da revisão final

- Candidato sem SHA ou patch congelado, worktree sujo, migration fora do fluxo
  permitido, SQL congelado alterado ou teste que depende de provider real.
- Ausência de teste que simule dispatcher antigo e novo sobre o mesmo banco.
- Uso de `notificado_em` como se fosse receipt, consentimento derivado de
  telefone ou audiência, reativação sem S3, ou payload persistido com conteúdo
  livre de terceiros.
- Qualquer caminho que faça HTTP antes do commit da fence ou que reprograme
  automaticamente estado ambíguo.

Próximo gate humano único: Sarah revisar a PR candidata após a execução local
deste plano e os checks obrigatórios verdes no SHA exato.

## Regressão completa antes da entrega

Mudanças compartilhadas no ORM e no lock de destinatário exigem executar toda a suíte `rls_integration` em PostgreSQL descartável, além dos E2E focais. As fixtures SQL manuais devem refletir as colunas consumidas pelo ORM, sem substituir as policies e os testes de isolamento. No cutover, a prova inclui o scheduler contra todos os estados legados, o limite de 24 horas e a seleção de ocorrência recorrente.
