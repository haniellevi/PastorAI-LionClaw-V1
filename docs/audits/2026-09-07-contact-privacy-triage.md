# Triagem de contatos — encerramento técnico

**DONE / FREEZE.** Atualização final em `2026-09-08T02:23:03Z`
(`2026-09-07`, America/Sao_Paulo). Base local preservada em
`ccbbc786fb46d06da1cb24df787fda5b606f21bd`. Sem novo commit.
Esta seção é o estado corrente e substitui os estados BLOCKED históricos
preservados abaixo. Os oito locais restantes foram explicitamente resolvidos.

## Classificação final dos oito pontos

| Local do inventário anterior | Categoria final | Justificativa e tratamento |
|---|---|---|
| `backend/app/config.py:189` | c — configuração institucional | Dono confirmou remetente do produto; liberado somente alias exato `no-reply@igreja12.com.br`, junto de `contato@igreja12.com.br`. Campo operacional intocado; sem liberar o domínio inteiro |
| `backend/app/domain/phone.py:27` | c — exemplo técnico de formato | Docstring de `normalize_phone` reconhecida por AST, símbolo e SHA-256 exato; não é exceção para código executável ou telefone global |
| `backend/app/services/evolution.py:69` | c — exemplo técnico JID | Docstring de `numero_from_jid` reconhecida por AST, símbolo e SHA-256 exato; JIDs novos e código fora da docstring continuam examinados |
| `backend/tests/test_calendar_oauth.py:48` | d — fixture sintética | Proveniência confirmada pelo dono; domínio pessoal substituído por example.com, sem alterar identidade relativa ao cenário |
| `frontend/package-lock.json:5943` | c — metadado técnico de dependência | Apenas campo deprecated do pacote rimraf/glob, com texto exato e SHA-256 aprovado; lockfile intocado, sem ignorar outros campos/contatos |
| `frontend/src/components/calendario/CalendarConnectCard.test.ts:77` | d — fixture sintética | Domínio pessoal substituído por example.com |
| `frontend/src/lib/calendar-api.test.ts:242` | d — fixture sintética | Domínio pessoal substituído por example.com |
| `frontend/src/lib/calendar-api.test.ts:253` | d — assert sintético | Assert atualizado junto da fixture correspondente |

Categoria a: nenhum caso novo de PII real confirmado; a confirmação da natureza
sintética/institucional vem do dono, não de consulta a pessoas/domínios.
Categoria b: os placeholders de sete telas já saneados na rodada anterior
permanecem preservados. Categoria d: manifesto de conjuntos sintéticos
revisados em **81 arquivos de teste**; era 82 antes de o alias institucional
dispensar a exceção de uma fixture. Categoria c: máscaras, regex, decoradores,
DSNs e os contextos exatos acima. **Nenhuma pendência corrente nesta triagem.**

## Diff sanitizado desta rodada

- `test_source_contact_privacy.py`: dois aliases institucionais exatos;
  duas docstrings técnicas com binding AST/símbolo/hash; um campo de metadado
  com binding caminho/JSON/hash; testes adversariais para evitar generalização.
- `test_calendar_oauth.py`, `CalendarConnectCard.test.ts`,
  `calendar-api.test.ts`: domínio das fixtures/asserts passou para example.com.
  Nenhum endereço completo anterior é reproduzido neste relatório.
- `source_contact_synthetic_review.json`: reduzidas somente as exceções
  dispensadas pelo alias institucional; sem inclusão automática de contatos novos.
- Este inventário registra reclassificação c/d e evidências atuais.

No próprio guard não há literal de mailbox pessoal. Os testes NEGATIVOS
constroem sondas sintéticas em memória a partir do nome do provedor, para provar
que gmail/hotmail/outlook/yahoo continuam bloqueados. Trocar essas sondas por
um domínio reservado e esperar bloqueio invalidaria o teste; não foi feito.
Não há exceção para provedor pessoal nem autorização do domínio do produto
inteiro. Domínios não reservados de fixtures só passam no conjunto e arquivo
exatos confirmados pelo dono; alterar contato, quantidade ou localização exige
nova revisão.

Nenhuma linha funcional de `backend/app/config.py`, `phone.py`,
`evolution.py`, `event_notify.py` ou `frontend/package-lock.json` foi alterada.
Os exemplos .env citados pelo dono não precisaram ser abertos.

## Verificação final executada

| Verificação | Resultado real |
|---|---|
| Guard local, Python stdlib | **13/13 pass**, zero falhas, erros ou skips |
| Guard em cópia de fontes sem .git nem objetos históricos | **13/13 pass**, zero falhas, erros ou skips |
| Ocorrências pendentes nos dois modos | **0** |
| Pytest: calendar_oauth + source_contact_privacy | **126 passed**, zero falhas/skips, 5,56s |
| Vitest: legal-pages, CreateIgrejaModal, CalendarConnectCard, calendar-api | **75 passed**, 4 arquivos, Node 24.19.0 |
| git diff --check | exit 0 |

A cópia sem Git é mais restrita quanto à disponibilidade de histórico que
checkout raso. O guard usa apenas a árvore atual e o manifesto local: não
executa Git, não busca objetos e não converte ausência de base em skip.
Testes adicionais provam que copiar número para código executável, mudar
docstring, inserir código na mesma linha, trocar campo de dependência,
adicionar contato ou duplicar fixture continua falhando.

Pytest executado na imagem local
`pastorai-agent-local-validation-v1-backend:3799272`, com `--pull never`,
`--network none`, filesystem/source read-only, tmpfs temporário e ambiente
explícito sem credenciais. Nenhum banco ou serviço compartilhado foi acessado.
Vitest usou dependências já locais, sem instalação/rede.

## Efeitos, privacidade e escopo

Zero efeito externo nesta rodada: sem rede, commit, push, PR, merge, deploy,
banco, migration, worker, flags ou envio. Nenhum dado real novo nos arquivos/
artefatos; valores de contato não são reproduzidos na evidência.
Histórico Git preservado. Não é declaração de ausência global de toda PII:
caminhos protegidos, mídias e formatos fora do scanner não foram auditados.

O teste e a declaração do dono comprovam apenas o escopo desta triagem local.
Não aprovam runtime, consentimento, legalidade, destinatário ou operação.
Próximo passo que exige autorização: publicação destas mudanças locais na PR,
sem autorização de merge nesta missão.

---

# Histórico das rodadas anteriores (estados substituídos)

# Atualização da triagem após confirmação do dono

**Estado atual: BLOCKED / FREEZE.** Esta seção substitui os totais/pendências
históricos das seções seguintes; o inventário original foi preservado para
rastreabilidade e suas fixtures foram reclassificadas nominalmente.

## Confirmação e regra aplicada

O dono informou que a amostra de fixtures é sintética e sem titularidade real.
Isso é uma declaração de proveniência do dono, não consulta de titularidade,
registro de domínio ou autorização operacional. Domínio não reservado não
passa a ser universalmente seguro. Os contatos revisados são aceitos somente
no conjunto exato de cada arquivo de teste confirmado.

