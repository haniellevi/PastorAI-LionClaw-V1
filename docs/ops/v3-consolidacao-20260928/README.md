# V3: consolidação pelo WhatsApp

Fatia originalmente autorizada sobre PR435 `342f0ced7af53d2d7e708d99e3b92d54e7a3e22c`. Após o merge #435, a PR #436 foi retargetada para `main@8c6cc3cdb0fda0938edd43dd6988763c79872f8d`; a composição exige CI e nova revisão Sarah. O [plano aprovado](../mvp-v3-consolidacao-whatsapp-plano.md) e a [matriz de QA](QA-PLAN.md) definem o contrato. A validação local no commit de código `db3a4b8f136c6ca9f802b4dd494e806027f485a4` é histórica e não atesta a composição atual.

## Domínio e confirmação

Uma decisão individual usa o serviço canônico e abre sua consolidação. Visitante sem vínculo conserva o prazo de conexão de 24 horas; uma pessoa já vinculada não recebe esse prazo por inferência. Cada nova consolidação tem sua própria fonovisita. Totais agregados de decisões em relatórios não identificam pessoas e não abrem consolidações individuais automaticamente.

Consulta, confirmação de fonovisita e atribuição usam identidade e permissões derivadas no servidor. As escritas compartilham o serviço humano e a plataforma S3: resumo enviado, confirmação explícita, prazo de dez minutos, uso único e comprovante depois do commit. A etapa de fonovisita e sua tarefa são baixadas juntas; isso não conclui toda a consolidação. No painel, consolidações antigas sem tarefa canônica conservam o avanço humano da etapa, sem criar fila ou alerta retroativo. O WhatsApp continua exigindo a tarefa canônica. A atribuição sincroniza as tarefas abertas e invalida propostas baseadas em uma revisão anterior, inclusive se o responsável mudar de A para B e voltar para A.

O suporte de consentimento é uma proposta S3 para ativar os próprios lembretes de consolidação. Consultar a fila, aceitar um termo genérico ou possuir papel não ativa essa preferência. PARAR LEMBRETES e SAIR prevalecem e invalidam propostas antigas de ativação.

## Privacidade e elegibilidade

Somente o responsável atual recebe primeiro nome normalizado, tipo e prazo, em conversa individual. A identidade e a atribuição são revalidadas na consulta e antes do HTTP, inclusive em respostas inbound persistidas que aguardam entrega ou retry. O nome não entra no prompt do roteador. Coordenação sem atribuição àquela tarefa recebe somente contagens e códigos. Uma consulta pode combinar detalhes das próprias tarefas com códigos das demais, respeitando o escopo humano.

A resposta tem limite determinístico de dez pendências, prioriza as próprias e informa quantas restam no painel. O código técnico permite selecionar a tarefa sem transmitir nomes ao roteador. Para comandos V3, texto residual que não caiba integralmente na intenção validada leva a atendimento humano, sem encaminhar o texto livre ao modelo. Essa restrição evita apagar sinais de risco durante a projeção; os comandos determinísticos de opt-out continuam prioritários.

Telefone, sobrenome e contexto pastoral permanecem no painel autenticado. O link curto usa a tela existente `/#consolidar`, sem token, identificador ou PII na URL; o usuário seleciona o registro no painel. O link não concede acesso. Não existe encurtador externo ou login automático.

Coordenação e atribuição permanecem restritas a `admin`, `pastor` e `lider_consol`. O responsável atual também pode consultar e confirmar suas próprias tarefas conforme a permissão humana por tipo: `lider_celula` pode fonovisita; `lider_g12` pode fonovisita e conexão à célula. Esses papéis não recebem códigos de tarefas alheias nem poder gerencial. AppUser, Pessoa, papel e atribuição são revalidados no servidor; o link do painel conserva suas permissões Clerk existentes.

## Comandos da primeira fatia

Os exemplos abaixo documentam a gramática restrita do candidato, não autorizam ativação. Use o código exibido na consulta; o marcador `CODIGO` deve ser substituído pelo valor completo `P-` seguido de dez caracteres.

