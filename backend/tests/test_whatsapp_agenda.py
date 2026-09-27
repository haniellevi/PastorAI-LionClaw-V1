import datetime as dt
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.services import whatsapp_agenda
from app.services.whatsapp_privilege import PrivilegeContext


IGREJA_ID = UUID("00000000-0000-0000-0000-000000000101")


def _event(**overrides):
    values = {
        "id": UUID("00000000-0000-0000-0000-000000000201"),
        "igreja_id": IGREJA_ID,
        "titulo": "Encontro com Deus",
        "tipo": "culto",
        "status": "confirmado",
        "data": dt.date(2026, 9, 28),
        "hora": "19:30",
        "recorrencia": "pontual",
        "dia_semana": None,
        "confirmado_em": dt.datetime(2026, 9, 20, tzinfo=dt.UTC),
        "confirmado_por": UUID("00000000-0000-0000-0000-000000000301"),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _context(*, roles=frozenset({'membro'}), sensitive=False, proof_id=None):
    return PrivilegeContext(
        igreja_id=IGREJA_ID,
        conversation_id=UUID("00000000-0000-0000-0000-000000000401"),
        inbound_message_id=UUID("00000000-0000-0000-0000-000000000402"),
        pessoa_id=UUID("00000000-0000-0000-0000-000000000403"),
        app_user_id=UUID("00000000-0000-0000-0000-000000000404"),
        roles=roles,
        role_snapshot=(),
        owned_cell_ids=(),
        credential_fingerprint='credential',
        phone_fingerprint='phone',
        authorization_fingerprint='authorization',
        proof_id=proof_id,
        proof_until=None,
        sensitive=sensitive,
        scope_fingerprint='scope',
        context_fingerprint='context',
    )


def test_agenda_gate_requires_both_releases_and_allowlists(monkeypatch):
    monkeypatch.setattr(whatsapp_agenda, "AGENDA_WHATSAPP_APPROVED_RELEASE_ID", None)
    monkeypatch.setenv("AGENDA_WHATSAPP_ENABLED_IGREJA_IDS", str(IGREJA_ID))
    assert not whatsapp_agenda.agenda_enabled_from_environment(IGREJA_ID)

    monkeypatch.setattr(whatsapp_agenda, "AGENDA_WHATSAPP_APPROVED_RELEASE_ID", "v2a-test")
    monkeypatch.setattr(whatsapp_agenda, "privilege_enabled_from_environment", lambda _: False)
    assert not whatsapp_agenda.agenda_enabled_from_environment(IGREJA_ID)

    monkeypatch.setattr(whatsapp_agenda, "privilege_enabled_from_environment", lambda _: True)
    assert whatsapp_agenda.agenda_enabled_from_environment(IGREJA_ID)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Encontro com Deus", "Encontro com Deus"),
        ("Culto de Celebração", "Culto de Celebração"),
        ("Festa da Ana", None),
        ("Culto com líder", None),
        ("Culto 11999998888", None),
        ("Culto na Rua das Flores", None),
        ("Culto <Especial>", "Culto Especial"),
        ("x" * 121, None),
    ],
)
def test_title_projection_is_conservative_and_neutralizes_delimiters(title, expected):
    assert whatsapp_agenda.project_institutional_title(title) == expected


def test_parse_query_clamps_period_page_and_draft_request():
    default = whatsapp_agenda.parse_agenda_query("quais eventos temos?")
    assert default == whatsapp_agenda.AgendaQuery(days=7, page=1, include_drafts=False)

    parsed = whatsapp_agenda.parse_agenda_query("agenda dos próximos 30 dias página 2 rascunhos")
    assert parsed == whatsapp_agenda.AgendaQuery(days=30, page=2, include_drafts=True)

    assert whatsapp_agenda.parse_agenda_query("agenda próximos 31 dias") is None
    assert whatsapp_agenda.parse_agenda_query("agenda 100 dias") is None
    assert whatsapp_agenda.parse_agenda_query("agenda página 100") is None


def test_weekly_occurrences_use_event_sunday_zero_and_do_not_precede_series_start():
    # 2026-10-04 is Sunday, and Event.dia_semana=0 means Sunday.
    event = _event(
        data=dt.date(2026, 10, 4),
        recorrencia="semanal",
        dia_semana=0,
    )
    occurrences = whatsapp_agenda.occurrences_for_event(
        event,
        start=dt.date(2026, 10, 1),
        end=dt.date(2026, 10, 17),
    )
    assert [occ.date for occ in occurrences] == [dt.date(2026, 10, 4), dt.date(2026, 10, 11)]

    event.data = dt.date(2026, 10, 11)
    assert [occ.date for occ in whatsapp_agenda.occurrences_for_event(
        event,
        start=dt.date(2026, 10, 1),
        end=dt.date(2026, 10, 17),
    )] == [dt.date(2026, 10, 11)]


