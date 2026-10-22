"""Private memory inventory without identifiers or content."""
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session


class ErasureAgeBuckets(BaseModel):
    menos_24h: int
    de_1_a_3_dias: int
    mais_3_dias: int


class ErasureCounts(BaseModel):
    pendentes: int
    atendidos: int
    recusados: int
    mais_antigo_segundos: int | None
    faixas_idade: ErasureAgeBuckets


class SummaryTaskCounts(BaseModel):
    queued: int
    running: int
    done: int
    refused: int


class CleanupCounts(BaseModel):
    pendente: int
    concluida: int


class PrivateMemoryOverview(BaseModel):
    pedidos_exclusao: ErasureCounts
    resumos_ativos: int
    retomadas_entregues: int
    tarefas_resumo: SummaryTaskCounts
    limpezas_privadas: CleanupCounts


def memory_overview(db: Session, tenant: UUID) -> PrivateMemoryOverview:
    try:
        data = db.scalar(text("select public.private_memory_overview(:t)"), {"t": tenant})
    except DBAPIError as exc:
        if getattr(exc.orig, "pgcode", None) == "42501":
            raise HTTPException(403, "Acesso restrito a administrador ativo") from None
        raise
    return PrivateMemoryOverview.model_validate(data)
