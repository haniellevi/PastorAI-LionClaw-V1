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

A integração com a main (incluindo #509, merge `da5a7c84`) preserva
`delete_private(scope="conversa")` e GET do recibo. A função
`private_delete_conversation` da #509 executa como SECURITY DEFINER: coleta
inclusive mídia das mensagens em `pedido_oracao_mensagem`, enfileira a limpeza
na mesma transação e apaga explicitamente mensagens antes da conversa para
suportar a FK composta sem cascata legada. As associações caem pela FK da mensagem.
Nenhum SELECT de mensagens como admin é usado para descobrir mídia. A função
antiga `delete_prayer_inbox_conversation` foi removida da migration ainda não aplicada.

HTTP retorna somente o recibo com IDs/contagens/estado, nunca conteúdo ou
caminhos. Storage é removido pelo consumidor durável da #509 após commit;
falha mantém tarefa pendente e caminho privado para repetição. O recibo só
conclui a mídia depois do DELETE do provedor e da remoção do caminho da fila.
O proprietário da função precisa ignorar FORCE RLS (BYPASSRLS/superusuário);
conferir isso no release, sem alterar privilégios para contornar teste.

Limites conferidos: #509 implementa somente conversa; escopos pessoa/igreja/reset
em `delete_private` ainda recusam execução. Arquivar Pessoa remove pedidos e
propostas pelo serviço existente, conservando barreiras sem proposta; não é
exclusão integral do histórico. A exclusão antiga de igreja usa sessão
privilegiada do console, coleta mídia antes das cascatas e possui fila própria
com namespaces de Storage; não depende de leitura como admin de tenant.
Não declarar pessoa/igreja/reset cobertos pelo recibo da #509. Novos derivados,
backups e cópias do provedor continuam fora do comprovante desta fatia.
Sem aplicação remota, deploy ou ativação; gates permanecem fechados.


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
rollback do código junto: o histórico consulta `pedido_oracao_mensagem`.
Restaurar a função de exclusão da migration #509 somente após remover as
associações, preservando recibos e tarefas duráveis. Remover essas estruturas com o
backend atual causa falhas. Manter gates fechados e seguir o rollback comentado
no SQL, com autorização explícita de privacidade antes de remover a proteção;
não reexpor histórico como procedimento de recuperação.

## Áudio de oração retido (candidato desligado)

Áudio recebido durante coleta protegida fica no `media_path` da mensagem,
exclusivo dos pastores, sem transcrição e sem captura pelo V1b de relatório.
O prazo da proposta limita seu processamento e confirmação, não a retenção:
se ela expirar antes do worker, o áudio permanece órfão de pedido confirmado,
protegido e sujeito à exclusão privada aprovada por conversa, pessoa ou igreja.
A purga de 24h do V1b não remove esse áudio. Não há cota de volume nesta fatia;
o acúmulo pode crescer inclusive com propostas expiradas ou canceladas.
Antes de futura ativação, recomenda-se medir objetos/bytes retidos por igreja,
idade e quantidade de áudios sem pedido confirmado, com alertas e definição de
cota futura. Não executar limpeza automática nem mudar retenção sem decisão.
