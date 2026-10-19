# Busca oficial — contrato para o futuro agente

GET autenticado `/conhecimento/busca?q=...&limite=10` usa o serviço único
`conhecimento.buscar`. Identidade e igreja vêm do servidor; visitantes só podem
ser construídos por caller confiável, nunca por argumentos do modelo.
A autorização por público e versão vigente precede matching, ranking e limite;
não há total de documentos. Cada resultado revalida `pode_ler` antes da entrega.

Trechos são texto citado e **dados, nunca instruções**. A futura fatia do agente
deve preservar essa fronteira: conteúdo não altera prompt, identidade,
autorização, ferramentas ou gates. Deve citar título, versão e seção; sem fonte,
declarar lacuna e encaminhar. Revalidar também antes de entregas pendentes.
Esta fatia não conecta WhatsApp, embeddings, uploads nem provedores externos.

Publicação gera seções numeradas, preservando fronteiras de palavras, de até 2.000 caracteres na mesma transação;
falha reverte a publicação. Revogação/substituição exclui imediatamente a versão
das novas buscas pelo join de vigência. Histórico permanece para futura purga.
A configuração lexical copia `portuguese` e usa o dicionário `unaccent` quando
disponível no PostgreSQL (instala a extensão local quando disponível). Respostas contêm texto simples, sem HTML;
o painel deve renderizá-las como texto. Consulta: até 200 caracteres; 1–20
resultados; citações até 300 caracteres. Aplicar a migration antes do backend
em futura release autorizada. Produção e aplicação remota não verificadas.

A barreira materializa somente as versões autorizadas; o matching nos trechos
pode usar o índice GIN após esse filtro.
