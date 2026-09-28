from __future__ import annotations

import datetime as dt
from dataclasses import replace
from types import SimpleNamespace

import pytest
from uuid import UUID

from app.services.consolidation_privileged import (
    PendingConsolidationItem,
    consolidation_pending_reply,
    render_pending_consolidation_reply,
)


_CONSOLIDACAO = UUID('00000000-0000-0000-0000-0000000000c1')
_RESPONSAVEL = UUID('00000000-0000-0000-0000-0000000000b1')


def _item(
    item_id: UUID,
    *,
    revision: int = 0,
    task_type: str = 'fonovisita',
    due_at: dt.datetime | None = None,
    first_name: str | None = 'Maria',
    responsavel_id: UUID | None = _RESPONSAVEL,
    pessoa_id: UUID = UUID('00000000-0000-0000-0000-0000000000d1'),
) -> PendingConsolidationItem:
    return PendingConsolidationItem(
        work_queue_item_id=item_id,
        consolidacao_id=_CONSOLIDACAO,
        pessoa_id=pessoa_id,
        responsavel_id=responsavel_id,
        assignment_revision=revision,
        task_type=task_type,
        due_at=due_at,
        first_name=first_name,
    )


def test_current_responsible_reply_uses_only_first_name_type_and_deadline():
    reply = render_pending_consolidation_reply(
        (
            _item(
                UUID('12345678-90ab-cdef-0000-000000000001'),
                task_type='conectar_celula',
                due_at=dt.datetime(2026, 9, 29, 12, tzinfo=dt.timezone.utc),
            ),
        ),
        own_assignment=True,
        panel_link='https://app.igreja12.example/#consolidar',
    )

    assert reply.response == (
        'Você tem 1 pendência de consolidação: Maria, conexão com célula, '
        'prazo 29/09/2026 às 09:00, código P-1234567890. '
        'Abra o painel: https://app.igreja12.example/#consolidar'
    )
    assert len(reply.projection_sha256) == 64
    assert str(_CONSOLIDACAO) not in reply.response
    assert str(_RESPONSAVEL) not in reply.response
    assert 'telefone' not in reply.response.casefold()
    assert 'silva' not in reply.response.casefold()


def test_pending_reply_fingerprint_changes_when_assignment_changes_even_if_text_does_not():
    item_id = UUID('12345678-90ab-cdef-0000-000000000001')
    before = render_pending_consolidation_reply(
        (_item(item_id, revision=1),), own_assignment=True, panel_link=None
    )
    after = render_pending_consolidation_reply(
        (_item(item_id, revision=2),), own_assignment=True, panel_link=None
    )

    assert before.response == after.response
    assert before.projection_sha256 != after.projection_sha256


def test_current_responsible_projection_fences_name_type_and_deadline_changes():
    item_id = UUID('12345678-90ab-cdef-0000-000000000001')
    before = render_pending_consolidation_reply(
        (
            _item(
                item_id,
                task_type='conectar_celula',
                due_at=dt.datetime(2026, 9, 29, 12, tzinfo=dt.timezone.utc),
                first_name='Maria',
            ),
        ),
        own_assignment=True,
        panel_link=None,
    )
    after = render_pending_consolidation_reply(
        (
            _item(
                item_id,
                task_type='conectar_celula',
                due_at=dt.datetime(2026, 9, 29, 13, tzinfo=dt.timezone.utc),
                first_name='Ana',
            ),
        ),
        own_assignment=True,
        panel_link=None,
    )

    assert before.projection_sha256 != after.projection_sha256
    assert before.response != after.response


def test_pending_reply_hides_colliding_opaque_codes_instead_of_remapping_them():
    first = _item(UUID('12345678-90ab-cdef-0000-000000000001'))
    second = _item(UUID('12345678-90ff-ffff-0000-000000000002'))

    reply = render_pending_consolidation_reply(
        (first, second), own_assignment=False, panel_link=None
    )

    assert reply.response == 'Há 2 pendências de consolidação no seu escopo.'
    assert 'P-1234567890' not in reply.response
    assert 'Maria' not in reply.response


def test_current_responsible_reply_fails_closed_without_a_normalized_template_name():
    with pytest.raises(ValueError, match='projeção inválida'):
        render_pending_consolidation_reply(
            (_item(UUID('12345678-90ab-cdef-0000-000000000001'), first_name=None),),
            own_assignment=True,
            panel_link=None,
        )


