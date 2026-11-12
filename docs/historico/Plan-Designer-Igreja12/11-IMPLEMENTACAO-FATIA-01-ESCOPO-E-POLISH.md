# Implementação local, Fatia 01: escopos e polish

Data: 2026-08-11

Status: `PR RASCUNHO`, publicado e aguardando revisão humana

Commit da fatia: `fd90ccb9676eaee017be8f2bd7c023280c93e7c4`

Branch local: `codex/ux01-fatia1-scopes`

PR rascunho: [#247](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/247)

Grafo: `NÃO COMPROVADO`; validação por leitura direta, testes e auditoria autenticada do produto atual

## Objetivo executado

Primeira fatia vertical do plano aprovado, concentrada em impedir enumeração ou
mutação fora da responsabilidade pastoral, alinhar os CTAs ao contrato real da
API e corrigir problemas visuais pequenos sem reescrever o design já evoluído.

Esta fatia cobre a base do PR-01 do roadmap e quick wins seguros do PR-03. Ela
não implementa ainda a composição completa do Painel de Hoje por responsabilidade.

## Entregue

### Pessoas, Ganhar e Jornada

- escopo por tenant, papel acumulado, própria pessoa, célula liderada e conversa atribuída;
- operador e líder de célula deixam de enumerar a igreja inteira;
- CSIM e pessoas arquivadas ficam fora da Jornada em leitura e escrita direta por UUID;
- promoção limitada a admin, pastor, líder G12 e líder de consolidação;
- vínculo de célula limitado a admin e pastor no frontend e backend;
- atribuição de consolidador exige conta ativa da mesma igreja, preservando o contrato de capacidade por identidade.

### Células e árvore G12

- membro vê somente a própria célula ativa;
- líder vê a célula que lidera, inclusive inativa para gestão;
- alertas pastorais ficam com pastor, admin ou líder efetivo da célula;
- descendência respeita self, célula, responsabilidade ampla e tenant.

### Fila pastoral

- mesmo predicado de escopo em listagem, contagem, ação e mensagem;
- itens resolvidos saem antes da paginação;
- status `NULL` legado permanece operacional e normaliza ao assumir;
- takeover somente quando o responsável anterior está ausente, revogado, convidado ou incapaz;
- responsável ativo e capaz mantém proteção de concorrência;
- `canMessage` vem do servidor e usa a mesma conversa tenant-safe e determinística do envio;
- destinos de atribuição são ativos, aptos ao tipo da fila e carregados em todas as páginas.

### Conversas

- diretório dedicado `GET /team/inbox-lookup`, sem e-mail, status, Pessoa ou tipos de fila;
- líder de célula e operador mantêm transferência das conversas que atendem;
- destino é revalidado por tenant, status e papel de inbox no POST;
- revogado, convidado, incapaz e cross-tenant falham antes da mutação;
- todas as páginas de destinos são carregadas.

### Quick wins visuais

- busca decorativa removida da Topbar;
- gutters corrigidos em Agenda e Minha Célula;
- foco visível reforçado;
- botões sem quebra apenas em grupos responsivos, sem regressão global de overflow;
- textos operacionais abaixo do mínimo elevado para 12 px;
- nenhum breakpoint e nenhum rail do Dashboard foi alterado nesta fatia.

## Evidência visual de produção usada como baseline

Estas capturas mostram o produto em produção antes das correções locais. Não são
prova de deploy da fatia.

- [Agenda mobile, 360 px](assets/research/prod-2026-08-11/prod-agenda-mobile-360.png)
- [Minha Célula mobile, 360 px](assets/research/prod-2026-08-11/prod-minha-celula-mobile-360.png)

A captura desktop da fila foi mantida somente no acervo local de pesquisa, fora
do repositório, porque continha um nome de exibição da sessão autenticada.

## Validação consolidada

- backend: `2.291` testes coletados, suíte integral com exit code 0;
- backend: `compileall` PASS;
- frontend: `65` arquivos e `603/603` testes PASS;
- frontend: TypeScript `tsc --noEmit` PASS;
- frontend: build Next.js `15.5.22` PASS;
- lockfile: conteúdo idêntico ao HEAD, sem alteração intencional;
- `git diff --check`: PASS;
- revisão independente: `PASS`, sem finding P0, P1, P2 ou P3 remanescente.

## Medido, inferido e ainda não comprovado

### Medido

- código e contratos da base local;
- testes unitários e integrações simuladas por papel, tenant, estado e UUID direto;
- build com dependências exatas do lockfile;
- produto autenticado atual em 360, 768 e 1440 px para os recortes desta fatia;
- revisão independente do diff consolidado.

### Inferido

- o resultado visual local deve remover a busca falsa e melhorar gutters e botões;
- a experiência de cada papel deve corresponder aos predicados testados.

### Não comprovado nesta fatia

- smoke autenticado local com dados reais de todos os papéis;
- integração descartável em PostgreSQL com RLS real e dois tenants;
- corrida real entre revogação e transferência/atribuição durante sessão aberta;
- deploy ou comportamento em produção após estas mudanças.

## Decisões preservadas para a próxima fatia

1. Painel de Hoje ainda usa composição ampla por `isLeader`; a composição por responsabilidades acumuladas é a próxima mudança recomendada.
2. `DESIGN.md` diz “sem rail persistente”, enquanto o runtime usa rail em desktop largo e o conceito aprovado o explora. Não alterar sem decisão explícita.
3. Agenda, Minha Célula e Central precisam de fatias próprias para completar fluxos, não de uma reescrita visual global.

## Gate

Commit, push e PR rascunho foram autorizados e concluídos. Não houve merge,
migration, deploy, alteração de banco, produção ou envio externo. Esses passos
continuam dependendo de autorização explícita do dono do produto.
