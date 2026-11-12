"""RF-26: configuração das regras de alerta ao líder (somente admin).

O admin vê e edita as regras da própria igreja. O papel vem do servidor
(``require_role``), o ``igreja_id`` vem da sessão autenticada e a RLS isola a
tabela por igreja. ``processamentoLiberado`` mostra se o gate operacional da
igreja está aberto; o painel não abre esse gate.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.deps import CurrentUser, require_role
from app.services import cell_alert_rules as svc

router = APIRouter(tags=["cell-alert-rules"])

require_admin = require_role(["admin"])


class AlertRuleParamOut(BaseModel):
    nome: str
    rotulo: str
    unidade: str
    minimo: int
    maximo: int
    padrao: int
    valor: int


class AlertRuleOut(BaseModel):
    tipo: str
    titulo: str
    descricao: str
    ativo: bool
    parametros: list[AlertRuleParamOut]
    atualizadoEm: dt.datetime | None = None  # noqa: N815

    @classmethod
    def from_state(cls, state: svc.RuleState) -> "AlertRuleOut":
        return cls(
            tipo=state.spec.tipo,
            titulo=state.spec.titulo,
            descricao=state.spec.descricao,
            ativo=state.ativo,
            parametros=[
                AlertRuleParamOut(
                    nome=p.nome,
                    rotulo=p.rotulo,
                    unidade=p.unidade,
                    minimo=p.minimo,
                    maximo=p.maximo,
                    padrao=p.padrao,
                    valor=state.parametros[p.nome],
                )
                for p in state.spec.parametros
            ],
            atualizadoEm=state.atualizado_em,
        )


class AlertRulesOut(BaseModel):
    processamentoLiberado: bool  # noqa: N815
    regras: list[AlertRuleOut]


class AlertRuleUpdate(BaseModel):
    ativo: bool
    parametros: dict[str, int] = Field(default_factory=dict)


@router.get("/cell-alert-rules", response_model=AlertRulesOut)
def list_cell_alert_rules(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> AlertRulesOut:
    igreja_id = uuid.UUID(current_user.igreja_id)
    return AlertRulesOut(
        processamentoLiberado=svc.cell_alert_release_includes(igreja_id),
        regras=[AlertRuleOut.from_state(s) for s in svc.list_rules(db, igreja_id)],
    )


@router.put("/cell-alert-rules/{tipo}", response_model=AlertRuleOut)
def update_cell_alert_rule(
    tipo: str,
    payload: AlertRuleUpdate,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
) -> AlertRuleOut:
    if tipo not in svc.RULES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Regra de alerta não encontrada")
    try:
        state = svc.save_rule(
            db,
            uuid.UUID(current_user.igreja_id),
            tipo,
            ativo=payload.ativo,
            parametros=payload.parametros,
            actor_app_user_id=uuid.UUID(current_user.app_user_id),
        )
        db.commit()
    except svc.CellAlertRuleError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return AlertRuleOut.from_state(state)
