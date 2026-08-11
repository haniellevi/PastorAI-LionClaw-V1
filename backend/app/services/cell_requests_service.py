"""Ciclo de decisão das Solicitações de célula (Células PR3-PR9).

Concentra as transições de estado da `celula_solicitacao` (aprovar, rejeitar,
pedir ajuste, reenviar, cancelar) SEMPRE com a trilha de auditoria gravada na
MESMA transação SQLAlchemy (RNF-07). Falha parcial → rollback total (nada é
aplicado, nenhum evento fica). A trilha `celula_solicitacao_evento` é append-only:
o código NUNCA faz UPDATE/DELETE nela (o trigger do banco blinda também).

A Central NUNCA edita o payload (SPEC §3.6): aprova como está, rejeita ou pede
ajuste. `tipo` roteia a rotina de aplicação da aprovação:
  - campos sensíveis: escreve o campo em `celulas`;
  - transferir/remover membro: mexe em `celula_membro` + espelho `pessoas.celula_id`;
  - multiplicacao: delega ao `cell_multiplication_service` (transacional/idempotente).
"""

from __future__ import annotations

import copy
import datetime as dt
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Celula,
    CelulaMembro,
    CelulaSolicitacao,
    CelulaSolicitacaoEvento,
    Pessoa,
)
from app.domain.cell_requests import (
    ACAO_AJUSTE_SOLICITADO,
    ACAO_APROVADA,
    ACAO_CANCELADA,
    ACAO_REENVIADA,
    ACAO_REJEITADA,
    OPEN_STATUSES,
    STATUS_AGUARDANDO,
    STATUS_AJUSTE_SOLICITADO,
    STATUS_APROVADA,
    STATUS_CANCELADA,
    STATUS_REJEITADA,
    TIPO_ALTERAR_ANFITRIAO,
    TIPO_ALTERAR_AUXILIAR,
    TIPO_ALTERAR_DIA,
    TIPO_ALTERAR_ENDERECO,
    TIPO_ALTERAR_HORARIO,
    TIPO_MULTIPLICACAO,
    TIPO_REMOVER_MEMBRO,
    TIPO_TRANSFERIR_MEMBRO,
    referenced_pessoa_ids,
)
from app.services.cell_multiplication_service import execute_multiplication
from app.services.celula_membro import (
    MembroInelegivelError,
    assert_membro_elegivel,
    assert_pessoas_nao_arquivadas,
    promote_tipo_para_membro,
)


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------------------
# Auditoria append-only
# ---------------------------------------------------------------------------
def _append_event(
    db: Session,
    *,
    solicitacao: CelulaSolicitacao,
    acao: str,
    autor_id: uuid.UUID | None,
    de_status: str | None,
    para_status: str | None,
    observacao: str | None = None,
    payload_snapshot: dict | None = None,
) -> None:
    """Adiciona uma linha imutável na trilha (na transação corrente, sem commit)."""
    snapshot = copy.deepcopy(
        payload_snapshot
        if payload_snapshot is not None
        else (solicitacao.payload_proposto or {})
    )
    db.add(
        CelulaSolicitacaoEvento(
            igreja_id=solicitacao.igreja_id,
            solicitacao_id=solicitacao.id,
            acao=acao,
            autor_id=autor_id,
            payload_snapshot=snapshot,
            de_status=de_status,
            para_status=para_status,
            observacao=observacao,
        )
    )


# ---------------------------------------------------------------------------
# Rotinas de aplicação por tipo (aprovação)
# ---------------------------------------------------------------------------
def _assert_pessoa_in_tenant(
    db: Session, igreja_id: uuid.UUID, pessoa_id: uuid.UUID, campo: str
) -> None:
    found = db.execute(
        select(Pessoa.id).where(
            Pessoa.id == pessoa_id, Pessoa.igreja_id == igreja_id
        )
    ).scalar_one_or_none()
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{campo}: pessoa não encontrada nesta igreja",
        )


