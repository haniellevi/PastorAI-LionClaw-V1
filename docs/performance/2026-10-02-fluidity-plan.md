# Igreja12: execução do programa de desempenho

Data: 02/10/2026. Base: `35c79663f706a9db489b3a896e0f4b1ec96f8b1c`.
Branch de implementação: `codex/performance-fluidity`.

## Objetivo e limites de aceite

Reduzir espera e trabalho redundante sem perder conteúdo, rascunhos, estados de
erro, permissões cumulativas ou isolamento entre igrejas. A velocidade não
autoriza ocultar registros além da primeira página, ampliar acesso ou repetir
uma escrita cujo resultado ficou ambíguo.

Este incremento implementa os contratos de leitura e cliente do plano. A
observação autenticada em produção, a implantação do backend e as decisões de
infraestrutura dependem de evidência operacional própria. Testes com dados
sintéticos não comprovam o tempo de resposta dos dados reais.

## Entrega por item do plano

| Item | Implementação deste candidato | Limite que permanece |
|---|---|---|
| PERF-00 | Identificação explícita do release da API; duração de requisição, histogramas, erros e amostragem de SQL/conexão/provedores | Coleta de campo autenticada e versões efetivamente implantadas |
| PERF-01 | Prefetch por intenção; Agenda carrega janela necessária em vez do histórico na entrada de Hoje | Medição de tráfego real |
| PERF-02 | Deadline e cancelamento; invalidação após escrita confirmada; respostas antigas não repovoam cache | Timeout de escrita permanece ambíguo e não recebe retry automático |
| PERF-03 | Dados de apoio independentes e estados próprios; nenhuma consulta de domínio antes da autoridade confirmada | Exercitar todas as integrações reais separadamente |
| PERF-04 | `/auth/bootstrap`; login entrega matriz junto ao perfil; matriz vinculada à sessão no cliente | Fallback para API anterior; backend precisa ser publicado para usar contrato combinado |
| PERF-05 | Checklist com projeção SQL; contadores/páginas da Central no banco; nomes em lote | Saúde das células preserva seu serviço e trabalho proporcional ao escopo |
| PERF-06 | Reports usa count e página SQL; valida snapshots enviados em projeção com stream de 100 | Validação fail-closed continua percorrendo todos os snapshots enviados na semana |
| PERF-07 | Busca/lookups paginados; projeção de próxima reunião; completude explícita além de 200 registros | Compatibilidade com API anterior e seleção preservada entre páginas |
| PERF-08 | `/work-queue/snapshot`: total, revisão e página no mesmo statement; revisão nas páginas e revalidação final | Hash percorre fila visível; não equivale a trabalho constante no banco |
| PERF-09 | Polling somente visível; janela recente, delta por cursor e histórico anterior sob demanda | Sem WebSocket novo; preserva polling de recuperação e ressincronização |
| PERF-10 | DTOs e ponteiros materializados antes de liberar Session; assinatura de mídia em endpoint autorizado separado | Uma autorização válida antes do I/O não revoga URLs já emitidas durante seu TTL |
| PERF-11 | Lock atual de envio humano permanece com testes existentes | Novo protocolo de reserva/envio/finalização é condicionado à evidência de retenção e ADR abaixo |
| PERF-12 | Lifecycle dos pools Google/Storage; timeouts por operação preservados; ORM de identidade em endpoint sync | Upload durável de áudio mantém transporte dedicado e deadline estrito; LLM exige protocolo próprio |
| PERF-13 | Casca estática do console e fronteira dinâmica dos formulários | Fontes/CSS/efeitos aprovados ficam sujeitos a profiling; não há redução visual presumida |
| PERF-14 | Métricas para comparar regiões, capacidade, pool e recursos | Nenhuma mudança de região, pool, workers, Redis ou backup sem comparação de campo |
| PERF-15 | Testes de transporte, autoridade, paginação, PostgreSQL/RLS e CI do candidato | Metas de campo exigem amostra real; sucesso local não basta |

## Contratos de consistência e compatibilidade

### Fila

`GET /work-queue/snapshot?page=1&pageSize=N` devolve `Page<WorkItem>` com
`revision`. A revisão é MD5 de fingerprints JSONB ordenados das colunas que
afetam conteúdo/ordem, calculada na mesma visão MVCC do count e da página.
É um detector de mudança, sem função de autorização ou integridade criptográfica.

