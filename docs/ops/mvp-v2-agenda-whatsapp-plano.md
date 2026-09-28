# V2: agenda pelo WhatsApp
Status: APTO COM AJUSTES por Claude + Opencoded em 27/09; V2a autorizada, V2b em PR própria posterior.
Base: `3e8306e9dfd5e3dec3097f3e8a701829b4d7aa36`; PR433 e SQL congelados, sem alteração/rebase.
Referências: PRD0611 delta-046/047/052, PRD-COVERAGE, MVP-PLANO e AMBIENTE-LOCAL da PR432; prevalece a decisão local/release de 27/09.
## V2a: consulta e autoridade (implementar agora, sem migration se possível)
Reusar `Event`, serviços humanos de Agenda e PrivilegeContext S3; tenant/ator/papel derivados no servidor, RLS e predicado igreja_id em toda consulta.
Sem vínculo ativo: só horários públicos Igreja/Celula da S2b; `publico_alvo` é seleção de notificação, nunca autorização pública de leitura de events.
Membro, operador e líderes vinculados: eventos confirmados permitidos pelo serviço humano; liderança não amplia leitura para outra igreja nem dados de pessoas/células.
Pastor/admin: mesma consulta; rascunhos editoriais somente após prova Clerk S3 válida. Ambiguidade de identidade -> humano; finanças e listas de participantes fora.
Título somente do Event cadastrado por humano autorizado, validado como S2b: sem telefone/nome/endereço, até 120 caracteres e delimitadores neutralizados; template fixo título/dia/hora, jamais instrução; inválido -> tipo. Descrição/mensagem livre fora.
Endereço somente do cadastro público da igreja quando explicitamente aplicável; nunca presumir local de evento nem usar endereço residencial de célula.
Consulta padrão próximos 7 dias, limite 30 dias/5 ocorrências por página; recorrência semanal calculada no servidor; datas/horas inválidas não são inventadas.
Reusar roteador tipado com enum fechado e handles opacos, projeção mínima e resposta factual; erro/timeout/schema inválido -> handoff; alvo p95 <10s.
SAIR, humano, LGPD e confirmações pendentes precedem roteamento; sem informação: “Não tenho essa informação cadastrada. Quer falar com a secretaria da igreja?”.
## V2b: lembretes e preferências (PR própria posterior)
Somente eventos confirmados, ocorrência válida e destinatário autorizado; reutilizar configuração `notificar_em`/antecedência e resolvedor de audiência, revalidando vínculos/opt-out.
Público coletivo/telefone cadastrado não implica aceite: exigir termo LGPD vigente versionado, timestamp/revogação e preferência de lembretes; ilegível = negar, sem E4B/mint/bypass.
“Me lembre”/reativação exige resumo e confirmação S3 por ação, TTL 10min/uso único, persistência pelo serviço humano e comprovante pós-commit; consulta não cria inscrição.
Primeiro lembrete registra aviso; PARAR LEMBRETES interrompe agenda e relatório, SAIR global prevalece; comandos determinísticos cancelam pendências antes do LLM.
Um lembrete por ocorrência/destinatário; janela 08:00 inclusive a 21:00 exclusive, America/Sao_Paulo explícito neste piloto e persistência UTC; sem inferir outro fuso.
Fora da janela, adiar até abertura somente se anterior ao evento; caso contrário expirar. Sem hora válida, sem lembrete; sem recuperar atrasados em rajada; teto agenda 2/dia por destinatário.
## V2b: outbox única e entrega
Uma outbox durável e um dispatcher para lembretes de agenda, aviso interno EVT-7 e lembretes V1a; adaptar transporte/fences já testados em `cell_report_reminders`.
Trocar envio síncrono `event_notify` por enqueue transacional; finalidades distintas, payload mínimo/reconstruído e deduplicação por tenant + destinatário + origem/ocorrência + finalidade.
Cutover sem dupla escrita/duplo consumo: importar estado/idempotência V1a, preservar terminais/ambíguos; sem replay histórico. Broadcast/cobrança e respostas inbound ficam fora desta fatia.
Claim/lease por linha com commit antes do HTTP; revalidar autoridade, consentimento, gates, horário e versão do evento imediatamente antes de enviar; alteração/exclusão cancela estado obsoleto.
Retries limitados somente quando comprovado pré-envio; resultado ambíguo não reenvia automaticamente e vai para reconciliação; aceito pelo provedor não significa entregue.
Revogação, handoff e desligamento suprimem pendências; manutenção/purga continua com flags off; cancelamento após início do HTTP fica registrado como corrida, sem promessa de recolhimento.
Sem guardar conteúdo de terceiros; reutilizar retenção/erasure V1a, purgar payload transitório em até 24h; recibos técnicos mínimos sem telefone/texto, respeitando exclusão de tenant/pessoa.
## Gates, testes e entrega
`AGENDA_WHATSAPP_ENABLED_IGREJA_IDS` vazia + `AGENDA_WHATSAPP_APPROVED_RELEASE_ID=None`; cumulativos com S3, agente ativo e gates de envio/piloto; Jev não é dependência.
Envios de agenda exigem também `AGENDA_NOTIFY_ENABLED`; migração para dispatcher comum preserva gates próprios V1a e nunca os abre por habilitar agenda.
Arquivos V2a: leitor, catálogo/roteador e testes/docs; V2b: serviços/rotas Agenda, catálogo/roteador S3, dispatcher/cron, models, migration, testes e docs; sem novo painel nem integração Google nesta fatia.
Migration aditiva datada, idempotente, RLS/grants mínimos/FKs tenant, unicidade por tenant + destinatário + ocorrência + finalidade e rollback comentado; não alterar SQLs congelados.
Testes PG17: cross-tenant/papel/Clerk, PII em todos os campos livres, recorrência/janela/limites, revogação/edição, concorrência/replay/lease, cutover V1a/EVT-7, falha pré-envio versus ambígua.
Após #432 mesclada, atualizar base autorizada, `./dev.sh reset` e painel/simulador local com dados fictícios; simulador ainda pendente no head432 consultado, sua falta impede declarar aceite E2E.
CI sem provedor real, fixtures/mocks e regressões S3/V1a/V1b; evidência do SHA exato, sprint e MVP-PLANO, sem reclassificar Agenda completa por esta fatia.
Rollback: flags off, suprimir/reconciliar pendências antes de reverter consumidor; preservar histórico e não reativar envio legado. PROD só release em lote com backup/migrations/backend/frontend e Sarah por release.
Próximo gate: Sarah revisar a PR V2a com CI do head; V2b fica para depois. Sem reset/merge/deploy nesta missão; frontend futuro depende da Vercel restrita à branch producao; ativação real exige Raniel.