def test_agenda_metadata_is_deny_all_when_malformed():
    assert not whatsapp_agenda.valid_agenda_reply_metadata({})
    assert not whatsapp_agenda.valid_agenda_reply_metadata({"agenda": {"page": 1}})
    assert whatsapp_agenda.valid_agenda_reply_metadata({
        "agenda": {
            "days": 7,
            "page": 1,
            "include_drafts": False,
            "snapshot_sha256": "a" * 64,
        }
    })


def test_snapshot_changes_when_only_internal_event_identity_changes():
    query = whatsapp_agenda.AgendaQuery(days=7, page=1, include_drafts=False)
    first = whatsapp_agenda.AgendaOccurrence(UUID(int=1), dt.date(2026, 9, 28), "19:30", "Culto")
    second = whatsapp_agenda.AgendaOccurrence(UUID(int=2), dt.date(2026, 9, 28), "19:30", "Culto")
    assert whatsapp_agenda._snapshot(query, (first,)) != whatsapp_agenda._snapshot(query, (second,))


def test_reply_uses_only_safe_event_projection_and_offers_secretary_when_empty(monkeypatch):
    class Session:
        def __init__(self, rows):
            self.rows = rows
            self.statement = None

        def execute(self, statement):
            self.statement = statement
            return SimpleNamespace(all=lambda: self.rows)

    context = _context()
    monkeypatch.setattr(whatsapp_agenda, "agenda_enabled_from_environment", lambda _tenant: True)
    monkeypatch.setattr(whatsapp_agenda, "require_tenant_scope", lambda *_args, **_kwargs: None)
    session = Session([(
        UUID("00000000-0000-0000-0000-000000000202"),
        IGREJA_ID,
        "Festa da Ana",  # must fall back to the server enum label, never leak this title.
        "culto",
        dt.date(2026, 9, 28),
        "19:30",
        "pontual",
        None,
        False,
    )])
    reply = whatsapp_agenda.resolve_agenda_reply(
        session,
        context=context,
        text="agenda próximos 7 dias",
        now=dt.datetime(2026, 9, 27, 3, tzinfo=dt.UTC),
    )
    assert reply is not None
    assert "Festa da Ana" not in reply.response
    assert "Culto" in reply.response
    assert "Período: 27/09/2026 a 03/10/2026, página 1." in reply.response
    assert not reply.offers_secretary
    compiled = str(session.statement)
    assert "events.descricao" not in compiled and "events.mensagem_confirmacao" not in compiled
    assert "events.confirmado_por" in compiled and "user_roles" in compiled

    empty = Session([])
    missing = whatsapp_agenda.resolve_agenda_reply(
        empty,
        context=context,
        text="agenda",
        now=dt.datetime(2026, 9, 27, 3, tzinfo=dt.UTC),
    )
    assert missing is not None and missing.offers_secretary
    assert missing.response.endswith("Quer falar com a secretaria da igreja?")


@pytest.mark.parametrize("roles", [
    frozenset({'membro'}),
    frozenset({'operador'}),
    frozenset({'lider_celula'}),
])
def test_non_pastoral_roles_cannot_begin_clerk_draft_flow(roles):
    context = _context(roles=roles)
    assert whatsapp_agenda.agenda_read_allowed(context)
    assert not whatsapp_agenda.agenda_draft_role_allowed(context)
    assert not whatsapp_agenda.agenda_drafts_allowed(context)


def test_pastor_can_begin_but_needs_clerk_proof_for_drafts():
    context = _context(roles=frozenset({'pastor'}))
    assert whatsapp_agenda.agenda_draft_role_allowed(context)
    assert not whatsapp_agenda.agenda_drafts_allowed(context)


def test_only_human_confirmed_title_is_projected_and_past_today_time_is_omitted(monkeypatch):
    class Session:
        def execute(self, _statement):
            return SimpleNamespace(all=lambda: [(
                UUID("00000000-0000-0000-0000-000000000203"),
                IGREJA_ID,
                "Encontro com Deus",
                "especial",
                dt.date(2026, 9, 27),
                "18:00",
                "pontual",
                None,
                True,
            )])

    monkeypatch.setattr(whatsapp_agenda, "agenda_enabled_from_environment", lambda _tenant: True)
    monkeypatch.setattr(whatsapp_agenda, "require_tenant_scope", lambda *_args, **_kwargs: None)
    context = _context()
    reply = whatsapp_agenda.resolve_agenda_reply(
        Session(),
        context=context,
        text="agenda",
        now=dt.datetime(2026, 9, 27, 22, 0, tzinfo=dt.UTC),
    )
    assert reply is not None and reply.offers_secretary
