# Sigilo de oração — fatia 1

Decisões provisórias, aguardando confirmação pastoral, centralizadas em
`backend/app/prayer/policy.py`: pastor ativo; líder nominal somente após SIM
para o compartilhamento e enquanto persistir o vínculo. Admin/secretaria não
herdam leitura; assumir atendimento não concede acesso pastoral. Não há promessa
retroativa. A trava de release e a lista por igreja continuam fechadas.

O comando `QUERO INICIAR PEDIDO DE ORAÇÃO` abre a proposta na mesma transação
da ingestão, quando os gates e o contato vigente permitem. As mensagens
seguintes da pessoa são vinculadas pelo banco antes do commit, incluindo mídia ignorada
pelo fluxo textual, correções, resumo, confirmação e cancelamento, enquanto
a coleta estiver no prazo. Após expirar, novas entradas não herdam a coleta. Cancelar ou
expirar não remove a proteção. Envio inicial inline legado só passa a ter
associação quando processado; iniciar explicitamente antes do conteúdo evita
essa janela. Áudio/transcrição de oração seguem fora desta fatia.

`pedido_oracao_mensagem` não contém conteúdo. FKs compostas impedem associação
entre igrejas/conversas. O apagamento somente da proposta conserva uma barreira
sem proposta, acessível apenas aos pastores; apagar mensagem/conversa remove
sua associação. RLS restritiva impede SELECT direto de mensagens protegidas.
A projeção do inbox retorna marcadores e elimina todos os metadados de mídia
antes da aplicação, da paginação e da assinatura. A prévia persistida da conversa
com histórico protegido fica neutra para todos os papéis; a busca atual usa
somente os dados dessa lista. Respostas do inbox usam `private, no-store`.

O backfill da migration protege conservadoramente mensagens posteriores à
primeira entrada de oração: a V4 não guardava o horário de encerramento.
Somente source, resumo, SIM e contexto de resposta explicitamente correlacionados
herdam compartilhamento confirmado com líder. Demais mensagens históricas ficam
exclusivas de pastores, sem inferir autorização por proximidade temporal.

## Exclusão e integração com #509

Em 18/10/2026, a PR #509 ainda estava aberta, fora da base `65e2f1c5`.
A exclusão atual do inbox usa `delete_prayer_inbox_conversation`: valida admin
ativo e igreja no banco, coleta caminhos internamente, apaga a conversa e
retorna esses caminhos somente para limpeza de Storage após commit, sem
conteúdo na resposta HTTP. A cascata da associação e a limpeza de mídia
protegida têm teste local em PostgreSQL sintético.

Ao integrar #509, incluir os caminhos protegidos na fila durável de purga **na
mesma transação de exclusão**, antes da cascata, usando a autorização desse
serviço; não voltar a consultar `Message` como admin para coletar caminhos,
pois a RLS corretamente os oculta. Substituir a limpeza best-effort atual pela
fila da #509. Esta fatia não entrega exclusão de checkpoints/vetores nem
purga durável de mídia. Não aplicar migration nem ativar em produção sem
runbook de release e autorização nominal.


## Envio humano e histórico do modelo

Assumir o atendimento já cancela propostas pendentes pelo trigger existente
`prayer_handoff_cancel` e não concede acesso pastoral. Mesmo se houver coleta
ainda viva (estado legado ou concorrência), o envio humano não a integra.
Saídas humanas (texto/mídia) não são vinculadas à coleta; o trigger vincula
somente inbound da pessoa e outbound do agente com `kind=prayer`. O envio
humano monta a resposta com os valores do INSERT/RETURNING, sem `refresh`
obrigatório após a entrega. Isso remove a falha de releitura por RLS; não
oferece atomicidade entre Evolution e banco diante de outras falhas de commit.
Todas as mensagens associadas em `pedido_oracao_mensagem`, inclusive entradas,
correções, resumos e barreiras sem proposta, ficam fora do histórico do modelo.

## Rollback coordenado

A migration deve preceder o rollout do backend. O rollback da migration exige
rollback do código junto: a exclusão usa `delete_prayer_inbox_conversation` e
o histórico consulta `pedido_oracao_mensagem`. Remover essas estruturas com o
backend atual causa falhas. Manter gates fechados e seguir o rollback comentado
no SQL, com autorização explícita de privacidade antes de remover a proteção;
não reexpor histórico como procedimento de recuperação.
