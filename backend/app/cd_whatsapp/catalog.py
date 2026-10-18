"""Deterministic closed commands. Identity and targets are resolved in the server."""
import re
from app.prayer.catalog import normalized

HELP = ('Envie CD para listar turmas; CD turma NOME para consultar. '
        'Para propor presença: CD presença TURMA; aula 1; ALUNO; presente '
        '(ou ausente ou reposição). Matrícula, conclusão de módulo, equivalência e certificado exigem o painel autenticado.')


def route(text, *, pending=False):
    value = " ".join(normalized(text).split())
    if pending and text.strip().casefold() == 'sim':
        return 'confirm', None
    if pending and value in {'nao', 'cancelar'}:
        return 'cancel', None
    if value == 'cd':
        return 'list', None
    read = re.fullmatch(r'cd turma (.+)', value)
    if read:
        return 'read', read.group(1)
    match = re.fullmatch(r'cd presenca (.+);\s*aula (100|[1-9][0-9]?);\s*(.+);\s*(presente|ausente|reposicao)', value)
    if match:
        turma, aula, aluno, status = match.groups()
        return 'attendance', (turma.strip(), int(aula), aluno.strip(), status != 'ausente',
                              'reposicao' if status == 'reposicao' else 'regular')
    if value.startswith('cd '):
        return 'help', None
    return ('clarify' if pending and value in {'sim', 'confirmo'} else 'none'), None


def execute(db, user, proposal):
    from uuid import UUID
    from app.routers.cd import PresencaInput
    from app.services import cd
    from app.services.formation_errors import AttendanceChanged
    from fastapi import HTTPException
    # The panel writer holds this same turma lock and compares registro_id atomically.
    try:
        return cd.attendance(db, user, UUID(proposal['turma_id']), UUID(proposal['matricula_id']),
            UUID(proposal['aula_id']), PresencaInput(id=UUID(proposal['id']), presente=proposal['presente'],
                modalidade=proposal['modalidade'], anterior_id=(UUID(proposal['anterior_id'])
                    if proposal['anterior_id'] else None)))
    except HTTPException as exc:
        if getattr(exc, 'code', None) == AttendanceChanged.code:
            raise HTTPException(409, 'Registro alterado. Faça uma nova proposta.') from None
        raise
