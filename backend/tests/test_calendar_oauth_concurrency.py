"""OAUTH-CALENDAR-V1: corridas reais de callback e finish no PostgreSQL.

FakeSession não prova espera de row lock nem reavaliação do WHERE depois do
commit concorrente. Esta suíte usa duas conexões contra um Postgres descartável
e o mesmo guard anti DEV/PROD da integração RLS.
"""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from collections.abc import Iterator

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import app.db.session  # noqa: F401 - registra o listener de sessão de produção
from app.config import get_settings
from app.db.models import AppUser, Base, CalendarOAuthFlow, CalendarSync, Igreja
from app.deps import CurrentUser
from app.routers.calendar import (
    FinishRequest,
    SelectCalendarRequest,
    callback,
    finish_connection,
    select_calendar,
)
from app.services.calendar_oauth_flows import (
    _COMPLETED_REPLAY_GRACE,
    _IN_FLIGHT_FINISH_GRACE,
    hash_secret,
    purge_expired_flows,
)
from app.services.google_oauth import GoogleIdentity, OAuthTokens
from tests.conftest_rls import rls_database_url  # noqa: F401 - fixture do pytest

pytestmark = pytest.mark.rls_integration

_SCHEMA = "oauth_calendar_race"
_IGREJA = uuid.UUID("0e0e1e0e-0000-0000-0000-00000000aa01")
_APP_USER = uuid.UUID("0a111a11-0000-0000-0000-00000000bb01")
_STATE = "estado-opaco-concorrente"
_FLOW_SECRET = "segredo-concorrente-do-finish"
_EMAIL = "agenda@igreja12.com.br"
_SUB = "google-sub-da-conta"
_OTHER_EMAIL = "outra-agenda@igreja12.com.br"
_OTHER_SUB = "google-sub-da-outra-conta"
_ORIGIN = "https://admin.igreja12.com.br"

_CALLBACK_AUDIT_SQL = """
create table callback_write_audit (
  id bigserial primary key,
  flow_id uuid not null,
  written_at timestamptz not null default now()
);

create or replace function audit_first_callback_write()
returns trigger
language plpgsql
as $$
begin
  if old.code_encrypted is null and new.code_encrypted is not null then
    insert into callback_write_audit (flow_id) values (new.id);
  end if;
  return new;
end;
$$;

create trigger trg_audit_first_callback_write
after update of code_encrypted on calendar_oauth_flows
for each row execute function audit_first_callback_write();
"""


@pytest.fixture(autouse=True)
def crypto_enabled(monkeypatch):
    """Uma chave só é instalada antes de abrir as threads."""
    from app.services import crypto

    monkeypatch.setattr(get_settings(), "secrets_encryption_key", "k" * 32)
    crypto._get_fernet.cache_clear()  # noqa: SLF001
    yield crypto
    crypto._get_fernet.cache_clear()  # noqa: SLF001


@pytest.fixture
def engine_fx(rls_database_url: str) -> Iterator[Engine]:
    """Schema próprio, criado do zero e destruído ao fim do teste."""
    engine = create_engine(
        rls_database_url,
        future=True,
        connect_args={"options": f"-c search_path={_SCHEMA}"},
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"drop schema if exists {_SCHEMA} cascade; create schema {_SCHEMA};"
        )
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(_CALLBACK_AUDIT_SQL)
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"drop schema if exists {_SCHEMA} cascade;")
        engine.dispose()


def _factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )


def _seed(
    factory: sessionmaker[Session],
    crypto,
    *,
    code: str | None,
    expected_email: str = _EMAIL,
    expires_at: dt.datetime | None = None,
    consumed_at: dt.datetime | None = None,
    finish_result: str | None = None,
    finished_at: dt.datetime | None = None,
    sync_connected_em: dt.datetime | None = None,
) -> None:
    session = factory()
    try:
        now = dt.datetime.now(dt.timezone.utc)
        session.add(Igreja(id=_IGREJA, nome="Igreja OAuth"))
        session.flush()
        session.add(
            AppUser(
                id=_APP_USER,
                igreja_id=_IGREJA,
                clerk_user_id="clerk-oauth-race",
                nome="Admin",
                email="admin@igreja12.com.br",
                status="ativo",
            )
        )
        session.flush()
        session.add(
            CalendarOAuthFlow(
                id=uuid.uuid4(),
                state_hash=hash_secret(_STATE),
                flow_secret_hash=hash_secret(_FLOW_SECRET),
                igreja_id=_IGREJA,
                app_user_id=_APP_USER,
                return_origin=_ORIGIN,
                expected_email=expected_email,
                verifier_encrypted=crypto.encrypt_secret("verifier"),
                code_encrypted=crypto.encrypt_secret(code) if code else None,
                expires_at=expires_at
                or (now + dt.timedelta(minutes=10)),
                consumed_at=consumed_at,
                finish_result=finish_result,
                finished_at=finished_at,
            )
        )
        if sync_connected_em is not None:
            session.add(
                CalendarSync(
                    igreja_id=_IGREJA,
                    google_calendar_id="calendar-da-conta-a",
                    refresh_token_encrypted=crypto.encrypt_secret("refresh-a"),
                    access_token_encrypted=crypto.encrypt_secret("access-a"),
                    access_token_expira_em=now + dt.timedelta(hours=1),
                    google_account_email=_EMAIL,
                    google_account_sub=_SUB,
                    connected_by_app_user_id=_APP_USER,
                    connected_em=sync_connected_em,
                )
            )
        session.commit()
    finally:
        session.close()


def _user() -> CurrentUser:
    return CurrentUser(
        app_user_id=str(_APP_USER),
        clerk_user_id="clerk-oauth-race",
        igreja_id=str(_IGREJA),
        email="admin@igreja12.com.br",
        nome="Admin",
        roles=frozenset({"admin"}),
    )


def test_concurrent_callbacks_are_first_write_wins(
    engine_fx: Engine, crypto_enabled
) -> None:
    """Dois callbacks reais produzem exatamente UMA escrita de code."""
    factory = _factory(engine_fx)
    _seed(factory, crypto_enabled, code=None)
    barrier = threading.Barrier(2)
    outcomes: dict[int, str] = {}

    def worker(idx: int) -> None:
        session = factory()
        try:
            barrier.wait(timeout=10)
            redirect = callback(
                code=f"code-{idx}", state=_STATE, error="", db=session
            )
            outcomes[idx] = redirect.headers["location"]
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not any(thread.is_alive() for thread in threads)
    assert len(outcomes) == 2
    assert all(url.endswith("#integracoes/callback/ready") for url in outcomes.values())
    with factory() as session:
        flow = session.execute(select(CalendarOAuthFlow)).scalar_one()
        parked = crypto_enabled.decrypt_secret(flow.code_encrypted or "")
        writes = session.execute(text("select count(*) from callback_write_audit")).scalar_one()
    assert parked in {"code-0", "code-1"}
    assert writes == 1


class _BlockingOAuth:
    """Segura a primeira troca depois da queima para abrir a janela de replay."""

    def __init__(
        self,
        *,
        identity: GoogleIdentity | None = None,
        block_probe: bool = False,
    ) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.probe_entered = threading.Event()
        self.probe_release = threading.Event()
        self._block_probe = block_probe
        self._identity = identity or GoogleIdentity(
            sub=_SUB, email=_EMAIL, email_verified=True
        )
        self._lock = threading.Lock()
        self.exchanges = 0

    def exchange_code(self, code: str, verifier: str) -> OAuthTokens:
        assert code == "code-pronto"
        assert verifier == "verifier"
        with self._lock:
            self.exchanges += 1
        self.entered.set()
        assert self.release.wait(timeout=20), "teste não liberou a troca OAuth"
        return OAuthTokens(
            access_token="access",
            refresh_token="refresh",
            expires_in=3600,
            scope=None,
        )

    def fetch_userinfo(self, access_token: str) -> GoogleIdentity:
        assert access_token == "access"
        return self._identity

    def list_calendars(self, access_token: str) -> list[dict]:
        assert access_token == "access"
        if self._block_probe:
            self.probe_entered.set()
            assert self.probe_release.wait(timeout=20), "teste não liberou o probe"
        return [{"id": "primary", "summary": "Principal", "primary": True}]


