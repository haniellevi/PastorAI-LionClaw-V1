"""Gestão direta de membros pela Central (Células pós-V1).

A Central de Células transfere e remove membros por execução DIRETA — sem fluxo
de solicitação, sem segregação 3.1 (quem executa é a própria Central). Espelha o
padrão do ``add_cell_member`` (decisão 3.2 — entrada direta), mas com trilha de
auditoria append-only ``celula_membro_evento`` gravada na MESMA transação SQL
que aplica os efeitos de domínio. Falha parcial → rollback total.

Operações:
  - ``transferir_membro``: desativa vínculo ativo na origem, cria vínculo ativo
    no destino, atualiza espelho ``pessoas.celula_id``, promove tipo se
    necessário, grava evento ``transferido``.
  - ``remover_membro``: desativa vínculo ativo na origem, limpa espelho
    ``pessoas.celula_id``, grava evento ``removido``. NÃO deleta a pessoa.

Invariantes preservados (mesmos do fluxo de solicitação):
  - 1 pessoa → 1 vínculo ativo (índice único parcial);
  - elegibilidade no destino (pastor/líder ativo/número WhatsApp/arquivado);
  - origem e destino pertencem ao mesmo tenant e estão ativas;
  - origem tem líder (membresia órfão não é transferível);
  - revalidação SOB LOCK (SELECT ... FOR UPDATE) — fecha TOCTOU;
  - auditoria append-only na mesma transação (RNF-07).
"""

from __future__ import annotations

import copy
import datetime as dt
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Celula, CelulaMembro, CelulaMembroEvento, Pessoa
from app.services.celula_membro import (
    assert_membro_elegivel,
    promote_tipo_para_membro,
)

ACAO_TRANSFERIDO = "transferido"
ACAO_REMOVIDO = "removido"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _lock_cell(
    db: Session, *, igreja_id: uuid.UUID, celula_id: uuid.UUID
) -> Celula:
    """Carrega a célula sob lock e valida tenant + ativa + com líder."""
    cell = db.execute(
        select(Celula)
        .where(Celula.id == celula_id, Celula.igreja_id == igreja_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if cell is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Célula não encontrada nesta igreja",
        )
    return cell


def _lock_active_membership(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    expected_celula_id: uuid.UUID,
) -> CelulaMembro:
    """Exige uma única membresia ativa, ainda exatamente na célula esperada."""
    memberships = list(
        db.execute(
            select(CelulaMembro)
            .where(
                CelulaMembro.igreja_id == igreja_id,
                CelulaMembro.pessoa_id == pessoa_id,
                CelulaMembro.ativo.is_(True),
            )
            .order_by(CelulaMembro.id.asc())
            .with_for_update()
        ).scalars().all()
    )
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pessoa não possui vínculo ativo na célula de origem",
        )
    if len(memberships) > 1:
        # Invariante violado (índice único parcial deveria impedir); recusa
        # determinística em vez de escolher uma linha arbitrariamente.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pessoa possui múltiplos vínculos ativos (inconsistência)",
        )
    if str(memberships[0].celula_id) != str(expected_celula_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A membresia atual não corresponde à célula de origem informada",
        )
    return memberships[0]


def _append_event(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    celula_origem_id: uuid.UUID,
    celula_destino_id: uuid.UUID | None,
    acao: str,
    actor_id: uuid.UUID | None,
    motivo: str | None,
    payload_snapshot: dict | None = None,
) -> None:
    """Adiciona uma linha imutável na trilha (na transação corrente, sem commit)."""
    snapshot = copy.deepcopy(payload_snapshot or {})
    db.add(
        CelulaMembroEvento(
            igreja_id=igreja_id,
            pessoa_id=pessoa_id,
            celula_origem_id=celula_origem_id,
            celula_destino_id=celula_destino_id,
            acao=acao,
            actor_id=actor_id,
            motivo=motivo,
            payload_snapshot=snapshot,
        )
    )


