"""Synthetic batch/pool regressions without external services."""

from types import SimpleNamespace
from uuid import UUID

import httpx

from app.config import Settings
from app.routers.events import IndividualTargetInput, _resolve_contatos
from app.services.google_oauth import GoogleOAuthClient


def test_notification_target_resolution_is_one_tenant_query():
    person = UUID(int=21)
    conversation = SimpleNamespace(pessoa_id=person, telefone="559900000001")
    class Session:
        def __init__(self):
            self.statements = []
        def execute(self, statement):
            self.statements.append(statement)
            return SimpleNamespace(scalar_one_or_none=lambda: conversation,
                scalars=lambda: SimpleNamespace(all=lambda: [conversation]))
    db = Session()
    targets = [IndividualTargetInput(pessoaId=str(person)) for _ in range(50)]
    result = _resolve_contatos(db, UUID(int=1), targets)
    assert result == [(person, None)]
    assert len(db.statements) == 1
    assert "conversations.igreja_id" in str(db.statements[0].whereclause)


def test_google_pool_reuses_transport_but_binds_each_credential_to_request():
    authorizations = []
    cookies = []
    def handler(request):
        authorizations.append(request.headers["Authorization"])
        cookies.append(request.headers.get("Cookie"))
        return httpx.Response(200, json={"items": []}, headers={"Set-Cookie":"provider_session=synthetic-A; Path=/; Secure"})
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    oauth = GoogleOAuthClient(settings=Settings(session_jwt_secret="x"*32), http_client=client)
    oauth.list_calendars("synthetic-A")
    oauth.list_calendars("synthetic-B")
    assert authorizations == ["Bearer synthetic-A", "Bearer synthetic-B"]
    assert "Authorization" not in client.headers
    assert cookies == [None,None]
    assert not list(client.cookies.jar)
    oauth.close()
    assert not client.is_closed  # injected client's owner controls its lifetime
    client.close()
