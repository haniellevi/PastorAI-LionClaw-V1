"""Tenant-scoped official evidence reader; never mutates formation or leadership."""
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select, text
from app.db.models import Celula

from app.domain.enviar import (
    EstadoEvidencia,
    EvidenciasEnviar,
    ResultadoEnviar,
    avaliar_aptidao,
)


class PessoaEnviar(Protocol):
    igreja_id: UUID
    apto_lider: bool
    sem_interesse: bool
    arquivada_em: datetime | None
    etapa: str | None


def ler_pendencias_pessoa(pessoa: PessoaEnviar, *, igreja_id: UUID, evidencias: dict | None = None, lideranca_existente: bool = False) -> ResultadoEnviar:
    """Lê campos já carregados, sem inferir certificados de etapa ou apto_lider.

    A flag histórica não comprova Reencontro. Evidências e responsabilidade
    efetiva são fornecidas pelo leitor oficial, nunca inferidas da etapa.
    """
    if not isinstance(igreja_id, UUID) or pessoa.igreja_id != igreja_id:
        raise ValueError("Pessoa fora do escopo da igreja")
    return avaliar_aptidao(EvidenciasEnviar(
        **{c: EstadoEvidencia(evidencias[c]["estado"]) if evidencias else EstadoEvidencia.NAO_INFORMADA
           for c in ("uv", "cd", "reencontro")},
        lideranca_existente=lideranca_existente,
        csim=pessoa.sem_interesse,
        arquivada=pessoa.arquivada_em is not None,
        apto_lider_legado=pessoa.apto_lider,
    ))


def ler_evidencias_oficiais(db, pessoa, *, igreja_id: UUID) -> dict:
    """Official records only, explicitly tenant/person scoped even under BYPASSRLS.

    An active reissue supersedes revoked certificates. No legacy flag or course
    enrollment attests completion. References contain only official identity/date.
    """
    if not isinstance(igreja_id, UUID) or pessoa.igreja_id != igreja_id:
        raise ValueError("Pessoa fora do escopo da igreja")
    params = dict(t=igreja_id, p=pessoa.id)
    queries = {
        'uv': "select id,confirmada_em as data,false as revogada from uv_conclusoes where igreja_id=:t and pessoa_id=:p order by confirmada_em desc,id desc limit 1",
        'cd': "select id,codigo,emitida_em as data,revogada from cd_certificados where igreja_id=:t and pessoa_id=:p order by revogada asc,emitida_em desc,id desc limit 1",
        'reencontro': "select id,data,revogada from uv_marcos where igreja_id=:t and pessoa_id=:p and tipo='reencontro' limit 1",
    }
    result = {}
    for criterion, sql in queries.items():
        row = db.execute(text(sql), params).mappings().first()
        result[criterion] = dict(estado=(EstadoEvidencia.REVOGADA if row['revogada'] else EstadoEvidencia.COMPROVADA) if row else EstadoEvidencia.NAO_INFORMADA,
            referencia=' / '.join(str(row[k]) for k in ('id','codigo','data') if k in row) if row else None)
    return result


def ler_pendencias_oficiais(db, pessoa, *, igreja_id: UUID) -> ResultadoEnviar:
    evidence = ler_evidencias_oficiais(db, pessoa, igreja_id=igreja_id)
    leadership = db.execute(select(Celula.id).where(Celula.igreja_id == igreja_id,
        Celula.lider_id == pessoa.id, Celula.ativo.is_(True)).limit(1)).scalar_one_or_none() is not None
    return ler_pendencias_pessoa(pessoa, igreja_id=igreja_id, evidencias=evidence,
        lideranca_existente=leadership)
