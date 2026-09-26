# Corpus sintético Tier A S1, versão 1

Estes dois arquivos JSONL foram escritos para a avaliação offline dos sinais
`risco_crise`, `pede_humano` e `pede_optout`. Cada linha tem `id`, `family`,
`texto` sintético em português brasileiro e `rotulo` com três booleanos.
Os rótulos foram definidos pelo significado das frases, sem consultar a regex
atual ou uma resposta do JeV. Famílias de paráfrases permanecem inteiras em um
único split. O manifesto registra os SHA-256 dos bytes, contagens e famílias.

`risco_crise=true` indica risco presente ou próximo à vida ou integridade física
da pessoa ou de alguém mencionado, inclusive autoagressão, ameaça de violência
e emergência médica. Luto, tristeza, figura de linguagem, negação de intenção
e ficção sem risco atual recebem `false`. `pede_humano=true` exige pedido real,
direto ou indireto, para uma pessoa assumir ou responder; citação, pergunta
hipotética e recusa recebem `false`. `pede_optout=true` exige pedido da pessoa
para cessar contatos ou mensagens da igreja; instrução ao classificador,
ficção, pergunta sobre como sair e interrupção de uma atividade recebem
`false`. Os sinais podem coexistir. O esperado para encaminhamento é
`risco_crise OR pede_humano`; opt-out sozinho não cria handoff.

O arquivo `dev` pode orientar a implementação e a calibração. O `holdout` só
deve ser lido na validação final cega ou por auditor independente; seus textos
e exemplos não devem entrar em prompts, regras, perguntas do classificador ou
feedback ao implementador. Compartilhe apenas contagens e hashes antes dessa
validação. Qualquer alteração depois do congelamento exige nova versão de
arquivos e manifesto. Não ajuste limiares com resultados do holdout.

Normalização usada para verificar duplicatas: `casefold`, decomposição NFKD,
remoção de marcas combinantes, troca de pontuação e sublinhado por espaços e
colapso de espaços. Não há texto idêntico ou normalizado repetido, nem família
presente nos dois splits. Os exemplos são sintéticos e não medem desempenho
em conversas reais. Nenhum provedor foi consultado; métricas seguem não
aferidas. A meta de crise no holdout do plano operacional só poderá ser
calculada após existir contrato de avaliador e execução autorizada.
