-- ============================================================================
-- PastorAI 1.0 — Migration 0011: app_users.celula_pendente_id (convite Parte B)
-- delta-049. Convite de pessoa NOVA (que ainda não é uma Pessoa cadastrada): o
-- convidado completa o cadastro (telefone/WhatsApp) na ativação e só então vira
-- uma Pessoa-membro. Entre o convite e a ativação não há Pessoa ainda, então a
-- célula destino fica guardada aqui (no app_user convidado) até a ativação criar
-- a Pessoa e vinculá-la. Limpa (volta a NULL) após a ativação.
--
-- Aditiva e nullable: convites da Parte A (pessoa já cadastrada) deixam NULL.
-- ON DELETE SET NULL: apagar a célula não derruba o convite pendente.
-- Idempotente.
-- ============================================================================

begin;

alter table app_users
  add column if not exists celula_pendente_id uuid
  references celulas(id) on delete set null;

comment on column app_users.celula_pendente_id is
  'Célula destino de um convite pendente (Parte B / delta-049): quando o convidado ainda não é Pessoa, guarda a célula até a ativação criar a Pessoa-membro. NULL na Parte A e após a ativação.';

commit;
