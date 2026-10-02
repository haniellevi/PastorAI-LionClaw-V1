# Presença própria da célula pelo WhatsApp

## Comportamento

O pedido explícito de confirmar a própria presença entra no catálogo S3 mesmo
quando também contém uma consulta sobre a próxima reunião. O contexto do
servidor determina titular, igreja, consentimento e vínculo. O modelo seleciona
apenas um alvo opaco autorizado; resumo entregue e SIM atual são necessários.

A reunião vem da célula ativa do membro. A seleção da próxima ocorrência usa
ordem cronológica limitada, rejeita empates e datas ambíguas e respeita E4 no
fuso de São Paulo. O serviço compartilhado bloqueia e relê ator, reunião,
célula, vínculo e presença; revalida horário antes da escrita. Callers humanos
existentes continuam com seu contrato histórico. A confirmação usa a mesma
presença que Minha Célula já lê, sem tabela ou migration nova.

## Validação local

Candidato de produto: catálogo SHA256 `869704214872a349e153ca6fb946c52cd429328d2f9efecc2df2a88046b6689a`,
serviço `4cecec5d9cdfb6a57054ffd3b1e1654d5fe53ec3cde9f20d191e4f67cf5bbaa0`
e dispatcher `4eb206995849954df71a900dd65eb7934af5f8e54b97f4b8c935f417accd46ba`.
Base de teste `379a4dc51bfd46d25d68e5cb43a0699b48d12bc1`, ambiente local
sintético em 02/10/2026, CPython 3.13.14 com dependências fixadas.

226 testes offline passaram, sem falhas, erros ou skips. A seleção cobre
catálogo, propostas, serviço humano, roteamento, presença própria e dispatcher.
53 testes integrados passaram em PostgreSQL 17.6 descartável, sem falhas,
erros ou skips. Percurso exercitado: HTTP autenticado sintético, fila, ingestão,
worker, proposta, resumo, SIM, commit, recibo e projeções de presença/conversa do
painel. Cobertura inclui HMAC inválido antes da persistência, replay, revogação,
rollback antes do commit com recuperação, locks físicos e duas confirmações
concorrentes. O conflito com o serviço humano observa 23505 real e reconsulta
da mesma presença; não alega medição do mecanismo de espera desse conflito.
A sonda dos runners usa PIDs físicos distintos, sem acrescentar espera.

Revisão independente por LENTE: GO nos três arquivos de produto e no ensaio
PG53 final, sem P0 ou P1 bloqueante.
[Evidência sanitizada e hashes](2026-10-02-mvp-own-presence.evidence.json).
CI do commit e autorização nominal de merge continuam obrigatórios.

## Limites

As fixtures usam pessoas fictícias, fila protocolar em memória, LLM e transporte
substituídos. A leitura do painel exerce sua projeção com principal sintético;
não comprova Clerk, Redis, políticas RLS operacionais, provedor ou entrega real.
Não há mudança de flags, consentimento, dados compartilhados, publicação,
envio, cobrança ou PROD. Visitante, oração e piloto continuam pendentes, sem
classificar esta fatia como conclusão da V4 ou do MVP amplo.

Rollback de código: reversão do commit da branch própria. Nenhuma migration ou
aplicação em banco compartilhado pertence a esta alteração.
