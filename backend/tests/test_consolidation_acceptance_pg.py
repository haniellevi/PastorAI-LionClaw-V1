"""Explicit acceptance uses the real V3 workflow and tenant-scoped PG sessions."""
from pathlib import Path
import datetime as dt
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from tests.test_consolidation_workflow_pg import (
    workflow_database, rls_database_url, _seed, _insert_track, _factory, _scoped, _actor,
)
from app.db.models import Consolidacao
from app.services.consolidation_workflow import assign_consolidacao, complete_fonovisita

pytestmark = pytest.mark.rls_integration


def test_assignment_invites_without_replacing_effective_responsible(workflow_database):
    values = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, values)
    session = _scoped(_factory(workflow_database), values['tenant'])
    try:
        result = assign_consolidacao(
            session, _actor(values['tenant'], values['actor']), consolidacao_id=track,
            responsavel_id=values['target_a'], expected_assignment_revision=None, whatsapp=False,
        )
        assert result.consolidacao.responsavel_id == values['actor']
        assert result.atribuicao.status == 'atribuida'
        assert result.atribuicao.prazo_aceite - result.atribuicao.criada_em == dt.timedelta(hours=24)
    finally:
        session.rollback()
        session.close()


def _invite(session, values, track, key='target_a'):
    return assign_consolidacao(
        session, _actor(values['tenant'], values['actor']), consolidacao_id=track,
        responsavel_id=values[key], expected_assignment_revision=None, whatsapp=False,
    ).atribuicao


def _answer(session, values, track, invitation, *, accept=True, key='target_a'):
    from app.services.consolidation_workflow import respond_consolidacao_invitation
    return respond_consolidacao_invitation(
        session, _actor(values['tenant'], values[key]), consolidacao_id=track,
        atribuicao_id=invitation.id, aceitar=accept,
    )


@pytest.mark.parametrize('accept', [True, False])
def test_answer_and_repeat_are_atomic_and_keep_operational_deadline(workflow_database, accept):
    v = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, v)
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        before = s.execute(text('select prazo from work_queue_items where id=:id'), {'id': queue}).scalar_one()
        invitation = _invite(s, v, track)
        assert _invite(s, v, track).id == invitation.id
        row = _answer(s, v, track, invitation, accept=accept)
        assert row.status == ('aceita' if accept else 'recusada')
        answered = row.respondida_em
        assert _answer(s, v, track, invitation, accept=accept).respondida_em == answered
        if accept:
            assert _invite(s, v, track).id == invitation.id
        s.commit()
        current = s.get(Consolidacao, track)
        assert current.responsavel_id == v['target_a' if accept else 'actor']
        actual = s.execute(text('select responsavel_id,prazo from work_queue_items where id=:id'), {'id': queue}).one()
        assert actual == (current.responsavel_id, before)


def test_first_assignment_requires_acceptance_before_completion(workflow_database):
    v = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, v)
    with workflow_database.begin() as c:
        c.execute(text('update consolidacoes set responsavel_id=null where id=:id'), {'id': track})
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        invitation = _invite(s, v, track)
        s.commit()
        with pytest.raises(HTTPException) as exc:
            complete_fonovisita(s, _actor(v['tenant'], v['target_a']), consolidacao_id=track,
                               work_queue_item_id=queue, expected_assignment_revision=None, whatsapp=False)
        assert exc.value.status_code == 403
        s.rollback()
        _answer(s, v, track, invitation)
        complete_fonovisita(s, _actor(v['tenant'], v['target_a']), consolidacao_id=track,
                           work_queue_item_id=queue, expected_assignment_revision=None, whatsapp=False)
        s.commit()
        assert s.execute(text('select status from work_queue_items where id=:id'), {'id': queue}).scalar_one() == 'resolvido'


def test_replacement_fences_old_invitation_and_keeps_legacy_holder(workflow_database):
    v = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, v)
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        old = _invite(s, v, track)
        new = _invite(s, v, track, 'target_b')
        s.commit()
        assert old.status == 'substituida'
        assert s.get(Consolidacao, track).responsavel_id == v['actor']
        with pytest.raises(HTTPException) as exc:
            _answer(s, v, track, old)
        assert exc.value.status_code == 409
        s.rollback()
        _answer(s, v, track, new, key='target_b')
        s.commit()
        assert s.get(Consolidacao, track).responsavel_id == v['target_b']


