# Igreja 12: regras compartilhadas para agentes

## Autonomia de desenvolvimento

- Uma solicitação de implementação autoriza investigar, editar, testar e corrigir
  dentro do escopo, em ambiente local identificado, com dados fictícios e
  provedores simulados. Conclua esse trabalho sem aprovação a cada etapa.
- Resolva decisões técnicas locais e reversíveis com a menor alteração adequada.
  Pergunte quando a dúvida mudar requisito, comportamento esperado, acesso a dados,
  custo ou efeito externo. Explicite suposições relevantes sem interromper o restante.
- Se uma etapa depender de autorização, conclua as partes independentes e apresente
  a ação concreta a aprovar. Não crie ADR, processo, agente extra ou refatoração
  como pré-requisito sem necessidade para a entrega.

## Entrada e fontes

- Ao iniciar trabalho técnico, confirme repositório, branch, SHA e alterações locais;
  reconfirme se o checkout mudar. Preserve trabalho alheio e reutilize branch/worktree
  adequada; crie outra quando precisar isolar alterações. Análise sem edição não exige
  nova branch/worktree.
- Consulte o trecho pertinente do [ROADMAP.md](ROADMAP.md), única fonte ativa de
  planejamento. Para requisitos, use o [PRD canônico](docs/Docs20260611_163530/PRD20260611_163530.md)
  e, quando necessário, [PRD-COVERAGE](docs/ai/PRD-COVERAGE.md). Leia o runbook da
  operação em questão. Não releia documentos sem necessidade nem retome planos históricos.
- Fatos vivos identificados por ambiente/horário prevalecem sobre registros;
  Git/código/CI/testes do SHA exato provam apenas seu alcance. Merge ou teste
  verde não provam deploy, migration aplicada, credencial ou gate aberto.
  Sem prova, registre “não verificado”. Prioridades, decisões e estado dos ambientes
  ficam no ROADMAP; decisões vigentes prevalecem sobre registros antigos.

## Produto e segurança

- Preserve a configuração operacional do piloto Filadélfia, restrito à equipe
  interna. Nova ativação ou ampliação exige autorização específica conforme ROADMAP.
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

Exigem autorização humana explícita para ação, ambiente e escopo: acesso a dados
reais, alterações em produção ou banco remoto, deploy/restart remoto, canários,
envios reais, cobranças, exclusão de dados reais e mudanças de gates operacionais.
Use o runbook específico. Consulta a documentação pública e testes locais sintéticos
sem efeitos reais podem seguir dentro da tarefa. Autorização já dada vale no mesmo
escopo; só peça novamente se ação, ambiente, escopo ou risco relevante mudar.
Não inferir autorização de merge, teste, credencial validada ou canário anterior.
Preserve gates existentes:
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

Código e exemplos sanitizados, incluindo `.env.example`, podem ser lidos e editados
dentro do escopo. Revisão estática de scripts sanitizados não autoriza sua execução.
Segredos reais (`.env` reais, `*.pem`, `*.key`, `id_rsa*`, `id_ed25519*`, `secrets/`)
ficam fora do contexto, das saídas de ferramentas e do Git. Diagnóstico de configuração
mostra apenas nomes de variáveis e presença/ausência, nunca valores, mesmo parciais.
Ao achar segredo real em outro arquivo, avise o dono sem reproduzi-lo.

Não abra dados reais de pessoas (`backend/scripts/target_users*.json`, dumps, backups,
exports e mídias) sem autorização específica; não os copie para prompts, documentação,
logs ou commits. Scripts que contenham esses dados também estão protegidos.
Nunca copie dados/segredos de PROD para DEV/local nem conecte o número da
Filadélfia neles. Desenvolvimento usa dados fictícios e provedores simulados;
não presuma disponibilidade ou isolamento de DEV remoto. Stack local opcional:
[guia](docs/ops/AMBIENTE-LOCAL.md). Prioridades de infraestrutura seguem o ROADMAP.

## Entrega e validação

- Uma fatia por vez, PR pequeno e refatoração sob demanda; reutilize serviços existentes.
- Toda capacidade nova do agente exige ao menos um E2E do turno completo:
  inbound persistido, catálogo e roteador reais, serviço de domínio e resposta
  persistida/entregue pelo fluxo existente. Simule provedores externos;
  não substitua por mocks catálogo, roteador ou autorização que se quer provar.
  Cubra papel autorizado e recusa sem permissão.
- Durante o desenvolvimento, rode testes pertinentes à mudança. Antes da integração,
  são obrigatórios `backend-tests`, `frontend-ci`, `e2e-critical` e `rls-integration`
  no CI do candidato. Não repita toda a suíte após cada edição sem motivo.
  Não crie testes que congelam hash de arquivo ou leem texto de documento.
- Migration: `AAAAMMDD_HHMMSS_slug.sql`, `igreja_id`, RLS e rollback comentado;
  use `backend/scripts/migrate.py`, ambiente sintético primeiro e PROD só no
  release com backup prévio. Consulte [migrations](backend/migrations/README.md).
  Não use `apply_migrations.py` nem wrappers catalog-bound pausados.
- Revisão independente é obrigatória antes de integrar mudanças de RLS/autenticação
  e antes de aplicar migration em PROD; não bloqueia implementação e testes locais.
  Governança histórica permanece pausada conforme ROADMAP; não retome por obrigação documental.
- Use Python 3.13, Node 24 (`.nvmrc`) e `umask 022`; ferramentas opcionais só
  quando disponíveis e úteis, sem instalação obrigatória por tarefa.
- Registre entrega, testes e limites na descrição da PR; atualize o ROADMAP
  quando estado/escopo mudar. Sem novos sprints, plano paralelo ou obrigação de
  manter `tarefas.json`/painel. PRD-COVERAGE só muda se a classificação do domínio mudar.
- Commit, push, merge e release somente quando autorizados pela solicitação.
  Antes de push/merge, verifique automações disparadas; efeitos fora do escopo
  autorizado exigem decisão própria. Na entrega, informe mudanças, testes e limites.

## Encerramento de worktrees

- Ao concluir a tarefa e confirmar sua integração na `main` remota, encerre a worktree
  temporária. Antes de remover, confira alterações pendentes, arquivos úteis inclusive
  ignorados e uso por chats, processos ou contêineres; preserve o que ainda for necessário.
- Worktrees gerenciadas pelo Codex usam o arquivamento do aplicativo; as demais usam
  `git worktree remove`, sem `--force`. Preserve o checkout principal e áreas compartilhadas
  ou em uso. Se houver pendência, mantenha a pasta e informe o impedimento.
- Reutilize áreas adequadas e prefira o diretório próprio de worktrees da ferramenta;
  evite criar pastas avulsas na raiz do workspace. Não apague branches remotas.
