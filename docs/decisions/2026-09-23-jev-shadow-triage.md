---
id: JEV-SHADOW-TRIAGE
document_kind: design-decision
status: MODULO_ENTREGUE_NAO_INTEGRADO
base_sha: 5729c6cafb167b78e4db59a2298a0ce9493042d3
environment: local_offline
created_at: 2026-09-23
---

# Triagem semântica Jev (TypeSafe) em modo sombra

## Decisão

Adicionar ao backend um módulo que faz perguntas tipadas ao Jev, o modelo
System One da TypeSafe, sobre cada mensagem inbound do WhatsApp. As respostas
**não mudam nenhum comportamento**. Elas só servem para medir, com dados reais,
onde as regras atuais de roteamento erram e onde nenhuma regra decide hoje.

Módulo: `backend/app/services/semantic_triage.py`. Testes:
`backend/tests/test_jev_shadow_triage.py`.

## Por quê

Hoje o roteador (`app/agent/nodes.py` `route_intent`) decide tudo por regex e
listas de palavras. As falhas conhecidas são:

- **Aceite de termo** (`consent.is_acceptance`): olha só a primeira palavra,
  então "sim, mas não quero" conta como aceite.
- **Classificação CSIM** (`classification.classify_contact`): basta a palavra
  aparecer em qualquer parte da frase, como "empresa".
- **Detecção de crise**: não existe. Uma mensagem de risco à vida cai no
  `onboarding` com resposta genérica.
- **Intenções sem destino**: pedido de oração e interesse em visitar ainda
  não são reconhecidos.

## Perguntas por mensagem

| id | primitivo | uso futuro pretendido |
|---|---|---|
| `risco_pastoral` | Noul | handoff humano + alerta pastoral |
| `pede_optout` | Noul | aumentar a cobertura da regex (a regex continua valendo) |
| `aceita_termo` | Noul, só com termo pendente | barrar aceite falso; nunca concede aceite sozinho |
| `intencao` | Choice com `outro` | relatório de célula, oração, visita, comercial, fora da cidade |

## Limites invariáveis

- A etapa G12 nunca muda a partir do texto do chat. A promoção continua por
  contadores e `aceitou_jesus`.
- O opt-out por regex continua obrigatório e continua sendo aplicado antes de
  qualquer gate.
- O Jev sugere, sinaliza e prioriza. Ele não executa tool, não grava
  consentimento e não responde ao contato.

## Privacidade e ligação

- Desligado por padrão. Só roda para igrejas listadas em
  `JEV_SHADOW_TRIAGE_IGREJA_IDS`, com `TYPESAFE_API_KEY` configurada **e**
  com o guard global `ALLOW_REAL_SENDS` aberto. Isso vale também para o teste
  de conexão do Admin Master.
- **O corpo da mensagem sai como a pessoa escreveu.** `redact_for_egress`
  redige apenas CPF, e-mail, telefones (inclusive formatados, como
  `(11) 99999-8888`) e sequências de 7 ou mais dígitos. Nome, endereço e
  conteúdo pastoral sensível (fé, saúde, crise) **saem em claro** para a
  TypeSafe. É redação parcial, não pseudonimização. O servidor só acrescenta o canal e um
  booleano de papel ministerial. Ids, nome e telefone do cadastro não são
  acrescentados.
- O evento `jev_shadow_triage` em `agent_conversation_logs` guarda só
  probabilidades, a intenção, a rota das regras, tokens e latência. O texto
  da mensagem não é gravado.
- **Antes de ligar para qualquer igreja** é preciso ter:
  1. base legal e contrato de operador (DPA) com a TypeSafe, tratando o envio
     como **dado pessoal sensível em claro** e transferência a processador
     estrangeiro;
  2. um dono e testes próprios para a redação antes do egresso, se ela passar
     a ser controle de privacidade;
  3. revisão independente (Sarah) com GO;
  4. `ALLOW_REAL_SENDS` aberto por decisão operacional própria.

## Admin Master

