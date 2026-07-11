"""Multiplicação de célula — transacional e idempotente (Células PR3-PR9).

Acionado por `POST /cell-requests/{id}/approve` quando `tipo='multiplicacao'`
(SPEC §6.3, US-19/RF-23). NÃO faz commit: roda dentro da MESMA transação da
aprovação/auditoria (o serviço de solicitações commita/rollbacka uma única vez).

Em uma passada, para a solicitação aprovada:
  1. Idempotência: se já existe `multiplicacoes` para esta `solicitacao_id` ou para
     este `idempotency_key` (por tenant), devolve a linha existente sem duplicar
     nada (RNF-06/07).
  2. Valida o payload contra o banco (regra 2026-07-06): `novo_lider_id` precisa
     ser pessoa do tenant, `apto_lider=true` (Reencontro), não-CSIM e não pode
     já liderar célula ATIVA. NÃO precisa ser membro da célula de origem — a
     Central/Admin pode escolher qualquer apto sem célula.
  3. Cria a nova `celulas` (`lider_id=novo_lider_id`, herda a cobertura da origem
     e aplica os campos sensíveis do payload). A liderança é SEMPRE
     `celulas.lider_id` — nunca papel em `celula_membro`.
  4. Move os membros transferidos: desativa o vínculo ativo na origem e cria
     vínculo ATIVO na nova célula (papel 'membro'); sincroniza `pessoas.celula_id`
     (espelho legado). Novo líder EXTERNO à origem não ganha vínculo em
     `celula_membro` (o enum de papel não tem 'lider' de propósito) e o
     `pessoas.celula_id` dele não muda.
  5. Grava `multiplicacoes` com `celula_id`=origem, `celula_nova_id`=nova,
     `solicitacao_id` (UNIQUE) e `idempotency_key`.

`celula_id` PERMANECE a célula de origem (nunca renomear — RNF-17).
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Celula, CelulaMembro, Multiplicacao, Pessoa
from app.domain.multiplication import STATUS_CONCLUIDA

# Papel do vínculo em celula_membro — o enum celula_membro_papel só aceita
# membro/auxiliar/anfitriao ('lider' NÃO existe: liderança é celulas.lider_id).
_PAPEL_MEMBRO = "membro"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _assert_pessoa_in_tenant(
    db: Session, igreja_id: uuid.UUID, pessoa_id: uuid.UUID, campo: str
) -> None:
    """Rejeita (422) uma FK de pessoa que não pertence à igreja do tenant.

    A FK do Postgres roda como owner (bypassa RLS), então uma pessoa de OUTRA
    igreja passaria na checagem referencial e vazaria cross-tenant — mesmo furo
    que o PR1 fechou em cells.py. Toda pessoa vinda do payload é validada aqui.
    """
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


def find_existing_multiplication(
    db: Session, *, igreja_id: uuid.UUID, solicitacao_id: uuid.UUID, idempotency_key: str
) -> Multiplicacao | None:
    """Linha existente que barra reprocesso (por solicitação OU por idempotency_key)."""
    by_solicitacao = db.execute(
        select(Multiplicacao).where(
            Multiplicacao.igreja_id == igreja_id,
            Multiplicacao.solicitacao_id == solicitacao_id,
        )
    ).scalar_one_or_none()
    if by_solicitacao is not None:
        return by_solicitacao
    return db.execute(
        select(Multiplicacao).where(
            Multiplicacao.igreja_id == igreja_id,
            Multiplicacao.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()


def execute_multiplication(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    cell_origin: Celula,
    payload: dict,
    solicitacao_id: uuid.UUID,
    idempotency_key: str,
    approver_app_user_id: uuid.UUID | None = None,
) -> Multiplicacao:
    """Executa (ou reaproveita) a multiplicação. Sem commit — ver docstring.

    Levanta 422 quando o novo líder não é apto/é CSIM/não existe no tenant e
    409 quando já lidera uma célula ativa (regra 2026-07-06).
    """
    # 1. Idempotência: reprocesso devolve a mesma linha, sem criar 2ª célula.
    existing = find_existing_multiplication(
        db,
        igreja_id=igreja_id,
        solicitacao_id=solicitacao_id,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        return existing

    novo_lider_id = uuid.UUID(str(payload["novo_lider_id"]))
    membros_ids = [uuid.UUID(str(m)) for m in payload["membros_transferidos_ids"]]

    # 2. Validação com o banco (regra 2026-07-06): apto + não-CSIM + não lidera
    #    célula ativa. Membership na origem NÃO é exigida — a Central pode
    #    escolher qualquer apto sem célula do tenant.
    novo_lider = db.execute(
        select(Pessoa).where(
            Pessoa.id == novo_lider_id, Pessoa.igreja_id == igreja_id
        )
    ).scalar_one_or_none()
    if novo_lider is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="novo_lider_id: pessoa não encontrada nesta igreja",
        )
    if bool(novo_lider.sem_interesse):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "novo_lider_id: pessoa sem interesse (CSIM) não pode liderar célula"
            ),
        )
    if not bool(novo_lider.apto_lider):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "novo_lider_id: pessoa ainda não fez o Reencontro "
                "(não apta a liderar)"
            ),
        )
    ja_lidera = db.execute(
        select(Celula.id)
        .where(
            Celula.igreja_id == igreja_id,
            Celula.lider_id == novo_lider_id,
            Celula.ativo.is_(True),
        )
        .limit(1)
    ).scalar_one_or_none()
    if ja_lidera is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="novo_lider_id: pessoa já lidera uma célula ativa",
        )

    # 2b. FKs de pessoa da NOVA célula (anfitrião/auxiliar) validadas no tenant
    #     ANTES de qualquer escrita — a FK do Postgres bypassa RLS.
    anfitriao_id = _to_uuid(payload.get("anfitriao_id"))
    auxiliar_id = _to_uuid(payload.get("auxiliar_id"))
    if anfitriao_id is not None:
        _assert_pessoa_in_tenant(db, igreja_id, anfitriao_id, "anfitriao_id")
    if auxiliar_id is not None:
        _assert_pessoa_in_tenant(db, igreja_id, auxiliar_id, "auxiliar_id")

    # 3. Nova célula (herda cobertura_espiritual — NOT NULL — da origem).
    nova_celula = Celula(
        igreja_id=igreja_id,
        nome=str(payload["nome_nova_celula"]),
        lider_id=novo_lider_id,
        cobertura_espiritual=cell_origin.cobertura_espiritual,
        dia_reuniao=payload.get("dia_reuniao"),
        horario=payload.get("horario"),
        endereco=payload.get("endereco"),
        anfitriao_id=anfitriao_id,
        auxiliar_id=auxiliar_id,
        ativo=True,
    )
    db.add(nova_celula)
    db.flush()  # popula nova_celula.id para os vínculos/sincronizações abaixo.

    # 4. Move cada membro: desativa vínculo antigo, cria vínculo ativo na nova,
    #    sincroniza pessoas.celula_id (espelho legado).
    for pessoa_id in membros_ids:
        antigo = db.execute(
            select(CelulaMembro).where(
                CelulaMembro.igreja_id == igreja_id,
                CelulaMembro.celula_id == cell_origin.id,
                CelulaMembro.pessoa_id == pessoa_id,
                CelulaMembro.ativo.is_(True),
            )
        ).scalar_one_or_none()
        # Todo transferido tem de ser membro ATIVO da origem: fecha o vazamento
        # cross-tenant (pessoa de outra igreja não tem vínculo aqui) E evita o
        # IntegrityError do índice único parcial (pessoa ativa em outra célula)
        # que virava 500 opaco na aprovação. 422 acionável para a Central.
        if antigo is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"membro {pessoa_id} não é membro ativo da célula de origem"
                ),
            )
        # ponytail: a guarda de elegibilidade (M7B-W1.2) NÃO é aplicada aqui de
        # propósito. A multiplicação só move membros JÁ ATIVOS da origem (validado
        # acima) e o payload inclui o `novo_lider_id` na lista de transferidos —
        # aplicar a guarda barraria o próprio novo líder (regra "líder da própria
        # célula"), quebrando um fluxo válido. O tratamento do líder-como-membro na
        # multiplicação é questão de domínio à parte, fora do escopo desta missão.
        antigo.ativo = False
        antigo.updated_at = _now()

        db.add(
            CelulaMembro(
                igreja_id=igreja_id,
                celula_id=nova_celula.id,
                pessoa_id=pessoa_id,
                papel=_PAPEL_MEMBRO,
                ativo=True,
            )
        )

        pessoa = db.execute(
            select(Pessoa).where(
                Pessoa.id == pessoa_id, Pessoa.igreja_id == igreja_id
            )
        ).scalar_one_or_none()
        if pessoa is not None:
            pessoa.celula_id = nova_celula.id

    # 5. Registra a multiplicação (celula_id=origem; celula_nova_id=nova).
    data_prevista = _to_date(payload.get("data_prevista"))
    multiplicacao = Multiplicacao(
        igreja_id=igreja_id,
        celula_id=cell_origin.id,
        celula_nova_id=nova_celula.id,
        solicitacao_id=solicitacao_id,
        idempotency_key=idempotency_key,
        novo_lider_id=novo_lider_id,
        status=STATUS_CONCLUIDA,
        data_prevista=data_prevista,
        descendencia=payload.get("descendencia"),
        supervisao_ok=True,
        aprovada_por=approver_app_user_id,
    )
    db.add(multiplicacao)
    db.flush()
    return multiplicacao


def _to_uuid(value: object) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value else None


def _to_date(value: object) -> dt.date | None:
    if not value:
        return None
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))
