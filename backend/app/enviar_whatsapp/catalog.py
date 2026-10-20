"""Closed typed request tools; approvals and evidence writes have no route."""
import re
from uuid import UUID
from typing import Literal
from pydantic import BaseModel, ConfigDict
from app.prayer.catalog import normalized
from app.domain.cell_requests import NomearLiderPayload, AbrirCelulaPayload

HELP = ('Envie ENVIAR para consultar pendências; ENVIAR pessoa NOME para estado e evidências; '
        'ENVIAR solicitações para estado das solicitações. Para solicitar: '
        'ENVIAR nomear CÉLULA; CANDIDATO ou ENVIAR abrir NOME; COBERTURA; CANDIDATO. '
        'Avaliação humana, validação/revogação de evidências e aprovação de nomeação/abertura '
        'exigem o painel autenticado, por pastor/admin distinto do autor e candidato. '
        'O WhatsApp não promove liderança nem abre célula.')


class RequestTool(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tipo: Literal['nomear_lider', 'abrir_celula']
    celula_id: UUID | None = None
    payload: NomearLiderPayload | AbrirCelulaPayload


def route(text, *, pending=False):
    value = ' '.join(normalized(text).split())
    if pending and text.strip().casefold() == 'sim':
        return 'confirm', None
    if pending and value in {'nao', 'cancelar'}:
        return 'cancel', None
    if value == 'enviar':
        return 'list', None
    if value == 'enviar solicitacoes':
        return 'history', None
    match = re.fullmatch(r'enviar pessoa (.+)', value)
    if match:
        return 'read', match.group(1)
    match = re.fullmatch(r'enviar nomear ([^;]+);\s*([^;]+)', value)
    if match:
        return 'nominate', tuple(p.strip() for p in match.groups())
    match = re.fullmatch(r'enviar abrir ([^;]+);\s*([^;]+);\s*([^;]+)', value)
    if match:
        # Preserve the spelling of user-proposed names, never treat them as identity.
        return 'open', tuple(p.strip() for p in ' '.join(text.split())[len('enviar abrir '):].split(';'))
    if re.match(r'^enviar (?:pessoa|solicitacoes|nomear|abrir|aprovar|avaliar|validar|revogar)(?: |$)', value):
        return 'help', None
    return ('clarify' if pending and value in {'sim', 'confirmo'} else 'none'), None


def execute(db, user, proposal):
    from fastapi import HTTPException
    from app.routers.cell_requests import CreateCellRequest
    from app.services.cell_request_creation import create_request
    tool = RequestTool.model_validate(proposal)
    if ((tool.tipo == 'nomear_lider' and type(tool.payload) is NomearLiderPayload and tool.celula_id)
        or (tool.tipo == 'abrir_celula' and type(tool.payload) is AbrirCelulaPayload and tool.celula_id is None)):
        from app.enviar_whatsapp.service import validate_targets
        validate_targets(db, user, tool)
        return create_request(db, user, CreateCellRequest(tipo=tool.tipo,
            celula_id=str(tool.celula_id) if tool.celula_id else None,
            payload_proposto=tool.payload.model_dump(mode='json')))
    raise HTTPException(422, 'Ferramenta indisponível. Use o painel autenticado.')
