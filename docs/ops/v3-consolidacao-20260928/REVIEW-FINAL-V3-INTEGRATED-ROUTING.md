# Parecer integrado V3, revisão final de roteamento

## Veredito

**GO técnico integrado para as fontes congeladas revisadas.** Não há P0, P1 ou P2 de implementação aberto neste recorte. A RLS integral está em execução pelo root e a CI precisará confirmar o SHA publicado; nenhuma delas é declarada verde por este parecer.

O próximo gate humano permanece Sarah, depois das evidências automáticas finais. Este parecer não autoriza merge, migration compartilhada, provider real ou envio externo.

## Integridade do recorte

Base documental: `342f0ced7af53d2d7e708d99e3b92d54e7a3e22c`.

| Artefato | SHA-256 |
| --- | --- |
| Snapshot integrado local de referência, 18 arquivos | `c3fa00e08358da0212590b6ad46b8a07df8052bcd29b73a5837c4d25defcc541` |
| Artefato publicado de paridade modelo e schema, `review-inputs/V3-MODEL-PARITY-DELTA.json` | `0c9558de4cbd9b8cf3378493c25b1775c80acf4cfc43bc25f17fce45bd8751fd` |
| Delta local de decisão e turno inicial | `f8d530a515611552e70f1af30a26100ff39ef3be86ba52cfc67ad4e226c2316d` |
| Snapshot local de delivery final | `5aca7a6e25022d6b3e6ae8b52c97f552684f5afe364c84cd585219524a7843c3` |
| Catálogo após correção P1 | `6d514590218d7d6a9198df4ecf91ced9b9b4f9a3c7b16e2ec6dea23436cefe7d` |
| Teste do catálogo após correção P1 | `599672235e970580b1d29e5c1fc0e4e7d1b4f869993455e89fc245f72f6085fc` |
| Turno PG após reforço diagnóstico | `67240413ec9e6c09287cfdcea0d5180ecf582b716b8d403875ba22a44bb47214` |

Os hashes correntes dos módulos que fecharam os deltas finais também foram conferidos: `privileged_turn.py` `03049ea9`, `consolidation_workflow.py` `e90b5a9f`, `consolidation_whatsapp.py` `8e801509`, `consolidation_privileged.py` `6eef320d`, `notification_outbox.py` `416d7aa1`, `models.py` `8cc08a4e` e a migration V3 `267f6197`.

## Fechamento dos achados

O P1 de roteamento foi resolvido no catálogo. Com V3 habilitada, o código lê e reconhece a gramática antes de avaliar a capacidade do ator. Uma solicitação reconhecida de membro, ator com papel revogado, comando residual, alvo ambíguo ou combinação insegura produz somente a projeção fixa de handoff. Esse caminho não contém texto livre, nome, telefone, código acionável, proposta ou chamada ao roteador, Tier A ou provider. `None` continua reservado ao texto fora da gramática V3 e ao caminho legado quando a flag V3 está fechada.

O P2 de responsabilidade de fonovisita permanece resolvido pelo fluxo humano canônico. `lider_celula` só opera a própria fonovisita; `lider_g12` opera conexão e fonovisita próprias; coordenação opaca e atribuição continuam limitadas a `admin`, `pastor` e `lider_consol`. A confirmação final exige responsável atual, tipo da pendência, revisão de atribuição e locks da consolidação e da fila.

No delivery, o produtor e o fence reconstroem pessoa canônica, consentimento, preferência versionada, STOP, conversa humana, papel atual, fonte, fingerprint, época de ativação, prazo de 24 horas, janela, quota e lease antes de HTTP. Reatribuição, revogação de papel, mudança de origem, ambiguidade telefônica, lock contendido e expiração suprimem a entrega ou permitem apenas retentativa pré-envio. Nenhuma trilha faz reroteamento automático para outro responsável.

## Evidência independente

Em Python 3.13.14 e bancos PostgreSQL sintéticos locais, já tinham sido reproduzidos nesta revisão: modelo e migration, **19 passed**; workflow e compatibilidade do painel, **24 passed**; e delivery V3, **25 passed**.

Para o fechamento do P1, executei em 2026-09-28, com `V3_TURN_DATABASE_URL` apontando ao banco sintético exclusivo `v3_consolidation_test`:

```text
pytest tests/test_agent_privilege_catalog.py tests/test_consolidation_turn_e2e_pg.py -q
```

Resultado: **70 passed**, correspondentes a 48 unitários do catálogo e 22 cenários PG de turno. A prova percorre inbound persistido, identidade real sob RLS autenticada, worker, catálogo, confirmação S3, persistência e provider falso. Ela cobre membro e papel revogado com fonovisita, consulta e residual, todos sem roteador, proposta ou transporte; decisão V3 com alvo único; homônimo e residual em handoff; STOP e SAIR; e líder G12 concluindo a própria fonovisita.

O caso G12 teve uma execução anterior não reproduzida, no teste anterior `91e5c0a4`, em que a pendência ficou aberta após `SIM`. Não houve log de worker ou estado intermediário suficiente para atribuir causa. O teste atual adiciona asserções de proposta pendente, resumo entregue e `delivered_at` antes da confirmação, seguidas de proposta executada, âncora, recibo e pendência resolvida. A repetição independente verde não demonstra defeito de produção; também não permite afirmar a causa daquela execução anterior.

O root registrou ainda a suíte offline final: **5.998 passed, 770 deselected, zero falhas e zero skips**. A RLS integral de 770 casos estava em curso ao escrever este parecer.

## Limites

O E2E começa depois do inbound já persistido. Gates, credenciais e provider são sintéticos; não prova parser HTTP, piloto, flag aplicada, migration aplicada em ambiente compartilhado, credencial viva ou entrega real. A gramática V3 permanece deliberadamente fechada, e um pedido reconhecido fora da forma segura termina em handoff humano local.
