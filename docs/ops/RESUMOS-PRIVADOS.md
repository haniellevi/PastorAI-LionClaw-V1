# Resumo privado por conversa — fatia 3

Geração integrada na `main` (#526; identidade dedicada da #588, `bd673afa`),
desligada; a migration da #588 não foi aplicada em PROD. Não cria ficha por pessoa nem implementa pedido
de exclusão. A [retomada privada da fatia 4](RETOMADA-PRIVADA.md) acrescenta um
consumidor separado, também desligado por padrão. Deploy, migration remota,
credencial e ativação: **não verificados**.

## Conteúdo e acesso

Uma versão corrente por conversa, pessoa atribuída exclusivamente pelo servidor,
referências compostas às mensagens e suas datas. Rótulo: **derivado, pode errar**.
Não constitui conhecimento oficial nem prova de cadastro, consentimento ou ação.

O primeiro vocabulário é intencionalmente estreito: perguntas exatas de horários
de culto e matrícula/informações de UV/CD (`private_summary_topic`). A conversa
inteira deve ter de 1 a 40 mensagens de texto recebidas do contato, todas nesse
vocabulário. Qualquer saída, texto livre, terceiro, ambiguidade, mídia,
transcrição, contexto privilegiado ou associação/proposta de oração recusa a
conversa **antes** do modelo. Esse corte produz falsos negativos deliberados;
não promete classificar semanticamente qualquer conversa. Ampliar o vocabulário
exige mudança global versionada, avaliação sintética e revisão de privacidade.

O provedor recebe somente os códigos operacionais permitidos, sem nomes,
telefones, texto original, identidade ou correção humana. Sua saída estrita
seleciona um assunto das fontes; o servidor produz o texto em pt-BR, até 1.000
caracteres. Saída inválida, duplicada, cortada pelo provedor ou fora das opções é
recusada; não há truncamento, fallback ou retry externo automático.

A API exige sessão web, tela inbox e admin/pastor atualmente autorizado à origem.
A função de elegibilidade também exige leitor autorizado ou worker, impedindo sondagem por usuário comum. O banco revalida subject, usuário ativo, papel, matriz inbox, pessoa ativa,
telefone canônico não ambíguo, origem e revisão. Apagar não concede leitura.
Não há endpoint por pessoa nem busca/agregação. Respostas usam `private, no-store`.

- `GET /conversations/{id}/private-summary`: versão, estado, texto, fontes e datas.
- `PATCH /conversations/{id}/private-summary`: `version`, `correction` ou
  `incorrect: true`. Versão divergente retorna 409. Correção também deve ser uma
  pergunta operacional reconhecida; texto livre é recusado com 422.
- `POST /conversations/{id}/private-summary/generate`: solicita tarefa durável,
  retorna 202/ID; recusa origem não elegível ou release desligada com 409.

Correção é restrição vigente na mesma linha, não histórico de versões. Ela
prevalece inclusive se for feita durante a chamada externa. Nova mensagem comum
suspende o derivado; regeneração válida reaplica a correção sem chamar o modelo.
Marcar incorreto impede geração automática de texto, até outra correção humana.
Excluir/proteger fonte remove também correções derivadas. Não há checkpoint,
expiração de 30 dias ou retenção de versões antigas.

## Worker, orçamento e gates

`private_summary_tasks` persiste IDs, revisão, geração, solicitante e estado;
nenhum prompt ou conteúdo. O cron consome tarefas só pelo login dedicado
`private_summary_runtime` (seção abaixo). Duplicatas não
repetem a chamada. Novo pedido explícito recoloca a mesma tarefa `refused/budget_or_credential` em `queued`, sem duplicar; o worker revalida gates, credencial e orçamento antes de qualquer chamada. Outras recusas, inclusive resultado ambíguo do provedor, não são reenviadas. Reserva mensal atômica por igreja antes de cruzar o provedor;
falha, timeout ou crash conservam a reserva. Tarefa `running` abandonada por mais
de dois minutos vira `refused/provider_outcome_unknown`; não se presume sucesso,
não há nova chamada automática nem devolução de orçamento.

O teto usa microdólares de reserva conservadora: 100.000 (= USD 0,10) por tentativa,
para entrada limitada a códigos (menos de 2.048 bytes) e saída de até 512 tokens,
sem retries, nos três modelos fixos da allowlist existente. É um teto interno de
reserva, não conciliação de fatura. Preços/modelos devem ser reconferidos antes de
qualquer ativação; mudança de preço exige ajustar a reserva/allowlist primeiro.
A reutilização não chama o gerador: o consumidor separado da fatia 4 usa o
turno normal, sujeito ao custo e gates desse turno.

Todos precisam permitir geração: `APPROVED_RELEASE_ID` (**None**),
`APPROVED_IGREJA_IDS` (**vazia**), `private_summary_settings.enabled` (**false**) e
`monthly_limit_microusd` (**0**, nenhuma geração). Configuração ausente também
nega. Não há API para abrir esses gates. `ALLOW_REAL_SENDS` continua obrigatório
para o adaptador OpenAI real. `AgentConfig.ativo` e demais gates não são alterados.
Testes substituem exclusivamente o provedor e gates da fatia com valores
sintéticos; jamais ativam envios reais. Estado entregue: custo externo zero.

Leitura sob barreira compartilhada e lock de conversa → reserva/claim/commit →
chamada **sem sessão/transação/lock de igreja** → nova barreira e lock → revalidar
origem/revisão/geração/pessoa/credencial/gates/solicitante → publicar/commit.
Correção vigente é relida sob o lock de publicação. Exclusão durante a chamada
remove tarefa e impede ressurgimento local; não desfaz o que já foi enviado.

## Identidade dedicada do ciclo (candidata local, migration `20261030_140000`)

Integrada pela #588 (`bd673afa`; checks do SHA `b2978c5b` verdes antes do merge);
migration só em PG sintético, não aplicada em PROD; LOGIN não provisionado.

Descoberta, claim, reserva, leitura das projeções e publicação rodam só no login
`private_summary_runtime` (`PRIVATE_SUMMARY_DATABASE_URL`, distinta das demais
URLs; LOGIN NOBYPASSRLS, sem memberships). Cada transação prova a identidade,
o `search_path` fixo e a igreja, sem `SET ROLE` e sem fallback. Os gates de
código vêm antes de resolver a factory. Sem URL, com URL inválida ou com factory
principal injetada, a geração não roda e registra só
`private_summary_runtime_unavailable`. Se a identidade mudar entre o claim e a
publicação, a tarefa fica `running` e depois vira abandonada, sem nova chamada.

Grants só nas tabelas privadas: settings SELECT; tasks SELECT e
UPDATE(state, started_at, error_code), só de queued/running para
running/done/refused (nunca de volta a queued); resumos SELECT, INSERT/UPDATE
nas colunas do upsert (sem `human_correction` no UPDATE); fontes
SELECT/INSERT/DELETE. Policies `to private_summary_runtime` exigem igreja da
transação **e** sessão viva. As restritivas `request_suspends_*` valem só
`to authenticated` e não alcançam o runtime: um SELECT direto desse login lê
resumo e fontes da igreja fixada mesmo com pedido de exclusão pendente. O
caminho real valida a origem (`origin_valid`, que inclui pedido pendente e
opt-out) antes de cada leitura e publicação, mas não há suspensão equivalente
em toda consulta SQL; worker comprometido segue fora do escopo. Orçamento sem grant: reserva só por função de custo fixo 100.000.
Tabelas centrais só por seis funções tipadas: descoberta (só IDs; mesmo
predicado e ordem, mas agora com limite técnico de 1 a 100 igrejas aprovadas e
`limit` de 1 a 100, padrão 20; fora disso recusa com 22023), snapshot com
barreira e lock de conversa, fontes (ID e código, nunca texto), solicitante
(NULL segue confiável), credencial (mesmo filtro; allowlist no Python) e
reserva. Locks e verificações de FK provados em PG sintético com o LOGIN real.
O snapshot segura a barreira compartilhada `private-content:<igreja>` até o
COMMIT; `private_erasure_request` (migration `20261022_100000`) toma a mesma
barreira em modo exclusivo, então o caminho oficial não confirma pedido entre
o snapshot e a leitura das fontes. A recusa 55000 da projeção de fontes cobre
contorno da barreira (por exemplo INSERT manual): falha fechada, rollback e aviso
genérico, sem prova de corrida no caminho autorizado nem prova em produção.

Não muda: `enqueue`, `reserve_budget`, leitura, correção, enfileiramento web,
retomada, pedidos de exclusão e permissões antigas de `authenticated`. O login
principal (BYPASS) continua capaz de tudo isso: limite declarado. O runtime
comprometido ainda pode gravar resumo/fontes da igreja fixada, como o principal
já pode. O preflight acrescenta só as três funções cujo corpo lê tabela com
FORCE RLS (descoberta, fontes e reserva); snapshot, solicitante e credencial
leem diretamente só tabelas sem FORCE, que o dono das tabelas lê sem BYPASS
(com outro dono, falham fechadas), e entram como exclusões explícitas no teste
de completude do catálogo. A dependência transitiva do dono de `origin_valid`,
que herda `row_security=off` do chamador e lê tabelas com FORCE, não é contrato
do preflight: o preflight olha só o `proconfig` da própria função.
Antes de ativar: provisionar o LOGIN por decisão nominal e entregar a URL só ao
cron; hoje API, queue, cron e broadcast compartilham o mesmo `env_file`, então
essa separação **não** está entregue. Aplicação remota, dono real e URL por
processo: **não verificados**.

## Exclusão, invalidação e release

A migration `20261019_120001_private_conversation_summaries.sql` acrescenta FKs
compostas, ENABLE/FORCE RLS, revokes e funções SECURITY DEFINER com search_path
fixo. Amplia a mesma `private_delete_content` da #518: conta/remove resumos e
suas correções/fontes/tarefas antes de apagar mensagens, nos escopos conversa,
pessoa e igreja. Recibo declara texto já enviado ao provedor fora do alcance,
além de backups/cópias externas. A retenção externa permanece não verificada.

Triggers invalidam resumos/tarefas por edição/remoção da fonte; proteção de oração
ou criação de proposta apaga derivados; entrada de áudio (origem e âncora viva) e mensagem de mídia também apagam resumo, correção, fontes e tarefas. Remover a origem sensível não restaura o derivado. Troca de pessoa/telefone/responsável, arquivamento, opt-out e
mudança de célula/líder/vínculo canônico removem derivados, sem transferi-los.
O vínculo pessoa/conversa é sempre revalidado; identidade errada nunca é reparada
pelo modelo. Fonte movida para outra conversa é recusada pela FK composta.

Aplicar a cadeia ativa via `backend/scripts/migrate.py`, primeiro em PostgreSQL
sintético. `20261030_140000` nada revoga: o código anterior segue igual com
ela; o código novo sem ela só falharia com gates abertos. Conter o cron na
aplicação/rollback; o rollback comentado preserva dados e recusa LOGIN provisionado. Conter consumidores na atualização/rollback; publicar somente com
schema compatível. Rollback comentado restaura a função anterior antes de remover
tabelas/triggers; conteúdo apagado não é recuperável pelo rollback. Sem execução
remota autorizada nesta entrega. Revisão de Sarah: **RLS, migration e privacidade**.
