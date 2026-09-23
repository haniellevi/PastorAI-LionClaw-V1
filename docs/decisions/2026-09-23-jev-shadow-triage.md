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
- **O corpo da mensagem sai como a pessoa escreveu.** `mask_text` redige
  apenas CPF, e-mail e sequências de 7 ou mais dígitos contíguos. Nome,
  endereço, telefone formatado (por exemplo `(11) 99999-8888`) e conteúdo
  pastoral sensível (fé, saúde, crise) **saem em claro** para a TypeSafe. É
  redação parcial, não pseudonimização. O servidor só acrescenta o canal e um
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
`platform_audit_logs`, sem o e-mail do operador. As configurações ficam em
cache no processo, então uma mudança no `.env` só vale depois de reiniciar o
backend.

A chave e a lista continuam no ambiente de deploy. Gravar esse segredo pelo
console exigiria uma tabela global, que o contrato de migration v1 recusa
(`GLOBAL` falha fechado), e a aplicação de migrations está bloqueada.

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

## Integração pendente (gate D3)

`app/config.py`, `app/agent/runtime.py` e `app/workers/queue_worker.py` estão
congelados por hash em `backend/tests/test_d2b2b2_decision_packet_docs.py`.
Por isso a configuração fica em `TriageSettings`, dentro do próprio módulo,
e o runtime ainda não chama o módulo.

A integração é uma única chamada em `process_inbound_message`, depois que os
eventos do turno são auditados e antes do retorno de handoff:

```python
semantic_triage.log_shadow_triage(
    session, igreja_id=igreja_id, conversation_id=conv_uuid,
    context=context, texto=texto, route=route,
)
```

Essa chamada só entra quando o gate D3 for revisado e os pins atualizados por
decisão explícita. **Resolver antes de ligar:** hoje seria uma chamada HTTP
síncrona de cerca de 0,9 s, com timeout de até 2 s, dentro da transação
Postgres do turno. O desenho da integração deve avaliar fazer a chamada fora
da transação ou por fila.

## Próximos passos

1. Resolver DPA/base legal e obter revisão.
2. Revisar o gate D3 e ligar a chamada no runtime.
3. Rodar em sombra para uma igreja piloto e comparar `routeRegras` com as
   respostas do Jev. Escolher os limites com base nesses dados.
4. Só então promover sinais específicos, começando por `risco_pastoral` →
   handoff, e cada um com seu próprio gate.
