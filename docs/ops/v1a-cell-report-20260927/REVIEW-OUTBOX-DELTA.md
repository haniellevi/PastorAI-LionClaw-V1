# Revisão V1a, outbox e retenção

## Escopo conferido

Base declarada: `f2a532a`.

- `backend/app/services/cell_report_reminders.py`: `35e379e802ae6748894475315015bb36c33dd7866553268291a6464fa16bb593`
- `backend/app/services/cell_report_application.py`: `e408add357a570876bf5bcbf1f15b121a66cdd87da202ebd7385994b947d4311`
- `backend/app/agent/runtime.py`: `77ae4084feeceafc8baeb28339ffdff6879c0e23bf5054c230485d36e43e491b`

Os três hashes conferem com o candidato informado. Esta revisão leu apenas o código e os testes focais. Não executou PostgreSQL, provedor ou qualquer efeito externo.

## Parecer

**APTO técnico delimitado para o delta de outbox e retenção.** Não encontrei P0, P1 ou P2 novos neste recorte.

O agendador voltou a preservar as três colunas da consulta com `.all()`. O relógio real é lido novamente entre claim e fence quando `now` não foi fornecido. Não há sessão ou lock de banco atravessando o transporte.

A limpeza agora identifica a proposta da revisão atual sem confundir revisões históricas, terminaliza proposta `preparada` quando o rascunho expira, revalida reunião, célula, liderança, acesso e LGPD também para rascunho parcial sem proposta, e usa `null()` SQL para não gravar JSON `null` em `agent_privilege_context`.

O caminho de resumo não entregue conserva estados ambíguos ou em transporte para reconciliação e só limpa texto quando o ledger prova que o transporte não começou. O lock da mensagem deixa o rascunho elegível para tentativa posterior, em vez de marcar a limpeza como concluída. A seleção percorre as identidades elegíveis antes de consumir a cota de mutações, e a cota é aplicada por tenant, evitando que prefixos válidos ou um tenant movimentado ocultem conteúdo expirado de outro tenant.

Segundo a evidência informada pelo root, os 58 comportamentos deste recorte passaram, incluindo retenção, locks, retries, relógio, revisão, fairness, estado ambíguo e mensagem bloqueada. Essa evidência não substitui a rodada integral do candidato final.

## Limites registrados

- `limit` passou a limitar mutações de conteúdo por tenant, e não a leitura inicial de identidades. Isso é uma escolha explícita para eliminar starvation. Uma igreja com grande volume de rascunhos ambíguos ainda exige observação de capacidade no agendamento futuro.
- Resumos ambíguos permanecem preservados até reconciliação. O rascunho agregado é apagado, mas não há falsa alegação de que uma chamada externa não ocorreu.
- Cron, orçamento, extração e o finalizador humano compartilhado permanecem fora deste recorte.