O botão **Jev** no Console da Plataforma (`JevModal`) usa `GET /admin/jev` e
`POST /admin/jev/teste`, restritos a `get_platform_admin`. Ele mostra se a
chave está configurada (sem devolvê-la, nem parcialmente), o modelo, o timeout
e as igrejas da lista, com seus nomes, além do estado de `ALLOW_REAL_SENDS`.
O teste de conexão envia só uma mensagem sintética fixa, respeita o guard,
tem limite de 10 por janela por operador e grava `jev_testar` em
`platform_audit_logs`, sem o e-mail do operador.

Atualizado em 2026-09-26: com o processo simples de migration, o master passou
a configurar pelo console (`PUT /admin/jev/config`) a chave, o modelo, o
timeout, a data do DPA e as igrejas. A tabela `platform_jev_settings` tem
linha única e fica fechada para `anon` e `authenticated`, como
`platform_orchestrator`. A chave é cifrada com `services/crypto.py` e nunca
volta, nem em parte. O banco recusa igreja listada sem data de DPA. Campo vazio
cai no ambiente, e a mudança vale na hora, sem reiniciar. Cada gravação fica em
`jev_configurar` na auditoria, sem a chave. `ALLOW_REAL_SENDS` e a URL da API
continuam só no ambiente: editável pelo console, a URL poderia desviar a chave
para outro servidor. Sem a tabela, antes da migration `20260926_120446`, o
console mostra só o ambiente e salvar responde 409. O runtime do J1 deve ler
essa configuração numa sessão de plataforma: a sessão com escopo de tenant
roda como `authenticated`, que não lê a tabela.

### Evidência de calibração (sanitizada)

- **SHA:** `1aa9c82` (módulo antes do guard B2).
- **Ambiente:** estação local de desenvolvimento, chamando
  `https://api.typesafe.ai/v1/systemone` com `jev-latest` e uma chave pessoal
  do proprietário. Nenhum banco, DEV ou PROD foi usado.
- **Horário:** 2026-09-23, America/Sao_Paulo.
- **Entrada:** 20 frases inventadas, sem nenhum dado de pessoa real (crise
  indireta, violência doméstica, luto, pedido de opt-out, falsos opt-outs como
  "vou sair do trabalho" e "parar de fumar", aceites e aceite com ressalva,
  relatórios de célula, visita, comercial, fora da cidade, saudação).
- **Resultado:** 20 de 20 no comportamento esperado.
  - Crise: `risco_pastoral` entre 0,93 e 0,98.
  - Falsos opt-outs: 0,01.
  - Aceite com ressalva: `aceita_termo` 0,03.
  - "Trabalho numa empresa… célula?": intenção de visita, não comercial.
  - Latência entre 808 e 977 ms por chamada.
- **Limites:** amostra pequena e escrita pelo próprio desenvolvedor, sem
  representatividade estatística. Não substitui a avaliação em sombra com
  mensagens reais, que depende do DPA. Os limites de decisão continuam por
  definir.

## Integração pendente

Atualizado em 2026-09-26. O gate D3 (testes de hash sobre `config.py`,
`runtime.py` e `queue_worker.py`) foi removido na Fase 0 do plano MVP
(commit `adb6b6e`), então a integração não depende mais dele. Ela segue a
trilha Jev de `docs/ops/MVP-PLANO-SIMPLIFICACAO.md`:

1. **J0, avaliação offline** (`backend/scripts/jev_eval.py`): corpus
   sintético pt-BR rotulado, comparação com as regras atuais, latência e
   custo. Os critérios de GO saem no próprio relatório.
2. **J1, sombra na igreja piloto**: só com J0 = GO, DPA, termo LGPD que cite
   IA e processador estrangeiro e backend de produção atualizado. A chamada
   acontece depois do envio da resposta, em transação própria, nunca dentro
   da transação do turno. Versão do modelo fixada e custo em
   `ai_usage_logs`.
3. **J2, sinais ativos na Fase 2**: um por vez, cada um com flag própria e
   comportamento definido para quando o Jev estiver indisponível (por
   exemplo, sem Jev não se marca CSIM, porque isso silencia o contato).