@pytest.mark.parametrize('elapsed', [dt.timedelta(0), dt.timedelta(microseconds=1)])
def test_expiry_at_boundary_cannot_accept_or_extend(workflow_database, monkeypatch, elapsed):
    from app.services import consolidation_workflow as workflow
    v = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, v)
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        invitation = _invite(s, v, track)
        deadline = invitation.prazo_aceite
        monkeypatch.setattr(workflow, '_server_now', lambda db: deadline + elapsed)
        row = _answer(s, v, track, invitation)
        assert row.status == 'expirada'
        assert _answer(s, v, track, invitation).status == 'expirada'
        s.commit()
        assert s.get(Consolidacao, track).responsavel_id == v['actor']
        assert row.prazo_aceite == deadline


@pytest.mark.parametrize('mutation', [
    "update app_users set status='inativo' where id=:id",
    "update app_users set pessoa_id=null where id=:id",
    "update pessoas set arquivada_em=now() where id=(select pessoa_id from app_users where id=:id)",
    "delete from user_roles where user_id=:id",
])
@pytest.mark.parametrize('accept', [True, False])
def test_answer_revalidates_active_identity_link_and_capability(workflow_database, mutation, accept):
    v = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, v)
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        invitation = _invite(s, v, track)
        s.commit()
        with workflow_database.begin() as c:
            c.execute(text(mutation), {'id': v['target_a']})
        with pytest.raises(HTTPException) as exc:
            _answer(s, v, track, invitation, accept=accept)
        assert exc.value.status_code in (403, 404, 422)
        s.rollback()
        assert s.get(Consolidacao, track).responsavel_id == v['actor']


def test_only_recipient_and_tenant_can_answer_and_rls_hides_history(workflow_database):
    from app.db.models import ConsolidacaoAtribuicao
    from app.services.consolidation_workflow import respond_consolidacao_invitation
    v = _seed(workflow_database)
    other = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, v)
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        invitation = _invite(s, v, track)
        s.commit()
        invitation_id = invitation.id
        with pytest.raises(HTTPException) as exc:
            _answer(s, v, track, invitation, key='actor')
        assert exc.value.status_code == 403
        s.rollback()
    with _scoped(_factory(workflow_database), other['tenant']) as s:
        assert list(s.execute(select(ConsolidacaoAtribuicao)).scalars()) == []
        with pytest.raises(HTTPException) as exc:
            respond_consolidacao_invitation(s, _actor(other['tenant'], other['actor']),
                consolidacao_id=track, atribuicao_id=invitation_id, aceitar=True)
        assert exc.value.status_code == 404
        s.rollback()
        with pytest.raises(Exception) as denied:
            s.execute(text("insert into consolidacao_atribuicoes(igreja_id,consolidacao_id,responsavel_id,atribuida_por,criada_em,prazo_aceite) values(:tenant,:track,:user,:user,now(),now()+interval '24 hours')"),
                      {'tenant': v['tenant'], 'track': track, 'user': v['target_a']})
        assert 'row-level security' in str(denied.value)
        s.rollback()


def test_queue_self_assignment_records_immediate_acceptance(workflow_database):
    v = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, v)
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        result = assign_consolidacao(s, _actor(v['tenant'], v['target_a']),
            consolidacao_id=track, responsavel_id=v['target_a'], expected_assignment_revision=None,
            whatsapp=False, expected_work_queue_item_id=queue, work_queue_action='assume')
        assert result.atribuicao.status == 'aceita'
        assert result.atribuicao.autoatribuicao is True
        assert result.consolidacao.responsavel_id == v['target_a']
        s.commit()
        again = assign_consolidacao(s, _actor(v['tenant'], v['target_a']),
            consolidacao_id=track, responsavel_id=v['target_a'], expected_assignment_revision=None,
            whatsapp=False, expected_work_queue_item_id=queue, work_queue_action='assume')
        assert again.consolidacao.responsavel_id == v['target_a']
        assert s.execute(text('select count(*) from consolidacao_atribuicoes')).scalar_one() == 1


