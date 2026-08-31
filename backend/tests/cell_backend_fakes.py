"""Fakes compartilhados para os testes de backend das Células (PR3-PR9).

Sessão fake em memória (sem Postgres) que espelha os predicados WHERE, o filtro
``ativo`` e o ORDER BY dos routers de avisos/materiais/Central e do serviço de
saúde. Segue o mesmo estilo de ``test_cell_discipulo.py`` (``DiscipuloSession``),
ampliado para as entidades usadas por esta sprint (Material, Solicitacao,
Visitante, Pessoa).

Datas em extremos (2000 = sempre passada; 2999 = sempre futura) tornam
``meeting_has_passed`` (relógio real, America/Sao_Paulo) determinista.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from sqlalchemy.sql import operators

from app.db.models import (
    AppUser,
    Celula,
    CelulaAviso,
    CelulaExpectativaVisitante,
    CelulaMaterial,
    CelulaMembro,
    CelulaPresenca,
    CelulaReuniao,
    CelulaSolicitacao,
    CelulaVisitante,
    Pessoa,
)
from tests.conftest import make_app_user  # re-exportado p/ os testes desta sprint

__all__ = ["make_app_user"]

# --- IDs canônicos (uuid válidos) -----------------------------------------
TENANT = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT = "00000000-0000-0000-0000-000000000002"
CELL = "00000000-0000-0000-0000-0000000000e1"
CELL2 = "00000000-0000-0000-0000-0000000000e2"
OTHER_CELL = "00000000-0000-0000-0000-0000000000e3"
PASTOR_PESSOA = "00000000-0000-0000-0000-0000000000b0"
LP = "00000000-0000-0000-0000-0000000000b1"  # pessoa do líder
LP2 = "00000000-0000-0000-0000-0000000000b2"  # pessoa de outro líder
MEMBER_PESSOA = "00000000-0000-0000-0000-0000000000d1"
REU = "00000000-0000-0000-0000-0000000000f1"

PAST = dt.date(2000, 1, 1)  # sempre no passado
FUTURE = dt.date(2999, 12, 31)  # sempre no futuro


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ===========================================================================
# Result helpers
# ===========================================================================
class _Scalars:
    def __init__(self, items) -> None:
        self._items = list(items)

    def all(self) -> list:
        return list(self._items)

    def first(self):
        return self._items[0] if self._items else None


class _R:
    def __init__(self, *, scalar=None, scalars=None, rows=None) -> None:
        self._scalar = scalar
        self._scalars = list(scalars or [])
        self._rows = list(rows or [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self) -> _Scalars:
        return _Scalars(self._scalars)

    def all(self) -> list:
        return list(self._rows)


# ===========================================================================
# Fake session
# ===========================================================================
class CellSession:
    def __init__(
        self,
        *,
        app_user,
        roles,
        actor_pessoa_id=None,
        cells=None,
        reunioes=None,
        membros=None,
        presencas=None,
        expectativas=None,
        visitantes=None,
        avisos=None,
        materiais=None,
        solicitacoes=None,
        pessoas=None,
    ) -> None:
        self.app_user = app_user
        self.roles = roles
        self.actor_pessoa_id = actor_pessoa_id
        self.cells = cells or []
        self.reunioes = reunioes or []
        self.membros = membros or []
        self.presencas = presencas or []
        self.expectativas = expectativas or []
        self.visitantes = visitantes or []
        self.avisos = avisos or []
        self.materiais = materiais or []
        self.solicitacoes = solicitacoes or []
        self.pessoas = pessoas or []
        self.added: list = []
        self.deleted: list = []
        self.committed = False
        self.execute_count = 0
        self.executed_sql: list[str] = []
        self.health_result_row_counts: dict[str, int] = {}

    # -- predicate / ordering helpers (idênticos ao DiscipuloSession) -------
    @staticmethod
    def _eq_predicates(statement) -> dict[str, str]:
        preds: dict[str, str] = {}
        clause = getattr(statement, "whereclause", None)
        stack = [clause] if clause is not None else []
        while stack:
            node = stack.pop()
            left = getattr(node, "left", None)
            right = getattr(node, "right", None)
            operator = getattr(node, "operator", None)
            if (
                left is not None
                and right is not None
                and operator is operators.eq
            ):
                key = getattr(left, "key", None)
                value = getattr(right, "value", None)
                if key is not None and value is not None:
                    preds[key] = str(value)
                continue
            stack.extend(getattr(node, "clauses", []) or [])
        return preds

    @staticmethod
    def _in_predicates(statement) -> dict[str, set[str]]:
        preds: dict[str, set[str]] = {}
        clause = getattr(statement, "whereclause", None)
        stack = [clause] if clause is not None else []
        while stack:
            node = stack.pop()
            left = getattr(node, "left", None)
            right = getattr(node, "right", None)
            operator = getattr(node, "operator", None)
            if (
                left is not None
                and right is not None
                and operator is operators.in_op
            ):
                key = getattr(left, "key", None)
                values = getattr(right, "value", None)
                if key is not None and values is not None:
                    preds[key] = {str(value) for value in values}
                continue
            stack.extend(getattr(node, "clauses", []) or [])
        return preds

    @staticmethod
    def _ne_predicates(statement) -> dict[str, str]:
        preds: dict[str, str] = {}
        clause = getattr(statement, "whereclause", None)
        stack = [clause] if clause is not None else []
        while stack:
            node = stack.pop()
            left = getattr(node, "left", None)
            right = getattr(node, "right", None)
            operator = getattr(node, "operator", None)
            if (
                left is not None
                and right is not None
                and operator is operators.ne
            ):
                key = getattr(left, "key", None)
                value = getattr(right, "value", None)
                if key is not None and value is not None:
                    preds[key] = str(value)
                continue
            stack.extend(getattr(node, "clauses", []) or [])
        return preds

    def _filter(self, store, statement):
        eq_preds = self._eq_predicates(statement)
        in_preds = self._in_predicates(statement)
        ne_preds = self._ne_predicates(statement)
        return [
            o
            for o in store
            if all(str(getattr(o, k, None)) == v for k, v in eq_preds.items())
            and all(
                str(getattr(o, k, None)) in values
                for k, values in in_preds.items()
            )
            and all(str(getattr(o, k, None)) != v for k, v in ne_preds.items())
        ]

    @staticmethod
    def _wants_active(statement) -> bool:
        clause = getattr(statement, "whereclause", None)
        stack = [clause] if clause is not None else []
        while stack:
            node = stack.pop()
            left = getattr(node, "left", None)
            if left is not None and getattr(left, "key", None) == "ativo":
                return True
            stack.extend(getattr(node, "clauses", []) or [])
        return False

    @staticmethod
    def _order_specs(statement) -> list[tuple[str, bool]]:
        specs: list[tuple[str, bool]] = []
        for clause in getattr(statement, "_order_by_clauses", ()) or ():
            descending = getattr(clause, "modifier", None) is operators.desc_op
            element = getattr(clause, "element", clause)
            key = getattr(element, "key", None)
            if key is None:
                inner = getattr(element, "element", None)
                key = getattr(inner, "key", None)
            if key:
                specs.append((key, descending))
        return specs

    @staticmethod
    def _apply_order(rows, specs):
        rows = list(rows)
        for key, descending in reversed(specs):
            rows.sort(
                key=lambda r, k=key: (
                    getattr(r, k) is None,
                    getattr(r, k),
                ),
                reverse=descending,
            )
        return rows

    @staticmethod
    def _active(rows):
        return [r for r in rows if getattr(r, "ativo", True) is True]

    def _select(self, store, statement, *, active=False):
        rows = self._filter(store, statement)
        if active and self._wants_active(statement):
            rows = self._active(rows)
        rows = self._apply_order(rows, self._order_specs(statement))
        return _R(scalar=(rows[0] if rows else None), scalars=rows)

    def _select_group_count(
        self,
        store,
        statement,
        *,
        group_key: str,
        result_name: str,
        active: bool = False,
    ) -> _R:
        rows = self._filter(store, statement)
        if active and self._wants_active(statement):
            rows = self._active(rows)
        counts: dict[object, int] = {}
        for row in rows:
            key = getattr(row, group_key)
            counts[key] = counts.get(key, 0) + 1
        result_rows = list(counts.items())
        self.health_result_row_counts[result_name] = len(result_rows)
        return _R(rows=result_rows)

    def _select_distinct_ids(
        self,
        store,
        statement,
        *,
        key: str,
        result_name: str,
    ) -> _R:
        rows = self._filter(store, statement)
        seen = set()
        distinct_ids = []
        for row in rows:
            value = getattr(row, key)
            if value in seen:
                continue
            seen.add(value)
            distinct_ids.append(value)
        self.health_result_row_counts[result_name] = len(distinct_ids)
        return _R(scalars=distinct_ids)

    def _select_health_window(self, statement) -> _R:
        """Executa em memória o ``row_number`` do serviço de saúde."""
        params = statement.compile().params
        igreja_id = next(
            (
                value
                for key, value in params.items()
                if key.startswith("igreja_id")
            ),
            None,
        )
        cell_ids = next(
            (
                value
                for key, value in params.items()
                if key.startswith("celula_id")
            ),
            (),
        )
        cancelled_status = next(
            (
                value
                for key, value in params.items()
                if key.startswith("status")
            ),
            "cancelada",
        )
        window = next(
            (
                value
                for key, value in params.items()
                if key.startswith("health_rank")
            ),
            10,
        )

        allowed_cells = {str(cell_id) for cell_id in cell_ids}
        rows = [
            meeting
            for meeting in self.reunioes
            if str(meeting.igreja_id) == str(igreja_id)
            and str(meeting.celula_id) in allowed_cells
            and meeting.status != cancelled_status
        ]
        by_cell: dict[str, list] = {}
        for meeting in rows:
            by_cell.setdefault(str(meeting.celula_id), []).append(meeting)

        selected = []
        meeting_order = [("data", True), ("hora", True)]
        for meetings in by_cell.values():
            selected.extend(
                self._apply_order(meetings, meeting_order)[: int(window)]
            )
        selected = self._apply_order(selected, self._order_specs(statement))
        return _R(
            scalar=(selected[0] if selected else None),
            scalars=selected,
        )

    # -- execute ------------------------------------------------------------
    def execute(self, statement, params=None) -> _R:
        self.execute_count += 1
        sql = str(statement)
        self.executed_sql.append(sql)
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        name = descs[0].get("name") if descs else None

        if ent is AppUser and name == "pessoa_id":
            return _R(scalar=self.actor_pessoa_id)
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is Celula:
            return self._select(self.cells, statement)
        if ent is CelulaReuniao:
            if "row_number() over" in sql.lower():
                return self._select_health_window(statement)
            return self._select(self.reunioes, statement)
        if ent is CelulaMembro:
            if name == "celula_id" and "count(" in sql.lower():
                return self._select_group_count(
                    self.membros,
                    statement,
                    group_key="celula_id",
                    result_name="active_members",
                    active=True,
                )
            return self._select(self.membros, statement, active=True)
        if ent is CelulaPresenca:
            if name == "reuniao_id" and "count(" in sql.lower():
                return self._select_group_count(
                    self.presencas,
                    statement,
                    group_key="reuniao_id",
                    result_name="attendance",
                )
            return self._select(self.presencas, statement)
        if ent is CelulaExpectativaVisitante:
            if name == "reuniao_id" and "distinct" in sql.lower():
                return self._select_distinct_ids(
                    self.expectativas,
                    statement,
                    key="reuniao_id",
                    result_name="expected_visitors",
                )
            return self._select(self.expectativas, statement)
        if ent is CelulaVisitante:
            if name == "reuniao_id" and "distinct" in sql.lower():
                return self._select_distinct_ids(
                    self.visitantes,
                    statement,
                    key="reuniao_id",
                    result_name="registered_visitors",
                )
            return self._select(self.visitantes, statement)
        if ent is CelulaAviso:
            return self._select(self.avisos, statement, active=True)
        if ent is CelulaMaterial:
            return self._select(self.materiais, statement, active=True)
        if ent is CelulaSolicitacao:
            return self._select(self.solicitacoes, statement)
        if ent is Pessoa:
            return self._select(self.pessoas, statement)
        # set_config text / UserRole.papel projection.
        return _R(scalars=self.roles)

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)
        if isinstance(obj, CelulaAviso):
            self.avisos.append(obj)
        if isinstance(obj, CelulaMaterial):
            self.materiais.append(obj)

    def delete(self, obj) -> None:
        self.deleted.append(obj)

    def flush(self) -> None:
        pass

    def refresh(self, obj, **_kwargs) -> None:
        # Aceita with_for_update=... (SEC-4B): sem Postgres real não há lock.
        pass

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:  # pragma: no cover
        pass

    def close(self) -> None:  # pragma: no cover
        pass


# ===========================================================================
# Builders
# ===========================================================================
def make_cell(
    *,
    cell_id: str = CELL,
    igreja_id: str = TENANT,
    nome: str = "Célula A",
    lider_id: str | None = None,
    ativo: bool = True,
    endereco: str | None = None,
):
    return SimpleNamespace(
        id=cell_id,
        igreja_id=igreja_id,
        nome=nome,
        lider_id=lider_id,
        ativo=ativo,
        endereco=endereco,
    )


def make_member(
    *,
    member_id: str | None = None,
    igreja_id: str = TENANT,
    celula_id: str = CELL,
    pessoa_id: str = MEMBER_PESSOA,
    ativo: bool = True,
):
    return SimpleNamespace(
        id=member_id or str(uuid.uuid4()),
        igreja_id=igreja_id,
        celula_id=celula_id,
        pessoa_id=pessoa_id,
        ativo=ativo,
    )


def make_reuniao(
    *,
    reuniao_id: str,
    igreja_id: str = TENANT,
    celula_id: str = CELL,
    data: dt.date,
    hora: str = "19:30",
    status: str = "planejada",
    relatorio_status: str = "pendente",
    relatorio_snapshot: dict | None = None,
):
    return SimpleNamespace(
        id=reuniao_id,
        igreja_id=igreja_id,
        celula_id=celula_id,
        data=data,
        hora=hora,
        status=status,
        relatorio_status=relatorio_status,
        relatorio_snapshot=relatorio_snapshot,
    )


def make_presenca(
    *,
    presenca_id: str | None = None,
    igreja_id: str = TENANT,
    reuniao_id: str = REU,
    pessoa_id: str = MEMBER_PESSOA,
    estado: str = "compareceu",
):
    return SimpleNamespace(
        id=presenca_id or str(uuid.uuid4()),
        igreja_id=igreja_id,
        reuniao_id=reuniao_id,
        pessoa_id=pessoa_id,
        estado=estado,
    )


def make_expectativa(
    *,
    expectativa_id: str | None = None,
    igreja_id: str = TENANT,
    reuniao_id: str = REU,
    pessoa_id: str = MEMBER_PESSOA,
):
    return SimpleNamespace(
        id=expectativa_id or str(uuid.uuid4()),
        igreja_id=igreja_id,
        reuniao_id=reuniao_id,
        pessoa_id=pessoa_id,
    )


def make_visitante(
    *,
    visitante_id: str | None = None,
    igreja_id: str = TENANT,
    reuniao_id: str = REU,
):
    return SimpleNamespace(
        id=visitante_id or str(uuid.uuid4()),
        igreja_id=igreja_id,
        reuniao_id=reuniao_id,
    )


def make_aviso(
    *,
    aviso_id: str,
    igreja_id: str = TENANT,
    celula_id: str | None = None,
    origem: str = "central",
    escopo: str = "igreja",
    titulo: str = "Aviso",
    conteudo: str = "Conteúdo",
    ativo: bool = True,
    publicado_em: dt.datetime | None = None,
    notificado_em: dt.datetime | None = None,
):
    return SimpleNamespace(
        id=aviso_id,
        igreja_id=igreja_id,
        celula_id=celula_id,
        origem=origem,
        escopo=escopo,
        titulo=titulo,
        conteudo=conteudo,
        ativo=ativo,
        publicado_em=publicado_em or now_utc(),
        notificado_em=notificado_em,
        updated_at=None,
    )


def make_material(
    *,
    material_id: str,
    igreja_id: str = TENANT,
    titulo: str = "Material",
    descricao: str | None = None,
    url: str | None = "https://example.com/a.pdf",
    tipo: str | None = None,
    ativo: bool = True,
    publicado_em: dt.datetime | None = None,
):
    return SimpleNamespace(
        id=material_id,
        igreja_id=igreja_id,
        titulo=titulo,
        descricao=descricao,
        url=url,
        tipo=tipo,
        ativo=ativo,
        publicado_em=publicado_em or now_utc(),
        updated_at=None,
    )


def make_solicitacao(
    *,
    solicitacao_id: str | None = None,
    igreja_id: str = TENANT,
    tipo: str = "alterar_dia",
    status: str = "aguardando",
):
    return SimpleNamespace(
        id=solicitacao_id or str(uuid.uuid4()),
        igreja_id=igreja_id,
        tipo=tipo,
        status=status,
    )


def make_pessoa(*, pessoa_id: str, igreja_id: str = TENANT, nome: str = "Fulano"):
    return SimpleNamespace(id=pessoa_id, igreja_id=igreja_id, nome=nome)
