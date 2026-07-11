"""Testes de app.services.whatsapp_identity.find_ministerial_conflicts (M7B-W1.2).

Offline (sem Postgres): fake session entity-routed. A query de Pessoa devolve os
candidatos semeados (o service confirma a igualdade canônica de telefone em
Python, via normalize_phone); as checagens de liderança/membro ativo são
resolvidas por conjuntos de pessoa_id extraídos do WHERE real.

Cobre: casa por telefone normalizado (+55 / 9º dígito), distingue pastor / líder
de célula ativa / membro de célula ativa, NÃO acusa contato solto, e é
tenant-scoped (só o próprio igreja_id).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.db.models import Celula, CelulaMembro, Pessoa
from app.services.whatsapp_identity import find_ministerial_conflicts

_IGREJA = uuid.UUID("00000000-0000-0000-0000-00000000a001")
_P_PASTOR = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
_P_LIDER = uuid.UUID("00000000-0000-0000-0000-0000000000d2")
_P_MEMBRO = uuid.UUID("00000000-0000-0000-0000-0000000000d3")
_P_CONTATO = uuid.UUID("00000000-0000-0000-0000-0000000000d4")

_NUMERO = "558994315927"  # forma WhatsApp (com 55, sem 9º dígito local)


def _eq_predicates(statement) -> dict[str, str]:
    preds: dict[str, str] = {}
    clause = getattr(statement, "whereclause", None)
    stack = [clause] if clause is not None else []
    while stack:
        node = stack.pop()
        left = getattr(node, "left", None)
        right = getattr(node, "right", None)
        if left is not None and right is not None:
            key = getattr(left, "key", None)
            value = getattr(right, "value", None)
            if key is not None and value is not None:
                preds[key] = str(value)
            continue
        stack.extend(getattr(node, "clauses", []) or [])
    return preds


class _Result:
    def __init__(self, *, scalar=None, scalars_list=None) -> None:
        self._scalar = scalar
        self._scalars_list = list(scalars_list or [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        items = self._scalars_list
        return SimpleNamespace(all=lambda: list(items))


class _Session:
    """`pessoas` são os candidatos (o service confirma o telefone em Python);
    `leads` / `membros` são conjuntos de pessoa_id com liderança / vínculo ativo."""

    def __init__(self, *, pessoas=(), leads=frozenset(), membros=frozenset()) -> None:
        self.pessoas = list(pessoas)
        self.leads = set(str(p) for p in leads)
        self.membros = set(str(p) for p in membros)

    def execute(self, statement, params=None) -> _Result:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is Pessoa:
            # Devolve todos os candidatos do tenant filtrado; o pré-filtro por
            # sufixo é SQL (func.right/regexp_replace) e não é reavaliado aqui.
            preds = _eq_predicates(statement)
            igreja = preds.get("igreja_id")
            rows = [
                p for p in self.pessoas
                if igreja is None or str(getattr(p, "igreja_id", None)) == igreja
            ]
            return _Result(scalars_list=rows)
        if ent is Celula:
            pid = _eq_predicates(statement).get("lider_id")
            return _Result(scalar=(uuid.uuid4() if pid in self.leads else None))
        if ent is CelulaMembro:
            pid = _eq_predicates(statement).get("pessoa_id")
            return _Result(scalar=(uuid.uuid4() if pid in self.membros else None))
        return _Result()


def _pessoa(pessoa_id, *, tipo="contato", telefone="558994315927", igreja=_IGREJA):
    return SimpleNamespace(
        id=pessoa_id, igreja_id=igreja, nome="Fulano", tipo=tipo, telefone=telefone
    )


def test_sem_pessoa_correspondente_nao_ha_conflito() -> None:
    session = _Session(pessoas=[])
    assert find_ministerial_conflicts(session, igreja_id=_IGREJA, numero=_NUMERO) == []


def test_numero_vazio_retorna_lista_vazia() -> None:
    session = _Session(pessoas=[_pessoa(_P_PASTOR, tipo="pastor")])
    assert find_ministerial_conflicts(session, igreja_id=_IGREJA, numero="") == []
    assert find_ministerial_conflicts(session, igreja_id=_IGREJA, numero=None) == []


def test_pastor_com_mesmo_numero_e_conflito() -> None:
    session = _Session(pessoas=[_pessoa(_P_PASTOR, tipo="pastor")])
    conflitos = find_ministerial_conflicts(session, igreja_id=_IGREJA, numero=_NUMERO)
    assert len(conflitos) == 1
    assert conflitos[0]["pessoaId"] == str(_P_PASTOR)
    assert conflitos[0]["vinculos"] == ["pastor"]


def test_lider_de_celula_ativa_e_conflito() -> None:
    session = _Session(
        pessoas=[_pessoa(_P_LIDER, tipo="membro")], leads={_P_LIDER}
    )
    conflitos = find_ministerial_conflicts(session, igreja_id=_IGREJA, numero=_NUMERO)
    assert conflitos[0]["vinculos"] == ["lidera_celula"]


def test_membro_de_celula_ativa_e_conflito() -> None:
    session = _Session(
        pessoas=[_pessoa(_P_MEMBRO, tipo="membro")], membros={_P_MEMBRO}
    )
    conflitos = find_ministerial_conflicts(session, igreja_id=_IGREJA, numero=_NUMERO)
    assert conflitos[0]["vinculos"] == ["membro_celula"]


def test_contato_solto_com_mesmo_numero_nao_e_conflito() -> None:
    # Uma pessoa com o número mas SEM vínculo ministerial (contato, sem célula,
    # não lidera, não é pastor) não bloqueia a conexão.
    session = _Session(pessoas=[_pessoa(_P_CONTATO, tipo="contato")])
    assert find_ministerial_conflicts(session, igreja_id=_IGREJA, numero=_NUMERO) == []


def test_numero_de_linha_diferente_nao_casa() -> None:
    # Telefone da pessoa é OUTRA linha (mesmo sufixo? não) → sem conflito.
    session = _Session(
        pessoas=[_pessoa(_P_PASTOR, tipo="pastor", telefone="11988887777")]
    )
    assert find_ministerial_conflicts(session, igreja_id=_IGREJA, numero=_NUMERO) == []


def test_casa_apesar_de_mais_55_e_nono_digito() -> None:
    # Pessoa cadastrada com máscara/9º dígito; número conectado na forma WhatsApp.
    session = _Session(
        pessoas=[_pessoa(_P_PASTOR, tipo="pastor", telefone="+55 (89) 99431-5927")]
    )
    conflitos = find_ministerial_conflicts(session, igreja_id=_IGREJA, numero=_NUMERO)
    assert len(conflitos) == 1


def test_pessoa_de_outro_tenant_nao_entra() -> None:
    # A query já filtra por igreja_id; uma pessoa de outra igreja não é candidata.
    session = _Session(
        pessoas=[_pessoa(_P_PASTOR, tipo="pastor", igreja=uuid.uuid4())]
    )
    assert find_ministerial_conflicts(session, igreja_id=_IGREJA, numero=_NUMERO) == []