def test_accept_and_replacement_serialize_on_track(workflow_database):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    v = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, v)
    factory = _factory(workflow_database)
    with _scoped(factory, v['tenant']) as s:
        invitation = _invite(s, v, track)
        s.commit()
    barrier = threading.Barrier(2)
    def accept():
        with _scoped(factory, v['tenant']) as s:
            barrier.wait(timeout=5)
            try:
                row = _answer(s, v, track, invitation)
                s.commit()
                return row.status
            except HTTPException as exc:
                s.rollback()
                return exc.status_code
    def replace():
        with _scoped(factory, v['tenant']) as s:
            barrier.wait(timeout=5)
            row = _invite(s, v, track, 'target_b')
            s.commit()
            return row.status
    with ThreadPoolExecutor(2) as pool:
        a, b = pool.submit(accept), pool.submit(replace)
        assert a.result(timeout=10) in ('aceita', 409)
        assert b.result(timeout=10) == 'atribuida'
    with _scoped(factory, v['tenant']) as s:
        holder = s.get(Consolidacao, track).responsavel_id
        assert holder in (v['actor'], v['target_a'])
        assert s.execute(text("select count(*) from consolidacao_atribuicoes where status='atribuida'")).scalar_one() == 1


def test_panel_http_persists_invitation_and_answer_across_sessions(workflow_database, app):
    from fastapi.testclient import TestClient
    from app.db.session import get_db
    from app.deps import get_current_user
    v = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, v)
    factory = _factory(workflow_database)
    def session_dependency():
        with _scoped(factory, v['tenant']) as s:
            yield s
    app.dependency_overrides[get_db] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: _actor(v['tenant'], v['actor'])
    with TestClient(app) as client:
        invited = client.post('/pipeline/assign-consolidador', json={
            'consolidacaoId': str(track), 'responsavelId': str(v['target_a']),
        })
        assert invited.status_code == 200, invited.text
        assert invited.json()['status'] == 'invited'
        assert invited.json()['responsavelId'] == str(v['actor'])
        invitation_id = invited.json()['atribuicaoId']
        listed = client.get('/consolidacao/atribuicoes')
        assert listed.status_code == 200, listed.text
        assert listed.json()['items'][0]['convite']['id'] == invitation_id
        url = f'/consolidacao/{track}/atribuicoes/{invitation_id}/resposta'
        assert client.post(url, json={'aceitar': True}).status_code == 403
        app.dependency_overrides[get_current_user] = lambda: _actor(v['tenant'], v['target_a'])
        assert client.post(url, json={'aceitar': 'true'}).status_code == 422
        answered = client.post(url, json={'aceitar': True})
        assert answered.status_code == 200, answered.text
        assert answered.json()['status'] == 'aceita'
        listed = client.get('/consolidacao/atribuicoes').json()
        assert listed['items'][0]['responsavelId'] == str(v['target_a'])


def test_accept_waiting_for_track_lock_expires_using_actual_server_clock(workflow_database):
    from concurrent.futures import ThreadPoolExecutor
    import time
    v = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, v)
    factory = _factory(workflow_database)
    with workflow_database.begin() as c:
        invitation_id = c.execute(text("insert into consolidacao_atribuicoes(igreja_id,consolidacao_id,responsavel_id,atribuida_por,criada_em,prazo_aceite) values(:tenant,:track,:target_a,:actor,statement_timestamp()-interval '24 hours'+interval '1 second',statement_timestamp()+interval '1 second') returning id"), dict(v, track=track)).scalar_one()
    from app.services.consolidation_workflow import respond_consolidacao_invitation
    blocker = _scoped(factory, v['tenant'])
    blocker.execute(text('select id from consolidacoes where id=:id for update'), {'id': track})
    def answer_after_lock():
        with _scoped(factory, v['tenant']) as s:
            result = respond_consolidacao_invitation(s, _actor(v['tenant'], v['target_a']),
                consolidacao_id=track, atribuicao_id=invitation_id, aceitar=True)
            s.commit()
            return result.status
    try:
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(answer_after_lock)
            time.sleep(1.2)
            blocker.commit()
            assert future.result(timeout=10) == 'expirada'
    finally:
        blocker.close()
    with _scoped(factory, v['tenant']) as s:
        assert s.get(Consolidacao, track).responsavel_id == v['actor']


