"""Criação de Pessoa por telefone à prova de corrida (UNIQ-PESSOA-1).

Os três pontos que criam Pessoa por telefone (queue_worker de inbound, POST
/contacts, ativação de convite) fazem "procura-antes-de-criar" — TOCTOU: duas
criações concorrentes do MESMO telefone/tenant não se veem e ambas inseririam.
``uq_pessoas_telefone_ativa`` (índice único PARCIAL em (igreja_id, telefone)
onde ``arquivada_em IS NULL``) serializa a corrida no banco; ``insert_pessoa_or_
get_winner`` traduz o ``unique_violation`` da perdedora em "usa a Pessoa
vencedora" — o caminho feliz fica idêntico ao de hoje (padrão CONSOL-1).
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Pessoa
from app.domain.phone import normalize_phone, phone_suffix

# Postgres SQLSTATE de unique_violation. Só ele é tratado como "perdi a corrida";
# qualquer outra IntegrityError sobe inalterada (não é uma colisão de telefone).
_PG_UNIQUE_VIOLATION = "23505"


def find_active_pessoa_by_phone(
    db: Session, *, igreja_id: uuid.UUID, canonical: str
) -> Pessoa | None:
    """Pessoa ATIVA do tenant cujo telefone == ``canonical`` (ou None).

    Estreita pelos 8 dígitos estáveis em SQL e confirma a igualdade canônica
    completa em Python — mesma dedupe de queue_worker/contacts/auth, mas restrita
    a ativas (``arquivada_em IS NULL``), que é o conjunto coberto pelo índice
    único. A vencedora de uma corrida é, por definição, uma pessoa ATIVA.
    """
    stored_digits = func.regexp_replace(Pessoa.telefone, r"\D", "", "g")
    candidates = db.execute(
        select(Pessoa).where(
            Pessoa.igreja_id == igreja_id,
            Pessoa.arquivada_em.is_(None),
            func.right(stored_digits, 8) == phone_suffix(canonical),
        )
    ).scalars().all()
    return next(
        (p for p in candidates if normalize_phone(p.telefone) == canonical),
        None,
    )


def insert_pessoa_or_get_winner(
    db: Session, pessoa: Pessoa, *, igreja_id: uuid.UUID, canonical: str
) -> Pessoa:
    """Insere ``pessoa`` num SAVEPOINT; na corrida, devolve a vencedora.

    O INSERT roda dentro de ``db.begin_nested()`` (SAVEPOINT): se uma criação
    concorrente do mesmo telefone/tenant já venceu, o flush levanta
    ``unique_violation`` de ``uq_pessoas_telefone_ativa`` — só o SAVEPOINT é
    desfeito (ROLLBACK TO SAVEPOINT), preservando qualquer coisa já pendente na
    transação externa (importante no queue_worker, cuja Session é compartilhada
    no turno). Aí re-busca e devolve a Pessoa ATIVA vencedora. Qualquer outra
    IntegrityError (não-unique) sobe inalterada.

    Retorna a Pessoa a usar (a recém-criada no caminho feliz, ou a vencedora).
    """
    try:
        with db.begin_nested():
            db.add(pessoa)
            db.flush()
        return pessoa
    except IntegrityError as exc:
        if getattr(exc.orig, "pgcode", None) != _PG_UNIQUE_VIOLATION:
            raise
        winner = find_active_pessoa_by_phone(
            db, igreja_id=igreja_id, canonical=canonical
        )
        if winner is None:
            # unique_violation mas nenhuma vencedora ATIVA casável — inesperado
            # (ex.: colisão em algo que não é este índice). Não mascarar.
            raise
        return winner
