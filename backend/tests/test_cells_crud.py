"""Tests for the Células PR1 schema/base endpoints (POST /cells + membros).

Covers the new surface added by PR1 on top of the existing cells router:
  - create sets the new leve/sensitive fields; role gating unchanged;
  - the sensitive-field guard (decisão 3.2): a non-Central editor that changes
    dia/horário/endereço/anfitrião/auxiliar gets 403; the Central applies it;
  - horário HH:MM validation;
  - direct member entry (celula_membro) with the "1 pessoa → 1 célula ativa"
    rule (409), the pessoa-not-found 404, authorization, and the legacy mirror
    (pessoas.celula_id);
  - tenant isolation on the member queries via the fake that MIRRORS the SQL
    predicates (dropping igreja_id from the router makes these fail).

Follows the fake-session style of test_agent_crons_crud.py. Real Postgres RLS is
not exercised here (no live DB); the cell lookup relies on RLS and is validated
manually in DEV — see docs/design scout. The member queries carry an explicit
igreja_id predicate, so their isolation IS exercised below.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Celula, CelulaMembro, CellAlert, Pessoa
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}

_TENANT = "00000000-0000-0000-0000-000000000001"
_OTHER = "00000000-0000-0000-0000-000000000002"
_CELL = "00000000-0000-0000-0000-0000000000e1"
_P1 = "00000000-0000-0000-0000-0000000000f1"
_P2 = "00000000-0000-0000-0000-0000000000f2"
_LP = "00000000-0000-0000-0000-0000000000b1"  # pessoa vinculada ao líder-ator
_MID = "00000000-0000-0000-0000-0000000000d1"


class _R:
    def __init__(self, *, scalar=None, scalars=None, rows=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))

    def all(self):
        return list(self._rows)


class CellSession:
    """Fake session that mirrors the statement predicates for Celula, CelulaMembro
    and Pessoa lookups. Auth (AppUser/roles) and the leadership map are served
    from the configured builders, so the router's own WHERE is what's tested.
    """

    def __init__(
        self,
        *,
        app_user,
        roles,
        cells=None,
        members=None,
        pessoas=None,
        actor_pessoa_id=None,
    ) -> None:
        self.app_user = app_user
        self.roles = roles
        self.cells = cells or []
        self.members = members or []
        self.pessoas = pessoas or []
        self.actor_pessoa_id = actor_pessoa_id
        self.added: list = []
        self.committed = False

    @staticmethod
    def _eq_predicates(statement) -> dict[str, str]:
        preds: dict[str, str] = {}
        clause = getattr(statement, "whereclause", None)
        stack = [clause] if clause is not None else []
        while stack:
            node = stack.pop()
            left = getattr(node, "left", None)
            right = getattr(node, "right", None)
            if left is not None and right is not None:
                key = getattr(left, "key", None)
                value = getattr(right, "value", None)
                if key is not None and value is not None:
                    preds[key] = str(value)
                continue
            stack.extend(getattr(node, "clauses", []) or [])
        return preds

    def _filter(self, store, statement):
        preds = self._eq_predicates(statement)
        return [
            o
            for o in store
            if all(str(getattr(o, k, None)) == v for k, v in preds.items())
        ]

    @staticmethod
    def _wants_active(statement) -> bool:
        """True se a query filtra por `ativo` (predicado `ativo.is_(True)`).

        `_eq_predicates` descarta o IS-clause (value=None), então detectamos a
        presença da coluna `ativo` no WHERE: se o router LARGAR esse filtro, o
        fake para de aplicá-lo e os testes de ativo=False quebram (exercendo-o).
        """
        clause = getattr(statement, "whereclause", None)
        stack = [clause] if clause is not None else []
        while stack:
            node = stack.pop()
            left = getattr(node, "left", None)
            if left is not None and getattr(left, "key", None) == "ativo":
                return True
            stack.extend(getattr(node, "clauses", []) or [])
        return False

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        name = descs[0].get("name") if descs else None

        if ent is AppUser and name == "pessoa_id":
            return _R(scalar=self.actor_pessoa_id)
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is Celula:
            rows = self._filter(self.cells, statement)
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is CelulaMembro:
            rows = self._filter(self.members, statement)
            if self._wants_active(statement):
                rows = [r for r in rows if getattr(r, "ativo", True) is True]
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is Pessoa and len(descs) > 1:
            # select(Pessoa.id, Pessoa.lider_id) -> tuples para o lider_of map.
            return _R(rows=[(p.id, p.lider_id) for p in self.pessoas])
        if ent is Pessoa:
            rows = self._filter(self.pessoas, statement)
            return _R(scalar=(rows[0] if rows else None))
        if ent is CellAlert:
            return _R(scalars=[])
        # set_config text / func.count / UserRole.papel projection.
        return _R(scalars=self.roles)

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        if isinstance(obj, CelulaMembro):
            self.members.append(obj)

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


def make_cell(
    *,
    cell_id: str = _CELL,
    igreja_id: str = _TENANT,
    nome: str = "Célula Central",
    lider_id: str | None = None,
    cobertura: str = "Rede Azul",
    dia_reuniao: str | None = None,
    horario: str | None = None,
    endereco: str | None = None,
    anfitriao_id: str | None = None,
    auxiliar_id: str | None = None,
    link_grupo: str | None = None,
    link_localizacao: str | None = None,
    mensagem_convite: str | None = None,
    ativo: bool = True,
):
    return SimpleNamespace(
        id=cell_id,
        igreja_id=igreja_id,
        nome=nome,
        lider_id=lider_id,
        cobertura_espiritual=cobertura,
        dia_reuniao=dia_reuniao,
        horario=horario,
        endereco=endereco,
        # UUIDs (espelham o tipo real do modelo — a comparação sensível é UUID×UUID).
        anfitriao_id=uuid.UUID(anfitriao_id) if anfitriao_id else None,
        auxiliar_id=uuid.UUID(auxiliar_id) if auxiliar_id else None,
        link_grupo=link_grupo,
        link_localizacao=link_localizacao,
        mensagem_convite=mensagem_convite,
        ativo=ativo,
        created_at=None,
    )


def make_pessoa(
    *, pessoa_id: str = _P1, igreja_id: str = _TENANT, lider_id: str | None = None,
    celula_id: str | None = None,
):
    return SimpleNamespace(
        id=pessoa_id,
        igreja_id=igreja_id,
        nome="Fulano",
        lider_id=lider_id,
        celula_id=celula_id,
        tipo="membro",
    )


def make_member(
    *, member_id: str = _MID, igreja_id: str = _TENANT, celula_id: str = _CELL,
    pessoa_id: str = _P1, papel: str = "membro", ativo: bool = True,
):
    return SimpleNamespace(
        id=member_id,
        igreja_id=igreja_id,
        celula_id=celula_id,
        pessoa_id=pessoa_id,
        papel=papel,
        ativo=ativo,
        created_at=None,
    )


def _wire(app, *, session, clerk=None) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk or FakeClerk()
    return TestClient(app)


def _full_payload(**over) -> dict:
    base = {
        "nome": "Célula Central",
        "coberturaEspiritual": "Rede Azul",
        "diaReuniao": None,
        "horario": None,
        "endereco": None,
        "anfitriaoId": None,
        "auxiliarId": None,
        "linkGrupo": None,
        "linkLocalizacao": None,
        "mensagemConvite": None,
        "ativo": True,
    }
    base.update(over)
    return base


# ---- create ---------------------------------------------------------------
def test_create_cell_sets_new_fields(app) -> None:
    session = CellSession(app_user=make_app_user(), roles=["pastor"])
    resp = _wire(app, session=session).post(
        "/cells",
        headers=_AUTH,
        json=_full_payload(
            nome="Nova Célula",
            horario="20:00",
            endereco="Rua A, 100",
            linkGrupo="https://chat.whatsapp.com/x",
        ),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["horario"] == "20:00"
    assert body["endereco"] == "Rua A, 100"
    assert body["linkGrupo"] == "https://chat.whatsapp.com/x"
    assert session.committed is True


def test_create_cell_forbidden_for_member(app) -> None:
    session = CellSession(app_user=make_app_user(), roles=["membro"])
    resp = _wire(app, session=session).post(
        "/cells", headers=_AUTH, json=_full_payload()
    )
    assert resp.status_code == 403


def test_create_cell_rejects_bad_horario(app) -> None:
    session = CellSession(app_user=make_app_user(), roles=["pastor"])
    resp = _wire(app, session=session).post(
        "/cells", headers=_AUTH, json=_full_payload(horario="25:61")
    )
    assert resp.status_code == 422


# ---- sensitive-field guard (decisão 3.2) ----------------------------------
def test_central_can_edit_sensitive(app) -> None:
    cell = make_cell(endereco="Antigo")
    session = CellSession(app_user=make_app_user(), roles=["pastor"], cells=[cell])
    resp = _wire(app, session=session).post(
        "/cells",
        headers=_AUTH,
        json=_full_payload(id=_CELL, endereco="Rua Nova, 200", horario="19:30"),
    )
    assert resp.status_code == 200, resp.text
    assert cell.endereco == "Rua Nova, 200"
    assert cell.horario == "19:30"
    assert session.committed is True


def test_non_central_leader_cannot_change_sensitive(app) -> None:
    # Líder da célula (via hierarquia), papel não-Central: mudar endereço = 403.
    cell = make_cell(lider_id=_LP, endereco=None)
    session = CellSession(
        app_user=make_app_user(),
        roles=["lider_celula"],
        cells=[cell],
        pessoas=[make_pessoa(pessoa_id=_LP)],
        actor_pessoa_id=_LP,
    )
    resp = _wire(app, session=session).post(
        "/cells",
        headers=_AUTH,
        json=_full_payload(id=_CELL, endereco="Rua Proibida, 1"),
    )
    assert resp.status_code == 403
    assert session.committed is False


def test_non_central_leader_can_edit_leve(app) -> None:
    # Mesmo líder: sem mudar sensível (todos iguais aos atuais), muda só leve.
    cell = make_cell(lider_id=_LP, nome="Antiga", link_grupo=None)
    session = CellSession(
        app_user=make_app_user(),
        roles=["lider_celula"],
        cells=[cell],
        pessoas=[make_pessoa(pessoa_id=_LP)],
        actor_pessoa_id=_LP,
    )
    resp = _wire(app, session=session).post(
        "/cells",
        headers=_AUTH,
        json=_full_payload(
            id=_CELL, nome="Nova", linkGrupo="https://chat.whatsapp.com/y"
        ),
    )
    assert resp.status_code == 200, resp.text
    assert cell.nome == "Nova"
    assert cell.link_grupo == "https://chat.whatsapp.com/y"
    assert session.committed is True


def test_non_central_leader_resending_same_sensitive_is_noop(app) -> None:
    # Reenviar o MESMO anfitrião (UUID×UUID idêntico) não é "mudança sensível":
    # o líder não-Central pode salvar edições de leve sem tomar 403.
    cell = make_cell(lider_id=_LP, anfitriao_id=_P2, nome="Antiga")
    session = CellSession(
        app_user=make_app_user(),
        roles=["lider_celula"],
        cells=[cell],
        pessoas=[make_pessoa(pessoa_id=_LP), make_pessoa(pessoa_id=_P2)],
        actor_pessoa_id=_LP,
    )
    resp = _wire(app, session=session).post(
        "/cells",
        headers=_AUTH,
        json=_full_payload(id=_CELL, nome="Nova", anfitriaoId=_P2),
    )
    assert resp.status_code == 200, resp.text
    assert cell.nome == "Nova"


# ---- member entry ---------------------------------------------------------
def test_add_member_creates_link_and_mirror(app) -> None:
    cell = make_cell()
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=None)
    session = CellSession(
        app_user=make_app_user(), roles=["pastor"], cells=[cell], pessoas=[pessoa]
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros", headers=_AUTH, json={"pessoaId": _P1}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["pessoaId"] == _P1
    assert body["papel"] == "membro"
    # espelho legado (Q1): pessoas.celula_id passa a apontar para a célula.
    assert pessoa.celula_id == cell.id
    assert session.committed is True


def test_add_member_conflicts_when_already_active(app) -> None:
    cell = make_cell()
    pessoa = make_pessoa(pessoa_id=_P1)
    existing = make_member(pessoa_id=_P1)
    session = CellSession(
        app_user=make_app_user(),
        roles=["pastor"],
        cells=[cell],
        pessoas=[pessoa],
        members=[existing],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros", headers=_AUTH, json={"pessoaId": _P1}
    )
    assert resp.status_code == 409
    assert session.committed is False


def test_add_member_active_rule_is_tenant_scoped(app) -> None:
    # Pessoa ativa em OUTRA igreja não bloqueia a entrada nesta (o predicado
    # igreja_id do check de unicidade é o que garante isso — removê-lo faria
    # este teste 409 indevidamente).
    cell = make_cell()
    pessoa = make_pessoa(pessoa_id=_P1)
    other_active = make_member(
        member_id="00000000-0000-0000-0000-0000000000d9",
        igreja_id=_OTHER,
        pessoa_id=_P1,
    )
    session = CellSession(
        app_user=make_app_user(),
        roles=["pastor"],
        cells=[cell],
        pessoas=[pessoa],
        members=[other_active],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros", headers=_AUTH, json={"pessoaId": _P1}
    )
    assert resp.status_code == 201, resp.text


def test_add_member_inactive_membership_does_not_conflict(app) -> None:
    # Vínculo INATIVO da mesma pessoa não bloqueia nova entrada (a query de
    # conflito filtra ativo.is_(True) — o índice único é parcial WHERE ativo).
    cell = make_cell()
    pessoa = make_pessoa(pessoa_id=_P1)
    inactive = make_member(pessoa_id=_P1, ativo=False)
    session = CellSession(
        app_user=make_app_user(),
        roles=["pastor"],
        cells=[cell],
        pessoas=[pessoa],
        members=[inactive],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros", headers=_AUTH, json={"pessoaId": _P1}
    )
    assert resp.status_code == 201, resp.text


def test_add_member_pessoa_not_found(app) -> None:
    cell = make_cell()
    session = CellSession(
        app_user=make_app_user(), roles=["pastor"], cells=[cell], pessoas=[]
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros", headers=_AUTH, json={"pessoaId": _P2}
    )
    assert resp.status_code == 404


def test_add_member_forbidden_for_non_editor(app) -> None:
    # Papel não-Central e não é líder da célula → sem permissão de editar.
    cell = make_cell(lider_id=_LP)
    session = CellSession(
        app_user=make_app_user(),
        roles=["membro"],
        cells=[cell],
        pessoas=[make_pessoa(pessoa_id=_LP)],
        actor_pessoa_id="00000000-0000-0000-0000-0000000000c9",  # não é o líder
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros", headers=_AUTH, json={"pessoaId": _P1}
    )
    assert resp.status_code == 403


def test_add_member_rejects_invalid_papel(app) -> None:
    cell = make_cell()
    session = CellSession(
        app_user=make_app_user(),
        roles=["pastor"],
        cells=[cell],
        pessoas=[make_pessoa(pessoa_id=_P1)],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros",
        headers=_AUTH,
        json={"pessoaId": _P1, "papel": "presidente"},
    )
    assert resp.status_code == 422


# ---- member list + tenant isolation ---------------------------------------
def test_list_members_returns_only_tenant_rows(app) -> None:
    cell = make_cell()
    mine = make_member(member_id=_MID, pessoa_id=_P1, igreja_id=_TENANT)
    foreign = make_member(
        member_id="00000000-0000-0000-0000-0000000000d2",
        pessoa_id=_P2,
        igreja_id=_OTHER,
    )
    session = CellSession(
        app_user=make_app_user(),
        roles=["pastor"],
        cells=[cell],
        members=[mine, foreign],
    )
    resp = _wire(app, session=session).get(
        f"/cells/{_CELL}/membros", headers=_AUTH
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [m["pessoaId"] for m in body] == [_P1]


def test_list_members_requires_auth(app) -> None:
    session = CellSession(app_user=make_app_user(), roles=["pastor"], cells=[make_cell()])
    assert (
        _wire(app, session=session).get(f"/cells/{_CELL}/membros").status_code == 401
    )
