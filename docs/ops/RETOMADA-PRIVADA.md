# Retomada privada — fatia 4 candidata e desligada

Comando inicial exato: `retomar conversa`. O turno S3 normal resolve a identidade,
constrói catálogo e roteia; só a resposta geral recebe contexto do resumo vigente
da própria pessoa/conversa. Nenhuma ferramenta, consulta por pessoa, agregação,
visão de líder ou ação nova foi adicionada. Sem resumo elegível segue o fluxo
existente. A fatia atende identidades já aceitas pelo S3; ampliar o atendimento
público e reconhecer retomadas em linguagem livre ficam para outra entrega.

Gates independentes: `PRIVATE_RESUME_APPROVED_RELEASE_ID=None`,
`PRIVATE_RESUME_APPROVED_IGREJA_IDS=frozenset()` e
`private_summary_settings.resume_enabled=false`. Não há API para habilitar.
Os gates de geração e seu orçamento continuam independentes. Nenhum gate de
WhatsApp, OpenAI real, Jev, broadcast, Brevo, Asaas ou AgentConfig foi aberto.

A migration `20261020_200000_private_resume.sql` mantém ENABLE/FORCE RLS e as
policies existentes. Quando a flag local permite, somente o INSERT do comando
exato de texto e a reserva de saída IA vazia deixam de invalidar o resumo.
Nenhuma dessas linhas vira fonte. Toda edição, saída com conteúdo, novo assunto,
mídia, oração e alteração de vínculo continuam invalidando. Não reativa resumo
suspenso. A resposta do próprio turno suspende o resumo: esta fatia permite uma
retomada de um resumo vigente, sem regeneração automática posterior.

Leitura exige worker sem subject e contexto WhatsApp revalidado pelo servidor,
igreja, pessoa, conversa, geração de exclusão e revisão iguais, origem ativa,
sem opt-out, fontes operacionais permitidas e ausência de oração/áudio protegidos.
Só o vocabulário fechado da #526 entra; correção humana corrente prevalece.
O rótulo é **derivado, pode errar** e o contexto não concede autoridade nem
substitui ferramentas. Nenhum texto do resumo vai para metadados de entrega.

O provedor é chamado sem sessão/lock aberto. Antes de persistir a resposta,
versão/revisão/geração e vínculo são conferidos novamente. Antes de transporte
e retry, o fluxo existente revalida o ator e a referência do resumo; só aceita
a revisão seguinte, causada pela própria resposta, sem mudanças intermediárias.
Falha fecha a entrega. Exclusão/proteção durante a chamada impede publicação;
texto já cruzado para o provedor permanece fora do alcance da exclusão local.

Aplicação: seguir [migrations](../../backend/migrations/README.md), com o runner
`backend/scripts/migrate.py`, primeiro em PostgreSQL local sintético. Rollback
comentado restaura o trigger anterior antes de remover a flag. Conter consumidores
antes de aplicar/reverter. Deploy, aplicação remota, retenção do provedor e
ativação: **não verificados**. WhatsApp permanece desligado.
