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
  `JEV_SHADOW_TRIAGE_IGREJA_IDS` e com `TYPESAFE_API_KEY` configurada.
- A mensagem sai mascarada por `mask_text` (CPF, e-mail e dígitos longos).
  Nome, telefone e ids não são enviados.
- O evento `jev_shadow_triage` em `agent_conversation_logs` guarda só
  probabilidades, a intenção, a rota das regras, tokens e latência. O texto
  da mensagem não é gravado.
- **Antes de ligar para qualquer igreja** é preciso ter:
  1. base legal e contrato de operador (DPA) com a TypeSafe, já que o texto
     pode conter dado sensível (fé, pedido de oração, crise);
  2. revisão independente (Sarah) com GO.

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
decisão explícita. O custo previsto é uma chamada HTTP síncrona com timeout
padrão de 2 s dentro da transação do turno, com o mesmo padrão já usado pelo
refino BYO LLM.

## Próximos passos

1. Resolver DPA/base legal e obter revisão.
2. Revisar o gate D3 e ligar a chamada no runtime.
3. Rodar em sombra para uma igreja piloto e comparar `routeRegras` com as
   respostas do Jev. Escolher os limites com base nesses dados.
4. Só então promover sinais específicos, começando por `risco_pastoral` →
   handoff, e cada um com seu próprio gate.