def _lock_origin_cell(db: Session, solicitacao: CelulaSolicitacao) -> Celula:
    """Relê a origem sob lock e confirma que a autoria ainda é liderança atual."""

    cell = db.execute(
        select(Celula)
        .where(
            Celula.id == solicitacao.celula_id,
            Celula.igreja_id == solicitacao.igreja_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if (
        cell is None
        or not bool(cell.ativo)
        or solicitacao.solicitante_id is None
        or cell.lider_id is None
        or str(cell.lider_id) != str(solicitacao.solicitante_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A liderança ou a célula de origem mudou desde a solicitação",
        )
    return cell


def _lock_current_source_membership(
    db: Session,
    *,
    solicitacao: CelulaSolicitacao,
    pessoa_id: uuid.UUID,
) -> CelulaMembro:
    """Exige uma única membresia ativa, ainda exatamente na célula de origem."""

    memberships = list(
        db.execute(
            select(CelulaMembro)
            .where(
                CelulaMembro.igreja_id == solicitacao.igreja_id,
                CelulaMembro.pessoa_id == pessoa_id,
                CelulaMembro.ativo.is_(True),
            )
            .order_by(CelulaMembro.id.asc())
            .with_for_update()
        ).scalars().all()
    )
    if (
        len(memberships) != 1
        or str(memberships[0].celula_id) != str(solicitacao.celula_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A membresia atual não corresponde mais à célula de origem",
        )
    return memberships[0]


def _apply_payload(
    db: Session, *, solicitacao: CelulaSolicitacao, cell: Celula
) -> None:
    """Aplica `payload_proposto` ao dado real, roteado por `tipo`.

    Multiplicação NÃO passa por aqui: é tratada diretamente em `approve`
    (delega ao serviço transacional dedicado).
    """
    tipo = solicitacao.tipo
    payload = solicitacao.payload_proposto or {}
    igreja_id = solicitacao.igreja_id

    if tipo == TIPO_ALTERAR_DIA:
        cell.dia_reuniao = payload["dia_reuniao"]
    elif tipo == TIPO_ALTERAR_HORARIO:
        cell.horario = payload["horario"]
    elif tipo == TIPO_ALTERAR_ENDERECO:
        cell.endereco = payload["endereco"]
    elif tipo == TIPO_ALTERAR_ANFITRIAO:
        anfitriao_id = uuid.UUID(str(payload["anfitriao_id"]))
        _assert_pessoa_in_tenant(db, igreja_id, anfitriao_id, "anfitriao_id")
        cell.anfitriao_id = anfitriao_id
    elif tipo == TIPO_ALTERAR_AUXILIAR:
        auxiliar_id = uuid.UUID(str(payload["auxiliar_id"]))
        _assert_pessoa_in_tenant(db, igreja_id, auxiliar_id, "auxiliar_id")
        cell.auxiliar_id = auxiliar_id
    elif tipo == TIPO_TRANSFERIR_MEMBRO:
        pessoa_id = uuid.UUID(str(payload["pessoa_id"]))
        destino_id = uuid.UUID(str(payload["celula_destino_id"]))
        _assert_pessoa_in_tenant(db, igreja_id, pessoa_id, "pessoa_id")
        destino = db.execute(
            select(Celula)
            .where(Celula.id == destino_id, Celula.igreja_id == igreja_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        if destino is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="celula_destino_id: célula não encontrada nesta igreja",
            )
        if not bool(destino.ativo):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="celula_destino_id: a célula de destino está inativa",
            )
        pessoa = db.execute(
            select(Pessoa).where(
                Pessoa.id == pessoa_id, Pessoa.igreja_id == igreja_id
            )
        ).scalar_one_or_none()
        # M7B-W1.2: guarda compartilhada ANTES de desativar/inserir — recusa
        # pastor / líder da célula de destino / número do WhatsApp (este é o 6º
        # ponto de escrita de celula_membro; não passa pelo seam ensure_active_membro).
        # MembroInelegivelError vira 409 no handler global. Guarda antes da mutação
        # para a recusa não deixar o vínculo antigo desativado (a transação inteira
        # é revertida no rollback do approve, mas a ordem mantém a intenção clara).
        if pessoa is not None:
            assert_membro_elegivel(db, igreja_id=igreja_id, celula=destino, pessoa=pessoa)
        source_membership = _lock_current_source_membership(
            db, solicitacao=solicitacao, pessoa_id=pessoa_id
        )
        source_membership.ativo = False
        source_membership.updated_at = _now()
        db.add(
            CelulaMembro(
                igreja_id=igreja_id,
                celula_id=destino_id,
                pessoa_id=pessoa_id,
                papel="membro",
                ativo=True,
            )
        )
        if pessoa is not None:
            pessoa.celula_id = destino_id
            promote_tipo_para_membro(pessoa)  # vínculo ativo ⇒ tipo ≥ membro
    elif tipo == TIPO_REMOVER_MEMBRO:
        pessoa_id = uuid.UUID(str(payload["pessoa_id"]))
        _assert_pessoa_in_tenant(db, igreja_id, pessoa_id, "pessoa_id")
        source_membership = _lock_current_source_membership(
            db, solicitacao=solicitacao, pessoa_id=pessoa_id
        )
        source_membership.ativo = False
        source_membership.updated_at = _now()
        pessoa = db.execute(
            select(Pessoa).where(
                Pessoa.id == pessoa_id, Pessoa.igreja_id == igreja_id
            )
        ).scalar_one_or_none()
        if pessoa is not None:
            pessoa.celula_id = None
    else:  # pragma: no cover - tipos válidos cobertos acima / multiplicacao à parte
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"tipo não aplicável: {tipo}",
        )


# ---------------------------------------------------------------------------
# Transições de estado (cada uma commita ou rollbacka uma única vez)
# ---------------------------------------------------------------------------
def approve(
    db: Session,
    *,
    solicitacao: CelulaSolicitacao,
    cell: Celula,
    actor_pessoa_id: uuid.UUID | None,
    approver_app_user_id: uuid.UUID | None,
    idempotency_key: str | None,
) -> CelulaSolicitacao:
    """Aprova a solicitação e aplica o payload em transação única + auditoria.

    Idempotência de estado: se JÁ estava `aprovada` quando o request começou,
    retorna o mesmo resultado sem reprocessar (multiplicação reaproveita a linha
    existente). Estados terminais diferentes → 409.

    SEC-4B (TOCTOU): a linha é travada com ``SELECT ... FOR UPDATE`` (via
    ``db.refresh(..., with_for_update=True)``) ANTES de revalidar o status, na
    MESMA transação que aplica o payload, registra a decisão e commita. Duas
    aprovações concorrentes serializam nesse lock: a segunda espera a primeira
    commitar, relê o estado já decidido e cai no 409 abaixo — payload e efeitos
    de domínio são aplicados uma única vez.
    """
    # Status observado pelo caminho de leitura ANTES do lock (sem trava). Só ele
    # distingue reprocesso idempotente (já era `aprovada`) de corrida perdida
    # (virou `aprovada` enquanto esperávamos o lock) → 409.
    status_antes = solicitacao.status

    # Trava pessimista + releitura autoritativa da linha na transação corrente
    # (fecha o TOCTOU check→apply). O lock é mantido até o commit/rollback abaixo.
    db.refresh(solicitacao, with_for_update=True)

    if solicitacao.status == STATUS_APROVADA:
        if status_antes == STATUS_APROVADA:
            # Reprocesso idempotente: nada muda, nenhum novo evento (SPEC §643).
            db.rollback()
            return solicitacao
        # Outra aprovação venceu a corrida enquanto aguardávamos o lock: o estado
        # já foi decidido por ela → conflito (fecha o TOCTOU SEC-4B).
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Solicitação já foi decidida por outra aprovação",
        )
    if solicitacao.status != STATUS_AGUARDANDO:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Solicitação não está aguardando aprovação",
        )

    try:
        cell = _lock_origin_cell(db, solicitacao)
    except HTTPException:
        db.rollback()
        raise

    # W3.2A: revalida SOB O LOCK — a pessoa referenciada pode ter sido
    # arquivada entre a criação da solicitação e esta aprovação (fecha o
    # TOCTOU create->approve). `for_update=True` (3ª revisão externa PR#163)
    # trava a(s) Pessoa(s) referenciada(s) com o MESMO padrão SEC-4B de
    # `archive_pessoa`, serializando as duas operações na mesma linha de
    # Pessoa — mantido como defesa em profundidade e consistência com
    # `upsert_cell`. NOTA: a hipótese original de que a ausência deste lock
    # permitia `archive_pessoa` commitar DURANTE esta transação e conceder um
    # vínculo a pessoa já arquivada foi investigada e refutada — o bloqueador
    # `celula_solicitacao_aberta` (`preflight_archive`) já recusa
    # `archive_pessoa` durante toda a vida desta solicitação, e a mutação
    # aplicada abaixo fica coberta pelo bloqueador tipo-específico
    # (`celula_anfitriao`/`celula_auxiliar`/`celula_membro_ativo`/
    # `celula_lider`) no mesmo commit atômico que a aprova — ver testes
    # `test_approve_vs_archive_concurrent_*` em
    # test_pessoa_offboarding_service.py e o relatório da 3ª rodada. Mesmo
    # padrão de rollback-antes-do-raise das checagens acima.
    try:
        assert_pessoas_nao_arquivadas(
            db,
            igreja_id=solicitacao.igreja_id,
            pessoa_ids=referenced_pessoa_ids(
                solicitacao.tipo, solicitacao.payload_proposto or {}
            ),
            for_update=True,
        )
    except MembroInelegivelError:
        db.rollback()
        raise

    if solicitacao.tipo == TIPO_MULTIPLICACAO:
        key = (idempotency_key or "").strip()
        if not key:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="idempotency_key é obrigatório para multiplicação",
            )

    try:
        if solicitacao.tipo == TIPO_MULTIPLICACAO:
            execute_multiplication(
                db,
                igreja_id=solicitacao.igreja_id,
                cell_origin=cell,
                payload=solicitacao.payload_proposto or {},
                solicitacao_id=solicitacao.id,
                idempotency_key=(idempotency_key or "").strip(),
                approver_app_user_id=approver_app_user_id,
            )
        else:
            _apply_payload(db, solicitacao=solicitacao, cell=cell)

        de = solicitacao.status
        solicitacao.status = STATUS_APROVADA
        solicitacao.decidido_por = actor_pessoa_id
        solicitacao.decidido_em = _now()
        solicitacao.updated_at = _now()
        _append_event(
            db,
            solicitacao=solicitacao,
            acao=ACAO_APROVADA,
            autor_id=actor_pessoa_id,
            de_status=de,
            para_status=STATUS_APROVADA,
        )
        db.flush()
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return solicitacao


