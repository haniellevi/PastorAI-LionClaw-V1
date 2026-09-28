# Revisão independente, V1a extração paga

Base de leitura: `f2a532a`.

## Escopo conferido

- `backend/app/agent/privileged_turn.py` `a76f03901deaee4cacebe6394d1bb3cfa8efa804e27dd861ecd484879a44f387`
- `backend/app/services/cell_report_v1a_service.py` `32bfb5745ec3cc279fd708341da162c3332f18b7f6eb69fa206c8e0c8c92aad7`
- `backend/app/services/llm.py` `b92f325d03ee6de8249111b37f743ef0fb640e983dbd59fd0c32269b7c230653`
- `backend/app/services/cell_report_whatsapp.py` `09a87dee78bc9e5f71d025b312baddf998a7a594148891ad736139573319dbea`
- `backend/app/workers/cron_worker.py` `ff7f6a725997dfaf7d187bc7b18a34f2aebe94345e88848d38fb3beea0c4a495`
- Testes de extração, LLM e cron: `4fad23cd`, `b2f3edc9`, `16c76dca`, além de `6f8f0425` para a projeção fechada.

## Veredito

**APTO técnico delimitado à fonte revisada.** Não há P1 ou P2 aberto neste recorte.

A reserva é persistida antes da chamada externa e a sessão de banco é fechada antes do LLM. O payload do provedor contém somente os quatro agregados rotulados, com schema estrito, limite de saída de 400 via `max_completion_tokens`, sem retry, timeout máximo de quatro segundos e orçamento conservador. A conclusão reabre sessão curta, revalida contexto, consentimento, reunião, líder, versão do rascunho e limites antes de liquidar ou produzir resumo.

O parser determinístico prevalece sobre números já reconhecidos. A projeção paga agora contém apenas campos por extenso ainda não resolvidos, inclusive excluindo `oferta: 30 reais` já canônica. Entrada que o parser rejeita, inclusive observação explícita, produz clarificação fixa antes de reserva ou chamada, sem gravar proposta parcial nem expor o conteúdo recusado.

A auditoria do extrator é persistida uma vez no ramo de expiração pós-HTTP; o uso não é reenviado ao handoff depois desse commit. O cron executa a manutenção V1a no `finally`, depois de fechar a sessão global, mesmo se o sweep SLA ou os crons legados falharem.

## Limites verificados

A lease consultiva de execução já existente permanece durante o turno, mas não há transação ou sessão de pool aberta no HTTP de extração. Entradas distintas podem competir pelo mesmo rascunho: a revisão impede sobrescrita stale, e uma delas pode terminar em handoff após consumir a reserva permitida. É limite de experiência documentado, sem duplicação de efeito ou transporte neste recorte.

Não executei banco, provedor ou cron. A validação integral backend/RLS do hash exato permanece como o próximo gate técnico do responsável pela integração.
