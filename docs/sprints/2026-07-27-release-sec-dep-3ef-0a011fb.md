# Release de segurança do frontend (SEC-DEP-3E/F) — `0a011fb` — 2026-07-27

**Branch:** `main` (merges das PRs #205, #206 e #207) · **Commit publicado:** `0a011fbdbdf7d6951683cca2e4f0f86a913aa897` · **Deploy:** SIM — frontend em produção (2026-07-27) · **Migration:** não

> Escopo deste registro: fato do release e das verificações abaixo. Não inclui
> credencial, token, chave, endereço de rede, caminho de servidor ou valor de
> variável de ambiente.

## Código mergeado

Três PRs de dependência, mergeadas em `main` em sequência estrita, cada uma por
merge commit real de 2 pais (sem squash, sem rebase; branches preservadas):

| PR | Escopo | Merge commit | Mergeada em |
|---|---|---|---|
| [#205](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/205) | `fix(deps): postcss 8.5.10 override (SEC-DEP-3C)` | `42e64a8e98356a41bd022b3c2d39185ffa596095` | 2026-07-22 |
| [#206](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/206) | `fix(frontend): override sharp 0.35.3 for libvips advisory (SEC-DEP-3D)` | `e93dde93eee0e70bc95205436d5ba922cfae363f` | 2026-07-27 |
| [#207](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/207) | `fix(deps): Next 15.5.22 + PostCSS 8.5.23 — fecha 2 advisories high de runtime (SEC-DEP-3E)` | `0a011fbdbdf7d6951683cca2e4f0f86a913aa897` | 2026-07-27 |

Encadeamento verificado no grafo de `origin/main`:
`42e64a8` → `e93dde9` → `0a011fb`, sendo `0a011fb` a ponta atual de `origin/main`.
O override de PostCSS introduzido pela #205 (`8.5.10`) foi elevado para `8.5.23`
pela #207 — o valor publicado é o da #207.

**Os três PRs chegaram juntos nesta publicação de produção.** Nenhum deles havia
sido publicado isoladamente: #205 permaneceu mergeada em `main` sem deploy desde
2026-07-22, e #206 e #207 foram mergeadas no mesmo dia da publicação. O
deployment de 2026-07-27, no SHA `0a011fb`, entregou o conteúdo dos três de uma
única vez.

## Versões publicadas

Estado verificado em `frontend/package.json` e `frontend/package-lock.json` no
commit `0a011fb`:

| Pacote | Versão | Origem |
|---|---|---|
| `next` | `15.5.22` | dependência direta |
| `eslint-config-next` | `15.5.22` | devDependency |
| `react` / `react-dom` | `19.2.7` | dependências diretas |
| `@clerk/nextjs` | `6.39.6` | dependência direta |
| `postcss` (sob `next`) | `8.5.23` | `overrides.next.postcss` |
| `sharp` (sob `next`) | `0.35.3` | `overrides.next.sharp` |
| libvips | `8.18.3` | binários `@img/sharp-libvips-*` `1.3.2`, exigidos por `sharp@0.35.3` (`config.libvips: ">=8.18.3"`) |

Os dois overrides são **escopados a `next`** (bloco `overrides.next`), não
globais — não alteram resoluções de outras árvores de dependência.

## Segurança

- **Audit de runtime antes**: 2 pacotes com severidade **high**.
- **Audit de runtime final**: `npm audit --omit=dev` → **0 vulnerabilidades**
  (reconferido sobre o lock de `origin/main` nesta sessão).
- Advisories de **Next**, **PostCSS** e **Sharp/libvips** fechados no runtime.
- **Nenhum `npm audit fix` foi executado** em nenhuma das três PRs — todas as
  mudanças foram bumps e overrides explícitos, revisáveis linha a linha.

### Findings dev-only — fora desta release

`npm audit` completo (incluindo `devDependencies`) ainda aponta 2 pacotes high,
ambos exclusivos da cadeia de ferramentas de desenvolvimento e ausentes do
bundle de produção:

- `brace-expansion` (`<=5.0.7`) — DoS por expansão exponencial / OOM
  (`GHSA-3jxr-9vmj-r5cp`, `GHSA-mh99-v99m-4gvg`); alcançado via
  `@typescript-eslint/typescript-estree`.
- `js-yaml` (`4.0.0 - 4.2.0`) — consumo quadrático de CPU via cadeias de
  merge-key (`GHSA-52cp-r559-cp3m`).

Peer dependency dev-only **pré-existente**, não introduzida por esta release:
`@types/node 20.14.10` está fora do range pedido pelo `vite 8.1.3` (trazido por
`vitest`, dev-only).

Esses três itens são **follow-ups separados**, não runtime de produção, e não
bloqueiam esta release.

## Deploy

- **SHA publicado**: `0a011fbdbdf7d6951683cca2e4f0f86a913aa897`
- **Deployment**: `dpl_GYpYmkyv78u6vjrC1AhYyEtnkARU`
- **Target**: `production` · **Status**: `READY`
- **Aliases promovidos**: `app.igreja12.com.br`, `admin.igreja12.com.br`,
  `painel.igreja12.com.br`
- **Rollback primário preservado**: deployment `dpl_CC3DQiA7GJWUnaDFSjmRnTXsT858`
  (imediatamente anterior, mantido disponível para promoção).

**Backend, banco de dados, migrations, ambiente DEV e variáveis de ambiente não
foram alterados nesta release.** O diff publicado é restrito a
`frontend/package.json` e `frontend/package-lock.json`.

## Smoke público (read-only, sem autenticação)

| Domínio | Rota | Resultado |
|---|---|---|
| App | `/` | HTTP **200** |
| Admin | `/gestao` | HTTP **200** |
| Painel | `/admin` | HTTP **200** |

- HTML não vazio nas três respostas.
- **Zero respostas 5xx.**
- Image optimizer do Next exercitado: HTTP **200**, `content-type: image/png`,
  **1150 bytes** — prova que o pipeline `sharp` 0.35.3 / libvips 8.18.3 responde
  em produção.

## Smoke autenticado — verificação externa pelo Codex

Executado em **sessão separada, pelo Codex**, após a publicação em produção.
**Não executado por este agente.**

| Superfície | Resultado |
|---|---|
| App | **PASS** |
| Admin | **PASS** |
| Painel central | **PASS** |

- Dados e menus principais carregaram nas três superfícies.
- Nenhum erro ou warning de console observado.
- **Nenhuma escrita realizada**: nenhum formulário enviado, nenhuma ação
  administrativa executada.

## Follow-up visual não bloqueante

O título da aba do Painel aparece como
`Console da Plataforma · Igreja 12 · Igreja 12` — sufixo de marca duplicado.
Classificado como **detalhe de metadata/título**, sem efeito sobre
funcionalidade, dados ou segurança. **Não é regressão bloqueante desta release**;
fica como follow-up cosmético.

## Veredito

**Release publicada e validada ponta a ponta.**

- Código: **PASS** (3 PRs mergeadas por merge commit real, encadeadas até `0a011fb`).
- Deploy: **PASS** (`READY`, target `production`, 3 aliases promovidos).
- Smoke público: **PASS** (3/3 HTTP 200 + image optimizer 200).
- Smoke autenticado (Codex, sessão externa): **PASS** (3/3).
- Audit de runtime: **0 vulnerabilidades**.

Sem migration. Sem rollback. As pendências citadas — `brace-expansion`,
`js-yaml`, peer `@types/node` × `vite`, e o título duplicado da aba do Painel —
permanecem como **follow-ups separados**, fora do escopo desta release.
