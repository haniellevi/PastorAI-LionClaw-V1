"""Registro de pedido de oração recusa com HTTPException quando falta um dado.

O turno trata HTTPException como recusa: cancela a proposta e responde à
pessoa. Um AttributeError derrubaria o turno inteiro. Os três casos abaixo
vieram da checagem de tipos (mypy). Dados sintéticos, sem banco.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.prayer import service

TENANT = uuid.UUID("4a4a4a4a-0000-4000-8000-0000000000aa")
ENTREGUE_EM = dt.datetime(2026, 1, 5, 12, 0, tzinfo=dt.UTC)


class _Db:
    def __init__(self, *, conversation=None, delivered=None):
        self._conversation = conversation
        self._delivered = delivered

    def get(self, _model, _id):
        return self._conversation

    def execute(self, _statement):
        return SimpleNamespace(scalar_one_or_none=lambda: self._delivered)


@pytest.fixture
def pedido(monkeypatch):
    monkeypatch.setattr(service.policy, "enabled", lambda _igreja_id: True)
    monkeypatch.setattr(service, "has_audio", lambda _db, _proposal: False)
    contact = SimpleNamespace(
        igreja_id=TENANT,
        conversation_id=uuid.uuid4(),
        pessoa_id=uuid.uuid4(),
        term_version="termo-sintetico",
    )
    proposal = SimpleNamespace(
        id=uuid.uuid4(),
        summary="resumo sintético",
        cell_id=None,
        leader_id=None,
        state="pending",
        audience="pastoral",
        igreja_id=TENANT,
        pessoa_id=contact.pessoa_id,
        conversation_id=contact.conversation_id,
        term_version=contact.term_version,
        summary_message_id=uuid.uuid4(),
        authorization_text=None,
        delivered_at=None,
    )
    monkeypatch.setattr(service, "resolve_contact", lambda *_args, **_kwargs: contact)
    return contact, proposal


def _confirmacao(texto):
    return SimpleNamespace(
        id=uuid.uuid4(),
        provider_message_id="sintetico",
        texto=texto,
        criado_em=ENTREGUE_EM + dt.timedelta(minutes=1),
    )


def test_conversa_inexistente_recusa_sem_quebrar_o_turno(pedido):
    contact, proposal = pedido

    with pytest.raises(HTTPException) as erro:
        service.register(
            _Db(conversation=None), contact=contact, proposal=proposal, confirmation=_confirmacao("SIM")
        )

    assert erro.value.status_code == 403


def test_confirmacao_sem_texto_recusa_sem_quebrar_o_turno(pedido):
    contact, proposal = pedido
    conversa = SimpleNamespace(telefone="5500000000000")

    with pytest.raises(HTTPException) as erro:
        service.register(
            _Db(conversation=conversa), contact=contact, proposal=proposal, confirmation=_confirmacao(None)
        )

    assert erro.value.status_code == 403
    assert erro.value.detail == "Confirmação explícita obrigatória"


def test_proposta_sem_texto_de_autorizacao_recusa_sem_quebrar_o_turno(pedido, monkeypatch):
    contact, proposal = pedido
    # Resumo entregue e dentro do prazo: só falta o texto de autorização.
    proposal.delivered_at = ENTREGUE_EM
    proposal.expires_at = ENTREGUE_EM + dt.timedelta(minutes=10)
    monkeypatch.setattr(service, "now", lambda _db: ENTREGUE_EM + dt.timedelta(minutes=2))
    monkeypatch.setattr(service, "has_pastoral_team", lambda _db, _tenant: True)
    conversa = SimpleNamespace(telefone="5500000000000")
    resumo_entregue_sem_texto = SimpleNamespace(texto=None)

    with pytest.raises(HTTPException) as erro:
        service.register(
            _Db(conversation=conversa, delivered=resumo_entregue_sem_texto),
            contact=contact,
            proposal=proposal,
            confirmation=_confirmacao("SIM"),
        )

    assert erro.value.status_code == 409
