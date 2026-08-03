"""BROADCAST-SAFETY-1 — pessoa arquivada fica FORA da audiência de comunicados.

Exercita o corpo real de ``POST /broadcasts`` (não o domínio puro, já coberto
por test_broadcast_domain) com harness offline: FakeSession roteando por
entidade + Evolution fake. Zero rede, zero DB.

O ponto delicado é provar a REGRESSÃO. Um fake que devolvesse a lista de pessoas
crua ignoraria o WHERE e passaria com ou sem a correção. Então, como o
``_plano_query_filters`` do conftest, este fake COMPILA o ``Select`` real e só
esconde as arquivadas se a consulta tiver pedido ``arquivada_em IS NULL``. Se
alguém remover o filtro de app/routers/broadcasts.py, o fake volta a entregar
todo mundo e os testes de arquivamento quebram.

Contrato coberto:
  - ativa consentida e compatível entra no alcance e recebe mensagem;
  - arquivada consentida e compatível não entra nem recebe;
  - arquivada que lidera célula ativa também não entra pelo segmento "lider";
  - opt-out de pessoa ATIVA continua contado em ignoradosOptout;
  - audiência só de arquivados => alcance 0, bloqueado, ignoradosOptout 0.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Broadcast, Celula, Pessoa, WhatsappConnection
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from app.services.evolution import get_evolution_client
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_BID = "00000000-0000-0000-0000-0000000000b1"
_INSTANCE = "igreja-piloto"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------
class _R:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


def _hides_archived(statement) -> bool:
    """True se o SELECT de pessoas pediu explicitamente só as ativas.

    Lê o SQL compilado em vez de confiar no shape da query — é isso que faz o
    teste falhar quando a correção some do router.
    """
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    return "pessoas.arquivada_em IS NULL" in sql


class BroadcastSession:
    """Roteia auth (AppUser/UserRole) + pessoas, células e conexão WhatsApp."""

    def __init__(self, *, app_user, roles, pessoas, leader_ids=None) -> None:
        self.app_user = app_user
        self.roles = roles
        self.pessoas = pessoas
        self.leader_ids = leader_ids or []
        self.added: list = []
        self.committed = False
        self.pessoa_stmt = None

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is Pessoa:
            self.pessoa_stmt = statement
            rows = self.pessoas
            if _hides_archived(statement):
                rows = [p for p in rows if p.arquivada_em is None]
            return _R(scalars=rows)
        if ent is Celula:
            return _R(scalars=self.leader_ids)
        if ent is WhatsappConnection:
            return _R(scalar=SimpleNamespace(instance=_INSTANCE))
        if ent is Broadcast:
            return _R(scalars=[])
        return _R(scalars=self.roles)

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        pass

    def refresh(self, obj) -> None:
        # O DB atribuiria o id no flush (server_default gen_random_uuid).
        if getattr(obj, "id", None) is None:
            obj.id = uuid.UUID(_BID)

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


class FakeEvolution:
    """Registra os envios; nunca fala com a Evolution API."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send_text(self, instance: str, phone: str, message: str) -> None:
        self.sent.append((instance, phone, message))


def _pessoa(
    *,
    pid=None,
    telefone="11999990000",
    tipo="membro",
    optout=False,
    consentimento=True,
    arquivada_em=None,
):
    return SimpleNamespace(
        id=pid or uuid.uuid4(),
        telefone=telefone,
        tipo=tipo,
        optout=optout,
        consentimento=consentimento,
        arquivada_em=arquivada_em,
    )


_ARQUIVADA_EM = dt.datetime(2026, 7, 20, 12, 0, tzinfo=dt.timezone.utc)


def _wire(app, *, pessoas, leader_ids=None, roles=("admin",)):
    session = BroadcastSession(
        app_user=make_app_user(),
        roles=list(roles),
        pessoas=pessoas,
        leader_ids=leader_ids,
    )
    evolution = FakeEvolution()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    app.dependency_overrides[get_evolution_client] = lambda: evolution
    return TestClient(app), session, evolution


def _post(client, *, segmentos=("todos",)):
    return client.post(
        "/broadcasts",
        headers=_AUTH,
        json={
            "titulo": "Culto de domingo",
            "mensagem": "Nos vemos às 19h.",
            "segmentos": list(segmentos),
            "modo": "agora",
        },
    )


# ---------------------------------------------------------------------------
# 1. Pessoa ativa continua entrando (a correção não pode encolher o alcance real)
# ---------------------------------------------------------------------------
def test_pessoa_ativa_consentida_entra_na_audiencia(app) -> None:
    ativa = _pessoa(telefone="11911111111")
    client, session, evolution = _wire(app, pessoas=[ativa])

    resp = _post(client)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "enviado"
    assert body["enviados"] == 1
    assert body["ignoradosOptout"] == 0
    assert evolution.sent == [(_INSTANCE, "11911111111", "Nos vemos às 19h.")]
    assert session.added[0].alcance == 1
    assert session.committed is True