| Ação | Mensagem |
| --- | --- |
| Registrar decisão | `registrar decisão de NOME`, com pessoa e vínculo resolvidos sem ambiguidade no servidor |
| Consultar | `quais pendências de consolidação` |
| Concluir fonovisita | `confirmar fonovisita CODIGO` |
| Atribuir a si | `atribuir consolidação CODIGO para mim` |
| Atribuir a outra pessoa | `atribuir consolidação CODIGO para NOME`, com nome completo resolvido de forma única entre responsáveis elegíveis da igreja |
| Ativar os próprios lembretes | `ativar lembretes de consolidação` |

Toda escrita ainda exige o resumo entregue e uma mensagem separada `SIM` em até dez minutos. `PARAR LEMBRETES` desativa lembretes, e `SAIR` mantém precedência global. Formas não cobertas ou mensagens mistas podem exigir atendimento humano; esta fatia não promete compreensão irrestrita de texto livre.

## Alertas e transporte

Os alertas de abertura e prazo de conexão e de fonovisita usam apenas a outbox e o dispatcher V2b. Respostas inbound e recibos S3 conservam o worker existente. Não há transporte paralelo. Cada aviso vence 24 horas após seu instante previsto; a janela é 08:00 inclusive até 21:00 exclusive, em São Paulo, com teto V3 de dois avisos por destinatário/dia.

Claim e lease são persistidos antes do HTTP. O envio revalida origem, responsável, papel, consentimento, preferência, gates e prazo. A validação usa a barreira de revalidação imediatamente antes da chamada ao provedor; o commit libera os locks antes do HTTP. Há um intervalo inevitável entre esse commit e o provedor, sem promessa de atomicidade entre PostgreSQL e a rede. Resultado ambíguo continua terminal; a reserva diária é preservada. A fonovisita identifica sua consolidação exclusivamente pela tarefa canônica; a outbox não aceita um segundo vínculo de pai. Nenhuma troca de responsável reabre uma intenção já terminalizada para aquele destinatário. Se A voltar a ser responsável, a pendência continua consultável, mas a mesma finalidade/ocorrência não é reenviada automaticamente para A.

## Ativação prospectiva e rollback

### Ordem obrigatória da release futura

Com os gates V3 fechados, drenar processos antigos e aplicar `20260928_080000_whatsapp_consolidation_v3.sql` antes de publicar ou reiniciar backend e workers V3. Após autorização específica de banco, executar o inventário LID e a pré-verificação de schema abaixo no destino. Somente com reconciliação LID decidida e verificada, quando necessária, e `preflight_ok = 1` iniciar os binários novos; abrir gates exige decisão separada. Falha ou resultado inconclusivo exige **PARAR** e manter os binários antigos. Estes blocos não devem ser executados nesta missão de PR.

A ordem importa mesmo com flags V3 fechadas: mapeamentos ORM e caminhos de `work_queue`, `contacts`, `sla_engine`, `offboarding` e `ministerial_actions` usam colunas novas sem guarda da flag. Invertê-la pode causar `undefined_column` (`42703`) ou `undefined_table` (`42P01`), HTTP 500 e falhas dos workers. São exigidas `consolidacoes.origin_decision_id`, `consolidacoes.assignment_revision`, `work_queue_items.consolidacao_id`, `notification_outbox.consolidacao_id`, `notification_outbox.work_queue_item_id` e `public.consolidation_whatsapp_activation` com RLS habilitada e forçada. A role `authenticated` precisa de SELECT, INSERT e UPDATE na tabela de ativação, sem DELETE.

Antes desse restart, há um gate independente para identidades LID legadas. O parser corrigido usa o telefone de `remoteJidAlt` como identidade canônica, mas mensagens antigas `@lid` podem ter criado uma `Pessoa` e uma `Conversation` sob o número LID. A nova identidade telefônica pode abrir outra linha com `optout = false` e `estado = 'ia'`, perdendo a recusa e o atendimento humano da linha antiga. O relato sanitizado histórico aponta cerca de cinco Pessoas com telefones de 14 ou 15 dígitos; essa contagem não é prova do estado atual.

Com autorização de leitura própria no destino, executar o inventário literal abaixo **antes de iniciar backend ou workers novos**, usando acesso privado da role `postgres`. O resultado por identificador fica somente no registro privado da release; não copiar nomes, telefones, UUIDs, estados individuais ou outras informações pessoais para PR, notas, chat ou CI. Conferir `current_user`, endereço do servidor e visibilidade total contra inventário independente aprovado. Se role, alvo, contagem, linhas ou vínculo com telefone canônico forem desconhecidos, **PARAR**. O filtro é de triagem, não prova que todas as linhas são LID nem que não existem LIDs em outros formatos.

