# Revisão P2 final, S2b

## Candidato revisado

- Base: `7a00383576878f90c1eb35bfd8648a09c4152529`.
- Patch fonte: `81847a6143b8ed0e037ec1bf75c8c04cb41223c56058f05e89f4a783b2b53e89`.
- Manifesto: `/tmp/igreja12-s2b-p2-snapshot.json`.
- Conferência independente: 13 de 13 blobs do manifesto coincidem byte a byte com o snapshot. O SHA-256 do patch também coincide.

## Parecer

**APTO técnico, dentro do escopo P2 congelado.** Não encontrei P0, P1 ou P2 adicionais.

O reparo da oferta resolve o caso em que um termo muda depois da oferta e antes do inbound `sim`: `process_inbound_message` resolve a oferta sob bloqueio antes do roteamento de consentimento, e o resolvedor terminaliza a aceitação de termo obsoleto para oferta pendente, preparada, expirado ou âncora ausente. O `inbound_message_id` é gravado nesses desfechos, portanto o retry não reclassifica a mesma mensagem nem aplica consentimento ou grafo. O aceite exato de oferta confirmada continua levando somente a handoff.

O parser público reutiliza a allowlist fechada de dia da semana. Um valor legado inválido deixa de vazar como fato público, preservando célula e horário válidos. A API bloqueia publicação ou alteração de dia de célula publicada quando o dia é inválido, e o formulário apresenta erro acessível e evita submissão para o estado desconhecido de publicação em célula inativa. O fluxo de despublicação e os campos ausentes legados continuam preservados.

A migration falha fechada se faltar `igrejas_self_update` ou se a policy tiver comando incompatível. A prova SQL exercita o abort atômico e o catálogo esperado. A guarda intencionalmente não certifica a expressão de predicado de policy pré-existente: depende da baseline canônica já aprovada, e não há evidência de drift permissivo neste candidato.

## Evidência observada

- Backend: 5.467 passed, 354 deselected, sem falhas ou skips.
- RLS: 354 passed, sem skips.
- UI: 915 testes e typecheck verdes.
- SQL da migration original em banco PostgreSQL descartável: 4 provas verdes, incluindo falha `P0001` e fingerprint da guarda.

Essas provas validam o SHA congelado; não comprovam migration aplicada, deploy, flag ou qualquer envio externo.

## Limites e próximo gate

O parecer cobre somente a fonte e evidências do patch acima. O próximo gate humano permanece a decisão de integração e publicação do candidato, separada de deploy e de qualquer operação externa.
