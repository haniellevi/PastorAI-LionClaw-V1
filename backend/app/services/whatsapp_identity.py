"""Identidade do número na conexão WhatsApp (Missão M7B-W1.2).

Regra ministerial: o número conectado ao WhatsApp/Evolution da igreja é o número
OFICIAL de atendimento — não pode, ao mesmo tempo, ser uma pessoa que participa
de célula, lidera célula ou é pastor. Antes de AUTORIZAR uma conexão, o sistema
normaliza o número e procura uma pessoa existente no tenant com esse telefone que
carregue algum desses vínculos ministeriais. Se houver, a conexão é bloqueada com
409 acionável (lista dos vínculos a resolver) — nunca se altera/apaga dado
silenciosamente (a resolução é humana).

Reutiliza o normalizador canônico de telefone (``normalize_phone``/``phone_suffix``,
mesmo do dedupe de contatos) para casar ``+55`` e o 9º dígito.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Celula, CelulaMembro, Pessoa
from app.domain.phone import normalize_phone, phone_suffix


def find_ministerial_conflicts(
    db: Session, *, igreja_id: uuid.UUID, numero: str | None
) -> list[dict[str, object]]:
    """Pessoas do tenant cujo telefone == ``numero`` e que têm vínculo ministerial.

    Vínculos que bloqueiam o número oficial: é ``pastor``, lidera célula ATIVA
    (``celulas.lider_id``) ou tem vínculo ATIVO em ``celula_membro``. Retorna uma
    lista de ``{pessoaId, nome, telefone, vinculos: [...]}`` (vazia = sem
    conflito). Não muta nada — só detecta.
    """
    normalized = normalize_phone(numero or "")
    if not normalized:
        return []

    # Pré-filtro barato pelos 8 dígitos estáveis (igual ao dedupe de contatos),
    # confirmando a igualdade canônica completa em Python — assim +55 / 9º dígito
    # da MESMA linha não escapam nem geram falso-positivo por sufixo colidente.
    stored_digits = func.regexp_replace(Pessoa.telefone, r"\D", "", "g")
    candidatos = db.execute(
        select(Pessoa).where(
            Pessoa.igreja_id == igreja_id,
            func.right(stored_digits, 8) == phone_suffix(normalized),
        )
    ).scalars().all()

    conflitos: list[dict[str, object]] = []
    for pessoa in candidatos:
        if normalize_phone(getattr(pessoa, "telefone", None) or "") != normalized:
            continue
        vinculos: list[str] = []
        if (getattr(pessoa, "tipo", None) or "").lower() == "pastor":
            vinculos.append("pastor")
        if _leads_active_cell(db, igreja_id=igreja_id, pessoa_id=pessoa.id):
            vinculos.append("lidera_celula")
        if _has_active_membro(db, igreja_id=igreja_id, pessoa_id=pessoa.id):
            vinculos.append("membro_celula")
        if vinculos:
            conflitos.append(
                {
                    "pessoaId": str(pessoa.id),
                    "nome": getattr(pessoa, "nome", None),
                    "telefone": getattr(pessoa, "telefone", None),
                    "vinculos": vinculos,
                }
            )
    return conflitos


def _leads_active_cell(
    db: Session, *, igreja_id: uuid.UUID, pessoa_id: uuid.UUID
) -> bool:
    """True se a pessoa lidera alguma célula ATIVA do tenant (líder derivado)."""
    return (
        db.execute(
            select(Celula.id)
            .where(
                Celula.lider_id == pessoa_id,
                Celula.ativo.is_(True),
                Celula.igreja_id == igreja_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )


def _has_active_membro(
    db: Session, *, igreja_id: uuid.UUID, pessoa_id: uuid.UUID
) -> bool:
    """True se a pessoa tem vínculo ATIVO em ``celula_membro`` no tenant."""
    return (
        db.execute(
            select(CelulaMembro.id)
            .where(
                CelulaMembro.pessoa_id == pessoa_id,
                CelulaMembro.igreja_id == igreja_id,
                CelulaMembro.ativo.is_(True),
            )
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )
