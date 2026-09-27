# Revisão independente, S3 WhatsApp, candidato final

**Resultado: APTO técnico delimitado.** Não encontrei P0, P1 ou P2 aberto no código congelado.

## Candidato conferido

- Base declarada: `2bacfe8ae7688e7b489294ad75f1b9f2dac29b72`.
- Manifesto: `docs/ops/s3-whatsapp-20260927/CANDIDATE-HASHES.json`.
- SHA-256 do manifesto: `927a583ccbf1405343d15015dc11c42a999ec633cd01ac08996d77d2fb9906ae`.
- Conferência local: 46 de 46 blobs de fonte, testes e CI coincidem com o manifesto.

## Pontos revisados

O turno privilegiado resolve confirmação local antes de Jev B/C/D e do LLM. Uma segunda confirmação exata sem proposta pendente é persistida como esclarecimento, impedindo que ela abra nova seleção ou novo efeito. A proposta, o efeito e o recibo continuam sob transação curta e CAS; o roteamento, LLM e transporte ficam fora de sessão ou lock duráveis. Antes do transporte, a fence revalida conversa, opt-out, estado humano, configuração, telefone, instância, identidade, escopo e, para resumo de ação, a proposta, o texto, argumentos e catálogo atual do alvo.

Handoff, opt-out, troca de papel, alvo revogado, perda de ownership e entrega ambígua preservam supressão ou terminalização, sem transformar uma tentativa incerta em retry seguro. O histórico destinado ao LLM exclui resumos privilegiados e a metadata do ledger usa identificadores opacos, sem copiar o conteúdo da seleção ao log de decisão.

O P2 desta revisão foi fechado no delta final. Com termo LGPD vencido, `runtime.py:1966-1980` cancela qualquer proposta S3 ativa antes de encaminhar a mensagem ao fluxo legado. Somente `SIM` estrito é consumido para não virar aceite de termo. `test_agent_privileged_turn_pg.py:472-489` cobre `Aceito` e `sim, concordo`, verifica proposta cancelada e prova que um `SIM` posterior não gera efeito nem recibo.

O UI já revisado permanece incluído no manifesto. O comportamento cobre erro de leitura de sessão, troca tardia de credencial, submissão duplicada e confirmação de identidade sem expor código pela URL ou armazenamento persistente do navegador.

## Evidência informada

Não executei banco, provedor ou ambiente externo nesta revisão. O root informou para o candidato anterior imediato: backend `5660/5660`, sem skips; frontend `937`, lint, build e um E2E aprovados; RLS `384/384`, sem falhas, erros ou skips. Após o delta de termo, informou 25 focais verdes, sendo 23 de worker e 2 de concorrência. A CI deve executar os 386 cenários RLS no head exato.

## Limites

Este parecer não autoriza ativação de flag, envio WhatsApp, provedor, deploy, migration compartilhada ou operação com dados reais. Também não mede qualidade do modelo, latência p95 real ou eficácia de Jev. O catálogo permanece deliberadamente limitado aos alvos e janelas documentados; um alvo ausente exige novo pedido ou encaminhamento humano.
