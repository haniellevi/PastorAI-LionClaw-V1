# MVP fase 2, fatia 1: resposta contextual, handoff e B4

Base: main `92eed5767bd74a2130e7572d739cc871e6e698a9`.
Branch: `feat/mvp-fase2-respostas`. PR419. Ambiente: somente local/GitHub.

## Comportamento entregue

O runtime responde à mensagem persistida com `AgentConfig.comportamento` e
até dez mensagens anteriores da mesma conversa e igreja. Exclui mensagens
futuras e saídas pendentes, suprimidas ou ambíguas. Consentimento, opt-out e
efeitos de domínio continuam determinísticos. Resposta limitada a 1600 caracteres.
Perfil, histórico e mensagem têm os caracteres de delimitador neutralizados
antes da montagem dos blocos fixos do prompt.

O detector normaliza acentos e caixa, cobre formas reflexivas, pedidos humanos,
expressões e tokens soltos de crise. A negação é local à ocorrência e preserva
“não quero mais viver”. Aceites curtos, incluindo “eu aceito”, “sim aceito”,
“ok, aceito” e “claro que sim”, são permitidos; “mas”, “porém” e “não” rejeitam
a frase antes da allowlist.

O handoff automático, manual e a transferência humana aplicam uma barreira
na mesma transação: intents reservadas, em execução e pendentes são suprimidas;
tentativas em transporte ficam ambíguas para reconciliação. Liberação para IA,
preparo atrasado, retry e perda de ownership não reabrem essas respostas.
A sonda pré-HTTP exige estado elegível persistido. Locks seguem Conversation
antes de Message e terminam antes do HTTP. No inbox, humano sem responsável
aparece aguardando; liberar para IA limpa o horário de espera.

## Verificação

Em 26/09/2026, `test-local.sh` passou com Python 3.13.14 e Node 24.19.0:
5125 testes backend, 856 frontend em 97 arquivos e verificação de tipos.
PostgreSQL 17 descartável: 322 testes, zero falhas, erros ou skips. Código e testes
foram congelados no patch
`365f22a93ac6ca92b9aa65296a5eaf991ebd22f972237bd4a744dd781b029738`;
o único delta posterior foi consolidar este registro documental.

As regressões RED reproduziram os achados antes das correções: variantes de
crise/humano, negação, B4, delimitadores nos três campos, retry após handoff,
preparo atrasado, três transportes, retorno retentável, perda de ownership e
horário de espera no release. A consulta de histórico foi exercitada em SQL
real com outras conversas/igrejas, mensagem futura e estados de entrega.
LLM e transporte foram simulados. Revisão independente usa diretório próprio;
CI e respostas às threads são vinculados ao novo head da PR. Evidências
integrais estão na ficha `M-2026-09-26-piloto-roteiro-e-mvp-fase2` e em
`docs/ops/mvp-fase2-20260926/` do workspace de controle.

## Limites e rollback

A heurística pode encaminhar menções incidentais; não diagnostica intenção ou
eficácia clínica. Neutralizar delimitadores não garante proteção geral contra
prompt injection ou factualidade de um modelo real. Uma chamada iniciada,
ou na janela após a última sonda, não pode ser recolhida. As 20 conversas reais,
ferramentas de leitura e jornada visual manual ficam fora desta evidência.

Nenhuma migration, dependência, checkpointer ou operação DEV/PROD/VPS/provedor.
O roteiro anterior refere-se à main `92eed57` e não implanta esta fatia.
Rollback: revert da PR, sem alteração de schema. O head novo deve voltar à Sarah
para reconferência. Merge depende de frase nominal de Raniel; esta entrega
não autoriza deploy ou canário.
