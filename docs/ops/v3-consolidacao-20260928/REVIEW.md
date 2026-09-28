# Parecer integrado V3, fontes finais condicionais

**Veredito:** GO técnico condicional para as fontes revisadas. Não há P0, P1 ou P2 aberto neste recorte. O encaminhamento humano permanece condicionado à RLS integral e ao CI do SHA final.

## Escopo e integridade

Base Git: `342f0ced7af53d2d7e708d99e3b92d54e7a3e22c`.

| Artefato | SHA-256 |
| --- | --- |
| Snapshot integrado de produção, 18 arquivos | `c3fa00e08358da0212590b6ad46b8a07df8052bcd29b73a5837c4d25defcc541` |
| Delta de paridade modelo e schema | `0c9558de4cbd9b8cf3378493c25b1775c80acf4cfc43bc25f17fce45bd8751fd` |
| Delta final de decisão e turno | `f8d530a515611552e70f1af30a26100ff39ef3be86ba52cfc67ad4e226c2316d` |

Conferi os hashes substituídos pelo delta de paridade: `models.py` `8cc08a4e6d7f703f21e58b0117c159db359ec2696182b03b73e7f185e8555af7`, `test_consolidation_v3_models.py` `f45d7a8d67067ece1b0ea46b0b743b9c9c7814a853f0be259b70388123503fe4` e `test_whatsapp_consolidation_v3_migration_pg.py` `f43c6c356719fdebfec3ec33975e9a96f10c6c386c8b1c2b1ba066e3c3f03cce`.

Conferi os hashes do delta de decisão: `agent_privilege_catalog.py` `acd0545b205943239e35703230b95571e09ffa5118694c79a47d673ade43f545` e `test_consolidation_turn_e2e_pg.py` `9bfe532746a43a9989b9c0d281b25cc697bd02342ccc1d75912944d15a48f4d6`.

## Fechamento da decisão V3

Com V3 aberta, a projeção reconhece a gramática fechada de decisão, resolve a pessoa no servidor e só admite exatamente um candidato. O texto remetido ao roteador é `Solicitação de registro de decisão.` e o resumo de confirmação é `Registrar decisão da pessoa indicada`; ambos omitem nome, telefone e texto livre. A revalidação da seleção e o fence imediatamente anterior ao transporte recompõem `build_catalog`, que sobrepõe o alvo legado pelo grupo V3 opaco enquanto o gate permanece aberto.

O residual reconhecido, um alvo homônimo, mais de um candidato ou uma mudança de contexto retorna handoff sem chamar o roteador ou o transporte. A confirmação usa o serviço transacional canônico, cria a decisão, a consolidação vinculada, o prazo de conexão de 24 horas e uma única fonovisita. Quando V3 está fechada, o grupo V3 não é aplicado e o caminho S3 legado permanece selecionável como antes.

O ajuste de paridade mantém a pendência derivada sob `ON DELETE CASCADE`, igual ao SQL, e preserva a outbox terminal com referências vivas anuladas. O dispatcher comum continua submetido a gates, época, quota, lease, revalidação de destinatário e expiração antes do HTTP.

## Evidência executada

Em Python 3.13.14 e bancos PostgreSQL sintéticos locais exclusivos, executei:

| Prova | Resultado |
| --- | --- |
| Modelo e migration V3 | 19 passed, 0 failed, 0 skipped |
| Delivery V3, incluindo coordenação sem PII e ausência de destinatário elegível | 21 passed, 0 failed, 0 skipped |
| Turno E2E da decisão V3, worker, identidade, roteador fechado, confirmação e provider fake | 12 passed, 0 failed, 0 skipped |

O último E2E começa no inbound já persistido, usa migration literal e RLS autenticada, atravessa o worker real e usa catálogo e confirmação reais. A configuração de gates é sintética e os provedores externos são fakes. Ele cobre alvo único, residual que não chega ao roteador, homônimo que encerra em handoff, proposta opaca, SIM e criação da trilha canônica. Não prova parser, HTTP de provider, piloto real ou efeito externo.

Há também evidência do root de regressão offline no candidato: 5982 passed, 750 deselected, sem falhas. A RLS integral estava em execução no momento deste parecer; ela e o CI final ainda são gates separados.

## Limites e próximo gate

Este parecer não prova ambiente compartilhado, flag aplicada, credencial, envio real, migration aplicada ou produção. A gramática V3 é propositalmente restrita e entradas reconhecidas fora dela seguem para atendimento humano, sem retomar o texto original para um modelo externo.

O próximo gate humano permanece único: Sarah, após a RLS integral e o CI do SHA final verdes. Este parecer não autoriza merge, migration compartilhada ou transporte real.
