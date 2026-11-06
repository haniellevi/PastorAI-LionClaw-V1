"""V1a conversation through committed storage and the leader's real HTTP view.

V1A_PANEL_BRIDGE_DIR optionally lets a local browser inspect that same report.
Without it, the complete backend proof still runs against disposable PostgreSQL.
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
import json
import os
from pathlib import Path
import socket
from threading import Thread
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import httpx
import pytest
from sqlalchemy import delete
import uvicorn

from app.db.models import (
    AgentActionProposal, AgentActionReceipt, AiUsageLog, AppUser, Celula,
    CelulaReuniao, CellReportAiReservation, CellReportDraft, Decision, Message,
    UserRole,
)
from app.db.session import get_db
from app.domain.cell_report_snapshot import validate_cell_report_snapshot_v2
from app.routers import cell_meetings
from app.services.auth_sessions import register_session_with_backend_role
from app.services.clerk import ClerkClient, get_clerk_client
from app.workers import queue_worker as worker_module
from tests.conftest_rls import assert_disposable_database
from tests.test_cell_report_v1a_worker_pg import (
    _CommittedReceiptEvolution, _IGREJA, _rows, _run, _snapshot,
    msg_engine_fx, report_turn, s3_turn,  # noqa: F401 - fixtures
)
from tests.private_send_pg import install_private_send_release, private_send_login

pytestmark = pytest.mark.rls_integration


@pytest.fixture(scope="session")
def rls_database_url() -> str:
    """A missing disposable database must fail this proof, never skip it."""
    url = os.environ.get("RLS_TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.fail("This proof requires RLS_TEST_DATABASE_URL for disposable PostgreSQL")
    assert_disposable_database(url)
    return url


@pytest.fixture
def send_release(msg_engine_fx, monkeypatch):
    """Install the existing release helper even on a fresh CI shard cluster."""
    assert_disposable_database(msg_engine_fx.url.render_as_string(hide_password=False))
    with msg_engine_fx.begin() as connection:
        connection.exec_driver_sql("""
            do $$ begin
              if not exists (select 1 from pg_roles where rolname = 'anon') then
                create role anon nologin noinherit nobypassrls;
              end if;
              if not exists (select 1 from pg_roles where rolname = 'service_role') then
                create role service_role nologin noinherit nobypassrls;
              end if;
            end $$;
        """)
        schema = connection.exec_driver_sql("select current_schema()").scalar_one()
    install_private_send_release(msg_engine_fx, schema)
    with private_send_login(msg_engine_fx, monkeypatch, schema=schema) as factory:
        yield factory


@pytest.fixture
def leader_report_turn(report_turn):
    """Keep the real person/cell link, removing the seed's Central privilege."""
    with report_turn.factory.begin() as session:
        app_user = session.get(AppUser, report_turn.app_user_id)
        meeting = session.get(CelulaReuniao, report_turn.meeting_id)
        cell = session.get(Celula, meeting.celula_id)
        assert cell.lider_id == app_user.pessoa_id
        session.execute(delete(UserRole).where(
            UserRole.igreja_id == _IGREJA,
            UserRole.user_id == report_turn.app_user_id,
        ))
        session.add(UserRole(
            igreja_id=_IGREJA, user_id=report_turn.app_user_id, papel="lider_celula",
        ))
    return report_turn


@contextmanager
def _panel_http(app: FastAPI, *, bridge_directory: Path | None):
    """A bounded, temporary listener; no ASGI transport or auth overrides."""
    socket_path = bridge_directory / "api.sock" if bridge_directory else None
    if socket_path:
        bridge_directory.mkdir(parents=True, exist_ok=True)
        assert not socket_path.exists(), "Browser bridge socket already exists"
    with socket.socket(socket.AF_UNIX if socket_path else socket.AF_INET) as listener:
        listener.bind(str(socket_path) if socket_path else ("127.0.0.1", 0))
        try:
            listener.listen(128)
            port = 0 if socket_path else listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(
                app, host="127.0.0.1", port=port, lifespan="off", access_log=False,
                log_level="error", timeout_graceful_shutdown=2,
            ))
            thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started and thread.is_alive() and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert server.started and thread.is_alive(), "Temporary HTTP server did not start"
                yield (
                    {"base_url": "http://localhost", "transport": httpx.HTTPTransport(
                        uds=str(socket_path), trust_env=False,
                    )} if socket_path else {"base_url": f"http://127.0.0.1:{port}"}
                )
            finally:
                server.should_exit = True
                thread.join(timeout=5)
                if thread.is_alive():
                    server.force_exit = True
                    thread.join(timeout=5)
                assert not thread.is_alive(), "Temporary HTTP server did not stop"
        finally:
            if socket_path:
                listener.close()
                socket_path.unlink(missing_ok=True)


