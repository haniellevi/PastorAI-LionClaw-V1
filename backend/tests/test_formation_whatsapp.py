import pytest
from fastapi import HTTPException
from uuid import uuid4


def test_uv_saved_names_normalize_spaces():
    from app.uv_whatsapp.service import choose
    item = dict(nome='  Ána   Clara  ')
    assert choose([item], 'ana clara') is item


def test_uv_refusal_uses_code(monkeypatch):
    from app.uv_whatsapp.catalog import execute
    from app.services.formation_errors import AttendanceChanged
    from app.services import uv
    def changed(*a, **kw):
        raise AttendanceChanged(detail='Mensagem independente')
    monkeypatch.setattr(uv, 'attendance', changed)
    proposal = dict(id=str(uuid4()), turma_id=str(uuid4()),
        matricula_id=str(uuid4()), aula=1, presente=True, modalidade='regular', anterior_id=None)
    with pytest.raises(HTTPException, match='nova proposta'):
        execute(None, None, proposal)


@pytest.mark.parametrize('domain',['uv','cd'])
def test_unrelated_conflict_is_not_classified_by_its_text(monkeypatch,domain):
    from importlib import import_module
    service=import_module(f'app.services.{domain}')
    catalog=import_module(f'app.{domain}_whatsapp.catalog')
    original=HTTPException(409,'correção explícita')
    def conflict(*a,**kw): raise original
    monkeypatch.setattr(service,'attendance',conflict)
    proposal=dict(id=str(uuid4()),turma_id=str(uuid4()),matricula_id=str(uuid4()),
        aula=1,aula_id=str(uuid4()),presente=True,modalidade='regular',anterior_id=None)
    with pytest.raises(HTTPException) as exc:
        catalog.execute(None,None,proposal)
    assert exc.value is original