O guard usa o manifesto local
`backend/tests/source_contact_synthetic_review.json`: **82 arquivos de fixtures**,
com SHA-256 do conjunto de contatos não reservados e quantidade de ocorrências.
Não contém valores, não depende de Git/objeto base e não é autorização de envio.
Qualquer contato novo, alteração do conjunto, duplicação ou cópia para outro
arquivo exige revisão. Não há permissão global por domínio, por pasta de testes
ou por função mask_text. E-mails de provedores pessoais permanecem bloqueados,
inclusive se a fingerprint coincidir. Configuração/runtime não pode receber
exceção de fixture.

## Categorias finais desta rodada

| Categoria | Arquivos / resultado |
|---|---|
| a — PII real confirmada nova | Nenhuma titularidade real foi afirmada nesta rodada; três pontos confirmados anteriormente já estavam sanitizados |
| b — placeholders UI | Sete telas enumeradas no inventário; mantidas as substituições locais por exemplos reservados |
| c — sintaxe técnica | Decoradores, máscaras/regex, DSNs e parte sintática de JIDs; código preservado, parte telefônica examinada separadamente |
| d — fixtures confirmadas pelo dono | 82 arquivos exatos no manifesto; domínio não reservado mas fictício no contexto informado, testes de redação/validação, sem titularidade real segundo o dono |
| d — fixtures ainda incompatíveis com a proibição de provedores pessoais | Três arquivos, quatro ocorrências; confirmação de ficção registrada, mas não criada exceção para esses provedores |
| Fora de fixture / decisão pendente | Configuração de remetente, exemplos em docstrings de domínio e metadado de dependência; não classificados como fixture por inferência |

## Pendências atuais, sem valores

| Arquivo:linha | Motivo do bloqueio |
|---|---|
| `backend/app/config.py:189` | Campo de remetente de serviço; configuração operacional, não fixture; alteração fora do escopo runtime |
| `backend/app/domain/phone.py:27` | Exemplo concreto em docstring de domínio; necessita sanitização textual ou revisão própria, sem mudar normalização |
| `backend/app/services/evolution.py:69` | Exemplo concreto de JID em docstring; protocolo preservado, número não liberado globalmente |
| `backend/tests/test_calendar_oauth.py:48` | Fixture em provedor pessoal; substituir por domínio reservado antes de liberar |
| `frontend/package-lock.json:5943` | Contato em metadado de dependência; não é fixture de aplicação; não alterar lockfile para esconder alerta |
| `frontend/src/components/calendario/CalendarConnectCard.test.ts:77` | Fixture em provedor pessoal; substituir por domínio reservado |
| `frontend/src/lib/calendar-api.test.ts:242` | Fixture em provedor pessoal; substituir junto com assert relacionado |
| `frontend/src/lib/calendar-api.test.ts:253` | Assert da fixture em provedor pessoal |

## Resultado atual dos testes

- Local: **11 testes; 10 pass, 1 fail, 0 errors, 0 skips**.
- Cópia isolada sem .git nem objeto base: **11 testes; 10 pass, 1 fail,
  0 errors, 0 skips**.
- A única falha nos dois ambientes é a verificação da árvore atual:
  **8 linhas em 7 arquivos** acima. Não há falha de Git ou histórico.
- Os testes positivos/negativos provam que a revisão é restrita ao arquivo,
  conjunto, quantidade e contexto de fixture; não abre exceção para provedor
  pessoal, outro arquivo ou código operacional.
- `git diff --check`: exit 0. Nenhum teste remoto executado nesta rodada.

## Diff resumido e limites

- Guard: adicionada validação do manifesto local e comparação de fingerprint
  por fixture, com bloqueio prioritário de provedores pessoais e casos novos.
- Manifesto novo: somente caminhos, hashes e contagens de contatos confirmados
  sintéticos pelo dono.
- Inventário: reclassificação de fixtures antes pendentes como d, com a
  proveniência humana explícita; não reclassifica arquivos operacionais.
- Nenhuma nova alteração em fixture, runtime ou UI nesta rodada; alterações
  locais de placeholders da rodada anterior permanecem preservadas.
- Zero dado real novo nos artefatos adicionados e nenhuma reprodução de valores
  nesta entrega. Não se declara ausência global de PII na árvore/histórico.
- Zero rede ou efeito externo; sem commit/push/PR/merge, banco, flag ou deploy.
  Histórico intocado. O guard permanece deliberadamente vermelho até resolver
  os oito locais restantes, em vez de ampliar exceções silenciosamente.

---

## Registro histórico da triagem anterior (não é o status corrente)

# Triagem local de contatos — 2026-09-07 (America/Sao_Paulo)

Estado: **BLOCKED / FREEZE**. Sem aprovação de contatos pendentes.
Base de trabalho: `ccbbc786fb46d06da1cb24df787fda5b606f21bd`, branch
`chore/pii-working-tree-sanitization-v1`. Mudanças desta triagem ainda sem commit.
Fonte: leitura local de código/frontend/backend permitidos; nenhum segredo,
banco, rede ou verificação de titularidade. Valores não são registrados aqui.

## Critérios e limites

- (a) PII real identificável: exige evidência de titularidade, não apenas regex.
  Os três pontos confirmados pelo dono na missão anterior já foram sanitizados
  no commit base. Nesta rodada não se atribui titularidade a contatos desconhecidos.
- (b) Placeholder UI: trocar por domínio reservado ou DDD inválido inequívoco.
- (c) Formato técnico: máscara/regex sem contato literal, decorador Python,
  separador de DSN e sintaxe JID. JID não é e-mail; sua parte telefônica continua
  inspecionada. Separador de DSN não é e-mail; isto não audita credenciais.
- (d) Fixture claramente sintética: domínios example.com/org/net, .example,
  .test, .invalid ou telefone com DDD inválido. Estar em teste, usar dígitos
  repetidos ou domínio iniciado por example não prova ficção. Nenhuma isenção
  genérica por nome do arquivo, pasta de testes ou repetição numérica.
- A revisar: proveniência/titularidade não demonstrada. Não aprovar por inferência,
  não incluir em allowlist e não substituir em massa relações de igualdade/
  normalização sem validar a suíte correspondente.
- Excluídos explicitamente da leitura: caminhos protegidos do AGENTS, mídias,
  dumps, backups, dependências, caches e links simbólicos. Scanner limitado às
  extensões de fonte declaradas em frontend/backend, não a todo tipo de PII.
- A existência do alias institucional não atesta que a caixa exista/esteja
  monitorada. Nenhum runtime, serviço de envio ou flag foi alterado.

## Tabela de classificação

O detector anterior marcou 357 ocorrências em 352 grupos (arquivo/linha/tipo),
distribuídas por 88 arquivos. Uma linha pode conter mais de um grupo.

| Categoria | Ocorrências originais | Arquivos / ação |
|---|---:|---|
| a — PII confirmada nova | 0 confirmadas nesta rodada | Não inferir que desconhecido é seguro; pendências abaixo |
| b — UI | 9 | 7 arquivos listados abaixo; placeholders sanitizados |
| c — sintaxe técnica | 30 | Detalhe nominal no inventário; JIDs ainda passam pelo detector numérico |
| d — fixture inequivocamente falsa entre os alertas originais | 0 confirmadas | Exemplos reservados já eram aceitos; fixtures plausíveis ficam pendentes |
| A revisar | 318 | Arquivo/linha de cada grupo abaixo; sem allowlist automática |

Arquivos de UI alterados (somente literais de placeholder):

