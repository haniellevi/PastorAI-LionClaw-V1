"""Construção de célula compartilhada pelo cadastro e pela abertura aprovada.

Não concede liderança, não envia mensagens e não commita. O chamador usa
cell_leadership e valida autorização na mesma transação.
"""
from app.db.models import Celula


def new_cell(*, igreja_id, nome, cobertura_espiritual, **fields):
    return Celula(igreja_id=igreja_id, nome=nome,
        cobertura_espiritual=cobertura_espiritual, lider_id=None, ativo=False, **fields)
