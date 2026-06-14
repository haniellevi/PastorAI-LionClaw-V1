"""Cell multiplication rules (enviar — US-21/22/23, delta-027).

Pure helpers gating the multiplication lifecycle: a multiplication is scheduled
(`agendada`) or pending a date (`sem_agendamento`), and can only be approved
once supervision has signed off (`supervisao_ok`). Approval records the
approver and moves the status to `aprovada`.
"""

from __future__ import annotations

# Roles allowed to schedule/approve multiplications (US-22/23).
# admin always passes via CurrentUser.has_any_role (implicit access).
MULTIPLICATION_ROLES: list[str] = ["lider_g12", "pastor"]

# multiplicacao_status enum (SPEC 2.1).
STATUS_AGENDADA = "agendada"
STATUS_SEM_AGENDAMENTO = "sem_agendamento"
STATUS_APROVADA = "aprovada"
STATUS_CONCLUIDA = "concluida"
VALID_STATUS: frozenset[str] = frozenset(
    {STATUS_AGENDADA, STATUS_SEM_AGENDAMENTO, STATUS_APROVADA, STATUS_CONCLUIDA}
)


def schedule_status(has_data_prevista: bool) -> str:
    """A multiplication with a planned date is `agendada`, otherwise pending."""
    return STATUS_AGENDADA if has_data_prevista else STATUS_SEM_AGENDAMENTO


def can_approve(supervisao_ok: bool) -> bool:
    """delta-027: approval is disabled while supervision has not signed off."""
    return bool(supervisao_ok)
