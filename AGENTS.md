# Igreja 12 — regras compartilhadas para agentes

## Entrada e fontes

- Confirme repositório, branch, SHA e alterações locais; leia [ROADMAP.md](ROADMAP.md),
  a única fonte ativa de planejamento. Preserve trabalho alheio em branch/worktree própria.
- Para requisitos, consulte o [PRD canônico](docs/Docs20260611_163530/PRD20260611_163530.md)
  e os trechos pertinentes de [PRD-COVERAGE](docs/ai/PRD-COVERAGE.md).
  Para operação, leia o runbook específico. Planos, sprints, auditorias e painel
  antigos servem como histórico; suas sequências não são instruções ativas.
- Fatos vivos identificados por ambiente/horário prevalecem sobre registros;
  Git/código/CI/testes do SHA exato provam apenas seu alcance. Merge ou teste
  verde não provam deploy, migration aplicada, credencial ou gate aberto.
  Sem prova, registre “não verificado”. Decisões aprovadas de 15/10 no ROADMAP
  prevalecem sobre prioridades e cortes antigos, inclusive UV/CD.

## Produto e segurança

- Piloto Filadélfia restrito à equipe interna; a decisão de 15/10 mantém o agente
  como está, sem autorizar nova ativação ou ampliação. A V1 encerrou como piloto;
  o produto amplo WhatsApp-first não está concluído. Siga a ordem do ROADMAP.
- WhatsApp é a interface operacional principal; painel para configuração,
  supervisão, exceções e ações sensíveis. Comportamento global e versionado;
  dados, memória, conhecimento, credenciais e execução isolados por igreja.
  OpenAI BYO por igreja; OpenRouter não integra o produto.
- Toda leitura/escrita de domínio valida `igreja_id` no backend e na RLS.
  Autenticação e autorização vêm do servidor, nunca do modelo; pessoa, acesso,
  papel e responsabilidade são distintos. Revalide vínculo/capacidade no uso.
- Ferramentas do agente reutilizam serviços e autorizações do caminho humano;
  não escrevem tabelas para contornar regras. Dados vivos vêm de ferramentas
  tipadas, não de embeddings. Preserve confirmação, transação, idempotência,
  resposta após commit e recuperação; ações sensíveis exigem autenticação web.
- Opt-out global prevalece antes de qualquer resposta. Preserve consentimento,
  elegibilidade por finalidade/canal e handoff; não mude regras ao refatorar.
- Conversas, mídia, transcrições, resumos, checkpoints e vetores derivados são
  privados. Exclusão aprovada alcança todas essas camadas. Conhecimento oficial
  vem de registros oficiais e documentos aprovados pelo admin, nunca de
  conversas convertidas automaticamente.
- Não copie PII, dados pastorais, segredos ou dados de produção para prompts,
  documentação, issues, logs de CI ou artefatos de revisão.

## Produção e efeitos externos

Produção, banco remoto, deploy, restart, canário e efeitos externos exigem
autorização humana nominal e runbook específico. Não inferir autorização de
merge, teste, credencial validada ou canário anterior. Preserve gates existentes:
`ALLOW_REAL_SENDS`, `ASAAS_BILLING_ENABLED`, `BREVO_SEND_MODE`,
`BROADCAST_ASYNC_ENABLED`, `AgentConfig.ativo` e listas/releases por igreja e
finalidade. Canários de agente, broadcast, Brevo e Asaas são independentes.

Jev, inclusive sombra (`TYPESAFE_API_KEY`/Console e
`JEV_SHADOW_TRIAGE_IGREJA_IDS`), envia texto pastoral em claro a terceiro:
exige DPA antes de listar igreja, gates técnicos, avaliação e decisão nominal.
O modo sombra também depende de `ALLOW_REAL_SENDS`.
Não abrir gate para fazer teste passar. Fechar gate não equivale a pausar fila:
pode cancelar pendências; contenção e retomada exigem procedimento próprio.

## Caminhos protegidos

Nunca abra, resuma, imprima ou versione:

- `.env` e `.env.*`, salvo exemplos sanitizados explicitamente autorizados;
- `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*` e diretórios `secrets/`;
- `backend/scripts/clerk_*`, `backend/scripts/target_users*.json` e
  `backend/scripts/migrate_clerk_production.py`;
- dumps, backups, exports e mídias que possam conter dados reais.

Se precisar de caminho protegido, pare e solicite gate específico sem lê-lo.
Nunca copie dados/segredos de PROD para DEV/local nem conecte o número da
Filadélfia neles. Desenvolvimento usa dados fictícios e provedores simulados;
DEV online é planejado, não disponível por presunção. Stack local opcional:
[guia](docs/ops/AMBIENTE-LOCAL.md). Infraestrutura fica no final do ROADMAP.

## Entrega e validação

- Uma fatia por vez, PR pequeno e refatoração sob demanda. Edição local
  reversível com dados sintéticos: implemente, teste e apresente sem aprovação
  de cada edição, ADR, grafo, pipeline ou agente extra obrigatório.
- Toda capacidade nova do agente exige ao menos um E2E do turno completo:
  inbound persistido, catálogo e roteador reais, serviço de domínio e resposta
  persistida/entregue pelo fluxo existente. Simule provedores externos;
  não substitua por mocks catálogo, roteador ou autorização que se quer provar.
  Cubra papel autorizado e recusa sem permissão.
- Testes proporcionais à mudança; antes da integração são obrigatórios
  `backend-tests`, `frontend-ci`, `e2e-critical` e `rls-integration`.
  Não crie testes que congelam hash de arquivo ou leem texto de documento.
- Migration: `AAAAMMDD_HHMMSS_slug.sql`, `igreja_id`, RLS e rollback comentado;
  use `backend/scripts/migrate.py`, ambiente sintético primeiro e PROD só no
  release com backup prévio. Consulte [migrations](backend/migrations/README.md).
  Não use `apply_migrations.py` nem wrappers catalog-bound pausados.
- Revisão independente só para mudanças de RLS/autenticação e migration em PROD.
  Governança E4B/D3/D6/D2A, atestações, catálogos e F1/F2 históricos continuam
  pausados; não reabrir por obrigação documental. UV/CD seguem o ROADMAP.
- Use Python 3.13, Node 24 (`.nvmrc`) e `umask 022`; ferramentas opcionais só
  quando disponíveis e úteis, sem instalação obrigatória por tarefa.
- Registre entrega, testes e limites na descrição da PR; atualize o ROADMAP
  quando estado/escopo mudar. Sem novos sprints, plano paralelo ou obrigação de
  manter `tarefas.json`/painel. PRD-COVERAGE só muda se a classificação do domínio mudar.
- Commit, push, merge e release somente quando autorizados pela solicitação.
