"""Read-only neighborhood lookup; deliberately no membership or intake writer."""

import re
from sqlalchemy import select
from app.db.models import Celula
from app.agent.read_only_info import (
    canonical_public_bairro_key,
    _canonical_cell_for_reply,
    _canonical_meeting,
    _public_reply,
)
from app.services.public_church_info import load_public_church_info
from app.cell_suggest import catalog


def resolve(db, *, igreja_id, bairro):
    if bairro is None:
        return catalog.ASK, "ask", None
    key = canonical_public_bairro_key(bairro)
    # Names only: never load addresses, leaders, phones, or private links.
    public_bairros = db.scalars(
        select(Celula.bairro)
        .where(
            Celula.igreja_id == igreja_id,
            Celula.ativo.is_(True),
            Celula.divulgar_whatsapp.is_(True),
            Celula.bairro.is_not(None),
        )
        .distinct()
    ).all()
    matches = {
        canonical_public_bairro_key(value)
        for value in public_bairros
        if canonical_public_bairro_key(value).startswith(key)
    }
    if key not in matches:
        if matches:
            # We cannot infer adjacent neighborhoods or cities from cell data.
            return catalog.AMBIGUOUS, "ask", None
        return catalog.MISSING, "handoff", key
    info = load_public_church_info(db, igreja_id=igreja_id, bairro=key)
    cells = [
        safe
        for row in (info.celulas if info else ())
        if (safe := _canonical_cell_for_reply(row)) is not None
        and canonical_public_bairro_key(safe.bairro) == key
        and not re.search(
            r"\d|://|[/@]|www\.|(?:[a-z-]+\.)+[a-z]{2,}|\bmapa\b",
            safe.nome + " " + safe.bairro,
            re.I,
        )
    ]
    if not cells:
        return catalog.MISSING, "handoff", key
    lines = ["Células com divulgação autorizada nesse bairro (até 5):"]
    for cell in cells:
        meeting = _canonical_meeting(cell)
        lines.append(
            f"• {cell.nome} — {cell.bairro}" + (f"; {meeting}" if meeting else "") + "."
        )
    lines.append(
        "Esta consulta só informa; não cria vínculo. A Central da igreja faz o vínculo. Não calculo distância."
    )
    return _public_reply("\n".join(lines)), "done", key
