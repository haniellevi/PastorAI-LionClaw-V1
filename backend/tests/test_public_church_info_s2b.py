"""S2b canonical public church facts stay whitelisted and deterministic."""

from __future__ import annotations

import subprocess
import sys
import uuid

import pytest

from app.agent.read_only_info import (
    CanonicalPublicCell,
    CanonicalPublicChurchInfo,
    resolve_canonical_public_info,
)
from app.routers.cells import UpsertCellRequest
from app.services.public_church_info import load_public_church_info


_TENANT_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")


@pytest.mark.parametrize(
    "module",
    ("app.services.public_church_info", "app.agent.runtime"),
)
def test_public_info_service_imports_without_runtime_cycle(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


class _Result:
    def __init__(self, *, one=None, rows=()) -> None:
        self._one = one
        self._rows = list(rows)

    def one_or_none(self):
        return self._one

    def all(self):
        return list(self._rows)


class _PublicInfoSession:
    """Small SQL-aware fake: the tested service owns every projection query."""

    def __init__(self, *, church, cells) -> None:
        self.church = church
        self.cells = cells
        self.sql: list[str] = []

    def execute(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        self.sql.append(sql)
        if "FROM igrejas" in sql:
            return _Result(one=self.church)
        if "FROM celulas" in sql:
            return _Result(rows=self.cells)
        raise AssertionError(sql)


class _NeighborhoodBoundSession(_PublicInfoSession):
    """Returns only the row PostgreSQL would retain after the SQL predicate."""

    def __init__(self, *, church, cells, expected_key: str = "bairro seis") -> None:
        super().__init__(church=church, cells=cells)
        self.expected_key = expected_key

    def execute(self, statement):
        sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
        self.sql.append(sql)
        if "FROM igrejas" in sql:
            return _Result(one=self.church)
        if "FROM celulas" in sql:
            assert "translate(lower(celulas.bairro)" in sql
            assert f"= '{self.expected_key}'" in sql
            return _Result(rows=[self.cells[-1]])
        raise AssertionError(sql)


def test_canonical_loader_uses_only_public_columns_and_active_published_cells() -> None:
    session = _PublicInfoSession(
        church=("Avenida Institucional, 10", "Domingo, 19:00"),
        cells=[("Centro", "Esperança", "terça", "19:00")],
    )

    info = load_public_church_info(session, igreja_id=_TENANT_A)

    assert info == CanonicalPublicChurchInfo(
        endereco_institucional="Avenida Institucional, 10",
        horarios_culto="Domingo, 19:00",
        celulas=(
            CanonicalPublicCell(
                bairro="Centro",
                nome="Esperança",
                dia_reuniao="terça",
                horario="19:00",
            ),
        ),
    )
    church_sql, cells_sql = session.sql
    assert "igrejas.id" in church_sql
    assert str(_TENANT_A).replace("-", "") in church_sql
    assert "celulas.igreja_id" in cells_sql
    assert "celulas.ativo IS true" in cells_sql
    assert "celulas.divulgar_whatsapp IS true" in cells_sql
    for private_column in (
        "celulas.endereco",
        "celulas.lider_id",
        "celulas.anfitriao_id",
        "celulas.auxiliar_id",
        "celulas.link_grupo",
        "celulas.link_localizacao",
    ):
        assert private_column not in cells_sql


def test_requested_neighborhood_is_filtered_before_the_five_cell_limit() -> None:
    """A published sixth neighborhood remains findable without broad loading."""

    session = _NeighborhoodBoundSession(
        church=(None, None),
        cells=[
            (f"Bairro {index}", "Outra", "terça", "19:00")
            for index in range(1, 6)
        ]
        + [("Bairro Seis", "Esperança", "terça", "19:00")],
    )

    info = load_public_church_info(
        session,
        igreja_id=_TENANT_A,
        bairro="Bairro Seis",
    )

    assert info is not None
    assert info.celulas == (
        CanonicalPublicCell(
            bairro="Bairro Seis",
            nome="Esperança",
            dia_reuniao="terça",
            horario="19:00",
        ),
    )
    assert "LIMIT 5" in session.sql[-1]


def test_nfd_neighborhood_is_canonicalized_before_public_accentless_lookup() -> None:
    payload = UpsertCellRequest(
        nome="Esperança",
        coberturaEspiritual="Cobertura",
        bairro="Sa\u0303o Jose\u0301",
        divulgarWhatsapp=True,
    )
    session = _NeighborhoodBoundSession(
        church=(None, None),
        cells=[("São José", "Esperança", "terça", "19:00")],
        expected_key="sao jose",
    )

    info = load_public_church_info(
        session,
        igreja_id=_TENANT_A,
        bairro="sao jose",
    )

    assert payload.bairro == "São José"
    assert info is not None
    assert info.celulas[0].bairro == "São José"


def test_canonical_cell_reply_has_the_exact_secretary_offer_without_private_data() -> None:
    resolution = resolve_canonical_public_info(
        "Qual célula no bairro Centro?",
        CanonicalPublicChurchInfo(
            endereco_institucional="Rua privada que não entra nesta resposta",
            horarios_culto=None,
            celulas=(
                CanonicalPublicCell(
                    bairro="Centro",
                    nome="Esperança",
                    dia_reuniao="terça",
                    horario="19:00",
                ),
            ),
        ),
    )

    assert resolution is not None
    assert resolution.oferece_secretaria is True
    assert resolution.resposta == (
        "Há uma célula com informações públicas no bairro Centro: Esperança. "
        "Encontro: terça, 19:00. Quer falar com a secretaria da igreja para "
        "entrar em contato com o líder da célula?"
    )
    assert "Rua privada" not in resolution.resposta


@pytest.mark.parametrize(
    "question",
    (
        "Que horas é o culto?",
        "Onde fica a igreja?",
        "Qual célula no bairro Centro?",
    ),
)
def test_canonical_absence_offers_secretary_without_llm(question: str) -> None:
    resolution = resolve_canonical_public_info(
        question,
        CanonicalPublicChurchInfo(
            endereco_institucional=None,
            horarios_culto=None,
            celulas=(),
        ),
    )

    assert resolution is not None
    assert resolution.oferece_secretaria is True
    assert resolution.resposta == (
        "Não tenho essa informação cadastrada. Quer falar com a secretaria da igreja?"
    )


def test_non_public_question_is_not_claimed_by_the_deterministic_source() -> None:
    assert (
        resolve_canonical_public_info(
            "Quero oração pela minha célula",
            CanonicalPublicChurchInfo(
                endereco_institucional=None,
                horarios_culto=None,
                celulas=(),
            ),
        )
        is None
    )
