# V1a, diagnóstico de arquitetura

Base lida: `f2a532a9cadba44a31e3d3067125a9e2b624c233` em `/tmp/igreja12-v1a-cell-report-20260927`.

Fontes de contrato lidas: plano V1, ficha `M-2026-09-27-v1a-cell-report-implementation.md`, `ConsentRecord`, `cell_report_application`, `cell_report_whatsapp_coordinator`, `cell_report_meeting_resolver`, `cell_report_turn_uow`, `agent_action_proposals`, `privileged_turn`, `queue_worker`, `cell_meetings`, `tenant_deletion` e modelos relacionados.

Escopo desta nota: diagnóstico somente leitura. Não há candidato congelado, execução de teste, revisão de migration ou aprovação de produto.

## Contrato mínimo recomendado

1. Criar um adaptador MVP de consentimento para V1a, interno e somente leitura, chamado pelo caminho de lembrete, rascunho, confirmação e pré transporte. Ele deve travar e revalidar Pessoa, Conversation e o registro de consentimento dentro da transação curta. Autoriza somente se a Pessoa estiver ativa, sem `optout` ou `sem_interesse`, a conversa não estiver humana, o termo atual for legível e o último `ConsentRecord` for aceitação exata da versão atual. Registros `optout:<versão>` e `reoptin:<versão>` não são aceite do termo. A leitura deve ordenar por `aceite_em, id`; dois registros no topo com o mesmo instante devem negar, não escolher um por acaso.

2. Não ativar `cell_report_whatsapp_coordinator` como está. Ele declara `tarefas_operacionais` inativo, usa `DenyAllOperationalConsentGate` e tem um permit process-local. V1a não deve chamar `_mint_operational_consent_permit`, registrar finalidade, criar permit ou depender de E4B. O adaptador MVP substitui somente esse gate no caminho novo e não altera a origem de consentimento.

3. Manter uma única proposta confirmável. O fluxo offline de `CellReportPendingProposal` usa estado próprio, TTL de 24 horas e `CONFIRMAR RELATORIO`; S3 usa `AgentActionProposal`, resumo entregue e `SIM` com TTL de 10 minutos. Reaproveitar o finalizador de `cell_report_application`, extraído para receber um agregado tipado, mas não ligar os dois workflows de pendência.

4. Estender S3 com a ação fechada de relatório e alvo `reuniao`, preservando os dois valores já existentes. A proposta precisa ficar vinculada a igreja, conversa, líder, inbound, reunião, hash canônico dos quatro agregados, resumo e versão. O efeito canônico precisa de unicidade por igreja, reunião e ação, além do receipt único. A confirmação só pode executar depois de o resumo ter sido confirmado no ledger e de um inbound posterior, novo e literal.

5. Extrair o finalizador de relatório para que o WhatsApp e `cell_meetings.submit_report` compartilhem a mesma trava de reunião, validação de líder, gravação de snapshot, conflito e receipt. O router humano hoje escreve e faz commit por conta própria; mantê-lo como escritor paralelo deixaria uma corrida com a confirmação S3.

6. Persistir lembrete como intenção durável e criar um consumer real. `AgentReplyOutboxEntry` é valor de domínio, não é outbox no banco. O ledger durável atual é `Message.agent_reply_state` e pressupõe um inbound `IngestionOutcome`; o cron não pode fabricar inbound para reutilizá-lo. A intenção deve ter chave por igreja, reunião e líder, tentativa, due time, claim e resultado. O consumer faz CAS ou lease curta, persiste e comita o claim, revalida antes do transporte e só então chama o cliente.

7. Não reutilizar `_AgentExecutionLease` durante HTTP. O worker atual o conserva até o transporte. O lembrete deve soltar sessão, transação, locks de linha e advisory lease antes da chamada, então registrar `aceito`, falha comprovadamente pré envio ou resultado ambíguo. Ambíguo não volta a pendente automaticamente.

8. Armazenar aviso inicial e `PARAR LEMBRETES` por igreja e Pessoa, não como opt-out global nem apenas na Conversation. `SAIR` e opt-out global vencem primeiro. A preferência cancela somente novos lembretes, nunca concede autoridade para rascunho, confirmação ou egress. Reunião sem hora válida não recebe horário inventado; o cron deve ignorá-la. O cálculo usa `America/Sao_Paulo`, início mais duas horas, janela 08:00 a 21:00 e expira após 24 horas.

9. O complemento LLM nunca recebe `Message.texto` cru. A mensagem pode conter nomes, endereço ou conteúdo pastoral, enquanto V1a permite somente presentes, visitantes, decisões e oferta declarados. O payload do mock deve ser uma projeção fechada e limitada desses campos. Texto livre fica fora de prompt, resumo e auditoria; quando a projeção não basta, o fluxo pede correção em vez de enviar conteúdo ao modelo.

