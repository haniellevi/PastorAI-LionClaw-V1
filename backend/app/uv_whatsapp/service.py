"""UV adapters reuse the panel services; only minimal names/status leave here."""
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select
from app.db.models import AppUser
from app.deps import CurrentUser
from app.services import uv
from app.prayer.catalog import normalized
from app.services.agent_privilege_catalog import _label as label


def actor(db, contact):
    users = db.scalars(select(AppUser).where(AppUser.igreja_id == contact.igreja_id,
        AppUser.pessoa_id == contact.pessoa_id, AppUser.status == 'ativo').with_for_update(of=AppUser)).all()
    if len(users) != 1:
        raise HTTPException(403, 'Remetente sem usuário ativo único')
    user = CurrentUser(app_user_id=str(users[0].id), igreja_id=str(contact.igreja_id),
        clerk_user_id='', email='', nome='', roles=frozenset())
    uv.actor(db, user)
    return user


def choose(items, name):
    found = [r for r in items if normalized(r['nome']) == normalized(name)]
    if len(found) != 1:
        raise HTTPException(422, 'Nome não encontrado ou ambíguo. Consulte o painel')
    return found[0]


def detail(db, user, name):
    turma = choose(uv.list_turmas(db, user), name)
    return uv.get_turma(db, user, turma['id'])


def list_summary(db, user):
    turmas = uv.list_turmas(db, user)
    return ('Turmas UV: ' + ', '.join(label(t['nome']) for t in turmas)
            if turmas else 'Nenhuma turma UV sob sua responsabilidade.')


def summary(turma):
    lines = [f"{label(turma['nome'])}: {'encerrada' if turma['encerrada'] else 'aberta'}"]
    for m in turma['matriculas']:
        lessons = lambda values: ', '.join(map(str, values)) or 'nenhuma'
        milestones = ', '.join(sorted(r['tipo'] for r in m['marcos'])) or 'nenhum'
        lines.append(f"{label(m['nome'])}: cumpridas {lessons(m['aulas_cumpridas'])}; "
            f"pendentes {lessons(m['aulas_pendentes'])}; marcos {milestones}; "
            f"{'UV concluída' if m['conclusao'] else 'em curso'}.")
    return '\n'.join(lines) if turma['matriculas'] else lines[0] + '\nSem matriculados.'


def propose(db, user, args):
    name, aula, student, presente, modalidade = args
    turma = detail(db, user, name)
    enrollment = choose(turma['matriculas'], student)
    current = next((p for p in enrollment['presencas'] if p['aula'] == aula), None)
    if current and (current['presente'], current['modalidade']) == (presente, modalidade):
        return 'Presença já registrada com esse valor. Nenhuma nova gravação.', None
    proposal = dict(id=str(uuid4()), turma_id=str(turma['id']),
        matricula_id=str(enrollment['id']), aula=aula, presente=presente, modalidade=modalidade,
        anterior_id=str(current['registro_id']) if current else None,
        anterior=dict(presente=current['presente'], modalidade=current['modalidade']) if current else None)
    # Validate with the SAME writer in a rolled-back savepoint. No duplicated rules.
    from app.uv_whatsapp.catalog import execute
    savepoint = db.begin_nested()
    try:
        execute(db, user, proposal)
    finally:
        savepoint.rollback()
    status = attendance_label(presente, modalidade)
    if current:
        status = f"Correção: atual {attendance_label(current['presente'], current['modalidade'])} → novo {status}"
    return (f"{label(turma['nome'])}, aula {aula}: {label(enrollment['nome'])}, {status}. "
            'Confirma gravar? Responda somente SIM ou NÃO em até 10 minutos.'), proposal


def attendance_label(presente, modalidade):
    return 'reposição presente' if modalidade == 'reposicao' else ('presente' if presente else 'ausente')
