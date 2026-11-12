"""RF-26 / US-23: alertas ao líder de célula gerados por regras configuráveis.

O admin liga, desliga e ajusta os parâmetros de cada regra da própria igreja
(``celula_alerta_regras``). O cron avalia o ESTADO do banco (RNF-23), não um
horário fixo, e grava em ``cell_alerts`` um alerta por fato: a chave
``(igreja_id, regra_tipo, fato_chave)`` é única, então ciclos repetidos não
duplicam e um alerta já tratado não volta para o mesmo fato.

Gates (desligado por padrão):
- processamento só para igrejas listadas em ``CELL_ALERT_ENABLED_IGREJA_IDS``;
- dentro da igreja, só regras com ``ativo = true`` (padrão falso).

Nada aqui envia mensagem: o alerta aparece no painel (detalhe da célula), onde
o líder direto, o pastor ou o admin o baixam pela rota já existente.
O texto gravado não contém nome nem telefone; a chave do fato é opaca (UUIDs).
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.models import (
    CelulaAlertaRegra,
    Celula,
    CelulaMembro,
    CelulaReuniao,
    CelulaVisitante,
    CellAlert,
    Consolidacao,
)

logger = logging.getLogger("pastorai.cell_alert_rules")

SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")
ENV_ALLOWLIST = "CELL_ALERT_ENABLED_IGREJA_IDS"

VISITANTE_NOVO = "visitante_novo"
LIDERADO_EM_CONSOLIDACAO = "liderado_em_consolidacao"
RELATORIO_PENDENTE = "relatorio_pendente"
PRAZO_VENCENDO = "prazo_vencendo"
META_ATINGIDA = "meta_atingida"

RELATORIO_ENVIADO = "enviado"
REUNIAO_CANCELADA = "cancelada"
# Reuniões mais antigas que isso não geram pendência nova (evita avalanche
# de alertas retroativos quando a regra é ligada).
JANELA_RELATORIO_DIAS = 14


class CellAlertRuleError(ValueError):
    """Parâmetro ou tipo de regra inválido (mensagem segura para o painel)."""


@dataclass(frozen=True, slots=True)
class ParamSpec:
    nome: str
    rotulo: str
    unidade: str
    minimo: int
    maximo: int
    padrao: int


@dataclass(frozen=True, slots=True)
class RuleSpec:
    tipo: str
    titulo: str
    descricao: str
    acao: str
    parametros: tuple[ParamSpec, ...] = ()


RULES: dict[str, RuleSpec] = {
    spec.tipo: spec
    for spec in (
        RuleSpec(
            VISITANTE_NOVO,
            "Visitante novo a acompanhar",
            "Visitante registrado no relatório de uma reunião recente da célula.",
            "Faça contato com o visitante desta semana.",
            (ParamSpec("janela_dias", "Considerar reuniões dos últimos", "dias", 1, 30, 7),),
        ),
        RuleSpec(
            LIDERADO_EM_CONSOLIDACAO,
            "Liderado em consolidação",
            "Membro ativo da célula com consolidação em andamento.",
            "Acompanhe as etapas da consolidação deste liderado.",
        ),
        RuleSpec(
            RELATORIO_PENDENTE,
            "Relatório de célula pendente",
            "Reunião passada sem relatório enviado depois do prazo.",
            "Envie o relatório da reunião.",
            (ParamSpec("horas_apos_reuniao", "Avisar depois de", "horas", 1, 168, 24),),
        ),
        RuleSpec(
            PRAZO_VENCENDO,
            "Prazo de conexão vencendo",
            "Consolidação de liderado com prazo de conexão próximo ou vencido.",
            "Conecte o liderado à célula antes do prazo.",
            (ParamSpec("antecedencia_horas", "Avisar com antecedência de", "horas", 1, 336, 48),),
        ),
        RuleSpec(
            META_ATINGIDA,
            "Meta de membros atingida",
            "Célula atingiu a meta de membros ativos.",
            "Converse com sua liderança sobre a multiplicação.",
            (ParamSpec("meta_membros", "Meta de membros ativos", "membros", 2, 200, 12),),
        ),
    )
}


# ---------------------------------------------------------------------------
# Gate por igreja
# ---------------------------------------------------------------------------
def cell_alert_release_includes(igreja_id: object) -> bool:
    """True só para igreja listada (lista vazia, malformada ou repetida = nenhuma)."""
    if type(igreja_id) is not uuid.UUID or igreja_id.int == 0:
        return False
    return igreja_id in enabled_igreja_ids()


def enabled_igreja_ids() -> tuple[uuid.UUID, ...]:
    raw = os.environ.get(ENV_ALLOWLIST, "")
    if type(raw) is not str or not raw.strip():
        return ()
    pieces = raw.split(",")
    if any(not piece.strip() for piece in pieces):
        return ()
    try:
        ids = tuple(uuid.UUID(piece.strip()) for piece in pieces)
    except ValueError:
        return ()
    if len(ids) != len(set(ids)) or any(i.int == 0 for i in ids):
        return ()
    return ids


# ---------------------------------------------------------------------------
# Configuração (admin)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RuleState:
    spec: RuleSpec
    ativo: bool
    parametros: dict[str, int]
    atualizado_em: dt.datetime | None


def default_params(spec: RuleSpec) -> dict[str, int]:
    return {p.nome: p.padrao for p in spec.parametros}


def normalize_params(spec: RuleSpec, raw: object, *, strict: bool) -> dict[str, int]:
    """Valida parâmetros. ``strict`` recusa chaves/valores ruins; senão usa o padrão."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        if strict:
            raise CellAlertRuleError("Parâmetros inválidos")
        raw = {}
    known = {p.nome for p in spec.parametros}
    if strict and set(raw) - known:
        raise CellAlertRuleError("Parâmetro desconhecido para esta regra")
    out: dict[str, int] = {}
    for p in spec.parametros:
        value = raw.get(p.nome, p.padrao)
        valid = type(value) is int and p.minimo <= value <= p.maximo
        if not valid:
            if strict:
                raise CellAlertRuleError(
                    f"{p.rotulo}: use um número inteiro entre {p.minimo} e {p.maximo} {p.unidade}"
                )
            value = p.padrao
        out[p.nome] = value
    return out


