# V2b: lembretes e outbox comum

Implementação originalmente autorizada sobre PR434 `58bcd1808aa511cdfafc7957d5c36a9c0f8ee348`. Após o merge da #434, esta PR foi atualizada contra `main@87e13da06eee047419b583d87545ee44326e1a28`. O [plano V2](../mvp-v2-agenda-whatsapp-plano.md) foi aprovado com entrega separada de consulta e lembretes. Esta fatia reúne os avisos internos EVT-7, lembretes de agenda e lembretes de relatório V1a em uma única outbox e dispatcher. Respostas inbound, broadcast e cobrança ficam fora.

## Contrato de entrega

A identidade e a autorização vêm do servidor. A intenção é única por igreja, destinatário, ocorrência e finalidade; destinatários e finalidades diferentes conservam intenções independentes. Consulta de agenda não inscreve ninguém. Inscrição ou reativação solicitada no WhatsApp exige proposta S3, resumo enviado, confirmação explícita, TTL de dez minutos e uso único.

Após PARAR LEMBRETES, uma nova proposta pode habilitar somente uma nova ocorrência futura. Intenções canceladas e demais terminais não são reabertos. Um evento único sem outra ocorrência não pode ser reativado nesta fatia; a preferência de relatório V1a também não é reativada pela confirmação de agenda.

Eventos semanais usam a antecedência cadastrada para cada ocorrência selecionada. Sem antecedência válida, um horário absoluto só vale para a data original do evento; uma ocorrência posterior fica inelegível.

Todo lembrete exige termo LGPD vigente com versão e timestamp e ausência de revogação. Configuração de público ou telefone não cria consentimento. PARAR LEMBRETES interrompe agenda e V1a; SAIR global prevalece. O aviso curto de parada é registrado. Dados de terceiros, endereços residenciais e texto livre do evento não entram na mensagem.

A janela é 08:00 inclusive até 21:00 exclusive, America/Sao_Paulo. Agenda e EVT-7 compartilham teto de duas intenções de transporte por destinatário/dia local; fora da janela adia somente se o novo horário anteceder a ocorrência. Não há recuperação em rajada nem replay histórico.

EVT-7 tem prazo fixo de dez minutos a partir da primeira janela permitida desde sua criação. Adiamentos por indisponibilidade ou lock não renovam esse prazo; vencido, cancela antes do HTTP, inclusive se o worker retomar tarde. Agenda expira na ocorrência, e V1a conserva a janela da reunião.

O dispatcher persiste claim e lease e encerra a transação antes do HTTP. Revalida autorização, versão da origem, preferência, gates e janela antes do transporte. Retry exige falha comprovadamente anterior ao envio; ambiguidade vira estado terminal para reconciliação. Aceitação pelo provedor não é prova de entrega ao aparelho. Cancelamento após início do HTTP registra a corrida, sem promessa de recolhimento.

## Cutover e rollback

Migration aditiva idempotente, RLS, FKs de tenant e grants mínimos sem DELETE. SQLs anteriores congelados permanecem intactos. O cutover precisa preservar recibos terminais/ambíguos e impedir escritores e consumidores antigos, sem duplicar intenções. Novos registros não podem reconstruir envios anteriores apenas porque o carimbo legado está vazio.

O scheduler V1a consulta as duas gerações de histórico: qualquer linha legada da mesma reunião/líder impede uma nova intenção, independentemente do estado. O histórico legado recente também conserva o limite de um lembrete por líder em 24 horas.

Rollback operacional: fechar gates e preservar histórico; suprimir ou reconciliar pendências antes de reverter o consumidor. Nunca reativar automaticamente o envio síncrono EVT-7 ou a outbox antiga V1a. As colunas `igrejas.notification_outbox_cutover_at` e `events.notification_outbox_fenced_at` são pré-requisitos do binário V2b: publicar backend antes da migration falha, e remover a migration enquanto qualquer processo novo roda também falha. No rollback de código, manter o schema aditivo até comprovar que nenhum binário V2b pode executar; rollback de schema requer janela e autorização próprias. Aplicação de migration e deploy compartilham release com autorização própria, fora desta missão.

## Sequência obrigatória da futura release

Esta sequência é preparação documental. Sua execução depende de release e autorização nominal próprias e não será feita nesta missão. O P2-1 de consolidação registrado na fila é pré-requisito antes de qualquer aplicação de migration em PROD.

