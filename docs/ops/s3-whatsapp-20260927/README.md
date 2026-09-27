# S3: identidade e confirmação por ação no WhatsApp

Candidato source-only a partir de `2e08d11`, sem deploy ou ativação.
[Plano aprovado](../mvp-s3-whatsapp-first-plano.md). A PR426 e seu SQL ficam
congelados; somente a branch S3 pode receber rebase depois do merge426.

## Limites de autoridade

Telefone único identifica operacionalmente um acesso ativo; não prova posse
forte. O backend deriva tenant, Pessoa, AppUser, papéis e responsabilidades.
Ambiguidade encaminha para humano. Texto, modelo e handles não concedem papel.

A proposta oferece somente duas ações mutantes: decisão (admin, pastor ou
líder de consolidação) e confirmação de presença prevista de terceiro em uma
reunião (permissão humana sobre a célula, alvo membro ativo). Presença usa
`CelulaPresenca.estado=confirmada`; não altera contador legado nem declara
comparecimento real. Os serviços internos são os mesmos usados pelo painel.

O resumo precisa ter entrega confirmada antes do SIM. O TTL é de dez minutos,
sem renovação por retry. Ator, alvo, ação, argumentos e escopo são vinculados;
cancelamento, mudança de papel ou termo impede execução. Efeito, uso único e
intent do comprovante pertencem à mesma transação; transporte ocorre após commit.

Consultas readonly cobrem o próprio vínculo e nomes das células autorizadas,
mediante confirmação explícita na sessão vigente do painel ligada ao Clerk.
O desafio vale cinco minutos e a prova quinze. O produto usa JWT local;
esta confirmação não declara nova autenticação nativa no provedor Clerk.
Finanças, notas pastorais, conversas privadas e endereço residencial ficam fora.
A emissão de desafios é exclusiva do worker; o painel confirma somente os seus.
Respostas privadas não entram no histórico de gerações posteriores.

## Classificação e gates

O OpenAI BYO da igreja escolhe enum e handles de um catálogo limitado pelo
servidor. B precede C, C precede D; erro/schema inválido/timeout causa handoff.
Regex e supressão tipada continuam. Confirmações locais precedem classificadores.
Jev B/C/D é opcional e permanece inerte sem releases e gates próprios.

O catálogo é deliberadamente limitado: até oito pessoas para decisão, 64 células
para buscar presença, quatro reuniões por célula na janela de 14 dias antes/depois
e 16 handles por ferramenta. Consulta sensível mostra até dez células. Alvos
fora do catálogo exigem atendimento humano; esta fatia não implementa busca geral.
Homônimos e resumos ambíguos são omitidos, inclusive colisões antes desses limites.
A contagem de nomes ocorre no servidor e não amplia a projeção enviada ao modelo.

A flag `AGENT_PRIVILEGE_ENABLED_IGREJA_IDS` é vazia por padrão. Ativação interna
sem Jev não exige DPA TypeSafe, mas depende de ordem nominal de Raniel e testes.
Jev mantém DPA, aprovação de release e métricas de holdout independentes.
A meta de latência é inferior a dez segundos; mocks não comprovam p95 real.

## Compatibilidade, operação e rollback

Frontend pode publicar antes do backend: endpoint de confirmação ausente
mostra indisponibilidade e não concede acesso. A migration S3 deve ser aplicada
sob seu gate antes de implantar o backend que consulta as novas colunas/tabelas.
PR, revisão Sarah, merge, migration, deploy e ativação são etapas separadas.
Nada aqui altera DEV, PROD, VPS, provedores ou credenciais reais.

Rollback imediato: remover a igreja da flag mantendo esta versão do backend,
que suprime respostas S3 pendentes. Reverter o binário só depois de conferir que
o ledger S3 não possui envio pendente, pois versões antigas ignoram seus gates.
Preservar registros; não reenviar mensagens ambíguas nem reaplicar ações.
SQL reverso permanece comentado e depende de gate próprio, com dados preservados.

## Evidência local

PostgreSQL17.6 descartável em loopback; nenhuma chamada real de LLM, TypeSafe ou
WhatsApp. Testes incluem fluxo worker para as duas ações, uso único/retry, TTL,
rollback após efeito antes do comprovante, alteração de termo e papel, retorno
de humano para IA, destino divergente e exclusão de resumo privado do histórico.
A suíte RLS verifica tenants/policies e há banco separado para aplicar os bytes
exatos da migration no schema public. O CI cria esse banco efêmero e rejeita skip.
Números finais, SHA e hash SQL ficam no relatório de validação do candidato.