def list_rules(session: Session, igreja_id: uuid.UUID) -> list[RuleState]:
    rows = {
        r.tipo: r
        for r in session.execute(
            select(CelulaAlertaRegra).where(CelulaAlertaRegra.igreja_id == igreja_id)
        ).scalars()
    }
    states = []
    for spec in RULES.values():
        row = rows.get(spec.tipo)
        states.append(
            RuleState(
                spec=spec,
                ativo=bool(row.ativo) if row else False,
                parametros=normalize_params(spec, row.parametros if row else None, strict=False),
                atualizado_em=row.atualizado_em if row else None,
            )
        )
    return states


def save_rule(
    session: Session,
    igreja_id: uuid.UUID,
    tipo: str,
    *,
    ativo: bool,
    parametros: object,
    actor_app_user_id: uuid.UUID,
) -> RuleState:
    spec = RULES.get(tipo)
    if spec is None:
        raise CellAlertRuleError("Regra de alerta desconhecida")
    params = normalize_params(spec, parametros, strict=True)
    now = dt.datetime.now(dt.timezone.utc)
    row = session.execute(
        select(CelulaAlertaRegra).where(
            CelulaAlertaRegra.igreja_id == igreja_id,
            CelulaAlertaRegra.tipo == tipo,
        )
    ).scalar_one_or_none()
    if row is None:
        row = CelulaAlertaRegra(igreja_id=igreja_id, tipo=tipo)
        session.add(row)
    row.ativo = bool(ativo)
    row.parametros = params
    row.atualizado_por = actor_app_user_id
    row.atualizado_em = now
    session.flush()
    return RuleState(spec=spec, ativo=row.ativo, parametros=params, atualizado_em=now)


# ---------------------------------------------------------------------------
# Avaliação (funções puras sobre linhas já lidas no escopo da igreja)
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class AlertCandidate:
    regra_tipo: str
    fato_chave: str
    celula_id: uuid.UUID
    pessoa_id: uuid.UUID | None
    acao: str


def _fmt_data(value: dt.date) -> str:
    return value.strftime("%d/%m")


def meeting_start(data: dt.date, hora: str | None) -> dt.datetime:
    """Início da reunião em São Paulo; sem hora válida, considera o fim do dia."""
    if isinstance(hora, str):
        parts = hora.strip().split(":")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1][:2].isdigit():
            h, m = int(parts[0]), int(parts[1][:2])
            if 0 <= h < 24 and 0 <= m < 60:
                return dt.datetime.combine(data, dt.time(h, m), tzinfo=SAO_PAULO_TZ)
    return dt.datetime.combine(data, dt.time(23, 59), tzinfo=SAO_PAULO_TZ)


def visitante_candidates(
    rows: Iterable[tuple[uuid.UUID, uuid.UUID, dt.date]],
    *,
    today: dt.date,
    janela_dias: int,
) -> list[AlertCandidate]:
    """rows: (visitante_id, celula_id, data_reuniao)."""
    inicio = today - dt.timedelta(days=janela_dias)
    spec = RULES[VISITANTE_NOVO]
    return [
        AlertCandidate(
            VISITANTE_NOVO,
            str(visitante_id),
            celula_id,
            None,
            f"Visitante na reunião de {_fmt_data(data)}. {spec.acao}",
        )
        for visitante_id, celula_id, data in rows
        if inicio <= data <= today
    ]


def consolidacao_candidates(
    rows: Iterable[tuple[uuid.UUID, uuid.UUID, uuid.UUID]],
) -> list[AlertCandidate]:
    """rows: (consolidacao_id, celula_id, pessoa_id) de trilhas em andamento."""
    spec = RULES[LIDERADO_EM_CONSOLIDACAO]
    return [
        AlertCandidate(LIDERADO_EM_CONSOLIDACAO, f"{cid}:{celula_id}", celula_id, pessoa_id, spec.acao)
        for cid, celula_id, pessoa_id in rows
    ]


def relatorio_candidates(
    rows: Iterable[tuple[uuid.UUID, uuid.UUID, dt.date, str | None]],
    *,
    now: dt.datetime,
    horas_apos_reuniao: int,
) -> list[AlertCandidate]:
    """rows: (reuniao_id, celula_id, data, hora) sem relatório enviado."""
    spec = RULES[RELATORIO_PENDENTE]
    out = []
    for reuniao_id, celula_id, data, hora in rows:
        due = meeting_start(data, hora) + dt.timedelta(hours=horas_apos_reuniao)
        if now >= due:
            out.append(
                AlertCandidate(
                    RELATORIO_PENDENTE,
                    str(reuniao_id),
                    celula_id,
                    None,
                    f"Reunião de {_fmt_data(data)} sem relatório. {spec.acao}",
                )
            )
    return out


def prazo_candidates(
    rows: Iterable[tuple[uuid.UUID, uuid.UUID, uuid.UUID, dt.datetime]],
    *,
    now: dt.datetime,
    antecedencia_horas: int,
) -> list[AlertCandidate]:
    """rows: (consolidacao_id, celula_id, pessoa_id, prazo_conexao).

    O prazo entra na chave: se for remarcado, o novo prazo gera novo alerta.
    """
    spec = RULES[PRAZO_VENCENDO]
    limite = now + dt.timedelta(hours=antecedencia_horas)
    out = []
    for cid, celula_id, pessoa_id, prazo in rows:
        if prazo is None or prazo.tzinfo is None or prazo > limite:
            continue
        quando = prazo.astimezone(SAO_PAULO_TZ).date()
        texto = "venceu" if prazo <= now else "vence"
        out.append(
            AlertCandidate(
                PRAZO_VENCENDO,
                f"{cid}:{celula_id}:{prazo.astimezone(dt.timezone.utc).isoformat()}",
                celula_id,
                pessoa_id,
                f"Prazo de conexão {texto} em {_fmt_data(quando)}. {spec.acao}",
            )
        )
    return out


