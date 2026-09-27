# V1a: relatório de célula por texto, 2026-09-27

**Branch:** `feat/whatsapp-cell-report-text` · **Base:** `f2a532a9cadba44a31e3d3067125a9e2b624c233` · **Deploy:** não

## O que foi feito

O líder prepara por WhatsApp os quatro agregados da reunião: presentes, visitantes, decisões e oferta total. O fluxo permite corrigir o resumo, exige um novo SIM após a entrega e grava pelo finalizador compartilhado com o painel, com comprovante somente após commit. A confirmação durável reaproveita a S3.

Lembretes usam outbox com claim/lease, revalidação antes do transporte e limite de uma intenção por líder em 24 horas. PARAR LEMBRETES persiste a preferência; SAIR prevalece. O cron limpa rascunhos vencidos mesmo com a flag desligada ou falha das rotinas legadas, sempre depois de fechar a sessão global.

O parser numérico é determinístico. O extrator opcional recebe apenas valores rotulados por extenso, com JSON schema fechado, reserva de custo antes do HTTP e revalidação posterior. Números reconhecidos não podem ser sobrescritos pelo modelo. Observações explícitas e entradas inválidas pedem esclarecimento sem chamada paga.

## Decisões

Consentimento vem do termo LGPD vigente, versionado e revogável; E4B permanece pausado. Oferta é somente total declarado em centavos; decisões são contagem, sem efeitos financeiros ou cadastro de pessoas.

Allowlist vazia e release V1a `None` mantêm a fatia inerte, cumulativa à S3, agente, consentimento, piloto e envio. Tetos: quatro extrações por reunião, US$0,10 por relatório e US$2 por igreja/dia UTC. Falha após a reserva conserva o orçamento comprometido; preço desconhecido impede a chamada paga e leva ao humano.

Migration aditiva própria, idempotente, com RLS/FORCE RLS, ACL, FKs compostas, `lock_timeout=2s` e rollback comentado. SQLs congelados 426/428 preservados byte a byte. A PR é empilhada na S3; rebase/retarget exigem nova conferência após a integração da base.

## Pendente / próximo passo

Próximo gate humano: Sarah revisar o head da PR após CI verde. Migration compartilhada, deploy, ativação e merge têm gates próprios. Áudio fica na V1b, com aceite separado versionado e retenção de 24 horas; não integra esta PR.

Mensagens simultâneas podem consumir duas reservas permitidas e levar uma delas ao humano por revisão desatualizada. A revisão do rascunho impede sobrescrita; não foi criada serialização adicional por rascunho.

## Verificação

Head inicial `7d98d0c`: `test-local.sh backend` com 5.747 testes verdes. `rls_integration`: 500 verdes, incluindo 16 casos do SQL exato aplicado duas vezes. Nenhum skip, falha ou erro nas duas suítes. Só PostgreSQL17 descartável e provedores falsos. A prova inclui isolamento, concorrência com painel/SIM, orçamento, retenção, cron, correções, revogação durante HTTP e comprovante após commit.

Revisão independente de fonte sem P1/P2 aberto nos recortes conferidos. Hashes, comandos e limites estão em [VALIDATION.json](../ops/v1a-cell-report-20260927/VALIDATION.json). CI e aprovação Sarah são provas separadas; não houve operação real.

## Delta após revisão do robô e Sarah

Três P2 reproduzidos com PostgreSQL descartável: rascunho parcial capturava pergunta pública, candidato inelegível encerrava o lote de lembretes e comprovante omitia célula/data. A correção preserva o rascunho para continuar o roteamento normal, distingue candidato processado de fila esgotada e persiste o contexto do comprovante junto com o efeito, antes do transporte. Candidatos rejeitados contam no limite do lote. Retry recupera a mensagem original, inclusive se a célula for renomeada depois.

Sarah solicitou revogar DELETE nas cinco tabelas privadas e impor unicidade global do efeito por igreja/reunião/ação. A migration V1a candidata foi ajustada antes de qualquer aplicação compartilhada; os SQLs congelados 426/428 permanecem byte a byte. A revisão local também exigiu que uma cabeça bloqueada não impeça o próximo lembrete: IDs já visitados ficam fora da seleção seguinte, sem antecipar locks de lembrete. Evidência do delta e limites em [DELTA-VALIDATION.json](../ops/v1a-cell-report-20260927/DELTA-VALIDATION.json); aprovação Sarah do novo head continua como gate separado.

Validação do delta: 5.755 backend e 515 RLS, todos verdes, sem skips; 25 casos exercitam o SQL exato. Migration SHA256 `b318e47a27204a2abba3490b7fbfee21b7029890ef329880277c59df7b02ee6f`.