Páginas posteriores exigem a revisão observada. Inclusão, exclusão, mudança de
prioridade, prazo, conteúdo ou responsável retorna 409. UUID desempata prioridade
e data iguais. O cliente aceita o conjunto completo somente quando total,
unicidade, páginas e a revalidação da primeira página concordam, com no máximo
três tentativas. Mantém a primeira página utilizável durante a coleta.

O statement retorna apenas uma página, mas calcula fingerprints de todos os
itens ativos visíveis. Para uma fila estável com P páginas, a verificação final
usa uma página adicional, em vez de repetir as P páginas inteiras. O fallback
da API anterior preserva a verificação integral e tem capacidade temporária
vinculada ao token, sem dispensar autorização.

`canMessage` é uma projeção da capacidade atual e não uma permissão para a
escrita futura. A ação continua revalidando contato, conversa, papel e posse.

### Conversas

O contrato legado oldest-first continua disponível. `latest=true` seleciona
a janela recente, devolvida em ordem cronológica. `before`/`after` usam o par
`(criado_em,id)`, evitando empates instáveis. Cursores inválidos, simultâneos,
sem fuso ou misturados com offset recebem 422.

`includeMedia=false` entrega texto sem depender de Storage. O endpoint
`messages/media-urls?ids=...` valida a tela, a conversa atual, o tenant e a
visibilidade de cada mensagem; IDs desconhecidos ou de outro escopo falham
fechado antes da assinatura. Mantém o bucket privado e o TTL existente.

O cliente combina janela recente, delta e ressincronização periódica para
alterações em mensagens existentes e confirmações tardias, reconciliando a
faixa já carregada. Quando o histórico já foi totalmente carregado, a
reconciliação cobre também intenções antigas que ficaram visíveis depois.
Esse protocolo não declara snapshot atômico entre múltiplas requisições.
Histórico anterior usa paginação explícita.
Mudança de seleção cancela a visita anterior e preserva rascunhos por conversa.

Assinatura de mídia é dividida em lotes de até 200 IDs. O cliente renova URLs
após 50 minutos, antes do TTL atual de uma hora, sem reiniciar a thread. Uma
negativa de acesso cancela as assinaturas pendentes e impede que suas respostas
atrasadas restaurem URLs. Polling em falha aplica backoff; aba oculta não consulta.

### Bootstrap e lookups

O perfil e a matriz de navegação são resolvidos na mesma sessão tenant-scoped.
O backend continua sendo a autoridade de toda ação. Login/restauração e logout
não reaproveitam uma matriz de outra sessão. API sem o novo contrato usa o
caminho anterior e continua bloqueando conteúdo até confirmação.

Os lookups reutilizam o escopo das listas humanas, com busca literal e limite
de 200 por página. Seleção previamente confirmada não desaparece durante uma
busca. Totais do servidor nunca são substituídos pelo tamanho de uma página.
Quando a API anterior não oferece resumos, o cliente percorre suas páginas
completas em background para restaurar os mesmos indicadores e nomes, depois
da primeira página visível. Esse fallback conserva conteúdo e tem custo maior
até a publicação do novo backend.

A lista de contatos confirma busca com `searchSupported`. Se a API anterior
ignorar `q`, o cliente lê suas páginas no mesmo `view`, filtra nome/telefone/e-mail
e pagina o resultado completo. A confirmação evita apresentar uma página sem
filtro como se fosse uma busca válida.

Agenda opta por `includeUndated=true` para incluir recorrências sem data junto
à janela. O servidor confirma suporte com `includeUndatedSupported`; sua
ausência exige a leitura legada completa, sem o filtro `fromDate` que excluiria
recorrências. O dashboard mantém sua regra de eventos futuros datados. Ambos
preservam o filtro de drafts e tenant.

### Relatórios e tempo de reunião

A validação de snapshots fora da página foi mantida. O novo stream reduz
hidratação e memória, mantendo o custo proporcional aos envios da semana.
Cancelamento, formatos malformados/ausentes de horário, empates e fuso
`America/Sao_Paulo` precisam coincidir com a regra anterior nos testes PostgreSQL.

