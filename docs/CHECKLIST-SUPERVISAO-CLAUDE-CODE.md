# Checklist de supervisão — Igreja 12

Atualizado em: 2026-06-25 — F3 fechada; F4 polish/PWA em planejamento

Este documento organiza a ordem dos trabalhos enviados ao Claude Code. Execute
**um prompt por vez**. Ao terminar uma etapa, traga o relatório do Claude Code
para revisão antes de enviar o prompt seguinte.

## Como este arquivo funciona

- Este é o documento vivo de supervisão do redesign. Ele **não se atualiza
  sozinho** nem consegue ler automaticamente o conteúdo de outras conversas.
- O arquivo deve ser atualizado depois de cada relatório do Claude Code, mudança
  de branch, PR, gate aprovado ou bloqueio descoberto.
- Somente prompts completos dentro de um bloco `text` estão prontos para envio.
  Tópicos resumidos, como os atuais Prompts 4–6, são rascunhos que ainda serão
  transformados em prompts completos conforme o estado real do projeto.
- Em visualizadores Markdown compatíveis, incluindo GitHub, cada bloco de código
  possui um botão de copiar no canto superior direito. Copie somente o conteúdo
  do bloco do prompt atual, nunca o documento inteiro.
- Se estiver vendo apenas o texto cru e o botão não aparecer, abra o arquivo no
  modo Preview do editor ou no GitHub. Manter os prompts em Markdown evita criar
  uma segunda cópia em HTML que poderia ficar desatualizada.

## Onde cada tipo de regra deve ficar

- `C:\Users\hanie\.claude\CLAUDE.md`: comportamento global e durável do Claude
  Code, como autonomia, mudanças cirúrgicas, worktrees e verificação.
- `CLAUDE.md` do PastorAI: arquitetura, comandos, segurança, RLS, CodeGraph e
  regras específicas deste repositório.
- Este checklist: estado atual, ordem F0–F4, gates e o texto exato do próximo
  prompt.
- As melhores práticas detalhadas abaixo servem como referência para preparar os
  prompts. Elas **não precisam ser coladas integralmente em cada execução**, pois
  o núcleo permanente já está nas regras globais. Cada prompt deve repetir apenas
  restrições específicas e críticas daquela tarefa.

## Regra principal

Não envie todos os prompts de uma vez. A ordem é:

1. estabilizar Git e CodeGraph;
2. validar e fechar a F0;
3. atualizar a F0 com a `main` e abrir o PR;
4. executar a F1;
5. criar os testes e gates de qualidade;
6. corrigir deploy e CI;
7. executar F2, F3 e F4;
8. homologar em staging e fazer o piloto real.

## Regra para várias conversas abertas

É permitido manter várias conversas trabalhando em paralelo, mas somente quando
cada uma possui **uma missão, uma branch e um worktree diferentes**. Duas
conversas não devem editar a mesma branch nem os mesmos arquivos ao mesmo tempo.

Antes de enviar qualquer novo prompt, registrar:

| Frente | Conversa responsável | Branch | Worktree | Arquivos principais | Estado |
|---|---|---|---|---|---|
| Redesign F0 | Opus 4.8 — conversa que reconheceu o worktree | `feat/redesign-f0-tokens` | `hardcore-sammet-e68aa1` | `globals.css`, marca e `docs/design` | em andamento |
| Deploy reproduzível | identificar | identificar | identificar | Dockerfile, Compose e `.env.example` | possível trabalho local |
| CodeGraph/configuração | identificar | configuração local | repositório/worktree correto | `.mcp.json`, `.claude/settings.json` | pendente |
| Outras conversas | identificar | identificar | identificar | identificar | desconhecido |

### O que o Claude Code consegue descobrir

O Claude consegue inventariar worktrees, branches, mudanças locais, processos e
PRs. Ele normalmente **não conhece a missão completa de outras janelas de
conversa**. Portanto:

1. ele deve inferir o possível escopo pela branch, diff e arquivos alterados;
2. quando houver sobreposição ou missão ambígua, deve parar e pedir ao usuário o
   nome/objetivo daquela conversa;
3. nunca deve fechar conversa, apagar worktree ou descartar mudanças para
   “organizar” o ambiente;
4. antes de commit, rebase, push ou PR, deve repetir o inventário de concorrência.

### Bloco de coordenação para colocar no início de novos prompts

```text
COORDENAÇÃO COM OUTRAS CONVERSAS
- Antes de editar, execute `git worktree list --porcelain`, `git branch -vv` e
  consulte os PRs abertos.
- Para cada worktree relevante, informe branch, HEAD, status e diff --stat.
- Identifique outras frentes que possam tocar os mesmos arquivos deste prompt.
- Não edite branch ou worktree pertencente a outra conversa.
- Não apague, mova, faça stash ou descarte mudanças de outra frente.
- Se houver sobreposição de arquivos, branch sem dono claro ou missão ambígua,
  pare antes de escrever e peça ao usuário para definir qual conversa é a dona.
- Repita esta checagem antes de commit, rebase, push ou abertura de PR.
```

## Glossário simples

- **Fase ou F:** um pedaço pequeno do redesign. `F0` significa “fase zero”,
  `F1` significa “fase um” e assim por diante.
- **F0 — Fundação:** troca os tokens básicos: cores, bordas, raios, sombras e
  nomes da marca. É como trocar a tinta e os materiais antes de reformar os
  cômodos.
- **F1 — Identidade:** aplica logo, fontes, gradientes, sidebar e detalhes que
  deixam o produto reconhecível como Igreja 12.
- **F2 — Navegação:** reorganiza menus e atalhos, preservando as rotas e
  permissões existentes.
- **F3 — Mobile:** adapta tabelas, modais e telas densas para celular.
- **F4 — Polimento:** acessibilidade, microinterações, PWA e revisão final.
- **Branch:** linha de trabalho isolada. Permite experimentar sem alterar a
  versão principal.
- **Commit:** fotografia de um conjunto de mudanças.
- **PR (Pull Request):** pedido para revisar e juntar uma branch na `main`.
- **`main`:** linha principal do projeto. Deve permanecer estável.
- **Worktree:** outra pasta do mesmo repositório, usada para trabalhar em uma
  branch sem misturar arquivos.
- **Conversa responsável:** janela do Claude Code que é a única autorizada a
  continuar determinada frente/branch.
- **Build:** processo que verifica se o sistema consegue gerar a versão final.
- **CI:** testes automáticos executados no GitHub a cada PR.
- **CodeGraph / CRG:** mapa estrutural atualizado do código. Ajuda a descobrir
  dependências, impacto e testes relacionados.
- **Graphify:** snapshot semântico amplo de código e documentos. Neste projeto
  passa a ser **opcional**, não faz parte do fluxo diário.
- **Gate:** condição que precisa passar antes de avançar.

## Decisão sobre CodeGraph e Graphify

### Estado verificado

- CodeGraph do repositório principal: atualizado pela última vez em 22/06,
  branch `feat/master-console`, commit `168fb66`.
- CodeGraph do worktree do redesign: reconstruído em 24/06 para a branch
  `feat/redesign-f0-tokens`, com 242 arquivos e 2.278 nós.
- Trabalho atual do redesign: dois commits (`4b95d75` e `94a3afe`) rebaseados
  sobre `origin/main` no commit `95553d2` e enviados para o PR draft #35.
- O hook antigo apontava para o repositório principal; a execução da F0 passou a
  reconstruir o grafo no worktree correto. O revisor independente confirmou que
  o hook usa `git rev-parse --show-toplevel`, sem caminho fixo para o
  repositório principal.
- O snapshot Graphify não está presente nos checkouts verificados e a referência
  conhecida é periódica, não em tempo real.

### Decisão

- Usar **CodeGraph como ferramenta principal e obrigatória** para navegação,
  impacto e revisão de código.
- Corrigir o hook para descobrir dinamicamente o worktree atual.
- Não apagar nem desinstalar Graphify agora. Apenas retirar sua execução dos
  prompts e do checklist diário.
- Usar Graphify somente se surgir uma tarefa específica de cruzar muitos PRDs,
  documentos e código num snapshot semântico.

## Situação atual do redesign

- [x] Protótipo standalone criado.
- [x] Contrato `RECONCILIACAO-igreja12.md` criado.
- [x] Branch local `feat/redesign-f0-tokens` criada.
- [x] Tokens da F0 modificados localmente.
- [x] A conversa atual reconheceu corretamente que a F0 pertence ao worktree
  `hardcore-sammet-e68aa1` e não ao worktree `nervous-sinoussi-8cb3fe`.
- [x] Concorrência rechecada antes do push; nenhuma outra sessão encontrada na
  branch `feat/redesign-f0-tokens`.
- [x] CodeGraph reconstruído para o worktree correto.
- [x] Preview autenticado abriu e a resolução do conflito em Agente IA foi
  verificada ao vivo.
- [x] `typecheck`, lint e build comprovados depois do rebase.
- [x] F0 commitada em dois commits de escopo separado.
- [x] Branch atualizada sobre `origin/main`.
- [x] PR draft #35 aberto, com cinco arquivos e sem checks de CI configurados.
- [x] Revisão independente confirmou diff, commits, gates técnicos, CodeGraph,
  hook dinâmico, mergeabilidade e ausência de bloqueador da F0.
- [ ] Evidência visual direta de recuperação de senha e telas internas
  autenticadas permanece limitada; o revisor considerou não bloqueante para
  sair de draft porque a F0 não altera autenticação nem regras funcionais.
- [x] PR #35 saiu de draft e entrou em revisão.
- [x] PR #35 saiu de draft, foi aprovado e mesclado.
- [x] `origin/main` contém a F0 no merge commit `7b57d3e`.
- [x] Registro de sprint/documentação pós-merge criado em `docs/sprints`.
- [x] Registro de sprint/documentação pós-merge foi enviado ao remoto e
  mesclado na `main` pelo PR #36.
- [x] F1 iniciada.
- [x] F1 implementada na branch `feat/redesign-f1-identidade`, commit
  `0e42310`, PR draft #37.
- [x] F1 revisada independentemente; sem bloqueadores, `APTO PARA SAIR DE DRAFT`.
- [x] Bloqueio do login local diagnosticado: não é senha; `frontend/.env.local`
  ausente faz o frontend apontar para `http://localhost:8000`, mas o backend
  local está offline.
- [x] Ambiente local ajustado para permitir smoke visual autenticado.
- [x] Smoke visual autenticado via Chrome visível, com login manual do usuário:
  telas internas desktop aprovadas em modo read-only; recomendação final
  `TIRAR PR #37 DE DRAFT`.
- [x] PR #37 saiu de draft; HEAD `0e42310` inalterado, MERGEABLE/CLEAN.
- [x] PR #37 foi aprovado e mesclado na `main`; merge commit `85bc1ea`.
- [x] Sprint da F1 registrado em `docs/sprints` e mesclado pelo PR #39;
  `origin/main` em `3e0d4c4`.
- [x] F1.5 auditada: ambiente atual não separa dev/staging/produção; local/dev
  usa banco/auth/serviços reais.
- [x] B1 planejado: staging deve ser projeto Supabase dedicado, não Postgres
  local.
- [x] B1-IMPL entregue em PR #40 com artefatos versionáveis de staging, sem
  tocar banco/produção.
- [x] PR #40 revisado e mesclado; merge commit `9726e06`.
- [x] Ações manuais B1 executadas e gates fechados: Supabase staging, bucket,
  Clerk dev, usuário de teste, migrations, envs, login, RLS e guard `[SANDBOX]`.
- [x] Fechamento B1 manual registrado no histórico pelo PR docs #43;
  `origin/main` em `e32fdd15dc2bdce93f6e56216c369c3dfd60952c`.
- [x] B2 planejado: guard/sandbox para impedir WhatsApp, cobrança, e-mail, LLM
  e Calendar reais fora de produção.
- [x] B2-IMPL implementado e entregue em PR draft #41; commit `91736bd`.
- [x] PR #41 revisado independentemente: `APTO PARA SAIR DE DRAFT`.
- [x] PR #41 tirado de draft; head/commits inalterados.
- [x] PR #41 mesclado; B2 presente na `origin/main`, merge commit `7cd30bb`.
- [x] Registro docs do bloco B1/B2 criado em `docs/sprints` e mesclado pelo
  PR #42; `origin/main` em `ab4ea2a`.

### Atenções atuais

- Não copiar `globals.css` para o repositório principal para fazer preview.
- Não apagar nem resetar mudanças existentes na `main`.
- O repositório principal está atrás de `origin/main` e possui mudanças locais;
  elas precisam ser inventariadas e preservadas.
- O protótipo é referência visual. Ele não autoriza implementar Universidade da
  Vida, Capacitação, treinamentos, financeiro ou outras funções futuras.
- `plano-redesign-igreja12.html`, `roadmap-proximas-fases.html` e
  `docs/design/_work` não pertencem ao commit da F0.
- O sprint da F0 foi registrado em
  `docs/sprints/2026-06-25-redesign-f0-fundacao-tokens.md`, no commit
  `3a7374c`, e versionado na `main` pelo PR #36, merge commit `67114b2`.
- Próxima ação: desbloquear o ambiente local antes de repetir o smoke visual.
  O diagnóstico mostrou que o login falha porque o frontend local está tentando
  falar com `localhost:8000` e não há backend rodando ali. Não é evidência de
  senha inválida.
- Caminho recomendado: configurar apenas ambiente local/gitignored para apontar
  o frontend a um backend compatível que contenha a conta do usuário e aceite
  origem `http://localhost:3000`; depois repetir o Prompt 3.6.
- Separação de ambientes: o deploy público atual não deve ser tratado como
  produção operacional madura se ainda não há usuários reais/piloto ativo. Mesmo
  assim, antes de F2/F3 ou piloto real, registrar F1.5 para separar dev/staging
  de produção e reduzir risco de mutação em dados reais.
- Auditoria F1.5 já executada de forma read-only. Conclusão: hoje não há
  separação real; dev/local aponta para produção em banco/auth e pode alcançar
  serviços externos reais. Para a F1, smoke visual read-only ainda é tolerável.
  Para F2/F3, B1+B2 são bloqueadores.
- Smoke read-only da F1 concluído: Dashboard, Sidebar ativo/hover/inativo,
  Topbar, Pessoas/Contatos, Comunicação e Conversas aprovados visualmente. Não
  foram abertos modais de ação para evitar mutação, e mobile autenticado não foi
  capturado por limitação do Chrome visível; ambos foram classificados como
  baixo risco para F1.
- Backend local `:8000` usado contra dados reais no smoke foi encerrado após o
  PR #37 sair de draft. Frontend `:3000` ficou ligado, mas sem backend não deve
  ser usado para navegação autenticada.
- F1 mesclada na `main` pelo PR #37, merge commit `85bc1ea`. Durante o ciclo da
  F1, a `main` também recebeu o PR #38 de outra conversa, relacionado ao botão
  mostrar/ocultar senha no login; o merge da F1 ocorreu limpo por cima desse
  avanço.
- Registro pós-merge da F1 concluído pelo PR docs #39, merge commit `3e0d4c4`.
  O registro corrigiu a descrição técnica para refletir o diff real: corpo em
  Plus Jakarta Sans, display em Sora e mono em JetBrains Mono; Topbar/tabelas/pills
  herdam a fonte, mas não receberam regras específicas na F1.
- B1 planejamento concluiu que staging deve ser um projeto Supabase dedicado,
  porque roles/grants nativos (`authenticated`, `anon`, `service_role`) e
  privilégios do schema `public` vêm do Supabase, não das migrations.
- B1-IMPL abriu o PR #40 (`chore/staging-b1-artefatos`, commit `7293827`) com
  templates `.env.staging.example`, runner de migrations, guia `deploy/STAGING.md`
  e proteção `.env.staging` no `.gitignore`. Não aplicou migrations nem tocou
  banco/produção.