def test_concurrent_finish_exchanges_once_and_replay_is_processing(
    engine_fx: Engine, crypto_enabled
) -> None:
    """A segunda request não troca code nem infere sucesso da conexão antiga."""
    factory = _factory(engine_fx)
    _seed(factory, crypto_enabled, code="code-pronto")
    oauth = _BlockingOAuth()
    outcomes: dict[str, tuple[int, str]] = {}

    def worker(label: str) -> None:
        session = factory()
        response = Response()
        try:
            result = finish_connection(
                FinishRequest(flowSecret=_FLOW_SECRET),
                response=response,
                db=session,
                current_user=_user(),
                oauth=oauth,
            )
            outcomes[label] = (response.status_code, result.status)
        finally:
            session.close()

    first = threading.Thread(target=worker, args=("first",))
    first.start()
    assert oauth.entered.wait(timeout=20), "primeiro finish não chegou à troca"

    # Nesse instante a queima já foi commitada e o lock do fluxo foi solto.
    second = threading.Thread(target=worker, args=("second",))
    second.start()
    second.join(timeout=20)
    try:
        assert not second.is_alive(), "replay ficou bloqueado durante chamada externa"
        assert outcomes["second"] == (202, "processando")
    finally:
        oauth.release.set()
        first.join(timeout=20)

    assert not first.is_alive()
    assert outcomes["first"] == (200, "conectado")
    assert oauth.exchanges == 1

    with factory() as session:
        flow = session.execute(select(CalendarOAuthFlow)).scalar_one()
        sync = session.execute(select(CalendarSync)).scalar_one()
        assert flow.finish_result == "connected"
        assert flow.finished_at == sync.connected_em
        assert flow.verifier_encrypted is None
        assert flow.code_encrypted is None
        assert sync.google_account_email == _EMAIL
        assert sync.google_account_sub == _SUB

    # O consentimento já expirou, mas a resposta do finish se perdeu enquanto a
    # PWA estava offline: o cron preserva a prova durável deste MESMO segredo.
    with factory() as session:
        flow = session.execute(select(CalendarOAuthFlow)).scalar_one()
        flow.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
        session.commit()

    with factory() as session:
        assert purge_expired_flows(session, now=dt.datetime.now(dt.timezone.utc)) == 0
        session.commit()

    # Depois do commit, o mesmo segredo devolve a prova durável sem falar com o
    # Google uma segunda vez.
    with factory() as session:
        response = Response()
        replay = finish_connection(
            FinishRequest(flowSecret=_FLOW_SECRET),
            response=response,
            db=session,
            current_user=_user(),
            oauth=oauth,
        )
    assert response.status_code == 200
    assert replay.status == "conectado"
    assert oauth.exchanges == 1


def test_stale_calendar_selection_waiting_behind_account_switch_is_rejected(
    engine_fx: Engine, crypto_enabled
) -> None:
    """Uma seleção de A não pode ser persistida sob B depois do row lock."""
    factory = _factory(engine_fx)
    connection_a = dt.datetime.now(dt.timezone.utc)
    _seed(
        factory,
        crypto_enabled,
        code="code-pronto",
        expected_email=_OTHER_EMAIL,
        sync_connected_em=connection_a,
    )
    oauth = _BlockingOAuth(
        identity=GoogleIdentity(
            sub=_OTHER_SUB, email=_OTHER_EMAIL, email_verified=True
        ),
        block_probe=True,
    )
    outcomes: dict[str, int] = {}
    errors: dict[str, Exception] = {}

    def finish_worker() -> None:
        session = factory()
        response = Response()
        try:
            finish_connection(
                FinishRequest(flowSecret=_FLOW_SECRET),
                response=response,
                db=session,
                current_user=_user(),
                oauth=oauth,
            )
            outcomes["finish"] = response.status_code
        except Exception as exc:  # torna uma falha de thread observável
            errors["finish"] = exc
        finally:
            session.close()

    def select_worker() -> None:
        session = factory()
        try:
            select_calendar(
                SelectCalendarRequest(
                    calendarId="calendar-da-conta-a",
                    connectionVersion=connection_a,
                ),
                db=session,
                current_user=_user(),
            )
            outcomes["select"] = 200
        except HTTPException as exc:
            outcomes["select"] = exc.status_code
        except Exception as exc:  # torna uma falha de thread observável
            errors["select"] = exc
        finally:
            session.close()

    finish = threading.Thread(target=finish_worker)
    finish.start()
    assert oauth.entered.wait(timeout=20), "finish não chegou à troca OAuth"
    # Libera a troca; o probe abaixo é chamado JÁ sob o lock da igreja.
    oauth.release.set()
    assert oauth.probe_entered.wait(timeout=20), "finish não segurou a conexão B"

    selection = threading.Thread(target=select_worker)
    selection.start()
    # A seleção foi enviada com a revisão de A e está atrás do lock do finish B.
    selection.join(timeout=0.2)
    assert selection.is_alive(), "seleção não esperou o lock da troca de conta"

    oauth.probe_release.set()
    finish.join(timeout=20)
    selection.join(timeout=20)

    assert not finish.is_alive()
    assert not selection.is_alive()
    assert errors == {}
    assert outcomes == {"finish": 200, "select": 409}

    with factory() as session:
        sync = session.execute(select(CalendarSync)).scalar_one()
        assert sync.google_account_email == _OTHER_EMAIL
        assert sync.google_account_sub == _OTHER_SUB
        assert sync.connected_em != connection_a
        # A seleção de A jamais atravessou para a conexão B.
        assert sync.google_calendar_id is None


