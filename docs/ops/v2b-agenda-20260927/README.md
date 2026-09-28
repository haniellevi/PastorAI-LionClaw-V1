# V2b: lembretes e outbox comum

Implementação autorizada sobre PR434 `58bcd1808aa511cdfafc7957d5c36a9c0f8ee348`, mantida congelada. O [plano V2](../mvp-v2-agenda-whatsapp-plano.md) foi aprovado com entrega separada de consulta e lembretes. Esta fatia reúne os avisos internos EVT-7, lembretes de agenda e lembretes de relatório V1a em uma única outbox e dispatcher. Respostas inbound, broadcast e cobrança ficam fora.

## Contrato de entrega

A identidade e a autorização vêm do servidor. A intenção é única por igreja, destinatário, ocorrência e finalidade; destinatários e finalidades diferentes conservam intenções independentes. Consulta de agenda não inscreve ninguém. Inscrição ou reativação solicitada no WhatsApp exige proposta S3, resumo enviado, confirmação explícita, TTL de dez minutos e uso único.

Após PARAR LEMBRETES, uma nova proposta pode habilitar somente uma nova ocorrência futura. Intenções canceladas e demais terminais não são reabertos. Um evento único sem outra ocorrência não pode ser reativado nesta fatia; a preferência de relatório V1a também não é reativada pela confirmação de agenda.

Todo lembrete exige termo LGPD vigente com versão e timestamp e ausência de revogação. Configuração de público ou telefone não cria consentimento. PARAR LEMBRETES interrompe agenda e V1a; SAIR global prevalece. O aviso curto de parada é registrado. Dados de terceiros, endereços residenciais e texto livre do evento não entram na mensagem.

A janela é 08:00 inclusive até 21:00 exclusive, America/Sao_Paulo. Agenda e EVT-7 compartilham teto de duas intenções de transporte por destinatário/dia local; fora da janela adia somente se o novo horário anteceder a ocorrência. Não há recuperação em rajada nem replay histórico.

EVT-7 tem prazo fixo de dez minutos a partir da primeira janela permitida desde sua criação. Adiamentos por indisponibilidade ou lock não renovam esse prazo; vencido, cancela antes do HTTP, inclusive se o worker retomar tarde. Agenda expira na ocorrência, e V1a conserva a janela da reunião.

O dispatcher persiste claim e lease e encerra a transação antes do HTTP. Revalida autorização, versão da origem, preferência, gates e janela antes do transporte. Retry exige falha comprovadamente anterior ao envio; ambiguidade vira estado terminal para reconciliação. Aceitação pelo provedor não é prova de entrega ao aparelho. Cancelamento após início do HTTP registra a corrida, sem promessa de recolhimento.

## Cutover e rollback

Migration aditiva idempotente, RLS, FKs de tenant e grants mínimos sem DELETE. SQLs anteriores congelados permanecem intactos. O cutover precisa preservar recibos terminais/ambíguos e impedir escritores e consumidores antigos, sem duplicar intenções. Novos registros não podem reconstruir envios anteriores apenas porque o carimbo legado está vazio.

Rollback operacional: fechar gates e preservar histórico; suprimir ou reconciliar pendências antes de reverter o consumidor. Nunca reativar automaticamente o envio síncrono EVT-7 ou a outbox antiga V1a. Aplicação de migration e deploy compartilham release com autorização própria, fora desta missão.

## Sequência obrigatória da futura release

Esta sequência é preparação documental. Sua execução depende de release e autorização nominal próprias e não será feita nesta missão.

1. Fechar os gates de envio e de agenda, manter as releases novas inertes e interromper produtores/consumidores antigos, incluindo requisições EVT-7 já em andamento. Confirmar que nenhum processo com o binário antigo permanece ativo. Só aguardar um número fixo de segundos não prova quiescência.
2. Identificar claims ainda em voo, aguardar o maior lease persistido e preservar resultados incertos para reconciliação. O legado V1a usa lease padrão de 30 segundos; usar o prazo efetivo registrado, porque callers podem alterá-lo. HTTP já iniciado pode ter sido aceito sem recibo local.
3. Com backup e banco sob o gate próprio, aplicar a migration candidata exata. Os fences impedem elegibilidade de escritas/claims legados posteriores; não recolhem HTTP nem invalidam objetos ORM já carregados. Históricos marcados pelo corte são fences, não comprovantes de entrega.
4. Publicar os processos novos na mesma release, confirmar exclusividade do dispatcher e executar os checks do runbook de produção. Não abrir gates enquanto houver processo antigo ou dúvida sobre consumo duplicado.
5. Somente após autorização nominal de ativação, testes e revisão da release, abrir os gates previstos. Estados ambíguos continuam sem retry automático. Nenhuma migração/reinicialização autoriza replay de histórico.

## Destinatários EVT-7 e reserva diária

O servidor vincula a configuração de destinatário a uma Pessoa ativa e única. O vínculo não cria consentimento e é revalidado pelo telefone atual no enqueue e no dispatcher. Configuração legada sem vínculo fica inelegível até ser salva novamente, sem backfill ou replay. A transação humana pastor/admin somente enfileira; não escreve preferências, claims ou recibos.

A reserva diária usa o dia do transporte em America/Sao_Paulo, não a data do evento. Ambiguidade mantém o consumo da quota, inclusive após exclusão da origem. Retry comprovadamente anterior ao envio que cruza o dia disputa novamente o teto do novo dia sob lock. Uma intenção antiga não pode deslocar duas já enviadas.

## Gates e evidências

AGENDA_WHATSAPP_ENABLED_IGREJA_IDS vazia e AGENDA_WHATSAPP_APPROVED_RELEASE_ID=None; agenda exige também AGENDA_NOTIFY_ENABLED. Os gates próprios S3/V1a, agente ativo, piloto e envio continuam cumulativos. Manutenção e purga não dependem da ativação do transporte.

A evidência do [CI da PR434](PR434-CI-PG-NAMES.json) confirma nominalmente os E2E de membro e líder no job RLS do head congelado: 643 testes executados e zero skips. Ela se refere à V2a. Para esta V2b, o [plano de QA](QA-PLAN.md) orienta os testes; [arquivos do candidato](CANDIDATE-FILES.json) e [resultados locais](LOCAL-VALIDATION.json) registram a base e os hashes exatos. A validação local final executou 5.915 testes offline, 66 PG integrados e nove PG do SQL exato, sem falhas, erros ou skips. Os 33 arquivos de código, testes e CI permaneceram idênticos durante a execução. A [revisão independente final](FINAL-REVIEW.md) conferiu o candidato exato e o considerou apto para PR e revisão Sarah, sem autorização de merge.

Os testes cobrem o turno real de inscrição, entrega do resumo, SIM, efeito S3, outbox e transporte simulado; a confirmação EVT-7 via rota autenticada sob RLS; e o scheduler/dispatcher V1a. Casos negativos incluem PARAR/SAIR, consentimento revogado, quota concorrente, origem bloqueada, atraso além do prazo e ambiguidade. A prova SQL byte-exata é separada do E2E EVT-7, que adapta somente o nome do schema descartável.

Limite: desenvolvimento local com dados sintéticos e providers simulados. Nenhum estado de PROD foi consultado ou alterado; não há prova de painel/simulador nesta missão. Próximo gate humano: Sarah revisar o novo PR candidato.