def test_current_responsible_keeps_own_details_and_projects_other_pending_items_as_codes():
    own = _item(
        UUID('12345678-90ab-cdef-0000-000000000001'),
        task_type='conectar_celula',
        due_at=dt.datetime(2026, 9, 29, 12, tzinfo=dt.timezone.utc),
        first_name='Maria',
    )
    unassigned = _item(
        UUID('abcdef12-3456-7890-0000-000000000002'),
        first_name=None,
        responsavel_id=None,
        pessoa_id=UUID('00000000-0000-0000-0000-0000000000d2'),
    )
    assigned_elsewhere = _item(
        UUID('fedcba98-7654-3210-0000-000000000003'),
        first_name=None,
        responsavel_id=UUID('00000000-0000-0000-0000-0000000000b2'),
        pessoa_id=UUID('00000000-0000-0000-0000-0000000000d3'),
    )

    reply = render_pending_consolidation_reply(
        (own, unassigned, assigned_elsewhere),
        own_assignment=True,
        panel_link=None,
    )

    assert reply.response == (
        'Você tem 1 pendência de consolidação: Maria, conexão com célula, '
        'prazo 29/09/2026 às 09:00, código P-1234567890. Há 2 outras pendências de consolidação '
        'no seu escopo: P-ABCDEF1234, P-FEDCBA9876.'
    )
    assert 'Maria' in reply.response

    changed = render_pending_consolidation_reply(
        (own, _item(
            UUID('abcdef12-3456-7890-0000-000000000002'),
            first_name=None,
            responsavel_id=UUID('00000000-0000-0000-0000-0000000000b3'),
            pessoa_id=UUID('00000000-0000-0000-0000-0000000000d2'),
            revision=1,
        ), assigned_elsewhere),
        own_assignment=True,
        panel_link=None,
    )
    assert changed.projection_sha256 != reply.projection_sha256


def test_large_projection_is_deterministically_capped_without_other_people_names():
    names = ('Á' * 60, 'É' * 60, 'Í' * 60)
    items = []
    for position in range(1, 131):
        own_position = position >= 128
        item_id = UUID(f'{position:08x}-0000-0000-0000-000000000001')
        items.append(
            _item(
                item_id,
                task_type='conectar_celula' if own_position else 'fonovisita',
                due_at=(
                    dt.datetime(2026, 9, 29, 12, tzinfo=dt.timezone.utc)
                    if own_position
                    else None
                ),
                first_name=names[position - 128] if own_position else None,
                responsavel_id=(
                    _RESPONSAVEL
                    if own_position
                    else UUID('00000000-0000-0000-0000-0000000000b2')
                ),
            )
        )

    reply = render_pending_consolidation_reply(
        tuple(reversed(items)),
        own_assignment=True,
        panel_link='https://app.igreja12.example/#consolidar',
    )

    assert len(reply.response) <= 1_600
    assert 'Há 130 pendências de consolidação no seu escopo.' in reply.response
    assert 'Restam 120 pendências no painel.' in reply.response
    assert all(name in reply.response for name in names)
    assert reply.response.count('P-') == 10
    assert 'P-0000000B00' not in reply.response

    replay = render_pending_consolidation_reply(
        tuple(items),
        own_assignment=True,
        panel_link='https://app.igreja12.example/#consolidar',
    )
    assert replay == reply

    changed_items = list(items)
    changed_items[50] = replace(
        changed_items[50],
        responsavel_id=UUID('00000000-0000-0000-0000-0000000000b3'),
        assignment_revision=1,
    )
    changed = render_pending_consolidation_reply(
        tuple(changed_items),
        own_assignment=True,
        panel_link='https://app.igreja12.example/#consolidar',
    )
    assert changed.response == reply.response
    assert changed.projection_sha256 != reply.projection_sha256