- `frontend/src/components/admin/AdminLoginScreen.tsx`
- `frontend/src/components/admin/ChurchPage.tsx`
- `frontend/src/components/admin/CreateIgrejaModal.tsx`
- `frontend/src/components/calendario/CalendarConnectCard.tsx`
- `frontend/src/components/config/EquipeScreen.tsx`
- `frontend/src/components/contacts/NewContactModal.tsx`
- `frontend/src/components/login/LoginScreen.tsx`

Diff sanitizado das substituições: e-mail anterior omitido → `usuario@example.com`;
telefone anterior omitido → `5500000000000`. Nenhuma alteração de handlers,
validação de domínio, chamada de API ou lógica de envio.

## Guard refinado

`backend/tests/test_source_contact_privacy.py` não usa subprocess/Git,
git show, SHA-base ou comparação histórica. Percorre a árvore atual, inclusive
fonte nova, sem atravessar diretórios protegidos, dependências ou symlinks.
Falhas relatam apenas arquivo/linha. Não converte ausência de Git em skip.

Aceita os domínios reservados estritos e o alias institucional previamente
autorizado, não qualquer domínio começando por example. Máscaras/regex não são
números concretos. Reconhece decorador escapado, JID numérico (com inspeção
telefônica independente) e separador de autoridade PostgreSQL/Redis com único @.
Telefone plausível continua bloqueado mesmo com dígitos repetidos. O escopo
numérico cobre a representação com DDI brasileiro e variantes legadas, não
garante identificar todo contato local, concatenado ou codificado.

## Testes realmente executados

- Local: **8 testes, 7 pass, 1 fail, 0 errors, 0 skips**.
- Cópia isolada de fontes permitidas sem diretório .git e sem objetos históricos:
  **8 testes, 7 pass, 1 fail, 0 errors, 0 skips**. Resultado idêntico, sem erro Git.
  A cópia sem Git é mais restrita quanto a objetos disponíveis que checkout raso.
- Única falha nos dois ambientes:
  `test_current_tree_has_no_unreviewed_contacts`, por **349 linhas em 86 arquivos**.
  Não são 349 pessoas nem comprovação de PII; são locais a revisar.
  O número difere da triagem inicial porque o detector cobre também telefone
  legado sem nono dígito e porque os placeholders/falsos positivos foram tratados.
- Testes frontend: **62 pass em 3 arquivos**, Node 24.19.0, dependências já locais.
  Recorte: legal-pages, CreateIgrejaModal e CalendarConnectCard. Não é toda a suíte UI.
- `git diff --check`: exit 0.
- Não houve execução do CI remoto nesta rodada.

## Inventário dos alertas originais

Localizações referentes ao commit base antes das alterações desta rodada.
Agrupamento repete linha quando há tipos/contatos diferentes, sem seus valores.

