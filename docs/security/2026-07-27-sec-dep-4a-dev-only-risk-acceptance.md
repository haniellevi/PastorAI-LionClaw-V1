# Aceitação temporária de risco — residual dev-only da PR #210 (SEC-DEP-4A)

- **ID:** SEC-DEP-4A-RISK-001
- **Data:** 2026-07-27
- **PR:** [#210](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/210) — `fix(deps): SEC-DEP-4A — atualizações dev-only dentro dos ranges (js-yaml, brace-expansion, @types/node)`
- **SHA da PR:** `4e265f8` · **base:** `origin/main` @ `0de9da9`
- **Escopo:** cadeia de lint, declarada como dependência de desenvolvimento. **Não** entra no artefato publicado nem na árvore de runtime — não é alcançável por painel, API, banco ou login em execução. **Ressalva explícita:** `frontend/next.config.mjs` não define `eslint.ignoreDuringBuilds`, então `next build` executa o ESLint (a saída do build traz `Linting and checking validity of types ...`). A expansão vulnerável roda, portanto, **no processo** que produz o build de produção — não no código servido por ele.
- **Tipo deste documento:** registro versionado de decisão. **Docs-only — não implementa correção e não altera o residual.**
- **Não altera:** `docs/security/2026-07-08-seg-igreja12-remediation-plan.md` nem `docs/security/2026-07-18-sec-baixo-revalidacao.md`.

---

## 1. Residual exato

| Campo | Valor |
|---|---|
| Advisory | [GHSA-mh99-v99m-4gvg](https://github.com/advisories/GHSA-mh99-v99m-4gvg) |
| Título | `brace-expansion`: DoS via expansão sem limite de tamanho, causando crash do processo por falta de memória |
| Pacote | `brace-expansion` **1.1.16** (`frontend/node_modules/brace-expansion`) |
| Faixa vulnerável | `<= 5.0.7` |
| Cadeia de alcance | `minimatch@3.1.5` → `eslint@8.57.0` / `eslint-config-next@15.5.22` |
| Severidade (npm/GitHub) | **high** |
| Escopo real | **dev-only** — ausente da árvore de runtime e do bundle publicado; executa no lint e no processo de `next build` (ver §2) |
| `npm audit --omit=dev` | **0** (antes e depois da PR #210) |

O que a PR #210 **fechou**, para delimitar o que sobrou:

- `GHSA-52cp-r559-cp3m` (`js-yaml` → 4.3.0);
- `GHSA-3jxr-9vmj-r5cp` (`brace-expansion`, **nas duas** instalações: 5.0.8 e 1.1.16);
- `GHSA-mh99-v99m-4gvg` **na linha 5.x** (`brace-expansion` 5.0.8, sob `minimatch@10.2.5`).

Sobrou apenas o `GHSA-mh99-v99m-4gvg` na linha **1.x**.

**Leitura correta do `npm audit`.** Depois da PR, o comando imprime *13 pacotes high*. Não são 13 vulnerabilidades: é **1 advisory**, com advisory próprio somente em `brace-expansion`; as outras 12 entradas (`minimatch`, `eslint`, `eslint-config-next`, `eslint-plugin-import`, `eslint-plugin-jsx-a11y`, `eslint-plugin-react`, `@eslint/eslintrc`, `@humanwhocodes/config-array`, `file-entry-cache`, `flat-cache`, `glob`, `rimraf`) têm `via` do tipo string — são a mesma falha vista pelos dependentes. A verificação é feita inspecionando os objetos `via` de `npm audit --json`. Sem isso, o número 13 lê como explosão de findings e produz falso alarme.

---

## 2. Modelo de risco

**O que a falha permite.** Um padrão de chaves (`{a,b}`) hostil, ao ser expandido, gera um resultado de tamanho desproporcional ao texto de entrada. O processo que faz a expansão consome memória até ser interrompido. O efeito é **interrupção do processo**, não execução de código, não leitura de arquivo, não escalada de privilégio.

**Onde isso pode acontecer aqui.** `brace-expansion` 1.1.16 é alcançado por `minimatch@3.1.5`. No ESLint 8 instalado, `minimatch` é usado em dois lugares verificados:

- `@eslint/eslintrc/lib/config-array/override-tester.js:66,69` — casamento dos padrões `files`/`excludedFiles` de `overrides` na configuração. Este projeto tem um vetor presente: `eslint-config-next/index.js:96` declara `files: ['**/*.ts?(x)']`;
- `eslint/lib/cli-engine/file-enumerator.js:411` e `eslint/lib/eslint/eslint-helpers.js:162,261` — conversão em `Minimatch` dos alvos/globs passados na linha de comando.

Não afirmamos aqui que `.eslintignore` ou `ignorePatterns` passem por `minimatch`: isso não foi confirmado nesta versão e ficou fora do modelo.

**Quais processos executam essa cadeia.** (1) o lint local de quem desenvolve; (2) o passo de lint dentro do `next build` — inclusive o build de produção, onde quer que ele rode, já que `eslint.ignoreDuringBuilds` não está ligado. O CI **deste** repositório não exercita essa cadeia: `.github/workflows/backend-tests.yml` e `.github/workflows/rls-integration.yml` rodam com `working-directory: backend` e não executam lint nem build de frontend. Concretização exigiria que um padrão/glob controlado por terceiro chegasse a essa expansão.

**O que isso não é.** Não é vulnerabilidade alcançável pelo painel, pela API, pelo banco, pelo login ou por qualquer superfície servida: o pacote não está na árvore de runtime (`npm ls --omit=dev` não o lista) e não vai para o bundle publicado. `npm audit --omit=dev` = 0 confirma isso pelo lado do inventário. Isso vale para o **artefato**; o **processo** que o produz roda o lint, como descrito acima — e ali o efeito máximo é a interrupção do build, não um defeito no código servido.

**Limites desta avaliação.** Este documento **não** declara risco zero. A falha é real e a classificação *high* do advisory não está sendo contestada — o que está delimitado é a **superfície**: um processo de desenvolvimento, não um serviço exposto. Também **não** se assume que o ambiente de desenvolvimento seja privado ou confiável por definição: repositório, dependências, arquivos de configuração e conteúdo de PR de terceiros são vetores plausíveis de entrada de padrões, e é por isso que o gatilho 5 da §5 lista o uso do lint sobre padrões de fonte externa não confiável como motivo de reabertura **antes** do fato, não depois.

---

## 3. Por que não forçar a correção nesta PR

1. **O consumidor declara a faixa.** `minimatch@3.1.5` declara `"brace-expansion": "^1.1.7"`. O teto compatível dessa faixa é **1.1.16** — que já foi aplicado pela PR #210. Não existe patch dentro do range que feche o `GHSA-mh99-v99m-4gvg`.
2. **O patch está em outra major.** A correção do advisory exige `brace-expansion >= 5.0.8`, **fora** do `^1.1.7`.
3. **Override cruzando major quebraria o contrato do consumidor.** Forçar 5.x nessa árvore violaria o `^1.1.7` declarado por `minimatch` 3.x e entregaria ao ESLint 8 uma dependência que ele nunca declarou suportar — trocaria uma interrupção de processo por risco de quebra silenciosa da própria ferramenta que valida o código. Essa restrição também foi condição explícita da missão que originou a PR #210 ("é proibido forçar versão fora do range declarado pelo consumidor").
4. **A única saída apontada pelo npm é semver major.** O relatório traz `fixAvailable: {"name":"eslint","version":"10.8.0","isSemVerMajor":true}`.
5. **Trocar o stack de lint é missão separada.** Migrar para ESLint 9/10 ou substituir `eslint-config-next` muda regras, formato de configuração e possivelmente o resultado do lint em todo o frontend. Isso precisa de PR próprio, com gates próprios — não pode ser efeito colateral de uma PR de atualização de dependências cujo objetivo declarado era não mexer em nada além dos ranges já aceitos.

---

## 4. Decisão do dono

> **"Aceito temporariamente o residual dev-only da PR #210, com registro versionado e reabertura quando houver caminho compatível."**

Texto literal da decisão, registrado pelo dono em 2026-07-27 na missão SEC-DEP-4A-RISK-RECORD-1, que determinou a criação deste documento como registro versionado.

Alcance da aceitação, explicitamente delimitado:

- vale **somente** para o `GHSA-mh99-v99m-4gvg` em `brace-expansion` 1.1.16, alcançado pela cadeia `minimatch@3.1.5` → `eslint@8.57.0` / `eslint-config-next@15.5.22`;
- **não** se estende a nenhum outro finding, atual ou futuro, do mesmo pacote, da mesma cadeia ou de qualquer outra;
- **não** cria precedente para aceitar findings de runtime — a régua de runtime continua sendo `npm audit --omit=dev` = 0;
- é **temporária**: qualquer gatilho do item 5 a encerra e obriga reavaliação.

---

## 5. Reabertura obrigatória

Reabrir a análise assim que **qualquer** uma destas condições ocorrer:

1. **Correção compatível upstream na linha 1.x** — publicação de um `brace-expansion` 1.x que feche o `GHSA-mh99-v99m-4gvg` dentro de `^1.1.7`; ou alteração da faixa vulnerável da própria advisory que exclua a 1.1.16.
2. **A cadeia sair do `minimatch` 3** — qualquer atualização que faça a dependência passar a resolver por uma linhagem de `minimatch` já corrigida, tornando a correção alcançável sem override.
3. **`eslint-config-next` passar a suportar stack compatível mais novo** — abrindo caminho não-breaking para sair do ESLint 8.
4. **Missão planejada de atualização do stack ESLint** — quando ela existir, este residual entra no escopo dela por padrão.
5. **Antes de qualquer uso do lint sobre padrões fornecidos por fonte externa não confiável** — isto é, se passarmos a rodar lint com globs de linha de comando ou padrões `files`/`excludedFiles` de `overrides` vindos de terceiros (execução automática sobre conteúdo de PR externo, gerador de configuração a partir de entrada não confiável, ferramenta que monte padrões a partir de dado remoto). Vale também para adotar build ou lint automático sobre PR de origem externa, já que o `next build` dispara o ESLint. Este gatilho é **preventivo**: vale antes de adotar o uso, não depois de um incidente.

---

## 6. Critérios de encerramento

O SEC-DEP-4A-RISK-001 só é encerrado quando **os três** forem verdadeiros:

1. o residual for substituído por versão compatível — sem `override` cruzando major e sem forçar versão fora do range declarado pelo consumidor;
2. `npm audit --omit=dev` continuar em **0**;
3. os gates de frontend estiverem verdes no SHA que encerra: `npm ci`, `npm ls --all` (sem peer inválido), `npm ls --omit=dev`, `npm run typecheck`, `npm run lint`, `npm test -- --run` e `npm run build`.

Enquanto os três não forem satisfeitos, o item permanece aberto neste documento.

---

## 7. Evidências e método

Tudo abaixo foi reproduzido no worktree da PR #210, no SHA `4e265f8`:

- **Cadeia e faixas:** `npm explain brace-expansion` — duas instalações; `minimatch@3.1.5` declarando `^1.1.7` e `minimatch@10.2.5` declarando `^5.0.5`.
- **Advisory único:** contagem de objetos `via` distintos em `npm audit --json` → 1 (`GHSA-mh99-v99m-4gvg`), com advisory próprio apenas em `brace-expansion`.
- **Ausência do runtime:** `npm ls --omit=dev --all` — `brace-expansion`, `minimatch`, `js-yaml`, `@types/node`, `vite` e `undici-types` ausentes da árvore de produção.
- **Runtime limpo:** `npm audit --omit=dev --json` → `metadata.vulnerabilities` = `{"info":0,"low":0,"moderate":0,"high":0,"critical":0,"total":0}`.
- **Saída não-breaking inexistente:** `fixAvailable` do finding aponta `eslint@10.8.0` com `isSemVerMajor: true`.
- **Onde `minimatch` atua no ESLint 8:** `@eslint/eslintrc/lib/config-array/override-tester.js:66,69` (padrões `files`/`excludedFiles`) e `eslint/lib/cli-engine/file-enumerator.js:411` + `eslint/lib/eslint/eslint-helpers.js:162,261` (globs de linha de comando). Vetor presente na configuração: `eslint-config-next/index.js:96` → `files: ['**/*.ts?(x)']`.
- **Lint dentro do build:** `frontend/next.config.mjs` não define `eslint.ignoreDuringBuilds`; `npm run build` imprime `Linting and checking validity of types ...`.
- **CI não exercita a cadeia:** `.github/workflows/backend-tests.yml` e `.github/workflows/rls-integration.yml` usam `working-directory: backend`; nenhum job roda lint ou build de frontend.
- **Gates da PR:** `npm ci`, `npm ls --all` (exit 0), `npm ls --omit=dev`, `typecheck`, `lint`, 217/217 testes em 33 arquivos, `build` de produção, `git diff --check`. Detalhamento no corpo da PR #210.

Nenhum valor de segredo, token, credencial, endpoint interno ou dado operacional foi copiado para este documento (mesma política dos demais documentos de `docs/security/`).
