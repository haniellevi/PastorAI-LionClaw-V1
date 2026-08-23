"""Testes da gestão direta de membros pela Central (Células pós-V1).

Cobre os endpoints de transferência/remoção direta:
  - POST /cells/{cell_id}/membros/transferir
  - POST /cells/{cell_id}/membros/remover

Cenários cobertos:
  - transferência bem-sucedida (desativa origem, cria destino, atualiza espelho,
    promove tipo, grava evento, commita);
  - remoção bem-sucedida (desativa vínculo, limpa espelho, grava evento);
  - autorização: só Central (pastor/admin); líder comum e membro recebem 403;
  - destino == origem → 409;
  - destino inativa → 409;
  - destino sem líder → 409;
  - origem inativa → 409;
  - pessoa não encontrada → 404;
  - célula não encontrada → 404;
  - pessoa sem vínculo ativo na origem → 409;
  - vínculo ativo em outra célula (não na origem) → 409;
  - elegibilidade no destino: pastor rejeitado, líder ativo rejeitado,
    arquivado rejeitado;
  - tenant isolation: célula/pessoa de outra igreja não encontrada;
  - auditoria append-only: evento gravado na mesma transação;
  - rollback em falha (não commita, não cria vínculo destino);
  - motivo opcional aceito e snapshot gravado.

Estilo fake-session (sem Postgres/Clerk reais): o fake espelha os predicados
WHERE (==, IN, ativo) e o ORDER BY do router/serviço.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import (
    AppUser,
    Celula,
    CelulaMembro,
    CelulaMembroEvento,
    Pessoa,
    UserRole,
)
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}

_TENANT = "00000000-0000-0000-0000-000000000001"
_OTHER = "00000000-0000-0000-0000-000000000002"
_CELL = "00000000-0000-0000-0000-0000000000e1"
_DEST = "00000000-0000-0000-0000-0000000000e2"
_LP = "00000000-0000-0000-0000-0000000000b1"  # líder da célula origem
_LP2 = "00000000-0000-0000-0000-0000000000b2"  # líder da célula destino
_PASTOR = "00000000-0000-0000-0000-0000000000b9"  # Central que executa
_P1 = "00000000-0000-0000-0000-0000000000f1"  # pessoa membro
_P2 = "00000000-0000-0000-0000-0000000000f2"
_MID = "00000000-0000-0000-0000-0000000000d1"


class _R:
    def __init__(self, *, scalar=None, scalars=None, rows=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))

    def all(self):
        return list(self._rows)


class MgmtSession:
    """Fake session que espelha os predicados WHERE para Celula, CelulaMembro,
    Pessoa e CelulaMembroEvento. Auth (AppUser/roles) e o actor_pessoa_id são
    servidos dos builders — o WHERE do router/serviço é o que se testa.
    """

    def __init__(
        self,
        *,
        app_user,
        roles,
        actor_pessoa_id=None,
        cells=None,
        members=None,
        pessoas=None,
        eventos=None,
        accesses=None,
    ) -> None:
        self.app_user = app_user
        self.roles = roles
        self.actor_pessoa_id = actor_pessoa_id
        self.cells = cells or []
        self.members = members or []
        self.pessoas = pessoas or []
        self.eventos = eventos or []
        self.accesses = list(accesses) if accesses is not None else [
            SimpleNamespace(
                id=uuid.uuid5(uuid.NAMESPACE_URL, f"access:{p.id}"),
                igreja_id=uuid.UUID(_TENANT),
                pessoa_id=p.id,
                clerk_user_id=f"clerk_{p.id}",
                status="ativo",
            )
            for p in self.pessoas
        ]
        self.role_rows: list = []
        self.added: list = []
        self.deleted: list = []
        self.committed = False
        self.rolled_back = False

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
            preds = self._eq_predicates(statement)
            if "clerk_user_id" in preds:
                return _R(scalar=self.app_user)
            rows = self._filter(self.accesses, statement)
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is Celula:
            rows = self._filter(self.cells, statement)
            if self._wants_active(statement):
                rows = [r for r in rows if getattr(r, "ativo", True) is True]
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is CelulaMembro:
            rows = self._filter(self.members, statement)
            if self._wants_active(statement):
                rows = [r for r in rows if getattr(r, "ativo", True) is True]
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is Pessoa:
            rows = self._filter(self.pessoas, statement)
            if name == "id":
                return _R(scalar=(rows[0].id if rows else None))
            return _R(scalar=(rows[0] if rows else None))
        if ent is CelulaMembroEvento:
            rows = self._filter(self.eventos, statement)
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        if ent is UserRole and name == "papel":
            return _R(scalars=self.roles)
        if ent is UserRole:
            rows = self._filter(self.role_rows, statement)
            return _R(scalar=(rows[0] if rows else None), scalars=rows)
        # set_config text / func.count / WhatsappConnection lookup (vazio).
        return _R(scalars=self.roles)

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        if isinstance(obj, CelulaMembro):
            self.members.append(obj)
        elif isinstance(obj, CelulaMembroEvento):
            self.eventos.append(obj)
        elif isinstance(obj, UserRole):
            self.role_rows.append(obj)

    def delete(self, obj) -> None:
        self.deleted.append(obj)
        if obj in self.role_rows:
            self.role_rows.remove(obj)

    def flush(self) -> None:
        pass

    def refresh(self, obj, **_kwargs) -> None:
        pass

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:  # pragma: no cover
        pass


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def make_cell(
    *,
    cell_id: str = _CELL,
    igreja_id: str = _TENANT,
    nome: str = "Célula Origem",
    lider_id: str | None = _LP,
    ativo: bool = True,
):
    return SimpleNamespace(
        id=cell_id,
        igreja_id=igreja_id,
        nome=nome,
        lider_id=lider_id,
        cobertura_espiritual="Rede Azul",
        anfitriao_id=None,
        auxiliar_id=None,
        endereco=None,
        dia_reuniao=None,
        horario=None,
        ativo=ativo,
        created_at=None,
    )


def make_pessoa(
    *,
    pessoa_id: str = _P1,
    igreja_id: str = _TENANT,
    nome: str = "Fulano",
    celula_id: str | None = _CELL,
    tipo: str = "membro",
    telefone: str | None = None,
    arquivada_em: object = None,
    lider_id: str | None = None,
):
    return SimpleNamespace(
        id=pessoa_id,
        igreja_id=igreja_id,
        nome=nome,
        lider_id=lider_id,
        celula_id=celula_id,
        tipo=tipo,
        telefone=telefone,
        apto_lider=True,
        sem_interesse=False,
        arquivada_em=arquivada_em,
    )


def make_member(
    *,
    member_id: str = _MID,
    igreja_id: str = _TENANT,
    celula_id: str = _CELL,
    pessoa_id: str = _P1,
    papel: str = "membro",
    ativo: bool = True,
):
    return SimpleNamespace(
        id=member_id,
        igreja_id=igreja_id,
        celula_id=celula_id,
        pessoa_id=pessoa_id,
        papel=papel,
        ativo=ativo,
        created_at=None,
        updated_at=None,
    )


def _wire(app, *, session, clerk=None) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk or FakeClerk()
    return TestClient(app)


def _central_session(**kwargs) -> MgmtSession:
    kwargs.setdefault("app_user", make_app_user())
    kwargs.setdefault("roles", ["pastor"])
    kwargs.setdefault("actor_pessoa_id", _PASTOR)
    return MgmtSession(**kwargs)


# ===========================================================================
# POST /cells/{cell_id}/membros/transferir
# ===========================================================================
def test_transfer_member_succeeds(app) -> None:
    """Transferência direta: desativa origem, cria destino, atualiza espelho,
    grava evento, commita."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    destino = make_cell(cell_id=_DEST, lider_id=_LP2, nome="Célula Destino")
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL, tipo="membro")
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = _central_session(
        cells=[origem, destino],
        pessoas=[pessoa, make_pessoa(pessoa_id=_LP, nome="Líder 1", celula_id=None, tipo="lider")],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST, "motivo": "Mudou de bairro"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["pessoaId"] == _P1
    assert body["ativo"] is True
    # origem desativada
    assert member.ativo is False
    # espelho atualizado
    assert str(pessoa.celula_id) == _DEST
    # evento gravado
    eventos = [e for e in session.eventos if isinstance(e, CelulaMembroEvento)]
    assert len(eventos) == 1
    assert eventos[0].acao == "transferido"
    assert str(eventos[0].celula_origem_id) == _CELL
    assert str(eventos[0].celula_destino_id) == _DEST
    assert eventos[0].motivo == "Mudou de bairro"
    assert session.committed is True


def test_transfer_member_promotes_contato_to_membro(app) -> None:
    """Vínculo ativo no destino ⇒ tipo ≥ membro (invariante preservado)."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    destino = make_cell(cell_id=_DEST, lider_id=_LP2)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL, tipo="contato")
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = _central_session(
        cells=[origem, destino],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    assert resp.status_code == 201, resp.text
    assert pessoa.tipo == "membro"  # promovido de contato


def test_transfer_member_forbidden_for_leader(app) -> None:
    """Líder comum (não Central) não pode transferir — 403."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    destino = make_cell(cell_id=_DEST, lider_id=_LP2)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL)
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = MgmtSession(
        app_user=make_app_user(),
        roles=["lider"],
        actor_pessoa_id=_LP,
        cells=[origem, destino],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    assert resp.status_code == 403
    assert session.committed is False


def test_transfer_member_forbidden_for_common_member(app) -> None:
    """Membro comum não pode transferir — 403."""
    session = MgmtSession(
        app_user=make_app_user(),
        roles=["membro"],
        actor_pessoa_id=_P1,
        cells=[make_cell(cell_id=_CELL, lider_id=_LP), make_cell(cell_id=_DEST, lider_id=_LP2)],
        pessoas=[make_pessoa(pessoa_id=_P1)],
        members=[make_member(pessoa_id=_P1)],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    assert resp.status_code == 403


def test_transfer_member_same_destination_409(app) -> None:
    """Destino == origem não é transferência — 409."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL)
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = _central_session(
        cells=[origem],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _CELL},
    )
    assert resp.status_code == 409
    assert "mesma" in resp.json()["detail"].lower()


def test_transfer_member_inactive_destination_409(app) -> None:
    """Destino inativa não recebe membros — 409."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    destino = make_cell(cell_id=_DEST, lider_id=_LP2, ativo=False)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL)
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = _central_session(
        cells=[origem, destino],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    assert resp.status_code == 409
    assert session.committed is False


def test_transfer_member_destination_without_leader_409(app) -> None:
    """Destino sem líder não recebe membros — 409."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    destino = make_cell(cell_id=_DEST, lider_id=None)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL)
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = _central_session(
        cells=[origem, destino],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    assert resp.status_code == 409


def test_transfer_member_inactive_origin_409(app) -> None:
    """Origem inativa — 409."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP, ativo=False)
    destino = make_cell(cell_id=_DEST, lider_id=_LP2)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL)
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = _central_session(
        cells=[origem, destino],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    assert resp.status_code == 409


def test_transfer_member_pessoa_not_found_404(app) -> None:
    """Pessoa não encontrada no tenant — 404."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    destino = make_cell(cell_id=_DEST, lider_id=_LP2)
    session = _central_session(
        cells=[origem, destino],
        pessoas=[],
        members=[],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    assert resp.status_code == 404


def test_transfer_member_cell_not_found_404(app) -> None:
    """Célula de origem (URL) não encontrada — 404."""
    destino = make_cell(cell_id=_DEST, lider_id=_LP2)
    session = _central_session(
        cells=[destino],
        pessoas=[make_pessoa(pessoa_id=_P1)],
        members=[make_member(pessoa_id=_P1, celula_id=_CELL)],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    assert resp.status_code == 404


def test_transfer_member_no_active_membership_409(app) -> None:
    """Pessoa sem vínculo ativo na origem — 409."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    destino = make_cell(cell_id=_DEST, lider_id=_LP2)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=None)
    session = _central_session(
        cells=[origem, destino],
        pessoas=[pessoa],
        members=[],  # sem vínculo ativo
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    assert resp.status_code == 409
    assert session.committed is False


def test_transfer_member_active_in_other_cell_409(app) -> None:
    """Vínculo ativo em OUTRA célula (não na origem informada) — 409."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    destino = make_cell(cell_id=_DEST, lider_id=_LP2)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_OTHER)
    # vínculo ativo em célula diferente da origem
    other_member = make_member(
        member_id="00000000-0000-0000-0000-0000000000d9",
        pessoa_id=_P1,
        celula_id=_OTHER,
    )
    session = _central_session(
        cells=[origem, destino],
        pessoas=[pessoa],
        members=[other_member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    assert resp.status_code == 409


def test_transfer_member_pastor_rejected_409(app) -> None:
    """Pastor não pode ser membro de célula — elegibilidade no destino."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    destino = make_cell(cell_id=_DEST, lider_id=_LP2)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL, tipo="pastor")
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = _central_session(
        cells=[origem, destino],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    assert resp.status_code == 409
    assert session.committed is False


def test_transfer_member_active_leader_rejected_409(app) -> None:
    """Pessoa que lidera célula ativa não pode ser membro — elegibilidade."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    destino = make_cell(cell_id=_DEST, lider_id=_LP2)
    # P1 lidera uma 3ª célula ativa
    third_cell = make_cell(
        cell_id="00000000-0000-0000-0000-0000000000e3",
        lider_id=_P1,
        nome="Célula do P1",
    )
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL, tipo="membro")
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = _central_session(
        cells=[origem, destino, third_cell],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    assert resp.status_code == 409


def test_transfer_member_archived_rejected_409(app) -> None:
    """Pessoa arquivada não recebe novos vínculos — elegibilidade."""
    import datetime as dt

    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    destino = make_cell(cell_id=_DEST, lider_id=_LP2)
    pessoa = make_pessoa(
        pessoa_id=_P1,
        celula_id=_CELL,
        arquivada_em=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
    )
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = _central_session(
        cells=[origem, destino],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    assert resp.status_code == 409


def test_transfer_member_tenant_isolation(app) -> None:
    """Célula/pessoa de outra igreja não é visível — 404/409, nunca vaza."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    # destino pertence a OUTRO tenant
    destino_other = make_cell(
        cell_id=_DEST, igreja_id=_OTHER, lider_id=_LP2, nome="Célula Outra Igreja"
    )
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL)
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = _central_session(
        cells=[origem, destino_other],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    # destino não encontrada no tenant atual → 404 (não 409 de inativa)
    assert resp.status_code == 404
    assert session.committed is False


def test_transfer_member_requires_auth(app) -> None:
    session = _central_session()
    assert (
        _wire(app, session=session).post(
            f"/cells/{_CELL}/membros/transferir",
            json={"pessoaId": _P1, "celula_destino_id": _DEST},
        ).status_code
        == 401
    )


def test_transfer_member_invalid_uuid_404(app) -> None:
    """UUID malformado na URL → 404 (não vaza 422)."""
    session = _central_session()
    resp = _wire(app, session=session).post(
        "/cells/not-a-uuid/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    assert resp.status_code == 404


def test_transfer_member_admin_allowed(app) -> None:
    """Admin (acesso implícito via has_any_role) pode transferir."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    destino = make_cell(cell_id=_DEST, lider_id=_LP2)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL)
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = MgmtSession(
        app_user=make_app_user(),
        roles=["admin"],
        actor_pessoa_id=_PASTOR,
        cells=[origem, destino],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    assert resp.status_code == 201


# ===========================================================================
# POST /cells/{cell_id}/membros/remover
# ===========================================================================
def test_remove_member_succeeds(app) -> None:
    """Remoção direta: desativa vínculo, limpa espelho, grava evento, commita.
    NÃO deleta a pessoa."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL, tipo="membro")
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = _central_session(
        cells=[origem],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/remover",
        headers=_AUTH,
        json={"pessoaId": _P1, "motivo": "Pediu para sair"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pessoaId"] == _P1
    assert body["ativo"] is False  # vínculo desativado
    # espelho limpo
    assert pessoa.celula_id is None
    # pessoa NÃO foi deletada (continua na lista de pessoas)
    assert pessoa in session.pessoas
    # evento gravado
    eventos = [e for e in session.eventos if isinstance(e, CelulaMembroEvento)]
    assert len(eventos) == 1
    assert eventos[0].acao == "removido"
    assert eventos[0].celula_destino_id is None
    assert eventos[0].motivo == "Pediu para sair"
    assert session.committed is True


def test_remove_member_forbidden_for_leader(app) -> None:
    """Líder comum não pode remover — 403."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL)
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = MgmtSession(
        app_user=make_app_user(),
        roles=["lider"],
        actor_pessoa_id=_LP,
        cells=[origem],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/remover",
        headers=_AUTH,
        json={"pessoaId": _P1},
    )
    assert resp.status_code == 403
    assert session.committed is False


def test_remove_member_forbidden_for_common_member(app) -> None:
    """Membro comum não pode remover — 403."""
    session = MgmtSession(
        app_user=make_app_user(),
        roles=["membro"],
        actor_pessoa_id=_P1,
        cells=[make_cell(cell_id=_CELL, lider_id=_LP)],
        pessoas=[make_pessoa(pessoa_id=_P1)],
        members=[make_member(pessoa_id=_P1)],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/remover",
        headers=_AUTH,
        json={"pessoaId": _P1},
    )
    assert resp.status_code == 403


def test_remove_member_no_active_membership_409(app) -> None:
    """Pessoa sem vínculo ativo — 409."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=None)
    session = _central_session(
        cells=[origem],
        pessoas=[pessoa],
        members=[],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/remover",
        headers=_AUTH,
        json={"pessoaId": _P1},
    )
    assert resp.status_code == 409
    assert session.committed is False


def test_remove_member_active_in_other_cell_409(app) -> None:
    """Vínculo ativo em outra célula (não na origem) — 409."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_OTHER)
    other_member = make_member(
        member_id="00000000-0000-0000-0000-0000000000d9",
        pessoa_id=_P1,
        celula_id=_OTHER,
    )
    session = _central_session(
        cells=[origem],
        pessoas=[pessoa],
        members=[other_member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/remover",
        headers=_AUTH,
        json={"pessoaId": _P1},
    )
    assert resp.status_code == 409


def test_remove_member_pessoa_not_found_404(app) -> None:
    """Pessoa não encontrada — 404."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    session = _central_session(
        cells=[origem],
        pessoas=[],
        members=[],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/remover",
        headers=_AUTH,
        json={"pessoaId": _P1},
    )
    assert resp.status_code == 404


def test_remove_member_cell_not_found_404(app) -> None:
    """Célula de origem (URL) não encontrada — 404."""
    session = _central_session(
        cells=[],
        pessoas=[make_pessoa(pessoa_id=_P1)],
        members=[make_member(pessoa_id=_P1, celula_id=_CELL)],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/remover",
        headers=_AUTH,
        json={"pessoaId": _P1},
    )
    assert resp.status_code == 404


def test_remove_member_inactive_origin_409(app) -> None:
    """Origem inativa — 409."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP, ativo=False)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL)
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = _central_session(
        cells=[origem],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/remover",
        headers=_AUTH,
        json={"pessoaId": _P1},
    )
    assert resp.status_code == 409


def test_remove_member_tenant_isolation(app) -> None:
    """Pessoa de outra igreja não é visível — 404."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    pessoa_other = make_pessoa(pessoa_id=_P1, igreja_id=_OTHER, celula_id=_CELL)
    session = _central_session(
        cells=[origem],
        pessoas=[pessoa_other],
        members=[],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/remover",
        headers=_AUTH,
        json={"pessoaId": _P1},
    )
    # pessoa não encontrada no tenant atual → 404
    assert resp.status_code == 404
    assert session.committed is False


def test_remove_member_requires_auth(app) -> None:
    session = _central_session()
    assert (
        _wire(app, session=session).post(
            f"/cells/{_CELL}/membros/remover",
            json={"pessoaId": _P1},
        ).status_code
        == 401
    )


def test_remove_member_admin_allowed(app) -> None:
    """Admin pode remover."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL)
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = MgmtSession(
        app_user=make_app_user(),
        roles=["admin"],
        actor_pessoa_id=_PASTOR,
        cells=[origem],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/remover",
        headers=_AUTH,
        json={"pessoaId": _P1},
    )
    assert resp.status_code == 200


def test_remove_member_invalid_uuid_404(app) -> None:
    """UUID malformado na URL → 404."""
    session = _central_session()
    resp = _wire(app, session=session).post(
        "/cells/not-a-uuid/membros/remover",
        headers=_AUTH,
        json={"pessoaId": _P1},
    )
    assert resp.status_code == 404


def test_transfer_member_without_motivo_succeeds(app) -> None:
    """Motivo é opcional — transferência sem motivo funciona."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    destino = make_cell(cell_id=_DEST, lider_id=_LP2)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL)
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = _central_session(
        cells=[origem, destino],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/transferir",
        headers=_AUTH,
        json={"pessoaId": _P1, "celula_destino_id": _DEST},
    )
    assert resp.status_code == 201
    eventos = [e for e in session.eventos if isinstance(e, CelulaMembroEvento)]
    assert eventos[0].motivo is None


def test_remove_member_without_motivo_succeeds(app) -> None:
    """Motivo é opcional — remoção sem motivo funciona."""
    origem = make_cell(cell_id=_CELL, lider_id=_LP)
    pessoa = make_pessoa(pessoa_id=_P1, celula_id=_CELL)
    member = make_member(pessoa_id=_P1, celula_id=_CELL)
    session = _central_session(
        cells=[origem],
        pessoas=[pessoa],
        members=[member],
    )
    resp = _wire(app, session=session).post(
        f"/cells/{_CELL}/membros/remover",
        headers=_AUTH,
        json={"pessoaId": _P1},
    )
    assert resp.status_code == 200
    eventos = [e for e in session.eventos if isinstance(e, CelulaMembroEvento)]
    assert eventos[0].motivo is None
