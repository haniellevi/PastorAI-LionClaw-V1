# Revisão intermediária V1a, fundação SQL e contratos

Data: 27/09/2026

## Candidato conferido

- Base declarada: `f2a532a9cadba44a31e3d3067125a9e2b624c233`.
- Patch: `6e483ad68bbf20e278b3aec258b3d6bea1304661c767544f483dc251677ecb48`, conferido.
- Migration: `20260927_190000_cell_report_whatsapp_v1a.sql`, SHA-256 `d76ab1c6096d2c33781c5cd03a978c5a1cdd524c2a4bdc344b08c73df8abda50`, conferido.
- Os 10 blobs do `FOUNDATION-VALIDATION.json` coincidem com a árvore revisada.

O recorte corrige a fronteira de tenant de `celula_reuniao` com chaves compostas `(igreja_id, id)` nos rascunhos e lembretes. A migration força RLS nas cinco relações novas, separa o worker sem `sub` do painel com `sub`, revoga papéis não autorizados e mantém o default de release inerte. A projeção de extração permanece fechada aos quatro agregados e rejeita observações.

## P1, contrato de recibo V1a não chega ao serviço

A migration e o modelo permitem `Relatório confirmado.`, mas `ActionEffect` e `_require_receipt_text` em `backend/app/services/agent_action_proposals.py:115-119` e `:616-619` aceitam somente `Registro confirmado.`. Portanto, o finalizador V1a não consegue persistir o recibo novo pelo contrato comum de propostas, embora o schema o aceite.

Reprodução mínima: construir `ActionEffect(receipt_text="Relatório confirmado.", opaque_effect_id=<UUID válido>)` gera `ProposalContractError` antes da gravação. A correção mínima é mapear cada ação para o único recibo fechado esperado e validar a correspondência no ponto que já conhece a proposta. Incluir teste positivo da ação V1a e testes de rejeição cruzada entre recibos e ações.

O autor informou correção em outra árvore. Este parecer continua sobre o snapshot congelado acima e requer rechecagem do delta exato antes de aprovação.

## P2, empate de consentimento não é totalmente determinístico

`current_v1a_lgpd_acceptance` em `backend/app/services/cell_report_whatsapp.py:108-118` só nega empates se as versões terminais forem diferentes. Dois registros distintos, com mesmo `aceite_em` e mesma versão vigente, retornam aceite. O contrato atual já nega o empate conflitante, portanto não há bypass demonstrado neste snapshot; ainda assim, o resultado depende de uma escolha implícita sobre dois eventos terminais equivalentes.

Para manter o contrato conservador de ledger, exigir `len(terminal) == 1` e cobrir dois `record_id` distintos com mesmo timestamp e versão. A futura consulta que alimenta essa função também deve incluir todos os registros no timestamp terminal, sem reduzir o conjunto antes da checagem.

## Cobertura que falta antes da integração do worker

A prova PG relatada cobre segunda aplicação/OID, isolamento de leitura e deleção cross-tenant, painel sem leitura ou update e inserções negadas ao painel ou outro tenant. Ela não exercita uma escrita válida do worker sem `sub` em cada uma das cinco tabelas novas. A policy e os grants parecem permitir esse caminho, mas o contrato operacional ainda precisa da prova.

Adicionar PG17 sanitizado que, como `authenticated` com tenant configurado e `sub` vazio, execute ao menos uma inserção e uma atualização válidas por relação, respeitando as FKs compostas e as unicidades. Reexecutar a matriz para confirmar que o mesmo papel não grava tenant alheio.

## Veredito deste recorte

**NÃO APTO para integrar a fundação tal como congelada**, devido ao P1 de recibo. Não é aprovação de produto V1a. Após o delta de recibo, o fortalecimento do empate LGPD e a prova de escrita válida do worker, cabe revisão apenas do candidato exato e das evidências correspondentes.
