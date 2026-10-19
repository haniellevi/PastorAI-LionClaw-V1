"""Shared human/WhatsApp request creation. Caller owns the transaction."""
import uuid
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.db.models import Celula, CelulaSolicitacao, CelulaSolicitacaoEvento
from app.deps import get_current_cell_for_leader, resolve_actor_pessoa_id
from app.domain.cell_requests import (TIPO_ABRIR_CELULA, TIPO_NOMEAR_LIDER, InvalidPayload,
    validate_payload, referenced_pessoa_ids, conflict_pessoa_id, STATUS_AGUARDANDO, ACAO_CRIADA)
from app.services import cell_requests_service
from app.services.celula_membro import assert_pessoas_nao_arquivadas


def create_request(db, current_user, body):
    """Líder abre uma solicitação: nasce `aguardando`, NÃO altera o dado real.

    Valida o payload por `tipo` (422), barra conflito com solicitação aberta (409)
    e grava o evento `criada` na mesma transação. `celula_id` é sempre a ORIGEM,
    derivada da propriedade do líder (nunca do payload).
    """

    from app.routers.cell_requests import (CellRequestOut, _reject_member_tipo,
        _has_open_conflict, _PG_UNIQUE_VIOLATION, _require_requests_enabled)
    _require_requests_enabled()

    # Ownership: só o líder da célula de origem abre a solicitação (404 senão).
    igreja_id = uuid.UUID(current_user.igreja_id)
    if body.tipo == TIPO_ABRIR_CELULA:
        if body.celula_id is not None:
            raise HTTPException(422, "Abertura não tem célula de origem")
        cell = None
    elif body.celula_id is None:
        raise HTTPException(422, "celula_id é obrigatório para este tipo")
    elif body.tipo == TIPO_NOMEAR_LIDER and current_user.has_any_role(["pastor"]):
        try:
            cell_id = uuid.UUID(body.celula_id)
        except ValueError as exc:
            raise HTTPException(404, "Célula não encontrada") from exc
        cell = db.execute(select(Celula).where(Celula.id == cell_id,
            Celula.igreja_id == igreja_id).with_for_update()
            .execution_options(populate_existing=True)).scalar_one_or_none()
        if cell is None or not cell.ativo:
            raise HTTPException(404, "Célula não encontrada")
    else:
        cell = get_current_cell_for_leader(db, current_user, body.celula_id)

    # Membro (transferir/remover) é gerido pela Central, não pela tela do líder.
    _reject_member_tipo(body.tipo)

    try:
        payload = validate_payload(body.tipo, body.payload_proposto)
    except InvalidPayload as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    # W3.2A: nenhuma pessoa referenciada no payload (alvo de transferir/remover,
    # anfitrião/auxiliar propostos, novo líder/membros da multiplicação) pode
    # estar arquivada — antes de qualquer escrita (revisão externa PR#163).
    assert_pessoas_nao_arquivadas(
        db, igreja_id=igreja_id, pessoa_ids=referenced_pessoa_ids(body.tipo, payload)
    )

    if body.tipo == TIPO_ABRIR_CELULA:
        cell_requests_service._assert_pessoa_in_tenant(db, igreja_id,
            uuid.UUID(payload["novo_lider_id"]), "novo_lider_id")
        cell_requests_service.lock_opening_author(db, igreja_id=igreja_id,
            candidato_id=uuid.UUID(payload["novo_lider_id"]),
            app_user_id=uuid.UUID(current_user.app_user_id))
    if body.tipo == TIPO_NOMEAR_LIDER:
        cell_requests_service._assert_pessoa_in_tenant(db, igreja_id,
            uuid.UUID(payload["novo_lider_id"]), "novo_lider_id")
        db.refresh(cell, with_for_update=True)
        if not cell.ativo:
            raise HTTPException(409, "Célula indisponível")
        cell_requests_service.lock_nomination_author(db, cell=cell,
            candidato_id=uuid.UUID(payload["novo_lider_id"]),
            app_user_id=uuid.UUID(current_user.app_user_id))
    pessoa_id = conflict_pessoa_id(body.tipo, payload)
    if _has_open_conflict(
        db,
        igreja_id=igreja_id,
        celula_id=cell.id if cell else None,
        candidato_id=uuid.UUID(payload["novo_lider_id"]) if body.tipo == TIPO_ABRIR_CELULA else None,
        tipo=body.tipo,
        pessoa_id=pessoa_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma solicitação aberta conflitante para esta célula",
        )

    actor = resolve_actor_pessoa_id(db, current_user)
    solicitante_id = uuid.UUID(actor) if actor else None
    motivo = (body.motivo or "").strip() or None

    solicitacao = CelulaSolicitacao(
        igreja_id=igreja_id,
        celula_id=cell.id if cell else None,
        solicitante_id=solicitante_id,
        pessoa_id=uuid.UUID(pessoa_id) if pessoa_id else None,
        tipo=body.tipo,
        status=STATUS_AGUARDANDO,
        payload_proposto=payload,
        versao_proposta=1,
        candidato_id=uuid.UUID(payload["novo_lider_id"]) if body.tipo in {TIPO_NOMEAR_LIDER, TIPO_ABRIR_CELULA} else None,
        payload_atual={"lider_id": str(cell.lider_id) if cell.lider_id else None} if body.tipo == TIPO_NOMEAR_LIDER else None,
        motivo=motivo,
    )
    db.add(solicitacao)
    try:
        db.flush()

        db.add(
            CelulaSolicitacaoEvento(
                igreja_id=igreja_id,
                solicitacao_id=solicitacao.id,
                acao=ACAO_CRIADA,
                autor_id=solicitante_id,
                payload_snapshot=payload,
                de_status=None,
                para_status=STATUS_AGUARDANDO,
            )
        )
        db.flush()
        db.refresh(solicitacao)
    except IntegrityError as exc:
        # TOCTOU (SEC-4B / E13): entre o pré-check `_has_open_conflict` acima e
        # este INSERT, outra criação concorrente abriu a MESMA solicitação aberta
        # conflitante. O índice único parcial `uq_celula_solicitacao_aberta_*`
        # serializa a corrida — a 2ª a commitar recebe unique_violation. Traduz
        # DETERMINÍSTICO para o mesmo 409 do pré-check. Qualquer outra violação de
        # integridade (não-unique) sobe e vira 500: não é conflito de estado.
        if getattr(exc.orig, "pgcode", None) == _PG_UNIQUE_VIOLATION:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Já existe uma solicitação aberta conflitante para esta célula",
            ) from exc
        raise
    return CellRequestOut.from_model(solicitacao, db)

