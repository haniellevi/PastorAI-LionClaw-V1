"""Stable attendance conflict identity, independent of user-facing wording."""
from fastapi import HTTPException


class AttendanceChanged(HTTPException):
    code = 'attendance_changed'

    def __init__(self, detail='Presença já registrada ou corrigida. Atualize e faça uma correção explícita'):
        super().__init__(409, detail)