def test_accepted_responsible_losing_capability_cannot_complete(workflow_database):
    v = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, v)
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        invitation = _invite(s, v, track)
        _answer(s, v, track, invitation)
        s.commit()
        with workflow_database.begin() as c:
            c.execute(text('delete from user_roles where user_id=:id'), {'id': v['target_a']})
        with pytest.raises(HTTPException) as exc:
            complete_fonovisita(s, _actor(v['tenant'], v['target_a']), consolidacao_id=track,
                work_queue_item_id=queue, expected_assignment_revision=None, whatsapp=False)
        assert exc.value.status_code in (403, 422)
        s.rollback()
        assert s.execute(text('select status from work_queue_items where id=:id'), {'id': queue}).scalar_one() == 'assumido'


def test_cross_tenant_foreign_keys_and_force_rls(workflow_database):
    from sqlalchemy.exc import IntegrityError
    v = _seed(workflow_database)
    other = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, other)
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        with pytest.raises(IntegrityError):
            s.execute(text("insert into consolidacao_atribuicoes(igreja_id,consolidacao_id,responsavel_id,atribuida_por,criada_em,prazo_aceite) values(:tenant,:track,:user,:user,now(),now()+interval '24 hours')"),
                      {'tenant': v['tenant'], 'track': track, 'user': v['actor']})
        s.rollback()
    with workflow_database.connect() as c:
        assert c.execute(text("select relrowsecurity,relforcerowsecurity from pg_class where oid='consolidacao_atribuicoes'::regclass")).one() == (True, True)
        assert c.execute(text("select has_table_privilege('authenticated','consolidacao_atribuicoes','DELETE')")).scalar_one() is False


def test_read_does_not_lock_or_write_even_with_writer_holding_track(workflow_database):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy import event
    from app.routers.consolidacao import list_assignments
    v = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, v)
    factory = _factory(workflow_database)
    with _scoped(factory, v['tenant']) as s:
        _invite(s, v, track)
        s.commit()
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.upper())
    with _scoped(factory, v['tenant']) as blocker:
        blocker.execute(text('select id from consolidacoes where id=:id for update'), {'id': track})
        event.listen(workflow_database, 'before_cursor_execute', capture)
        def read():
            with _scoped(factory, v['tenant']) as s:
                return list_assignments(db=s, current_user=_actor(v['tenant'], v['actor']))
        try:
            with ThreadPoolExecutor(1) as pool:
                assert len(pool.submit(read).result(timeout=3).items) == 1
            assert not any('FOR UPDATE' in sql or sql.lstrip().startswith(('UPDATE ', 'INSERT ', 'DELETE ')) for sql in statements)
        finally:
            event.remove(workflow_database, 'before_cursor_execute', capture)


def test_cursor_does_not_skip_valid_invitation_when_first_fifty_expire(workflow_database):
    from app.routers.consolidacao import list_assignments
    v = _seed(workflow_database)
    with workflow_database.begin() as c:
        c.execute(text("update user_roles set papel='lider_celula' where user_id=:id"), {'id': v['target_a']})
        for index in range(51):
            person, track = uuid.uuid4(), uuid.UUID(int=1000 + index)
            params = {'person': person, 'track': track, 'tenant': v['tenant'],
                      'recipient': v['target_a'], 'author': v['actor'], 'age': 25 if index < 50 else 0}
            c.execute(text('insert into pessoas(id,igreja_id,telefone) values(:person,:tenant,:phone)'),
                      dict(params, phone=f'55000000{index:05d}'))
            c.execute(text("insert into consolidacoes(id,igreja_id,pessoa_id,tipo,responsavel_id,progresso,concluida) values(:track,:tenant,:person,'individual',null,0,false)"), params)
            c.execute(text("insert into consolidacao_atribuicoes(igreja_id,consolidacao_id,responsavel_id,atribuida_por,criada_em,prazo_aceite) values(:tenant,:track,:recipient,:author,statement_timestamp()-:age * interval '1 hour',statement_timestamp()-:age * interval '1 hour'+interval '24 hours')"), params)
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        first = list_assignments(db=s, current_user=_actor(v['tenant'], v['target_a']))
        assert first.items == []
        assert first.nextCursor == str(uuid.UUID(int=1049))
        second = list_assignments(after=uuid.UUID(first.nextCursor), db=s,
                                  current_user=_actor(v['tenant'], v['target_a']))
        assert [row.id for row in second.items] == [str(uuid.UUID(int=1050))]
        assert second.nextCursor is None
        assert s.execute(text("select count(*) from consolidacao_atribuicoes where status='expirada'")).scalar_one() == 0