- PR #40 foi revisado por 6 gates e mesclado na `main`, merge commit `9726e06`.
  `origin/main` agora contém os artefatos versionáveis do B1. Próximo B1 passa
  a ser manual: criar Supabase staging, bucket, Clerk dev, usuário de teste,
  aplicar migrations no staging e validar gates de isolamento.
- B2 planejamento concluído em modo read-only. Achado central: egress externo
  passa por clientes em `backend/app/services/*`, então o guard deve ficar na
  camada de serviço. Métodos bloqueáveis fora de produção: Evolution
  `send_text`/`send_media`/`set_webhook`, Asaas `create_checkout`, Brevo
  `send_invite`/`send_password_reset`, LLM `complete`, Google Calendar
  `create_event`/`delete_event`. Próximo: B2-IMPL em branch nova.
- B2-IMPL entregue em PR draft #41 (`feat/b2-guard-envios-naoprod`, commit
  `91736bd`). Implementou 11 métodos guardados: 9 críticos do prompt + 3 cinza
  Evolution (`connect`/`reconnect`/`disconnect`). Clerk `create_user` e LLM
  `validate_credential` ficaram fora por serem auth/infra. Testes reportados:
  531 passed, sem segredo no diff, sem banco/serviço externo tocado.
- Revisão independente do PR #41 corrigiu a contagem real para 12 métodos
  guardados e concluiu `APTO PARA SAIR DE DRAFT`. Riscos restantes são
  não-bloqueadores: descrição do PR com contagem 11, `create_event` levanta
  erro em sandbox mas caller atual trata, `create_checkout` retorna URL nula em
  sandbox.
- PR #41 saiu de draft sem novos commits; segue OPEN, ready, head `91736bd`,
  MERGEABLE/CLEAN.
- PR #41 mesclado na `main` por merge commit `7cd30bb`. B2 agora está presente
  na `origin/main`: guard não-prod em 12 métodos, docs/env atualizados, testes
  incluídos. Banco e serviços externos não foram tocados; F2/F3/F4 não foram
  iniciadas.
- Registro pós-merge B1/B2 concluído pelo PR docs #42, merge commit `ab4ea2a`.
  Houve incidente corrigido: primeiro commit docs caiu no repo principal/main
  stale, foi refeito em branch docs correta e o repo principal foi restaurado
  preservando mudanças locais do usuário. Nada foi pushado no erro; `origin/main`
  só avançou pelo PR #42 legítimo.
- B1 manual concluído: staging Supabase/Clerk isolado criado, 24/24 migrations
  aplicadas, seed validado, login funcional, RLS efetiva em `/contacts`, externos
  sem credencial e guard `[SANDBOX]` ativo com `ALLOW_REAL_SENDS=false`. F2/F3
  estão liberadas do ponto de vista de ambiente.
- Registro operacional B1 manual feito no PR docs #43, atualizando
  `docs/sprints/2026-06-25-ambientes-b1-b2-staging-guard.md`. F2/F3 agora estão
  formalmente liberadas no histórico do repositório.
- F2 navegação/shell desktop foi mesclada pelo PR #44 e registrada pelo PR docs
  #45; `origin/main` avançou para `7907760`.
- F3 mobile-first foi mesclada pelo PR #46 e registrada pelo PR docs #47;
  `origin/main` avançou para `86c06dc2f54af9ad344166bb0ff56c7188946866`.
- F4 foi investigada em modo read-only; decisões D1–D5 já estão definidas para
  o prompt de implementação.
- F4 implementação/polish/PWA ainda não foi iniciada.

### Dívidas explícitas para F1/F4

- `--warn` em texto sobre branco foi ajustado na F1 para ~5,0:1, mas ainda
  precisa de revisão independente e merge.
- `--accent` / `--accent-fg` em CTA primário foi apontado pelo bot Codex como
  cerca de 3,65:1 para texto de 13,5px. Não bloqueou F0, mas deve entrar na F1
  ou F4 como ajuste de contraste antes de ampliar uso do token. Na F1, o par foi
  ajustado para ~4,67:1 no CTA e ~4,79:1 como texto sobre branco; pendente de
  revisão independente.

## Padrão permanente para prompts do Claude Code

Documentação oficial revisada em 24/06/2026:

- [Best practices](https://code.claude.com/docs/en/best-practices)
- [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works)
- [Worktrees](https://code.claude.com/docs/en/worktrees)
- [Subagents](https://code.claude.com/docs/en/sub-agents)
- [Agent teams](https://code.claude.com/docs/en/agent-teams)
- [Hooks](https://code.claude.com/docs/en/hooks)

Todos os próximos prompts preparados para este projeto devem seguir estas
regras:

1. **Uma missão por prompt.** Informar o resultado esperado e o gate que libera
   a próxima fase.
2. **Investigar antes de implementar.** Em mudanças grandes, incertas ou que
   atingem vários arquivos, começar em modo de planejamento e somente leitura.
   Correções pequenas e óbvias podem ser executadas diretamente.
3. **Fornecer contexto específico.** Citar fontes de verdade, arquivos,
   sintomas, restrições e padrões já existentes. Usar referências `@arquivo`
   no Claude Code quando possível.
4. **Definir limites.** Separar claramente escopo permitido e fora de escopo.
   Não autorizar funções futuras apenas porque aparecem no protótipo.
5. **Delegar o objetivo, não cada movimento.** Explicar o problema, o resultado
   e as restrições; deixar o Claude descobrir os comandos e detalhes internos,
   salvo quando houver uma regra de segurança ou projeto que exija algo exato.
6. **Dar uma forma objetiva de verificação.** Todo prompt de implementação deve
   exigir os testes adequados, `typecheck`, lint, build e/ou comparação visual.
   O Claude deve corrigir falhas dentro do escopo antes de encerrar.
7. **Exigir evidências.** O relatório final deve mostrar comandos executados,
   resultados, arquivos modificados e capturas quando houver mudança visual.
8. **Controlar o paralelismo.** Subagentes são apropriados para investigação ou
   revisão focada. Times de agentes só devem ser usados quando as frentes forem
   realmente independentes. Qualquer edição paralela exige arquivos separados
   e worktrees isolados.
9. **Preservar o contexto.** Usar `/clear` entre tarefas sem relação. Depois de
   duas tentativas de correção malsucedidas, iniciar contexto limpo com um prompt
   melhor que incorpore o aprendizado, em vez de acumular remendos na conversa.
10. **Manter instruções permanentes enxutas.** `CLAUDE.md` deve conter apenas
    comandos, arquitetura, regras e armadilhas que se aplicam amplamente. Fluxos
    ocasionais pertencem a skills ou aos prompts, não ao contexto de toda sessão.
11. **Usar hooks para regras determinísticas.** Checagens repetíveis e de
    segurança devem virar hooks; instruções que exigem julgamento permanecem no
    prompt.
12. **Não aceitar sucesso declarado.** Uma etapa só termina quando o gate passa
    e o relatório traz prova verificável.

### Estrutura que usaremos nos próximos prompts

```text
TÍTULO E TIPO DA TAREFA
[ANÁLISE | IMPLEMENTAÇÃO | REVISÃO]

MISSÃO
Descreva em uma frase o resultado concreto desta execução.

RESULTADO ESPERADO
- Liste os resultados observáveis que devem existir ao final.

FONTES DE VERDADE E CONTEXTO
- Indique documentos, arquivos, protótipo, branch e decisões anteriores.
- Peça ao Claude para ler essas fontes antes de decidir.

COORDENAÇÃO E ISOLAMENTO
- Identifique branch e worktree responsáveis.
- Rode o inventário das outras frentes antes de editar.
- Não toque em mudanças de outra conversa.

ESCOPO PERMITIDO
- Liste o que pode ser investigado ou alterado.

FORA DE ESCOPO
- Liste explicitamente o que não pode ser alterado ou implementado.

MODO DE EXECUÇÃO
1. Investigue em modo somente leitura quando a tarefa for ampla ou incerta.
2. Apresente ou valide o plano antes da primeira escrita quando houver risco.
3. Implemente com autonomia dentro do escopo aprovado.
4. Execute as verificações e corrija as falhas relacionadas à mudança.

VERIFICAÇÃO OBRIGATÓRIA
- Informe comandos/testes exatos ou critérios visuais verificáveis.
- Exija evidências, não apenas a afirmação de que passou.

GATE DE CONCLUSÃO
- Defina as condições objetivas para encerrar e avançar.
- Se alguma condição falhar, não faça commit, push ou PR.

RELATÓRIO FINAL
- branch, worktree e HEAD;
- resumo do que foi encontrado e decidido;
- arquivos alterados e diff --stat;
- verificações executadas e resultados;
- capturas/comparação visual, se aplicável;
- riscos, pendências e recomendação explícita: AVANÇAR ou NÃO AVANÇAR.
```

### Como escolher o tipo de prompt

- **Análise:** somente leitura; serve para descobrir estado, impacto e opções.
- **Implementação:** escrita autorizada dentro de escopo estreito, seguida por
  verificação e relatório.
- **Revisão:** contexto novo e preferencialmente outro agente/sessão tenta
  encontrar falhas, regressões ou diferenças contra o contrato aprovado.

Os prompts abaixo continuam como o plano de execução. Antes de cada envio, sua
versão final deve ser adaptada a este padrão e ao estado mais recente relatado
pelo Claude Code.

---

# PROMPT 0 — CONCLUÍDO

## Estabilizar Git e CodeGraph sem perder trabalho

```text
Antes de continuar o redesign, estabilize o Git e o CodeGraph. Não implemente
novas alterações visuais nesta etapa.

CONTEXTO
- Repositório principal:
  C:\Users\hanie\Searches\OneDrive\Documentos\workspace\PastorAi-1.0
- Worktree do redesign:
  C:\Users\hanie\Searches\OneDrive\Documentos\workspace\PastorAi-1.0\.claude\worktrees\hardcore-sammet-e68aa1
- Branch esperada do redesign: feat/redesign-f0-tokens

REGRAS DE SEGURANÇA
- Não usar git reset --hard, git clean, checkout destrutivo ou apagar arquivos.
- Não descartar nenhuma mudança da main ou do worktree.
- Não copiar arquivos entre o worktree e o repositório principal.
- Não exibir nem commitar conteúdo de .env.local.
- Não iniciar F1.

1. INVENTÁRIO DO GIT
- Mostre branch, HEAD, status e diff --stat do repositório principal.
- Mostre branch, HEAD, status e diff --stat do worktree do redesign.
- Compare ambos com origin/main após um git fetch sem alterar os arquivos.
- Classifique as mudanças do repositório principal em:
  a) preview copiado temporariamente;
  b) deploy/infraestrutura;
  c) configuração local de ferramentas;
  d) desconhecida.
- Não mova nem descarte nada. Apenas apresente o inventário e preserve tudo.

2. CORRIGIR O HOOK DO CODEGRAPH
- Leia .mcp.json, .claude/settings.json, CLAUDE.md e AGENTS.md.
- O hook atual aponta para um caminho absoluto do repositório principal.
- Ajuste somente a configuração local necessária para que o hook descubra o
  worktree corrente com `git rev-parse --show-toplevel` e atualize esse caminho.
- Não versione configurações locais sem explicar exatamente por quê.
- Preserve o servidor MCP `code-review-graph` habilitado.

3. RECONSTRUIR O GRAFO CERTO
- No worktree do redesign, execute um rebuild completo do CodeGraph.
- Depois execute `code-review-graph status` para o worktree.
- O status final deve apontar para `feat/redesign-f0-tokens` e para o HEAD atual.
- Confirme contagem de arquivos, nós, arestas, branch, commit e horário.
- Confirme que as ferramentas MCP `get_architecture_overview`,
  `detect_changes`, `get_impact_radius`, `query_graph` e
  `semantic_search_nodes` estão disponíveis na sessão.
- Use `detect_changes` para analisar o diff atual da F0.
- Use `get_affected_flows` ou `get_impact_radius` para confirmar que a F0 afeta
  apenas apresentação/identidade e não contratos de API ou regras pastorais.

4. GRAPHIFY
- Não rode Graphify.
- Não apague instalações, históricos ou documentos antigos do Graphify.
- Considere Graphify opcional e fora do fluxo diário deste redesign.

5. RELATÓRIO
Entregue:
- estado do Git nas duas pastas;
- mudanças locais encontradas na main e sua classificação;
- configuração do hook antes/depois;
- status antigo e novo do CodeGraph;
- análise de impacto da F0 pelo CodeGraph;
- qualquer bloqueio real.

Pare ao final. Não continue para a validação visual da F0 até o usuário revisar
este relatório.
```

## Gate para avançar

- [x] Nenhuma mudança foi perdida.
- [x] Mudanças locais da `main` foram identificadas e preservadas.
- [x] Correção permanente do hook usa o worktree atual, não caminho fixo.
- [x] CodeGraph mostra a branch correta.
- [x] CodeGraph analisou o diff da F0.

---

# PROMPT 1 — CONCLUÍDO COM EVIDÊNCIA PARCIAL A REVISAR

## Validar e fechar a F0

```text
Valide e prepare o fechamento da F0 no próprio worktree
`feat/redesign-f0-tokens`.

REGRAS
- Use CodeGraph antes de Grep/Read para entender impacto e cobertura.
- Faça o inventário de coordenação entre worktrees/branches antes de editar e
  repita-o antes de qualquer commit, rebase, push ou PR.
- Não copie globals.css nem qualquer arquivo para o repositório principal.
- Não alterar APIs, banco, autenticação, RBAC, RLS ou regras pastorais.
- Não iniciar F1.
- Não fazer push, PR, merge ou deploy ainda.

1. PREVIEW CORRETO
- Identifique com segurança o processo que ocupa a porta 3000.
- Se for o Next do repositório principal, pare somente esse processo após
  confirmar sua linha de comando.
- Inicie o frontend do worktree na porta 3000.
- Confirme que .env.local está ignorado e não mostre seu conteúdo.

2. LOGIN E RECUPERAÇÃO
- Teste login e recuperação de senha.
- Se falhar, inspecione URL, status HTTP, resposta, NEXT_PUBLIC_API_URL efetiva,
  CORS, backend e origem do Clerk.
- Não atribua a falha ao Clerk sem evidência.
- Não mude o código de autenticação apenas para facilitar o preview.

3. VERIFICAÇÕES
- npm run typecheck
- npm run lint
- npm run build
- git diff --check
- CodeGraph detect_changes
- CodeGraph get_affected_flows ou get_impact_radius

4. REVISÃO VISUAL
- Login, dashboard, sidebar, pessoas, comunicação, conversas, tabelas e modais.
- Desktop e mobile.
- Contraste, foco, hover, item ativo e overlays.
- Confirmar que status semântico não foi confundido com cor de estágio G12.

5. CONTRATO
- Reconciliar a inconsistência: as cores dos estágios foram alteradas na F0,
  mas o contrato também as lista na F1.
- Manter os valores dos estágios como tokens da F0 e registrar que a F1 apenas
  aplica a identidade nos componentes.

6. ESCOPO DO FUTURO COMMIT
Pode entrar:
- frontend/src/app/globals.css
- frontend/package.json
- frontend/src/components/config/AgenteScreen.tsx
- docs/design/RECONCILIACAO-igreja12.md
- docs/design/Igreja12-Prototipo.standalone.html

Não pode entrar:
- .env.local
- node_modules
- docs/design/_work
- plano-redesign-igreja12.html
- roadmap-proximas-fases.html
- arquivos temporários, backups, screenshots ou logs

Entregue relatório, diff --stat, resultados dos comandos e checklist visual.
Pare sem commitar até o usuário aprovar visualmente.
```

## Gate para avançar

- [ ] Login e recuperação possuem evidência independente registrada. Observação:
  a revisão do PR #35 trouxe evidência direta de login, mas não demonstrou
  recuperação de senha de ponta a ponta.
- [x] Preview confirmado no worktree da F0, não na `main`.
- [x] Typecheck, lint e build passaram.
- [ ] Revisão independente percorreu todas as superfícies previstas.
- [x] Escopo do commit está limpo.

---

# PROMPT 2 — CONCLUÍDO

## Commitar, atualizar com a main e abrir PR da F0

```text
Feche a F0 aprovada.

- Confirme novamente que nenhum segredo ou arquivo temporário será commitado.
- Faça dois commits:
  1. docs(design): registra contrato e protótipo congelado Igreja 12
  2. feat(design): aplica fundação de tokens da F0
- Execute git fetch origin.
- Rebaseie a branch feat/redesign-f0-tokens sobre origin/main.
- Não use rebase na main e não force alterações de terceiros.
- Resolva conflitos preservando tanto as mudanças recentes da main quanto a F0.
- Reconstrua/atualize o CodeGraph depois do rebase.
- Rode novamente typecheck, lint, build e revisão visual rápida.
- Mostre o diff final contra origin/main.
- Faça push da branch e abra PR inicialmente como draft.
- Não faça merge nem deploy.
- Entregue hashes dos commits, URL do PR, testes e riscos restantes.
```

## Gate para avançar

- [x] F0 está baseada na `origin/main` usada no rebase (`95553d2`).
- [x] PR pequeno, revisável e sem arquivos locais.
- [x] Testes passaram depois do rebase.
- [ ] PR aprovado e mesclado antes de criar F1.

---

# PROMPT 2.5 — CONCLUÍDO: APTO PARA SAIR DE DRAFT

## Revisão independente do PR draft #35

```text
[REVISÃO — SOMENTE LEITURA]

MISSÃO
Faça uma revisão independente do PR #35 — “F0 — fundação de tokens Igreja 12”
e decida, com evidências, se ele está apto para sair de draft. Não implemente
correções nesta execução.

PR
https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/35

RESULTADO ESPERADO
- Confirmar ou refutar que a F0 contém apenas rebrand e fundação visual.
- Verificar os cinco arquivos do PR e os dois commits separadamente.
- Reexecutar os gates técnicos depois do rebase.
- Validar visualmente as superfícies afetadas em desktop e mobile.
- Entregar recomendação final: APTO PARA SAIR DE DRAFT ou NÃO APTO.

FONTES DE VERDADE
- PR #35 e seu diff contra a origin/main atual.
- docs/design/RECONCILIACAO-igreja12.md
- docs/design/Igreja12-Prototipo.standalone.html
- CLAUDE.md do projeto.
- Código atual da main, especialmente a versão nova de AgenteScreen.tsx.

INDEPENDÊNCIA E COORDENAÇÃO
- Trabalhe em uma conversa nova, como revisor, sem confiar nas conclusões da
  conversa que implementou a F0.
- Use um checkout/worktree isolado do PR #35 ou faça inspeção estritamente
  somente leitura no worktree existente.
- Antes de começar, informe cwd, branch, HEAD, worktree, git status e estado
  atual do PR.
- Não edite arquivos, não faça commit, não envie push, não mude o PR para ready,
  não aprove, não mescle e não faça deploy.
- Não faça reset, clean, stash ou descarte de mudanças de nenhuma conversa.

ESCOPO ESPERADO DO PR
- docs/design/Igreja12-Prototipo.standalone.html
- docs/design/RECONCILIACAO-igreja12.md
- frontend/package.json
- frontend/src/app/globals.css
- frontend/src/components/config/AgenteScreen.tsx

REVISÃO DO DIFF
1. Confirme que não há segredo, .env, _work, plano local, screenshot, backup,
   log ou arquivo fora da lista permitida.
2. Revise os commits 4b95d75 e 94a3afe e confirme a separação docs/feature.
3. Verifique se a resolução em AgenteScreen preserva o fluxo novo da main
   (“requisição ao master”) e altera somente PastorAI para Igreja 12.
4. Confirme que não houve mudança de API, autenticação, RBAC, RLS, banco,
   navegação, screenId ou regra pastoral.
5. Compare globals.css com o contrato e procure tokens ausentes, colisões
   semânticas, regressões de contraste e seletores afetados acidentalmente.
6. Classifique achados como:
   - BLOQUEADOR DA F0;
   - DÍVIDA JÁ PREVISTA PARA F1/F3/F4;
   - OBSERVAÇÃO NÃO BLOQUEANTE.

CODEGRAPH
- Confirme que o grafo usado pertence ao checkout e HEAD revisados; reconstrua
  somente se estiver desatualizado.
- Execute detect_changes e get_affected_flows ou get_impact_radius.
- Confirme que o impacto encontrado é de apresentação/identidade.
- Verifique se o hook deixou de depender do caminho fixo do repositório
  principal; apenas relate se a correção permanente ainda estiver pendente.

GATES TÉCNICOS
- npm run typecheck
- npm run lint
- npm run build com ambiente de build limpo
- git diff --check
- Confirme mergeabilidade e estado dos checks do PR pelo GitHub.
- Não altere código para fazer os gates passarem; se falhar, registre a causa.

VERIFICAÇÃO VISUAL
- Use configuração local já ignorada pelo Git sem exibir segredos.
- Confirme que o preview executado pertence ao checkout do PR.
- Verifique login e recuperação de senha sem modificar autenticação.
- Percorra dashboard, sidebar, Pessoas, Comunicação, Conversas, tabelas, modais
  e Agente IA.
- Teste desktop e mobile.
- Observe contraste, foco, hover, item ativo, overlays e legibilidade dos status.
- Confirme especificamente em Agente IA o texto Igreja 12 junto do fluxo
  “Solicitar mudança ao master”.
- Registre capturas ou evidências objetivas das superfícies verificadas.

FORA DE ESCOPO
- Não corrigir --warn, densidade mobile ou colisões estágio/status nesta revisão;
  apenas decidir se são dívidas previstas ou regressões bloqueantes.
- Não iniciar F1, F2, F3 ou F4.
- Não registrar sprint nem atualizar memória nesta execução.
- Não parar serviços que não pertençam ao preview criado pelo revisor.

RELATÓRIO FINAL
- cwd, branch, HEAD e worktree revisados;
- estado do PR, mergeabilidade e checks;
- arquivos e commits conferidos;
- achados por severidade com arquivo/linha e evidência;
- resultados completos dos gates técnicos;
- checklist visual com desktop/mobile;
- situação da correção permanente do hook do CodeGraph;
- riscos restantes;
- conclusão única: APTO PARA SAIR DE DRAFT ou NÃO APTO.

Pare após o relatório. Não altere o PR nem implemente correções.
```

## Gate para avançar

- [x] Revisor independente não encontrou bloqueador.
- [x] Todos os gates técnicos passaram no checkout revisado.
- [ ] Login, recuperação e superfícies visuais têm evidência registrada.
  Evidência atual: login e admin foram verificados diretamente; telas internas
  foram verificadas por CSS/JS compilado; recuperação de senha não apareceu
  comprovada no relatório.
- [x] Hook do CodeGraph foi confirmado ou virou pendência explícita separada.
- [x] Recomendação final: `APTO PARA SAIR DE DRAFT`.

---

# PROMPT 2.6 — CONCLUÍDO: PRONTO PARA REVIEW

## Tirar o PR #35 de draft sem alterar código

```text
[OPERAÇÃO GITHUB — SEM ALTERAÇÃO DE CÓDIGO]

MISSÃO
Converter o PR #35 da F0 de draft para ready for review, sem adicionar commits,
sem alterar código e sem iniciar F1.

CONTEXTO
- PR: https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/35
- Branch: feat/redesign-f0-tokens
- HEAD revisado e aprovado: 94a3afe
- Revisor independente concluiu: APTO PARA SAIR DE DRAFT.
- Limitação registrada: telas internas autenticadas foram verificadas
  programaticamente; recuperação de senha não teve evidência direta no relatório.
  Isso não bloqueia sair de draft porque a F0 não altera autenticação nem regras
  funcionais.

REGRAS
- Não edite arquivos.
- Não faça commit.
- Não faça push de novos commits.
- Não faça merge.
- Não inicie F1.
- Não registre sprint ainda.
- Não descarte mudanças de nenhuma conversa.

PASSOS
1. Confirme cwd, branch, worktree, git status e HEAD.
2. Confirme no GitHub que o PR #35 ainda está aberto, draft, mergeable, sem
   novos commits além de 94a3afe e com base em main.
3. Se o HEAD do PR não for 94a3afe, pare e reporte NÃO AVANÇAR.
4. Se estiver tudo igual ao revisado, execute somente a ação de GitHub para
   marcar o PR como ready for review.
5. Depois confirme o estado final do PR.

RELATÓRIO FINAL
- cwd, branch, worktree e HEAD;
- estado do PR antes e depois;
- confirmação de que nenhum arquivo foi alterado;
- confirmação de que nenhum commit novo foi criado;
- conclusão: PR #35 PRONTO PARA REVIEW ou NÃO AVANÇAR.
```

## Gate para avançar

- [x] PR #35 não é mais draft.
- [x] Nenhum commit novo foi criado.
- [x] PR continua mergeable.
- [x] F1 ainda não foi iniciada.

---

# PROMPT 2.7 — CONCLUÍDO: F0 MESCLADA

## Fechar e mesclar a F0 sem iniciar F1

```text
[OPERAÇÃO GITHUB — FECHAMENTO DA F0]

MISSÃO
Fazer a checagem final do PR #35 e mesclar a F0 na main somente se o estado
continuar exatamente compatível com o que foi revisado. Não iniciar F1 nesta
execução.

CONTEXTO
- PR: https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/35
- Branch do PR: feat/redesign-f0-tokens
- HEAD aprovado: 94a3afe
- Estado esperado antes do merge: OPEN, isDraft false, MERGEABLE/CLEAN, 2
  commits, base main, sem commits novos.
- Revisão independente: APTO PARA SAIR DE DRAFT.
- Operação anterior: PR #35 saiu de draft sem alterar código.

REGRAS
- Não edite arquivos.
- Não faça commit.
- Não faça push de novos commits.
- Não inicie F1.
- Não registre sprint ainda.
- Não faça deploy.
- Não descarte mudanças de nenhuma conversa.
- Se houver commit novo, conflito, check vermelho, review bloqueante ou estado
  diferente do esperado, pare e reporte NÃO MESCLAR.

PASSOS
1. Confirme cwd, branch, worktree e git status.
2. Consulte o PR #35 no GitHub e confirme:
   - OPEN;
   - isDraft false;
   - MERGEABLE/CLEAN;
   - headRefOid começa com 94a3afe;
   - exatamente 2 commits;
   - baseRefName main;
   - status checks sem falha;
   - sem review com REQUEST_CHANGES ou comentário bloqueante aberto.
3. Se qualquer item acima falhar, não faça merge.
4. Se tudo estiver correto, mescle o PR #35 usando a estratégia padrão segura do
   repositório. Preserve a rastreabilidade do PR no histórico/mensagem de merge.
5. Depois do merge, confirme:
   - PR fechado/merged;
   - commit de merge ou squash gerado;
   - main remota contém a F0;
   - nenhum arquivo local foi alterado.

RELATÓRIO FINAL
- cwd, branch, worktree e git status;
- estado do PR antes do merge;
- estratégia de merge usada;
- estado do PR depois do merge;
- SHA final na main;
- confirmação de que F1 não foi iniciada;
- conclusão: F0 MESCLADA ou NÃO MESCLAR.
```

## Gate para avançar

- [x] PR #35 foi mesclado.
- [x] `origin/main` contém a F0.
- [x] Nenhum commit extra foi criado na branch da F0 antes do merge.
- [x] F1 ainda não foi iniciada.

---

# PROMPT 2.8 — CONCLUÍDO: REGISTRO LOCAL CRIADO

## Registrar pós-merge da F0 e preparar main para F1

```text
[DOCUMENTAÇÃO E COORDENAÇÃO — PÓS-MERGE F0]

MISSÃO
Registrar a F0 mesclada, sincronizar a main/CodeGraph e deixar o terreno pronto
para criar a branch da F1. Não implemente design nem altere código de produto
nesta execução.

CONTEXTO
- PR #35 foi mesclado em 2026-06-25.
- Merge commit na main: 7b57d3e.
- Commits da F0:
  - 4b95d75 — docs(design): registra contrato e protótipo congelado Igreja 12
  - 94a3afe — feat(design): aplica fundação de tokens da F0
- A F0 alterou apenas:
  - docs/design/Igreja12-Prototipo.standalone.html
  - docs/design/RECONCILIACAO-igreja12.md
  - frontend/package.json
  - frontend/src/app/globals.css
  - frontend/src/components/config/AgenteScreen.tsx
- Dívida pós-review a registrar:
  - `--accent` / `--accent-fg` em CTA primário ficou em torno de 3,65:1 para
    texto de 13,5px, abaixo de AA 4,5:1. Não bloqueou F0, mas deve ser corrigido
    na F1/F4 junto de `--warn` e demais dívidas de contraste.

REGRAS
- Não alterar código de produto.
- Não iniciar F1.
- Não fazer deploy.
- Não apagar branch, worktree, `_work`, arquivos locais ou mudanças de outra
  conversa.
- Não alterar o PR #35.
- Não mexer em autenticação, RBAC, RLS, banco, API, navegação ou regras
  pastorais.

PASSOS
1. Confirme o estado atual:
   - cwd, branch, worktree e git status;
   - `origin/main` aponta para `7b57d3e`;
   - PR #35 está `MERGED`.
2. Atualize/sincronize a main local de forma segura em um worktree apropriado.
   Se o worktree atual não for a main ou tiver mudanças de outra conversa, não
   force nada; crie ou use um worktree limpo para documentação.
3. Atualize/reconstrua o CodeGraph para a `main` em `7b57d3e` e confirme branch,
   commit, horário, arquivos e nós.
4. Crie um registro de sprint em `docs/sprints/` seguindo o padrão do
   `docs/sprints/README.md`, por exemplo:
   `docs/sprints/2026-06-25-redesign-f0-fundacao-tokens.md`.
5. O registro deve conter:
   - branch/PR/merge commit;
   - arquivos alterados;
   - decisões tomadas;
   - gates executados;
   - dívidas pendentes para F1/F3/F4;
   - destaque explícito para contraste `--accent`/`--accent-fg` e `--warn`;
   - próximo passo: F1 em branch nova a partir da `origin/main`.
6. Se necessário, crie uma branch docs pequena para esse registro. Não misture
   com F1.

VERIFICAÇÃO
- `git diff --check`
- Confirmar que somente documentação de sprint foi alterada.
- Confirmar que nenhum código de produto foi alterado.
- Confirmar que F1 ainda não foi iniciada.

RELATÓRIO FINAL
- cwd, branch, worktree e HEAD;
- estado do PR #35 e da `origin/main`;
- status do CodeGraph na main;
- arquivo de sprint criado;
- diff --stat;
- verificação executada;
- confirmação de que nenhum código de produto foi alterado;
- recomendação: AVANÇAR PARA F1 ou NÃO AVANÇAR.
```

## Gate para avançar

- [x] Registro da F0 criado em `docs/sprints`.
- [x] CodeGraph atualizado para `origin/main` em `7b57d3e` ou commit posterior.
- [x] Dívida `--accent`/`--accent-fg` registrada para F1/F4.
- [x] Nenhum código de produto foi alterado.
- [x] Recomendação final: `AVANÇAR PARA F1`.
- [ ] O commit docs `3a7374c` ainda precisa ser enviado ao remoto e mesclado
  para o registro ficar versionado na `main`.

---

# PROMPT 2.9 — CONCLUÍDO: REGISTRO VERSIONADO

## Publicar o registro docs da F0 sem alterar código

```text
[OPERAÇÃO GITHUB — DOCUMENTAÇÃO PÓS-MERGE F0]

MISSÃO
Publicar e mesclar o registro de sprint da F0 que já foi criado localmente,
sem alterar código de produto e sem iniciar F1.

CONTEXTO
- PR #35 da F0 já foi mesclado na main.
- Merge commit da F0: 7b57d3e.
- Registro docs criado localmente:
  - branch: docs/sprint-f0-fundacao-tokens
  - commit: 3a7374c
  - arquivo: docs/sprints/2026-06-25-redesign-f0-fundacao-tokens.md
- O commit contém somente documentação de sprint.
- O worktree da main possui mudanças de outra conversa; não toque nele.

REGRAS
- Não alterar código de produto.
- Não iniciar F1.
- Não fazer deploy.
- Não apagar branch, worktree ou mudanças de outra conversa.
- Não mexer em autenticação, RBAC, RLS, banco, API, navegação ou regras
  pastorais.
- Se a branch `docs/sprint-f0-fundacao-tokens` tiver qualquer arquivo além de
  `docs/sprints/2026-06-25-redesign-f0-fundacao-tokens.md`, pare e reporte
  NÃO AVANÇAR.

PASSOS
1. Confirme cwd, worktree, branch, HEAD e git status.
2. Confirme que a branch `docs/sprint-f0-fundacao-tokens` contém somente o
   commit docs `3a7374c` sobre `origin/main`/`7b57d3e`.
3. Confirme que o diff contra `origin/main` altera somente:
   `docs/sprints/2026-06-25-redesign-f0-fundacao-tokens.md`.
4. Rode `git diff --check origin/main...HEAD`.
5. Faça push da branch docs.
6. Abra um PR pequeno de documentação para `main`, com título claro, por exemplo:
   `docs(sprints): registra F0 do redesign Igreja 12`.
7. Se o PR estiver limpo, mergeable e sem check vermelho, mescle-o usando a
   estratégia padrão do repositório.
8. Não delete worktrees nem branches locais pertencentes a outras conversas.

RELATÓRIO FINAL
- cwd, worktree, branch e HEAD;
- diff --stat;
- PR docs criado;
- estratégia de merge usada;
- SHA final na `origin/main`;
- confirmação de que nenhum código de produto foi alterado;
- confirmação de que F1 ainda não foi iniciada;
- conclusão: REGISTRO VERSIONADO ou NÃO AVANÇAR.
```

## Gate para avançar

- [x] Registro da F0 está na `origin/main`.
- [x] PR docs pequeno foi mesclado.
- [x] Nenhum código de produto foi alterado.
- [x] F1 ainda não foi iniciada.
- [x] Conclusão final: `REGISTRO VERSIONADO`.

---

# PROMPT 3 — CONCLUÍDO: F1 IMPLEMENTADA EM PR DRAFT #37

## F1: identidade Igreja 12

```text
[IMPLEMENTAÇÃO — F1 IDENTIDADE VISUAL]

MISSÃO
Aplicar a identidade visual Igreja 12 nos componentes principais, partindo da
F0 já mesclada, sem alterar comportamento funcional, navegação, permissões,
APIs ou regras pastorais.

RESULTADO ESPERADO
- Branch nova da F1 criada a partir de `origin/main` no commit `67114b2` ou
  posterior.
- Identidade Igreja 12 aplicada em componentes reais: Login, shell, Sidebar,
  Topbar, dashboard/fila de trabalho, cards, botões, estados, foco e superfícies
  principais.
- Webfonts ou estratégia tipográfica local aplicada sem depender de download do
  Google durante o build.
- Contraste corrigido para `--accent`/`--accent-fg` e `--warn` em usos de texto.
- Gradientes, sombras, focus ring e estados ativos aplicados com parcimônia.
- PR pequeno e revisável, sem F2/F3/F4.

FONTES DE VERDADE
- `docs/design/Igreja12-Prototipo.standalone.html`
- `docs/design/RECONCILIACAO-igreja12.md`
- `docs/sprints/2026-06-25-redesign-f0-fundacao-tokens.md`
- `frontend/src/app/globals.css`
- `frontend/src/app/layout.tsx`
- `frontend/src/components/login/LoginScreen.tsx`
- `frontend/src/components/shell/AppShell.tsx`
- `frontend/src/components/shell/Sidebar.tsx`
- `frontend/src/components/shell/Topbar.tsx`
- `frontend/src/components/dashboard/DashboardScreen.tsx`
- `frontend/src/components/dashboard/StatCard.tsx`
- `frontend/src/components/dashboard/WorkQueueItem.tsx`
- `frontend/src/components/ui/Button.tsx`
- `frontend/src/components/ui/DataTable.tsx`

COORDENAÇÃO E ISOLAMENTO
- Antes de editar, execute `git fetch origin`, `git worktree list --porcelain`,
  `git branch -vv` e consulte PRs abertos.
- Não toque no worktree da `main` se ele tiver mudanças de outra conversa.
- Crie uma branch nova para a F1, por exemplo:
  `feat/redesign-f1-identidade`.
- Se essa branch já existir ou houver worktree com missão F1 em andamento, pare
  e peça definição de dono antes de editar.
- Não apagar, mover, fazer stash ou descartar mudanças de outra conversa.
- Repita a checagem de concorrência antes de commit, push ou PR.

ESCOPO PERMITIDO
- CSS/tokens e aplicação visual em componentes do frontend.
- Tipografia local/self-hosted:
  - preferir `next/font/local` se houver arquivos de fonte disponíveis;
  - se não houver arquivos locais, usar estratégia determinística que fique no
    repositório ou em dependência npm versionada, sem chamadas externas no build;
  - não usar `next/font/google` se o build depender de internet.
- Ajustes de contraste dos tokens `--accent`/`--accent-fg` e `--warn`.
- Aplicação de `--grad-sidebar`, `--grad-brand`, `--shadow-primary`, `--ring` e
  tokens da F0 em componentes existentes.
- Pequenos ajustes de copy visual de marca se forem estritamente de
  apresentação e não mudarem fluxo.
- Documentação curta no relatório ou em docs/design apenas se necessário para
  registrar decisão visual/contraste.

FORA DE ESCOPO
- Não alterar backend, banco, migrations, API, RLS, RBAC, Clerk, middleware,
  billing ou integrações.
- Não mudar `screenId`, hashes, rotas, permissões, navegação funcional,
  `LOCKED_SCREENS`, `role_permissions` ou regras pastorais.
- Não implementar Universidade da Vida, Capacitação, financeiro, treinamentos,
  novas telas, novas rotas ou módulos futuros do protótipo.
- Não reorganizar navegação; isso é F2.
- Não refatorar mobile/tabelas densas; isso é F3.
- Não implementar PWA/polimento amplo; isso é F4.
- Não fazer deploy.
- Não mesclar o PR.

MODO DE EXECUÇÃO
1. Use CodeGraph antes de Grep/Read para mapear impacto em Login, shell,
   Sidebar, Topbar, dashboard, botões, cards e tabelas.
2. Faça uma análise curta antes da primeira escrita:
   - quais componentes serão tocados;
   - quais tokens serão aplicados;
   - estratégia de fontes;
   - estratégia de contraste.
3. Aplique a identidade com disciplina:
   - o produto é um centro de operações pastoral para Igreja 12/G12;
   - a tela principal continua sendo fila de trabalho e ação, não BI;
   - evite aparência genérica de template SaaS;
   - use uma assinatura visual contida, como sidebar petróleo com trilho/halo
     mint de item ativo e superfícies de prioridade pastoral.
4. Corrija contraste com medição objetiva:
   - `--accent`/`--accent-fg` deve alcançar pelo menos AA 4.5:1 em texto normal
     quando usado em CTA;
   - `--warn` em texto sobre fundo claro deve ser medido e ajustado ou ter par
     foreground próprio;
   - não confundir tokens semânticos de status com tokens de estágio G12.
5. Rode preview e revisão visual em desktop e mobile.
6. Corrija falhas dentro do escopo antes de encerrar.

VERIFICAÇÃO OBRIGATÓRIA
- `npm run typecheck`
- `npm run lint`
- `npm run build`
- `git diff --check`
- CodeGraph `detect_changes`
- CodeGraph `get_affected_flows` ou `get_impact_radius`
- Medição/documentação do contraste de `--accent`/`--accent-fg` e `--warn`.
- Verificação visual:
  - Login;
  - Dashboard/fila de trabalho;
  - Sidebar item ativo/inativo/hover;
  - Topbar;
  - Pessoas/Contatos;
  - Comunicação/Comunicados;
  - Conversas;
  - tabelas e modais principais;
  - desktop e mobile.

GATE DE CONCLUSÃO
- F1 altera somente apresentação/identidade.
- Build não depende de internet para baixar fonte.
- Contraste de CTA e warning está comprovado ou explicitamente bloqueado com
  causa técnica.
- Nenhuma navegação, permissão, API ou regra de negócio foi alterada.
- PR aberto como draft ou pronto para review conforme segurança do resultado.
- F2 não foi iniciada.

RELATÓRIO FINAL
- branch, worktree e HEAD;
- base usada da `origin/main`;
- arquivos alterados e diff --stat;
- componentes mapeados pelo CodeGraph;
- estratégia de fontes usada e por que não depende de internet no build;
- valores/medição de contraste antes/depois para `--accent`/`--accent-fg` e
  `--warn`;
- verificações executadas e resultados;
- checklist visual desktop/mobile;
- riscos e dívidas restantes;
- URL do PR, se aberto;
- recomendação explícita: AVANÇAR PARA REVISÃO DA F1 ou NÃO AVANÇAR.
```

## Gate para avançar

- [x] Identidade aplicada sem mudança funcional.
- [x] Build funciona sem depender da internet.
- [x] Contraste e foco acessível.
- [ ] F1 revisada e mesclada separadamente.

---

# PROMPT 3.5 — CONCLUÍDO: APTO PARA SAIR DE DRAFT

## Revisão independente do PR draft #37

```text
[REVISÃO — SOMENTE LEITURA]

MISSÃO
Faça uma revisão independente do PR draft #37 — F1 identidade Igreja 12 — e
decida, com evidências, se ele está apto para sair de draft. Não implemente
correções nesta execução.

PR
https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/37

CONTEXTO
- F0 já está mesclada na main pelo PR #35.
- Registro da F0 já está versionado na main pelo PR #36.
- F1 foi implementada na branch `feat/redesign-f1-identidade`, commit
  `0e42310`, base `origin/main` `67114b2`.
- PR #37 está aberto como draft, mergeable/clean, com 5 arquivos:
  - `frontend/package.json`
  - `frontend/package-lock.json`
  - `frontend/src/app/globals.css`
  - `frontend/src/app/layout.tsx`
  - `frontend/src/components/shell/Sidebar.tsx`
- O relatório da implementação mencionou um trecho estranho posterior sobre
  detectar dev servers e `.claude/launch.json`. Confirme explicitamente que esse
  fluxo não contaminou o PR.

RESULTADO ESPERADO
- Confirmar ou refutar que a F1 contém apenas apresentação/identidade.
- Validar dependências `@fontsource` e estratégia de build sem internet.
- Verificar contraste `--accent`/`--accent-fg`, `--warn` e acentos on-dark.
- Revisar visualmente login e telas internas autenticadas em desktop e mobile.
- Entregar recomendação final: APTO PARA SAIR DE DRAFT ou NÃO APTO.

INDEPENDÊNCIA E COORDENAÇÃO
- Trabalhe em conversa nova ou contexto limpo, como revisor, sem confiar nas
  conclusões da implementação.
- Use checkout/worktree isolado do PR #37 ou inspeção estritamente somente
  leitura.
- Antes de começar, informe cwd, branch, HEAD, worktree, git status e estado do
  PR.
- Não edite arquivos, não faça commit, não faça push, não tire de draft, não
  aprove, não mescle e não faça deploy.
- Não apague, mova, faça stash, reset, clean ou descarte mudanças de nenhuma
  conversa.

ESCOPO ESPERADO DO PR
- Somente os 5 arquivos listados acima.
- Mudanças permitidas:
  - instalação versionada de fontes `@fontsource`;
  - import das fontes em `layout.tsx`;
  - aplicação visual no CSS global;
  - selo/markup estritamente visual em `Sidebar.tsx`.

FORA DE ESCOPO
- Backend, banco, migrations, API, RLS, RBAC, Clerk, middleware, billing ou
  integrações.
- Navegação funcional, `screenId`, hashes, permissões, `LOCKED_SCREENS`,
  `role_permissions` ou regras pastorais.
- F2, F3, F4, PWA, novas rotas, novas telas ou módulos futuros do protótipo.
- `.claude/launch.json`, configs de preview, arquivos temporários, screenshots,
  logs, backups ou mudanças locais.

REVISÃO DO DIFF
1. Confirme que o PR altera exatamente os 5 arquivos esperados.
2. Confirme que não há `.claude/launch.json`, `.env`, screenshot, log, backup,
   `_work`, arquivo temporário ou configuração de dev server no PR.
3. Revise `package.json` e `package-lock.json`:
   - dependências adicionadas são apenas as fontes necessárias;
   - não há pacote estranho, script alterado ou mudança de runtime não
     relacionada à F1.
4. Revise `layout.tsx`:
   - não usa `next/font/google`;
   - fontes são importadas de modo compatível com build offline;
   - não altera metadata/estrutura funcional indevidamente.
5. Revise `globals.css`:
   - tokens de contraste foram ajustados conforme relatório;
   - gradientes, foco, mint ativo e tipografia foram aplicados sem quebrar
     semântica;
   - não houve colisão indevida entre token de status e token de estágio G12;
   - seletores globais não causam efeitos colaterais óbvios em modais, tabelas
     e estados.
6. Revise `Sidebar.tsx`:
   - o selo do dono é apenas visual;
   - não muda navegação, permissões, screenId ou lógica de domínio.

CODEGRAPH
- Confirme que o grafo pertence ao checkout/HEAD do PR #37.
- Execute `detect_changes`.
- Execute `get_affected_flows` ou `get_impact_radius`.
- Confirme que o impacto é apresentação/identidade e que não há fluxo de API,
  auth, RBAC/RLS ou regra pastoral afetado.

GATES TÉCNICOS
- `npm run typecheck`
- `npm run lint`
- `npm run build`
- `git diff --check`
- Confirme estado do PR no GitHub: draft, mergeable/clean, checks sem falha.
- Não corrija nada nesta revisão; se falhar, registre causa e recomende NÃO
  APTO.

VERIFICAÇÃO DE FONTES E BUILD OFFLINE
- Confirme que o build empacota as fontes localmente.
- Confirme que não existe chamada para Google Fonts no build.
- Confirme que `@fontsource` não introduz download em runtime.
- Registre evidência objetiva: arquivos `.woff2`, CSS compilado ou output do
  build.

VERIFICAÇÃO DE CONTRASTE
- Recalcule ou valide objetivamente:
  - CTA `--accent-fg` sobre `--accent` >= 4.5:1;
  - `--accent` como texto sobre branco >= 4.5:1;
  - `--warn` como texto sobre branco >= 4.5:1;
  - acentos on-dark/kicker/checks com legibilidade adequada.
- Se a medição divergir do relatório, classifique o achado.

VERIFICAÇÃO VISUAL
- Use configuração local ignorada pelo Git sem exibir segredos.
- Confirme que o preview executado pertence ao checkout do PR #37.
- Verifique pelo menos:
  - Login;
  - Dashboard/fila de trabalho;
  - Sidebar ativo/inativo/hover;
  - Topbar;
  - Pessoas/Contatos;
  - Comunicação/Comunicados;
  - Conversas;
  - tabelas;
  - modais principais;
  - desktop e mobile.
- Se o login Clerk bloquear telas internas, não invente evidência. Registre o
  bloqueio e, se possível, valide por sessão/local env já existente sem alterar
  auth.

CLASSIFICAÇÃO DOS ACHADOS
- BLOQUEADOR DA F1;
- DÍVIDA JÁ PREVISTA PARA F2/F3/F4;
- OBSERVAÇÃO NÃO BLOQUEANTE.

RELATÓRIO FINAL
- cwd, branch, HEAD e worktree revisados;
- estado do PR, mergeabilidade e checks;
- arquivos conferidos;
- resultados dos gates técnicos;
- evidência de build/fontes offline;
- evidência de contraste;
- checklist visual desktop/mobile;
- situação do trecho `.claude/launch.json`/dev servers;
- achados por severidade;
- conclusão única: APTO PARA SAIR DE DRAFT ou NÃO APTO.

Pare após o relatório. Não altere o PR.
```

## Gate para avançar

- [x] Revisão independente não encontrou bloqueador.
- [x] Todos os gates técnicos passaram no checkout revisado.
- [x] Fontes/build offline validados.
- [x] Contraste validado independentemente.
- [x] Telas internas autenticadas foram verificadas ou bloqueio foi registrado
  com precisão.
- [x] Não houve contaminação por `.claude/launch.json` ou dev-server config.
- [x] Recomendação final: `APTO PARA SAIR DE DRAFT`.

---

# PROMPT 3.6A — ENVIAR AGORA

## Desbloquear login local para smoke visual da F1

```text
[DESBLOQUEIO DE AMBIENTE LOCAL — SEM CÓDIGO DE PRODUTO — SEM SEGREDOS NO CHAT]

MISSÃO
Preparar o ambiente local para permitir o smoke visual autenticado da F1 no
Chrome visível. O diagnóstico anterior concluiu que a senha não é o problema:
o frontend local está sem `frontend/.env.local`, cai no default
`http://localhost:8000`, e não há backend rodando em `:8000`.

CONTEXTO
- PR #37: https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/37
- Branch: feat/redesign-f1-identidade
- HEAD técnico revisado: 0e42310
- Revisão 3.5: APTO PARA SAIR DE DRAFT.
- Bloqueio atual: login local falha por ambiente/configuração, não por senha.
- O objetivo é viabilizar o Prompt 3.6, sem sujar o PR #37.

REGRAS
- Não altere código de produto.
- Não altere arquivos versionados.
- Não faça commit.
- Não faça push.
- Não tire o PR de draft.
- Não faça merge.
- Não peça senha no chat.
- Não peça token de sessão, cookie, localStorage, header Authorization ou
  segredo.
- Não exiba valores de `.env`, apenas nomes de variáveis.
- Pode criar/ajustar somente arquivos locais gitignored necessários ao preview,
  como `frontend/.env.local`, desde que confirme antes que estão ignorados pelo
  Git.
- Não iniciar F2, F3 ou F4.

PASSOS
1. Confirme cwd, branch, HEAD, PR #37 e working tree.
2. Confirme que `frontend/.env.local` é gitignored antes de escrever qualquer
   coisa nele.
3. Identifique, sem exibir valores, quais variáveis são necessárias para o
   frontend local:
   - `NEXT_PUBLIC_API_URL`;
   - `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, se exigida pela tela/auth.
4. Descubra qual backend compatível deve ser usado para o smoke:
   - staging, se existir e aceitar `http://localhost:3000`;
   - produção, apenas se não houver staging e apenas para navegação read-only;
   - backend local, somente se já estiver configurado com a mesma base/usuários.
5. Se você já tiver acesso seguro às variáveis públicas necessárias no ambiente
   local ou configuração do projeto, escreva `frontend/.env.local` sem imprimir
   valores no terminal/chat.
6. Se faltar algum valor, pare e peça ao usuário apenas isto:
   “Cole os valores diretamente no arquivo `frontend/.env.local`, não no chat.
   Use estes nomes de variáveis: ... Depois responda: ENV PRONTO.”
7. Suba/reinicie o frontend local e valide:
   - qual tipo de backend está sendo usado: local, staging ou produção;
   - se `POST /auth/login` chega ao backend;
   - se CORS permite `http://localhost:3000`;
   - se a falha anterior de rede para `localhost:8000` desapareceu.
8. Não submeta senha pelo usuário. Abra o Chrome visível na tela de login e
   pare.
9. Se o ambiente estiver pronto, diga ao usuário que o Prompt 3.6 pode ser
   executado.

RELATÓRIO FINAL
- estado do PR #37;
- confirmação de que nenhum arquivo versionado foi alterado;
- confirmação de que `frontend/.env.local`, se criado/editado, é gitignored;
- nomes das variáveis usadas, sem valores;
- tipo de backend usado: local/staging/produção;
- status de conectividade do login:
  - backend alcançável;
  - CORS ok ou bloqueado;
  - erro de rede anterior resolvido ou ainda presente;
- conclusão:
  - `AMBIENTE PRONTO PARA PROMPT 3.6`; ou
  - `AINDA BLOQUEADO`, com causa objetiva.
```

## Gate para avançar

- [ ] `frontend/.env.local` criado/ajustado somente se gitignored.
- [ ] Nenhum arquivo versionado alterado.
- [ ] Backend compatível alcançável pelo frontend local.
- [ ] CORS/login local não falha mais por backend offline.
- [ ] Conclusão final: `AMBIENTE PRONTO PARA PROMPT 3.6`.

---

# PROMPT 3.6 — ENVIAR AGORA SE VOCÊ PUDER FAZER LOGIN NO CHROME

## Smoke visual autenticado da F1 via Chrome visível

```text
[REVISÃO VISUAL ASSISTIDA — CHROME VISÍVEL — SEM ALTERAÇÃO DE CÓDIGO]

MISSÃO
Validar visualmente as telas internas autenticadas do PR #37 usando o Chrome
visível/controlado pela extensão. O usuário fará login manualmente no navegador.
Não altere código, auth, dados ou configuração versionada.

CONTEXTO
- PR #37: https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/37
- Branch: feat/redesign-f1-identidade
- HEAD aprovado tecnicamente: 0e42310
- Revisão independente do Prompt 3.5 concluiu: APTO PARA SAIR DE DRAFT.
- Única lacuna: telas internas foram bloqueadas pelo Clerk e validadas por CSS
  compilado.
- O Claude não pode digitar senha nem pedir senha/token no chat. A sessão será
  criada exclusivamente pelo usuário no Chrome visível.

REGRAS
- Não peça senha no chat.
- Não peça token de sessão, cookie, localStorage, header, `.env` ou segredo.
- Não registre, copie, leia, capture nem exponha senha, token, sessão ou segredo.
- Não abra DevTools para ler storage/cookies/sessão.
- Não use `eval` para injetar token.
- O usuário digita as credenciais diretamente no Chrome visível.
- Não edite arquivos.
- Não faça commit.
- Não faça push.
- Não tire o PR de draft.
- Não faça merge.
- Não altere Clerk, auth, env, cookies ou localStorage para burlar login.
- Não crie `.claude/launch.json` versionado nem inclua config de dev server no
  PR.
- Não iniciar F2, F3 ou F4.

PASSOS
1. Confirme o estado atual do PR #37 no GitHub:
   - OPEN;
   - draft;
   - HEAD `0e42310` ou registre se mudou;
   - arquivos esperados;
   - mergeable/checks.
2. Confirme o checkout/preview correto do PR #37:
   - branch `feat/redesign-f1-identidade`;
   - HEAD `0e42310`;
   - CSS servido contém F1: fontes `@fontsource`, sidebar/gradiente/mint,
     `--accent` e `--warn` escurecidos.
3. Abra o preview no Chrome visível/controlado pela extensão e pare na tela de
   login.
4. Diga ao usuário:
   “Faça login diretamente no Chrome. Não envie senha, token ou print com
   credencial no chat. Quando chegar ao dashboard, responda apenas: LOGADO.”
5. Depois que o usuário responder `LOGADO`, continue a navegação. Não leia nem
   capture credenciais, tokens, cookies ou localStorage.
6. Checklist mínimo desktop:
   - Dashboard/fila de trabalho;
   - Sidebar ativo/inativo/hover;
   - Topbar;
   - Pessoas/Contatos;
   - Comunicação/Comunicados;
   - Conversas;
   - tabelas;
   - modais principais disponíveis;
   - selo visual `Dono`, se a conta tiver `user.isOwner`.
7. Checklist mínimo mobile/responsivo:
   - Dashboard;
   - Sidebar/menu ou navegação equivalente;
   - Pessoas/Contatos;
   - Conversas;
   - uma tabela/lista;
   - um modal.
8. Observe:
   - legibilidade;
   - contraste;
   - foco visível;
   - hover/ativo;
   - overlays/modais;
   - se a UI continua parecendo fila de trabalho pastoral, não BI genérico;
   - se nenhuma navegação/permissão foi alterada.
9. Se alguma tela mostrar dados sensíveis, descreva apenas a estrutura visual;
   não transcreva conteúdo pastoral, nomes, telefones, mensagens ou dados
   pessoais.
10. Se encontrar problema visual bloqueante, não corrija. Registre evidência e
   recomende NÃO TIRAR DE DRAFT.
11. Se tudo estiver correto, recomende TIRAR PR #37 DE DRAFT.

RELATÓRIO FINAL
- estado do PR #37;
- URL/porta do preview usado;
- confirmação de que o login foi feito manualmente pelo usuário no Chrome
  visível;
- confirmação de que nenhuma credencial/token/sessão foi pedida, recebida,
  lida ou registrada;
- checklist visual desktop/mobile;
- descrição objetiva das telas verificadas;
- achados por severidade:
  - BLOQUEADOR DA F1;
  - DÍVIDA F2/F3/F4;
  - OBSERVAÇÃO NÃO BLOQUEANTE;
- confirmação de que nenhum arquivo foi alterado;
- conclusão única: TIRAR PR #37 DE DRAFT ou NÃO TIRAR DE DRAFT.
```

## Gate para avançar

- [ ] Usuário fez login manualmente no Chrome sem expor credenciais/tokens.
- [ ] Telas internas autenticadas foram verificadas em desktop.
- [ ] Telas internas autenticadas foram verificadas em mobile/responsivo.
- [ ] Nenhum arquivo foi alterado.
- [ ] Recomendação final: `TIRAR PR #37 DE DRAFT`.

---

# PROMPT 3.7 — ENVIAR AGORA

## Tirar PR #37 de draft e encerrar backend local

```text
[READY FOR REVIEW — PR #37 — SEM ALTERAR CÓDIGO]

MISSÃO
Tirar o PR #37 de draft após a revisão técnica e o smoke visual read-only da F1,
e encerrar o backend local usado no smoke para reduzir risco contra dados reais.

CONTEXTO
- PR #37: https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/37
- Branch: feat/redesign-f1-identidade
- HEAD esperado: 0e42310
- Revisão técnica 3.5: APTO PARA SAIR DE DRAFT.
- Smoke visual 3.6: recomendação final TIRAR PR #37 DE DRAFT.
- F1.5 auditoria: local/dev usa dados/serviços reais; não iniciar F2/F3 antes
  de B1+B2.

REGRAS
- Não alterar código.
- Não editar arquivos.
- Não fazer commit.
- Não fazer push.
- Não fazer merge.
- Não iniciar F2, F3 ou F4.
- Não mexer em banco, auth, env, Clerk, Supabase, webhooks ou dados.
- Não acessar credenciais/tokens/secrets.
- A única mutação autorizada no GitHub é marcar o PR #37 como ready for review.
- Encerrar apenas o backend local que foi iniciado para o smoke, se ele ainda
  estiver rodando em `:8000`; não encerrar processos não relacionados.

PASSOS
1. Confirme o estado do worktree:
   - branch correta;
   - HEAD local;
   - `git status`;
   - nenhum arquivo versionado modificado.
2. Confirme o estado do PR #37:
   - `OPEN`;
   - `isDraft: true`;
   - `headRefOid` igual ao HEAD esperado `0e42310`;
   - base `main`;
   - mergeable/checks sem bloqueio.
3. Se qualquer pré-condição falhar, pare e reporte. Não execute a ação.
4. Se tudo estiver correto, execute somente a ação de tirar o PR #37 de draft.
5. Confirme o estado final do PR:
   - `OPEN`;
   - `isDraft: false`;
   - `headRefOid` inalterado;
   - commits inalterados;
   - mergeable/checks.
6. Depois, encerre o backend local `:8000` usado no smoke, se ainda estiver
   rodando, e confirme que não há listener em `:8000`.
7. Não encerre o frontend `:3000` se ele for necessário para conferência visual;
   apenas reporte se ele continua rodando.

RELATÓRIO FINAL
- Estado antes/depois do PR #37.
- Confirmação de que nenhum arquivo foi alterado.
- Confirmação de que nenhum commit/push/merge foi feito.
- Confirmação de que F2/F3/F4 não foram iniciadas.
- Confirmação sobre backend local `:8000`: encerrado ou não estava rodando.
- Próximo passo recomendado: revisão/merge do PR #37; depois B1+B2 antes de
  F2/F3.
```

## Gate para avançar

- [ ] PR #37 não é mais draft.
- [ ] HEAD/commits do PR #37 inalterados.
- [ ] Nenhum arquivo alterado.
- [ ] Backend local `:8000` encerrado ou confirmado ausente.
- [ ] F2/F3/F4 não iniciadas.

---

# PROMPT 3.8 — PRONTO PARA ENVIAR APÓS 3.7

## Checagem final e merge da F1

```text
[CHECAGEM FINAL E MERGE — PR #37 — F1 IDENTIDADE]

MISSÃO
Fazer a checagem final do PR #37 e, se todas as pré-condições continuarem
verdes, mesclar a F1 na `main`.

CONTEXTO
- PR #37: https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/37
- Branch: feat/redesign-f1-identidade
- HEAD esperado: 0e42310
- PR #37 já saiu de draft.
- Revisão técnica 3.5: APTO PARA SAIR DE DRAFT.
- Smoke visual autenticado 3.6: TIRAR PR #37 DE DRAFT.
- Prompt 3.7: PR ficou ready for review; backend local `:8000` encerrado.
- Antes de F2/F3, B1+B2 são bloqueadores. Não iniciar próximas fases agora.

REGRAS
- Não alterar código.
- Não editar arquivos.
- Não criar commit novo.
- Não fazer push de novos commits.
- Não iniciar F2, F3 ou F4.
- Não mexer em banco, auth, env, Supabase, Clerk, WhatsApp, Asaas, Brevo ou
  webhooks.
- A única mutação autorizada, se todos os gates passarem, é mesclar o PR #37.
- Não deletar branch/worktree se ela estiver em uso.

GATES ANTES DO MERGE
1. Confirmar PR #37:
   - `OPEN`;
   - `isDraft: false`;
   - `headRefOid` igual a `0e42310`;
   - base `main`;
   - mergeable/checks sem bloqueio;
   - commits inalterados.
2. Confirmar diff do PR:
   - somente escopo F1/identidade;
   - arquivos esperados:
     - `frontend/package-lock.json`;
     - `frontend/package.json`;
     - `frontend/src/app/globals.css`;
     - `frontend/src/app/layout.tsx`;
     - `frontend/src/components/shell/Sidebar.tsx`;
   - sem backend/API/auth/RBAC/RLS/banco/navegação funcional.
3. Confirmar working tree sem modificações versionadas.
4. Confirmar que F2/F3/F4 não foram iniciadas.
5. Confirmar que backend local `:8000` segue encerrado ou não será usado.

SE QUALQUER GATE FALHAR
Pare. Não faça merge. Reporte o bloqueio.

SE TODOS OS GATES PASSAREM
Mescle o PR #37 usando a estratégia padrão do repositório. Não criar commit
extra fora do merge. Não deletar branch se houver worktree em uso.

RELATÓRIO FINAL
- Estado do PR antes/depois.
- Estratégia de merge usada.
- SHA final da `origin/main`.
- Confirmação de arquivos alterados.
- Confirmação de que nenhum código fora do escopo F1 entrou.
- Confirmação de que F2/F3/F4 não foram iniciadas.
- Confirmação de que B1+B2 continuam como pré-requisito antes de F2/F3.
```

## Gate para avançar

- [ ] PR #37 mesclado.
- [ ] `origin/main` contém a F1.
- [ ] Nenhum commit extra fora do merge.
- [ ] F2/F3/F4 não iniciadas.
- [ ] B1+B2 mantidos como próximos pré-requisitos antes de F2/F3.

---

# PROMPT 3.9 — CONCLUÍDO

## Registrar sprint da F1 pós-merge

```text
[REGISTRO PÓS-MERGE — F1 IDENTIDADE — DOCS ONLY]

MISSÃO
Registrar a conclusão da F1 em `docs/sprints`, sem alterar código de produto e
sem iniciar F2/F3/F4.

CONTEXTO
- F0 já foi mesclada pelo PR #35 e registrada pelo PR #36.
- F1 foi mesclada pelo PR #37.
- PR #37: feat(design): F1 — identidade Igreja 12.
- Commit da F1: `0e42310`.
- Merge commit da F1 na `origin/main`: `85bc1ea`.
- Durante o ciclo da F1, a `main` recebeu também o PR #38 de outra conversa
  sobre mostrar/ocultar senha no login; a F1 mesclou limpa por cima.
- Antes de F2/F3, B1+B2 são bloqueadores:
  - B1: staging isolado com Supabase/Clerk/dados de teste;
  - B2: guard/sandbox para impedir WhatsApp, cobrança e e-mail reais fora de
    produção.

REGRAS
- Docs only.
- Não alterar código de produto.
- Não alterar frontend/backend/config/env.
- Não mexer em banco, auth, webhooks, Supabase, Clerk, WhatsApp, Asaas ou Brevo.
- Não iniciar F2/F3/F4.
- Não criar branch F2/F3/F4.
- Não apagar branches/worktrees existentes.
- Não expor valores de env/secrets.

PASSOS
1. Atualize a `main` local/remota de forma segura ou use uma branch docs nova a
   partir de `origin/main`.
2. Confirme que `origin/main` contém o merge da F1 (`85bc1ea`) e que o commit
   `0e42310` é ancestral.
3. Crie um arquivo docs:
   `docs/sprints/2026-06-25-redesign-f1-identidade.md`.
4. O registro deve conter:
   - objetivo da F1;
   - PR/commits/merge commit;
   - arquivos alterados;
   - resumo técnico: fontes offline `@fontsource`, Sora/Inter/JetBrains,
     tokens/contraste, Sidebar, Topbar, tabelas, pills, foco;
   - validações executadas: typecheck/lint/build, contraste, fontes offline,
     CodeGraph/affected flows, smoke autenticado read-only;
   - limitações aceitas: modal ao vivo não aberto; mobile autenticado não
     capturado; ambos baixo risco para F1;
   - risco ambiental descoberto: local/dev usa dados/serviços reais;
   - próximos bloqueadores antes de F2/F3: B1+B2;
   - confirmação de que F2/F3/F4 não foram iniciadas.
5. Faça commit docs-only em branch docs própria.
6. Abra PR pequeno de documentação para `main`.
7. Se o PR docs estiver limpo, mergeie usando a estratégia padrão do repo.
8. Não delete branch se estiver em uso.

RELATÓRIO FINAL
- branch usada;
- arquivo criado;
- commit docs;
- PR docs criado/mesclado;
- SHA final da `origin/main`;
- confirmação de docs-only;
- confirmação de que F2/F3/F4 não foram iniciadas;
- próximo passo recomendado: B1+B2 antes de F2/F3.
```

## Gate para avançar

- [x] Registro da F1 criado em `docs/sprints`.
- [x] PR docs da F1 mesclado na `main`.
- [x] Alteração docs-only.
- [x] F2/F3/F4 não iniciadas.
- [x] B1+B2 mantidos como próximos pré-requisitos.

---

# PROMPT 4.0 — ENVIAR AGORA

## B1 — Plano executável de staging isolado

```text
[B1 — STAGING ISOLADO — PLANO EXECUTÁVEL — SEM IMPLEMENTAR AINDA]

MISSÃO
Planejar a criação de um ambiente staging/dev isolado antes de F2/F3, sem ainda
alterar código, banco ou serviços externos.

CONTEXTO
- F0 mesclada e registrada.
- F1 mesclada pelo PR #37 e registrada pelo PR docs #39.
- `origin/main` atual após registro F1: `3e0d4c4`.
- F2/F3 ainda não devem iniciar.
- Auditoria F1.5 concluiu que local/dev hoje usa banco/auth/serviços reais.
- B1 é bloqueador antes de F2/F3: staging isolado com Supabase/Clerk/dados de
  teste.
- B2 virá depois: guard/sandbox para impedir envios/cobranças/e-mails reais fora
  de produção.

REGRAS
- Read-only.
- Não alterar código.
- Não criar migrations.
- Não alterar banco.
- Não criar projeto Supabase/Clerk ainda.
- Não mexer em produção.
- Não exibir valores de env/secrets.
- Não iniciar F2/F3/F4.
- Não criar branch de feature ainda.

INVESTIGUE
1. Liste todos os arquivos de schema/migrations/seeds existentes.
2. Identifique como o backend espera as tabelas e policies atuais.
3. Identifique quais variáveis de ambiente seriam necessárias para um staging
   isolado, apenas por NOME.
4. Separe o que deve ser duplicado em staging:
   - Supabase/Postgres;
   - Storage, se usado;
   - RLS/policies;
   - Clerk/Auth;
   - usuários/contas de teste;
   - webhooks desativados ou mockados;
   - frontend/backend env.
5. Proponha um plano de execução em etapas pequenas:
   - criar Supabase staging;
   - aplicar schema;
   - criar tabela de controle de migrations, se necessário;
   - criar seed fictício;
   - criar Clerk dev/staging;
   - configurar env local/staging;
   - validar login com conta de teste;
   - provar que staging não aponta para produção.
6. Identifique quais passos exigem ação manual do usuário em painel externo
   (Supabase/Clerk/Vercel/etc.).
7. Liste riscos e gates de segurança.

RELATÓRIO FINAL
- Diagnóstico do estado atual.
- Plano B1 em passos numerados.
- Quais arquivos precisariam ser criados/alterados numa implementação futura.
- Quais ações manuais o usuário precisará fazer.
- Gates para provar que staging é isolado.
- O que não fazer.
- Recomendação do próximo prompt de implementação B1, se o plano estiver pronto.
```

## Gate para avançar

- [ ] Plano B1 documentado.
- [ ] Ações manuais identificadas.
- [ ] Arquivos futuros identificados.
- [ ] Gates de isolamento definidos.
- [ ] Nenhuma alteração aplicada ainda.

---

# PROMPT 4.0.5 — CONCLUÍDO

## Revisar e mesclar PR #40 — artefatos B1

```text
[REVISÃO E MERGE — PR #40 — B1 ARTEFATOS DE STAGING]

MISSÃO
Revisar independentemente o PR #40, confirmar que ele só adiciona artefatos
seguros de staging e, se todos os gates passarem, mesclar na main.

CONTEXTO
- F0/F1 já foram mescladas e registradas.
- `origin/main` antes do B1-IMPL: `3e0d4c4`.
- B1 planejamento decidiu: staging = projeto Supabase dedicado, não Postgres
  local.
- PR #40: https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/40
- Branch: `chore/staging-b1-artefatos`
- Commit esperado: `7293827`
- Arquivos esperados:
  - `.gitignore`
  - `backend/.env.staging.example`
  - `frontend/.env.staging.example`
  - `backend/scripts/apply_migrations.py`
  - `deploy/STAGING.md`

REGRAS
- Não alterar código.
- Não criar novos commits.
- Não tocar banco.
- Não aplicar migrations.
- Não criar Supabase/Clerk.
- Não mexer em produção.
- Não chamar serviços externos.
- Não iniciar F2/F3/F4.
- A única mutação autorizada, se todos os gates passarem, é mesclar o PR #40.

GATES DE REVISÃO
1. Confirmar estado do PR #40:
   - OPEN;
   - branch correta;
   - commit/head esperado ou reportar se mudou;
   - mergeable/checks.
2. Confirmar diff:
   - exatamente os arquivos esperados ou justificar diferenças;
   - sem código de produto;
   - sem migrations aplicadas;
   - sem valores reais de env/secrets.
3. Validar `.gitignore`:
   - `.env.staging` ignorado;
   - `.env.staging.example` versionável.
4. Validar `apply_migrations.py` sem tocar banco real:
   - compila;
   - `list` mostra migrations em ordem;
   - `status/apply` sem destino falham;
   - `apply` exige confirmação explícita;
   - falhas de conexão não expõem senha.
5. Validar docs:
   - deixam claro que staging usa Supabase dedicado;
   - ações manuais estão explícitas;
   - gates de isolamento estão claros;
   - B2 permanece necessário antes de F2/F3.
6. Confirmar que `plano-b1-staging-isolado.html` não entrou no commit, a menos
   que exista decisão explícita para versioná-lo.

SE QUALQUER GATE FALHAR
Pare. Não faça merge. Reporte o bloqueio.

SE TODOS OS GATES PASSAREM
Mescle o PR #40 usando a estratégia padrão do repositório. Não delete branch se
estiver em uso.

RELATÓRIO FINAL
- Estado do PR antes/depois.
- SHA final da `origin/main`.
- Arquivos alterados.
- Confirmação de que nenhum banco/serviço externo foi tocado.
- Confirmação de que F2/F3/F4 não foram iniciadas.
- Próximo passo recomendado: ações manuais B1 ou planejamento B2.
```

## Gate para avançar

- [x] PR #40 revisado.
- [x] PR #40 mesclado.
- [x] Nenhum banco/serviço externo tocado.
- [x] F2/F3/F4 não iniciadas.
- [x] Próximas ações manuais B1 identificadas.

---

# PROMPT 4.1 — CONCLUÍDO

## B2 — Plano de guard/sandbox para envios não-prod

```text
[B2 — GUARD/SANDBOX NÃO-PROD — PLANO EXECUTÁVEL — SEM IMPLEMENTAR AINDA]

MISSÃO
Planejar os guards de não-produção para impedir que ambiente local/staging
dispare WhatsApp, cobrança, e-mail ou webhooks reais.

REGRAS
- Read-only.
- Não alterar código.
- Não alterar env.
- Não mexer em produção.
- Não disparar chamadas externas.
- Não iniciar F2/F3/F4.

INVESTIGUE
1. Onde o app envia WhatsApp/Evolution.
2. Onde o app cria cobrança/assinatura/Asaas.
3. Onde o app envia e-mail/Brevo.
4. Onde o app chama Google Calendar/OAuth ou outros externos.
5. Quais flags/guards seriam necessários:
   - `APP_ENV`;
   - `ALLOW_REAL_SENDS`;
   - `EXTERNAL_SENDS_ENABLED`;
   - URLs sandbox/mock;
   - logs em vez de envio fora de produção.
6. Proponha desenho de implementação com dupla trava:
   - production permite real;
   - staging/dev bloqueia por padrão;
   - override explícito só se seguro.
7. Proponha testes/gates para provar que nada real dispara em staging.

RELATÓRIO FINAL
- Mapa dos pontos de envio externo.
- Plano B2 em passos pequenos.
- Arquivos que precisariam mudar em implementação futura.
- Flags recomendadas.
- Testes/gates.
- Riscos restantes.
```

## Gate para avançar

- [x] Pontos de envio externo mapeados.
- [x] Flags/guards definidos.
- [x] Testes/gates definidos.
- [x] Nenhuma alteração aplicada ainda.

---

# PROMPT 4.2 — B2-IMPL — ENVIAR AGORA

## Implementar guard/sandbox de envios não-prod

**Conversa recomendada:** enviar na mesma conversa do Claude que executou o
Prompt 4.1, porque ela já tem o mapa completo dos pontos de egress.

```text
[B2-IMPL — GUARD/SANDBOX DE ENVIOS NÃO-PROD — BRANCH NOVA]

MISSÃO
Implementar o guard de não-produção para impedir que ambientes local/staging
disparem WhatsApp, cobrança, e-mail, LLM ou Google Calendar reais fora de
produção.

CONTEXTO
- F0/F1 concluídas e registradas.
- B1 artefatos de staging mesclados pelo PR #40, merge commit `9726e06`.
- B1 manual ainda pendente: Supabase staging, bucket, Clerk dev, usuário teste,
  migrations e gates.
- B2 planejamento read-only concluído.
- Achado central do B2: egress externo passa por clientes em
  `backend/app/services/*`; o guard deve ficar na camada de serviço.
- Não iniciar F2/F3/F4.

REGRAS
- Criar branch nova a partir de `origin/main`.
- Não tocar banco.
- Não aplicar migrations.
- Não criar Supabase/Clerk.
- Não mexer em produção.
- Não chamar serviços externos reais.
- Não usar ou exibir secrets.
- Não iniciar workers contra serviços reais.
- Não iniciar F2/F3/F4.
- Não alterar fluxo de produto além do necessário para o guard.

IMPLEMENTAR
1. Config:
   - adicionar flag `ALLOW_REAL_SENDS` com default seguro `false`;
   - expor propriedade/função `external_sends_enabled`;
   - regra base: `external_sends_enabled = is_production or allow_real_sends`.
2. Criar helper, por exemplo:
   - `backend/app/services/outbound_guard.py`;
   - função para decidir se pode enviar;
   - logging `[SANDBOX]`/skip-and-log sem segredos.
3. Bloquear fora de produção, com retorno neutro e log explícito:
   - `EvolutionClient.send_text`;
   - `EvolutionClient.send_media`;
   - `EvolutionClient.set_webhook`;
   - `AsaasClient.create_checkout`;
   - `BrevoClient.send_invite`;
   - `BrevoClient.send_password_reset`;
   - `LLMClient.complete`;
   - `GoogleCalendarClient.create_event`;
   - `GoogleCalendarClient.delete_event`.
4. Decidir e documentar pontos cinza:
   - Evolution `connect`/`disconnect`/`reconnect`;
   - Clerk `create_user`;
   - LLM `validate_credential`.
   Preferência: bloquear operações que possam atingir recurso compartilhado em
   não-produção, salvo se forem claramente auth/infra local.
5. Se necessário, curto-circuitar `cron_worker`/SLA para não gerar envios fora
   de produção.
6. Atualizar docs/env examples:
   - `.env.example`;
   - `backend/.env.staging.example`;
   - `deploy/STAGING.md`;
   - documentar `ALLOW_REAL_SENDS` e o comportamento default.
7. Criar/ajustar testes:
   - não-prod não chama `httpx` nos 9 métodos;
   - produção preserva comportamento;
   - override `ALLOW_REAL_SENDS=true` funciona apenas quando esperado;
   - logs/retornos neutros não expõem segredo;
   - teste-meta de cobertura dos métodos guardados.

GATES
- Typecheck/testes relevantes verdes.
- Nenhuma chamada externa real feita durante testes.
- Nenhum segredo no diff.
- `APP_ENV=staging` + `ALLOW_REAL_SENDS=false` bloqueia envios.
- `APP_ENV=production` preserva envio real.
- F2/F3/F4 não iniciadas.

RELATÓRIO FINAL
- branch criada;
- arquivos alterados;
- métodos protegidos;
- comportamento em produção vs staging/dev;
- testes executados;
- confirmação de que nenhum banco/serviço externo foi tocado;
- PR criado como draft ou pronto para review;
- riscos restantes.
```

## Gate para avançar

- [ ] B2-IMPL em PR próprio.
- [x] Todos os métodos externos críticos protegidos.
- [x] Testes comprovam bloqueio fora de produção.
- [x] Produção preserva comportamento.
- [x] Nenhum banco/serviço externo tocado.
- [x] F2/F3/F4 não iniciadas.

---

# PROMPT 4.3 — CONCLUÍDO

## Revisão independente do PR #41 — B2 guard não-prod

**Conversa recomendada:** abrir nova conversa no Claude.

Motivo: o PR #41 já existe no GitHub e a revisão deve ser independente da
conversa que implementou o B2, especialmente porque houve queda de internet e a
revisão adversarial original foi interrompida.

```text
[REVISÃO INDEPENDENTE — PR #41 — B2 GUARD NÃO-PROD]

MISSÃO
Revisar independentemente o PR #41, confirmar se o guard de envios não-prod está
correto e decidir se o PR pode sair de draft.

CONTEXTO
- Repositório: haniellevi/PastorAI-LionClaw-V1
- F0/F1 concluídas e registradas.
- B1 artefatos de staging mesclados pelo PR #40, merge commit `9726e06`.
- B2-IMPL entregue em PR draft #41.
- PR #41: https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/41
- Branch: `feat/b2-guard-envios-naoprod`
- Commit esperado: `91736bd`
- Implementação reportada:
  - 11 métodos protegidos;
  - 531 testes passed;
  - nenhum segredo no diff;
  - nenhum banco/serviço externo tocado;
  - F2/F3/F4 não iniciadas.

REGRAS
- Read-only.
- Não alterar código.
- Não fazer commit.
- Não fazer push.
- Não tirar o PR de draft ainda.
- Não fazer merge.
- Não tocar banco.
- Não chamar serviço externo real.
- Não iniciar F2/F3/F4.
- Não usar/exibir secrets.

GATES DE REVISÃO
1. Confirmar estado do PR #41:
   - OPEN;
   - draft;
   - branch correta;
   - head commit `91736bd` ou reportar divergência;
   - base `main`;
   - mergeable/checks.
2. Confirmar diff:
   - arquivos alterados;
   - sem frontend/redesign F2/F3;
   - sem migrations;
   - sem valores reais de env/secrets.
3. Confirmar configuração:
   - `ALLOW_REAL_SENDS` default seguro `false`;
   - `external_sends_enabled = is_production or allow_real_sends`;
   - comportamento documentado em env/docs.
4. Confirmar métodos guardados:
   - `EvolutionClient.send_text`;
   - `EvolutionClient.send_media`;
   - `EvolutionClient.set_webhook`;
   - `EvolutionClient.connect`;
   - `EvolutionClient.reconnect`;
   - `EvolutionClient.disconnect`;
   - `AsaasClient.create_checkout`;
   - `BrevoClient.send_invite`;
   - `BrevoClient.send_password_reset`;
   - `LLMClient.complete`;
   - `GoogleCalendarClient.create_event`;
   - `GoogleCalendarClient.delete_event`.
5. Confirmar exclusões conscientes:
   - Clerk `create_user`;
   - LLM `validate_credential`;
   - explicar se a decisão é aceitável por serem auth/infra e dependentes do B1.
6. Confirmar worker/SLA:
   - `cron_worker` não foi alterado;
   - verificar se o guard em `send_text` cobre envios autônomos;
   - registrar se isso é suficiente ou se precisa ajuste.
7. Rodar testes relevantes sem rede real:
   - testes do outbound guard;
   - testes dos services alterados;
   - suíte completa se viável;
   - scan de segredos no diff.
8. Revisar retorno neutro/logs:
   - não quebrar fluxo esperado;
   - não expor secrets;
   - logs `[SANDBOX]` claros.

SE HOUVER BLOQUEADOR
Não tire de draft. Liste o bloqueio e o prompt de correção.

SE NÃO HOUVER BLOQUEADOR
Concluir: `APTO PARA SAIR DE DRAFT`, mas não executar a ação ainda.

RELATÓRIO FINAL
- estado do PR;
- arquivos alterados;
- métodos protegidos;
- métodos conscientemente não protegidos;
- testes executados;
- riscos restantes;
- confirmação de que nenhum banco/serviço externo foi tocado;
- confirmação de que F2/F3/F4 não foram iniciadas;
- conclusão única: `APTO PARA SAIR DE DRAFT` ou `NÃO TIRAR DE DRAFT`.
```

## Gate para avançar

- [x] PR #41 revisado independentemente.
- [x] Nenhum bloqueador encontrado.
- [x] Conclusão: `APTO PARA SAIR DE DRAFT`.

---

# PROMPT 4.4 — CONCLUÍDO

## Tirar PR #41 de draft

**Conversa recomendada:** enviar na mesma conversa do Claude que fez a revisão
independente do PR #41, porque ela já confirmou os gates.

```text
[READY FOR REVIEW — PR #41 — B2 GUARD NÃO-PROD]

MISSÃO
Tirar o PR #41 de draft após revisão independente concluir `APTO PARA SAIR DE DRAFT`.

CONTEXTO
- PR #41: https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/41
- Branch: `feat/b2-guard-envios-naoprod`
- Commit esperado: `91736bd`
- Revisão independente: `APTO PARA SAIR DE DRAFT`
- Revisão confirmou 12 métodos guardados, 531 testes passed e nenhum serviço
  externo/banco tocado.
- Não iniciar F2/F3/F4.

REGRAS
- Não alterar código.
- Não editar descrição do PR, salvo se for apenas corrigir a contagem 11→12 e
  isso for feito sem commit.
- Não fazer commit.
- Não fazer push.
- Não fazer merge.
- Não tocar banco.
- Não chamar serviço externo.
- Não iniciar F2/F3/F4.
- A única mutação autorizada é marcar o PR #41 como ready for review.

PASSOS
1. Confirmar estado atual do PR #41:
   - OPEN;
   - draft;
   - head `91736bd`;
   - base `main`;
   - mergeable/checks sem bloqueio.
2. Confirmar que nenhum commit novo apareceu depois da revisão.
3. Se tudo estiver igual, marcar o PR como ready for review.
4. Confirmar estado final:
   - OPEN;
   - `isDraft: false`;
   - head/commits inalterados.

RELATÓRIO FINAL
- Estado antes/depois.
- Confirmação de que nenhum arquivo/commit/push/merge foi feito.
- Confirmação de que F2/F3/F4 não foram iniciadas.
- Próximo passo recomendado: checagem final e merge do PR #41.
```

## Gate para avançar

- [x] PR #41 não é mais draft.
- [x] Head/commits inalterados.
- [x] Nenhum código alterado.
- [x] F2/F3/F4 não iniciadas.

---

# PROMPT 4.5 — CONCLUÍDO

## Checagem final e merge do PR #41

**Conversa recomendada:** enviar na mesma conversa do Claude que tirou o PR #41
de draft.

```text
[CHECAGEM FINAL E MERGE — PR #41 — B2 GUARD NÃO-PROD]

MISSÃO
Fazer a checagem final do PR #41 e, se todos os gates continuarem verdes,
mesclar o B2 na `main`.

CONTEXTO
- PR #41: https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/41
- Branch: `feat/b2-guard-envios-naoprod`
- Head esperado: `91736bd`
- PR #41 já saiu de draft.
- Revisão independente: `APTO PARA SAIR DE DRAFT`.
- 12 métodos guardados.
- Suíte reportada: 531 passed.
- Sem banco/serviço externo tocado.
- F2/F3/F4 não iniciadas.

REGRAS
- Não alterar código.
- Não criar commit novo.
- Não fazer push de novos commits.
- Não tocar banco.
- Não chamar serviço externo.
- Não iniciar F2/F3/F4.
- A única mutação autorizada, se todos os gates passarem, é mesclar o PR #41.
- Não deletar branch se estiver em uso.

GATES ANTES DO MERGE
1. Confirmar PR #41:
   - OPEN;
   - `isDraft: false`;
   - head `91736bd`;
   - base `main`;
   - MERGEABLE/CLEAN;
   - commits inalterados.
2. Confirmar diff:
   - backend + docs apenas;
   - sem frontend/redesign F2/F3;
   - sem migrations;
   - sem valores reais de env/secrets.
3. Confirmar que não houve commits novos depois da revisão independente.
4. Confirmar que F2/F3/F4 não foram iniciadas.
5. Confirmar que nenhum banco/serviço externo foi tocado.

SE QUALQUER GATE FALHAR
Pare. Não faça merge. Reporte o bloqueio.

SE TODOS OS GATES PASSAREM
Mescle o PR #41 usando a estratégia padrão do repositório. Não delete branch se
estiver em uso.

RELATÓRIO FINAL
- Estado do PR antes/depois.
- Estratégia de merge.
- SHA final da `origin/main`.
- Arquivos alterados.
- Confirmação de que B2 está na main.
- Confirmação de que nenhum banco/serviço externo foi tocado.
- Confirmação de que F2/F3/F4 não foram iniciadas.
- Próximo passo recomendado:
  - ações manuais B1, se ainda pendentes; ou
  - validação final B1+B2 antes de liberar F2/F3.
```

## Gate para avançar

- [x] PR #41 mesclado.
- [x] B2 presente na `origin/main`.
- [x] Nenhum commit extra fora do merge.
- [x] Nenhum banco/serviço externo tocado.
- [x] F2/F3/F4 não iniciadas.

---

# PROMPT 4.6 — CONCLUÍDO

## Registrar sprint B1/B2 pós-merge

**Conversa recomendada:** enviar na mesma conversa do Claude que mesclou o PR
#41, porque ele acabou de confirmar o merge e o SHA final.

```text
[REGISTRO PÓS-MERGE — B1/B2 AMBIENTES — DOCS ONLY]

MISSÃO
Registrar em `docs/sprints` o bloco de confiabilidade de ambientes B1/B2:
artefatos de staging + guard não-prod. Não iniciar F2/F3/F4.

CONTEXTO
- F0/F1 já foram mescladas e registradas.
- B1 artefatos de staging: PR #40 mesclado, merge commit `9726e06`.
- B2 guard não-prod: PR #41 mesclado, merge commit `7cd30bb`.
- B2 commit: `91736bd`.
- B2 protege 12 métodos externos.
- B1 manual ainda pendente:
  - criar Supabase staging;
  - bucket `whatsapp-media`;
  - Clerk dev/test;
  - usuário de teste;
  - aplicar migrations;
  - validar gates de isolamento.
- F2/F3/F4 ainda NÃO foram iniciadas.

REGRAS
- Docs only.
- Não alterar código.
- Não mexer em banco.
- Não chamar serviços externos.
- Não criar Supabase/Clerk.
- Não aplicar migrations.
- Não iniciar F2/F3/F4.
- Não exibir secrets.

PASSOS
1. Confirmar que `origin/main` contém:
   - PR #40 / merge `9726e06`;
   - PR #41 / merge `7cd30bb`;
   - commit B2 `91736bd` ancestral.
2. Criar branch docs nova a partir de `origin/main`.
3. Criar arquivo:
   `docs/sprints/2026-06-25-ambientes-b1-b2-staging-guard.md`
4. O registro deve conter:
   - objetivo do bloco;
   - por que B1/B2 foram necessários antes de F2/F3;
   - resumo B1: Supabase dedicado, artefatos versionáveis, `deploy/STAGING.md`,
     runner de migrations, templates env;
   - resumo B2: `ALLOW_REAL_SENDS`, `external_sends_enabled`, guard em camada de
     service, 12 métodos protegidos;
   - PRs/commits/merge commits;
   - validações: testes, revisão independente, scan de segredos, sem banco/externos;
   - pendência: B1 manual ainda não executado;
   - gate para liberar F2/F3: B1 manual concluído + isolamento validado.
5. Commit docs-only.
6. Abrir PR docs pequeno.
7. Se limpo, mesclar pelo padrão do repo.

RELATÓRIO FINAL
- branch usada;
- arquivo criado;
- commit docs;
- PR docs criado/mesclado;
- SHA final da `origin/main`;
- confirmação de docs-only;
- confirmação de que F2/F3/F4 não foram iniciadas;
- próximo passo recomendado: executar B1 manual seguindo `deploy/STAGING.md`.
```

## Gate para avançar

- [x] Registro B1/B2 criado em `docs/sprints`.
- [x] PR docs B1/B2 mesclado.
- [x] Alteração docs-only.
- [x] F2/F3/F4 não iniciadas.
- [x] Próximo passo B1 manual registrado.

---

# PROMPT 5.0 — PRÓXIMO PASSO MANUAL

## B1 manual — preparar checklist assistido de staging

**Conversa recomendada:** abrir nova conversa no Claude.

Motivo: agora sai do ciclo de PRs/docs e entra em operação manual de painel
externo e banco. Nova conversa reduz risco de confundir worktrees antigos e
obriga o agente a confirmar estado atual da `main` antes de orientar.

```text
[B1 MANUAL — STAGING ISOLADO — CHECKLIST ASSISTIDO — SEM EXECUTAR SEM CONFIRMAÇÃO]

MISSÃO
Guiar o usuário, passo a passo, na criação do ambiente staging isolado seguindo
`deploy/STAGING.md`, sem tocar produção e sem executar ações irreversíveis sem
confirmação explícita.

CONTEXTO
- Repositório: haniellevi/PastorAI-LionClaw-V1
- F0/F1 concluídas.
- B1 artefatos mesclados pelo PR #40.
- B2 guard não-prod mesclado pelo PR #41.
- Registro docs B1/B2 mesclado pelo PR #42.
- `origin/main` esperado: `ab4ea2a`.
- F2/F3/F4 ainda NÃO devem iniciar.
- Objetivo atual: B1 manual — criar staging isolado e validar gates.

REGRAS
- Não iniciar F2/F3/F4.
- Não tocar produção.
- Não usar dados reais de fiéis em staging.
- Não exibir secrets no chat.
- Não aplicar migrations em produção.
- Não rodar workers contra serviços reais.
- Não alterar código.
- Não fazer commit/push/merge.
- Operações em painel externo devem ser guiadas para o usuário executar.
- Antes de qualquer comando que conecte em banco, confirmar que o alvo é staging
  e que o project ref é diferente do de produção.

PASSOS
1. Confirmar localmente:
   - `origin/main` contém `ab4ea2a`;
   - `deploy/STAGING.md` existe;
   - `backend/scripts/apply_migrations.py` existe;
   - templates `.env.staging.example` existem.
2. Ler `deploy/STAGING.md` e resumir o checklist operacional.
3. Criar um checklist interativo para o usuário executar nos painéis:
   - Supabase staging dedicado;
   - bucket privado `whatsapp-media`;
   - Clerk dev/test;
   - usuário de teste;
   - envs staging com `APP_ENV=staging` e `ALLOW_REAL_SENDS=false`.
4. Para cada etapa, dizer:
   - o que o usuário precisa clicar/criar;
   - quais valores copiar para arquivo local, sem colar no chat;
   - quais nomes de variáveis preencher;
   - qual gate valida o passo.
5. Quando chegar na aplicação de migrations:
   - antes de rodar, pedir confirmação explícita de que o DATABASE_URL é do
     Supabase staging;
   - confirmar project ref distinto de produção;
   - listar migrations em ordem;
   - só então orientar o comando.
6. Depois das migrations:
   - orientar o casamento do `app_users.clerk_user_id` com o usuário Clerk dev;
   - validar login com conta teste;
   - validar RLS;
   - validar que externos estão sem credencial ou bloqueados pelo B2;
   - validar que tentativas de envio geram apenas log `[SANDBOX]`.

ENTREGA ESPERADA
- Checklist B1 manual com status por etapa.
- Lista de ações que o usuário deve fazer em painel.
- Lista de comandos seguros, quando houver.
- Gates de isolamento.
- Ponto exato em que F2/F3 ficam liberadas.
```

## Gate para liberar F2/F3

- [x] Supabase staging criado e project ref distinto de produção.
- [x] Bucket privado `whatsapp-media` criado no staging.
- [x] Clerk dev/test criado.
- [x] Usuário de teste criado.
- [x] Migrations aplicadas no staging.
- [x] `app_users.clerk_user_id` casado com usuário Clerk dev.
- [x] Env staging com `APP_ENV=staging` e `ALLOW_REAL_SENDS=false`.
- [x] Login teste validado.
- [x] RLS efetiva validada.
- [x] Externos reais bloqueados; logs `[SANDBOX]` validados.

---

# PROMPT 5.1 — CONCLUÍDO

## Registrar conclusão do B1 manual

**Conversa recomendada:** enviar na mesma conversa do Claude que concluiu o B1
manual.

```text
[REGISTRO OPERACIONAL — B1 MANUAL CONCLUÍDO — DOCS ONLY]

MISSÃO
Registrar em documentação o fechamento dos gates manuais do B1/staging, sem
alterar código de produto e sem iniciar F2/F3/F4.

CONTEXTO
- B1 artefatos: PR #40.
- B2 guard: PR #41.
- Registro B1/B2: PR #42.
- B1 manual agora concluiu todos os gates:
  - ref distinto;
  - Clerk test;
  - cripto exclusiva;
  - volume = seed;
  - externos sem credencial;
  - produção intocada;
  - migrations 24/24;
  - `clerk_user_id` casado + login;
  - RLS efetiva;
  - guard `[SANDBOX]`.
- F2/F3 ainda não foram iniciadas.

REGRAS
- Docs only.
- Não alterar código de produto.
- Não exibir secrets/refs sensíveis além do que já foi autorizado.
- Não tocar banco.
- Não rodar workers.
- Não iniciar F2/F3/F4.

PASSOS
1. Registrar o resultado em `docs/sprints` ou atualizar o registro B1/B2, conforme
   o padrão já usado.
2. Incluir:
   - data;
   - gates fechados;
   - evidências sem secrets;
   - decisão: F2/F3 liberadas do ponto de vista de ambiente;
   - ressalva: workers ainda não sobem;
   - próximo passo recomendado.
3. Fazer commit docs-only em branch própria.
4. Abrir PR docs pequeno.
5. Se limpo, mesclar.

RELATÓRIO FINAL
- arquivo criado/alterado;
- PR docs;
- SHA final da main;
- confirmação de docs-only;
- confirmação de que F2/F3/F4 não foram iniciadas.
```

---

# PROMPT 5.2 — PREPARAR PRÓXIMA FRENTE

## Escolher F2 ou F3

**Conversa recomendada:** abrir nova conversa no Claude depois do registro 5.1.

Motivo: B1/B2 acabaram. A próxima frente volta a ser redesign/produto, então é
melhor começar com contexto limpo a partir da `main` atual e do staging validado.

Antes de enviar F2/F3, definir a ordem correta:

- F2 deve ser navegação/shell/organização das telas, se essa foi a próxima fase
  planejada.
- F3 deve ser mobile-first/responsivo, se essa foi a fase seguinte.
- F1 já foi identidade visual. Não chamar F2 de identidade visual.

## Handoff recomendado para nova conversa

```text
Estou continuando o redesign Igreja 12 / PastorAI.

Repositório: haniellevi/PastorAI-LionClaw-V1
origin/main atual esperado: e32fdd15dc2bdce93f6e56216c369c3dfd60952c

Estado consolidado:
- F0 tokens: concluída e registrada.
- F1 identidade Igreja 12: concluída e registrada.
- B1 artefatos de staging: concluídos e mesclados.
- B2 guard não-prod: concluído e mesclado.
- B1 manual/staging: concluído e registrado pelo PR docs #43.
- Staging Supabase/Clerk isolado existe, migrations 24/24 aplicadas, login teste
  funciona, RLS validada, guard [SANDBOX] ativo, produção intocada.
- F2/F3 agora estão liberadas do ponto de vista de ambiente.

Importante:
- F1 já foi identidade visual.
- Não chamar F2 de identidade visual.
- Não iniciar F3 ainda se F2 for a próxima fase do roadmap.
- Não tocar produção.
- Usar staging para smoke/testes autenticados.
- Não rodar workers contra serviços reais.

Missão inicial:
Antes de implementar, confirme pelo roadmap/checklist qual é exatamente a F2.
Minha hipótese atual: F2 = navegação/shell/organização das telas. F3 = mobile-first/responsivo.

Faça primeiro uma investigação read-only:
1. confirmar `origin/main`;
2. ler `docs/CHECKLIST-SUPERVISAO-CLAUDE-CODE.md`;
3. ler docs/sprints recentes;
4. identificar escopo exato da F2;
5. propor plano/prompt de implementação da F2 em branch nova, com gates.

Não implemente ainda até reportar o plano F2.
```

---

# F1.5 — Ambientes dev/staging/produção

## Quando executar

Executar depois que a F1 estiver revisada/encaminhada e antes de iniciar F2/F3
ou qualquer piloto real com igreja.

Esta etapa não bloqueia o smoke visual da F1. Ela existe para evitar que as
próximas fases de redesign e testes operem sobre dados reais sem proteção.

## Decisão atual

- App publicado no ar não significa automaticamente produção operacional.
- Sem usuários reais, piloto ativo, WhatsApp real ou rotina pastoral dependendo
  do sistema, o ambiente atual deve ser tratado como pré-produção/publicado.
- Se o banco/auth/webhooks já usam dados reais, então existe risco de produção
  mesmo sem usuários externos.
- Até a F1 fechar, qualquer navegação autenticada deve ser somente leitura.
- Auditoria read-only já confirmou que local/dev hoje usa banco/auth/serviços
  reais. Portanto, F2/F3 não devem começar antes de B1+B2.

## Resultado da auditoria F1.5

- Estado atual: sem separação real entre dev/staging/produção.
- Local/dev: conecta ao mesmo Supabase/Auth e pode alcançar serviços externos
  reais.
- Migrations: aplicadas manualmente, sem runner/tabela de controle.
- Risco principal: qualquer teste autenticado pode criar/alterar dados reais ou
  disparar WhatsApp/cobrança/e-mail real.
- Exceção aceita: smoke visual da F1 pode continuar se for estritamente
  read-only.
- Bloqueador B1 antes de F2/F3: staging isolado com Supabase/Clerk/dados de
  teste.
- Bloqueador B2 antes de F2/F3: guard/sandbox para impedir envios/cobranças/e-mails
  reais fora de produção.

## Prompt F1.5 — auditoria e plano de ambientes

```text
[AUDITORIA DE AMBIENTES — DEV/STAGING/PROD — SEM ALTERAR CÓDIGO]

MISSÃO
Analisar a separação atual de ambientes do projeto e propor uma configuração
segura mínima antes de avançar para F2/F3 ou piloto real com igreja.

REGRAS
- Read-only.
- Não alterar código.
- Não alterar banco.
- Não criar migrations.
- Não mexer em produção.
- Não exibir valores de env/secrets.
- Não pedir senha, token, cookie ou localStorage.
- Não iniciar F2/F3/F4.

CONTEXTO
- O app já tem deploy público, mas ainda não deve ser tratado como produção
  operacional madura se não há usuários reais/piloto ativo.
- O smoke da F1 pode usar ambiente conectado a dados reais apenas em modo
  read-only.
- Antes de novas fases, precisamos reduzir risco de mutação acidental em dados
  reais.

INVESTIGUE
1. Quais ambientes existem hoje:
   - local;
   - preview/staging, se existir;
   - deploy público;
   - produção operacional, se existir.
2. Quais serviços estão envolvidos:
   - Supabase/banco;
   - Clerk/Auth;
   - backend;
   - frontend;
   - WhatsApp/webhooks;
   - Vercel/deploy ou equivalente.
3. Quais variáveis separam ambiente local, staging e produção.
   Liste apenas NOMES, nunca valores.
4. Se local/dev hoje aponta para dados reais.
5. Se o deploy público atual usa banco/auth/webhooks reais.
6. Quais riscos existem:
   - mutação acidental em dados reais;
   - testes criando/alterando registros reais;
   - disparo de WhatsApp/webhook real;
   - CORS/auth permissivo demais;
   - migrations aplicadas no banco errado;
   - agentes navegando em telas com dados sensíveis.
7. Proponha uma arquitetura mínima:
   - ambiente dev/staging para Claude, QA e testes;
   - ambiente produção para piloto real;
   - contas de teste;
   - dados seed/sanitizados;
   - webhooks mockados/desativados no dev/staging.
8. Proponha a ordem de implantação com gates.

RELATÓRIO FINAL
- Classificação do estado atual: dev, pré-produção, staging ou produção.
- O que já está seguro.
- O que está arriscado.
- Plano mínimo recomendado.
- Checklist de implementação.
- O que é bloqueador antes de F2/F3.
- O que pode ficar para depois do piloto.
```

## Gate para avançar para F2/F3

- [ ] Estado atual dos ambientes classificado.
- [ ] Risco de banco/auth/webhooks reais documentado.
- [ ] Plano mínimo dev/staging/produção definido.
- [ ] Decisão explícita sobre conta de teste e dados seed/sanitizados.
- [ ] Regra de não mutar dados reais em QA registrada.

---

# Etapa de confiabilidade — antes de F2/F3

Após F1, pausar mudanças estruturais de design para criar proteção automática.

## Prompt 4 — testes visuais e fluxos críticos

- Criar testes E2E dos fluxos já existentes.
- Cobrir login, dashboard, conversas, pessoas e WhatsApp.
- Validar mobile e desktop.
- Não usar os testes para mudar comportamento do produto.

## Prompt 5 — deploy reproduzível

- Fechar Dockerfile, `.dockerignore`, `deploy/.env.example` e Compose.
- Não fazer deploy externo durante a correção.
- Buildar e testar a imagem dos três processos: backend, queue-worker e
  cron-worker.

## Prompt 6 — CI

- Backend: pytest.
- Frontend: typecheck, lint e build.
- Docker: validar Compose e build.
- Nenhum PR pode ser mesclado com gate vermelho.

---

# F2 — navegação

Só iniciar com F0/F1 mescladas e gates automáticos funcionando.

Recomendação de menor risco:

- manter a sidebar desktop aninhada, apenas mais limpa;
- preservar todos os `screenId`, hashes, deep-links e permissões;
- abas podem navegar para rotas existentes, não esconder permissões dentro de
  estado local;
- itens futuros permanecem marcados como “em breve”;
- não implementar telas extras do protótipo.

---

# F3 — mobile

- Bottom navigation: Hoje, Conversas, Pessoas, Jornada e Mais.
- Tabelas densas viram cards quando necessário.
- Modais ficam adequados à tela pequena.
- Áreas de toque com pelo menos 44px.
- Respeitar safe areas de iPhone e Android.
- Testar 375px, 768px e desktop.

---

# F4 — polimento e PWA

## Estado

- F4 investigada em modo read-only.
- F4 ainda não implementada.
- F0–F3 já estão mescladas e registradas.
- `origin/main` atual esperado antes da F4:
  `86c06dc2f54af9ad344166bb0ff56c7188946866`.

## Decisões F4 já tomadas

- **D1 — Redundância hambúrguer × Mais:** esconder o hambúrguer em viewport
  `<=860px`; manter "Mais" no bottom-nav como entrada do drawer; desktop
  permanece intacto.
- **D2 — PWA:** não implementar service worker/offline agora. F4 cobre apenas
  manifest, theme-color, ícones e add-to-home correto.
- **D3 — `theme_color`:** usar `#0b2c29`.
- **D4 — Contraste:** medir pares limítrofes e corrigir somente quando forem
  texto real que reprova AA. Não mexer em tokens decorativos.
- **D5 — Ícone:** sem asset final novo por enquanto; recolorir o ícone atual
  para a paleta Igreja 12. Não bloquear F4 por logo.

## Fora de escopo da F4

- Service worker/offline/cache.
- Nova feature de Assistente/chat.
- Mudança de rotas, `screenId`, `target`, permissões ou navegação funcional.
- Backend, auth, banco, migrations, RLS, workers ou produção.
- Registro de sprint no mesmo PR de código.

# PROMPT 6.0 — ENVIAR AGORA

## Implementar F4 — polish/PWA

**Conversa recomendada:** continuar na mesma conversa do Claude que investigou a
F4, porque ela já mapeou manifest, ícones, CSS e dívidas visuais.

```text
Go para implementar F4 — polish + PWA.

Use as decisões abaixo:

D1 — Redundância hambúrguer × Mais:
- Esconder o hambúrguer em viewport <=860px.
- Manter “Mais” no bottom-nav como entrada do drawer.
- Desktop permanece intacto.

D2 — PWA:
- Não implementar service worker/offline agora.
- Fazer apenas manifest, theme-color, ícones e add-to-home correto.
- SW/offline fica fora da F4.

D3 — theme_color:
- Usar #0b2c29.

D4 — Contraste:
- Medir os pares limítrofes.
- Corrigir somente se forem texto real e reprovarem AA.
- Não mexer em tokens decorativos que não são texto.

D5 — Ícone:
- Não há asset final novo agora.
- Recolorir o ícone atual para a paleta Igreja 12.
- Não bloquear F4 por logo.

Regras:
- Antes de criar branch, confirme o SHA atual de origin/main.
- Criar branch nova `feat/redesign-f4-polish-pwa` a partir do origin/main atual.
- PR da F4 deve ser draft.
- F4 é 100% frontend/apresentação.
- Não tocar backend, auth, banco, migrations, RLS, workers ou produção.
- Não alterar `permissions.ts`, `navigation.ts`, `canSee`, `LOCKED_SCREENS`,
  `OWNER_ONLY`, `screenId` ou `target`.
- Não implementar service worker.
- Não iniciar nenhuma nova fase.
- Não registrar sprint em `docs/sprints` neste PR. Registro docs virá depois do
  merge, em PR separado.

Escopo autorizado:
1. PWA/theme:
   - atualizar `frontend/public/manifest.webmanifest`;
   - atualizar `themeColor` em `frontend/src/app/layout.tsx`;
   - trocar cores antigas da identidade pré-F0 pela paleta Igreja 12;
   - usar `#0b2c29` como theme-color dark.
2. Ícones:
   - recolorir `frontend/public/icon.svg` e `icon-maskable.svg`;
   - gerar PNGs necessários para PWA/add-to-home, incluindo apple-touch 180,
     192 e 512, sem depender de asset novo.
3. Mobile polish:
   - esconder `.menu-toggle` em `<=860px`;
   - manter bottom-nav e “Mais” como entrada do drawer;
   - desktop intacto.
4. Motion/a11y:
   - adicionar `prefers-reduced-motion` para reduzir/desligar fade/transições
     globais relevantes.
5. Micro-polish:
   - ajustar apenas detalhes baratos e seguros de raios/transições/posicionamento
     de `.module-tabs`, se o diff permanecer pequeno.
6. Contraste:
   - medir pares limítrofes (`--faint`, `--sidebar-muted` e semelhantes);
   - alterar somente texto real que reprovar AA;
   - registrar no relatório o que foi medido e o que ficou inalterado.

Gates:
- typecheck, lint e build verdes.
- CodeGraph/detect_changes sem fluxo backend.
- Diff limitado a frontend/public, layout/head e CSS/apresentação.
- Invariantes intactos: `permissions.ts`, `navigation.ts`, `canSee`,
  `LOCKED_SCREENS`, `OWNER_ONLY`, `screenId`, `target`.
- Smoke staging:
  - backend staging `:8001`, `APP_ENV=staging`, `ALLOW_REAL_SENDS=false`;
  - frontend `:3000`;
  - produção `:8000` nunca alvo;
  - sem workers;
  - theme-color/manifest não usam mais `#1b2526`;
  - ícones/manifest apontam para assets novos/corretos;
  - hambúrguer some em mobile `<=860px`;
  - "Mais" abre o drawer;
  - desktop mantém comportamento atual;
  - `prefers-reduced-motion` reduz motion;
  - 0 outbound real, 0 banco/prod tocado.

Relatório final:
- branch;
- SHA base;
- arquivos alterados;
- decisões aplicadas;
- medições de contraste;
- validações executadas;
- resultado do smoke staging;
- confirmação de que backend/produção/banco/workers não foram tocados;
- PR draft criado.
```

## Próximo passo depois do merge da F4

Registrar sprint F4 em `docs/sprints` em PR separado, docs-only, mantendo o
mesmo padrão usado em F1/F2/F3.

---

# Fechamento do trabalho

- Staging atualizado com todas as migrations.
- Teste com dois tenants para isolamento.
- WhatsApp real ponta a ponta.
- Login, recuperação, convite e billing validados.
- HTTPS, firewall, CORS e secrets revisados.
- Piloto com uma igreja real.
- Registrar feedback antes de abrir features futuras.
