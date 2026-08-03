"""Shared test fixtures and lightweight fakes.

The Backend Core sprint is validated without a live database or Clerk tenant:
we override the DB session and Clerk client dependencies with in-memory fakes.
This keeps the auth/RBAC logic under test deterministic and offline.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from sqlalchemy.sql.dml import Update as _SqlUpdate

from app.db.models import (
    AgentConversationLog,
    AppUser,
    BillingPaymentOperation,
    BillingPlanChangeOperation,
    BillingSettings,
    BillingSubscriptionOperation,
    Igreja,
    PasswordResetToken,
    Plano,
    RolePermission,
    Subscription,
)
from app.services.clerk import ClerkAuthError, ClerkIdentity


def _plano_query_filters(statement) -> tuple[str | None, bool]:
    """Extrai os filtros (codigo, ativo) do WHERE compilado de uma query em `Plano`.

    Em vez de o fake ADIVINHAR o que a query filtra, compila o `Select` real
    (`literal_binds=True`) e lê o SQL — assim uma regressão que removesse
    `Plano.codigo == ...` do código de produção faria este helper devolver
    `codigo=None` (sem filtro), e o teste que pede um código errado com OUTRO
    plano ativo no catálogo pegaria a diferença (ver test_subscription_billing).
    """
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    codigo_match = re.search(r"planos\.codigo = '([^']*)'", sql)
    codigo = codigo_match.group(1) if codigo_match else None
    ativo_required = "planos.ativo IS true" in sql
    return codigo, ativo_required


# ---------------------------------------------------------------------------
# Fake SQLAlchemy session
# ---------------------------------------------------------------------------
class _FakeScalars:
    def __init__(self, items: list) -> None:
        self._items = items

    def all(self) -> list:
        return list(self._items)

    def first(self):
        # `find_any_open_operation` aceita mais de uma linha aberta (fontes
        # diferentes), então usa .scalars().first() em vez de one_or_none.
        return self._items[0] if self._items else None


class _FakeResult:
    def __init__(
        self, scalar=None, scalars_list=None, rows=None, one_row=None, rowcount=0
    ) -> None:
        self._scalar = scalar
        self._scalars_list = scalars_list or []
        self._rows = rows or []
        self._one_row = one_row
        # UPDATEs condicionais (claim_transition/finish_operation) decidem a
        # posse do passo pelo rowcount — o dispatch de Update o preenche.
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._scalars_list)

    def all(self) -> list:
        return list(self._rows)

    def one(self):
        # Usado pelo probe read-only de observabilidade (rls_observability).
        return self._one_row

    def first(self):
        # Usado pelo dedupe de notificação (notify_autoupgrade).
        return self._rows[0] if self._rows else self._one_row


class FakeSession:
    """Minimal session: routes selects by entity, ignores set_config text."""

    def __init__(
        self,
        app_user=None,
        roles: list[str] | None = None,
        role_permissions: list[tuple[str, str]] | None = None,
        reset_token=None,
        planos: list | None = None,
        igreja=None,
        billing_settings=None,
        subscription=None,
        operations: list | None = None,
        plan_changes: list | None = None,
        subscription_ops: list | None = None,
    ) -> None:
        self.app_user = app_user
        self.roles = roles or []
        # Linhas (papel, tela) da matriz do tenant, p/ testar require_screen.
        self.role_permissions = role_permissions or []
        # SEC-3B/MEDIO-003: linha de password_reset_tokens pro fluxo de reset.
        self.reset_token = reset_token
        # Catálogo `planos` (migration 0012) p/ testar checkout/catálogo de
        # subscription.py — o dispatch abaixo filtra por codigo/ativo lendo o
        # WHERE compilado de verdade (ver _plano_query_filters), não confia
        # cegamente no shape da query.
        self.planos = planos or []
        # Checkout resolve a taxa de setup pela igreja e pela configuração
        # global do master. Defaults explícitos deixam os testes isolados da
        # variável de ambiente legada.
        self.igreja = igreja if igreja is not None else getattr(app_user, "igreja", None)
        self.billing_settings = (
            billing_settings
            if billing_settings is not None
            else SimpleNamespace(id=1, setup_fee_default=0.0)
        )
        # Assinatura existente da igreja (GET /subscription e recovery de links).
        self.subscription = subscription
        # Operações duráveis de cobrança avulsa (setup / monthly_recovery).
        self.operations = operations or []
        # Operações duráveis de TROCA DE PLANO (PUT na assinatura existente).
        self.plan_changes = plan_changes or []
        # Intenções duráveis de CRIAÇÃO de assinatura (CORRECTIVE-6).
        self.subscription_ops = subscription_ops or []
        # Contagem canônica de `pessoas` da igreja (guarda de downgrade).
        self.pessoas_count = 0
        # Objetos passados a .add() (ex.: Subscription novo no checkout) —
        # permite o teste inspecionar o que o handler gravou (ex.: sub.limite).
        self.added: list = []
        self.commits = 0
        self.flushes = 0
        self.refresh_calls: list[tuple[object, object]] = []
        self.refresh_callback = None

    def _apply_conditional_update(self, statement) -> _FakeResult:
        """Aplica um UPDATE condicional de operação durável no pool em memória.

        As transições de estado (claim_transition/finish_operation) decidem a
        posse do passo pelo rowcount REAL: o fake lê os binds compilados —
        nomes puros são o SET; sufixados (`id_1`, `status_1`, expanding IN) são
        o WHERE — e só muta quem satisfaz id+status.
        """
        entity = statement.entity_description.get("entity")
        pools = {
            Igreja: [self.igreja] if self.igreja is not None else [],
            BillingPaymentOperation: self.operations,
            BillingPlanChangeOperation: self.plan_changes,
            BillingSubscriptionOperation: self.subscription_ops,
        }
        if entity not in pools:
            # Outros UPDATEs (ex.: gate da igreja no webhook) seguem inertes,
            # como antes deste dispatch existir.
            return _FakeResult()
        pool = [
            *pools[entity],
            *(o for o in self.added if isinstance(o, entity)),
        ]
        params = statement.compile().params
        set_values = {
            k: v for k, v in params.items() if re.fullmatch(r"[a-z_]+[a-z]", k)
        }
        where_id = next(
            (v for k, v in params.items() if re.fullmatch(r"id_\d+", k)), None
        )
        where_statuses: list[str] = []
        for key, value in params.items():
            if re.fullmatch(r"status_\d+(_\d+)?", key):
                if isinstance(value, (list, tuple, set)):
                    where_statuses.extend(value)
                else:
                    where_statuses.append(value)
        rowcount = 0
        for obj in pool:
            if where_id is not None and str(obj.id) != str(where_id):
                continue
            if where_statuses and getattr(obj, "status", None) not in where_statuses:
                continue
            for key, value in set_values.items():
                setattr(obj, key, value)
            rowcount += 1
        return _FakeResult(rowcount=rowcount)

    def execute(self, statement, params=None) -> _FakeResult:
        if isinstance(statement, _SqlUpdate):
            return self._apply_conditional_update(statement)
        # Contagem canônica de pessoas (guarda de downgrade por porte): o
        # select é `func.count()` com FROM em `pessoas` — sem entidade no
        # column_descriptions, então é reconhecido pelo texto compilado.
        sql_text = str(statement)
        if "count(" in sql_text.lower() and "pessoas" in sql_text.lower():
            return _FakeResult(scalar=self.pessoas_count)
        descriptions = getattr(statement, "column_descriptions", None)
        if not descriptions:
            # Cláusula text(): set_config(...) da RLS OU o probe read-only de
            # observabilidade do seam (select current_setting/current_igreja_id).
            sql = str(getattr(statement, "text", statement))
            if "current_igreja_id" in sql:
                igreja_id = (
                    getattr(self.app_user, "igreja_id", None)
                    if self.app_user
                    else None
                )
                return _FakeResult(
                    one_row=SimpleNamespace(
                        role="authenticated", igreja_id=igreja_id
                    )
                )
            return _FakeResult()
        entity = descriptions[0].get("entity")
        if entity is AppUser:
            return _FakeResult(scalar=self.app_user)
        if entity is RolePermission:
            return _FakeResult(rows=self.role_permissions)
        if entity is PasswordResetToken:
            return _FakeResult(scalar=self.reset_token)
        if entity is Igreja:
            return _FakeResult(scalar=self.igreja)
        if entity is BillingSettings:
            return _FakeResult(scalar=self.billing_settings)
        if entity is Subscription:
            return _FakeResult(scalar=self.subscription)
        if entity is BillingPlanChangeOperation:
            pool = [
                *self.plan_changes,
                *(
                    o
                    for o in self.added
                    if isinstance(o, BillingPlanChangeOperation)
                ),
            ]
            open_statuses = ("prepared", "processing", "reconciling")
            pool = [o for o in pool if o.status in open_statuses]
            return _FakeResult(scalar=pool[0] if pool else None, scalars_list=pool)
        if entity is BillingSubscriptionOperation:
            bound = statement.compile().params
            pool = [
                *self.subscription_ops,
                *(
                    o
                    for o in self.added
                    if isinstance(o, BillingSubscriptionOperation)
                ),
            ]
            key = next(
                (v for k, v in bound.items() if k.startswith("operation_key")), None
            )
            if key is not None:
                pool = [o for o in pool if o.operation_key == str(key)]
            elif any(k.startswith("status") for k in bound):
                open_statuses = ("prepared", "creating", "reconciling")
                pool = [o for o in pool if o.status in open_statuses]
            return _FakeResult(scalar=pool[0] if pool else None, scalars_list=pool)
        if entity is BillingPaymentOperation:
            # Operações duráveis de cobrança: filtra o pool (kwarg + added)
            # pelos binds REAIS da query (operation_key / asaas_payment_id /
            # purpose / cobrança-fonte / status). Os status vêm dos próprios
            # binds — `find_settled_recovery` procura `paid`, não os abertos.
            bound = statement.compile().params
            pool = [
                *self.operations,
                *(o for o in self.added if isinstance(o, BillingPaymentOperation)),
            ]
            key = next(
                (v for k, v in bound.items() if k.startswith("operation_key")), None
            )
            pay = next(
                (v for k, v in bound.items() if k.startswith("asaas_payment_id")), None
            )
            purpose = next(
                (v for k, v in bound.items() if k.startswith("purpose")), None
            )
            if key is not None:
                pool = [o for o in pool if o.operation_key == key]
            if pay is not None:
                pool = [o for o in pool if str(o.asaas_payment_id) == str(pay)]
            if purpose is not None:
                pool = [o for o in pool if o.purpose == purpose]
            # A cobrança-fonte é parte da identidade do claim: `IS NULL` não
            # gera bind, então o predicado é lido do SQL compilado.
            src = next(
                (v for k, v in bound.items() if k.startswith("source_payment_id")),
                None,
            )
            if "source_payment_id IS NULL" in str(statement):
                pool = [
                    o for o in pool if getattr(o, "source_payment_id", None) is None
                ]
            elif src is not None:
                pool = [
                    o
                    for o in pool
                    if str(getattr(o, "source_payment_id", None)) == str(src)
                ]
            statuses: list[str] = []
            for skey, svalue in bound.items():
                if not re.fullmatch(r"status_\d+(_\d+)?", skey):
                    continue
                if isinstance(svalue, (list, tuple, set)):
                    statuses.extend(svalue)
                else:
                    statuses.append(svalue)
            if statuses:
                pool = [o for o in pool if o.status in statuses]
            return _FakeResult(scalar=pool[0] if pool else None, scalars_list=pool)
        if entity is AgentConversationLog:
            # notify_autoupgrade (hoje chamado só pelo cron-worker) deduplica
            # por um marcador em agent_conversation_logs; devolver um marcador
            # existente encerra a notificação cedo, mantendo o teste offline
            # sem WhatsApp.
            return _FakeResult(rows=[("ja-notificado",)])
        if entity is Plano:
            codigo, ativo_required = _plano_query_filters(statement)
            candidatos = self.planos
            if codigo is not None:
                candidatos = [p for p in candidatos if getattr(p, "codigo", None) == codigo]
            if ativo_required:
                candidatos = [p for p in candidatos if getattr(p, "ativo", True)]
            return _FakeResult(
                scalar=candidatos[0] if candidatos else None, scalars_list=candidatos
            )
        # Anything else here is the UserRole.papel projection.
        return _FakeResult(scalars_list=self.roles)

    def add(self, obj) -> None:
        self.added.append(obj)

    def refresh(self, obj, *, with_for_update=None) -> None:
        self.refresh_calls.append((obj, with_for_update))
        if self.refresh_callback is not None:
            self.refresh_callback(obj, with_for_update)

    def commit(self) -> None:
        # In-memory: nada a persistir, mas o contador permite asserts de
        # persistência (ex.: recovery de links grava exatamente uma vez).
        self.commits += 1

    def flush(self) -> None:
        self.flushes += 1

    def rollback(self) -> None:  # pragma: no cover - in-memory, nothing to undo
        pass

    def close(self) -> None:  # pragma: no cover - nothing to release
        pass


# ---------------------------------------------------------------------------
# Fake Clerk client
# ---------------------------------------------------------------------------
class FakeClerk:
    def __init__(
        self,
        *,
        clerk_user_id: str = "clerk_user_1",
        login_result: tuple[str, str] | None = None,
        raise_verify: bool = False,
        raise_login: bool = False,
        invite_app_user_id: str | None = None,
        raise_invite: bool = False,
        created_clerk_id: str = "clerk_new_user",
        raise_create: bool = False,
    ) -> None:
        self._clerk_user_id = clerk_user_id
        self._login_result = login_result
        self._raise_verify = raise_verify
        self._raise_login = raise_login
        self._invite_app_user_id = invite_app_user_id
        self._raise_invite = raise_invite
        self._created_clerk_id = created_clerk_id
        self._raise_create = raise_create

    def verify_session_token(self, token: str) -> ClerkIdentity:
        if self._raise_verify:
            raise ClerkAuthError("invalid")
        return ClerkIdentity(
            clerk_user_id=self._clerk_user_id, claims={"sub": self._clerk_user_id}
        )

    def authenticate_password(self, email: str, password: str) -> tuple[str, str]:
        if self._raise_login:
            raise ClerkAuthError("invalid")
        return self._login_result or ("session_token_abc", self._clerk_user_id)

    # ---- Invite / activation (convite ponta a ponta) ------------------------
    def mint_invite_token(self, app_user_id: str) -> str:
        return f"invite-token-{app_user_id}"

    def verify_invite_token(self, token: str) -> str:
        if self._raise_invite:
            raise ClerkAuthError("invalid invite")
        return self._invite_app_user_id or "00000000-0000-0000-0000-0000000000a1"

    def create_user(self, email: str, password: str) -> str:
        if self._raise_create:
            raise ClerkAuthError("create failed")
        return self._created_clerk_id

    def set_user_password(self, clerk_user_id: str, password: str) -> None:
        pass


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def make_app_user(
    *,
    clerk_user_id: str = "clerk_user_1",
    igreja_status: str = "ativa",
    email: str = "pastor@igrejapiloto.com",
    nome: str = "Pastor Piloto",
    status: str = "ativo",
    chat_nome: str | None = None,
    dono_id: str | None = "00000000-0000-0000-0000-0000000000a1",
    password_changed_at=None,
):
    """Build an app_user stand-in compatible with the deps/router access.

    Por padrão o usuário É o dono da igreja (dono_id == seu id, #4), para que os
    testes de telas admin que viraram owner-gated (Assinatura) sigam passando.
    Passe ``dono_id=None`` (ou outro id) para simular um admin que NÃO é o dono.
    ``password_changed_at`` (SEC-3A/MEDIO-002) default None = comportamento
    legado (nenhuma sessão é invalidada); os testes dedicados de invalidação
    passam um datetime explícito.
    """
    igreja = SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        nome="Igreja Piloto",
        status=igreja_status,
        dono_id=dono_id,
        logo_path=None,
        setup_fee_override=None,
    )
    return SimpleNamespace(
        id="00000000-0000-0000-0000-0000000000a1",
        igreja_id="00000000-0000-0000-0000-000000000001",
        clerk_user_id=clerk_user_id,
        email=email,
        nome=nome,
        status=status,
        chat_nome=chat_nome,
        igreja=igreja,
        password_changed_at=password_changed_at,
    )


@pytest.fixture
def app():
    from app.main import create_app

    return create_app()


@pytest.fixture(autouse=True)
def _rate_limit_auth_disabled(monkeypatch):
    """Rate limiting de auth (ALTO-002) fica OFF por padrão na suíte.

    Sem isso, todo teste que bate em /auth/login etc. tentaria falar com um
    Redis real (pode nem existir na máquina, e se existir acumularia contador
    entre execuções da suíte). Os testes dedicados de rate limit ligam a flag
    e injetam um Redis fake via dependency override — ver test_rate_limit.py.
    """
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_auth_enabled", False, raising=False)
    yield


@pytest.fixture(autouse=True)
def _celulas_requests_enabled(monkeypatch):
    """O fluxo de Solicitações de célula nasce atrás de flag OFF (rollout).

    Sob teste a feature está SOB TESTE, então liga por padrão; o teste dedicado do
    gate desliga explicitamente (monkeypatch para False no corpo). Afeta só o gate
    de escrita de Células — inócuo para o resto da suíte.
    """
    from app.config import get_settings

    monkeypatch.setattr(
        get_settings(), "celulas_requests_enabled", True, raising=False
    )
    yield


@pytest.fixture(autouse=True)
def _seam_fake_session_info(monkeypatch):
    """Garante `session.info` nas fake sessions ao atravessar o seam (PR3-A).

    O seam de tenant grava sua marca em ``session.info`` (mark_tenant_scoped /
    mark_cross_tenant, chamados por deps.get_current_user / get_platform_admin).
    Uma ``Session`` real do SQLAlchemy sempre expõe ``.info``; as fake sessions
    espalhadas pela suíte (duck-types) não. Em vez de editar cada uma das ~25
    classes-fake, envolvemos os pontos de entrada do seam usados por ``deps`` num
    único lugar: se o objeto não tiver ``.info``, injetamos um dict e seguimos
    para a função REAL (a lógica de marcação/pinning continua sendo exercitada).
    O código de produção fica intocado — uma Session real nunca cai neste ramo.
    """
    import app.deps as deps

    def _ensure_info(session) -> None:
        if not hasattr(session, "info"):
            try:
                session.info = {}
            except (AttributeError, TypeError):  # pragma: no cover - Session real
                pass

    real_scoped = deps.mark_tenant_scoped
    real_cross = deps.mark_cross_tenant

    def _scoped(session, *args, **kwargs):
        _ensure_info(session)
        return real_scoped(session, *args, **kwargs)

    def _cross(session, *args, **kwargs):
        _ensure_info(session)
        return real_cross(session, *args, **kwargs)

    monkeypatch.setattr(deps, "mark_tenant_scoped", _scoped)
    monkeypatch.setattr(deps, "mark_cross_tenant", _cross)
    yield
