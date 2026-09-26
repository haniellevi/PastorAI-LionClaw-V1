# MVP fase 2, fatia 1: resposta contextual, handoff e B4

Base: main `92eed5767bd74a2130e7572d739cc871e6e698a9`.
Branch: `feat/mvp-fase2-respostas`. Ambiente: somente local/GitHub.

## Problema e escopo

O runtime descartava a mensagem recebida ao montar o prompt e pedia ao LLM
somente para reformular a saudação. A fatia usa mensagem atual, perfil da
igreja e até dez mensagens anteriores da mesma conversa/tenant. Consentimento,
opt-out e efeitos de domínio continuam sob regras determinísticas. Pedido
humano/crise por regex pausa a IA e abre espera no inbox; não atribui um
responsável fictício. Resposta limitada a 1600 caracteres. B4 exige aceite
inequívoco, sem aceitar “sim, mas não quero”.

Nenhuma migration, ferramenta nova de consulta, dependência, checkpointer,
credencial, rede de provedor, DEV/PROD/VPS ou envio real. O roteiro do piloto
anterior refere-se à main `92eed57` e não implanta esta fatia.

## Verificação

Em 26/09/2026, `test-local.sh` passou com Python 3.13.14 e Node 24.19.0:
5042 testes de backend, 856 de frontend em 97 arquivos e verificação de tipos.
A suíte PostgreSQL 17 descartável passou com 315 testes, zero falhas, erros ou
skips. O histórico foi exercitado em SQL real, excluindo outra igreja/conversa,
mensagem futura e respostas pendentes/suprimidas, preservando resposta confirmada.
As regressões também cobrem opt-out, B4, handoff, liberação humana concorrente
e perda de ownership antes do transporte. LLM e transporte foram simulados.

Código e testes do candidato `4b9afa40e007005f231df5d224054a6487a8144d169026a2f31dcb9a207dd68c`
foram conferidos em cópia separada por revisão Terra Max; quatro achados foram
corrigidos antes da validação final. Os resultados locais não comprovam deploy,
dados reais ou qualidade geral do LLM. CI será associado ao head publicado na PR.
Evidências integrais permanecem na ficha local
`M-2026-09-26-piloto-roteiro-e-mvp-fase2` e no pacote
`docs/ops/mvp-fase2-20260926/` do workspace de controle.

## Limites e rollback

Mocks comprovam montagem, filtros e controles exercitados, não qualidade geral
do LLM nem eficácia clínica dos sinais de crise. Regex pode ter falsos positivos
e negativos; o atendimento humano permanece necessário. O piloto com 20
conversas reais e ferramentas somente de leitura ficam fora desta fatia.
Rollback: revert do commit desta PR, sem reversão de schema. Nenhum efeito
operacional foi realizado nesta missão. Merge depende de frase nominal de
Raniel com o número da PR; esta entrega não autoriza deploy ou canário.
