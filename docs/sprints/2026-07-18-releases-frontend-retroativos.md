# Releases de frontend retroativos - registro em 2026-07-18

**Registro retroativo.** Este documento consolida deploys de frontend na Vercel
(projeto `pastorai-frontend`, dominio `app.igreja12.com.br`) realizados antes do
release conjunto `b5b990d` de 2026-07-18 (ja documentado em
`2026-07-18-release-b5b990d-backend-frontend.md`) e que nao tinham registro
versionado proprio.

> Escopo deste registro: fato dos releases e confirmacoes abaixo. Nao inclui
> endereco de rede, caminho de servidor, comando de implantacao, credencial,
> token ou chave.

As datas de merge abaixo vem do historico git (`origin/main`). As datas de
deploy sao **provaveis**: a evidencia e a confirmacao operacional do dono
(pendente de confirmacao da data exata na dashboard da Vercel).

## Deploy 1 - CONV-AI-1 (PR#170) - data provavel ~2026-07-14

- **Commit provavel:** `13b160f` (merge da PR#170 em `main`, 2026-07-14 14:33 BRT).
- **PRs incluidas:** #170 (`sem_interesse` pausa a IA na conversa; frontend-only).
- **Evidencia:** confirmacao operacional do dono (pendente de confirmacao da
  data exata na dashboard da Vercel). Observacao: a memoria do projeto situava
  este deploy em ~10-11/07, mas o merge da PR#170 ocorreu em 14/07; a data real
  do deploy precisa ser confirmada na Vercel.
- **Smoke:** pendente (missao EVID-1).

## Deploy 2 - Wave Visual W2 (PR#173) - data provavel ~2026-07-15

- **Commit provavel:** `d00bbb5` (merge da PR#173 em `main`, 2026-07-15 14:14 BRT).
- **PRs incluidas:** #173 (papeis/status visuais da Wave Visual W2).
- **Evidencia:** confirmacao operacional do dono (pendente de confirmacao da
  data exata na dashboard da Vercel). Observacao: a estimativa anterior era
  ~14/07, mas o merge da PR#173 ocorreu em 15/07; e possivel que este deploy e o
  Deploy 3 tenham sido um unico deploy em 15/07 (merges com ~40 min de
  intervalo) - confirmar na Vercel.
- **Smoke:** pendente (missao EVID-1).

## Deploy 3 - W3 Agenda + dialogos (~553ec86 / PR#174) - data provavel 2026-07-15

- **Commit provavel:** `553ec86` (2026-07-15 14:16 BRT, na branch da PR#174;
  contido em `main` via merge `611a2ad` da PR#174, 2026-07-15 14:54 BRT).
  O commit `553ec86` ja contem o merge da PR#173.
- **PRs incluidas:** #174 (W3: Agenda + dialogos), com #173 ja incorporada.
- **Evidencia:** confirmacao operacional do dono (pendente de confirmacao da
  data exata e do commit exato na dashboard da Vercel).
- **Smoke:** pendente (missao EVID-1).

## Deploy 4 - W4A/W4B dialogos ds/Dialog (3aac399) - data provavel 2026-07-17

- **Commit provavel:** `3aac399` (2026-07-16 21:37 BRT em `main`).
- **PRs incluidas:** #183 (W4A: Report/NewContact/LinkCell migrados para
  ds/Dialog; merge `a67cae9`, 2026-07-16 18:24 BRT) e #184 (W4B: dialogos admin
  Create/Edit/Orquestrador Igreja; merge `70846d2`, 2026-07-16 20:23 BRT).
  O commit `3aac399` em si e docs (#185); o deploy a partir dele carrega W4A e
  W4B.
- **Evidencia:** confirmacao operacional do dono em 2026-07-17 (pendente de
  confirmacao da data exata na dashboard da Vercel).
- **Smoke:** os smokes formais seguem pendentes (missao EVID-1). Observacao: o
  smoke autenticado de 2026-07-18 do release `b5b990d`
  (`2026-07-18-smoke-autenticado-release-b5b990d.md`) ja cobriu os dialogos W4A
  por tabela.

## Linha do tempo (git)

| Evento | Commit | Data (BRT) |
| --- | --- | --- |
| Merge PR#170 (CONV-AI-1) | `13b160f` | 2026-07-14 14:33 |
| Merge PR#173 (W2) | `d00bbb5` | 2026-07-15 14:14 |
| Commit `553ec86` (branch PR#174) | `553ec86` | 2026-07-15 14:16 |
| Merge PR#174 (W3) | `611a2ad` | 2026-07-15 14:54 |
| Merge PR#183 (W4A) | `a67cae9` | 2026-07-16 18:24 |
| Merge PR#184 (W4B) | `70846d2` | 2026-07-16 20:23 |
| Commit `3aac399` (docs #185) | `3aac399` | 2026-07-16 21:37 |

## Pendencias

- Confirmar na dashboard da Vercel a data/hora e o commit exato de cada um dos
  quatro deploys acima.
- Executar os smokes autenticados pendentes (missao EVID-1).
