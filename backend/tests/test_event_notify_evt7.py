"""EVT-7 PR1 — aviso síncrono de confirmação de evento à equipe interna.

Testa o helper `notify_event_confirmed` com fakes em memória (sem DB nem rede),
espelhando o estilo dos testes do motor de SLA. Cobre o contrato da missão:

  - flag OFF                        → não chama Evolution;
  - flag ON, sem destinatário       → não envia e não quebra;
  - flag ON, com destinatário       → envia UMA vez e marca notificado_em;
  - já notificado (notificado_em)   → não reenvia (idempotência);
  - evento ainda 'a_confirmar'      → não dispara envio;
  - falha do Evolution              → não desfaz nada e deixa notificado_em NULL;
  - outbound_guard NÃO é contornado (send_text guardado é o único caminho);
  - modelo e migration espelham a coluna notificado_em.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import uuid
from types import SimpleNamespace

import httpx

from app.config import Settings
from app.db.models import AppUser, Event, Pessoa, UserRole, WhatsappConnection
from app.services.event_notify import notify_event_confirmed
from app.services.evolution import EvolutionError

_IGREJA = uuid.UUID("00000000-0000-0000-0000-000000000001")
_UID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_PID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _Scalars:
    def __init__(self, items: list) -> None:
        self._items = items

    def all(self) -> list:
        return list(self._items)


class _Result:
    def __init__(self, items: list) -> None:
        self._items = items

    def scalars(self) -> _Scalars:
        return _Scalars(self._items)

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None


class FakeNotifySession:
    """Roteia execute() por entidade e get() por (modelo, id)."""

    def __init__(
        self, *, user_ids=None, users=None, pessoas=None, connection=None
    ) -> None:
        self.user_ids = user_ids or []
        self.users = users or {}
        self.pessoas = pessoas or {}
        self.connection = connection
        self.flushed = False
        self.committed = False

    def execute(self, statement, params=None) -> _Result:
        descs = getattr(statement, "column_descriptions", None)
        entity = descs[0].get("entity") if descs else None
        if entity is UserRole:
            return _Result(self.user_ids)
        if entity is WhatsappConnection:
            return _Result([self.connection] if self.connection else [])
        return _Result([])

    def get(self, model, ident):
        if model is AppUser:
            return self.users.get(ident)
        if model is Pessoa:
            return self.pessoas.get(ident)
        return None

    def flush(self) -> None:
        self.flushed = True

    def commit(self) -> None:
        self.committed = True


class SpyEvolution:
    """Registra send_text; opcionalmente falha (simula erro de rede)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.fail = fail

    def send_text(self, instance: str, telefone: str, texto: str) -> bool:
        if self.fail:
            raise EvolutionError("boom")
        self.sent.append((instance, telefone, texto))
        return True


def _event(*, status: str = "confirmado", notificado_em=None):
    return SimpleNamespace(
        igreja_id=_IGREJA,
        status=status,
        notificado_em=notificado_em,
        titulo="Culto",
        data=dt.date(2026, 1, 1),
        hora="19:30",
    )


def _session_with_recipient() -> FakeNotifySession:
    """Sessão com 1 usuário de coordenação (com telefone) e número oficial."""
    user = SimpleNamespace(id=_UID, pessoa_id=_PID)
    pessoa = SimpleNamespace(id=_PID, telefone="5511999990000")
    return FakeNotifySession(
        user_ids=[_UID],
        users={_UID: user},
        pessoas={_PID: pessoa},
        connection=SimpleNamespace(instance="igreja-inst"),
    )


def _on() -> Settings:
    return Settings(agenda_notify_enabled=True)


def _off() -> Settings:
    return Settings(agenda_notify_enabled=False)


# ---------------------------------------------------------------------------
# 1) flag OFF não chama Evolution
# ---------------------------------------------------------------------------
def test_flag_off_does_not_call_evolution() -> None:
    spy = SpyEvolution()
    event = _event()
    session = _session_with_recipient()
    assert notify_event_confirmed(session, event, settings=_off(), evolution=spy) is False
    assert spy.sent == []
    assert event.notificado_em is None
    assert session.committed is False


# ---------------------------------------------------------------------------
# 2) flag ON sem destinatário: não envia, não quebra, notificado_em fica NULL
# ---------------------------------------------------------------------------
def test_flag_on_without_recipient_does_not_send() -> None:
    spy = SpyEvolution()
    event = _event()
    # tem número oficial, mas ninguém com papel de coordenação → sem destinatário.
    session = FakeNotifySession(
        user_ids=[], connection=SimpleNamespace(instance="igreja-inst")
    )
    assert notify_event_confirmed(session, event, settings=_on(), evolution=spy) is False
    assert spy.sent == []
    assert event.notificado_em is None
    assert session.committed is False