| Arquivo:linha | Tipo | Quantidade | Categoria | Justificativa / decisão |
|---|---|---:|---|---|
| `backend/app/config.py:189` | email | 1 | A revisar | Contato plausível; titularidade não comprovada |
| `backend/app/domain/phone.py:27` | phone | 1 | A revisar | Contato plausível; titularidade não comprovada |
| `backend/app/services/evolution.py:69` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/app/services/evolution.py:69` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/app/services/evolution.py:69` | phone | 2 | A revisar | Contato plausível; titularidade não comprovada |
| `backend/tests/conftest.py:506` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_agenda_recipients_evt7_pr2.py:147` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_agent_hygiene.py:313` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_agent_hygiene.py:382` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_agent_orchestrator.py:174` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_agent_orchestrator.py:174` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_agent_orchestrator.py:176` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_agent_orchestrator.py:177` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_agent_orchestrator.py:182` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_agent_orchestrator.py:182` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_agent_orchestrator.py:187` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_agent_orchestrator.py:188` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_agent_orchestrator.py:246` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_agent_orchestrator.py:266` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_agent_orchestrator.py:267` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_auth_activate.py:144` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_auth_activate.py:176` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_auth_activate.py:469` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_auth_login.py:32` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_auth_login.py:39` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_auth_login.py:107` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_auth_login.py:125` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_auth_login.py:151` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_auth_login.py:168` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_backfill_whatsapp_numero_tipo.py:74` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_backfill_whatsapp_numero_tipo.py:80` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_billing_complimentary_concurrency.py:841` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_brevo_email_templates.py:20` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_broadcast_delivery.py:119` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_broadcast_delivery.py:132` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_broadcast_delivery.py:140` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_broadcast_delivery.py:141` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_broadcast_delivery.py:142` | phone | 2 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_broadcast_delivery.py:143` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_broadcast_delivery.py:308` | phone | 2 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_calendar_oauth.py:46` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_calendar_oauth.py:48` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_calendar_oauth.py:1812` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_calendar_oauth.py:2190` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_calendar_oauth.py:2199` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_calendar_oauth.py:2206` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_calendar_oauth.py:2207` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_calendar_oauth.py:2208` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_calendar_oauth.py:2209` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_calendar_oauth.py:2211` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_calendar_oauth_concurrency.py:48` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_calendar_oauth_concurrency.py:50` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_calendar_oauth_concurrency.py:145` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_calendar_oauth_concurrency.py:192` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_cell_discipulo.py:369` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_cell_lider.py:570` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_cells_scope.py:156` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_celula_membro_service.py:701` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_celula_membro_service.py:742` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_dedup_tenant.py:165` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_dedup_tenant.py:185` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_dedup_tenant.py:209` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_dedup_tenant.py:211` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_dedup_tenant.py:231` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_dedup_tenant.py:233` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_dedup_tenant.py:247` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_dedup_tenant.py:262` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_dedup_tenant.py:275` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_detail.py:73` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_detail.py:74` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_filters.py:163` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_link_cell.py:188` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_link_cell.py:199` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_link_cell.py:210` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_reactivate_communications.py:106` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_unarchive.py:114` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_update.py:69` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_update.py:69` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_update.py:119` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_update.py:125` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_contacts_update.py:130` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_conversations_domain.py:76` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_conversations_domain.py:76` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_conversations_domain.py:111` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_conversations_media_limits.py:295` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_d2b2b2_decision_payload_schema.py:307` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_d2b2b2_decision_payload_schema.py:339` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_d2b2b2_decision_payload_schema.py:425` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_d2b2b2_decision_payload_schema.py:431` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_descendencias_scope.py:103` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_domain_logic.py:30` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_domain_logic.py:40` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_event_notify_evt7.py:119` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_event_notify_evt7.py:165` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_event_notify_evt7.py:182` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_event_notify_evt7.py:194` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_event_recipients_evt8_pr2.py:78` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_events_confirm_toctou.py:131` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_events_confirm_toctou.py:135` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_events_crud_evt2.py:145` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_events_crud_evt2.py:695` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_events_crud_evt2.py:721` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_events_crud_evt2.py:726` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_events_crud_evt2.py:730` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_events_crud_evt2.py:735` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_events_crud_evt2.py:744` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_events_crud_evt2.py:749` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_evolution_service.py:165` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_evolution_service.py:321` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_evolution_service.py:349` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_evolution_service.py:357` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_evolution_service.py:371` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_evolution_service.py:481` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_evolution_service.py:486` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_evolution_service.py:529` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_evolution_service.py:559` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_messages_inbound_idempotency.py:158` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_messages_inbound_idempotency.py:180` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_messages_inbound_idempotency.py:228` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_messages_inbound_idempotency.py:546` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_messages_inbound_idempotency.py:546` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_messages_inbound_idempotency.py:612` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_messages_inbound_idempotency.py:670` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_messages_inbound_idempotency.py:1139` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_migration_history_environment_identity_preflight.py:919` | email | 1 | c | DSN sintético de teste; não endereço de e-mail |
| `backend/tests/test_new_migration.py:455` | email | 1 | c | Decorador Python em código de teste, não endereço |
| `backend/tests/test_new_migration.py:457` | email | 1 | c | Decorador Python em código de teste, não endereço |
| `backend/tests/test_new_migration.py:459` | email | 1 | c | Decorador Python em código de teste, não endereço |
| `backend/tests/test_outbound_guard.py:49` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_outbound_guard.py:147` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_outbound_guard.py:153` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_outbound_guard.py:201` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_outbound_guard.py:246` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_outbound_guard.py:361` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_outbound_guard.py:369` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_outbound_guard.py:377` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_outbound_guard.py:380` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_outbound_guard.py:429` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_outbound_guard.py:506` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_outbound_guard.py:509` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_outbound_guard.py:515` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_outbound_guard.py:515` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_outbound_guard.py:541` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_outbound_guard.py:549` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_outbound_guard.py:550` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_password_reset_single_use.py:303` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_password_reset_single_use.py:326` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_password_reset_single_use.py:349` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_password_reset_single_use.py:356` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_offboarding_router.py:57` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_offboarding_service.py:466` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_offboarding_service.py:584` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_offboarding_service.py:646` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_offboarding_service.py:653` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_offboarding_service.py:1023` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_offboarding_service.py:1403` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_offboarding_service.py:1648` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_offboarding_service.py:1820` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_offboarding_service.py:2008` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_offboarding_service.py:2195` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_offboarding_service.py:2266` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_offboarding_service.py:2344` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_offboarding_service.py:2402` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_telefone_unique_concurrency.py:310` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_telefone_unique_concurrency.py:311` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_telefone_unique_concurrency.py:312` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pessoa_telefone_unique_concurrency.py:528` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pipeline_assign_consolidador.py:122` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pipeline_csim.py:94` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_pipeline_scope.py:144` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:323` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:330` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:391` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:407` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:415` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:429` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:445` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:857` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:869` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:878` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:885` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:893` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:1059` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:1382` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:1400` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:1535` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:1547` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:1575` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:1579` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:1581` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:1594` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:1606` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:1622` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:1640` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:1933` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:2109` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:2118` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_platform_admin.py:2140` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_purpose_consent_service.py:175` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_rate_limit.py:125` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_rate_limit.py:127` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_rate_limit.py:130` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_rate_limit.py:148` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_rate_limit.py:157` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_rate_limit.py:246` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_rate_limit.py:276` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_rate_limit.py:352` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_rate_limit.py:373` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_rate_limit.py:396` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_rate_limit.py:430` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_rate_limit.py:431` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_rate_limit.py:443` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_rate_limit.py:455` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_rate_limit.py:468` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_readiness.py:113` | email | 1 | c | DSN sintético de teste; não endereço de e-mail |
| `backend/tests/test_rls_guard.py:23` | email | 1 | c | DSN sintético de teste; não endereço de e-mail |
| `backend/tests/test_rls_guard.py:25` | email | 1 | c | DSN sintético de teste; não endereço de e-mail |
| `backend/tests/test_rls_guard.py:27` | email | 1 | c | DSN sintético de teste; não endereço de e-mail |
| `backend/tests/test_secrets_crypto.py:54` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_secrets_crypto.py:57` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_secrets_crypto.py:62` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_secrets_crypto.py:65` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_sla_engine.py:278` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_sla_engine.py:281` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_sla_engine.py:290` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_sla_engine.py:305` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_sla_engine.py:308` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_sla_engine.py:317` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_sla_engine.py:380` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_sla_engine.py:383` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_sla_engine.py:452` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_sla_engine.py:455` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_sla_engine.py:473` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_sla_engine.py:496` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_sla_engine.py:499` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_sla_engine.py:508` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_sprint_routers_validation.py:101` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_subscription_autoupgrade_notify.py:207` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_subscription_autoupgrade_notify.py:213` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_inbox_lookup.py:98` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:186` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:228` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:247` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:269` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:282` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:287` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:301` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:316` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:332` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:347` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:348` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:357` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:370` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:389` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:409` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:428` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:452` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_invite.py:458` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_lookup.py:116` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_revoke.py:102` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_team_roles.py:128` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_identity.py:151` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_routers.py:210` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_routers.py:1053` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_routers.py:1062` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_routers.py:1064` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_routers.py:1101` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_routers.py:1183` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_routers.py:1191` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_routers.py:1201` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_routers.py:1233` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_routers.py:1314` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_whatsapp_routers.py:1314` | phone | 2 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_routers.py:1315` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_whatsapp_routers.py:1315` | phone | 2 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_routers.py:1327` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_whatsapp_routers.py:1333` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_whatsapp_routers.py:1336` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_whatsapp_routers.py:1337` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_whatsapp_worker.py:288` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_whatsapp_worker.py:288` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:341` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:345` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:369` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:391` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_whatsapp_worker.py:405` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:414` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_whatsapp_worker.py:430` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:446` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_whatsapp_worker.py:460` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:475` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_whatsapp_worker.py:493` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:566` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:569` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:689` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_whatsapp_worker.py:703` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_whatsapp_worker.py:706` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_whatsapp_worker.py:722` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:725` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:745` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:747` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:770` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_whatsapp_worker.py:770` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:946` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:948` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:1019` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:1031` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:1234` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:1243` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:1339` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:1621` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_whatsapp_worker.py:1643` | email | 1 | c | Identificador de protocolo; parte numérica examinada separadamente |
| `backend/tests/test_work_queue_assign.py:183` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `backend/tests/test_work_queue_message.py:165` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/package-lock.json:5943` | email | 1 | A revisar | Contato plausível; titularidade não comprovada |
| `frontend/src/components/admin/AdminLoginScreen.tsx:76` | email | 1 | b | Placeholder de UI; substituir por exemplo reservado |
| `frontend/src/components/admin/AuditModal.test.ts:86` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/admin/AuditModal.test.ts:99` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/admin/ChurchPage.tsx:999` | email | 1 | b | Placeholder de UI; substituir por exemplo reservado |
| `frontend/src/components/admin/CreateIgrejaModal.test.ts:170` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/admin/CreateIgrejaModal.test.ts:178` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/admin/CreateIgrejaModal.test.ts:189` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/admin/CreateIgrejaModal.test.ts:196` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/admin/CreateIgrejaModal.test.ts:207` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/admin/CreateIgrejaModal.test.ts:222` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/admin/CreateIgrejaModal.tsx:164` | email | 1 | b | Placeholder de UI; substituir por exemplo reservado |
| `frontend/src/components/calendario/CalendarConnectCard.test.ts:76` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/calendario/CalendarConnectCard.test.ts:77` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/calendario/CalendarConnectCard.test.ts:271` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/calendario/CalendarConnectCard.tsx:640` | email | 1 | b | Placeholder de UI; substituir por exemplo reservado |
| `frontend/src/components/central-celula/ManageCellsPanel.transfer-remove.test.ts:84` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/config/EquipeScreen.tsx:625` | email | 1 | b | Placeholder de UI; substituir por exemplo reservado |
| `frontend/src/components/config/EquipeScreen.tsx:667` | email | 1 | b | Placeholder de UI; substituir por exemplo reservado |
| `frontend/src/components/contacts/ArchiveContactModal.test.ts:30` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/contacts/ContatosScreen.test.ts:84` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/contacts/ContatosScreen.test.ts:124` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/contacts/ContatosScreen.test.ts:502` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/contacts/ContatosScreen.unarchive.test.ts:75` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/contacts/ContatosScreen.unarchive.test.ts:97` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/contacts/GanharScreen.navigation.test.ts:70` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/contacts/NewContactModal.tsx:82` | phone | 1 | b | Placeholder de UI; substituir por exemplo reservado |
| `frontend/src/components/inbox/ContactPanel.test.ts:58` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/inbox/ContactPanel.test.ts:123` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/inbox/ConversationList.test.ts:30` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/inbox/ConversationThread.test.ts:26` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/inbox/conversation-format.test.ts:20` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/components/login/LoginScreen.tsx:347` | email | 1 | b | Placeholder de UI; substituir por exemplo reservado |
| `frontend/src/components/login/LoginScreen.tsx:409` | email | 1 | b | Placeholder de UI; substituir por exemplo reservado |
| `frontend/src/components/minha-celula/MeetingReportForm.flow.test.ts:64` | phone | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/lib/calendar-api.test.ts:28` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/lib/calendar-api.test.ts:242` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |
| `frontend/src/lib/calendar-api.test.ts:253` | email | 1 | d — confirmação do dono | Domínio não reservado/contato de teste confirmado sintético pelo dono; contexto de redação/validação; sem titularidade real segundo o dono. Provedor pessoal continua bloqueado. |

## Pendências atuais (sem valores)

Todas as linhas a seguir continuam bloqueando o guard, sem classificação
positiva automática. Fixtures plausíveis necessitam revisão/substituição
coerente com normalização, deduplicação, JID e asserts relacionados. A configuração
de remetente de serviço e metadados de dependência exigem decisão de escopo:
não mudar runtime nem lockfile para esconder alerta.

- `backend/app/config.py:189` — a revisar.
- `backend/app/domain/phone.py:27` — a revisar.
- `backend/app/services/evolution.py:69` — a revisar.
- `backend/tests/conftest.py:506` — a revisar.
- `backend/tests/test_agenda_recipients_evt7_pr2.py:147` — a revisar.
- `backend/tests/test_agent_hygiene.py:313` — a revisar.
- `backend/tests/test_agent_hygiene.py:382` — a revisar.
- `backend/tests/test_agent_orchestrator.py:174` — a revisar.
- `backend/tests/test_agent_orchestrator.py:176` — a revisar.
- `backend/tests/test_agent_orchestrator.py:177` — a revisar.
- `backend/tests/test_agent_orchestrator.py:182` — a revisar.
- `backend/tests/test_agent_orchestrator.py:187` — a revisar.
- `backend/tests/test_agent_orchestrator.py:188` — a revisar.
- `backend/tests/test_agent_orchestrator.py:246` — a revisar.
- `backend/tests/test_agent_orchestrator.py:266` — a revisar.
- `backend/tests/test_agent_orchestrator.py:267` — a revisar.
- `backend/tests/test_agent_turn_identity.py:426` — a revisar.
- `backend/tests/test_auth_activate.py:144` — a revisar.
- `backend/tests/test_auth_activate.py:176` — a revisar.
- `backend/tests/test_auth_activate.py:469` — a revisar.
- `backend/tests/test_auth_login.py:32` — a revisar.
- `backend/tests/test_auth_login.py:39` — a revisar.
- `backend/tests/test_auth_login.py:107` — a revisar.
- `backend/tests/test_auth_login.py:125` — a revisar.
- `backend/tests/test_auth_login.py:151` — a revisar.
- `backend/tests/test_auth_login.py:168` — a revisar.
- `backend/tests/test_backfill_whatsapp_numero_tipo.py:72` — a revisar.
- `backend/tests/test_backfill_whatsapp_numero_tipo.py:74` — a revisar.
- `backend/tests/test_backfill_whatsapp_numero_tipo.py:80` — a revisar.
- `backend/tests/test_billing_complimentary_concurrency.py:841` — a revisar.
- `backend/tests/test_brevo_email_templates.py:20` — a revisar.
- `backend/tests/test_broadcast_delivery.py:119` — a revisar.
- `backend/tests/test_broadcast_delivery.py:132` — a revisar.
- `backend/tests/test_broadcast_delivery.py:140` — a revisar.
- `backend/tests/test_broadcast_delivery.py:141` — a revisar.
- `backend/tests/test_broadcast_delivery.py:142` — a revisar.
- `backend/tests/test_broadcast_delivery.py:143` — a revisar.
- `backend/tests/test_broadcast_delivery.py:158` — a revisar.
- `backend/tests/test_broadcast_delivery.py:308` — a revisar.
- `backend/tests/test_calendar_oauth.py:46` — a revisar.
- `backend/tests/test_calendar_oauth.py:48` — a revisar.
- `backend/tests/test_calendar_oauth.py:1812` — a revisar.
- `backend/tests/test_calendar_oauth.py:2190` — a revisar.
- `backend/tests/test_calendar_oauth.py:2199` — a revisar.
- `backend/tests/test_calendar_oauth.py:2206` — a revisar.
- `backend/tests/test_calendar_oauth.py:2207` — a revisar.
- `backend/tests/test_calendar_oauth.py:2208` — a revisar.
- `backend/tests/test_calendar_oauth.py:2209` — a revisar.
- `backend/tests/test_calendar_oauth.py:2211` — a revisar.
- `backend/tests/test_calendar_oauth_concurrency.py:48` — a revisar.
- `backend/tests/test_calendar_oauth_concurrency.py:50` — a revisar.
- `backend/tests/test_calendar_oauth_concurrency.py:145` — a revisar.
- `backend/tests/test_calendar_oauth_concurrency.py:192` — a revisar.
- `backend/tests/test_cell_discipulo.py:369` — a revisar.
- `backend/tests/test_cell_lider.py:570` — a revisar.
- `backend/tests/test_cell_report_application.py:33` — a revisar.
- `backend/tests/test_cell_report_legacy_snapshot.py:20` — a revisar.
- `backend/tests/test_cell_report_meeting_resolver.py:21` — a revisar.
- `backend/tests/test_cell_report_pending_proposal.py:140` — a revisar.
- `backend/tests/test_cell_report_turn_uow.py:40` — a revisar.
- `backend/tests/test_cell_report_turn_uow.py:41` — a revisar.
- `backend/tests/test_cell_report_workflow.py:613` — a revisar.
- `backend/tests/test_cell_report_workflow.py:659` — a revisar.
- `backend/tests/test_cells_scope.py:156` — a revisar.
- `backend/tests/test_celula_membro_service.py:701` — a revisar.
- `backend/tests/test_celula_membro_service.py:702` — a revisar.
- `backend/tests/test_celula_membro_service.py:722` — a revisar.
- `backend/tests/test_celula_membro_service.py:742` — a revisar.
- `backend/tests/test_celula_membro_service.py:743` — a revisar.
- `backend/tests/test_contacts_dedup_tenant.py:165` — a revisar.
- `backend/tests/test_contacts_dedup_tenant.py:185` — a revisar.
- `backend/tests/test_contacts_dedup_tenant.py:209` — a revisar.
- `backend/tests/test_contacts_dedup_tenant.py:211` — a revisar.
- `backend/tests/test_contacts_dedup_tenant.py:231` — a revisar.
- `backend/tests/test_contacts_dedup_tenant.py:233` — a revisar.
- `backend/tests/test_contacts_dedup_tenant.py:247` — a revisar.
- `backend/tests/test_contacts_dedup_tenant.py:262` — a revisar.
- `backend/tests/test_contacts_dedup_tenant.py:275` — a revisar.
- `backend/tests/test_contacts_detail.py:73` — a revisar.
- `backend/tests/test_contacts_detail.py:74` — a revisar.
- `backend/tests/test_contacts_filters.py:163` — a revisar.
- `backend/tests/test_contacts_link_cell.py:188` — a revisar.
- `backend/tests/test_contacts_link_cell.py:199` — a revisar.
- `backend/tests/test_contacts_link_cell.py:210` — a revisar.
- `backend/tests/test_contacts_reactivate_communications.py:106` — a revisar.
- `backend/tests/test_contacts_unarchive.py:114` — a revisar.
- `backend/tests/test_contacts_update.py:69` — a revisar.
- `backend/tests/test_contacts_update.py:119` — a revisar.
- `backend/tests/test_contacts_update.py:125` — a revisar.
- `backend/tests/test_contacts_update.py:130` — a revisar.
- `backend/tests/test_conversations_domain.py:76` — a revisar.
- `backend/tests/test_conversations_media_limits.py:295` — a revisar.
- `backend/tests/test_d2b2b2_decision_payload_schema.py:307` — a revisar.
- `backend/tests/test_d2b2b2_decision_payload_schema.py:339` — a revisar.
- `backend/tests/test_d2b2b2_decision_payload_schema.py:425` — a revisar.
- `backend/tests/test_d2b2b2_decision_payload_schema.py:431` — a revisar.
- `backend/tests/test_descendencias_scope.py:103` — a revisar.
- `backend/tests/test_domain_logic.py:30` — a revisar.
- `backend/tests/test_domain_logic.py:38` — a revisar.
- `backend/tests/test_domain_logic.py:39` — a revisar.
- `backend/tests/test_domain_logic.py:40` — a revisar.
- `backend/tests/test_event_notify_evt7.py:119` — a revisar.
- `backend/tests/test_event_notify_evt7.py:165` — a revisar.
- `backend/tests/test_event_notify_evt7.py:182` — a revisar.
- `backend/tests/test_event_notify_evt7.py:194` — a revisar.
- `backend/tests/test_event_recipients_evt8_pr2.py:78` — a revisar.
- `backend/tests/test_events_confirm_toctou.py:131` — a revisar.
- `backend/tests/test_events_confirm_toctou.py:135` — a revisar.
- `backend/tests/test_events_crud_evt2.py:145` — a revisar.
- `backend/tests/test_events_crud_evt2.py:695` — a revisar.
- `backend/tests/test_events_crud_evt2.py:721` — a revisar.
- `backend/tests/test_events_crud_evt2.py:726` — a revisar.
- `backend/tests/test_events_crud_evt2.py:730` — a revisar.
- `backend/tests/test_events_crud_evt2.py:735` — a revisar.
- `backend/tests/test_events_crud_evt2.py:744` — a revisar.
- `backend/tests/test_events_crud_evt2.py:749` — a revisar.
- `backend/tests/test_evolution_service.py:165` — a revisar.
- `backend/tests/test_evolution_service.py:321` — a revisar.
- `backend/tests/test_evolution_service.py:349` — a revisar.
- `backend/tests/test_evolution_service.py:357` — a revisar.
- `backend/tests/test_evolution_service.py:371` — a revisar.
- `backend/tests/test_evolution_service.py:481` — a revisar.
- `backend/tests/test_evolution_service.py:486` — a revisar.
- `backend/tests/test_evolution_service.py:529` — a revisar.
- `backend/tests/test_evolution_service.py:559` — a revisar.
- `backend/tests/test_messages_inbound_idempotency.py:158` — a revisar.
- `backend/tests/test_messages_inbound_idempotency.py:180` — a revisar.
- `backend/tests/test_messages_inbound_idempotency.py:228` — a revisar.
- `backend/tests/test_messages_inbound_idempotency.py:546` — a revisar.
- `backend/tests/test_messages_inbound_idempotency.py:612` — a revisar.
- `backend/tests/test_messages_inbound_idempotency.py:670` — a revisar.
- `backend/tests/test_messages_inbound_idempotency.py:1139` — a revisar.
- `backend/tests/test_outbound_guard.py:49` — a revisar.
- `backend/tests/test_outbound_guard.py:147` — a revisar.
- `backend/tests/test_outbound_guard.py:153` — a revisar.
- `backend/tests/test_outbound_guard.py:201` — a revisar.
- `backend/tests/test_outbound_guard.py:246` — a revisar.
- `backend/tests/test_outbound_guard.py:361` — a revisar.
- `backend/tests/test_outbound_guard.py:369` — a revisar.
- `backend/tests/test_outbound_guard.py:377` — a revisar.
- `backend/tests/test_outbound_guard.py:380` — a revisar.
- `backend/tests/test_outbound_guard.py:429` — a revisar.
- `backend/tests/test_outbound_guard.py:506` — a revisar.
- `backend/tests/test_outbound_guard.py:509` — a revisar.
- `backend/tests/test_outbound_guard.py:515` — a revisar.
- `backend/tests/test_outbound_guard.py:541` — a revisar.
- `backend/tests/test_outbound_guard.py:549` — a revisar.
- `backend/tests/test_outbound_guard.py:550` — a revisar.
- `backend/tests/test_password_reset_single_use.py:303` — a revisar.
- `backend/tests/test_password_reset_single_use.py:326` — a revisar.
- `backend/tests/test_password_reset_single_use.py:349` — a revisar.
- `backend/tests/test_password_reset_single_use.py:356` — a revisar.
- `backend/tests/test_pessoa_offboarding_router.py:57` — a revisar.
- `backend/tests/test_pessoa_offboarding_service.py:466` — a revisar.
- `backend/tests/test_pessoa_offboarding_service.py:584` — a revisar.
- `backend/tests/test_pessoa_offboarding_service.py:646` — a revisar.
- `backend/tests/test_pessoa_offboarding_service.py:653` — a revisar.
- `backend/tests/test_pessoa_offboarding_service.py:1023` — a revisar.
- `backend/tests/test_pessoa_offboarding_service.py:1025` — a revisar.
- `backend/tests/test_pessoa_offboarding_service.py:1403` — a revisar.
- `backend/tests/test_pessoa_offboarding_service.py:1648` — a revisar.
- `backend/tests/test_pessoa_offboarding_service.py:1820` — a revisar.
- `backend/tests/test_pessoa_offboarding_service.py:2008` — a revisar.
- `backend/tests/test_pessoa_offboarding_service.py:2195` — a revisar.
- `backend/tests/test_pessoa_offboarding_service.py:2266` — a revisar.
- `backend/tests/test_pessoa_offboarding_service.py:2344` — a revisar.
- `backend/tests/test_pessoa_offboarding_service.py:2402` — a revisar.
- `backend/tests/test_pessoa_telefone_unique_concurrency.py:310` — a revisar.
- `backend/tests/test_pessoa_telefone_unique_concurrency.py:311` — a revisar.
- `backend/tests/test_pessoa_telefone_unique_concurrency.py:312` — a revisar.
- `backend/tests/test_pessoa_telefone_unique_concurrency.py:528` — a revisar.
- `backend/tests/test_pipeline_assign_consolidador.py:122` — a revisar.
- `backend/tests/test_pipeline_csim.py:94` — a revisar.
- `backend/tests/test_pipeline_scope.py:144` — a revisar.
- `backend/tests/test_platform_admin.py:323` — a revisar.
- `backend/tests/test_platform_admin.py:330` — a revisar.
- `backend/tests/test_platform_admin.py:391` — a revisar.
- `backend/tests/test_platform_admin.py:407` — a revisar.
- `backend/tests/test_platform_admin.py:415` — a revisar.
- `backend/tests/test_platform_admin.py:429` — a revisar.
- `backend/tests/test_platform_admin.py:445` — a revisar.
- `backend/tests/test_platform_admin.py:857` — a revisar.
- `backend/tests/test_platform_admin.py:869` — a revisar.
- `backend/tests/test_platform_admin.py:878` — a revisar.
- `backend/tests/test_platform_admin.py:885` — a revisar.
- `backend/tests/test_platform_admin.py:893` — a revisar.
- `backend/tests/test_platform_admin.py:1059` — a revisar.
- `backend/tests/test_platform_admin.py:1382` — a revisar.
- `backend/tests/test_platform_admin.py:1400` — a revisar.
- `backend/tests/test_platform_admin.py:1535` — a revisar.
- `backend/tests/test_platform_admin.py:1547` — a revisar.
- `backend/tests/test_platform_admin.py:1575` — a revisar.
- `backend/tests/test_platform_admin.py:1579` — a revisar.
- `backend/tests/test_platform_admin.py:1581` — a revisar.
- `backend/tests/test_platform_admin.py:1594` — a revisar.
- `backend/tests/test_platform_admin.py:1606` — a revisar.
- `backend/tests/test_platform_admin.py:1622` — a revisar.
- `backend/tests/test_platform_admin.py:1640` — a revisar.
- `backend/tests/test_platform_admin.py:1933` — a revisar.
- `backend/tests/test_platform_admin.py:2109` — a revisar.
- `backend/tests/test_platform_admin.py:2118` — a revisar.
- `backend/tests/test_platform_admin.py:2140` — a revisar.
- `backend/tests/test_private_runtime_projection_pg17.py:60` — a revisar.
- `backend/tests/test_private_runtime_projection_pg17.py:199` — a revisar.
- `backend/tests/test_purpose_consent_service.py:175` — a revisar.
- `backend/tests/test_rate_limit.py:125` — a revisar.
- `backend/tests/test_rate_limit.py:127` — a revisar.
- `backend/tests/test_rate_limit.py:130` — a revisar.
- `backend/tests/test_rate_limit.py:148` — a revisar.
- `backend/tests/test_rate_limit.py:157` — a revisar.
- `backend/tests/test_rate_limit.py:246` — a revisar.
- `backend/tests/test_rate_limit.py:276` — a revisar.
- `backend/tests/test_rate_limit.py:352` — a revisar.
- `backend/tests/test_rate_limit.py:373` — a revisar.
- `backend/tests/test_rate_limit.py:396` — a revisar.
- `backend/tests/test_rate_limit.py:430` — a revisar.
- `backend/tests/test_rate_limit.py:431` — a revisar.
- `backend/tests/test_rate_limit.py:443` — a revisar.
- `backend/tests/test_rate_limit.py:455` — a revisar.
- `backend/tests/test_rate_limit.py:468` — a revisar.
- `backend/tests/test_secrets_crypto.py:54` — a revisar.
- `backend/tests/test_secrets_crypto.py:57` — a revisar.
- `backend/tests/test_secrets_crypto.py:62` — a revisar.
- `backend/tests/test_secrets_crypto.py:65` — a revisar.
- `backend/tests/test_sla_engine.py:278` — a revisar.
- `backend/tests/test_sla_engine.py:281` — a revisar.
- `backend/tests/test_sla_engine.py:290` — a revisar.
- `backend/tests/test_sla_engine.py:305` — a revisar.
- `backend/tests/test_sla_engine.py:308` — a revisar.
- `backend/tests/test_sla_engine.py:317` — a revisar.
- `backend/tests/test_sla_engine.py:380` — a revisar.
- `backend/tests/test_sla_engine.py:383` — a revisar.
- `backend/tests/test_sla_engine.py:452` — a revisar.
- `backend/tests/test_sla_engine.py:455` — a revisar.
- `backend/tests/test_sla_engine.py:473` — a revisar.
- `backend/tests/test_sla_engine.py:496` — a revisar.
- `backend/tests/test_sla_engine.py:499` — a revisar.
- `backend/tests/test_sla_engine.py:508` — a revisar.
- `backend/tests/test_source_contact_privacy.py:135` — a revisar.
- `backend/tests/test_sprint_routers_validation.py:101` — a revisar.
- `backend/tests/test_subscription_autoupgrade_notify.py:207` — a revisar.
- `backend/tests/test_subscription_autoupgrade_notify.py:213` — a revisar.
- `backend/tests/test_team_inbox_lookup.py:98` — a revisar.
- `backend/tests/test_team_invite.py:186` — a revisar.
- `backend/tests/test_team_invite.py:228` — a revisar.
- `backend/tests/test_team_invite.py:247` — a revisar.
- `backend/tests/test_team_invite.py:269` — a revisar.
- `backend/tests/test_team_invite.py:282` — a revisar.
- `backend/tests/test_team_invite.py:287` — a revisar.
- `backend/tests/test_team_invite.py:301` — a revisar.
- `backend/tests/test_team_invite.py:316` — a revisar.
- `backend/tests/test_team_invite.py:332` — a revisar.
- `backend/tests/test_team_invite.py:347` — a revisar.
- `backend/tests/test_team_invite.py:348` — a revisar.
- `backend/tests/test_team_invite.py:357` — a revisar.
- `backend/tests/test_team_invite.py:370` — a revisar.
- `backend/tests/test_team_invite.py:389` — a revisar.
- `backend/tests/test_team_invite.py:409` — a revisar.
- `backend/tests/test_team_invite.py:428` — a revisar.
- `backend/tests/test_team_invite.py:452` — a revisar.
- `backend/tests/test_team_invite.py:458` — a revisar.
- `backend/tests/test_team_lookup.py:116` — a revisar.
- `backend/tests/test_team_revoke.py:102` — a revisar.
- `backend/tests/test_team_roles.py:128` — a revisar.
- `backend/tests/test_whatsapp_identity.py:27` — a revisar.
- `backend/tests/test_whatsapp_identity.py:92` — a revisar.
- `backend/tests/test_whatsapp_identity.py:151` — a revisar.
- `backend/tests/test_whatsapp_routers.py:210` — a revisar.
- `backend/tests/test_whatsapp_routers.py:1053` — a revisar.
- `backend/tests/test_whatsapp_routers.py:1062` — a revisar.
- `backend/tests/test_whatsapp_routers.py:1064` — a revisar.
- `backend/tests/test_whatsapp_routers.py:1101` — a revisar.
- `backend/tests/test_whatsapp_routers.py:1107` — a revisar.
- `backend/tests/test_whatsapp_routers.py:1136` — a revisar.
- `backend/tests/test_whatsapp_routers.py:1145` — a revisar.
- `backend/tests/test_whatsapp_routers.py:1183` — a revisar.
- `backend/tests/test_whatsapp_routers.py:1191` — a revisar.
- `backend/tests/test_whatsapp_routers.py:1201` — a revisar.
- `backend/tests/test_whatsapp_routers.py:1233` — a revisar.
- `backend/tests/test_whatsapp_routers.py:1246` — a revisar.
- `backend/tests/test_whatsapp_routers.py:1277` — a revisar.
- `backend/tests/test_whatsapp_routers.py:1282` — a revisar.
- `backend/tests/test_whatsapp_routers.py:1314` — a revisar.
- `backend/tests/test_whatsapp_routers.py:1315` — a revisar.
- `backend/tests/test_whatsapp_worker.py:288` — a revisar.
- `backend/tests/test_whatsapp_worker.py:341` — a revisar.
- `backend/tests/test_whatsapp_worker.py:345` — a revisar.
- `backend/tests/test_whatsapp_worker.py:369` — a revisar.
- `backend/tests/test_whatsapp_worker.py:391` — a revisar.
- `backend/tests/test_whatsapp_worker.py:405` — a revisar.
- `backend/tests/test_whatsapp_worker.py:414` — a revisar.
- `backend/tests/test_whatsapp_worker.py:430` — a revisar.
- `backend/tests/test_whatsapp_worker.py:446` — a revisar.
- `backend/tests/test_whatsapp_worker.py:460` — a revisar.
- `backend/tests/test_whatsapp_worker.py:466` — a revisar.
- `backend/tests/test_whatsapp_worker.py:475` — a revisar.
- `backend/tests/test_whatsapp_worker.py:493` — a revisar.
- `backend/tests/test_whatsapp_worker.py:566` — a revisar.
- `backend/tests/test_whatsapp_worker.py:569` — a revisar.
- `backend/tests/test_whatsapp_worker.py:689` — a revisar.
- `backend/tests/test_whatsapp_worker.py:692` — a revisar.
- `backend/tests/test_whatsapp_worker.py:703` — a revisar.
- `backend/tests/test_whatsapp_worker.py:706` — a revisar.
- `backend/tests/test_whatsapp_worker.py:722` — a revisar.
- `backend/tests/test_whatsapp_worker.py:725` — a revisar.
- `backend/tests/test_whatsapp_worker.py:745` — a revisar.
- `backend/tests/test_whatsapp_worker.py:747` — a revisar.
- `backend/tests/test_whatsapp_worker.py:770` — a revisar.
- `backend/tests/test_whatsapp_worker.py:946` — a revisar.
- `backend/tests/test_whatsapp_worker.py:948` — a revisar.
- `backend/tests/test_whatsapp_worker.py:1019` — a revisar.
- `backend/tests/test_whatsapp_worker.py:1031` — a revisar.
- `backend/tests/test_whatsapp_worker.py:1234` — a revisar.
- `backend/tests/test_whatsapp_worker.py:1243` — a revisar.
- `backend/tests/test_whatsapp_worker.py:1339` — a revisar.
- `backend/tests/test_whatsapp_worker.py:1621` — a revisar.
- `backend/tests/test_whatsapp_worker.py:1627` — a revisar.
- `backend/tests/test_whatsapp_worker.py:1643` — a revisar.
- `backend/tests/test_work_queue_assign.py:183` — a revisar.
- `backend/tests/test_work_queue_message.py:165` — a revisar.
- `frontend/package-lock.json:5943` — a revisar.
- `frontend/src/components/admin/AuditModal.test.ts:86` — a revisar.
- `frontend/src/components/admin/AuditModal.test.ts:99` — a revisar.
- `frontend/src/components/admin/CreateIgrejaModal.test.ts:170` — a revisar.
- `frontend/src/components/admin/CreateIgrejaModal.test.ts:178` — a revisar.
- `frontend/src/components/admin/CreateIgrejaModal.test.ts:189` — a revisar.
- `frontend/src/components/admin/CreateIgrejaModal.test.ts:196` — a revisar.
- `frontend/src/components/admin/CreateIgrejaModal.test.ts:207` — a revisar.
- `frontend/src/components/admin/CreateIgrejaModal.test.ts:222` — a revisar.
- `frontend/src/components/calendario/CalendarConnectCard.test.ts:76` — a revisar.
- `frontend/src/components/calendario/CalendarConnectCard.test.ts:77` — a revisar.
- `frontend/src/components/calendario/CalendarConnectCard.test.ts:271` — a revisar.
- `frontend/src/components/central-celula/ManageCellsPanel.transfer-remove.test.ts:84` — a revisar.
- `frontend/src/components/contacts/ArchiveContactModal.test.ts:30` — a revisar.
- `frontend/src/components/contacts/ContatosScreen.test.ts:84` — a revisar.
- `frontend/src/components/contacts/ContatosScreen.test.ts:124` — a revisar.
- `frontend/src/components/contacts/ContatosScreen.test.ts:502` — a revisar.
- `frontend/src/components/contacts/ContatosScreen.unarchive.test.ts:75` — a revisar.
- `frontend/src/components/contacts/ContatosScreen.unarchive.test.ts:97` — a revisar.
- `frontend/src/components/contacts/GanharScreen.navigation.test.ts:70` — a revisar.
- `frontend/src/components/inbox/ContactPanel.test.ts:58` — a revisar.
- `frontend/src/components/inbox/ContactPanel.test.ts:123` — a revisar.
- `frontend/src/components/inbox/ConversationList.test.ts:30` — a revisar.
- `frontend/src/components/inbox/ConversationThread.test.ts:26` — a revisar.
- `frontend/src/components/inbox/conversation-format.test.ts:20` — a revisar.
- `frontend/src/components/minha-celula/MeetingReportForm.flow.test.ts:64` — a revisar.
- `frontend/src/lib/calendar-api.test.ts:28` — a revisar.
- `frontend/src/lib/calendar-api.test.ts:242` — a revisar.
- `frontend/src/lib/calendar-api.test.ts:253` — a revisar.

## Encerramento e próximo passo

Zero efeito externo nesta rodada: sem rede, commit, push, PR, merge, banco,
migration, flags ou deploy. Histórico Git preservado. Não são reproduzidos
valores reais nos artefatos novos ou neste relatório; permanecem valores
pendentes na árvore antiga e no histórico, sem declaração de saneamento global.

Não publicar esta revisão como verde. Próximo passo: revisão dos casos
pendentes e decisão do dono sobre remetente técnico/metadados de terceiros;
sanitização coerente das fixtures e suíte correspondente antes de novo push.
Reversão: alterações locais isoladas, sem estado operacional para restaurar.
