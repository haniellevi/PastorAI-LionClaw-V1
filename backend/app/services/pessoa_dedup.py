"""Criação de Pessoa por telefone à prova de corrida (UNIQ-PESSOA-1).

Os três pontos que criam Pessoa por telefone (queue_worker de inbound, POST
/contacts, ativação de convite) fazem "procura-antes-de-criar" — TOCTOU: duas
criações concorrentes do MESMO telefone/tenant não se veem e ambas inseririam.
``lock_canonical_phone`` serializa formatos equivalentes pela chave canônica
antes da busca/inserção. ``uq_pessoas_telefone_ativa`` (índice único PARCIAL em
(igreja_id, telefone) onde ``arquivada_em IS NULL``) permanece como backstop
para o telefone bruto; ``insert_pessoa_or_get_winner`` traduz o
``unique_violation`` da perdedora em "usa a Pessoa vencedora".
"""

from __future__ import annotations

import hashlib
import time
import uuid

from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Pessoa
from app.domain.phone import normalize_phone, phone_suffix

# Postgres SQLSTATE de unique_violation. Só ele é tratado como "perdi a corrida";
# qualquer outra IntegrityError sobe inalterada (não é uma colisão de telefone).
_PG_UNIQUE_VIOLATION = "23505"
_PESSOA_PHONE_UNIQUE_CONSTRAINT = "uq_pessoas_telefone_ativa"
_WINNER_RETRY_DELAYS_SECONDS = (0.0, 0.01, 0.05)


def _is_pessoa_phone_unique_violation(exc: IntegrityError) -> bool:
    """Return whether ``exc`` is exactly the active-Pessoa phone constraint."""

    orig = exc.orig
    sqlstates = (
        getattr(orig, "pgcode", None),
        getattr(orig, "sqlstate", None),
    )
    constraint_name = getattr(getattr(orig, "diag", None), "constraint_name", None)
    return (
        _PG_UNIQUE_VIOLATION in sqlstates
        and constraint_name == _PESSOA_PHONE_UNIQUE_CONSTRAINT
    )


def _require_transient_candidate(db: Session, pessoa: Pessoa) -> None:
    """Reject a candidate already attached to any Session.

    ``Session.begin_nested()`` flushes pending state before it opens the
    SAVEPOINT.  Keeping the candidate transient until the SAVEPOINT exists is
    what lets this helper distinguish its collision from an earlier failure in
    the caller's transaction.
    """

    state = inspect(pessoa)
    if state.transient and state.session is None:
        return

    if state.session is not None and state.session is not db:
        state_name = "associada a outra Session"
    elif state.pending:
        state_name = "pending"
    elif state.persistent:
        state_name = "persistent"
    elif state.detached:
        state_name = "detached"
    else:
        state_name = "associada a uma Session"
    raise ValueError(
        "A Pessoa candidata deve estar transitória e não associada a uma "
        f"Session; recebeu estado {state_name}."
    )


def lock_canonical_phone(
    db: Session, *, igreja_id: uuid.UUID, canonical: str
) -> None:
    """Serializa writers do mesmo telefone canônico/tenant na transação atual."""

    material = f"pessoa-phone:{igreja_id}:{canonical}".encode("utf-8")
    key = int.from_bytes(
        hashlib.blake2b(material, digest_size=8).digest(),
        byteorder="big",
        signed=True,
    )
    db.execute(
        text("SELECT pg_advisory_xact_lock(:canonical_phone_key)"),
        {"canonical_phone_key": key},
    )


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

    Primeiro faz flush do estado que já estava pendente na transação externa.
    Isso fica propositalmente FORA da captura de colisão da candidata porque
    ``Session.begin_nested()`` também autofluxa antes de estabelecer o
    SAVEPOINT. Se esse estado anterior falhar, o erro original deve subir sem
    procurar vencedora. A candidata deve estar transitória e só é adicionada
    depois de o SAVEPOINT ser aberto. Se ela perder a corrida, o seu flush
    levanta ``unique_violation`` de ``uq_pessoas_telefone_ativa`` — só o
    SAVEPOINT é desfeito (ROLLBACK TO SAVEPOINT), preservando o estado externo
    já enviado mas ainda não commitado. Aí re-busca e devolve a Pessoa ATIVA
    vencedora. Só a constraint exata é deduplicada; qualquer outra
    IntegrityError sobe inalterada.

    Retorna a Pessoa a usar (a recém-criada no caminho feliz, ou a vencedora).
    """
    _require_transient_candidate(db, pessoa)
    db.flush()
    savepoint = db.begin_nested()
    try:
        with savepoint:
            db.add(pessoa)
            db.flush()
        return pessoa
    except IntegrityError as exc:
        if not _is_pessoa_phone_unique_violation(exc):
            raise
        for retry_delay in _WINNER_RETRY_DELAYS_SECONDS:
            if retry_delay:
                time.sleep(retry_delay)
            winner = find_active_pessoa_by_phone(
                db, igreja_id=igreja_id, canonical=canonical
            )
            if winner is not None:
                return winner
        # A visibilidade não estabilizou dentro do limite seguro: não inventar
        # sucesso nem invalidar a transação externa; repropagar a causa original.
        raise
