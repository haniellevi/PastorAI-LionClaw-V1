# Igreja 12: memória operacional para agentes

Este arquivo é o ponto de entrada obrigatório para agentes que trabalhem neste
repositório. Ele complementa instruções específicas da ferramenta e nunca
autoriza um efeito externo.

## Bootstrap obrigatório

Antes de analisar, planejar ou alterar o projeto:

1. confirme repositório, branch, SHA e estado do worktree;
2. leia [`docs/ai/AI-BOOTSTRAP.md`](docs/ai/AI-BOOTSTRAP.md);
3. leia [`docs/ai/PRD-COVERAGE.md`](docs/ai/PRD-COVERAGE.md) quando a tarefa
   envolver escopo, requisito, roadmap ou definição de pronto;
4. leia [`docs/WIKI-IGREJA12.md`](docs/WIKI-IGREJA12.md) e o runbook específico
   antes de qualquer tarefa operacional;
5. fixe critérios de aceite, riscos de tenant, testes e rollback antes de
   alterar código ou schema.

Um snapshot documental não substitui o código atual, o CI do mesmo SHA ou o
estado vivo do ambiente correto.

## Ordem das fontes de verdade

Quando houver divergência, use esta precedência:

1. estado vivo consultado no momento da ação, com ambiente e horário
   identificados;
2. Git, CI, código, migrations e testes do SHA exato;
3. PRD canônico e decisões técnicas aprovadas;
4. `docs/audits/2026-08-27-d1-security-scope-audit.md`, seguido de
   `docs/audits/2026-08-27-project-source-of-truth.md`, do registro pós-V1 e
   dos runbooks em `docs/ops/`;
5. `docs/ai/AI-BOOTSTRAP.md`, `docs/ai/PRD-COVERAGE.md`,
   `docs/WIKI-IGREJA12.md`, `PRODUCT.md`, `SPEC.md`, `SPEC_PROGRESS.md` e Plan
   Designer;
6. auditorias substituídas, PRDs temáticos, sprints e planos históricos,
   usados como intenção e rastreabilidade.

Documentação prova o que foi registrado. Código prova implementação. Teste
verde prova apenas o comportamento exercitado naquele SHA. Nenhum desses itens
prova, isoladamente, migration aplicada, deploy, flag, credencial, fila ou dado
de produção.

## Estado de produto que deve permanecer explícito

- A V1 está encerrada como piloto controlado.
- O produto amplo WhatsApp-first ainda não está concluído.
- O WhatsApp é a interface operacional principal. O painel existe para
  configuração, governança, exceções e ações sensíveis.
- O comportamento do agente é global e versionado. Memória, conhecimento,
  configuração, dados e execução são isolados por igreja.
- Conversas são memória privada. Elas nunca viram conhecimento institucional
  automaticamente.
- Registros oficiais e documentos aprovados pelo admin são as fontes de
  conhecimento da igreja.
- Universidade da Vida e Capacitação Destino ainda não são módulos completos.
- Relatório de célula pelo WhatsApp é a primeira fatia vertical da nova fase.
- OpenAI BYO é a credencial de IA da igreja. OpenRouter não integra o PastorAI.

## Segurança, tenant e dados

- Toda leitura e escrita de domínio precisa validar `igreja_id` no backend e na
  RLS. Nunca aceite tenant, identidade, papel ou capacidade informados pelo
  modelo.
- Pessoa, acesso, papel e responsabilidade são conceitos distintos.
- Ferramentas do agente reaproveitam serviços de domínio e autorizações do
  caminho humano. Não escrevem diretamente em tabelas para contornar regras.
- Dados vivos, como pessoas, células, agenda e formação, são consultados por
  ferramentas tipadas. Embeddings não substituem a fonte transacional.
- Mensagens, mídia, transcrições, resumos, checkpoints e vetores derivados são
  dados privados. A exclusão aprovada deve alcançar todas essas camadas.
- Não copie PII, dados pastorais, segredos ou dados de produção para prompts,
  documentação, issues, logs de CI ou artefatos de revisão.

## Gates e ações externas

Efeitos externos são deny-by-default. Permanecem sujeitos a autorização humana
nominal e runbook específico:

- `ALLOW_REAL_SENDS`;
- `ASAAS_BILLING_ENABLED`;
- `BREVO_SEND_MODE`;
- `BROADCAST_ASYNC_ENABLED`;
- `AgentConfig.ativo` por igreja.

Merge, teste verde, migration criada, credencial validada ou canário anterior
não abre gate para uma ação futura. Canários de agente, broadcast, Brevo e
Asaas são missões independentes.

## Caminhos protegidos

Nunca abra, resuma, imprima ou versiona:

- `.env` e `.env.*`, exceto exemplos sanitizados explicitamente autorizados;
- `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*` e diretórios `secrets/`;
- `backend/scripts/clerk_*`;
- `backend/scripts/target_users*.json`;
- `backend/scripts/migrate_clerk_production.py`;
- dumps, backups, exports ou mídias que possam conter dados reais.

Se um caminho protegido parecer necessário, pare e solicite um gate específico
sem ler seu conteúdo.

## Contrato de mudança

- Trabalhe em branch ou worktree própria e preserve alterações do usuário.
- Mudança estrutural atualiza a fonte canônica, a matriz de cobertura e a Wiki.
- Banco ou Supabase exige migration imperativa, RLS, grants e revokes
  explícitos, testes cross-tenant, rollback ou compensação e verificação em
  PostgreSQL descartável antes de qualquer ambiente compartilhado.
- Captura, atestação, reconciliação ou aplicação de migrations exige fonte em
  snapshot privado do SHA exato criado por
  `backend/scripts/trusted_repository_snapshot.py`; o checkout compartilhado
  não é uma fonte operacional confiável e não deve receber `chmod` recursivo.
- Não implemente UV ou CD a partir de placeholders. Primeiro aprove um PRD
  próprio e a máquina de estados anterior da jornada.
- Use as versões fixadas pelo projeto. O frontend usa Node 24, não Node 20 nem
  a versão global do shell.
- Registre evidência com SHA, ambiente, horário e limite. Não converta ausência
  de prova em conclusão positiva.

## Regra de manutenção

Quando arquitetura, requisito ou estado operacional mudar:

1. atualize o documento ou código primário;
2. atualize `docs/ai/PRD-COVERAGE.md` se a classificação mudar;
3. atualize a Wiki e o registro operacional quando o estado vivo mudar;
4. registre testes e SHA sem inferir produção;
5. mantenha exatamente um próximo gate que exija autorização.
