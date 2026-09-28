# QA e revisão independente, V2a Agenda por WhatsApp

## Base e escopo

Worktree de revisão: `/tmp/igreja12-v2a-agenda-review-20260927`, detached, limpo, em `3e8306e9dfd5e3dec3097f3e8a701829b4d7aa36`.

Esta fase cobre apenas consulta de agenda por papel. Não cobre migrations, lembretes, outbox, inscrição, alteração de evento, painel, provedor real ou V2b. A configuração efetiva de modelo e esforço não foi exposta por metadados desta revisão, portanto não é afirmada aqui.

## Princípio e contrato mínimo

A resposta é uma projeção determinística, tenant-scoped e read-only de `Event`, nunca uma autorização derivada de telefone, texto, `publico_alvo` ou escolha do modelo. O roteador pode escolher somente a ferramenta fechada `consultar_agenda`; ele não recebe IDs, títulos livres, descrição, mensagem de confirmação, destinatários ou dados de participantes.

O serviço deve retornar ocorrências tipadas, limitadas e reformatadas em template fixo. A consulta usa `Event.igreja_id` explícito além da RLS. Membro e líder só veem eventos com `status == confirmado`. Pastor ou admin só recebe rascunho quando o `PrivilegeContext` atual tem prova Clerk válida. Sem vínculo ativo, a rota de agenda não lê `Event`; só a projeção pública S2b permanece acessível.

O título atual é `Text` livre. `Event.status` defaulta para confirmado e `confirmado_por` é opcional, portanto nenhum deles por si só prova que o texto é institucional ou livre de PII. Para cada título exibido, o serviço deve confirmar `confirmado_em`, `confirmado_por`, AppUser ativo do mesmo tenant e papel pastor/admin, e aplicar política conservadora de título institucional. Legado, autoria ausente, título inseguro ou título acima de 120 caracteres usam somente o fallback fixo de `tipo`. Um blacklist de telefone/endereço não pode alegar detecção geral de nomes.

Descrição, `mensagem_confirmacao`, `publico_alvo`, destinatários, `google_event_id`, campos de notificação e endereços de célula não cruzam a projeção. O texto final contém somente rótulos fixos, tipo ou título aprovado, data, hora e recorrência canônica.

## Sequência exigida no turno

1. SAIR, opt-out, termo LGPD, handoff humano, confirmações S3 pendentes, `AgentConfig.ativo`, tenant e identidade são avaliados antes de catálogo, consulta ou Choice.
2. A flag `AGENDA_WHATSAPP_ENABLED_IGREJA_IDS` e `AGENDA_WHATSAPP_APPROVED_RELEASE_ID` são cumulativas. Lista vazia ou release `None` preserva o caminho legado e não consulta `Event`, nem chama Choice ou transporte novo.
3. A consulta local captura somente fatos necessários, sem lock persistir durante Choice ou transporte.
4. Depois de Choice e antes de persistir ou transportar a resposta, o serviço relê contexto, prova Clerk quando aplicável e projeção do evento. Perda de papel, termo, vínculo, prova, autoria do título, confirmação, evento ou segurança do título suprime a resposta pendente e faz handoff ou ausência honesta. Não envia o snapshot antigo.
5. Retry usa o inbound e a reserva existentes. Não gera outra escolha, outra resposta ou transporte duplicado. A resposta pendente é revalidada antes de cada envio.

## Matriz de testes obrigatórios