10. As flags V1a precisam ser cumulativas com S3, consentimento, agente e envio. `CELL_REPORT_ENABLED_IGREJA_IDS` vazia e `CELL_REPORT_APPROVED_RELEASE_ID=None` deixam o caminho inerte. Flag desligada cancela intenções ainda não transportadas, preserva registros já confirmados e não reabre replay.

## Arquivos que devem concentrar a mudança

- Novo `backend/app/services/cell_report_whatsapp.py` para o adaptador de turno, consentimento MVP, rascunho e resolução S3. Ele não deve importar o permit E4B.
- `backend/app/services/cell_report_application.py` para o finalizador comum de relatório, sem introduzir uma segunda proposta.
- `backend/app/services/agent_action_proposals.py`, `backend/app/agent/privileged_turn.py`, modelos e migration V1a para a terceira ação, alvo reunião, receipt e invariantes de entrega.
- `backend/app/routers/cell_meetings.py` para chamar o mesmo finalizador humano.
- `backend/app/workers/queue_worker.py` ou consumer dedicado mínimo para o lembrete persistido, sem inbound sintético nem HTTP sob lock.
- `backend/app/services/conversation_handoff.py`, `backend/app/services/tenant_deletion.py` e o caminho de reset para cancelar propostas, rascunhos e lembretes antes de apagar mensagens ou conversas.
- `backend/app/config.py` para os dois gates inertes por padrão.

## Riscos que bloqueiam a integração se ficarem sem prova

### P1, consentimento e proposta duplicada

O coordinator offline e S3 têm máquinas de estado incompatíveis. Usar o permit E4B ou guardar simultaneamente `CellReportPendingProposal` e `AgentActionProposal` cria um grant fora da fonte MVP e duas confirmações. A correção é o adaptador de leitura e o finalizador compartilhado descritos acima.

### P1, entrega e retry

O cron não pode chamar o worker com um `IngestionOutcome` inventado, nem manter a lease de execução enquanto faz HTTP. Sem intenção persistida, claim curto e consumer explícito, dois ticks, crash após commit ou resultado ambíguo podem duplicar lembrete ou avançar estado sem entrega.

### P2, dados privados no extrator

Sem projeção fechada, um prompt com texto livre viola o limite explícito de não enviar nomes, endereço, roster ou conteúdo pastoral. O teste precisa capturar o payload do mock, não apenas o JSON de saída.

### P2, retenção e exclusão

O `tenant_deletion` atual toma todas as locks de Conversation antes de apagar Message. A migration V1a precisa incluir as novas relações nesse ciclo, limpar pendências antes de exclusão e manter tombstone mínimo que bloqueie retry. Nenhum texto de rascunho, resumo ou lembrete deve sobreviver por uma referência órfã.

## Provas críticas

1. Unidade: consentimento ausente, termo novo, `optout`, `reoptin`, empate de `aceite_em`, conversa humana, `SAIR` e `PARAR LEMBRETES`.
2. Unidade com mocks: texto com nome, endereço e observação pastoral nunca aparece no input LLM, audit ou resumo; limites de 4.000 caracteres e 16 KiB falham fechado.
3. Worker: resumo reservado não inicia TTL; entrega confirmada inicia 10 minutos; correção cancela a proposta anterior; dois `SIM`, replay do mesmo inbound, falha pré envio e resultado ambíguo não duplicam efeito.
4. Cron: duas execuções concorrentes, janela horária, reunião sem hora, mais de 24 horas, máximo por líder em 24 horas, retry em 1 e 5 minutos e cancelamento por flag, papel, termo, handoff ou opt-out.
5. PostgreSQL descartável: tenant cruzado, alvo reunião forjado, líder de outra célula, mudança de papel entre resumo e `SIM`, concorrência painel versus WhatsApp, receipt único, RLS sem bypass e commit antes do transporte.
6. Exclusão e reset: rascunho, proposta, intenção de lembrete e receipt são removidos ou terminalizados; retry posterior não recria mensagem, efeito ou conteúdo.

## Limites assumidos

- V1a é texto somente. Áudio, storage e transcrição permanecem fora da implementação.
- Oferta é decimal agregado no relatório, sem cobrança, saldo, doador ou lançamento financeiro. Decisões são contagem, sem criar Pessoa ou consolidação.
- Os tetos de US$ 0,10 por relatório e US$ 2 por igreja por dia permanecem os números já aprovados no plano. Esta revisão não conclui nada a partir do texto corrompido citado na ficha.
- Esta nota não é APTO de código, migration, teste PG, deploy ou produto. A revisão final depende de snapshot congelado, hashes e evidência do SHA exato.
