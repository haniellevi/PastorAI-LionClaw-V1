"""Reports router — relatórios de célula por semana (RF-27..29 / US-24..26).

Endpoint:
  - GET /reports   relatórios da semana, um item por REUNIÃO materializada

Fonte de verdade: ``celula_reuniao`` (+ ``relatorio_snapshot``). A tabela legada
``reports`` NÃO é lida aqui — ela nunca teve writer na aplicação, então o painel
mostrava 100% pendente para sempre. O model continua existindo (nada é apagado
nesta missão), apenas deixou de ser fonte operacional.

Decisões do dono (REPORT-SOT-IMPLEMENT-1):
  - relatório só existe por OCORRÊNCIA materializada. Célula sem reunião no
    período NÃO gera pendência virtual — nada de linha sintética por célula;
  - ``pendente`` vira ``atrasado`` em ``data + hora + 2h`` (America/Sao_Paulo),
    via ``report_is_overdue``. A regra legada de "domingo 22h" saiu de cena;
  - listagem tenant-wide é da Central: só ``pastor``/``admin`` (``require_central``).
    Oferta e observações trafegam apenas sob essa autorização. O líder continua
    lendo o relatório da PRÓPRIA célula por ``GET /cell-meetings/{id}/report``.

Escopo por tenant: filtro explícito de ``igreja_id`` além da RLS (defesa em
profundidade, como nos demais routers de célula).
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import nulls_last, select
from sqlalchemy.orm import Session

from app.db.models import Celula, CelulaReuniao
from app.db.session import get_db
from app.deps import CurrentUser, require_central
from app.domain.cell_report_snapshot import (
    CellReportSnapshotValidationError,
    has_cell_report_snapshot_schema_marker,
    validate_cell_report_snapshot_v2,
)
from app.domain.cell_meetings_schedule import now_in_sao_paulo, report_is_overdue
from app.routers._common import Page, PaginationParams
from app.services.cell_health_service import (
    ESTADO_COMPARECEU,
    RELATORIO_ENVIADO,
    STATUS_CANCELADA,
)

logger = logging.getLogger("pastorai.reports")

router = APIRouter(prefix="/reports", tags=["reports"])

# Status exibido de um relatório (contrato externo da tela #relatorios).
STATUS_RECEBIDO = "recebido"
STATUS_PENDENTE = "pendente"
STATUS_ATRASADO = "atrasado"

# Registro pastoral que conta como decisão — espelha `cell_meetings.RECORD_TIPOS`.
TIPO_DECISAO = "decisao"

# `YYYY-Www` — mesmo formato que `current_iso_week` produz.
_SEMANA_RE = re.compile(r"^(\d{4})-W(\d{2})$")


def current_iso_week(now: dt.datetime | None = None) -> str:
    """Semana ISO corrente (`YYYY-Www`) em ``America/Sao_Paulo``.

    O fuso é o do PRODUTO, não o do processo: com o host em UTC,
    ``date.today()`` viraria a semana até 3h antes da meia-noite de Brasília —
    domingo 21:30 em São Paulo já cairia na semana seguinte. ``now`` é injetável
    para determinismo nos testes (mesma costura de ``now_in_sao_paulo``).
    """
    year, week, _ = now_in_sao_paulo(now).date().isocalendar()
    return f"{year}-W{week:02d}"


def iso_week_bounds(semana: str) -> tuple[dt.date, dt.date]:
    """(segunda, domingo) da semana ISO `YYYY-Www`.

    Validação RIGOROSA: além do formato, a semana precisa EXISTIR no ano
    (``2026-W53`` não existe se o ano tem 52 semanas). Levanta ``ValueError`` em
    qualquer outro caso — o router traduz isso em 422.
    """
    match = _SEMANA_RE.match((semana or "").strip())
    if match is None:
        raise ValueError("semana deve estar no formato YYYY-Www")
    year, week = int(match.group(1)), int(match.group(2))
    try:
        monday = dt.date.fromisocalendar(year, week, 1)
    except ValueError as exc:
        raise ValueError(f"semana inexistente no calendário ISO: {semana}") from exc
    return monday, monday + dt.timedelta(days=6)


class ReportOut(BaseModel):
    """Projeção de um relatório de reunião. `id` é sempre o id da REUNIÃO.

    Números (`presentes`/`visitantes`/`decisoes`) e `oferta`/`observacoes` só
    existem depois do envio — em pendente/atrasado vêm nulos, sem inventar dado.
    Não há campo `origem`: o writer real é o painel do líder
    (``POST /cell-meetings/{id}/report/submit``), não o WhatsApp.
    """

    id: str
    celulaId: str  # noqa: N815
    celulaNome: str | None = None  # noqa: N815
    semana: str
    status: str  # recebido | pendente | atrasado
    dataReuniao: dt.date  # noqa: N815
    presentes: int | None = None
    visitantes: int | None = None
    decisoes: int | None = None
    oferta: float | None = None
    observacoes: str | None = None


class _Consolidado(BaseModel):
    """Números e textos consolidados de um relatório ENVIADO."""

    presentes: int | None = None
    visitantes: int | None = None
    decisoes: int | None = None
    oferta: float | None = None
    observacoes: str | None = None


def _consolidado(reuniao: CelulaReuniao) -> _Consolidado:
    """Projeção do relatório ENVIADO a partir do `relatorio_snapshot` congelado.

    O snapshot é a verdade pós-envio (mesma precedência de
    ``cell_meetings.get_report``): escritas posteriores em ``celula_presenca``
    não podem mexer no consolidado.

    Em ``cell-report/v2`` os totais agregados validados têm precedência e os
    arrays individuais precisam estar vazios. No formato legado, `presentes`
    conta SÓ ``estado == 'compareceu'`` — definição canônica de
    ``cell_health_service._attendance_count``; ``confirmada`` é intenção do
    discípulo (PR2), não comparecimento. `decisoes` conta registros pastorais
    de tipo ``decisao``.

    Sem snapshot, os números ficam nulos (nada é inventado) e oferta/observações
    caem para as colunas da reunião. Na prática não ocorre: ``submit_report``
    sempre congela o snapshot, criado na mesma migration do ciclo do relatório.
    """
    snapshot = reuniao.relatorio_snapshot
    if not snapshot:
        return _Consolidado(
            oferta=(
                float(reuniao.oferta_valor)
                if reuniao.oferta_valor is not None
                else None
            ),
            observacoes=reuniao.observacoes,
        )
    if has_cell_report_snapshot_schema_marker(snapshot):
        aggregate = validate_cell_report_snapshot_v2(snapshot)
        return _Consolidado(
            presentes=aggregate.totals.presentes,
            visitantes=aggregate.totals.visitantes,
            decisoes=aggregate.totals.decisoes,
            oferta=(
                float(aggregate.oferta_valor)
                if aggregate.oferta_valor is not None
                else None
            ),
            observacoes=aggregate.observacoes,
        )
    presencas = snapshot.get("presencas") or []
    visitantes = snapshot.get("visitantes") or []
    records = snapshot.get("records") or []
    oferta = snapshot.get("oferta_valor")
    return _Consolidado(
        presentes=sum(1 for p in presencas if p.get("estado") == ESTADO_COMPARECEU),
        visitantes=len(visitantes),
        decisoes=sum(1 for r in records if r.get("tipo") == TIPO_DECISAO),
        oferta=float(oferta) if oferta is not None else None,
        observacoes=snapshot.get("observacoes"),
    )


def _report_status(reuniao: CelulaReuniao, now: dt.datetime | None = None) -> str:
    """recebido (enviado) · atrasado (passou o SLA de 2h) · pendente (antes dele)."""
    if reuniao.relatorio_status == RELATORIO_ENVIADO:
        return STATUS_RECEBIDO
    if report_is_overdue(data=reuniao.data, hora=reuniao.hora, now=now):
        return STATUS_ATRASADO
    return STATUS_PENDENTE


@router.get("", response_model=Page[ReportOut])
def list_reports(
    semana: str | None = Query(default=None, description="ISO week, ex 2026-W24"),
    pagination: PaginationParams = Depends(),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_central),
) -> Page[ReportOut]:
    """Lista os relatórios da semana — um item por reunião materializada (RNF-09).

    Restrito a pastor/admin: a listagem é tenant-wide e carrega oferta e
    observações de TODAS as células. Reuniões canceladas ficam de fora. Célula
    sem reunião na semana simplesmente não aparece.
    """
    target_week = (semana or "").strip() or current_iso_week()
    try:
        monday, sunday = iso_week_bounds(target_week)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    igreja_id = uuid.UUID(current_user.igreja_id)

    reunioes = db.execute(
        select(CelulaReuniao)
        .where(
            CelulaReuniao.igreja_id == igreja_id,
            CelulaReuniao.data >= monday,
            CelulaReuniao.data <= sunday,
            CelulaReuniao.status != STATUS_CANCELADA,
        )
        .order_by(
            CelulaReuniao.data.asc(),
            nulls_last(CelulaReuniao.hora.asc()),
            CelulaReuniao.id.asc(),
        )
    ).scalars().all()

    # Nomes só das células referenciadas, filtrando por tenant (sem varrer a
    # tabela inteira nem confiar apenas na RLS).
    celula_ids = {r.celula_id for r in reunioes}
    nome_by_id: dict[uuid.UUID, str] = {}
    if celula_ids:
        nome_by_id = {
            cid: nome
            for cid, nome in db.execute(
                select(Celula.id, Celula.nome).where(
                    Celula.igreja_id == igreja_id,
                    Celula.id.in_(celula_ids),
                )
            ).all()
        }

    items: list[ReportOut] = []
    for r in reunioes:
        item_status = _report_status(r)
        # Antes do envio o relatório não existe: nada de números, oferta ou
        # observações de rascunho vazando para o painel da Central.
        try:
            dados = (
                _consolidado(r)
                if item_status == STATUS_RECEBIDO
                else _Consolidado()
            )
        except CellReportSnapshotValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "INVALID_CELL_REPORT_SNAPSHOT",
                    "reason": exc.code.value,
                },
            ) from None
        items.append(
            ReportOut(
                id=str(r.id),
                celulaId=str(r.celula_id),
                celulaNome=nome_by_id.get(r.celula_id),
                semana=target_week,
                status=item_status,
                dataReuniao=r.data,
                presentes=dados.presentes,
                visitantes=dados.visitantes,
                decisoes=dados.decisoes,
                oferta=dados.oferta,
                observacoes=dados.observacoes,
            )
        )

    total = len(items)
    start = pagination.offset
    page_items = items[start : start + pagination.limit]

    return Page[ReportOut](
        items=page_items,
        page=pagination.page,
        pageSize=pagination.page_size,
        total=total,
    )
