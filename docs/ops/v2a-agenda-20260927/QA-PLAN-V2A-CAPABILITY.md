# QA, capacidade V2a sem candidatos

## Contrato a provar

`consultar_agenda` é uma capacidade de leitura sem alvo. Quando ela for a única opção válida, o roteador deve executar B e C, pular D e devolver uma seleção com `tool="consultar_agenda"` e `handle=None`. O chamador só pode aceitá-la se o catálogo recém-reconstruído trouxer a mesma capacidade genérica do servidor.

Catálogo realmente vazio, catálogo malformado e qualquer ação mutante sem alvo devem resultar em `handoff` sem chamada ao modelo. `clarify` continua reservado às respostas explícitas `nenhuma` ou `nenhum` de um catálogo válido.

## Testes de roteamento puro

1. Com catálogo contendo somente `consultar_agenda` sem candidatos, o cliente falso recebe B e C, nunca D; a decisão é `selected`, com ferramenta agenda e handle nulo.
2. Com `catalog=()` ou opção inválida, a decisão é `handoff` e o cliente não recebe chamada.
3. Com zero candidatos em `registrar_decisao` ou `marcar_presenca`, a decisão é `handoff`, sem B, C ou D. A exceção sem alvo deve ser explícita para agenda, não uma regra implícita para qualquer ferramenta.
4. `nenhuma` em B e C, e `nenhum` em D de catálogo válido, continuam retornando `clarify` nos formatos atuais. Valores forjados em B, C ou D retornam `handoff` e não avançam para a etapa seguinte.
5. A opção genérica não contém título, id, descrição, mensagem, pessoa ou célula. Capturar os payloads B/C e afirmar essa ausência.

## E2E de capacidade real

Usar catálogo, roteador e `run_privileged_turn` reais, com falso somente para Choice e transporte Evolution.

1. Membro com vínculo confirmado, consentimento, config, credencial e flag ativos pede agenda. O catálogo real oferece somente a capacidade genérica, B/C escolhem agenda, D não ocorre e o outbound contém apenas a projeção permitida do evento. O falso Choice deve verificar `pool.checkedout() == 0` em B e C.
2. Líder vinculado percorre o mesmo caminho, sem ampliar dados de célula, participantes ou outra igreja. Repetir a captura dos prompts e a ausência de D.
3. Pedido de rascunhos de membro ou líder não emite challenge, não cria reply de agenda e não produz acesso editorial. Pastor ou admin com prova Clerk válida mantém o fluxo de rascunhos já coberto, também sem D.
4. Desabilitar a release, esvaziar a allowlist ou retirar o papel antes da aplicação da seleção faz o chamador recusar a capacidade. Não deve haver projeção nem outbound de agenda.

## Autoridade e injeção de mapping

1. Forjar `RoutingDecision(selected, tool="consultar_agenda", handle=None)` contra mapping sem a capacidade atual deve terminar em handoff, sem consulta ou resposta.
2. Um `CatalogTarget` de agenda com argumentos, resumo ou origem diferentes do catálogo atual não pode passar pela comparação de revalidação.
3. Forjar `handle=None` para uma ação mutante deve ser recusado antes de `prepare_action_proposal` ou serviço humano. Verificar ausência de proposal, efeito e outbound.
4. Mapping de tenant B, de conversa distinta ou de inbound distinto não autoriza a capacidade da conversa A.

## Retry, RLS e revalidação

1. Após falha retentável de transporte, alterar evento, remover papel, vencer prova de rascunho ou desligar a release suprime o intent pendente sem novo Choice nem novo envio.
2. Retry de agenda genérica preserva a âncora inbound e compara snapshot e texto atuais. Não pode reconstruir resposta com catálogo injetado ou enviar após mudança de tenant, conexão, telefone ou instância.
3. Em PostgreSQL descartável, escopo A lê e projeta somente Event de A; B não vê nem faz aparecer dado de A. Sem tenant scope, o serviço falha fechado antes da projeção.
4. O transporte ocorre depois do commit do reply. O teste de pool e uma sessão independente no falso Evolution devem confirmar que não há transação ou lock de Conversation aberto no HTTP.

## Critério de aceite

Passam os testes novos e as regressões C03 sem skip, inclusive o E2E de membro e líder, o negativo de ação mutante sem alvo, retry pós-revogação e RLS A/B. A prova deve referir o hash congelado do candidato e distinguir dados reais de fixtures sintéticas.

## Limites e próximo gate

Não há implementação nem aprovação deste contrato neste documento. A configuração efetiva de modelo e esforço não é exposta nesta sessão. O próximo gate é receber o patch congelado para revisão independente do código e dos testes discriminantes.
