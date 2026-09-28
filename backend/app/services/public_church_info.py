"""Tenant-scoped, read-only public facts from Igreja and Celula.

This is the only database reader used by the deterministic public-information
reply. Its SELECT list is deliberately narrower than the ORM models: private
cell location, leadership, contact and link fields cannot cross this seam.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Celula, Igreja

if TYPE_CHECKING:
    from app.agent.read_only_info import CanonicalPublicChurchInfo

_MAX_PUBLIC_CELLS = 5
_ACCENTED_BAIRRO_CHARS = "áàâãäéèêëíìîïóòôõöúùûüç"
_PLAIN_BAIRRO_CHARS = "aaaaaeeeeiiiiooooouuuuc"


def _row_value(row: Any, name: str, position: int) -> Any:
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        return mapping[name]
    if isinstance(row, tuple):
        return row[position]
    return getattr(row, name)


def load_public_church_info(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    bairro: str | None = None,
    include_cells: bool = True,
) -> "CanonicalPublicChurchInfo | None":
    """Load one church's public facts under its already-established RLS scope."""

    # Importing app.agent at module import time would execute its public runtime
    # package entry point, which also imports this service. Keep this boundary
    # local and dependency-free until a caller actually needs a projection.
    from app.agent.read_only_info import (
        CanonicalPublicCell,
        CanonicalPublicChurchInfo,
        canonical_public_bairro_key,
    )

    church = session.execute(
        select(Igreja.endereco_institucional, Igreja.horarios_culto).where(
            Igreja.id == igreja_id
        )
    ).one_or_none()
    if church is None:
        return None
    cells: list[Any] = []
    if include_cells:
        statement = (
            select(
                Celula.bairro,
                Celula.nome,
                Celula.dia_reuniao,
                Celula.horario,
            )
            .where(
                Celula.igreja_id == igreja_id,
                Celula.ativo.is_(True),
                Celula.divulgar_whatsapp.is_(True),
                Celula.bairro.is_not(None),
            )
            .order_by(func.lower(Celula.bairro).asc(), Celula.nome.asc(), Celula.id.asc())
            .limit(_MAX_PUBLIC_CELLS)
        )
        bairro_key = canonical_public_bairro_key(bairro)
        if bairro_key:
            normalized_column = func.translate(
                func.lower(Celula.bairro),
                _ACCENTED_BAIRRO_CHARS,
                _PLAIN_BAIRRO_CHARS,
            )
            statement = statement.where(normalized_column == bairro_key)
        cells = session.execute(statement).all()
    return CanonicalPublicChurchInfo(
        endereco_institucional=_row_value(church, "endereco_institucional", 0),
        horarios_culto=_row_value(church, "horarios_culto", 1),
        celulas=tuple(
            CanonicalPublicCell(
                bairro=_row_value(cell, "bairro", 0),
                nome=_row_value(cell, "nome", 1),
                dia_reuniao=_row_value(cell, "dia_reuniao", 2),
                horario=_row_value(cell, "horario", 3),
            )
            for cell in cells
        ),
    )
