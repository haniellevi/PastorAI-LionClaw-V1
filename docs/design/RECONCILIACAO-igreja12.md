# Reconciliação do design Igreja12 × código atual

> Contrato de engenharia do redesign (#8). Origem: protótipo `Igreja12-Prototipo.standalone.html` (Claude Designer), reconciliado contra `frontend/src/app/globals.css` e `frontend/src/lib/navigation.ts` em 2026-06-24 via workflow (extrair → sintetizar → verificar adversarial). Veredito: **reskin/restyle das mesmas telas** — Claude Code incremental, NÃO LionClaw. Os PRs F0–F4 conferem contra este doc.

## Identidade (o que o design define)

- **Cor:** teal `#0d9488` (primário/ação, mais **saturado** que o atual) + verde-petróleo escuríssimo `#0f3a36` (texto e superfície dark) sobre fundo **verde-branco frio** `#eef3f2`. Acento vivo = mint `#5eead4` (estados ativos na sidebar dark + logo). **Inverte a temperatura do app de quente (matiz ~90) para fria (~175).**
- **Tipografia:** **Sora** (display: títulos, KPIs, botões, logo — pesos 700/800) + **Plus Jakarta Sans** (corpo) + **JetBrains Mono** (dados). Hoje é tudo system-ui. → 3 webfonts novas.
- **Forma:** muito mais **arredondado e suave** — botões/pílulas 11px, cards 14-16px, containers 18px, pílulas stadium 20-30px; **sombras coloridas** (lift teal do botão primário `0 8px 20px rgba(13,148,136,.3)`), **focus ring teal**, **gradientes de marca** (login/sidebar radial verde-petróleo; logo teal→mint). Hoje é flat/hairline.
- **Estágios G12 (cores-assinatura) — INVERTEM:** Ganhar verde→**rose `#fb7185`**, Consolidar azul→**âmbar `#d97706`**, Discipular âmbar→**emerald `#0e9f6e`**, Enviar laranja→**indigo `#6366f1`**. Cada um com um par *soft* claro para pílulas/dots.

## Mapa de tokens (`:root` do globals.css)

| Token atual | Valor (≈ oklch) | Vira (design) | Ação | Nota |
|---|---|---|---|---|
| `--accent` | teal dessat. `52% .078 195` | `#0d9488` ≈ `60% .11 184` | **swap** | teal vivo; atualizar hover hardcoded do `.btn-primary` |
| `--accent-soft` | `95% .025 195` | `#e6f5f3` ≈ `96% .02 184` | swap | realinhar matiz |
| `--bg` | off-white quente `98.6% .003 95` | `#eef3f2` ≈ `96.5% .006 175` | **swap** | **inverte a temperatura do app** (quente→frio) |
| `--surface` | branco | `#ffffff` | keep | — |
| `--surface-2` | `97% .004 95` | `#f6f9f8` ≈ `97.5% .004 175` | swap | matiz frio |
| `--sidebar` | zinc-azul `21% .012 200` | base `#0b2c29` ≈ `20% .03 175` | **swap** | vira **gradiente** (ver `--grad-sidebar`); cor é só fallback |
| `--sidebar-fg` | `86% .01 200` | `#cfe4e1` ≈ `89% .02 175` | swap | ativo = mint (token novo) |
| `--sidebar-muted` | `64% .015 200` | `#6f928d` ≈ `60% .03 175` | swap | — |
| `--fg` | tinta quente `24% .01 90` | `#0f3a36` ≈ `31% .04 175` | **swap** | texto vira verde-petróleo |
| `--muted` | `52% .012 90` | `#3c4f4c` ≈ `45% .02 175` | swap | — |
| `--faint` | `64% .01 90` | `#9aa8a5` ≈ `64% .012 175` | swap | — |
| `--border` | `91% .005 95` | `#e8efed` ≈ `94% .006 175` | swap | borda-identidade, frio |
| `--border-strong` | `86% .006 95` | `#d6e3e0` ≈ `90% .01 175` | swap | — |
| `--ok` / `--ok-soft` | `56% .09 155` | `#16a34a` / `#dcfce7` | swap | mais saturado; **≠ estágio Discipular** (ver conflitos) |
| `--warn` / `--warn-soft` | `64% .11 75` | `#d97706` / `#fef3c7` | swap | **≠ estágio Consolidar** apesar do mesmo valor |
| `--danger` / `--danger-soft` | `56% .13 25` | `#dc2626` / `#fef2f2` | swap | — |
| `--r-sm` | 6px | 10px | swap | app mais arredondado |
| `--r-md` | 10px | 12px | swap | — |
| `--r-lg` / `--r-xl` | 14 / 20px | 14-16 / 18-20px | keep | já casa |
| `--font` | system stack | `'Plus Jakarta Sans', system-ui` | **swap** | carregar webfont |
| `--mono` | já lista JetBrains | `'JetBrains Mono', …` | keep | carregar webfont p/ glifo idêntico |
| `--st` ganhar | verde `76% .15 150` | rose `#fb7185` | **swap** | inversão de matiz |
| `--st` consolidar | azul `74% .12 225` | âmbar `#d97706` | **swap** | inversão |
| `--st` discipular | âmbar `81% .13 80` | emerald `#0e9f6e` | **swap** | inversão |
| `--st` enviar | laranja `73% .16 38` | indigo `#6366f1` | **swap** | inversão |

## Tokens novos (não existem hoje)

| Token | Valor | Porquê |
|---|---|---|
| `--accent-dark` | `#0f766e` | hover/gradiente do primário (hoje hardcoded) |
| `--accent-bright` (mint) | `#5eead4` | estado ATIVO da nav na sidebar dark + logo |
| `--font-display` | `'Sora', var(--font)` | headings/KPIs/botões/logo |
| `--grad-brand` / `--grad-brand-mint` | `135deg #0d9488→#0f766e` / `→#5eead4` | marca em banners/avatares/logo |
| `--grad-sidebar` | `radial #0f3a36→#0b2c29→#082220` | fundo da sidebar/login (não é cor chapada) |
| `--shadow-primary` | `0 8px 20px rgba(13,148,136,.3)` | lift colorido do botão primário |
| `--ring` | `0 0 0 3px rgba(13,148,136,.12)` | focus ring teal |
| `--urgent` / `--urgent-soft` | `#e11d48` / `#ffe4e6` | atrasado/vencido (≠ erro) |
| `--info` / `--info-soft` | `#0284c7` / `#e0f2fe` | estado informativo (azul) — não existe hoje |
| `--whatsapp` (+ soft `#1faa55`) | `#25d366` | canal WhatsApp (dot/badge **e** ícone de nav) |
| `--gold-plan` | `#d4af37` | selo de dono/plano (reforça a feature #4) |
| `--surface-3` | `#f1f5f4` | 2º nível de superfície sutil |
| `--border-2` / `--border-teal` | `#e2e9e7` / `#cfe3df` | divisor extra / contorno de botão-fantasma teal |
| `--st-*-soft` (4) | tints brilhantes (`#fbbf24`,`#34d399`,…) | **cada estágio precisa do par fg+soft** (pílulas/dots) |
| `--r-xs` / `--r-container` | 5px / 18px | micro-elementos / containers de topo |

## Tabela de escopo

| Área | Tipo | Esforço | Nota |
|---|---|---|---|
| Cor / neutros+acento+estados | troca de token | **alto** | reescrever `:root` **+ re-derivar TODOS os `oklch(… 200)` e `(… 90/95)` hardcoded** (a sidebar dark inteira usa literais matiz 200 que não esfriam só trocando `--sidebar`) |
| Cor / estágios G12 | troca de token | baixo | trocar 4 `--st` + criar 4 `--st-*-soft` |
| Cor / tokens novos | estrutural | médio | linhas novas no `:root` + aplicação pontual |
| Tipografia | ambos | **alto** | 3 webfonts via `next/font`; `--font-display` em h1-h4/.val/botões; risco FOUT/métricas |
| Forma / raios | troca de token | baixo | subir `--r-sm`/`--r-md` |
| Forma / sombras+gradientes | ambos | médio | `--shadow-primary`/`--ring`/3 gradientes; sidebar vira gradiente |
| Componentes | troca de token | baixo | quase tudo já consome var; tocar à mão os hardcoded |
| Navegação desktop | estrutural | alto | achatar (decisão de produto) — **preservando screenId** |
| Navegação mobile | estrutural | alto | bottom-nav + drawer (componente novo) |
| Mobile-first telas densas | estrutural | alto | data-table/grids → padrão mobile |

## Navegação — a verdade (corrigida pela verificação)

⚠️ **A síntese afirmou "nenhuma rota/screenId muda — regra dura preservada". É FALSO como estava.** O real:

1. **Labels diferentes (cosmético, trivial):** o design chama `pessoas`/`agenda`/`comunicacao`/`usuarios`/`arvore`; o app roteia por `contatos`/`calendario`/`comunicados`/`equipe`/`g12`. **Solução = manter o screenId, trocar só o label** (já fazemos isso — `contatos` exibe "Pessoas"). Não-quebrante.
2. **Consolidação de sub-views em ABAS (decisão real de produto):** o design embute `consol-individual`/`universidade-vida` como abas de **Consolidar** e `capacitacao`/`central-celula` como abas de **Discipular**. O app tem esses como **screenIds separados**. → **Não há caminho "sem tocar rota automático".** Duas opções:
   - **(a) recomendada:** manter os screenIds atuais e cada aba **navega por hash** para o screenId existente (`#consol-individual` etc.) — preserva `canSee`/`LOCKED_SCREENS`/matriz `role_permissions`/deep-link.
   - (b) migrar para o modelo de abas do design e reescrever `permissions.ts` + deep-links (mais caro/arriscado).
3. **Sidebar flat vs nested:** o design é lista plana (headers + links); o app é seções colapsáveis + estágios aninhados. Achatar é **decisão de produto** (remove collapse/expand). Alternativa de menor risco: manter o nested só **reskinado**.
4. **Mobile = bottom-nav + drawer** (corrige o que eu disse antes — o design **tem** bottom-nav: Hoje/Conversas/Jornada/Mais, "Jornada"=atalho p/ `#ganhar`, "Mais"=drawer). Atalhos apontam para screenIds existentes; "Jornada"/"Hoje"/"Mais" **não viram rota**.
5. **Locked/em breve:** ambos mostram cadeado → **manter visível** (confirma decisão #3); só padronizar o glifo (cadeado, não a ampulheta ⌛ atual).
6. **Preservar:** `OWNER_ONLY` de `#assinatura` (feature #4 — o design não modela dono); a superfície **Master/console** fica **separada** (o design a desenha junto, mas é Onda 1 fora do MVP).

**Fora de escopo (telas do design sem screenId no app):** `minhacelula`, seção `admin` (visão/secretaria/financeiro/ministérios), `master`/`master-prov`, e fluxos `planejar`/`realizar`/`encontro`/`onboarding`/`cadcelula`/`treino`. O reskin **ignora** essas — ou o escopo cresce. Não criar screenIds novos sem necessidade.

## Conflitos / cuidados (da verificação adversarial)

| Conflito | Sev. | Mitigação |
|---|---|---|
| Estágio Consolidar `#d97706` == `--warn`; Discipular `#16a34a` ≈ `--ok` | **alta** | **tokens SEPARADOS** mesmo com valor igual — nunca referenciar `--warn`/`--ok` dentro de estilo de estágio |
| (verif. F0) Colisão byte-idêntica também em Ganhar `--st-soft` == `--urgent-soft` e Consolidar **base** `--st` == `--warn` (não só o *soft*); `--warn`-texto subiu p/ L 66.6% sobre branco (limítrofe AA) | média | mesma regra: **tokens SEPARADOS** — a F0 **já cumpre** (`.stage` só consome `--st`, nunca `--warn`/`--urgent`; os `--st-soft`/`--urgent` ainda sem consumidor). Desfazer as colisões + medir contraste do `--warn` na F1/F4 **antes** de qualquer selo de estágio em superfície clara |
| Abas do módulo viram estado interno → quebra permissão/deep-link | **alta** | abas **navegam por hash** para o screenId existente (opção a) |
| Inversão das cores de estágio é mudança de **significado** | média | trocar os 4 de uma vez + revisar toda superfície de estágio; **confirmar com o usuário** que o mapa (Ganhar=rose, Enviar=indigo) é o canônico |
| `oklch` hardcoded ≫ 6 (sidebar dark inteira em matiz 200) | média | inventariar TODOS e re-derivar p/ matiz ~175 ou promover a `var()`/`color-mix` → **F0 cor é esforço ALTO** |
| Estágios/estados/canais têm **par fg+soft**, não valor único | média | criar `--st-*-soft`, `--whatsapp-soft`, etc. |
| 3 webfonts aumentam bundle/LCP, mudam métricas | média | `next/font` self-host, `display:swap`, subset latin, só pesos usados; medir LCP mobile |
| Owner-only de `#assinatura` ausente no design | baixa | preservar `OWNER_ONLY`; usar `--gold-plan` p/ reforçar o dono |

## Plano de 5 fases (atualizado)

- **F0 — tokens (esforço ALTO):** reescrever `:root` com os swaps + adicionar todos os tokens novos + criar `--st-*-soft` + **caçar e re-derivar todos os `oklch` hardcoded** (sidebar dark em matiz 200 inclusa). PR único de tokens que propaga para quase tudo. *Independe das decisões de nav.*
- **F1 — identidade:** 3 webfonts via `next/font`; `--font-display`(Sora) em headings/KPIs/botões/logo; gradientes de marca em logo/sidebar/login; `--shadow-primary`/`--ring`; selo dourado do dono; pílula WhatsApp. As cores de estágio (`--st` + `--st-*-soft`) **já vivem como tokens da F0** — a F1 **apenas aplica a identidade nos componentes** (pílulas/dots/barras de estágio que consomem esses tokens), **sem mudança de valor na F1**. *Independe das decisões de nav.*
- **F2 — navegação (decisões de produto):** achatar a sidebar **ou** manter nested+reskin; abas de módulo (se adotadas, **navegam por hash** p/ screenIds existentes); padronizar glifo locked. **Preservar todos os screenId/target.**
- **F3 — mobile-first:** bottom-nav (Hoje/Conversas/Jornada/Mais) + drawer; revisar densidade de data-table/grids; opcional painel "Assistente".
- **F4 — polish + PWA:** micro-raios, transições, contraste AA dos novos pares (mint sobre dark), tema/ícones PWA p/ Igreja12.

## Decisões pendentes (gateiam a F2, NÃO a F0/F1)

1. **Sidebar:** achatar (como o design) ou manter nested só reskinado?
2. **Abas de módulo:** adotar (navegando por hash) ou manter sub-telas no menu?
3. **Bottom-nav mobile:** adotar o do design?
4. **Painel "Assistente":** entra agora (é uma feature de chat, não só botão) ou fica pra depois?
5. **Confirmar** que a inversão das cores de estágio (Ganhar=rose, Consolidar=âmbar, Discipular=emerald, Enviar=indigo) é intencional.

**F0 + F1 podem começar já** — são reskin fiel ao design e não dependem de nenhuma decisão de nav.
