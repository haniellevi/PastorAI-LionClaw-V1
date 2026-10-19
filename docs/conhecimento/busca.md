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

A migration exige papel com `rolbypassrls=true` (ou superusuário) e recusa
explicitamente um executor sem essa capacidade. FORCE RLS significa que ser
apenas dono das tabelas não basta. O executor torna-se dono de
`public.conhecimento_gerar_trechos()` SECURITY DEFINER, com `search_path=pg_catalog`
fixo e referências de domínio qualificadas. Na futura release, conferir no
catálogo o proprietário (`pg_proc.proowner`) e `pg_roles.rolbypassrls`/`rolsuper`;
conservar esse dono como papel administrativo confiável, sem associação dos
papéis da aplicação. Não transferir a função para `authenticated`, `anon` ou
`service_role`. Essa conferência no ambiente remoto permanece não verificada.

`authenticated` recebe somente SELECT nos trechos. O BEFORE INSERT exige versão
publicada, execução aninhada no gatilho e o dono da função de publicação como
usuário efetivo; INSERT direto é recusado inclusive pelo owner. A geração
privilegiada revalida explicitamente o escopo da igreja. O backfill privilegiado
ocorre antes da instalação dessa guarda, dentro da transação da migration;
qualquer versão publicada sem trechos ao final aborta toda a migration.
O rollback comentado usa transação, lock_timeout e locks exclusivos, recusando
remover trechos/citações ou versões publicadas existentes.

A extensão é instalada com `CREATE EXTENSION IF NOT EXISTS unaccent SCHEMA
extensions`, criando o schema se necessário; uma extensão preexistente conserva
seu schema e o dicionário é resolvido pelo catálogo. Sem unaccent disponível,
a configuração mantém somente o stemmer português: busca continua funcionando,
mas equivalência entre palavras com/sem acento não é garantida. A futura
release deve validar esse comportamento no PostgreSQL alvo, sem remover uma
extensão compartilhada no rollback. Consultas com caracteres Unicode de controle
(categoria Cc, incluindo NUL, tabulação e quebras de linha) recebem HTTP 422
antes de executar a busca no banco.