def reject(
    db: Session,
    *,
    solicitacao: CelulaSolicitacao,
    actor_pessoa_id: uuid.UUID | None,
    observacao_central: str,
) -> CelulaSolicitacao:
    """Rejeita a solicitação (não altera dado real). `observacao_central` obrigatória.

    SEC-4B-C (TOCTOU): trava a linha e relê ANTES de revalidar o status, na MESMA
    transação que grava a decisão + auditoria + commit (mesmo padrão de ``approve``).
    Sem isso, dois decisores concorrentes — ou reject∥approve — passam o mesmo check
    com o estado obsoleto e duplicam a auditoria / sobrescrevem a decisão do outro
    (lost update). A 2ª a chegar espera o lock, relê o estado já decidido e cai no 409.
    """
    db.refresh(solicitacao, with_for_update=True)
    if solicitacao.status not in OPEN_STATUSES:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Solicitação já foi decidida",
        )
    try:
        de = solicitacao.status
        solicitacao.status = STATUS_REJEITADA
        solicitacao.observacao_central = observacao_central
        solicitacao.decidido_por = actor_pessoa_id
        solicitacao.decidido_em = _now()
        solicitacao.updated_at = _now()
        _append_event(
            db,
            solicitacao=solicitacao,
            acao=ACAO_REJEITADA,
            autor_id=actor_pessoa_id,
            de_status=de,
            para_status=STATUS_REJEITADA,
            observacao=observacao_central,
        )
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return solicitacao


