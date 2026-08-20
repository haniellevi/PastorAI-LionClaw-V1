"""Autorização das tools do agente por privilégio do interlocutor (#10b Fase 2).

Fecha o escalonamento: um contato comum não pode disparar ação ministerial
(ex.: registrar uma decisão para si via "relatório" falso). Cobre o domínio puro
(PrivilegeContext / tool_allowed) e o GATE determinístico no executor de tools.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.domain.agent_authz import (
    CENTRAL_TOOL_ROLES,
    CENTRAL_TOOLS,
    MINISTERIAL_TOOLS,
    PrivilegeContext,
    has_central_tool_role,
    has_ministerial_role,
    tool_allowed,
    tool_denial_reason,
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
    assert tool_allowed(ctx, "vincular_celula") is False


def test_liderar_celula_torna_ministerial() -> None:
    ctx = PrivilegeContext(pessoa_id="p", tipo="membro", leads_cells=True)
    assert ctx.is_ministerial is True


def test_tipo_lider_ou_pastor_e_ministerial() -> None:
    assert PrivilegeContext(pessoa_id="p", tipo="lider").is_ministerial is True
    assert PrivilegeContext(pessoa_id="p", tipo="pastor").is_ministerial is True
    # Tipo pastoral sem acesso utilizável não equivale à capacidade da Central.
    assert tool_allowed(
        PrivilegeContext(pessoa_id="p", tipo="pastor"), "vincular_celula"
    ) is False


@pytest.mark.parametrize("role", ["admin", "pastor"])
def test_vincular_celula_exige_papel_da_central(role: str) -> None:
    ctx = PrivilegeContext(
        pessoa_id="p",
        tipo="membro",
        roles=frozenset({"membro", "lider_celula", role}),
    )
    assert tool_allowed(ctx, "vincular_celula") is True
    assert has_central_tool_role(ctx.roles) is True


@pytest.mark.parametrize(
    "role",
    ["lider_celula", "lider_g12", "lider_consol", "lider_mult", "membro", "operador"],
)
def test_vincular_celula_nega_papeis_fora_da_central(role: str) -> None:
    ctx = PrivilegeContext(
        pessoa_id="p", tipo="membro", roles=frozenset({role}), leads_cells=True
    )
    assert tool_allowed(ctx, "vincular_celula") is False
    assert tool_denial_reason(ctx, "vincular_celula") == (
        "interlocutor sem capacidade da Central de Células"
    )


@pytest.mark.parametrize(
    "tool_name", ["registrar_decisao", "marcar_presenca", "avancar_trilha"]
)
def test_restricao_da_central_nao_remove_demais_tools_do_lider(
    tool_name: str,
) -> None:
    ctx = PrivilegeContext(
        pessoa_id="p", tipo="membro", roles=frozenset({"lider_celula"})
    )
    assert tool_allowed(ctx, tool_name) is True


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
    assert tool_allowed(ctx, "vincular_celula") is False


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
    assert CENTRAL_TOOLS == {"vincular_celula"}
    assert CENTRAL_TOOL_ROLES == {"admin", "pastor"}


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


def test_execute_tools_nega_vinculo_para_lider_sem_tocar_o_banco() -> None:
    from app.agent.runtime import _execute_tools

    ctx = PrivilegeContext(
        pessoa_id="p1",
        tipo="lider",
        roles=frozenset({"lider_celula", "lider_g12"}),
        leads_cells=True,
    )
    calls = [
        {
            "ferramenta": "vincular_celula",
            "args": {"pessoa_id": "p2", "celula_id": "c1"},
        }
    ]

    executed, audit = _execute_tools(_BoomSession(), uuid.uuid4(), ctx, calls)

    assert executed == []
    assert audit == [
        {
            "evento": "tool_negada",
            "payload": {
                "ferramenta": "vincular_celula",
                "motivo": "interlocutor sem capacidade da Central de Células",
                "tipo": "lider",
            },
        }
    ]


def test_execute_tools_injeta_papeis_acumulados_confiaveis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.agent.runtime as runtime

    igreja_id = uuid.uuid4()
    captured: dict = {}

    def fake_vincular(
        session,
        *,
        igreja_id,
        pessoa_id,
        celula_id,
        actor_roles,
    ):
        captured.update(
            session=session,
            igreja_id=igreja_id,
            pessoa_id=pessoa_id,
            celula_id=celula_id,
            actor_roles=actor_roles,
        )
        return SimpleNamespace(detalhe={"pessoaId": pessoa_id, "celulaId": celula_id})

    monkeypatch.setitem(runtime.TOOLS, "vincular_celula", fake_vincular)
    session = _BoomSession()
    roles = frozenset({"membro", "lider_celula", "pastor"})
    ctx = PrivilegeContext(pessoa_id="p1", tipo="membro", roles=roles)

    executed, audit = runtime._execute_tools(
        session,
        igreja_id,
        ctx,
        [
            {
                "ferramenta": "vincular_celula",
                "args": {"pessoa_id": "p2", "celula_id": "c1"},
            }
        ],
    )

    assert executed == ["vincular_celula"]
    assert audit[0]["evento"] == "tool_call"
    assert captured == {
        "session": session,
        "igreja_id": igreja_id,
        "pessoa_id": "p2",
        "celula_id": "c1",
        "actor_roles": roles,
    }


def test_execute_tools_rejeita_actor_roles_forjado_pelo_llm() -> None:
    from app.agent.runtime import _execute_tools

    ctx = PrivilegeContext(
        pessoa_id="p1", tipo="membro", roles=frozenset({"pastor"})
    )
    executed, audit = _execute_tools(
        _BoomSession(),
        uuid.uuid4(),
        ctx,
        [
            {
                "ferramenta": "vincular_celula",
                "args": {
                    "pessoa_id": "p2",
                    "celula_id": "c1",
                    "actor_roles": ["admin"],
                },
            }
        ],
    )

    assert executed == []
    assert audit[0]["evento"] == "tool_error"
    assert "actor_roles" in audit[0]["payload"]["erro"]


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

    def __init__(
        self,
        *,
        app_user_id=None,
        app_user_status="ativo",
        clerk_user_id="clerk_user",
        roles=None,
        leads=False,
        led_cell_active=True,
        duplicate_usable_access=False,
    ) -> None:
        self.app_user_id = app_user_id
        self.app_user_status = app_user_status
        self.clerk_user_id = clerk_user_id
        self.roles = roles or []
        self.leads = leads
        self.led_cell_active = led_cell_active
        self.duplicate_usable_access = duplicate_usable_access
        self.app_user_statement = None
        self.cell_statement = None
        self.roles_queries = 0

    def execute(self, statement, params=None) -> _PrivResult:
        from app.db.models import AppUser, Celula, UserRole

        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            self.app_user_statement = statement
            usable = (
                self.app_user_id is not None
                and self.clerk_user_id is not None
                and self.app_user_status in {None, "ativo"}
            )
            usable_ids = [self.app_user_id] if usable else []
            if usable and self.duplicate_usable_access:
                usable_ids.append(uuid.uuid4())
            return _PrivResult(scalars=usable_ids)
        if ent is UserRole:
            self.roles_queries += 1
            return _PrivResult(scalars=self.roles)
        if ent is Celula:
            self.cell_statement = statement
            leads_active_cell = self.leads and self.led_cell_active
            return _PrivResult(
                scalar=(uuid.uuid4() if leads_active_cell else None)
            )
        return _PrivResult()


_IGREJA = uuid.uuid4()


def _pessoa(
    tipo: str = "contato",
    sem_interesse: bool = False,
    pessoa_id: uuid.UUID | None = None,
):
    return SimpleNamespace(
        id=pessoa_id or uuid.uuid4(), tipo=tipo, sem_interesse=sem_interesse
    )


def _assert_privilege_queries_are_tenant_scoped(
    session: _PrivSession, pessoa_id: uuid.UUID
) -> None:
    assert session.app_user_statement is not None
    access_sql = str(session.app_user_statement)
    assert "app_users.pessoa_id" in access_sql
    assert "app_users.igreja_id" in access_sql
    assert "app_users.clerk_user_id IS NOT NULL" in access_sql
    assert "app_users.status IS NULL" in access_sql
    assert "app_users.status =" in access_sql
    access_params = session.app_user_statement.compile().params.values()
    assert pessoa_id in access_params
    assert _IGREJA in access_params

    assert session.cell_statement is not None
    cell_sql = str(session.cell_statement)
    assert "celulas.lider_id" in cell_sql
    assert "celulas.igreja_id" in cell_sql
    assert "celulas.ativo IS true" in cell_sql
    cell_params = session.cell_statement.compile().params.values()
    assert pessoa_id in cell_params
    assert _IGREJA in cell_params


def test_resolve_privilege_contato_sem_login_nao_e_ministerial() -> None:
    from app.agent.runtime import _resolve_privilege

    pessoa = _pessoa()
    session = _PrivSession(app_user_id=None)
    ctx = _resolve_privilege(session, _IGREJA, pessoa)
    assert ctx.roles == frozenset()
    assert ctx.leads_cells is False
    assert ctx.is_ministerial is False
    _assert_privilege_queries_are_tenant_scoped(session, pessoa.id)


def test_resolve_privilege_papel_de_lider_via_login() -> None:
    from app.agent.runtime import _resolve_privilege

    pessoa = _pessoa(tipo="membro")
    session = _PrivSession(app_user_id=uuid.uuid4(), roles=["lider_celula"])
    ctx = _resolve_privilege(
        session,
        _IGREJA,
        pessoa,
    )
    assert "lider_celula" in ctx.roles
    assert ctx.is_ministerial is True
    assert session.roles_queries == 1
    _assert_privilege_queries_are_tenant_scoped(session, pessoa.id)


def test_resolve_privilege_lidera_celula_sem_login() -> None:
    from app.agent.runtime import _resolve_privilege

    ctx = _resolve_privilege(
        _PrivSession(app_user_id=None, leads=True), _IGREJA, _pessoa(tipo="membro")
    )
    assert ctx.leads_cells is True
    assert ctx.is_ministerial is True


def test_resolve_privilege_ignora_lideranca_de_celula_inativa() -> None:
    from app.agent.runtime import _resolve_privilege

    ctx = _resolve_privilege(
        _PrivSession(app_user_id=None, leads=True, led_cell_active=False),
        _IGREJA,
        _pessoa(tipo="membro"),
    )
    assert ctx.leads_cells is False
    assert ctx.is_ministerial is False


def test_resolve_privilege_falha_fechado_com_acessos_utilizaveis_duplicados() -> None:
    from app.agent.runtime import _resolve_privilege

    session = _PrivSession(
        app_user_id=uuid.uuid4(),
        roles=["admin"],
        duplicate_usable_access=True,
    )
    ctx = _resolve_privilege(session, _IGREJA, _pessoa(tipo="membro"))

    assert ctx.roles == frozenset()
    assert session.roles_queries == 0
    assert tool_allowed(ctx, "vincular_celula") is False


@pytest.mark.parametrize("role,tipo", [("admin", "membro"), ("pastor", "pastor")])
@pytest.mark.parametrize(
    "status,clerk_user_id",
    [
        ("revogado", "clerk_user"),
        ("convidado", "clerk_user"),
        ("ativo", None),
        (None, None),
    ],
)
def test_acesso_inutilizavel_nao_autoriza_vincular_e_nao_toca_writer(
    role: str,
    tipo: str,
    status: str | None,
    clerk_user_id: str | None,
) -> None:
    from app.agent.runtime import _execute_tools, _resolve_privilege

    privilege_session = _PrivSession(
        app_user_id=uuid.uuid4(),
        app_user_status=status,
        clerk_user_id=clerk_user_id,
        roles=[role],
    )
    ctx = _resolve_privilege(privilege_session, _IGREJA, _pessoa(tipo=tipo))

    # UserRole persistido não é sequer consultado sem acesso utilizável.
    assert ctx.roles == frozenset()
    assert privilege_session.roles_queries == 0
    assert tool_allowed(ctx, "vincular_celula") is False

    executed, audit = _execute_tools(
        _BoomSession(),
        _IGREJA,
        ctx,
        [
            {
                "ferramenta": "vincular_celula",
                "args": {"pessoa_id": "p2", "celula_id": "c1"},
            }
        ],
    )
    assert executed == []
    assert audit[0]["evento"] == "tool_negada"


@pytest.mark.parametrize("role", ["admin", "pastor"])
@pytest.mark.parametrize("status", [None, "ativo"])
def test_acesso_central_utilizavel_resolve_papel_e_autoriza(
    role: str, status: str | None
) -> None:
    from app.agent.runtime import _resolve_privilege

    session = _PrivSession(
        app_user_id=uuid.uuid4(),
        app_user_status=status,
        clerk_user_id="clerk_user",
        roles=["membro", role],
    )
    ctx = _resolve_privilege(session, _IGREJA, _pessoa(tipo="membro"))

    assert ctx.roles == frozenset({"membro", role})
    assert session.roles_queries == 1
    assert tool_allowed(ctx, "vincular_celula") is True
