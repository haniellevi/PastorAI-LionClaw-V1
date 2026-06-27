# Redesign Igreja 12 — Ajustes de UX pós-F4

> **Fonte canônica** da onda de PRs corretivas de paridade visual + UX mobile que
> veio **depois** do redesign #8 (F0–F4).
> Continuação de [`RECONCILIACAO-igreja12.md`](RECONCILIACAO-igreja12.md) (o contrato F0–F4).
> Este é um **índice vivo** — recebe novas entradas conforme a onda avança.
> **Última atualização:** 2026-06-27 · **origin/main de referência:** `99716bf`.

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

As PRs dessa onda foram divididas em duas levas: **Onda 1 (#50–#56)** e **Onda 2 (#58–#64)** —
ambas mergidas em `origin/main` e deployadas em produção. O §3 cobre a Onda 1; a seção
[**Onda 2 — #58–#64**](#onda-2----58-64) cobre a segunda leva.

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

## 3. PRs — Onda 1 (#50–#56)

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

## Onda 2 — #58–#64

Fechou as pendências visuais listadas no §6 após a Onda 1 (superfícies, selects/modais,
Jornada G12, overflow de Enviar, contraste textual) e reordenou labels do menu de navegação.
Mesmos princípios e gates da Onda 1 (§2 e §5).

Todas **MERGED** em `origin/main` (`99716bf`) e **deployadas em produção**
(CSS/JS verificado no domínio público após cada deploy via CLI).

### PRs

| PR | Branch | Tema | Arquivo(s) | Decisão-chave | Risco controlado | Status |
|---|---|---|---|---|---|---|
| [#58](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/58) | `fix/design-surface-hierarchy` | Tokens de superfície — hierarquia visual | `globals.css` | Escada monotônica bg(94%) < surface-2(96.5%) < surface(100%); bordas e sombras reforçadas; `.topbar` troca cor hardcoded por `color-mix(var(--bg) 82%)` | Alcance global; hue/chroma da identidade Igreja 12 preservados; `--fg/--muted/--faint/--accent` intactos | MERGED + DEPLOYED |
| [#59](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/59) | `fix/pwa-bg-token` | Manifest PWA — background_color | `manifest.webmanifest` | `background_color` #eef3f2 → #ebf0ef — alinha splash do PWA ao novo `--bg` pós-#58 | JSON-only; `theme_color`, ícones e layout intactos | MERGED + DEPLOYED |
| [#60](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/60) | `fix/selects-modais-base` | Selects nativos + base de modal (PR1) | `globals.css` | `select` ganha chevron SVG do design system (appearance:none + SVG inline + padding-right); modal ganha `max-height`/`overflow-y`; alvo de toque ≥44px. **PR2** (bottom-sheet, Esc/focus-trap) fica de fora | Regra base `select` tem alcance global — smoke em 360/390/768/1024; nenhum TSX alterado | MERGED + DEPLOYED |
| [#61](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/61) | `fix/enviar-tabs-overflow` | Enviar — tabs/overflow mobile | `globals.css` | `.tab { white-space: nowrap }` + `flex-wrap` em `≤860px`; rótulos longos ("Sem agendamento", "Aptos a liderar") não quebram nem transbordam | `.tabs` melhora todas as telas com abas; `flex-wrap` só age com estouro — desktop inalterado | MERGED + DEPLOYED |
| [#62](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/62) | `feat/jornada-stepper` | Jornada G12 — stepper horizontal | `JourneyStepper.tsx` · `AppShell.tsx` · `navigation.ts` · `globals.css` | Stepper deriva de `NAV_SECTIONS` (fonte única); navega por `#hash` para `head.target` existentes; filtra por `canSee`; `firstVisibleTarget` resolve target navegável por etapa; fallback anti-render sem ativo | Componente novo `JourneyStepper.tsx`; BottomNav/Sidebar/ModuleTabs intocados; etapa sem target acessível = oculta | MERGED + DEPLOYED |
| [#63](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/63) | `fix/contraste-faint-muted` | Contraste textual fino (faint → muted) | `globals.css` | 10 classes promovidas `var(--faint)` → `var(--muted)` (≈7.3–8.7:1); `--faint` global **intacto**; `.lock-note` propositalmente fora (classe sobrecarregada) | CSS-only, sem tokens globais alterados; `.lock-note` → PR futura só se dor aparecer | MERGED + DEPLOYED |
| [#64](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/64) | `feat/menu-labels-agenda-ordem` | Menu — labels Gestão↔Igreja + Agenda após Painel | `navigation.ts` | `gestao.label` "Gestão"→"Igreja"; `igreja.label` "Igreja"→"Gestão"; `calendario` move de `igreja` para `gestao`, logo após `dashboard` | Só `label` e ordem; `screenId`, `target`, rotas e permissões **zero alteração** | MERGED + DEPLOYED |

### Decisões da Onda 2

#### Token `--faint` e contraste (#63)

- `--faint` **não alterado globalmente** (oklch L 72%, ≈2.07–2.46:1 em superfície).
- Uso correto de `--faint`: placeholder, texto desabilitado, ícones decorativos, separadores.
- **10 classes** promovidas para `--muted` (≈7.3–8.7:1, passa AA/AAA):
  `.panel-title .count`, `.stat .delta`, `.dash-today`, `.tile-sub`, `.kpi-hint`,
  `.ov-scope`, `.qbody .meta-line .resp`, `.tab .num`, `.org-leader .ol-count .cap`,
  `.conv-top time`.
- `.lock-note`: classe sobrecarregada (decorativo e status visível compartilham a mesma classe).
  Ficou em `--faint` por ora. **Só vira PR se dor real de leitura for reportada.**
  Candidato: modificador `.lock-note--info` que aplica `--muted` ao texto informativo em
  contextos como `TrackModal`.

#### Jornada Stepper (#62)

- Stepper horizontal acima do conteúdo nas telas da Jornada (e acima de `ModuleTabs` em
  Consolidar/Discipular).
- **Fonte única:** `NAV_SECTIONS` — mesma fonte da Sidebar e das ModuleTabs. Mudança no menu
  reflete automaticamente no stepper.
- **Navegação:** `#hash` para `head.target` existentes. Nenhuma rota nova criada; `screenId` e
  `canSee` preservados.
- **Sub-telas:** `journeyStageOf` mapeia para etapa pai (ex.: `consol-individual` → Consolidar;
  `g12/central-celula` → Discipular).
- **Edge de permissões resolvido (commit `9557990`):** `firstVisibleTarget` percorre cada etapa
  e devolve o primeiro target acessível (`head` se `canSee`, senão a primeira sub visível,
  pulando `locked`). Etapa sem nenhum target acessível = oculta. Fallback defensivo: se a
  etapa atual (`journeyStageOf`) não estiver na lista filtrada, stepper não renderiza — nunca
  aparece sem etapa ativa.

#### Menu labels e Agenda (#64)

- Reorganização **visual** de menu, zero impacto técnico.
- `gestao` (comunidade, pessoas, agenda) renomeado para **"Igreja"**.
- `igreja` (admin, configuração) renomeado para **"Gestão"**.
- `calendario` (Agenda) movido do grupo `igreja` para o grupo `gestao`, imediatamente após
  `dashboard` (Painel de Hoje).
- `screenId`, `target`, hash, rotas e permissões: **intactos**.

#### Deploy — padrão observado

Vercel não disparou build automático de forma confiável em merges diretos para `origin/main`.
Padrão adotado: **deploy manual via CLI em worktree limpo**. Resultado verificado por CSS/JS live
no domínio público após cada deploy. Monitorar recorrência antes de investir em workaround de CI.

---

## 6. Pendências atuais

### Resolvidas

| Item | Onda | PR |
|---|---|---|
| Superfícies / hierarquia visual | 2 | #58 |
| Manifest PWA background_color desatualizado | 2 | #59 |
| Selects — chevron + base modal (PR1) | 2 | #60 |
| Enviar — abas overflow mobile | 2 | #61 |
| Jornada G12 — stepper visual | 2 | #62 |
| Contraste `--faint` em texto informativo | 2 | #63 |
| Login + shell parity | 1 | #50 |
| Sidebar flat + topbar | 1 | #51 |
| Painel de Hoje | 1 | #52 |
| Conversas — densidade, master-detail, lista | 1 | #53–#55 |
| Pessoas — cards mobile | 1 | #56 |

### Abertas

- **Selects / Modais PR2:** bottom-sheet nativo, Esc/focus-trap — somente se sentido na prática.
- **Banner WhatsApp (PR B):** status admin-only via `fetchConnection` + contagem inbox-gated.
- **`.lock-note--info` / TrackModal:** modificador opcional para `.lock-note` com conteúdo
  informativo. Criar PR **apenas** se dor real de leitura for reportada.
- **Smoke em celular físico:** validar master-detail, drawer "Mais", BottomNav e stepper em
  device real (Android/iOS), não só harness ou emulador.
- **Itens sem `screenId` real** (não implementar até existir a tela): **Minha Célula**,
  **Árvore Ministerial**, **Gestão Administrativa**.
- **Deploy automático:** Vercel às vezes não dispara ao merge em `main`. Padrão atual = CLI
  manual em worktree limpo. Monitorar recorrência.
- **Repo principal local:** pode estar atrasado ou sujo — checar `git status` e
  `git log origin/main -3` antes de editar. `origin/main` é a fonte de verdade.
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