```sql
\set ON_ERROR_STOP on
BEGIN TRANSACTION READ ONLY;
SELECT current_user AS role_sql, inet_server_addr() AS servidor, inet_server_port() AS porta;
SELECT count(*) AS total_pessoas_visiveis FROM public.pessoas;
SELECT
  p.igreja_id,
  p.id AS pessoa_legada_id,
  length(p.telefone) AS comprimento_telefone,
  p.optout,
  p.arquivada_em IS NOT NULL AS arquivada,
  c.id AS conversa_legada_id,
  c.estado AS estado_conversa
FROM public.pessoas p
LEFT JOIN public.conversations c
  ON c.igreja_id = p.igreja_id AND c.pessoa_id = p.id
WHERE p.telefone ~ '^[0-9]{14,15}$'
ORDER BY p.igreja_id, p.id, c.id;
ROLLBACK;
```

Para cada candidata, um responsável humano autorizado precisa registrar em artefato privado a correspondência confiável LID↔telefone canônico, a decisão de reconciliação (merge de registro ou transporte de `optout` e estado humano), o executor e a verificação posterior. Nenhuma reconciliação é automática nesta PR. Se uma candidata tiver `optout = true` ou conversa `estado = 'humano'`, a nova identidade precisa conservar a restrição antes de qualquer inbound ou envio pelo binário novo. Se a correspondência não puder ser provada ou houver qualquer restrição sem transporte verificado, **PARAR** e manter os binários antigos. O inventário e a decisão são gate adicional ao preflight de schema e não autorizam abrir flags ou enviar mensagens.

Pré-verificação literal para `psql`, somente de leitura. `ON_ERROR_STOP` bloqueia erro, ausência ou resultado falso. Conferir `preflight_ok = 1`; resultado desconhecido nunca libera o restart.

```sql
\set ON_ERROR_STOP on
BEGIN TRANSACTION READ ONLY;
SELECT current_user AS role_sql, inet_server_addr() AS servidor, inet_server_port() AS porta;
WITH expected(table_name, column_name) AS (
  VALUES
    ('consolidacoes', 'origin_decision_id'),
    ('consolidacoes', 'assignment_revision'),
    ('work_queue_items', 'consolidacao_id'),
    ('notification_outbox', 'consolidacao_id'),
    ('notification_outbox', 'work_queue_item_id')
), columns_present AS (
  SELECT count(*) = 5 AS ok
  FROM expected e
  JOIN information_schema.columns c
    ON c.table_schema = 'public'
   AND c.table_name = e.table_name
   AND c.column_name = e.column_name
), activation AS (
  SELECT oid, relrowsecurity, relforcerowsecurity
  FROM pg_catalog.pg_class
  WHERE oid = to_regclass('public.consolidation_whatsapp_activation')
)
SELECT 1 / CASE WHEN
  (SELECT ok FROM columns_present) IS TRUE
  AND (SELECT relrowsecurity AND relforcerowsecurity FROM activation) IS TRUE
  AND (SELECT has_table_privilege('authenticated', oid, 'SELECT')
       AND has_table_privilege('authenticated', oid, 'INSERT')
       AND has_table_privilege('authenticated', oid, 'UPDATE')
       AND NOT has_table_privilege('authenticated', oid, 'DELETE')
       FROM activation) IS TRUE
  THEN 1 ELSE 0 END AS preflight_ok;
ROLLBACK;
```

No rollback de código, fechar gates e voltar aos binários anteriores, preservando schema e históricos até compensação aprovada. Não remover colunas enquanto houver processo V3.

A migration não cria nem preenche marcos de ativação. O worker registra o corte durável quando observa todos os gates abertos; tarefas anteriores continuam consultáveis e não geram alertas retroativos. A abertura de uma nova época exige um ciclo anterior comprovado com gates fechados, que feche o marcador e cancele a elegibilidade pendente. Um ciclo posterior aberto registra um corte estritamente posterior. O banco rejeita alterações do corte enquanto a época estiver aberta ou sendo fechada e rejeita retrocesso na reabertura.

