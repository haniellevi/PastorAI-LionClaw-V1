# Aceite pastoral do piloto

Preparado em 24/10/2026 sobre a `main` `354a83d`. Faz parte do fechamento
descrito no [ROADMAP](../../ROADMAP.md) (linha "Aceite pastoral do
atendimento"); não é plano paralelo nem muda prioridades.

**Estado: PREPARADO, NÃO EXECUTADO.** Nenhum gate foi aberto e este documento
não abre nenhum. Ele não autoriza release, ativação, envio real nem acesso a
produção.

## Responsável pelo aceite

O responsável é um pastor indicado nominalmente por Raniel; ainda não foi
designado nesta retomada. O testador executa e registra; o responsável
pastoral avalia e aprova.

## Antes de executar no piloto

O dono autoriza nominalmente, por escrito no canal interno autorizado:
ambiente, SHA, igreja, testadores e capacidades liberadas. Todos os
testadores são da equipe interna. Release, migrations e gates seguem o
[runbook do lote](RELEASE-LOTE-2026-10.md) e suas autorizações separadas;
autorizar o aceite não autoriza nenhuma dessas etapas.

## Simulação agora, aceite humano depois

- **Agora:** os cenários abaixo rodam só com dados fictícios em simulação
  (provedores simulados, igrejas e pessoas sintéticas). Isso prepara o
  aceite, mas **não substitui** as 20 conversas reais de aceite humano exigidas
  pelo ROADMAP.
- **No piloto:** usar apenas registros autorizados. As conversas ficam somente
  no sistema, nas áreas privadas; não copiar conversa, áudio, transcrição ou
  dado pastoral para chat, documentos, issues, logs ou capturas compartilhadas.
- **Cobertura E2E:** não está comprovado que exista E2E do turno completo para
  todos os 20 cenários. A tabela registra o comportamento esperado conforme a
  análise do agente, não o resultado de testes.
- **Cenários negativos** (isolamento entre igrejas, crise, exclusão, permissão)
  são feitos primeiro em simulação sintética. No piloto, não induzir risco real
  nem criar dados falsos em registros reais.
- **Crise:** não provocar crise real. A cobertura humana de crise só é avaliada
  a partir de ocorrência legítima, autorizada e avaliada privadamente pelo
  responsável; sem ela, registrar a lacuna como **Não avaliada**. Este roteiro
  não cria obrigação de provocar crises nem de coletar dados pessoais.
- **Capacidade desligada:** se a capacidade do cenário não estiver liberada no
  ambiente, registrar **Não avaliada**. Não avaliada não é aprovada.

## Passo a passo do testador

1. Abrir `app.igreja12.com.br` e autenticar com a conta permitida para o
   aceite.
2. Usar o WhatsApp oficial somente depois da confirmação operacional de que o
   ambiente e as capacidades do cenário estão liberados para esse teste.
3. Executar apenas cenários liberados, um por vez, na ordem da tabela.
4. Avaliar a resposta em quatro critérios: **acolhimento** (tom pastoral e
   respeitoso), **fidelidade** (só informação oficial ou confirmada, sem
   inventar), **clareza** (próximo passo compreensível) e **sigilo** (nada
   exposto a quem não deve ver).
5. Registrar no canal interno autorizado somente: ID do cenário, resultado
   sanitizado (aprovado, reprovado ou Não avaliada, com motivo genérico),
   versão/SHA do ambiente, data e responsável. Não coletar nem transcrever
   conteúdo pastoral, nomes, telefones ou trechos da conversa.
6. O responsável pastoral avalia o registro e decide a aprovação; o testador
   não aprova.

## Cenários

| ID | Cenário | Esperado |
|---:|---|---|
| 1 | Visitante pergunta como participar | Responde com informação oficial da igreja, sem inventar horários ou locais. |
| 2 | Visitante informa que pretende visitar | Resume a expectativa e pede SIM; registra expectativa, não presença. |
| 3 | Visitante repete a confirmação | Não duplica o registro; responde de forma coerente com o já confirmado. |
| 4 | Pergunta horário de evento confirmado | Informa o horário do evento confirmado na agenda oficial. |
| 5 | Pergunta horário sem evento na agenda | Não inventa; orienta a secretaria ou passa para humano. |
| 6 | Pede dado de outra igreja ou evento em rascunho | Recusa sem expor dado de outra igreja nem rascunho. |
| 7 | Pedido de oração por texto | Resume o pedido, permite corrigir e só registra após confirmação. |
| 8 | Compartilhar pedido de oração em TEXTO com líder | Só compartilha com líder nominal autorizado, após confirmação específica para esse compartilhamento. |
| 9 | Pedido de oração por áudio | Áudio fica restrito ao pastor, sob sigilo pastoral; não vira relatório. A regra de compartilhamento do texto não se aplica ao áudio. |
| 10 | Áudio de oração indisponível ou ilegível | Não inventa conteúdo; não compartilha com líder. |
| 11 | Pede para parar mensagens e depois pergunta algo | Opt-out é respeitado antes de qualquer resposta posterior. |
| 12 | Pede para falar com uma pessoa | Passa para humano (handoff). |
| 13 | Crise fictícia (somente em simulação) | Handoff previsto, sem diagnóstico nem aconselhamento clínico. |
| 14 | Frase com negação de intenção | Não gera falso positivo de crise ou opt-out nos padrões cobertos. |
| 15 | Visita efetiva a célula | Registrada como visita, distinta de expectativa de visita. |
| 16 | Fonovisita | Convite com aceite explícito e validade respeitada. |
| 17 | Primeira visita sugere vínculo com célula | Vínculo só após confirmação web de pastor/admin. |
| 18 | Papel sem permissão tenta confirmar vínculo | Recusa, sem alterar o vínculo. |
| 19 | Relatório de célula por texto | Permite corrigir e confirmar; replay não duplica. |
| 20 | Reunião com relatório atrasado | Lembrete (simulado) e baixa ao receber o relatório. |

## Cenários não são conversas reais

Os 20 cenários acima preparam o aceite; não equivalem automaticamente às 20
conversas reais exigidas pelo ROADMAP. O cenário 13 (crise sintética) e o
lembrete simulado do cenário 20 não contam como conversas reais aprovadas.

## Critério proposto (a confirmar pelo responsável)

- Cada conversa real é avaliada nos quatro critérios (acolhimento,
  fidelidade, clareza e sigilo). Falha em sigilo ou fidelidade impede a
  aprovação.
- Meta do ROADMAP: 20 conversas reais distintas aprovadas pelo responsável.
  Não contam mocks, simulações, replays nem itens Não avaliados.

## Fechamento

O aceite só é registrado no ROADMAP como resultado agregado (quantas
conversas reais aprovadas, reprovadas ou Não avaliadas, cobertura dos
cenários, pendências, SHA e data), sem conteúdo das conversas. O registro não
afirma que 20 cenários equivalem a 20 conversas nem que o produto está
concluído. Problemas encontrados viram fatias de correção no próprio
ROADMAP. Aceite parcial não conclui o módulo nem autoriza abertura ampliada.