@pytest.mark.parametrize('sibling_status,expected', [('aberto', ['conectar_celula','fonovisita']), ('resolvido', ['fonovisita'])])
def test_read_projects_every_active_assignment_capability(workflow_database, sibling_status, expected):
    from app.routers.consolidacao import list_assignments
    v = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, v)
    with workflow_database.begin() as c:
        c.execute(text("insert into work_queue_items(igreja_id,consolidacao_id,tipo,titulo,pessoa_id,status,prioridade) values(:tenant,:track,'conectar_celula','Conexão sintética',:person,:status,1)"),
                  {'tenant': v['tenant'], 'track': track, 'person': v['person'], 'status': sibling_status})
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        rows = list_assignments(db=s, current_user=_actor(v['tenant'], v['actor']))
        assert rows.items[0].tiposNecessarios == expected


@pytest.mark.parametrize('key,open_item', [('actor', False), ('target_b', True)])
def test_queue_cannot_cancel_pending_invitation(workflow_database, key, open_item):
    v = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, v)
    if open_item:
        with workflow_database.begin() as c:
            c.execute(text("update work_queue_items set status='aberto',responsavel_id=null where id=:id"), {'id': queue})
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        invitation = _invite(s, v, track)
        s.commit()
        revision = s.get(Consolidacao, track).assignment_revision
        with pytest.raises(HTTPException) as exc:
            assign_consolidacao(s, _actor(v['tenant'], v[key]), consolidacao_id=track,
                responsavel_id=v[key], expected_assignment_revision=None, whatsapp=False,
                expected_work_queue_item_id=queue, work_queue_action='assume')
        assert exc.value.status_code == 409
        assert exc.value.detail == 'Há convite pendente para outro responsável'
        s.rollback()
        s.refresh(invitation)
        assert invitation.status == 'atribuida'
        assert s.get(Consolidacao, track).assignment_revision == revision
        assert s.get(Consolidacao, track).responsavel_id == v['actor']


def test_legacy_holder_assume_is_noop(workflow_database):
    v = _seed(workflow_database)
    track, queue = _insert_track(workflow_database, v)
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        revision = s.get(Consolidacao, track).assignment_revision
        before = s.execute(text('select responsavel_id,status from work_queue_items where id=:id'), {'id': queue}).one()
        assign_consolidacao(s, _actor(v['tenant'], v['actor']), consolidacao_id=track,
            responsavel_id=v['actor'], expected_assignment_revision=None, whatsapp=False,
            expected_work_queue_item_id=queue, work_queue_action='assume')
        s.commit()
        assert s.get(Consolidacao, track).assignment_revision == revision
        assert s.execute(text('select responsavel_id,status from work_queue_items where id=:id'), {'id': queue}).one() == before
        assert s.execute(text('select count(*) from consolidacao_atribuicoes')).scalar_one() == 0


@pytest.mark.parametrize('mutation', [
    "responsavel_id=:target_b", "atribuida_por=:target_b",
    "criada_em=criada_em+interval '1 hour',prazo_aceite=prazo_aceite+interval '1 hour'",
    "prazo_aceite=prazo_aceite+interval '1 hour'", "autoatribuicao=true",
    "igreja_id=:other_tenant", "consolidacao_id=:other_track",
])
def test_invitation_identity_is_immutable_for_authenticated_role(workflow_database, mutation):
    from sqlalchemy.exc import DBAPIError
    v = _seed(workflow_database)
    other = _seed(workflow_database)
    track, _ = _insert_track(workflow_database, v)
    other_track, _ = _insert_track(workflow_database, other)
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        invitation = _invite(s, v, track)
        s.commit()
        with pytest.raises(DBAPIError, match='imutáveis'):
            s.execute(text("update consolidacao_atribuicoes set status='aceita',respondida_em=now(),"+mutation+" where id=:id"), dict(v, id=invitation.id, other_tenant=other['tenant'], other_track=other_track))
        s.rollback()


@pytest.mark.parametrize('terminal', ['aceita', 'recusada', 'expirada', 'substituida'])
def test_terminal_invitation_cannot_change(workflow_database, terminal):
    from sqlalchemy.exc import DBAPIError
    v = _seed(workflow_database)
    track, _ = _insert_track(workflow_database, v)
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        invitation = _invite(s, v, track)
        s.execute(text('update consolidacao_atribuicoes set status=:status,respondida_em=now() where id=:id'), {'id': invitation.id, 'status': terminal})
        s.commit()
        for status in ('atribuida', 'aceita', 'recusada', 'expirada', 'substituida'):
            with pytest.raises(DBAPIError, match='Transição'):
                s.execute(text('update consolidacao_atribuicoes set status=:status where id=:id'), {'id': invitation.id, 'status': status})
            s.rollback()


