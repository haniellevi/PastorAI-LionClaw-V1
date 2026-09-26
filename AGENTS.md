# Igreja 12: memória operacional para agentes

Este arquivo é o ponto de entrada obrigatório para agentes que trabalhem neste
repositório. Ele complementa instruções específicas da ferramenta e nunca
autoriza um efeito externo.

## Bootstrap obrigatório

Antes de analisar, planejar ou alterar o projeto:

1. confirme repositório, branch, SHA e estado do worktree;
2. leia [`docs/ops/MVP-PLANO-SIMPLIFICACAO.md`](docs/ops/MVP-PLANO-SIMPLIFICACAO.md):
   ele é o guia operacional (fases, prioridades, regras e travas);
3. leia [`docs/ai/PRD-COVERAGE.md`](docs/ai/PRD-COVERAGE.md) só quando a
   tarefa envolver escopo ou requisito;
4. para tarefa operacional, leia o runbook específico em `docs/ops/`.

A governança de migration e consentimento (E4B, D3, D6, D2A, atestações,
catálogo, F1/F2) e o `V1-FINALIZATION-MAP.md` estão **pausados e são
históricos** (branch `archive/governanca-2026-09`). Não abra missão nessas
frentes antes da Fase 5 do plano.

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
- A prioridade atual é o agente responder no WhatsApp da igreja piloto
  (Filadélfia); ver as fases do plano do MVP.
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
- `AgentConfig.ativo` por igreja;
- chave e igrejas da triagem Jev (Console da Plataforma ou `TYPESAFE_API_KEY` +
  `JEV_SHADOW_TRIAGE_IGREJA_IDS`; modo sombra, também sujeito a
  `ALLOW_REAL_SENDS`; envia texto pastoral em claro a processador terceiro e
  exige DPA antes de listar qualquer igreja).

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

- Trabalhe em branch ou worktree própria, com PR pequeno, e preserve
  alterações do usuário.
- Uma fatia vertical por vez, na ordem do plano do MVP, testada de ponta a
  ponta.
- CI obrigatório: `backend-tests`, `frontend-ci`, `e2e-critical` e
  `rls-integration`. Não crie testes que congelam hash de arquivo ou leem texto
  de documento.
- Banco: migration `AAAAMMDD_HHMMSS_slug.sql` com `igreja_id`, RLS e rollback
  comentado, aplicada com `backend/scripts/migrate.py` (DEV primeiro; PROD com
  backup antes). Ver `backend/migrations/README.md`. Não use
  `apply_migrations.py` nem os wrappers catalog-bound (pausados).
- Revisão independente só para migration em PROD e mudanças de
  RLS/autenticação.
- Não implemente UV ou CD a partir de placeholders antes da Fase 5.
- Use as versões fixadas pelo projeto: Python 3.13 e Node 24 (`.nvmrc`), com
  `umask 022`.

## Regra de manutenção

Ao fechar uma fatia:

1. atualize o checklist da fase em `docs/ops/MVP-PLANO-SIMPLIFICACAO.md`;
2. registre a fatia em `docs/sprints/AAAA-MM-DD-titulo.md`;
3. atualize `docs/ai/PRD-COVERAGE.md` só se a classificação de um domínio
   mudar.
