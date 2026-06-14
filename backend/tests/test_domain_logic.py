"""Unit tests for the pure pastoral-domain rules (no I/O)."""

from __future__ import annotations

from app.domain.consolidation import (
    can_conclude,
    compute_progresso,
    is_valid_etapa,
    pending_mandatory,
)
from app.domain.hierarchy import is_leader_or_superior
from app.domain.multiplication import can_approve, schedule_status
from app.domain.phone import normalize_phone
from app.domain.pipeline import (
    etapa_rank,
    meets_promotion_criteria,
    validate_transition,
)
from app.domain.work_queue import (
    can_resolve,
    format_internal_message,
    primary_role,
    resolvable_tipos,
)


# ---- phone ----------------------------------------------------------------
def test_normalize_phone_strips_formatting() -> None:
    # Canonical BR key drops +55 and keeps the local 11-digit mobile.
    assert normalize_phone("+55 (11) 99999-0000") == "11999990000"
    assert normalize_phone("11 99999 0000") == "11999990000"


def test_normalize_phone_canonicalizes_br_variants() -> None:
    # The same number across WhatsApp/E.164 forms collapses to one dedupe key:
    # +55 is dropped and the 9th digit (often omitted by WhatsApp) is re-added.
    assert normalize_phone("89994315927") == "89994315927"        # local, with 9
    assert normalize_phone("558994315927") == "89994315927"       # +55, 9 omitted
    assert normalize_phone("+55 89 9431-5927") == "89994315927"   # +55, 8-digit
    assert normalize_phone("5589994315927") == "89994315927"      # +55, with 9


def test_normalize_phone_empty() -> None:
    assert normalize_phone("") == ""
    assert normalize_phone("abc") == ""


# ---- pipeline -------------------------------------------------------------
def test_etapa_rank_order() -> None:
    assert etapa_rank("ganhar") < etapa_rank("consolidar") < etapa_rank("enviar")
    assert etapa_rank(None) == -1


def test_promotion_criteria() -> None:
    assert meets_promotion_criteria(3, False) is True
    assert meets_promotion_criteria(0, True) is True
    assert meets_promotion_criteria(2, False) is False


def test_visitante_cannot_be_promoted_without_criteria() -> None:
    result = validate_transition(
        current_tipo="visitante",
        current_etapa="ganhar",
        target_etapa="consolidar",
        target_subetapa=None,
        presencas_celula=1,
        aceitou_jesus=False,
    )
    assert result.allowed is False
    assert result.reason is not None


def test_visitante_promoted_with_attendances() -> None:
    result = validate_transition(
        current_tipo="visitante",
        current_etapa="ganhar",
        target_etapa="consolidar",
        target_subetapa="em_consolidacao",
        presencas_celula=3,
        aceitou_jesus=False,
    )
    assert result.allowed is True


def test_visitante_can_move_within_ganhar() -> None:
    result = validate_transition(
        current_tipo="visitante",
        current_etapa="ganhar",
        target_etapa="ganhar",
        target_subetapa="visitante",
        presencas_celula=0,
        aceitou_jesus=False,
    )
    assert result.allowed is True


def test_invalid_etapa_rejected() -> None:
    result = validate_transition(
        current_tipo="membro",
        current_etapa="consolidar",
        target_etapa="invalida",
        target_subetapa=None,
        presencas_celula=0,
        aceitou_jesus=False,
    )
    assert result.allowed is False


def test_member_can_advance_freely() -> None:
    result = validate_transition(
        current_tipo="membro",
        current_etapa="consolidar",
        target_etapa="discipular",
        target_subetapa=None,
        presencas_celula=0,
        aceitou_jesus=False,
    )
    assert result.allowed is True


# ---- hierarchy ------------------------------------------------------------
def test_leader_itself_is_authorized() -> None:
    assert is_leader_or_superior(
        actor_pessoa_id="L1", cell_leader_id="L1", lider_of={}
    )


def test_superior_in_chain_is_authorized() -> None:
    # L3 -> led by L2 -> led by L1 (top). L1 is superior to cell led by L3.
    lider_of = {"L3": "L2", "L2": "L1", "L1": None}
    assert is_leader_or_superior(
        actor_pessoa_id="L1", cell_leader_id="L3", lider_of=lider_of
    )


def test_unrelated_person_is_not_authorized() -> None:
    lider_of = {"L3": "L2", "L2": "L1", "L1": None, "X": None}
    assert not is_leader_or_superior(
        actor_pessoa_id="X", cell_leader_id="L3", lider_of=lider_of
    )


def test_hierarchy_handles_cycle() -> None:
    lider_of = {"A": "B", "B": "A"}  # malformed cycle
    assert not is_leader_or_superior(
        actor_pessoa_id="Z", cell_leader_id="A", lider_of=lider_of
    )


def test_hierarchy_requires_actor_and_leader() -> None:
    assert not is_leader_or_superior(
        actor_pessoa_id=None, cell_leader_id="L1", lider_of={}
    )
    assert not is_leader_or_superior(
        actor_pessoa_id="L1", cell_leader_id=None, lider_of={}
    )


# ---- work queue -----------------------------------------------------------
def test_can_resolve_by_role() -> None:
    assert can_resolve(["lider_celula"], "relatorio") is True
    assert can_resolve(["membro"], "relatorio") is False


def test_admin_resolves_everything() -> None:
    assert can_resolve(["admin"], "atendimento") is True
    assert resolvable_tipos(["admin"]) == {
        "visitante",
        "atendimento",
        "relatorio",
        "conectar_celula",
        "fonovisita",
    }


def test_resolvable_tipos_filtered_by_role() -> None:
    tipos = resolvable_tipos(["lider_consol"])
    assert "conectar_celula" in tipos
    assert "fonovisita" in tipos
    assert "atendimento" not in tipos


def test_primary_role_seniority() -> None:
    assert primary_role(["membro", "pastor", "lider_celula"]) == "pastor"
    assert primary_role(["lider_celula", "lider_consol"]) == "lider_consol"
    assert primary_role([]) == "membro"


def test_format_internal_message_prefix() -> None:
    text = format_internal_message("Ana", ["lider_celula"], "Olá, tudo bem?")
    assert text == "Ana [Líder de Célula]: Olá, tudo bem?"


# ---- consolidation --------------------------------------------------------
def test_is_valid_etapa_known_and_visita_n() -> None:
    assert is_valid_etapa("aceitou_jesus") is True
    assert is_valid_etapa("conectou_celula") is True
    assert is_valid_etapa("visita_3") is True
    assert is_valid_etapa("visita_x") is False
    assert is_valid_etapa("invalida") is False


def test_compute_progresso_reflects_confirmed_stages() -> None:
    assert compute_progresso([]) == 0
    assert compute_progresso(["aceitou_jesus"]) == 33
    assert compute_progresso(
        ["aceitou_jesus", "conectou_celula", "fonovisita"]
    ) == 100


def test_pending_mandatory_and_can_conclude() -> None:
    assert pending_mandatory(["aceitou_jesus"]) == {"conectou_celula", "fonovisita"}
    assert can_conclude(["aceitou_jesus"]) is False
    assert can_conclude(
        ["aceitou_jesus", "conectou_celula", "fonovisita"]
    ) is True


# ---- multiplication -------------------------------------------------------
def test_schedule_status_by_date() -> None:
    assert schedule_status(True) == "agendada"
    assert schedule_status(False) == "sem_agendamento"


def test_can_approve_requires_supervision() -> None:
    assert can_approve(True) is True
    assert can_approve(False) is False
