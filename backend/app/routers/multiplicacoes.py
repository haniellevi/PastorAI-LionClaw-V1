"""Multiplicações — visão consolidada da Central (Células PR3-PR9).

`GET /multiplicacoes` devolve duas listas em snake_case:
  - `pendentes`: solicitações `tipo='multiplicacao'` ainda `aguardando` decisão
    (a criação/decisão passa por `/cell-requests`);
  - `registradas`: multiplicações já efetivadas (`multiplicacoes`), com a célula
    de ORIGEM (`celula_id`) e a célula gerada (`celula_nova_id`).

A execução transacional/idempotente da multiplicação acontece na aprovação da
solicitação (`POST /cell-requests/{id}/approve` → `cell_multiplication_service`),
não mais por um POST direto aqui. Este router é somente leitura.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CelulaSolicitacao, Multiplicacao
from app.db.session import get_db
from app.deps import CurrentUser, require_central
from app.domain.cell_requests import STATUS_AGUARDANDO, TIPO_MULTIPLICACAO

logger = logging.getLogger("pastorai.multiplicacoes")

router = APIRouter(prefix="/multiplicacoes", tags=["multiplicacoes"])


# ---------------------------------------------------------------------------
# Schemas (snake_case)
# ---------------------------------------------------------------------------
class MultiplicacaoPendenteOut(BaseModel):
    id: str
    celula_id: str
    solicitante_id: str | None = None
    tipo: str
    status: str
    payload_proposto: dict
    created_at: dt.datetime | None = None

    @classmethod
    def from_model(cls, s: CelulaSolicitacao) -> "MultiplicacaoPendenteOut":
        return cls(
            id=str(s.id),
            celula_id=str(s.celula_id),
            solicitante_id=str(s.solicitante_id) if s.solicitante_id else None,
            tipo=s.tipo,
            status=s.status,
            payload_proposto=s.payload_proposto or {},
            created_at=s.created_at,
        )


class MultiplicacaoRegistradaOut(BaseModel):
    id: str
    celula_id: str
    celula_nova_id: str | None = None
    solicitacao_id: str | None = None
    novo_lider_id: str | None = None
    status: str | None = None
    data_prevista: dt.date | None = None
    descendencia: str | None = None
    idempotency_key: str | None = None
    created_at: dt.datetime | None = None

    @classmethod
    def from_model(cls, m: Multiplicacao) -> "MultiplicacaoRegistradaOut":
        return cls(
            id=str(m.id),
            celula_id=str(m.celula_id),
            celula_nova_id=str(m.celula_nova_id) if m.celula_nova_id else None,
            solicitacao_id=str(m.solicitacao_id) if m.solicitacao_id else None,
            novo_lider_id=str(m.novo_lider_id) if m.novo_lider_id else None,
            status=m.status,
            data_prevista=m.data_prevista,
            descendencia=m.descendencia,
            idempotency_key=m.idempotency_key,
            created_at=m.created_at,
        )


class MultiplicacoesListOut(BaseModel):
    pendentes: list[MultiplicacaoPendenteOut]
    registradas: list[MultiplicacaoRegistradaOut]


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@router.get("", response_model=MultiplicacoesListOut)
def list_multiplicacoes(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_central),
) -> MultiplicacoesListOut:
    """Lista multiplicações pendentes (solicitações) e registradas do tenant.

    Visão consolidada = superfície da Central (pastor/admin, PRD-CENTRAL). O
    guard `require_central` impede que líder/discípulo leiam `payload_proposto`
    de todas as solicitações driblando o escopo por autor de `/cell-requests`.
    Filtro `igreja_id` explícito além da RLS (defesa em profundidade).
    """
    igreja_id = uuid.UUID(current_user.igreja_id)

    pendentes = db.execute(
        select(CelulaSolicitacao)
        .where(
            CelulaSolicitacao.igreja_id == igreja_id,
            CelulaSolicitacao.tipo == TIPO_MULTIPLICACAO,
            CelulaSolicitacao.status == STATUS_AGUARDANDO,
        )
        .order_by(CelulaSolicitacao.created_at.desc())
    ).scalars().all()

    registradas = db.execute(
        select(Multiplicacao)
        .where(Multiplicacao.igreja_id == igreja_id)
        .order_by(Multiplicacao.created_at.desc())
    ).scalars().all()

    return MultiplicacoesListOut(
        pendentes=[MultiplicacaoPendenteOut.from_model(s) for s in pendentes],
        registradas=[MultiplicacaoRegistradaOut.from_model(m) for m in registradas],
    )
