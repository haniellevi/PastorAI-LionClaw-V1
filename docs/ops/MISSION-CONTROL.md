---
project: igreja12
document_kind: mission-control
status: canonical
last_reviewed: 2026-09-07
reviewed_by: Raniel
---

# Mission Control

Formato obrigatório de qualquer missão conduzida no canvas Maestri. O
Orquestrador preenche este formato antes de acionar qualquer especialista.
Missão sem ficha preenchida não começa.

Esta ficha cobre abertura, execução e encerramento de uma missão. Ela não
substitui o formato de encerramento exigido por
[`V1-FINALIZATION-MAP.md`](V1-FINALIZATION-MAP.md) nem o registro de
[`POST-V1-MISSION-REGISTER.md`](POST-V1-MISSION-REGISTER.md): a ficha os
alimenta. Em caso de divergência, o mapa e o registro prevalecem.

## Regras

- Uma missão tem um objetivo, um worktree, uma branch e um SHA base.
- Dois agentes nunca compartilham worktree. A raiz do repositório nunca é
  worktree de implementação.
- O Orquestrador é o único broker. Especialistas não falam entre si e não
  executam a CLI do Maestri.
- Toda missão termina em exatamente um gate aguardando autorização nominal do
  Raniel. Merge, teste verde, migration criada ou canário anterior não abrem
  gate para uma ação futura.
- Efeitos externos são deny-by-default e seguem
  `docs/ops/MAESTRI-PERSISTENCE-MANIFEST.md`.
- Nenhuma ficha carrega PII, dado pastoral, segredo ou dado de produção.

## Formato da ficha

~~~yaml
id: M-AAAA-MM-DD-slug
objetivo: uma frase, resultado observável
preflight:
  repositorio: <remoto e clone usados>
  branch: <branch consultada>
  sha_efetivo: <SHA do HEAD no momento da consulta>
  worktree_limpo: true | false, com a lista do que estava sujo
  ambiente: local | dev
  horario: AAAA-MM-DDTHH:MM:SS-03:00
  runbook_lido: <caminho do runbook e da seção>
  grafo: code-review-graph status, com SHA e frescor, ou "não disponível"
worktree: .worktrees/<slug>
branch: feat/<slug>
sha_base: <SHA completo de origin/main no momento da abertura>
especialistas:
  - implementador
  - revisor
criterios_de_aceite:
  - o que precisa estar verdadeiro para a missão fechar
riscos_de_tenant:
  - o que pode vazar entre igrejas e como isso é impedido
plano_de_teste:
  - comandos exatos e o que cada um prova
plano_de_rollback:
  - como desfazer, e o que não é reversível
proximo_gate: descrição de uma única ação que exige autorização nominal
encerramento:
  status_final: concluída | bloqueada | abandonada
  sha_final: <SHA do último commit da missão>
  branch_final: <branch>
  pr: <número ou "nenhum">
  mutacoes: tudo que mudou fora do código, ou "nenhuma"
  evidencias: comandos, saídas e artefatos, com SHA, ambiente e horário
  riscos_residuais: o que ficou aberto e para quem
  registro: caminho do arquivo em docs/sprints/ e, quando aplicável, a linha
    atualizada no POST-V1-MISSION-REGISTER
~~~

O bloco `encerramento` é preenchido ao fechar a missão, nunca na abertura.
Missão sem encerramento preenchido continua aberta, mesmo que o PR já tenha
sido integrado.

## Exemplo preenchido (fictício)

~~~yaml
id: M-2026-09-10-lembrete-celula
objetivo: enviar lembrete de relatório de célula ao líder, sem efeito externo real
preflight:
  repositorio: github.com/haniellevi/PastorAI-LionClaw-V1, clone local
  branch: chore/maestri-setup
  sha_efetivo: b3b35489436498fa234c74a6f835a572a0d89892
  worktree_limpo: true
  ambiente: local
  horario: 2026-09-10T09:12:00-03:00
  runbook_lido: docs/ops/EVOLUTION-AGENT-CANARY-RUNBOOK.md, seção de gates
  grafo: não disponível nesta sessão
worktree: .worktrees/lembrete-celula-v1
branch: feat/lembrete-celula-v1
sha_base: b3b35489436498fa234c74a6f835a572a0d89892
especialistas:
  - implementador
  - revisor
  - sentinela
criterios_de_aceite:
  - o job monta a mensagem e grava intenção, sem chamar a Evolution
  - ALLOW_REAL_SENDS permanece false em todo o caminho
  - pytest verde nos testes novos e nos existentes
riscos_de_tenant:
  - montar lembrete de líder de outra igreja; impedido por filtro igreja_id no
    serviço e por policy RLS testada com dois tenants sintéticos
plano_de_teste:
  - pytest backend/tests/test_lembrete_celula.py, prova a montagem e o bloqueio de envio
  - teste cross-tenant com dois igreja_id sintéticos, prova o isolamento
plano_de_rollback:
  - reverter o merge da branch; nenhuma migration e nenhum dado gravado
proximo_gate: autorizar a abertura do PR
encerramento:
  status_final: pendente
  sha_final: pendente
  branch_final: feat/lembrete-celula-v1
  pr: nenhum
  mutacoes: nenhuma
  evidencias: pendente
  riscos_residuais: pendente
  registro: pendente
~~~

## Onde a ficha vive

Enquanto a missão corre, a ficha fica em uma nota do canvas Maestri e no
cabeçalho da descrição do PR. Ao fechar, o resumo vai para
`docs/sprints/AAAA-MM-DD-titulo.md`.