## Observabilidade

O SHA da API vem de `PASTORAI_RELEASE_SHA` no build de candidato e rollback.
Sem uma revisão explícita válida, o header informa `unknown`; nenhum SHA do
frontend é utilizado para inferir a versão do backend.

Histogramas são internos ao processo, com rótulos finitos de rota/método/classe
de status. SQL/binds, IDs de igreja/pessoa/conversa, URLs, cookies, tokens e
payloads não são registrados. Detalhes de SQL/conexão/provedores são amostrados
independentemente do Request-ID do cliente. A observação não modifica gates.

`db_acquire_ms` cobre dispatch ORM até checkout, incluindo conexão/ping e
eventual fila. Não mede isoladamente espera de pool. `sql_ms` cobre execute
DBAPI e não row fetch. `db_hold_ms` cobre checkout até devolução da conexão,
incluindo o cleanup da dependência. Contagens informam a cobertura observada.
Spans de auth/provider/storage podem se sobrepor a SQL e não devem ser somados
como parcelas independentes.

## Limitações conhecidas

Consolidação WhatsApp produz códigos opacos `P-<10 caracteres hexadecimais>`.
Um prefixo somente numérico, como `P-1234567890`, conflita com o filtro de IDs
numéricos sensíveis do catálogo: o roteamento termina em handoff sem criar a
proposta. A reprodução determinística em PG17 confirmou o mesmo comportamento
na base deste programa e no candidato. O UUID aleatório da falha original não
foi preservado pelo fixture; a reprodução identifica um gatilho concreto da
mesma falha, sem recuperar aquela ocorrência.

Os testes do caminho válido estabilizam apenas os prefixos alfanuméricos das
IDs de tarefas sintéticas, mantendo o restante aleatório, versão/variante,
assertivas e o filtro de privacidade. Isso não corrige a incompatibilidade no
produto. Um follow-up próprio deve definir e revisar a representação do código
opaco, exercitando prefixos numéricos e alfanuméricos, códigos desconhecidos ou
ambíguos e dados sensíveis sem relaxar o guard genérico nesta entrega.

## Decisão condicionada: envio humano sem lock durante provedor

Não remover o `FOR UPDATE` isoladamente: ele protege posse/handoff durante o
envio atual. O ledger de resposta IA não aceita mensagem humana e não pode ser
reutilizado para contornar seu constraint.

Antes de um novo protocolo, medir retenção e saturação dos endpoints de envio.
Se a evidência justificar, especificar intenção durável humana com idempotência,
estado `prepared/sending/confirmed/ambiguous`, identidade/tenant/holder capturados,
fencing de tentativa e reconciliação de resposta ambígua. Revalidar posse antes
do dispatch, sem fingir que autorização anterior permite envio após handoff.
Crash depois do dispatch não deve gerar reenvio automático cego.

Uma eventual migration segue autoria, revisão, RLS/grants, teste cross-tenant e
rollback do contrato vigente. Este incremento não cria schema ou migration.

## Aceite e publicação

Ambiente local: Node 24.19.0, Python 3.13.14, locks existentes e PG17 descartável
com dados sintéticos. Checks de produto: backend-tests, frontend-ci,
e2e-critical, rls-integration e Vercel do SHA correto. O recibo do release registra
separadamente fonte, CI, frontend publicado, backend publicado e limites do QA.

O frontend continua compatível com a API anterior. A publicação do backend
segue `deploy/BACKEND-RELEASE-MANUAL.md` e `docs/ops/PRODUCTION-RUNBOOK.md`:
inventário nominal pelo operador, credenciais/allowlist do ambiente protegido,
janela dos gates, backup/rollback e candidato exato. O fechamento de envios tem
consequências na fila; não pode ser convertido em pausa ou reabertura automática.

Rollback frontend: redeploy do release anterior atribuído à base deste registro.
Rollback backend: imagem anterior com seu SHA próprio, apenas após equivalência
do schema comprovada pelo procedimento. Não há alteração de schema neste pacote.

Próximo gate operacional único: preparar a rota manual do backend e a janela
nominal do piloto para o candidato aprovado. A observação de campo e decisões
de infraestrutura seguem depois da implantação verificável.