def request_adjustment(
    db: Session,
    *,
    solicitacao: CelulaSolicitacao,
    actor_pessoa_id: uuid.UUID | None,
    observacao_central: str,
) -> CelulaSolicitacao:
    """Devolve ao líder em `ajuste_solicitado` (não altera dado real).

    SEC-4B-C (TOCTOU): trava a linha e relê ANTES de revalidar o status (ver
    ``reject``). Fecha a corrida com approve/reject/cancel sobre a MESMA linha
    `aguardando` — a 2ª transição relê o estado já decidido e recebe 409.
    """
    db.refresh(solicitacao, with_for_update=True)
    if solicitacao.status != STATUS_AGUARDANDO:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Solicitação não está aguardando decisão",
        )
    try:
        de = solicitacao.status
        solicitacao.status = STATUS_AJUSTE_SOLICITADO
        solicitacao.observacao_central = observacao_central
        solicitacao.decidido_por = actor_pessoa_id
        solicitacao.decidido_em = _now()
        solicitacao.updated_at = _now()
        _append_event(
            db,
            solicitacao=solicitacao,
            acao=ACAO_AJUSTE_SOLICITADO,
            autor_id=actor_pessoa_id,
            de_status=de,
            para_status=STATUS_AJUSTE_SOLICITADO,
            observacao=observacao_central,
        )
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return solicitacao