def _wait_for_browser(directory: Path, *, token: str, meeting_id: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    ready = directory / "ready.json"
    done = directory / "browser-done.json"
    assert not ready.exists() and not done.exists(), "Use an empty V1A_PANEL_BRIDGE_DIR"
    pending = directory / "ready.tmp"
    pending.write_text(json.dumps({"token": token, "meeting_id": meeting_id}), encoding="utf-8")
    pending.replace(ready)
    deadline = time.monotonic() + 90
    while not done.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert done.exists(), "Browser proof did not finish within 90 seconds"
    result = json.loads(done.read_text(encoding="utf-8"))
    assert result.get("ok") is True, "Browser proof reported failure"


def test_v1a_collect_correct_confirm_then_leader_http_and_revocation(
    leader_report_turn, send_release,
):
    turn = leader_report_turn
    assert [role.papel for role in _rows(turn, UserRole)] == ["lider_celula"]
    evolution = _CommittedReceiptEvolution(turn)
    initial_snapshot = _snapshot(turn)
    outcomes = []

    outcomes.append(_run(turn, "V1A-PANEL-PARTIAL", "Relatório: presentes: 10", evolution))
    draft = _rows(turn, CellReportDraft)[0]
    assert draft.state == "coletando"
    assert draft.candidate_json["presentes"] == 10
    assert all(draft.candidate_json[field] is None for field in (
        "visitantes", "decisoes", "oferta_centavos",
    ))
    assert "informe também: visitantes, decisões, oferta total." in evolution.calls[-1][2]
    assert _rows(turn, AgentActionProposal) == []
    before_invalid = (draft.id, draft.revision, draft.candidate_json, draft.candidate_sha256)

    outcomes.append(_run(turn, "V1A-PANEL-FRACTION", "visitantes: 2,5", evolution))
    draft = _rows(turn, CellReportDraft)[0]
    assert (draft.id, draft.revision, draft.candidate_json, draft.candidate_sha256) == before_invalid
    assert "Envie apenas presentes, visitantes, decisões e oferta total." in evolution.calls[-1][2]
    assert _rows(turn, AgentActionProposal) == []
    assert _snapshot(turn) == initial_snapshot
    assert _rows(turn, AgentActionReceipt) == []
    assert _rows(turn, CellReportAiReservation) == []
    assert _rows(turn, AiUsageLog) == []

    outcomes.append(_run(
        turn, "V1A-PANEL-COMPLETE", "visitantes: 2; decisões: 1; oferta: 30,00", evolution,
    ))
    proposals = _rows(turn, AgentActionProposal)
    assert len(proposals) == 1
    original = proposals[0]
    assert original.state == "pendente" and original.delivered_at is not None
    assert "10 presentes, 2 visitantes, 1 decisão e oferta total de R$ 30,00." in evolution.calls[-1][2]
    assert _snapshot(turn) == initial_snapshot
    assert _rows(turn, AgentActionReceipt) == []

    outcomes.append(_run(
        turn, "V1A-PANEL-CORRECT", "Correção: presentes: 12; oferta: 35,50", evolution,
    ))
    proposals = _rows(turn, AgentActionProposal)
    assert len(proposals) == 2
    assert next(p for p in proposals if p.id == original.id).state == "cancelada"
    pending = [p for p in proposals if p.state == "pendente"]
    assert len(pending) == 1 and pending[0].id != original.id
    assert pending[0].delivered_at is not None
    assert "12 presentes, 2 visitantes, 1 decisão e oferta total de R$ 35,50." in evolution.calls[-1][2]
    assert _snapshot(turn) == initial_snapshot
    assert _rows(turn, AgentActionReceipt) == []

    confirmation = _run(turn, "V1A-PANEL-SIM", "SIM", evolution)
    outcomes.append(confirmation)
    state, raw = _snapshot(turn)
    assert state == "enviado"
    committed = validate_cell_report_snapshot_v2(raw)
    assert (committed.totals.presentes, committed.totals.visitantes, committed.totals.decisoes) == (12, 2, 1)
    assert committed.oferta_valor == Decimal("35.50")
    receipts = _rows(turn, AgentActionReceipt)
    assert len(receipts) == 1
    assert receipts[0].proposal_id == pending[0].id
    assert receipts[0].confirmation_message_id == confirmation.inbound_message_id
    assert evolution.committed_receipts == 1
    assert "Relatório confirmado." in evolution.calls[-1][2]
    assert _rows(turn, Decision) == []
    assert _rows(turn, CellReportAiReservation) == []
    assert _rows(turn, AiUsageLog) == []
    outbounds = [message for message in _rows(turn, Message) if message.direcao == "out"]
    assert len(outbounds) == len(evolution.calls) == 5
    assert sorted(message.texto for message in outbounds) == sorted(call[2] for call in evolution.calls)
    assert all(message.agent_reply_state == worker_module._AGENT_REPLY_CONFIRMED for message in outbounds)

    bridge_value = os.environ.get("V1A_PANEL_BRIDGE_DIR")
    clerk = ClerkClient(SimpleNamespace(
        effective_session_secret="synthetic-v1a-leader-panel-session-secret",
        session_ttl_hours=1,
    ))
    try:
        token = clerk._mint_session_token("clerk-s3-synthetic")
        with turn.factory() as session:
            app_user = session.get(AppUser, turn.app_user_id)
        register_session_with_backend_role(clerk, token, app_user, session_factory=turn.factory)
        app = FastAPI()
        app.include_router(cell_meetings.router)
        if bridge_value:
            app.add_middleware(
                CORSMiddleware, allow_origin_regex=r"http://127\.0\.0\.1:\d+",
                allow_methods=["GET", "OPTIONS"], allow_headers=["Authorization"],
            )

        def db():
            with turn.factory() as session:
                yield session

        app.dependency_overrides[get_db] = db
        app.dependency_overrides[get_clerk_client] = lambda: clerk
        path = f"/cell-meetings/{turn.meeting_id}/report"
        bridge_directory = Path(bridge_value) if bridge_value else None
        with _panel_http(app, bridge_directory=bridge_directory) as client_options:
            with httpx.Client(**client_options, timeout=5, trust_env=False) as client:
                assert client.get(path).status_code == 401
                headers = {"Authorization": f"Bearer {token}"}
                response = client.get(path, headers=headers)
                assert response.status_code == 200, response.text
                body = response.json()
                assert body["meeting_id"] == str(turn.meeting_id)
                assert body["schema"] == "cell-report/v2"
                assert body["relatorio_status"] == "enviado"
                assert body["totals"] == {"presentes": 12, "visitantes": 2, "decisoes": 1}
                assert body["oferta_valor"] == 35.5
                assert body["observacoes"] is None
                assert body["presencas"] == body["visitantes"] == body["records"] == []
                assert "submission_effect_id" not in body and "submission_payload_digest" not in body
                if bridge_value:
                    _wait_for_browser(Path(bridge_value), token=token, meeting_id=str(turn.meeting_id))

                # Replay while leadership is still valid, independently of revocation.
                sends = len(evolution.calls)
                for outcome in outcomes:
                    disposition = worker_module.run_agent_for_message(
                        turn.factory, outcome, evolution_client=evolution,
                    )
                    assert disposition is worker_module.AgentRunDisposition.COMPLETED
                assert _snapshot(turn) == (state, raw)
                assert [receipt.id for receipt in _rows(turn, AgentActionReceipt)] == [receipts[0].id]
                assert len(evolution.calls) == sends
                assert evolution.committed_receipts == 1

                # The same valid session and role cannot bypass a revoked cell link.
                with turn.factory.begin() as session:
                    meeting = session.get(CelulaReuniao, turn.meeting_id)
                    session.get(Celula, meeting.celula_id).lider_id = None
                rejected = client.get(path, headers=headers)
                assert rejected.status_code == 404
                assert rejected.json() == {"detail": "Célula não encontrada"}

    finally:
        clerk.close()