def test_current_responsible_projection_includes_connection_and_fonovisita_without_surname(
    monkeypatch,
):
    import app.services.consolidation_privileged as privileged
    from app.services.whatsapp_privilege import PrivilegeContext

    igreja_id = UUID('00000000-0000-0000-0000-0000000000a1')
    pessoa_id = UUID('00000000-0000-0000-0000-0000000000d1')
    context = PrivilegeContext(
        igreja_id=igreja_id,
        conversation_id=UUID('00000000-0000-0000-0000-0000000000c2'),
        inbound_message_id=UUID('00000000-0000-0000-0000-0000000000c3'),
        pessoa_id=UUID('00000000-0000-0000-0000-0000000000d2'),
        app_user_id=_RESPONSAVEL,
        roles=frozenset({'pastor'}),
        role_snapshot=(),
        owned_cell_ids=(),
        credential_fingerprint='1' * 64,
        phone_fingerprint='2' * 64,
        authorization_fingerprint='3' * 64,
        proof_id=None,
        proof_until=None,
        sensitive=False,
        scope_fingerprint='4' * 64,
        context_fingerprint='5' * 64,
    )
    consolidacao = SimpleNamespace(
        id=_CONSOLIDACAO,
        igreja_id=igreja_id,
        pessoa_id=pessoa_id,
        responsavel_id=_RESPONSAVEL,
        assignment_revision=3,
        concluida=False,
        abandonada_em=None,
    )
    connection = SimpleNamespace(
        id=UUID('00000000-0000-0000-0000-0000000000e1'),
        igreja_id=igreja_id,
        consolidacao_id=_CONSOLIDACAO,
        pessoa_id=pessoa_id,
        responsavel_id=_RESPONSAVEL,
        tipo='conectar_celula',
        status='aberto',
        prazo=dt.datetime(2026, 9, 29, 12, tzinfo=dt.timezone.utc),
    )
    fono = SimpleNamespace(
        id=UUID('00000000-0000-0000-0000-0000000000e2'),
        igreja_id=igreja_id,
        consolidacao_id=_CONSOLIDACAO,
        pessoa_id=pessoa_id,
        responsavel_id=_RESPONSAVEL,
        tipo='fonovisita',
        status='aberto',
        prazo=None,
    )

    class _Result:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class _Session:
        calls = 0

        def execute(self, _statement):
            self.calls += 1
            if self.calls == 1:
                return _Result([(connection, consolidacao), (fono, consolidacao)])
            if self.calls == 2:
                return _Result([(pessoa_id, 'Maria Silva')])
            raise AssertionError('consulta inesperada')

    monkeypatch.setattr(privileged, 'require_tenant_scope', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(privileged, 'consolidation_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr(
        'app.config.get_settings',
        lambda: SimpleNamespace(frontend_url='https://app.igreja12.example'),
    )

    reply = consolidation_pending_reply(_Session(), context=context)

    assert reply is not None
    assert 'Maria, conexão com célula, prazo 29/09/2026 às 09:00, código P-0000000000' in reply.response
    assert 'Maria, fonovisita, prazo não definido, código P-0000000000' in reply.response
    assert 'Silva' not in reply.response
    assert str(_CONSOLIDACAO) not in reply.response


def test_current_responsible_projection_keeps_other_scope_items_opaque(monkeypatch):
    import app.services.consolidation_privileged as privileged
    from app.services.whatsapp_privilege import PrivilegeContext

    igreja_id = UUID('00000000-0000-0000-0000-0000000000a1')
    own_pessoa_id = UUID('00000000-0000-0000-0000-0000000000d1')
    own_consolidacao = SimpleNamespace(
        id=_CONSOLIDACAO,
        igreja_id=igreja_id,
        pessoa_id=own_pessoa_id,
        responsavel_id=_RESPONSAVEL,
        assignment_revision=3,
        concluida=False,
        abandonada_em=None,
    )
    unassigned_consolidacao = SimpleNamespace(
        id=UUID('00000000-0000-0000-0000-0000000000c2'),
        igreja_id=igreja_id,
        pessoa_id=UUID('00000000-0000-0000-0000-0000000000d2'),
        responsavel_id=None,
        assignment_revision=1,
        concluida=False,
        abandonada_em=None,
    )
    assigned_elsewhere_consolidacao = SimpleNamespace(
        id=UUID('00000000-0000-0000-0000-0000000000c3'),
        igreja_id=igreja_id,
        pessoa_id=UUID('00000000-0000-0000-0000-0000000000d3'),
        responsavel_id=UUID('00000000-0000-0000-0000-0000000000b2'),
        assignment_revision=2,
        concluida=False,
        abandonada_em=None,
    )

    def task(item_id, consolidacao, *, task_type='fonovisita', due_at=None):
        return SimpleNamespace(
            id=item_id,
            igreja_id=igreja_id,
            consolidacao_id=consolidacao.id,
            pessoa_id=consolidacao.pessoa_id,
            responsavel_id=consolidacao.responsavel_id,
            tipo=task_type,
            status='aberto',
            prazo=due_at,
        )

    own = task(
        UUID('12345678-90ab-cdef-0000-000000000001'),
        own_consolidacao,
        task_type='conectar_celula',
        due_at=dt.datetime(2026, 9, 29, 12, tzinfo=dt.timezone.utc),
    )
    unassigned = task(
        UUID('abcdef12-3456-7890-0000-000000000002'),
        unassigned_consolidacao,
    )
    assigned_elsewhere = task(
        UUID('fedcba98-7654-3210-0000-000000000003'),
        assigned_elsewhere_consolidacao,
    )
    context = PrivilegeContext(
        igreja_id=igreja_id,
        conversation_id=UUID('00000000-0000-0000-0000-0000000000a2'),
        inbound_message_id=UUID('00000000-0000-0000-0000-0000000000a3'),
        pessoa_id=UUID('00000000-0000-0000-0000-0000000000a4'),
        app_user_id=_RESPONSAVEL,
        roles=frozenset({'pastor'}),
        role_snapshot=(),
        owned_cell_ids=(),
        credential_fingerprint='1' * 64,
        phone_fingerprint='2' * 64,
        authorization_fingerprint='3' * 64,
        proof_id=None,
        proof_until=None,
        sensitive=False,
        scope_fingerprint='4' * 64,
        context_fingerprint='5' * 64,
    )

    class _Result:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class _Session:
        calls = 0

        def execute(self, _statement):
            self.calls += 1
            if self.calls == 1:
                return _Result([
                    (own, own_consolidacao),
                    (unassigned, unassigned_consolidacao),
                    (assigned_elsewhere, assigned_elsewhere_consolidacao),
                ])
            if self.calls == 2:
                return _Result([(own_pessoa_id, 'Maria Silva')])
            raise AssertionError('nomes de outras pendências não podem ser consultados')

    monkeypatch.setattr(privileged, 'require_tenant_scope', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(privileged, 'consolidation_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr(
        'app.config.get_settings',
        lambda: SimpleNamespace(frontend_url='https://app.igreja12.example'),
    )

    reply = consolidation_pending_reply(_Session(), context=context)

    assert reply is not None
    assert reply.response == (
        'Você tem 1 pendência de consolidação: Maria, conexão com célula, '
        'prazo 29/09/2026 às 09:00, código P-1234567890. Há 2 outras pendências de consolidação '
        'no seu escopo: P-ABCDEF1234, P-FEDCBA9876. '
        'Abra o painel: https://app.igreja12.example/#consolidar'
    )
    assert 'Silva' not in reply.response
    assert str(unassigned_consolidacao.id) not in reply.response
    assert str(assigned_elsewhere_consolidacao.id) not in reply.response


def test_lider_celula_projection_is_limited_to_its_own_fonovisita(monkeypatch):
    import app.services.consolidation_privileged as privileged
    from app.services.whatsapp_privilege import PrivilegeContext

    igreja_id = UUID('00000000-0000-0000-0000-0000000000a1')
    own_person_id = UUID('00000000-0000-0000-0000-0000000000d1')
    other_person_id = UUID('00000000-0000-0000-0000-0000000000d2')
    own_track = SimpleNamespace(
        id=_CONSOLIDACAO,
        igreja_id=igreja_id,
        pessoa_id=own_person_id,
        responsavel_id=_RESPONSAVEL,
        assignment_revision=3,
        concluida=False,
        abandonada_em=None,
    )
    other_track = SimpleNamespace(
        id=UUID('00000000-0000-0000-0000-0000000000c2'),
        igreja_id=igreja_id,
        pessoa_id=other_person_id,
        responsavel_id=UUID('00000000-0000-0000-0000-0000000000b2'),
        assignment_revision=4,
        concluida=False,
        abandonada_em=None,
    )

    def task(item_id, track):
        return SimpleNamespace(
            id=item_id,
            igreja_id=igreja_id,
            consolidacao_id=track.id,
            pessoa_id=track.pessoa_id,
            responsavel_id=track.responsavel_id,
            tipo='fonovisita',
            status='aberto',
            prazo=None,
        )

    own = task(UUID('12345678-90ab-cdef-0000-000000000001'), own_track)
    other = task(UUID('abcdef12-3456-7890-0000-000000000002'), other_track)
    context = PrivilegeContext(
        igreja_id=igreja_id,
        conversation_id=UUID('00000000-0000-0000-0000-0000000000a2'),
        inbound_message_id=UUID('00000000-0000-0000-0000-0000000000a3'),
        pessoa_id=UUID('00000000-0000-0000-0000-0000000000a4'),
        app_user_id=_RESPONSAVEL,
        roles=frozenset({'lider_celula'}),
        role_snapshot=(),
        owned_cell_ids=(),
        credential_fingerprint='1' * 64,
        phone_fingerprint='2' * 64,
        authorization_fingerprint='3' * 64,
        proof_id=None,
        proof_until=None,
        sensitive=False,
        scope_fingerprint='4' * 64,
        context_fingerprint='5' * 64,
    )

    class _Result:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class _Session:
        calls = 0

        def execute(self, _statement):
            self.calls += 1
            if self.calls == 1:
                return _Result([(own, own_track), (other, other_track)])
            if self.calls == 2:
                return _Result([(own_person_id, 'Maria Silva')])
            raise AssertionError('consulta inesperada')

    monkeypatch.setattr(privileged, 'require_tenant_scope', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(privileged, 'consolidation_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr('app.config.get_settings', lambda: SimpleNamespace(frontend_url=''))

    reply = consolidation_pending_reply(_Session(), context=context)

    assert reply is not None
    assert 'Maria, fonovisita, prazo não definido, código P-1234567890' in reply.response
    assert 'P-ABCDEF1234' not in reply.response
    assert 'Há 2 pendências' not in reply.response


def test_current_responsible_items_take_priority_over_the_opaque_projection_cap(monkeypatch):
    import app.services.consolidation_privileged as privileged
    from app.services.whatsapp_privilege import PrivilegeContext

    igreja_id = UUID('00000000-0000-0000-0000-0000000000a1')
    own_person_id = UUID('00000000-0000-0000-0000-0000000000d1')
    other_person_id = UUID('00000000-0000-0000-0000-0000000000d2')
    own_track = SimpleNamespace(
        id=UUID('00000000-0000-0000-0000-0000000000c1'),
        igreja_id=igreja_id,
        pessoa_id=own_person_id,
        responsavel_id=_RESPONSAVEL,
        assignment_revision=3,
        concluida=False,
        abandonada_em=None,
    )
    other_track = SimpleNamespace(
        id=UUID('00000000-0000-0000-0000-0000000000c2'),
        igreja_id=igreja_id,
        pessoa_id=other_person_id,
        responsavel_id=UUID('00000000-0000-0000-0000-0000000000b2'),
        assignment_revision=1,
        concluida=False,
        abandonada_em=None,
    )

    def task(item_id, track, *, due_at=None):
        return SimpleNamespace(
            id=item_id,
            igreja_id=igreja_id,
            consolidacao_id=track.id,
            pessoa_id=track.pessoa_id,
            responsavel_id=track.responsavel_id,
            tipo='conectar_celula' if due_at is not None else 'fonovisita',
            status='aberto',
            prazo=due_at,
        )

    others = tuple(
        task(UUID(f'{position:08x}-0000-0000-0000-000000000001'), other_track)
        for position in range(1, 11)
    )
    own = task(
        UUID('ffffffff-0000-0000-0000-000000000001'),
        own_track,
        due_at=dt.datetime(2026, 9, 29, 12, tzinfo=dt.timezone.utc),
    )
    context = PrivilegeContext(
        igreja_id=igreja_id,
        conversation_id=UUID('00000000-0000-0000-0000-0000000000a2'),
        inbound_message_id=UUID('00000000-0000-0000-0000-0000000000a3'),
        pessoa_id=UUID('00000000-0000-0000-0000-0000000000a4'),
        app_user_id=_RESPONSAVEL,
        roles=frozenset({'pastor'}),
        role_snapshot=(),
        owned_cell_ids=(),
        credential_fingerprint='1' * 64,
        phone_fingerprint='2' * 64,
        authorization_fingerprint='3' * 64,
        proof_id=None,
        proof_until=None,
        sensitive=False,
        scope_fingerprint='4' * 64,
        context_fingerprint='5' * 64,
    )

    class _Result:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class _Session:
        calls = 0

        def execute(self, _statement):
            self.calls += 1
            if self.calls == 1:
                return _Result([(item, other_track) for item in others] + [(own, own_track)])
            if self.calls == 2:
                return _Result([(own_person_id, 'Ana Silva')])
            raise AssertionError('somente o nome da responsabilidade atual pode ser consultado')

    monkeypatch.setattr(privileged, 'require_tenant_scope', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(privileged, 'consolidation_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr('app.config.get_settings', lambda: SimpleNamespace(frontend_url=''))

    reply = consolidation_pending_reply(_Session(), context=context)

    assert reply is not None
    assert 'Ana, conexão com célula, prazo 29/09/2026 às 09:00' in reply.response
    assert reply.response.count('P-') == 10
    assert 'P-0000000A00' not in reply.response
    assert 'Restam 1 pendência no painel.' in reply.response


def test_delivery_revalidation_locks_consolidation_without_waiting_for_assignment():
    from sqlalchemy.dialects import postgresql
    import app.services.consolidation_privileged as privileged

    statement = privileged._pending_statement(
        UUID('00000000-0000-0000-0000-0000000000a1'),
        lock_sources=True,
    )
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert 'FOR UPDATE OF consolidacoes SKIP LOCKED' in compiled