| Área | Prova discriminante |
| --- | --- |
| Flag e release | Flag vazia, tenant fora da lista e release `None` não abrem sessão de agenda, não consultam `Event`, não chamam Choice nem transportam. |
| Ordem de gates | SAIR, opt-out, termo vencido, humano, confirmação S3 pendente e `AgentConfig` inativo bloqueiam consulta antes do serviço de agenda. Use sentinela no leitor para provar ausência de SELECT. |
| Contexto e papéis | Telefone coincidente sem AppUser ativo fica público. Membro e líder confirmados veem somente confirmados. Pastor/admin sem prova Clerk não veem rascunho. Prova expirada, papel removido, AppUser desativado, vínculo ambíguo ou pessoa arquivada fazem handoff. |
| Tenant e RLS | Duas igrejas com eventos idênticos: leitura e handle de A nunca retornam B. PG17 deve executar sem `BYPASSRLS`, com predicado explícito `igreja_id`, incluindo tentativa de UUID de evento de B. |
| Publicidade | Conversa pública ou sem vínculo não consulta `Event`, ainda que `publico_alvo` inclua toda a igreja. Só os fatos S2b publicados podem responder. |
| Janela e recorrência | Padrão de sete dias, máximo de trinta, no máximo cinco ocorrências por página e ordenação estável. Recorrência semanal é expandida no servidor. Data, hora ou recorrência inválida não é inventada. Passado, ocorrência além do limite e duplicata não entram na resposta. |
| Projeção e privacidade | Mock e auditoria confirmam que SELECT, prompt, resposta e payload não carregam descrição, mensagem, alvo, telefone, convidados, endereço de célula ou ID do evento. O audit registra somente enum, contagem, estado e motivo técnico, sem título bruto. |
| Título institucional | Casos de telefone, endereço, nome sintético conhecido, delimitadores `[]{}()`, controles, zero-width, quebra de linha, markdown/JSON e 121 caracteres retornam fallback de `tipo`, sem truncar ou refletir fragmento bruto. Título verificavelmente institucional e até 120 caracteres aparece somente no template fixo. |
| Choice e handle | Enum, ferramenta, handle, schema ou timeout inválidos fazem handoff. Não há ID de evento em prompt, handle ou texto do usuário. Choice só seleciona a ferramenta fechada e não define tenant, papel, janela ou campos. |
| Revalidação | Durante Choice ou antes de retry, revogar papel, termo, prova, confirmação do evento, autoria do título ou apagar/editar o evento impede resposta stale. Edição segura pode ser reconsultada e reformatada; se não houver reconsulta atômica, a resposta é suprimida. |
| Concorrência e I/O | Dois workers do mesmo inbound deixam uma única reserva e no máximo um transporte. Fakes de Choice e Evolution verificam que não há transação ou lock aberto durante HTTP. Falha pré-envio pode recuperar a reserva; resultado ambíguo não é reenviado automaticamente. |
| Resposta de ausência | Sem evento autorizado ou sem dado válido retorna a frase aprovada de ausência e oferta à secretaria, sem LLM, sem inventar data e sem converter isso em handoff automático. |

## Arquivos e testes esperados no candidato

O candidato deve limitar mudanças ao serviço de leitura de agenda, catálogo e roteador S3, `privileged_turn` e testes correspondentes, com documentação de escopo. A revisão final verificará que nenhuma migration, interface, outbox, cron, `event_notify` ou transporte de lembrete entrou no diff.

Além dos testes unitários, a evidência mínima é uma suíte PG17 sintética com RLS para tenant e papel, um teste de retry pós-revogação/edição e uma prova de sessão sem transação durante Choice e transporte. O rollback permanece operacionalmente simples: flag V2a desligada e supressão das reservas próprias antes de qualquer reversão. Não há envio pendente V2a nesta fatia.

## Limites e próximo gate

Não há garantia de detectar qualquer nome humano em texto livre. A proteção aceitável nesta fatia é não exibir título cuja autorização institucional e segurança não sejam demonstráveis pelo servidor, usando o fallback fixo de `tipo`. O próximo gate é receber o patch congelado com hashes e evidência no SHA exato para revisão independente de implementação.

## Gate permanente após NO-GO do contrato sem candidatos

Toda capacidade nova precisa de E2E do turno completo, conforme AGENTS.md. Para V2a, provar com membro e líder: inbound persistido -> catálogo real sem candidatos de agenda -> route_privileged_message seleciona consultar_agenda após B/C -> privileged_turn persiste resposta correta -> transporte fake recebe essa resposta e a conversa permanece em IA. Não mockar catálogo, roteador, resolvedor de privilégios ou projeção de Event. O stub LLM deve falhar se D for chamado para agenda. Provar também catálogo realmente vazio, enum inválido, ausência de mapping autorizado e recusa de ação mutante sem alvo. O controle anterior com h1 continua apenas evidência histórica e não substitui este contrato.
