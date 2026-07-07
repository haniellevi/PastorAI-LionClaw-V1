"""EVT-8 PR2 — resolução de destinatários da notificação do evento.

Duas camadas:
  - **domínio puro** (``app/domain/event_notifications.py``): opt-out + dedup,
    testado com listas montadas à mão (sem banco);
  - **serviço** (``app/services/event_recipients.py``): as queries por público,
    testadas com uma FakeSession que roteia por entidade e devolve linhas
    canadas, e provando o contrato das queries pelo SQL gerado (mesma técnica de
    ``_last_event_where`` em test_events_crud_evt2) — sem DB real, sem ARRAY/UUID.

Nada de envio: um teste espiona ``EvolutionClient.send_text`` e prova que resolver
NÃO dispara WhatsApp.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.db.models import AppUser, Celula, Event, EventNotifyTarget, Pessoa, UserRole
from app.domain.event_notifications import (
    Candidate,
    ResolvedRecipient,
    resolve_recipients,
)
from app.services.event_recipients import resolve_event_notification_recipients

_IGREJA = uuid.UUID("00000000-0000-0000-0000-000000000001")
_EVENT = uuid.UUID("00000000-0000-0000-0000-0000000000e2")
_P1 = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
_P2 = uuid.UUID("00000000-0000-0000-0000-0000000000c2")
_P3 = uuid.UUID("00000000-0000-0000-0000-0000000000c3")


# ===========================================================================
# Domínio puro — opt-out + dedup
# ===========================================================================
def test_pure_individual_pessoa_resolves_phone() -> None:
    aud = resolve_recipients(
        individual=[Candidate(pessoa_id=str(_P1), telefone="11999990000", optout=False)],
        coletivo=[],
    )
    assert aud.recipients == [ResolvedRecipient(pessoa_id=str(_P1), telefone="11999990000")]
    assert aud.total == 1
    assert aud.ignored_optout == 0


def test_pure_individual_phone_fallback() -> None:
    aud = resolve_recipients(
        individual=[Candidate(pessoa_id=None, telefone="11988887777", optout=False)],
        coletivo=[],
    )
    assert aud.recipients == [ResolvedRecipient(pessoa_id=None, telefone="11988887777")]


def test_pure_optout_is_excluded_and_counted() -> None:
    aud = resolve_recipients(
        individual=[],
        coletivo=[Candidate(pessoa_id=str(_P1), telefone="11999990000", optout=True)],
    )
    assert aud.recipients == []
    assert aud.ignored_optout == 1


def test_pure_dedup_same_pessoa_individual_and_coletivo() -> None:
    # Mesma pessoa no individual e no coletivo → entra 1x (prioridade individual).
    aud = resolve_recipients(
        individual=[Candidate(pessoa_id=str(_P1), telefone="11999990000")],
        coletivo=[Candidate(pessoa_id=str(_P1), telefone="11999990000")],
    )
    assert aud.total == 1


def test_pure_dedup_by_normalized_phone_across_sources() -> None:
    # Individual só-telefone + coletivo por pessoa com o MESMO número (formatado
    # diferente) → 1x (dedup por telefone normalizado).
    aud = resolve_recipients(
        individual=[Candidate(pessoa_id=None, telefone="+55 11 99999-0000")],
        coletivo=[Candidate(pessoa_id=str(_P1), telefone="11999990000")],
    )
    assert aud.total == 1
    # o individual (só-telefone) tem prioridade.
    assert aud.recipients[0].pessoa_id is None


def test_pure_skips_candidate_without_phone() -> None:
    aud = resolve_recipients(
        individual=[],
        coletivo=[Candidate(pessoa_id=str(_P1), telefone=None)],
    )
    assert aud.recipients == []
    assert aud.skipped_sem_telefone == 1
    assert aud.ignored_optout == 0


# ===========================================================================
# Serviço — FakeSession roteando por entidade + asserções de SQL
# ===========================================================================
class _R:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = list(scalars or [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class ResolverSession:
    """Roteia Event / EventNotifyTarget / as várias queries de Pessoa."""

    def __init__(
        self,
        *,
        event=None,
        targets=(),
        individual_pessoas=(),
        pastores=(),
        g12=(),
        lideres=(),
        toda_igreja=(),
    ) -> None:
        self.event = event
        self.targets = list(targets)
        self.individual_pessoas = list(individual_pessoas)
        self.pastores = list(pastores)
        self.g12 = list(g12)
        self.lideres = list(lideres)
        self.toda_igreja = list(toda_igreja)
        self.statements: list = []

    def execute(self, statement, params=None) -> _R:
        self.statements.append(statement)
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        sql = str(statement).lower()
        if ent is Event:
            return _R(scalar=self.event)
        if ent is EventNotifyTarget:
            return _R(scalars=self.targets)
        if ent is Pessoa:
            if "user_roles" in sql:
                params_vals = list(statement.compile().params.values())
                if "lider_g12" in params_vals:
                    return _R(scalars=self.g12)
                return _R(scalars=self.pastores)
            if "celulas" in sql:
                return _R(scalars=self.lideres)
            if "pessoas.id in" in sql or " in (" in sql:
                return _R(scalars=self.individual_pessoas)
            return _R(scalars=self.toda_igreja)
        return _R(scalars=[])


def _pessoa(pid, telefone="11900000000", optout=False):
    return SimpleNamespace(id=pid, telefone=telefone, optout=optout)


def _target(*, pessoa_id=None, telefone=None):
    return SimpleNamespace(
        pessoa_id=pessoa_id, telefone=telefone, event_id=_EVENT, igreja_id=_IGREJA
    )


def _event(publico_alvo=None):
    return SimpleNamespace(id=_EVENT, igreja_id=_IGREJA, publico_alvo=publico_alvo)


def _find_sql(session, needle: str) -> str:
    for stmt in session.statements:
        s = str(stmt).lower()
        if needle in s:
            return s
    raise AssertionError(f"nenhum statement contém {needle!r}")


def test_service_event_not_found_returns_empty() -> None:
    session = ResolverSession(event=None)
    aud = resolve_event_notification_recipients(session, _EVENT, _IGREJA)
    assert aud.total == 0
    assert aud.recipients == []


def test_service_individual_by_pessoa_resolves_and_respects_optout() -> None:
    session = ResolverSession(
        event=_event(publico_alvo=[]),
        targets=[_target(pessoa_id=_P1), _target(pessoa_id=_P2)],
        individual_pessoas=[
            _pessoa(_P1, telefone="11999990000", optout=False),
            _pessoa(_P2, telefone="11888880000", optout=True),  # optout → fora
        ],
    )
    aud = resolve_event_notification_recipients(session, _EVENT, _IGREJA)
    assert [r.telefone for r in aud.recipients] == ["11999990000"]
    assert aud.ignored_optout == 1


def test_service_individual_phone_fallback() -> None:
    session = ResolverSession(
        event=_event(publico_alvo=[]),
        targets=[_target(telefone="11977776666")],  # sem pessoa vinculada
    )
    aud = resolve_event_notification_recipients(session, _EVENT, _IGREJA)
    assert aud.recipients == [ResolvedRecipient(pessoa_id=None, telefone="11977776666")]


def test_service_toda_igreja_filters_tenant_and_csim() -> None:
    session = ResolverSession(
        event=_event(publico_alvo=["toda_igreja"]),
        toda_igreja=[_pessoa(_P1, telefone="11999990000")],
    )
    aud = resolve_event_notification_recipients(session, _EVENT, _IGREJA)
    assert aud.total == 1
    sql = _find_sql(session, "sem_interesse")
    assert "pessoas.igreja_id" in sql  # tenant no WHERE
    assert "sem_interesse" in sql  # exclui CSIM


def test_service_lideres_celula_uses_celula_lider_id_not_membro() -> None:
    session = ResolverSession(
        event=_event(publico_alvo=["lideres_celula"]),
        lideres=[_pessoa(_P1, telefone="11999990000")],
    )
    aud = resolve_event_notification_recipients(session, _EVENT, _IGREJA)
    assert aud.total == 1
    sql = _find_sql(session, "celulas")
    assert "celulas.lider_id" in sql  # D5 — fonte canônica
    assert "celulas.ativo" in sql  # só célula ativa
    assert "celulas.igreja_id" in sql  # tenant
    assert "celula_membro" not in sql  # NUNCA por vínculo/papel de membro
    assert "papel" not in sql


def test_service_pastores_uses_role_pastor() -> None:
    session = ResolverSession(
        event=_event(publico_alvo=["pastores"]),
        pastores=[_pessoa(_P1, telefone="11999990000")],
    )
    aud = resolve_event_notification_recipients(session, _EVENT, _IGREJA)
    assert aud.total == 1
    sql = _find_sql(session, "user_roles")
    assert "user_roles.papel" in sql
    assert "app_users" in sql
    # papel resolvido = 'pastor'
    papel_stmt = next(s for s in session.statements if "user_roles" in str(s).lower())
    assert "pastor" in list(papel_stmt.compile().params.values())


def test_service_g12_pastoral_uses_role_lider_g12() -> None:
    session = ResolverSession(
        event=_event(publico_alvo=["g12_pastoral"]),
        g12=[_pessoa(_P1, telefone="11999990000")],
    )
    aud = resolve_event_notification_recipients(session, _EVENT, _IGREJA)
    assert aud.total == 1
    papel_stmt = next(s for s in session.statements if "user_roles" in str(s).lower())
    assert "lider_g12" in list(papel_stmt.compile().params.values())


def test_service_dedup_individual_and_coletivo_same_pessoa() -> None:
    # P1 é pastor E foi selecionado individualmente → entra 1x.
    session = ResolverSession(
        event=_event(publico_alvo=["pastores"]),
        targets=[_target(pessoa_id=_P1)],
        individual_pessoas=[_pessoa(_P1, telefone="11999990000")],
        pastores=[_pessoa(_P1, telefone="11999990000")],
    )
    aud = resolve_event_notification_recipients(session, _EVENT, _IGREJA)
    assert aud.total == 1


def test_service_makes_no_whatsapp_send(monkeypatch) -> None:
    calls: list = []

    def _record_send(self, instance, phone, text):  # pragma: no cover - não deve
        calls.append((instance, phone, text))
        return True

    monkeypatch.setattr(
        "app.services.evolution.EvolutionClient.send_text", _record_send
    )
    session = ResolverSession(
        event=_event(publico_alvo=["toda_igreja"]),
        targets=[_target(pessoa_id=_P1)],
        individual_pessoas=[_pessoa(_P1)],
        toda_igreja=[_pessoa(_P2, telefone="11999990000")],
    )
    resolve_event_notification_recipients(session, _EVENT, _IGREJA)
    assert calls == []  # resolver NÃO envia nada