Limite causal: se nenhum processo observou uma troca de flag de fechado para aberto, não há prova de uma nova época. Reiniciar ou editar a env não substitui a observação persistida exigida no runbook de ativação. Essa disciplina integra o gate futuro de release, fora desta missão local.

Rollback fecha os gates V3, confirma o marcador fechado e preserva históricos, resultados ambíguos e comprovantes; nunca reativa um consumidor antigo. Migrations anteriores congeladas permanecem byte a byte. A migration V3 é aditiva/idempotente, com FKs de tenant, RLS e permissões mínimas nas relações novas, sem conceder DELETE. As permissões de exclusão das tabelas legadas não são reclassificadas por esta fatia.

## Migration candidata

Arquivo: `backend/migrations/20260928_080000_whatsapp_consolidation_v3.sql`.
SHA-256: `267f619713f1e2c3ece030227ec387bcef3b76cfbba237f00568e1e347c5b82d`.
Os 86 arquivos SQL da base foram comparados byte a byte e permanecem intactos.
A prova local exercita aplicação e reaplicação do SQL candidato em PostgreSQL 17 descartável; não é evidência de aplicação em ambiente compartilhado.

## Verificação histórica do candidato original

| Prova | Resultado |
| --- | --- |
| Suíte offline integral, Python 3.13.14 | 5.998 passaram, zero falhas ou skips |
| Suíte RLS integral, PostgreSQL 17 descartável | 770 passaram, zero falhas ou skips |
| E2E V3 de turno real, incluídos na RLS | 22 passaram; repetidos na revisão independente |
| Entrega V3 pelo dispatcher comum, incluída na RLS | 25 passaram; repetidos na revisão independente |
| Migration literal, incluída na RLS | 15 passaram; repetidos na revisão independente |

[Resultados sanitizados](VALIDATION.json) registram a rodada histórica no commit `db3a4b8f`. O [manifesto de 39 pós-imagens](SOURCE-SNAPSHOT.json) identifica os arquivos de código, testes, migration e CI da composição atual; CI no head publicado ainda é necessário. O [parecer independente final anterior](REVIEW-FINAL-V3-INTEGRATED-ROUTING.md) foi emitido para o snapshot original. `REVIEW.md`, `REVIEW-FINAL-V3-INTEGRATED-ROUTING.md` e `review-inputs/` também são evidência histórica, sem atestar o head retargetado. O status `production sources frozen` do snapshot integrado se refere apenas ao recorte antigo, não ao estado de PROD nem ao head atual.

O E2E começa na mensagem inbound persistida, atravessa worker, identidade, catálogo, roteador, confirmação e persistência reais. Gates usam configuração sintética e provedores são simulados. Essa prova não cobre HTTP de ingresso, parser ou piloto real; o parser/JID e os gates inertes têm testes focais separados. O CI do head publicado ainda precisa passar antes de encaminhar a Sarah.

## Limites de entrega

Gates de V3 e notificações ficam desligados; allowlist vazia e release aprovada `None`. S3, agente ativo, piloto e envio real são cumulativos. Nenhuma execução local autoriza ativação, aplicação compartilhada, merge ou deploy. A main agora contém o ambiente local do PR432; não se afirma execução de `dev.sh reset` nem prova de painel/simulador nesta missão.

Próximo gate humano: Sarah revisar código, migration e evidências do candidato exato após CI verde.

## Delta das threads da PR436

O painel conserva o avanço de fonovisita legada sem criar tarefas retroativas. O responsável líder usa a permissão humana por tipo e somente sua atribuição atual; coordenação permanece separada. Comando V3 reconhecido sem capacidade leva a humano antes de qualquer modelo, inclusive após revogação de papel. A migration permanece intacta.

A revisão do delta repetiu 24 testes PG de domínio, 25 de entrega e 48 unitários de catálogo junto com 22 PG de turno. Na primeira repetição houve uma falha G12, com a tarefa ainda aberta após SIM e sem diagnóstico suficiente no teste. O autor não a reproduziu no módulo completo nem na mesma ordem. O teste foi reforçado para verificar proposta entregue, execução, âncora e recibo; a repetição independente dos 70 testes passou. A ocorrência fica registrada sem causa atribuída; não se apresenta a assertiva reforçada como correção de um defeito de produção comprovado.
