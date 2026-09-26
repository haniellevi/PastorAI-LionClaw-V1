# Tier A S1: avaliação offline

**Estado em 26/09/2026: NÃO AFERIDO.** Nenhuma predição produzida pelo código
candidato ou por provedor foi recebida nesta etapa. Não há recall, falso
alarme, latência, taxa de erro ou veredito operacional medido. O comando
`python backend/scripts/jev_tier_a_eval.py --split dev` confirmou apenas o
contrato congelado e retornou `NÃO AFERIDO`.

O manifesto `jev_tier_a_manifest_v1.json` tem SHA-256
`e43e670492bd4b2a349fabe34d14c6f7f54a95c0428d156b0c85b830d292fa2b`.
O dev tem 120 frases e 24 famílias (SHA-256
`27b097596a319d67e5f6738737f423b9d54beb16dcafe24db1a5a31d387e2edd`);
o holdout tem 120 frases e 24 famílias distintas (SHA-256
`05fecd57a7c64aa2a12e45df8323e07411af02fa96c8b9a6d69853a7e18cdb42`).
Cada split contém 35 positivos e 85 negativos por sinal. O gold de handoff,
definido por `risco_crise OR pede_humano`, soma 65/120 (54,17%). Essa proporção
foi construída para testar erros e não estima a prevalência do piloto.

## Contrato do avaliador

`backend/scripts/jev_tier_a_eval.py` aceita `--split dev|holdout`. Sem arquivo
de predições, emite somente o estado não aferido, contagens e hashes. Para
medir um candidato local, exige `--predictions ARQUIVO.jsonl` e
`--candidate-sha SHA` de 40 ou 64 caracteres hexadecimais. O SHA é declarado
pelo operador, não comprovado pelo avaliador. Cada linha de predição deve ter
exatamente `id`, `risco_crise`, `pede_humano`, `pede_optout`, `handoff`, `erro`
e `latencia_ms`. As cinco decisões são booleanas; latência é número finito e
não negativo. Os IDs devem corresponder exatamente aos do split, sem repetição.
`handoff` é obrigatório se `risco_crise`, `pede_humano` ou `erro` for verdadeiro.
Também pode ser verdadeiro por outro motivo do código candidato, mesmo com os
três campos falsos; nesse caso entra na taxa de handoff e pode contar como FP
contra o gold. Todo erro, portanto, termina em handoff. Campos extras,
inclusive texto, são recusados. A saída agrega contagens e hashes, sem frases
nem resultados por ID.

O avaliador calcula TP, FN, FP, TN, recall e FPR por sinal e por handoff,
intervalos bilaterais de Wilson de 95% para recall e FPR, taxa de handoff com
denominador, erros e p95 da latência por posto mais próximo. As metas usam
somente estimativas pontuais: crise com recall >= 90% e FPR < 10%; pedido
humano com recall >= 85%. A chave `metas_pontuais_atingidas` resume esses
três testes. Separadamente, `limites_wilson_atingem_metas` informa se o limite
inferior de recall de crise alcança 90%, o limite superior de FPR fica abaixo
de 10% e o limite inferior de recall humano alcança 85%. Denominador ausente
retorna falso. Esta segunda chave é informação para revisão futura, não um
critério de GO adicional aprovado. Em cada split, os denominadores de crise e
pedido humano são apenas 35 positivos; o FPR de crise tem 85 negativos.
Intervalos de Wilson impedem tratar uma meta pontual como garantia de
desempenho. Predições locais autodeclaradas jamais produzem status `GO` ou
autorização de ativação.

O teto operacional de handoff diário acima de 30% pertence à observação do
piloto. A taxa gold de 54,17% neste corpus enriquecido não reprova esse teto
nem demonstra viabilidade em tráfego real. O holdout permanece reservado à
validação final cega ou a auditor independente. Seus exemplos não podem ser
usados para alterar perguntas, regex, limiares ou prompts; qualquer mudança
do corpus congelado exige versão nova.