# ---------------------------------------------------------------------------
# 2. Pessoa arquivada sai da audiência mesmo com telefone + consentimento
# ---------------------------------------------------------------------------
def test_pessoa_arquivada_consentida_fica_fora(app) -> None:
    ativa = _pessoa(telefone="11911111111")
    arquivada = _pessoa(telefone="11922222222", arquivada_em=_ARQUIVADA_EM)
    client, session, evolution = _wire(app, pessoas=[ativa, arquivada])

    resp = _post(client)

    assert resp.status_code == 200
    body = resp.json()
    assert body["enviados"] == 1
    # Arquivada não é opt-out: ela não pertence mais à audiência.
    assert body["ignoradosOptout"] == 0
    assert session.added[0].alcance == 1
    assert [phone for _, phone, _ in evolution.sent] == ["11911111111"]


# ---------------------------------------------------------------------------
# 3. Arquivada que lidera célula ativa também sai (segmento "lider" derivado)
# ---------------------------------------------------------------------------
def test_pessoa_arquivada_que_lideraria_celula_fica_fora(app) -> None:
    lider_ativo = _pessoa(telefone="11933333333", tipo="membro")
    lider_arquivado = _pessoa(
        telefone="11944444444", tipo="membro", arquivada_em=_ARQUIVADA_EM
    )
    client, session, evolution = _wire(
        app,
        pessoas=[lider_ativo, lider_arquivado],
        # Ambos constam como lider_id de célula ATIVA — a derivação de líder
        # segue intacta; quem some é a pessoa arquivada.
        leader_ids=[lider_ativo.id, lider_arquivado.id],
    )

    resp = _post(client, segmentos=("lider",))

    assert resp.status_code == 200
    body = resp.json()
    assert body["enviados"] == 1
    assert body["ignoradosOptout"] == 0
    assert [phone for _, phone, _ in evolution.sent] == ["11933333333"]
    assert session.added[0].alcance == 1


# ---------------------------------------------------------------------------
# 4. Opt-out de pessoa ATIVA continua contado (RF-38 intacto)
# ---------------------------------------------------------------------------
def test_optout_de_pessoa_ativa_continua_contado(app) -> None:
    ativa = _pessoa(telefone="11911111111")
    ativa_optout = _pessoa(telefone="11955555555", optout=True)
    ativa_sem_consent = _pessoa(telefone="11966666666", consentimento=False)
    arquivada_optout = _pessoa(
        telefone="11977777777", optout=True, arquivada_em=_ARQUIVADA_EM
    )
    client, session, evolution = _wire(
        app, pessoas=[ativa, ativa_optout, ativa_sem_consent, arquivada_optout]
    )

    resp = _post(client)

    assert resp.status_code == 200
    body = resp.json()
    assert body["enviados"] == 1
    # 2 = os dois ATIVOS barrados. A arquivada com optout não infla o contador.
    assert body["ignoradosOptout"] == 2
    assert session.added[0].ignorados_optout == 2
    assert [phone for _, phone, _ in evolution.sent] == ["11911111111"]


# ---------------------------------------------------------------------------
# 5. Audiência só de arquivados => alcance zero (bloqueado), sem opt-out
# ---------------------------------------------------------------------------
def test_audiencia_so_de_arquivados_bloqueia_com_alcance_zero(app) -> None:
    pessoas = [
        _pessoa(telefone="11911111111", arquivada_em=_ARQUIVADA_EM),
        _pessoa(telefone="11922222222", arquivada_em=_ARQUIVADA_EM),
    ]
    client, session, evolution = _wire(app, pessoas=pessoas)

    resp = _post(client)

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "bloqueado"
    assert body["enviados"] == 0
    assert body["ignoradosOptout"] == 0
    assert session.added[0].alcance == 0
    assert session.added[0].status == "rascunho"


# ---------------------------------------------------------------------------
# 6. Nenhuma mensagem chega ao telefone de uma pessoa arquivada
# ---------------------------------------------------------------------------
def test_nenhuma_mensagem_enviada_para_pessoa_arquivada(app) -> None:
    arquivada = _pessoa(telefone="11922222222", arquivada_em=_ARQUIVADA_EM)
    pessoas = [_pessoa(telefone="11911111111"), arquivada]
    client, _session, evolution = _wire(app, pessoas=pessoas)

    _post(client)

    assert "11922222222" not in [phone for _, phone, _ in evolution.sent]


# ---------------------------------------------------------------------------
# Guarda do harness: a consulta de pessoas precisa PEDIR só as ativas.
# ---------------------------------------------------------------------------
def test_consulta_de_pessoas_filtra_arquivadas_no_sql(app) -> None:
    client, session, _evolution = _wire(app, pessoas=[_pessoa()])

    _post(client)

    assert session.pessoa_stmt is not None
    assert _hides_archived(session.pessoa_stmt) is True
