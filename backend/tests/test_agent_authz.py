"""Autorização das tools do agente por privilégio do interlocutor (#10b Fase 2).

Fecha o escalonamento: um contato comum não pode disparar ação ministerial
(ex.: registrar uma decisão para si via "relatório" falso). Cobre o domínio puro
(PrivilegeContext / tool_allowed) e o GATE determinístico no executor de tools.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.domain.agent_authz import (
    MINISTERIAL_TOOLS,
    PrivilegeContext,
    has_ministerial_role,
    tool_allowed,
)


# ---- domínio puro ---------------------------------------------------------
def test_contato_nao_e_ministerial() -> None:
    ctx = PrivilegeContext(pessoa_id="p", tipo="contato")
    assert ctx.is_ministerial is False
    assert tool_allowed(ctx, "registrar_decisao") is False


def test_visitante_e_membro_nao_sao_ministeriais() -> None:
    for tipo in ("visitante", "membro"):
        assert PrivilegeContext(pessoa_id="p", tipo=tipo).is_ministerial is False


def test_papel_de_lider_torna_ministerial() -> None:
    ctx = PrivilegeContext(
        pessoa_id="p", tipo="membro", roles=frozenset({"lider_celula"})
    )
    assert ctx.is_ministerial is True
    assert tool_allowed(ctx, "registrar_decisao") is True


def test_liderar_celula_torna_ministerial() -> None:
    ctx = PrivilegeContext(pessoa_id="p", tipo="membro", leads_cells=True)
    assert ctx.is_ministerial is True


def test_tipo_lider_ou_pastor_e_ministerial() -> None:
    assert PrivilegeContext(pessoa_id="p", tipo="lider").is_ministerial is True
    assert PrivilegeContext(pessoa_id="p", tipo="pastor").is_ministerial is True


def test_csim_nunca_e_ministerial() -> None:
    # Mesmo um pastor marcado como CSIM está fora do funil → nega.
    ctx = PrivilegeContext(
        pessoa_id="p",
        tipo="pastor",
        roles=frozenset({"pastor"}),
        leads_cells=True,
        sem_interesse=True,
    )
    assert ctx.is_ministerial is False
    assert tool_allowed(ctx, "registrar_decisao") is False


def test_as_quatro_tools_sao_ministeriais() -> None:
    contato = PrivilegeContext(pessoa_id="p", tipo="contato")
    for t in ("registrar_decisao", "marcar_presenca", "vincular_celula", "avancar_trilha"):
        assert tool_allowed(contato, t) is False
    assert MINISTERIAL_TOOLS == {
        "registrar_decisao",
        "marcar_presenca",
        "vincular_celula",
        "avancar_trilha",
    }


def test_tool_desconhecida_liberada_por_padrao() -> None:
    # Tools futuras de leitura pública não são bloqueadas pelo gate ministerial.
    contato = PrivilegeContext(pessoa_id="p", tipo="contato")
    assert tool_allowed(contato, "buscar_horario_culto") is True


def test_has_ministerial_role_helper() -> None:
    assert has_ministerial_role(["lider_celula"]) is True
    assert has_ministerial_role(["membro", "operador"]) is False


# ---- gate no executor de tools (segurança dura) ---------------------------
class _BoomSession:
    """Sessão que explode se for tocada — prova que a tool negada NÃO roda."""

    def execute(self, *a, **k):  # pragma: no cover - não deve ser chamado
        raise AssertionError("tool negada não pode tocar o banco")


def test_execute_tools_nega_contato_sem_rodar_a_tool() -> None:
    from app.agent.runtime import _execute_tools

    ctx = PrivilegeContext(pessoa_id="p1", tipo="contato")  # não-ministerial
    calls = [
        {
            "ferramenta": "registrar_decisao",
            "args": {"pessoa_id": "p1", "vinculo": "visitante"},
        }
    ]
    executed, audit = _execute_tools(_BoomSession(), uuid.uuid4(), ctx, calls)

    assert executed == []  # nada executou
    assert any(a["evento"] == "tool_negada" for a in audit)
    negada = next(a for a in audit if a["evento"] == "tool_negada")
    assert negada["payload"]["ferramenta"] == "registrar_decisao"
    assert negada["payload"]["tipo"] == "contato"


# ---- resolução do privilégio (trava nomes de coluna + filtro de tenant) ----
class _PrivResult:
    def __init__(self, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class _PrivSession:
    """Roteia as 3 queries de _resolve_privilege por entidade (AppUser/UserRole/Celula)."""

    def __init__(self, *, app_user_id=None, roles=None, leads=False) -> None:
        self.app_user_id = app_user_id
        self.roles = roles or []
        self.leads = leads

    def execute(self, statement, params=None) -> _PrivResult:
        from app.db.models import AppUser, Celula, UserRole

        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _PrivResult(scalar=self.app_user_id)
        if ent is UserRole:
            return _PrivResult(scalars=self.roles)
        if ent is Celula:
            return _PrivResult(scalar=(uuid.uuid4() if self.leads else None))
        return _PrivResult()


_IGREJA = uuid.uuid4()


def _pessoa(tipo: str = "contato", sem_interesse: bool = False):
    return SimpleNamespace(id=uuid.uuid4(), tipo=tipo, sem_interesse=sem_interesse)


def test_resolve_privilege_contato_sem_login_nao_e_ministerial() -> None:
    from app.agent.runtime import _resolve_privilege

    ctx = _resolve_privilege(_PrivSession(app_user_id=None), _IGREJA, _pessoa())
    assert ctx.roles == frozenset()
    assert ctx.leads_cells is False
    assert ctx.is_ministerial is False


def test_resolve_privilege_papel_de_lider_via_login() -> None:
    from app.agent.runtime import _resolve_privilege

    ctx = _resolve_privilege(
        _PrivSession(app_user_id=uuid.uuid4(), roles=["lider_celula"]),
        _IGREJA,
        _pessoa(tipo="membro"),
    )
    assert "lider_celula" in ctx.roles
    assert ctx.is_ministerial is True


def test_resolve_privilege_lidera_celula_sem_login() -> None:
    from app.agent.runtime import _resolve_privilege

    ctx = _resolve_privilege(
        _PrivSession(app_user_id=None, leads=True), _IGREJA, _pessoa(tipo="membro")
    )
    assert ctx.leads_cells is True
    assert ctx.is_ministerial is True