def test_flag_on_without_official_number_does_not_send() -> None:
    spy = SpyEvolution()
    event = _event()
    # tem destinatário com telefone, mas nenhum número oficial conectado.
    user = SimpleNamespace(id=_UID, pessoa_id=_PID)
    pessoa = SimpleNamespace(id=_PID, telefone="5511999990000")
    session = FakeNotifySession(
        user_ids=[_UID], users={_UID: user}, pessoas={_PID: pessoa}, connection=None
    )
    assert notify_event_confirmed(session, event, settings=_on(), evolution=spy) is False
    assert spy.sent == []
    assert event.notificado_em is None


# ---------------------------------------------------------------------------
# 3) flag ON com destinatário: envia UMA vez e marca notificado_em
# ---------------------------------------------------------------------------
def test_flag_on_with_recipient_sends_once_and_marks() -> None:
    spy = SpyEvolution()
    event = _event()
    session = _session_with_recipient()
    assert notify_event_confirmed(session, event, settings=_on(), evolution=spy) is True
    assert len(spy.sent) == 1
    instance, phone, texto = spy.sent[0]
    assert instance == "igreja-inst"
    assert phone == "5511999990000"
    assert texto == "Evento confirmado: Culto em 2026-01-01 19:30. Abra a Agenda para revisar."
    assert event.notificado_em is not None
    assert session.committed is True


# ---------------------------------------------------------------------------
# 4) idempotência: confirmar de novo não reenvia se notificado_em já preenchido
# ---------------------------------------------------------------------------
def test_does_not_resend_when_already_notified() -> None:
    spy = SpyEvolution()
    event = _event(notificado_em=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc))
    session = _session_with_recipient()
    assert notify_event_confirmed(session, event, settings=_on(), evolution=spy) is False
    assert spy.sent == []


# ---------------------------------------------------------------------------
# 5) evento ainda 'a_confirmar' não dispara envio antes da confirmação
# ---------------------------------------------------------------------------
def test_a_confirmar_event_does_not_notify() -> None:
    spy = SpyEvolution()
    event = _event(status="a_confirmar")
    session = _session_with_recipient()
    assert notify_event_confirmed(session, event, settings=_on(), evolution=spy) is False
    assert spy.sent == []
    assert event.notificado_em is None


# ---------------------------------------------------------------------------
# 6) falha do Evolution não desfaz nada e deixa notificado_em NULL
# ---------------------------------------------------------------------------
def test_evolution_failure_does_not_break_and_leaves_notificado_em_null() -> None:
    spy = SpyEvolution(fail=True)
    event = _event()
    session = _session_with_recipient()
    # não levanta: a falha é engolida (logada) dentro do helper.
    assert notify_event_confirmed(session, event, settings=_on(), evolution=spy) is False
    assert event.notificado_em is None
    assert session.committed is False


# ---------------------------------------------------------------------------
# 7) outbound_guard NÃO é contornado
# ---------------------------------------------------------------------------
def test_outbound_guard_not_bypassed(monkeypatch) -> None:
    """Com um EvolutionClient REAL e ambiente não-produção, o envio é suprimido
    pelo guard (send_text simula sucesso sem rede). Se o guard fosse contornado, o
    transport bloqueante abaixo levantaria — provando que o único caminho de envio
    é o send_text guardado.
    """

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError(f"guard contornado — tocou a rede: {request.url}")

    transport = httpx.MockTransport(handler)
    real = httpx.Client

    def fake(*args, **kwargs):
        kwargs.pop("transport", None)
        return real(*args, transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "Client", fake)

    # não-produção COM credenciais: se o guard falhasse, send_text iria à rede.
    settings = Settings(
        app_env="staging",
        agenda_notify_enabled=True,
        evolution_api_url="http://evo:8080",
        evolution_api_key="SECRET_EVO_KEY",
    )
    event = _event()
    session = _session_with_recipient()
    # sem injetar evolution → usa EvolutionClient(settings) real (guardado).
    assert notify_event_confirmed(session, event, settings=settings) is True
    # guard suprimiu a rede, mas o envio "simulado" contou como sucesso.
    assert event.notificado_em is not None


# ---------------------------------------------------------------------------
# 8) modelo e migration espelham notificado_em
# ---------------------------------------------------------------------------
def test_model_and_migration_mirror_notificado_em() -> None:
    assert "notificado_em" in Event.__table__.columns
    col = Event.__table__.columns["notificado_em"]
    assert col.nullable is True

    mig = (
        pathlib.Path(__file__).resolve().parents[1]
        / "migrations"
        / "20260701_164352_evt7_events_notificado_em_aviso_confirmacao.sql"
    )
    sql = mig.read_text(encoding="utf-8").lower()
    assert "add column if not exists notificado_em timestamptz" in sql