def transferir_membro(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    celula_origem_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    celula_destino_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    motivo: str | None = None,
) -> CelulaMembro:
    """Transfere uma pessoa da célula de origem para a destino (execução direta).

    Efeitos atômicos (tudo na mesma transação, rollback total em falha):
      1. trava e valida origem (tenant, ativa, com líder);
      2. trava e valida destino (tenant, ativa, com líder);
      3. carrega pessoa sob lock e valida elegibilidade no destino;
      4. trava vínculo ativo atual e confirma que ainda está na origem;
      5. desativa vínculo origem;
      6. cria vínculo ativo no destino;
      7. atualiza espelho ``pessoas.celula_id`` e promove tipo se necessário;
      8. grava evento ``transferido`` na trilha append-only.

    Recusa (409) destino == origem (não é transferência).
    """
    if str(celula_destino_id) == str(celula_origem_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A célula de destino é a mesma de origem",
        )

    origem = _lock_cell(db, igreja_id=igreja_id, celula_id=celula_origem_id)
    if not bool(origem.ativo):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A célula de origem está inativa",
        )
    if origem.lider_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A célula de origem não tem líder",
        )

    destino = _lock_cell(db, igreja_id=igreja_id, celula_id=celula_destino_id)
    if not bool(destino.ativo):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A célula de destino está inativa",
        )
    if destino.lider_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A célula de destino não tem líder",
        )

    pessoa = db.execute(
        select(Pessoa)
        .where(Pessoa.id == pessoa_id, Pessoa.igreja_id == igreja_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pessoa não encontrada nesta igreja",
        )

    # Guarda compartilhada: recusa pastor / líder ativo / número WhatsApp /
    # arquivado ANTES de qualquer escrita (mesma guarda do fluxo de solicitação).
    assert_membro_elegivel(db, igreja_id=igreja_id, celula=destino, pessoa=pessoa)

    source_membership = _lock_active_membership(
        db,
        igreja_id=igreja_id,
        pessoa_id=pessoa_id,
        expected_celula_id=celula_origem_id,
    )

    try:
        now = _now()
        source_membership.ativo = False
        source_membership.updated_at = now

        novo_membro = CelulaMembro(
            igreja_id=igreja_id,
            celula_id=celula_destino_id,
            pessoa_id=pessoa_id,
            papel="membro",
            ativo=True,
        )
        db.add(novo_membro)

        pessoa.celula_id = destino.id
        promote_tipo_para_membro(pessoa)

        _append_event(
            db,
            igreja_id=igreja_id,
            pessoa_id=pessoa_id,
            celula_origem_id=celula_origem_id,
            celula_destino_id=celula_destino_id,
            acao=ACAO_TRANSFERIDO,
            actor_id=actor_id,
            motivo=motivo,
            payload_snapshot={
                "pessoa_id": str(pessoa_id),
                "celula_origem_id": str(celula_origem_id),
                "celula_destino_id": str(celula_destino_id),
                "motivo": motivo,
            },
        )
        db.flush()
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return novo_membro


def remover_membro(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    celula_origem_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    motivo: str | None = None,
) -> CelulaMembro:
    """Remove uma pessoa da célula (execução direta). NÃO deleta a pessoa.

    Efeitos atômicos (tudo na mesma transação, rollback total em falha):
      1. trava e valida origem (tenant, ativa);
      2. carrega pessoa sob lock;
      3. trava vínculo ativo atual e confirma que ainda está na origem;
      4. desativa vínculo;
      5. limpa espelho ``pessoas.celula_id``;
      6. grava evento ``removido`` na trilha append-only.
    """
    origem = _lock_cell(db, igreja_id=igreja_id, celula_id=celula_origem_id)
    if not bool(origem.ativo):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A célula de origem está inativa",
        )

    pessoa = db.execute(
        select(Pessoa)
        .where(Pessoa.id == pessoa_id, Pessoa.igreja_id == igreja_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pessoa não encontrada nesta igreja",
        )

    source_membership = _lock_active_membership(
        db,
        igreja_id=igreja_id,
        pessoa_id=pessoa_id,
        expected_celula_id=celula_origem_id,
    )

    try:
        now = _now()
        source_membership.ativo = False
        source_membership.updated_at = now

        pessoa.celula_id = None

        _append_event(
            db,
            igreja_id=igreja_id,
            pessoa_id=pessoa_id,
            celula_origem_id=celula_origem_id,
            celula_destino_id=None,
            acao=ACAO_REMOVIDO,
            actor_id=actor_id,
            motivo=motivo,
            payload_snapshot={
                "pessoa_id": str(pessoa_id),
                "celula_origem_id": str(celula_origem_id),
                "motivo": motivo,
            },
        )
        db.flush()
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return source_membership
