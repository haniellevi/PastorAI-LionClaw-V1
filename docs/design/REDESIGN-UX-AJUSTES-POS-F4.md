# Redesign Igreja 12 — Ajustes de UX pós-F4

> **Fonte canônica** da onda de PRs corretivas de paridade visual + UX mobile que
> veio **depois** do redesign #8 (F0–F4).
> Continuação de [`RECONCILIACAO-igreja12.md`](RECONCILIACAO-igreja12.md) (o contrato F0–F4).
> Este é um **índice vivo** — recebe novas entradas conforme a onda avança.
> **Última atualização:** 2026-06-26 · **origin/main de referência:** `5f15e58`.

## 1. Contexto

O redesign #8 (fases **F0→F4**) está **encerrado** e mesclado em `origin/main` — ver
[`RECONCILIACAO-igreja12.md`](RECONCILIACAO-igreja12.md) (mapa de tokens, navegação, conflitos)
e os sprints `docs/sprints/2026-06-25-redesign-f0…f4-*.md`. Não há F5.

Ao rodar o app pós-F4, sobraram **divergências entre o protótipo `Igreja12-Prototipo.standalone.html`
e a tela real** + problemas de **usabilidade no mobile**. Esta onda (PRs **#50–#56**, todas
mescladas em 2026-06-26) trata **paridade visual e UX mobile**, **sem tocar regra de negócio**.

Diferença em relação ao F0–F4: aquilo foi um bloco planejado de 5 fases; **isto é uma sequência
de PRs corretivas pequenas e cirúrgicas**, cada uma escopada a uma tela/área. Por isso o registro
é um doc vivo, não um sprint-snapshot.

## 2. Princípios / gates duros (herdados do F0–F4)

Toda PR desta onda respeita:

- **Só apresentação.** Nada de backend, banco, migrations, **RLS**, **auth/Clerk**, **permissões**,
  `canSee`, **`screenId`**, hash routing, **rota**, workers, **env**, integrações externas.
- **Sem dado fake.** Deltas/badges do protótipo sem backing real (ex.: "+3 esta semana",
  badge "3") são **omitidos**; tiles caem para "—" quando a chamada falha (nunca `0` inventado).
- **Não inventar tela/rota.** Item do protótipo sem `screenId` real fica **pendente** — não se
  cria rota nova nem deep-link fantasma.
- **Blast-radius mínimo.** Mudança cirúrgica, preferindo CSS escopado.
- **Componentes compartilhados são escopados.** Estilo novo em componente reusado por N telas
  entra atrás de uma classe-flag opcional (ex.: `.people-cards`), nunca no seletor genérico.
- **QA visual baseado em evidência.** Screenshot/harness/breakpoint medido — **nunca "parece bom"**.

## 3. PRs da onda (#50–#56)