def meta_candidates(
    rows: Iterable[tuple[uuid.UUID, int]],
    *,
    meta_membros: int,
) -> list[AlertCandidate]:
    """rows: (celula_id, membros_ativos). A meta entra na chave do fato."""
    spec = RULES[META_ATINGIDA]
    return [
        AlertCandidate(
            META_ATINGIDA,
            f"{celula_id}:membros:{meta_membros}",
            celula_id,
            None,
            f"A célula chegou a {total} membros ativos (meta {meta_membros}). {spec.acao}",
        )
        for celula_id, total in rows
        if total >= meta_membros
    ]


# ---------------------------------------------------------------------------
# Leitura do banco (sempre com igreja_id explícito, além da RLS)
# ---------------------------------------------------------------------------
def _active_led_cells(igreja_id: uuid.UUID):
    return select(Celula.id).where(
        Celula.igreja_id == igreja_id,
        Celula.ativo.is_(True),
        Celula.lider_id.is_not(None),
    )


def _open_consolidations_of_members(session: Session, igreja_id: uuid.UUID):
    return session.execute(
        select(Consolidacao.id, CelulaMembro.celula_id, Consolidacao.pessoa_id, Consolidacao.prazo_conexao)
        .join(
            CelulaMembro,
            (CelulaMembro.igreja_id == Consolidacao.igreja_id)
            & (CelulaMembro.pessoa_id == Consolidacao.pessoa_id),
        )
        .where(
            Consolidacao.igreja_id == igreja_id,
            Consolidacao.concluida.is_(False),
            Consolidacao.abandonada_em.is_(None),
            CelulaMembro.ativo.is_(True),
            CelulaMembro.celula_id.in_(_active_led_cells(igreja_id)),
        )
    ).all()


def collect_candidates(
    session: Session,
    igreja_id: uuid.UUID,
    rules: Iterable[RuleState],
    *,
    now: dt.datetime,
) -> list[AlertCandidate]:
    today = now.astimezone(SAO_PAULO_TZ).date()
    out: list[AlertCandidate] = []
    consolidations = None
    for rule in rules:
        if not rule.ativo:
            continue
        tipo, params = rule.spec.tipo, rule.parametros
        if tipo == VISITANTE_NOVO:
            inicio = today - dt.timedelta(days=params["janela_dias"])
            rows = session.execute(
                select(CelulaVisitante.id, CelulaReuniao.celula_id, CelulaReuniao.data)
                .join(
                    CelulaReuniao,
                    (CelulaReuniao.igreja_id == CelulaVisitante.igreja_id)
                    & (CelulaReuniao.id == CelulaVisitante.reuniao_id),
                )
                .where(
                    CelulaVisitante.igreja_id == igreja_id,
                    CelulaReuniao.igreja_id == igreja_id,
                    CelulaReuniao.data >= inicio,
                    CelulaReuniao.data <= today,
                    CelulaReuniao.celula_id.in_(_active_led_cells(igreja_id)),
                )
            ).all()
            out += visitante_candidates(rows, today=today, janela_dias=params["janela_dias"])
        elif tipo in (LIDERADO_EM_CONSOLIDACAO, PRAZO_VENCENDO):
            if consolidations is None:
                consolidations = _open_consolidations_of_members(session, igreja_id)
            if tipo == LIDERADO_EM_CONSOLIDACAO:
                out += consolidacao_candidates((c, cel, p) for c, cel, p, _ in consolidations)
            else:
                out += prazo_candidates(
                    ((c, cel, p, prazo) for c, cel, p, prazo in consolidations if prazo is not None),
                    now=now,
                    antecedencia_horas=params["antecedencia_horas"],
                )
        elif tipo == RELATORIO_PENDENTE:
            rows = session.execute(
                select(CelulaReuniao.id, CelulaReuniao.celula_id, CelulaReuniao.data, CelulaReuniao.hora).where(
                    CelulaReuniao.igreja_id == igreja_id,
                    CelulaReuniao.data >= today - dt.timedelta(days=JANELA_RELATORIO_DIAS),
                    CelulaReuniao.data <= today,
                    CelulaReuniao.status != REUNIAO_CANCELADA,
                    CelulaReuniao.relatorio_status != RELATORIO_ENVIADO,
                    CelulaReuniao.celula_id.in_(_active_led_cells(igreja_id)),
                )
            ).all()
            out += relatorio_candidates(rows, now=now, horas_apos_reuniao=params["horas_apos_reuniao"])
        elif tipo == META_ATINGIDA:
            rows = session.execute(
                select(CelulaMembro.celula_id, func.count())
                .where(
                    CelulaMembro.igreja_id == igreja_id,
                    CelulaMembro.ativo.is_(True),
                    CelulaMembro.celula_id.in_(_active_led_cells(igreja_id)),
                )
                .group_by(CelulaMembro.celula_id)
            ).all()
            out += meta_candidates(rows, meta_membros=params["meta_membros"])
    return out


