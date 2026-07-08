"""Vínculo canônico ``celula_membro`` — mantém consistência com o espelho
legado ``pessoas.celula_id`` (achado C-02).

Três pontos de escrita atualizavam só o espelho (convite Parte A em team.py,
ativação Parte B em auth.py, ``link_cell`` em contacts.py), deixando a pessoa
invisível na visão do líder/discípulo (que lê ``celula_membro``, a fonte de
verdade — Q1). Este módulo centraliza a escrita canônica pra não duplicar a
lógica 3x e arriscar divergência entre as cópias.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Celula, CelulaMembro


def ensure_active_membro(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    celula_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    papel: str = "membro",
) -> None:
    """Garante uma linha ATIVA de celula_membro para (pessoa, célula).

    Idempotente: reativa a linha se já existir (não duplica). Não mexe em
    vínculos da pessoa em OUTRAS células — para transferência, chame
    ``deactivate_other_active_membro`` antes (o índice único parcial só
    permite 1 vínculo ativo por pessoa).

    Recusa (``ValueError``) se ``celula_id`` não pertencer a ``igreja_id`` —
    o service é o ponto canônico de escrita e não deve confiar cegamente nos
    IDs recebidos, mesmo que os 4 callers atuais já validem isso antes de
    chamar (achado de revisão externa do PR #134).
    """
    celula = db.execute(
        select(Celula).where(Celula.id == celula_id, Celula.igreja_id == igreja_id)
    ).scalar_one_or_none()
    if celula is None:
        raise ValueError("Célula fora do escopo da igreja — vínculo recusado")

    # Histórico anterior a este PR pode ter deixado mais de uma linha inativa
    # pra (pessoa, célula) — a migration de backfill reativa só a mais
    # recente e preserva as demais. scalar_one_or_none() estouraria
    # MultipleResultsFound nesse caso; pega a mais recente deterministicamente
    # (mesmo critério de desempate da migration).
    historico = db.execute(
        select(CelulaMembro)
        .where(
            CelulaMembro.pessoa_id == pessoa_id,
            CelulaMembro.celula_id == celula_id,
            CelulaMembro.igreja_id == igreja_id,
        )
        .order_by(
            CelulaMembro.updated_at.desc().nullslast(),
            CelulaMembro.created_at.desc(),
        )
    ).scalars().all()
    existing = historico[0] if historico else None
    if existing is not None:
        existing.ativo = True
    else:
        db.add(
            CelulaMembro(
                igreja_id=igreja_id,
                celula_id=celula_id,
                pessoa_id=pessoa_id,
                papel=papel,
                ativo=True,
            )
        )


def deactivate_other_active_membro(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    keep_celula_id: uuid.UUID,
) -> None:
    """Desativa o vínculo canônico ativo da pessoa em OUTRA célula.

    Chame antes de ``ensure_active_membro`` numa transferência: o índice único
    parcial ``celula_membro_pessoa_ativa_uq`` (igreja_id, pessoa_id) WHERE ativo
    só permite uma linha ativa por pessoa — sem desativar a antiga, ativar a
    nova colidiria.
    """
    other = db.execute(
        select(CelulaMembro).where(
            CelulaMembro.pessoa_id == pessoa_id,
            CelulaMembro.igreja_id == igreja_id,
            CelulaMembro.ativo.is_(True),
            CelulaMembro.celula_id != keep_celula_id,
        )
    ).scalar_one_or_none()
    if other is not None:
        other.ativo = False