@pytest.mark.parametrize('mutation', ["update app_users set status='inativo' where id=:id", "delete from user_roles where user_id=:id", "update user_roles set papel='convidado' where user_id=:id"])
def test_invitation_rejects_revoked_or_guest_before_write(workflow_database, mutation):
    v = _seed(workflow_database)
    track, _ = _insert_track(workflow_database, v)
    with workflow_database.begin() as c:
        c.execute(text(mutation), {'id': v['target_a']})
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        with pytest.raises(HTTPException) as exc:
            _invite(s, v, track)
        assert exc.value.status_code in (404, 422)
        assert s.execute(text('select count(*) from consolidacao_atribuicoes')).scalar_one() == 0


def test_invitation_other_church_returns_404_before_write(workflow_database):
    v = _seed(workflow_database)
    other = _seed(workflow_database)
    track, _ = _insert_track(workflow_database, v)
    v['target_a'] = other['target_a']
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        with pytest.raises(HTTPException) as exc:
            _invite(s, v, track)
        assert exc.value.status_code == 404
        assert s.execute(text('select count(*) from consolidacao_atribuicoes')).scalar_one() == 0


def test_panel_accepts_legacy_null_status(workflow_database):
    from app.routers.consolidacao import list_assignments
    v = _seed(workflow_database)
    track, _ = _insert_track(workflow_database, v)
    with workflow_database.begin() as c:
        c.execute(text('alter table app_users alter column status drop not null'))
        c.execute(text('update app_users set status=null where igreja_id=:tenant'), v)
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        invitation = _invite(s, v, track)
        assert list_assignments(db=s, current_user=_actor(v['tenant'], v['target_a'])).items
        assert _answer(s, v, track, invitation).status == 'aceita'


def test_whatsapp_rejects_capable_cell_leader_recipient(workflow_database):
    v = _seed(workflow_database)
    track, _ = _insert_track(workflow_database, v)
    with workflow_database.begin() as c:
        c.execute(text("update user_roles set papel='lider_celula' where user_id=:id"), {'id': v['target_a']})
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        with pytest.raises(HTTPException) as exc:
            assign_consolidacao(s, _actor(v['tenant'], v['actor']), consolidacao_id=track,
                responsavel_id=v['target_a'], expected_assignment_revision=0, whatsapp=True)
        assert exc.value.status_code == 422
        assert s.execute(text('select count(*) from consolidacao_atribuicoes')).scalar_one() == 0


def test_get_projects_expired_without_persisting(workflow_database, monkeypatch):
    from app.routers.consolidacao import list_assignments
    from app.services import consolidation_workflow as workflow
    v = _seed(workflow_database)
    track, _ = _insert_track(workflow_database, v)
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        invitation = _invite(s, v, track)
        s.commit()
        monkeypatch.setattr(workflow, '_server_now', lambda db: invitation.prazo_aceite)
        page = list_assignments(db=s, current_user=_actor(v['tenant'], v['actor']))
        assert page.items[0].convite.status == 'expirada'
        assert invitation.status == 'atribuida'
        assert s.execute(text('select status from consolidacao_atribuicoes where id=:id'), {'id': invitation.id}).scalar_one() == 'atribuida'


def test_assignment_result_distinguishes_new_pending_and_accepted(workflow_database):
    v = _seed(workflow_database)
    track, _ = _insert_track(workflow_database, v)
    with _scoped(_factory(workflow_database), v['tenant']) as s:
        def assign():
            return assign_consolidacao(s, _actor(v['tenant'], v['actor']), consolidacao_id=track,
                responsavel_id=v['target_a'], expected_assignment_revision=None, whatsapp=False)
        new = assign()
        assert new.invitation_created is True
        pending = assign()
        assert pending.invitation_created is False
        assert pending.atribuicao.id == new.atribuicao.id
        _answer(s, v, track, pending.atribuicao)
        accepted = assign()
        assert accepted.invitation_created is False
        assert accepted.atribuicao.status == 'aceita'