def persist_candidates(
    session: Session, igreja_id: uuid.UUID, candidates: Iterable[AlertCandidate]
) -> int:
    """Grava um alerta por fato; conflito na chave = já existe, nada muda."""
    created = 0
    for c in candidates:
        result = session.execute(
            pg_insert(CellAlert)
            .values(
                igreja_id=igreja_id,
                celula_id=c.celula_id,
                pessoa_id=c.pessoa_id,
                gatilho=RULES[c.regra_tipo].titulo,
                acao_esperada=c.acao,
                regra_tipo=c.regra_tipo,
                fato_chave=c.fato_chave,
            )
            .on_conflict_do_nothing(index_elements=["igreja_id", "regra_tipo", "fato_chave"])
        )
        created += int(result.rowcount or 0)
    return created


def evaluate_igreja(session: Session, igreja_id: uuid.UUID, *, now: dt.datetime) -> int:
    """Avalia as regras ativas de uma igreja na sessão já escopada. Não faz commit."""
    rules = [r for r in list_rules(session, igreja_id) if r.ativo]
    if not rules:
        return 0
    return persist_candidates(session, igreja_id, collect_candidates(session, igreja_id, rules, now=now))


def run_cell_alert_cycle(
    session_factory: Callable[[], Session],
    *,
    now: dt.datetime | None = None,
    scope: Callable[[Session, uuid.UUID], Any] | None = None,
) -> int:
    """Um ciclo do cron: cada igreja liberada numa sessão própria, isolada."""
    current = now or dt.datetime.now(dt.timezone.utc)
    if scope is None:
        from app.db.tenant_session import mark_tenant_scoped

        def scope(s: Session, igreja_id: uuid.UUID) -> None:
            mark_tenant_scoped(s, igreja_id, source="cell_alert_rules")

    created = 0
    for igreja_id in enabled_igreja_ids():
        session = session_factory()
        try:
            scope(session, igreja_id)
            created += evaluate_igreja(session, igreja_id, now=current)
            session.commit()
        except Exception:  # noqa: BLE001 - uma igreja não derruba as outras
            logger.exception("Cell alert evaluation failed", extra={"event": "cell_alert_eval_failed"})
            try:
                session.rollback()
            except Exception:  # noqa: BLE001
                logger.exception("Cell alert rollback failed")
        finally:
            session.close()
    return created
