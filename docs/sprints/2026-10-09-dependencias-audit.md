# Dependências reprovadas pelos audits — 2026-10-09

**Branch:** `fix/deps-audit-20261009`  ·  **Commits:** neste PR  ·  **Deploy:** não

## O que foi feito
- Backend: `langgraph` 1.0.10 → 1.2.14 (`requirements.txt` passa de `>=1.0.10,<1.1`
  para `>=1.2.3,<1.3`), o que traz `langgraph-sdk` 0.3.15 → 0.4.6 e
  `langgraph-prebuilt` 1.0.8 → 1.1.0. Lock regerado com o mesmo comando do
  cabeçalho; nenhum outro pacote mudou. `pip-audit` reprovava por
  CVE-2026-104873 (`langgraph-sdk`, correção na 0.4.4). O SDK só era
  puxado pelo `langgraph`, que limitava `langgraph-sdk<0.4`; por isso a
  correção exigiu subir o `langgraph`.
- Frontend: override `sharp` 0.35.4 → 0.35.5 (GHSA-wq5f-xc86-pv6w) e
  `source-map-js` 1.2.1 → 1.2.2 no lock (GHSA-68fv-2mgg-jv7q). O lock também
  atualizou os binários `@img/sharp-libvips-*` e desduplicou o `postcss`
  8.5.23 aninhado no vitest.

## Decisões
- O app não usa o servidor LangGraph nem os decoradores de autorização do SDK
  (`@auth.on.*`) afetados pelo CVE; a atualização é para o audit voltar a
  valer, não por exploração conhecida.
- Os audits continuam ligados. O `next` 15.5.25 segue com dois avisos
  moderados (cache de SSG/ISR em hospedagem própria, GHSA-4jqv-mc3x-m676 e
  GHSA-mcj8-r9mp-w47p). Estão abaixo do `--audit-level=high` do CI e a correção
  é o patch 15.5.27, fora do escopo desta fatia.

## Verificação
- `pip-audit` sobre `requirements.lock` e `requirements-audit.lock`: sem
  vulnerabilidades. `npm audit --omit=dev --audit-level=high`: exit 0.
- Backend (`pytest -m "not rls_integration"`, ambiente limpo a partir do lock
  novo, Python 3.13.14): verde. Testes de `deploy/` e do monitor: verdes.
- Frontend (Node 24.19.0, `npm ci`): lint, `tsc`, 1.165 testes Vitest,
  `next build` e smoke de headers verdes.
- Não reproduzido localmente: build da imagem Docker e a suíte
  `rls_integration`/PG17; ficam para o CI do PR.

## Pendente / próximo passo
- Depois de integrar, atualizar a base dos PRs #461 e #462 e revalidá-los.
- Avaliar o patch 15.5.27 do `next` em fatia própria.
