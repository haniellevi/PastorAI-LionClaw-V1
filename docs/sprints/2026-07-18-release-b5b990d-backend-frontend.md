# Release backend + frontend - b5b990d - 2026-07-18

**Commit:** `b5b990d` (`origin/main`, merge da PR#188)
**Deploy backend:** sim, producao (2026-07-18)
**Deploy frontend:** sim, producao (2026-07-18, dominio oficial do painel)

> Escopo deste registro: fato do release e confirmacoes abaixo. Nao inclui
> endereco de rede, caminho de servidor, nome de container, comando de
> implantacao, credencial, token ou chave.

## Origem

Primeira entrega executada pelo pipeline LionClaw "Igreja 12 - Fechamento MVP
(Execucao)" (4 sprints, worktree isolado, entrada direta na fase Planner),
com revisao humana/independente completa antes do merge: auditoria do diff
arquivo a arquivo, reexecucao das suites fora do pipeline e restauracao dos
artefatos de pipeline (nenhum foi versionado).

## Escopo funcional

Tres missoes do plano de fechamento do MVP:

1. **MEDIO-004 / CONTACT-TENANT-DEDUP-1** (`fix(contacts)`): as duas buscas de
   Pessoa por sufixo de telefone na deduplicacao de contatos (criacao e
   atualizacao) passaram a filtrar `igreja_id` explicitamente, em vez de
   depender apenas da RLS. Teste novo compila o `Select` real - remover o
   filtro quebra os asserts.
2. **MEDIO-005 / JWT-MINT-1** (`refactor(auth)`): emissao dos tres tokens de
   proposito (session, reset, invite) unificada em um helper unico, contraparte
   da politica compartilhada de verificacao (`fd651f9`). Assinaturas publicas,
   claims, TTLs e algoritmo preservados; testes cravam o conjunto exato de
   claims por tipo.
3. **W5A** (`refactor(frontend)`): os 8 ultimos dialogos manuais migrados para
   o primitive canonico `ds/Dialog` (DecisionModal, TrackModal, CellFormModal,
   InviteMemberModal, EditContactModal, AuditModal, PlanosManagerModal e o
   dialogo inline da tela de Equipe); componente morto CommunicateLeadersModal
   removido (zero importadores, provado por busca); `role="dialog"` indevido
   removido do painel lateral do inbox (que nao e modal). Busca final por
   `role="dialog"` no frontend retorna apenas o primitive e testes.

Nao ha migration neste release. Nenhuma dependencia nova.

## Verificacao

- Suite backend completa (pytest) verde antes do merge.
- Suite frontend 197/197 verde + build de producao ok antes do merge.
- Deploy backend com pre-checagem do pacote (simbolos novos confirmados no
  tarball e no staging antes da troca), backup do codigo e da imagem anteriores
  preservados, e recriacao apenas dos servicos da aplicacao.
- Runtime confirmou o helper unico de emissao dentro do container apos o deploy.
- Workers de fila e cron recriados junto com o backend (compartilham a imagem);
  demais servicos permaneceram intocados.
- Integracao WhatsApp reiniciada preventivamente apos o deploy (praxe do
  runbook) e sessao reconectada sem novo QR.
- Health check publico da API: **200** apos o deploy.
- Frontend publicado no dominio oficial do painel, resposta **200**.
- Smoke autenticado em producao pelo dono (2026-07-18): dialogos "Lancar
  decisao por Jesus", "Editar papeis", "Editar dados" e "Planos" abrindo e
  fechando por Esc/backdrop; painel lateral do inbox normal. **PASS.**

## Evidencia de codigo e teste

Commits contidos no merge `b5b990d` (PR#188): `ce14ee0` (contacts + teste de
isolamento de tenant `backend/tests/test_contacts_dedup_tenant.py`), `1419e97`
(clerk + testes de claims exatas em `backend/tests/test_clerk_jwt_policy.py`),
`ce27f4d` (frontend W5A).

Este registro tambem documenta o primeiro release de frontend com doc
versionado; releases de frontend anteriores (aprox. 2026-07-14/15/17) seguem
pendentes de registro retroativo (missao DOC-REL-FRONTEND).

## Rollback

Backend: backup do codigo anterior e tag da imagem anterior preservados no
servidor; nenhuma alteracao de schema ou dado exige reversao. Frontend: a
plataforma de hospedagem mantem o deployment anterior disponivel para
promocao imediata.