Todas **MERGED** em `origin/main` (`5f15e58`). Repo: `haniellevi/PastorAI-LionClaw-V1`.
**Deploy:** nenhuma destas PRs foi deployada por si — são merges em `main`; a produção precisa de
**redeploy** para refletir (ver observação do #50 sobre o build pré-F4 ainda em produção).

| PR | Branch | Tema | Status | Decisão-chave | Risco / observação |
|---|---|---|---|---|---|
| [#50](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/50) | `fix/design-parity-login-shell` | Login + shell parity Igreja 12 | MERGED | Login vira **card flutuante central** sobre fundo radial escuro + coluna teal; marca **"12"** (Sora 800) no login e na sidebar | CSS-first + 2 trocas mínimas de JSX. **Produção roda build pré-F4** (`apple-touch-icon` 404, `theme_color #1b2526`) → resolve com **redeploy**, não com código |
| [#51](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/51) | `fix/shell-menu-dashboard-parity` | Sidebar flat + topbar | MERGED | F2 deixa de ser "nested+reskin" e vira **flat como o protótipo** (grupos planos, sem accordion); bloco de ícone colorido por accent; eyebrow de grupo na topbar | Saldo **−216 linhas**. Itens sem screenId (Minha Célula / Árvore Ministerial / Gestão Administrativa) **omitidos** — não inventar rota |
| [#52](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/52) | `fix/dashboard-today-parity` | Painel de Hoje | MERGED | Hero (saudação+contagem) + tiles + card **"A jornada esta semana"** + fila pastoral, **só dado real**; `OverviewSection` sai do Painel | KPIs "Decisões por Jesus" / "Sem interesse (CSIM)" saíram com o Overview e foram **reencaixados** como faixa secundária (commit `000b34b`). **Banner WhatsApp fica para PR B** (admin-only + inbox-gated) |
| [#53](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/53) | `fix/inbox-mobile-css` | Conversas — densidade mobile (CSS) | MERGED | Composer usável no mobile; botões viram **só-ícone** (`aria-label`/`title` preservados); header não transborda | CSS-only + helper puro `messageTime()`. Corrige bug pré-existente: header reusava `.who`, escondido por `@media ≤860` |
| [#54](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/54) | `fix/inbox-mobile-master-detail` | Conversas master-detail mobile | MERGED | **Uma tela, uma tarefa** ≤860px: estado LISTA ou estado THREAD; botão voltar (‹); composer sticky acima do bottom-nav | Estado `isMobile` via `matchMedia`; **nenhuma lógica de envio/handoff alterada**. Desktop (>860) intacto, lado a lado |
| [#55](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/55) | `fix/inbox-list-minimal` | Lista de Conversas minimalista | MERGED | Lista deixa de parecer **planilha**; selecionado = `--accent-soft` + barra teal sutil; avatar teal-soft | **CSS-only** (+38/−12). Causa raiz: reset global de `button` não zera borda → topo/direita herdavam `outset` nativa |
| [#56](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/56) | `fix/people-mobile-cards` | Pessoas — cards mobile | MERGED | Cada pessoa = card com **cabeçalho próprio** (avatar+nome) + campos rotulados; modo card sobe ≤600→**≤768px** | `DataTable` é usada por **8 telas** → estilo escopado em `.data-table.people-cards` via prop opcional `className`; demais telas **intocadas** (commit `2b02d6d` reforça o escopo) |

## 4. Decisões de UX por área

### Login / shell (#50)
- Login = **card flutuante** (960px, radius 24, sombra) sobre fundo radial `#0f3a36→#0b2c29→#082220`;
  coluna esquerda em gradiente teal vivo `#0d9488→#0f766e→#0f3a36`.
- Marca textual **"12"** (Sora 800) substitui o glifo abstrato — no login **e** na sidebar.
- Mobile: coluna única, `aside` oculto ≤860. Olho de mostrar/ocultar senha preservado. Sem botões de demo.

### Sidebar / topbar (#51)
- **Sidebar FLAT** (decisão de produto): grupos com título, **sem accordion/expand** — abandona o
  "nested + reskin" que tinha sobrado em produção. Grupos: Gestão / A Jornada G12 / Igreja / Configuração.
- **Bloco de ícone arredondado colorido** (27×27) por accent: Ganhar=rosa, Consolidar=âmbar,
  Discipular=verde, Enviar=índigo, WhatsApp=verde-whats, demais=teal.
- Topbar com **eyebrow do grupo** ("GESTÃO" etc.) acima do título.
- Itens do protótipo **sem tela real** (Minha Célula, Árvore Ministerial, Gestão Administrativa)
  ficam **fora** até existir o `screenId` — regra dura "não inventar tela/rota".

### Painel de Hoje (#52)
- Hero: saudação "Bom dia/tarde/noite, {nome}" + "Você tem N ações… hoje" + data pt-BR.
- Tiles de overview (visitantes/consolidação/células/relatórios) clicáveis **só quando `canSee(rota)`**.
- Card **"A jornada esta semana"** (G12) **coexiste** com "Próximas ações por responsável"
  (`NextActions` preservado como bloco secundário).
- `OverviewSection` saiu do Painel (arquivo mantido no disco, reversível); KPIs **Decisões** e
  **CSIM** reencaixados como faixa secundária.
- **Banner WhatsApp = PR B futura** (status admin-only via `fetchConnection` + contagem inbox-gated) —
  nenhuma dessas chamadas foi adicionada aqui.

### Conversas (#53 → #54 → #55)
Sequência de 3 PRs, da densidade ao layout ao acabamento:
- **#53 (densidade):** input vira protagonista; botões Assumir/Devolver/Enviar só-ícone ≤860 com
  rótulo via `aria-label`/`title`; timestamps curtos (`messageTime` HH:MM, data completa no tooltip).
- **#54 (master-detail):** padrão de app de mensagens — **LISTA ou THREAD**, nunca empilhadas no
  mobile; botão voltar (‹); composer sticky acima do bottom-nav; `screen-head`/banners somem no THREAD
  para dar altura. Painel "Dados do contato" continua **drawer** (≤1100px), não vira coluna concorrente.
- **#55 (lista minimalista):** fim do efeito planilha; item selecionado com `--accent-soft` + barra teal;
  hierarquia de nome/preview/hora.

### Pessoas (#56)
- Cada pessoa = **card claro** no mobile: cabeçalho (avatar/iniciais + nome/telefone como título,
  **sem** o rótulo "Contato") separado do corpo; campos internos (Tipo/Célula/Estágio) com rótulo
  *muted* à esquerda e valor/chip à direita.
- Modo card sobe de **≤600px para ≤768px** (cobre celular + tablet retrato).
- **Escopo cirúrgico:** `DataTable` é compartilhada por 8 telas → estilo novo só em
  `.data-table.people-cards`; Ganhar/Consolidar/Relatórios/Equipe/Comunicados/AdminConsole **inalterados**.

### Dados reais / sem fake (transversal)
Todo elemento do protótipo sem fonte de dado real foi **omitido** (badges "3"/"2", deltas
"+3 esta semana", "2 com prazo hoje", "4/8"). Tiles caem para "—" em falha de chamada. Nunca `0` inventado.

### Mobile-first (transversal)
Cada tela densa recebeu um **padrão mobile próprio**: composer dominante (Conversas), master-detail
(Conversas), cards com cabeçalho (Pessoas), grids que colapsam para coluna única. Desktop sempre
preservado por `@media`.

## 5. Regras de QA visual

Como esta onda **valida** uma mudança visual antes do merge:

- **Breakpoints padrão:** 360 / 390–414 / 768 / 1024 (e 1440 quando relevante).
- **Sem overflow horizontal:** medir `scrollWidth == innerWidth` no harness.
- **Composer/elementos fixos** acima do bottom-nav (ex.: `footBottom ≤ navTop`).
- **Desktop sem regressão:** o `>860`/`≥769` precisa render igual ao anterior (lado a lado, tabela,
  botões com texto). Sempre verificar a regressão das telas vizinhas que compartilham componente.
- **Gates de código verdes** antes do merge: `npm run typecheck` · `npm run lint` · `npm run build`.
- **Contraste AA** medido de forma independente (oklch→sRGB linear→WCAG) em **texto essencial**.
- **Limitação declarada:** o shell autenticado exige **backend + Clerk + tenant**, então o smoke ao
  vivo (sessão real) raramente roda local. Quando não houver sessão real, a validação é feita com
  **harness/DOM/CSS real** (o `globals.css` do repo carregado num harness throwaway, fora do repo) —
  e isso é **declarado** na PR. Smoke autenticado real fica para **staging/preview de deploy**.
- **Nunca declarar "APTO visual" sem evidência** (screenshot, medição de breakpoint, ou comparação
  lado a lado protótipo × app). "Parece bom" não conta.

## 6. Pendências atuais

- **Superfícies / contraste global:** varredura dos rótulos suplementares ainda em `--faint`
  (~2.46:1, reprova AA) — `.stat .delta`, `.panel-title .count`, `.ov-scope`, `.qbody … .resp`.
  Decisão F4 foi "só texto essencial"; subir os secundários é polish futuro.
- **Enviar:** abas + forms (paridade visual ainda não feita).
- **Selects / forms:** padronização visual pendente.
- **Jornada G12:** paridade visual da tela de estágios.
- **Banner WhatsApp:** PR B do dashboard (status admin-only + contagem inbox-gated).
- **Itens sem `screenId` real** (não implementar até existir a tela): **Minha Célula**,
  **Árvore Ministerial**, **Gestão Administrativa**.
- **Smoke autenticado mobile real** (drawer via "Mais", `collapse-btn` ≤860) em staging.
- **Repo principal local atrasado/sujo:** o worktree principal estava ~48 commits atrás de
  `origin/main` e com `globals.css` editado/não-commitado + `globals.css.bak`. **Não usar** esse
  worktree para editar — reconciliar antes. `origin/main` é a fonte de verdade.
- **CodeGraph como apoio, não fonte única** (ver §7).

## 7. Notas de rastreabilidade

Camadas de memória deste projeto e o papel de cada uma:

- **`docs/sprints/`** = **snapshots** versionados ("o que fizemos e por quê", por bloco). Não muda
  depois de escrito. Cobre F0–F4 + B1/B2.
- **Este doc** (`docs/design/REDESIGN-UX-AJUSTES-POS-F4.md`) = **índice vivo da onda UX pós-F4**.
  Recebe novas entradas conforme as próximas frentes (§6) forem fechando.
- **GitHub PRs (#50–#56)** = **detalhe completo** (antes/depois, diff, gates, smoke). É a fonte
  granular, mas **não** deve ser a única memória — por isso este doc existe.
- **Memória local do Claude** (`~/.claude/.../memory/`) = anotações **voláteis / por máquina**, não
  portáveis e sujeitas a ficar stale. Útil para continuidade entre conversas, **não** é registro canônico.
- **CodeGraph (code-review-graph)** = grafo estrutural, ótimo para impacto/`detect_changes` durante
  uma revisão. Roda via **hook git-level em commits** e pode **atualizar incrementalmente** (observado
  no commit desta PR: `Incremental: 4 files updated, 9 nodes, 177 edges`). No **Windows** há um **erro
  cosmético de encoding** (`UnicodeEncodeError` cp1252) ao **imprimir o painel** — que ocorre **depois**
  de o índice já ter sido atualizado, ou seja, é falha de **output no console**, não de indexação.
  Ainda assim, CodeGraph é **ferramenta de apoio**: a fonte canônica versionada é **este documento +
  PRs/sprints**, nunca o grafo sozinho.

**Regra prática:** uma mudança de UX só está "registrada" quando está **neste doc** (resumo +
decisão) **e** na PR (detalhe). GitHub sozinho ou memória local sozinha não bastam.
