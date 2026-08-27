# Igreja 12: fonte de verdade de produto, agente e operação

**Data-base:** 2026-08-27
**Baseline versionada:** `ad4a27259127506493b69b348a6729e145f5c78b`
(`origin/main`, após a PR #308)
**Natureza desta rodada:** reconciliação documental, sem mudança de runtime,
migration, produção, credencial, flag ou envio externo

Este documento substitui
`docs/audits/2026-07-27-project-source-of-truth.md` como síntese atual. A
auditoria anterior permanece versionada e continua válida como registro
histórico da baseline que examinou.

## 1. Veredito

- A V1 permanece **encerrada**. A tag e o veredito de fechamento não são
  reabertos por este documento.
- A visão integral do Igreja 12 permanece **incompleta**. Ela inclui operação
  WhatsApp-first, memória privada durável, conhecimento oficial por igreja,
  ações confirmadas, notificações proativas e os especialistas dos diferentes
  setores.
- O primeiro canário ativo controlado da Filadélfia obteve **PASS técnico** e
  **FAIL de qualidade conversacional**, conforme relato do operador. O rollout
  amplo permanece bloqueado.
- O estado de segurança informado ao fim da janela foi
  `AgentConfig.ativo=false` e os quatro gates globais fechados. Esta atualização
  não consultou produção e não converte esse relato em prova atual de ambiente.

`V1_ENCERRADA` descreve o contrato entregue da V1. Não significa que toda a
visão de produto posterior já foi implementada.

## 2. Como classificar evidência

| Classe | O que pode comprovar | O que não pode comprovar |
|---|---|---|
| Código, migrations e testes no SHA fixado | Implementação e invariantes estáticos da baseline | Deploy, configuração ou execução atual em produção |
| Documento operacional com artefato identificável | Resultado do procedimento e seus limites na data registrada | Estado vivo posterior ao procedimento |
| Relato do operador | O que foi observado durante uma execução supervisionada | SHA servido, consulta reprodutível ou ausência atual de divergência |
| Merge e CI | Integração do código e passagem dos checks registrados | Promoção do artefato para produção |

O canário ativo de 2026-08-27 pertence à terceira classe. Foram relatadas três
entradas, `Olá`, `Aceito` e `Quero conhecer a igreja`, e três saídas, com autoria
de IA correta, filas e dead-letter canônicas vazias ao fim e gates restaurados.
O telefone sintético não é registrado em claro. O repositório não contém o
pacote imutável de logs, consultas e SHA de runtime dessa janela.

## 3. Precedência documental

Quando duas fontes divergirem, usar esta ordem:

1. código, migrations e testes no SHA de `origin/main`, para afirmar o que está
   implementado;
2. artefatos imutáveis de deploy, smokes e inventários datados, para afirmar o
   que ocorreu em um ambiente;
3. PRD canônico e decisões aprovadas em `docs/decisions/`, para intenção e
   limites de produto;
4. esta auditoria, `docs/ops/POST-V1-MISSION-REGISTER.md` e os runbooks ativos,
   para síntese e sequência operacional;
5. `PRODUCT.md`, `SPEC.md`, `SPEC_PROGRESS.md`, Wiki e documentação de desenho,
   para navegação e contexto;
6. auditorias e registros anteriores, para história, nunca para substituir o
   estado atual.

O PRD canônico continua em
`docs/Docs20260611_163530/PRD20260611_163530.md`. PRDs temáticos são recortes e
não substituem o contrato consolidado.

## 4. Estado comprovado na baseline

### 4.1 Fundação segura do agente

O código contém um LangGraph com entrada única, roteamento para uma rota e uma
saída por turno em `backend/app/agent/graph.py`. O runtime deriva contexto do
servidor, restringe ferramentas e mantém o LLM fora das decisões de identidade,
papel e acesso em `backend/app/agent/runtime.py`.

A fundação integrada pelas PRs anteriores falha fechada para identidade
duplicada, ferramenta desconhecida e acesso inconsistente. A capacidade
`marcar_presenca` permanece fora da ativação operacional do canário. Esses
controles são necessários, mas não resolvem memória, conhecimento ou qualidade
da conversa.

### 4.2 Limites técnicos atuais

Os seguintes gaps são diretamente observáveis no código de `ad4a272`:

1. **LangGraph sem memória durável.** `backend/app/agent/graph.py` chama
   `builder.compile()` sem checkpointer e avisa que
   `AGENT_GRAPH_CHECKPOINT_URL` não está implementada. O lock contém
   `langgraph-checkpoint`, mas não o saver PostgreSQL.
2. **Sem recuperação de histórico ou RAG.** O runtime reformula apenas uma
   resposta-base determinística e remove o texto recebido do prompt em
   `backend/app/agent/runtime.py`. Não há migration ou serviço de embeddings,
   pgvector ou conhecimento institucional na baseline.
3. **Relatório do agente não atualiza o relatório oficial.** A rota
   `report_capture` de `backend/app/agent/nodes.py` extrai números, grava somente
   um evento `report_captured` e responde que recebeu. O writer oficial continua
   sendo `POST /cell-meetings/{id}/report/submit`, conforme
   `backend/app/routers/reports.py` e `backend/app/routers/cell_meetings.py`.
4. **Sem ferramenta de relatório de célula.** O registro em
   `backend/app/agent/tools.py` contém decisão, presença, vínculo de célula e
   avanço de trilha, sem comando que reaproveite o writer oficial do relatório.
5. **Áudio sem transcrição do agente.** Há ingestão e armazenamento de mídia,
   mas a busca da baseline não encontrou implementação de transcrição que
   alimente o turno ou uma proposta confirmável.
6. **Notificações fragmentadas.** `backend/app/services/sla_engine.py` e
   `backend/app/services/event_notify.py` possuem fluxos especializados;
   `backend/app/services/cell_notify.py` é explicitamente no-op; e
   `backend/app/workers/cron_worker.py` ignora ações sem handler executável.
   Não existe uma outbox geral de intenção, consentimento, deduplicação,
   entrega, retry, dead-letter e escalonamento.
7. **Exclusão não alcança memória futura.** O endpoint atual em
   `backend/app/routers/conversations.py` remove conversa e mensagens por
   cascata e tenta remover mídia. Como resumo, checkpoint, transcrição e vetores
   ainda não existem, não há hoje uma exclusão integral desses derivados.
8. **Documentação operacional ficou atrás da execução.** Antes desta
   reconciliação, o registro e o runbook ainda classificavam o canário ativo
   como bloqueado, embora o operador já tivesse executado a janela controlada.

### 4.3 Resultado do canário

Pelo relato operacional, a cardinalidade, autoria, esvaziamento das filas
canônicas e rollback dos gates passaram. O item legado de dead-letter continua
preservado em chave de quarentena, sem leitura ou replay, e não deve ser
confundido com a dead-letter canônica vazia.

A revisão humana encontrou respostas robóticas e perguntas repetidas. Como o
grafo é stateless e o LLM apenas reformula respostas isoladas, o sintoma é
coerente com os limites comprovados no código. Essa relação é uma inferência
técnica, não uma prova de causa única.

## 5. Inventário de trabalho restante

### 5.1 Fundação obrigatória antes de outro canário

- contexto de execução e isolamento de tenant formalizados para todos os
  subgrafos e ferramentas;
- checkpoint PostgreSQL privado, resumo incremental e recuperação seletiva do
  histórico;
- conhecimento oficial por igreja, com registros vivos por ferramentas
  tipadas e documentos aprovados, versionados e filtrados por audiência;
- política explícita para dizer que não existe informação oficial, sem
  alucinação nem repetição de perguntas;
- consentimentos separados para atendimento, cuidado pastoral, tarefas
  operacionais e comunicados;
- proposta durável, confirmação, expiração, idempotência e revalidação de
  autorização para cada escrita iniciada pelo WhatsApp;
- aprovação pelo painel para permissões, terceiros, dados pastorais restritos,
  exclusão, finanças, conhecimento e configuração da igreja;
- outbox geral de notificações, recibos com semântica correta, retry,
  dead-letter e escalonamento;
- deleção propagada para mensagem, mídia, transcrição, resumo, checkpoint,
  vetores e outros derivados, preservando auditoria mínima sem conteúdo;
- onboarding guiado da igreja e avaliação automatizada mais revisão humana da
  qualidade conversacional.

### 5.2 Verticais da visão integral

1. relatório de célula completo pelo WhatsApp, com lembrete, texto ou áudio,
   resumo, correção, confirmação e gravação pelo mesmo serviço do painel;
2. Central de Células e Agenda operáveis pelo WhatsApp dentro das capacidades
   de cada papel;
3. Consolidação com máquina de estados canônica, responsáveis e prazos;
4. Universidade da Vida, Encontro, batismo e acompanhamento;
5. Capacitação Destino, pré-requisitos, progresso e aptidão para liderança;
6. jornada Enviar, multiplicação e exceções sensíveis aprovadas no painel;
7. canários independentes para broadcast, Brevo e Asaas, sem herdar autorização
   do agente.

## 6. Itens que exigem revalidação

Estes pontos não recebem conclusão apenas por inspeção desta baseline:

- SHA atual de backend e frontend em produção, saúde, configuração efetiva e
  estado vivo dos gates;
- isolamento RLS de todas as futuras tabelas de memória, conhecimento,
  consentimento, propostas e outbox;
- cobertura real de Universidade da Vida e Capacitação Destino contra PRDs
  específicos ainda a consolidar;
- semântica dos eventos Evolution disponíveis para distinguir aceitação,
  entrega, leitura e resposta;
- findings históricos de convites, AppUser, responsabilidades e permissões no
  código atual, antes de criar novas capacidades;
- política jurídica e operacional da retenção de conversas até exclusão manual,
  incluindo exportação, solicitação do titular e auditoria sem conteúdo;
- restauração de backup, acessibilidade, performance de campo e responsáveis
  por incidentes;
- destino da quarentena legada na revisão de 2026-09-25;
- qualidade do agente depois da implementação offline. Ela precisa de avaliação
  sintética, testes adversariais e revisão humana antes de produção.

## 7. Sequência autorizável

Esta auditoria permanece o snapshot D0 da baseline `ad4a272`. A PR #310
integrou a reconciliação documental em `253d230`, e a auditoria D1 posterior
está registrada em
`docs/audits/2026-08-27-d1-security-scope-audit.md`.

O próximo gate é revisar e integrar a PR D1A. Aplicação da migration em ambiente
compartilhado e início de D2 dependem de novos gates depois do merge.

Novo canário, ativação de agente, migration em produção, deploy ou abertura de
gate exigem missões e autorizações próprias. Nenhuma dessas ações faz parte da
reconciliação documental.
