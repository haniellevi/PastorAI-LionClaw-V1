"""Schemas and shared rules for creating human and WhatsApp cell requests."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Celula, CelulaSolicitacao, CelulaSolicitacaoEvento, Pessoa
from app.domain.cell_requests import (
    MEMBER_TIPOS,
    OPEN_STATUSES,
    TIPO_ABRIR_CELULA,
    TIPO_NOMEAR_LIDER,
)

# Postgres SQLSTATE de unique_violation. Só ele é traduzido para 409 na criação;
# outras violações de integridade sobem (500) — não são conflito de estado.
_PG_UNIQUE_VIOLATION = "23505"


def _require_requests_enabled() -> None:
    """Gate de rollout: 503 enquanto a escrita sensível de Células estiver OFF.

    Aplicado só às rotas que ESCREVEM (criação/decisão/reenvio/cancelamento). As
    leituras de solicitação permanecem abertas. Liga por env
    ``CELULAS_REQUESTS_ENABLED`` — ver PLANO-IMPLEMENTACAO-CELULAS §Flags.
    """
    if not get_settings().celulas_requests_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Fluxo de solicitações de célula ainda não habilitado",
        )


class CellRequestOut(BaseModel):
    id: str
    celula_id: str | None = None
    solicitante_id: str | None = None
    pessoa_id: str | None = None
    celula_criada_id: str | None = None
    celula_nome: str | None = None
    candidato_nome: str | None = None
    candidato_id: str | None = None
    versao_proposta: int = 1
    tipo: str
    status: str
    payload_proposto: dict
    payload_atual: dict | None = None
    motivo: str | None = None
    observacao_central: str | None = None
    decidido_por: str | None = None
    decidido_em: dt.datetime | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None

    @classmethod
    def from_model(cls, s: CelulaSolicitacao, db: Session | None = None) -> "CellRequestOut":
        names = {}
        if s.tipo in {TIPO_NOMEAR_LIDER, TIPO_ABRIR_CELULA} and db is not None:
            names = dict(
                celula_nome=db.execute(select(Celula.nome).where(Celula.id == s.celula_id, Celula.igreja_id == s.igreja_id)).scalar_one_or_none(),
                candidato_nome=db.execute(select(Pessoa.nome).where(Pessoa.id == s.candidato_id, Pessoa.igreja_id == s.igreja_id)).scalar_one_or_none(),
            )
        if s.tipo == TIPO_ABRIR_CELULA and s.status == "aprovada" and db is not None:
            event = db.execute(select(CelulaSolicitacaoEvento).where(
                CelulaSolicitacaoEvento.igreja_id == s.igreja_id,
                CelulaSolicitacaoEvento.solicitacao_id == s.id,
                CelulaSolicitacaoEvento.acao == "aprovada",
            )).scalar_one_or_none()
            names['celula_criada_id'] = (event.payload_snapshot or {}).get('celula_criada_id') if event else None
        return cls(
            **names,
            id=str(s.id),
            celula_id=str(s.celula_id) if s.celula_id else None,
            solicitante_id=str(s.solicitante_id) if s.solicitante_id else None,
            pessoa_id=str(s.pessoa_id) if s.pessoa_id else None,
            candidato_id=str(s.candidato_id) if s.candidato_id else None,
            versao_proposta=s.versao_proposta,
            tipo=s.tipo,
            status=s.status,
            payload_proposto=s.payload_proposto or {},
            payload_atual=s.payload_atual,
            motivo=s.motivo,
            observacao_central=s.observacao_central,
            decidido_por=str(s.decidido_por) if s.decidido_por else None,
            decidido_em=s.decidido_em,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )


def _has_open_conflict(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    celula_id: uuid.UUID | None,
    tipo: str,
    pessoa_id: str | None,
    candidato_id: uuid.UUID | None = None,
) -> bool:
    """Matriz E13 (§6.8): já existe solicitação ABERTA conflitante nesta célula?

    - membros (transferir/remover): conflita com qualquer aberta que mire a MESMA
      pessoa na célula;
    - demais tipos (campos sensíveis / multiplicação): conflita com uma aberta do
      MESMO `tipo` na célula.
    """
    filters = [
        CelulaSolicitacao.igreja_id == igreja_id,
        CelulaSolicitacao.celula_id == celula_id,
        CelulaSolicitacao.status.in_(list(OPEN_STATUSES)),
    ]
    if tipo == TIPO_ABRIR_CELULA:
        filters.append(CelulaSolicitacao.tipo == tipo)
        filters.append(CelulaSolicitacao.candidato_id == candidato_id)
    elif tipo in MEMBER_TIPOS:
        filters.append(CelulaSolicitacao.tipo.in_(list(MEMBER_TIPOS)))
        filters.append(CelulaSolicitacao.pessoa_id == uuid.UUID(str(pessoa_id)))
    else:
        filters.append(CelulaSolicitacao.tipo == tipo)
    existing = db.execute(
        select(CelulaSolicitacao.id).where(*filters).limit(1)
    ).first()
    return existing is not None


def _reject_member_tipo(tipo: str) -> None:
    """M7B-W1.3 — transferência/remoção de membro não parte da tela do líder.

    A gestão de membros é atribuição da Central de Célula; o líder não abre esse
    tipo de solicitação por aqui. Barrado no backend (403) p/ fechar o bypass de
    chamada direta ao endpoint fora da UI. Não toca a decisão da Central sobre
    solicitações legadas (approve/reject) nem os demais tipos permitidos.
    """
    if tipo in MEMBER_TIPOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Transferência e remoção de membro são geridas pela Central de Célula.",
        )