def resubmit(
    db: Session,
    *,
    solicitacao: CelulaSolicitacao,
    actor_pessoa_id: uuid.UUID | None,
    new_payload: dict,
) -> CelulaSolicitacao:
    """Líder autor edita o payload e reenvia (só em `ajuste_solicitado`).

    SEC-4B-C (TOCTOU): trava a linha e relê ANTES de revalidar o status (ver
    ``reject``). Fecha a corrida resubmit∥resubmit (payload/evento duplicados) e
    resubmit∥cancel (lost update) sobre a MESMA linha `ajuste_solicitado`.
    """
    db.refresh(solicitacao, with_for_update=True)
    if solicitacao.status != STATUS_AJUSTE_SOLICITADO:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Só é possível reenviar solicitação em ajuste_solicitado",
        )
    try:
        _lock_origin_cell(db, solicitacao)
    except HTTPException:
        db.rollback()
        raise
    try:
        de = solicitacao.status
        solicitacao.payload_proposto = new_payload
        solicitacao.status = STATUS_AGUARDANDO
        solicitacao.updated_at = _now()
        _append_event(
            db,
            solicitacao=solicitacao,
            acao=ACAO_REENVIADA,
            autor_id=actor_pessoa_id,
            de_status=de,
            para_status=STATUS_AGUARDANDO,
            payload_snapshot=new_payload,
        )
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return solicitacao


def cancel(
    db: Session,
    *,
    solicitacao: CelulaSolicitacao,
    actor_pessoa_id: uuid.UUID | None,
) -> CelulaSolicitacao:
    """Líder autor cancela a própria solicitação (só em aguardando/ajuste — E12).

    SEC-4B-C (TOCTOU): trava a linha e relê ANTES de revalidar o status (ver
    ``reject``). Fecha a corrida cancel∥cancel (auditoria duplicada) e cancel∥approve
    (payload aplicado mas status sobrescrito para `cancelada`).
    """
    db.refresh(solicitacao, with_for_update=True)
    if solicitacao.status not in OPEN_STATUSES:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Solicitação já decidida/cancelada não pode ser cancelada",
        )
    try:
        de = solicitacao.status
        solicitacao.status = STATUS_CANCELADA
        solicitacao.updated_at = _now()
        _append_event(
            db,
            solicitacao=solicitacao,
            acao=ACAO_CANCELADA,
            autor_id=actor_pessoa_id,
            de_status=de,
            para_status=STATUS_CANCELADA,
        )
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return solicitacao