def test_expiry_purge_keeps_an_inflight_finish_until_it_commits(
    engine_fx: Engine, crypto_enabled
) -> None:
    """O cron não pode apagar a linha entre `_burn` e o commit final do finish."""
    factory = _factory(engine_fx)
    _seed(factory, crypto_enabled, code="code-pronto")
    oauth = _BlockingOAuth()
    outcomes: dict[str, tuple[int, str]] = {}
    errors: dict[str, Exception] = {}

    def worker() -> None:
        session = factory()
        response = Response()
        try:
            result = finish_connection(
                FinishRequest(flowSecret=_FLOW_SECRET),
                response=response,
                db=session,
                current_user=_user(),
                oauth=oauth,
            )
            outcomes["finish"] = (response.status_code, result.status)
        except Exception as exc:  # prova que o purge não causa StaleDataError
            errors["finish"] = exc
        finally:
            session.close()

    finish = threading.Thread(target=worker)
    finish.start()
    assert oauth.entered.wait(timeout=20), "finish não chegou à troca OAuth"

    try:
        # `_burn` já commitou e soltou a linha. Simula o relógio ultrapassando o
        # TTL durante a chamada ao Google, exatamente a janela do finding.
        with factory() as session:
            flow = session.execute(select(CalendarOAuthFlow)).scalar_one()
            flow.expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)
            session.commit()

        with factory() as session:
            assert purge_expired_flows(session, now=dt.datetime.now(dt.timezone.utc)) == 0
            session.commit()
            assert session.execute(select(CalendarOAuthFlow)).scalar_one().finish_result is None
    finally:
        oauth.release.set()
        finish.join(timeout=20)

    assert not finish.is_alive()
    assert errors == {}
    assert outcomes["finish"] == (200, "conectado")


def test_expiry_purge_collects_an_abandoned_inflight_finish_after_grace(
    engine_fx: Engine, crypto_enabled
) -> None:
    """A proteção é limitada: crash após `_burn` não retém a linha para sempre."""
    factory = _factory(engine_fx)
    now = dt.datetime.now(dt.timezone.utc)
    _seed(
        factory,
        crypto_enabled,
        code=None,
        expires_at=now - dt.timedelta(seconds=1),
        consumed_at=now - _IN_FLIGHT_FINISH_GRACE - dt.timedelta(seconds=1),
    )

    with factory() as session:
        assert purge_expired_flows(session, now=now) == 1
        session.commit()

    with factory() as session:
        assert session.execute(select(CalendarOAuthFlow)).scalar_one_or_none() is None


def test_expiry_purge_collects_completed_replay_after_grace(
    engine_fx: Engine, crypto_enabled
) -> None:
    """A confirmação durável sobrevive à PWA offline, mas não indefinidamente."""
    factory = _factory(engine_fx)
    now = dt.datetime.now(dt.timezone.utc)
    finished_at = now - _COMPLETED_REPLAY_GRACE - dt.timedelta(seconds=1)
    _seed(
        factory,
        crypto_enabled,
        code=None,
        expires_at=now - dt.timedelta(seconds=1),
        consumed_at=finished_at,
        finish_result="connected",
        finished_at=finished_at,
    )

    with factory() as session:
        assert purge_expired_flows(session, now=now) == 1
        session.commit()

    with factory() as session:
        assert session.execute(select(CalendarOAuthFlow)).scalar_one_or_none() is None