0. Antes da release, obter autorização própria para consulta agregada com a role SQL `postgres` em transação read-only e registrar `current_user`. O caminho humano EVT-7 e as policies V2b exigem `app_users.status = 'ativo'`, enquanto o legado admite `NULL`. Executar `select count(*) filter (where status is null) as sem_status, count(*) as total from public.app_users;`. Prosseguir somente se `current_user = 'postgres'`, `sem_status = 0`, `total > 0` e `total` igualar a contagem conhecida em inventário independente e aprovado da mesma release, comprovando visibilidade integral. Se qualquer prova faltar, interromper a release e planejar remediação revisada; não atualizar status automaticamente. Este gate futuro não foi executado nesta missão.
1. Fechar os gates de envio e de agenda, manter as releases novas inertes e interromper produtores/consumidores antigos, incluindo requisições EVT-7 já em andamento. Confirmar que nenhum processo com o binário antigo permanece ativo. Só aguardar um número fixo de segundos não prova quiescência.
2. Identificar claims ainda em voo, aguardar o maior lease persistido e preservar resultados incertos para reconciliação. O legado V1a usa lease padrão de 30 segundos; usar o prazo efetivo registrado, porque callers podem alterá-lo. HTTP já iniciado pode ter sido aceito sem recibo local.
3. Com backup e banco sob o gate próprio, aplicar a migration candidata exata **antes de iniciar qualquer binário V2b**. Os fences impedem elegibilidade de escritas/claims legados posteriores; não recolhem HTTP nem invalidam objetos ORM já carregados. Históricos marcados pelo corte são fences, não comprovantes de entrega.
4. Somente depois de confirmar as novas colunas, publicar os processos novos na mesma release, confirmar exclusividade do dispatcher e executar os checks do runbook de produção. Não abrir gates enquanto houver processo antigo ou dúvida sobre consumo duplicado.
5. Somente após autorização nominal de ativação, testes e revisão da release, abrir os gates previstos. Estados ambíguos continuam sem retry automático. Nenhuma migração/reinicialização autoriza replay de histórico.

## Destinatários EVT-7 e reserva diária

O servidor vincula a configuração de destinatário a uma Pessoa ativa e única. O vínculo não cria consentimento e é revalidado pelo telefone atual no enqueue e no dispatcher. Configuração legada sem vínculo fica inelegível até ser salva novamente, sem backfill ou replay. A transação humana pastor/admin somente enfileira; não escreve preferências, claims ou recibos.

A reserva diária usa o dia do transporte em America/Sao_Paulo, não a data do evento. Ambiguidade mantém o consumo da quota, inclusive após exclusão da origem. Retry comprovadamente anterior ao envio que cruza o dia disputa novamente o teto do novo dia sob lock. Uma intenção antiga não pode deslocar duas já enviadas.

## Gates e evidências

AGENDA_WHATSAPP_ENABLED_IGREJA_IDS vazia e AGENDA_WHATSAPP_APPROVED_RELEASE_ID=None; agenda exige também AGENDA_NOTIFY_ENABLED. Os gates próprios S3/V1a, agente ativo, piloto e envio continuam cumulativos. Manutenção e purga não dependem da ativação do transporte.

A evidência do [CI da PR434](PR434-CI-PG-NAMES.json) confirma nominalmente os E2E de membro e líder no job RLS do head congelado: 643 testes executados e zero skips. Ela se refere à V2a. Para esta V2b, o [plano de QA](QA-PLAN.md) orienta os testes. O [manifesto de arquivos](CANDIDATE-FILES.json) identifica por SHA-256 os 37 arquivos de código, teste, migration e CI alterados pela PR sobre `main@87e13da`; documentação, inclusive `backend/migrations/README.md`, fica no diff Git e fora desse manifesto. O head Git publicado deve ser conferido com o manifesto e o diff completo. Os [resultados locais](LOCAL-VALIDATION.json) de 5.918 testes offline e 683 PG sem falhas ou skips e a [revisão independente anterior](FINAL-REVIEW.md) pertencem ao snapshot histórico `4a3fd616`, anterior às alterações em `notification_outbox.py` e seu teste, ao retarget e ao comentário do SQL. Não atestam o candidato atual. A prova PG/RLS do head final virá do CI no mesmo SHA; a revisão Sarah deve examinar esse head antes de qualquer merge.

Os testes cobrem o turno real de inscrição, entrega do resumo, SIM, efeito S3, outbox e transporte simulado; a confirmação EVT-7 via rota autenticada sob RLS; e o scheduler/dispatcher V1a. Casos negativos incluem PARAR/SAIR, consentimento revogado, quota concorrente, origem bloqueada, atraso além do prazo e ambiguidade. A prova SQL byte-exata é separada do E2E EVT-7, que adapta somente o nome do schema descartável.

Limite: desenvolvimento local com dados sintéticos e providers simulados. Nenhum estado de PROD foi consultado ou alterado; não há prova de painel/simulador nesta missão. Próximo gate humano: Sarah revisar o head final após CI.
