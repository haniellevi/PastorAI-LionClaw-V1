# V1 pronta para publicação formal — 2026-08-21

**Branch:** `codex/v1-closure-evidence`  ·  **Código:** `281e69c2fef80cfbcb27eab5ca4f85981e4adc0c`  ·  **Deploy:** backend Hostinger, frontend Vercel e Supabase PROD

## O que foi feito

- Corrigida a divergência de autenticação: seis vínculos auditados foram
  migrados de Clerk LIVE para Clerk DEV em uma transação, com rollback completo
  preservado.
- Reconciliado o ledger oficial do Supabase para M06 e M01 sem reaplicar DDL.
- Restaurados os dumps Supabase/PostgreSQL 17 e Evolution/PostgreSQL 16 em
  containers descartáveis; Storage e volumes foram verificados
  estruturalmente.
- Implantado o frontend RC no deployment Vercel
  `dpl_CdwTcTE8HZHvxs9t92Ak6sHxebAp`, compartilhado pelos três domínios.
- Aprovados smokes read-only de administrador, pastor, líder, membro e master.
- Executado exatamente um canário Brevo; recebimento confirmado e gate
  restaurado para `off` com allowlist vazia.
- Provados rollback e roll-forward de backend e frontend.
- Aprovadas duas execuções locais do monitor e os workflows GitHub
  `32543076877` e `32543098661` após o roll-forward.

## Decisões

- A V1 continua como piloto controlado em Clerk DEV.
- Migrations forward-only já aplicadas foram reconciliadas por recibos de
  metadados com SHA-256; nenhum DDL foi repetido.
- Asaas real, broadcast, envios globais e Brevo live permanecem desligados.
- PR #257 e Células continuam pós-V1.

## Pendente / próximo passo

- Integrar esta evidência.
- Criar e publicar a tag anotada `v1.0.0` no SHA de código, referenciando o
  commit documental, e criar o GitHub Release.
- Concluir housekeeping reversível e revogar a chave SSH temporária após provar
  acesso permanente alternativo.
- Atualizar o mapa com a tag/release e então declarar `V1_ENCERRADA`.

## Verificação

- Evidência detalhada: `docs/releases/v1/v1-closure-evidence.md`.
- API pública: health e readiness verdes.
- Frontend: três domínios HTTP 200, headers M06 presentes, zero erro de runtime
  Vercel na janela verificada.
- Backup final: `pastorai-backup-20260821T213637Z.tar.gz`, checksum e restauração
  aprovados.
