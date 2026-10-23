"""Private memory inventory without identifiers or content."""
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.services.private_erasure_requests import (
    PRIVATE_ERASURE_SLA_DAYS_V1,
    PRIVATE_ERASURE_SLA_POLICY_VERSION,
)


class ErasureAgeBuckets(BaseModel):
    menos_24h: int
    de_1_a_3_dias: int
    mais_3_dias: int


class ErasureCounts(BaseModel):
    pendentes: int
    vencidos: int
    prazo_dias: int
    prazo_versao: str
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
    data['pedidos_exclusao']['vencidos'] = db.scalar(text('''
        select count(*) from private_erasure_requests
        where igreja_id=:t and state='pendente'
          and created_at<=now()-make_interval(days=>:sla_days)
    '''), {'t': tenant, 'sla_days': PRIVATE_ERASURE_SLA_DAYS_V1})
    data['pedidos_exclusao']['prazo_dias'] = PRIVATE_ERASURE_SLA_DAYS_V1
    data['pedidos_exclusao']['prazo_versao'] = PRIVATE_ERASURE_SLA_POLICY_VERSION
    return PrivateMemoryOverview.model_validate(data)
