"""Auto-upgrade sincronizado pelo cron-worker (AUTOUPGRADE-BILLING-WORKER-1).

O trigger registra a operação durável (origin='autoupgrade') e NADA mais; o
worker é quem faz o PUT na assinatura Asaas EXISTENTE (nunca POST, nunca
setup) e só então aplica plano/limite/rótulo locais. Estes testes cobrem o
sweep `run_pending_plan_changes` com fakes offline:

  - PUT no MESMO id remoto; plano local só após confirmação; notificação só
    após a conclusão.
  - Falha remota → operação `reconciling`, plano local intacto, retry conclui
    por GET sem segundo PUT.
  - Descoberta ignora operações manuais/fechadas (o request do assinante é o
    dono das manuais) e respeita os binds REAIS da query.
  - Isolamento por tenant: sessão nova `mark_tenant_scoped` por operação,
    fechada sempre; a falha de uma igreja não interrompe as demais.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.db.models import BillingPlanChangeOperation, Subscription
from app.db.tenant_session import TENANT_IGREJA_KEY, TENANT_META_KEY
from app.services import billing_worker
from app.services.asaas import AsaasError, AsaasRejectedError
from app.services.billing_worker import (
    queue_autoupgrade_if_over_limit,
    run_pending_plan_changes,
)

from tests.conftest import FakeSession, _FakeResult

_IGREJA_A = uuid.uuid4()
_IGREJA_B = uuid.uuid4()
_SUB_ID = uuid.UUID("00000000-0000-0000-0000-00000000ab01")


def _op(**over) -> BillingPlanChangeOperation:
    fields = dict(
        id=uuid.uuid4(),
        subscription_id=_SUB_ID,
        asaas_subscription_id="sub_asaas_1",
        from_plano="ate_100",
        to_plano="101_200",
        to_preco=299.0,
        to_limite=200,
        origin="autoupgrade",
        status="prepared",
        # Espelha o trigger: toda operação de autoupgrade nasce com a entrega
        # da notificação pendente (durável).
        notify_status="pending",
    )
    fields.update(over)
    return BillingPlanChangeOperation(**fields)


def _sub(**over):
    base = dict(
        id=_SUB_ID,
        igreja_id=_IGREJA_A,
        plano="ate_100",
        limite=100,
        pessoas=None,  # contagem corrente (trigger); testes multi-tier setam
        asaas_subscription_id="sub_asaas_1",
        proxima_cobranca="2026-08-01",
    )
    base.update(over)
    return SimpleNamespace(**base)


class _WorkerAsaas:
    """Asaas do worker: só PUT/GET existem — qualquer criação EXPLODE."""

    def __init__(
        self,
        *,
        remote: dict | None = None,
        put_error: bool = False,
        put_rejected: bool = False,
    ) -> None:
        self.puts = 0
        self.gets = 0
        self.put_targets: list[str] = []
        self._remote = remote
        self._put_error = put_error
        self._put_rejected = put_rejected

    def update_subscription(self, subscription_id: str, *, valor: float, descricao: str):
        self.puts += 1
        self.put_targets.append(subscription_id)
        if self._put_rejected:
            raise AsaasRejectedError("Plano rejeitado definitivamente pelo Asaas")
        if self._put_error:
            raise AsaasError("timeout ambíguo depois do PUT")
        return {"id": subscription_id, "value": valor, "description": descricao}

    def get_subscription(self, subscription_id: str):
        self.gets += 1
        return self._remote

    def create_checkout(self, **kwargs):  # pragma: no cover - defesa
        raise AssertionError(
            "auto-upgrade nunca cria assinatura (POST /subscriptions)"
        )

    def create_one_time_charge(self, **kwargs):  # pragma: no cover - defesa
        raise AssertionError("auto-upgrade nunca emite cobrança de setup")


class _Discovery:
    """Sessão compartilhada da descoberta: aplica os binds REAIS da query.

    O pool recebe pares (operação, igreja_id); o filtro de origin/status vem
    dos parâmetros compilados do select — provando que a descoberta só enxerga
    operações autoupgrade ABERTAS, nunca as manuais nem as fechadas.
    """

    def __init__(self, pool: list[tuple[BillingPlanChangeOperation, uuid.UUID]]) -> None:
        self._pool = pool

    def execute(self, statement, params=None) -> _FakeResult:
        bound = statement.compile().params
        origin = next((v for k, v in bound.items() if k.startswith("origin")), None)
        notify = next(
            (v for k, v in bound.items() if k.startswith("notify_status")), None
        )
        # O IN(...) compila como UM bind expanding com a tupla inteira.
        statuses: list[str] = []
        for key, value in bound.items():
            if key.startswith("notify_status") or not key.startswith("status"):
                continue
            if isinstance(value, (list, tuple, set)):
                statuses.extend(value)
            else:
                statuses.append(value)
        rows = [
            (op.id, igreja_id)
            for op, igreja_id in self._pool
            if (origin is None or op.origin == origin)
            and (not statuses or op.status in statuses)
            and (notify is None or op.notify_status == notify)
        ]
        return _FakeResult(rows=rows)


class _WorkerSession(FakeSession):
    """Sessão tenant-scoped fake: aceita o seam real (`mark_tenant_scoped`)."""

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.info: dict = {}
        self.closed = False
        self.rolled_back = False

    def get(self, model, ident):
        if model is BillingPlanChangeOperation:
            pool = [
                *self.plan_changes,
                *(o for o in self.added if isinstance(o, BillingPlanChangeOperation)),
            ]
            return next((o for o in pool if str(o.id) == str(ident)), None)
        if model is Subscription:
            return self.subscription
        return None

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def _factory_queue(sessions: list[_WorkerSession]):
    queue = list(sessions)

    def factory() -> _WorkerSession:
        return queue.pop(0)

    factory.created = sessions  # type: ignore[attr-defined]
    return factory


def _spy_notify(monkeypatch, outcome: str = "sent") -> list:
    calls: list = []
    monkeypatch.setattr(
        billing_worker,
        "notify_autoupgrade",
        lambda db, igreja_id, evolution, *, plano=None: calls.append(igreja_id)
        or outcome,
    )
    return calls


def test_worker_completes_autoupgrade_via_put_on_existing_subscription(
    monkeypatch,
) -> None:
    op = _op()
    sub = _sub()
    igreja = SimpleNamespace(id=_IGREJA_A, plano="ate_100")
    tenant = _WorkerSession(subscription=sub, igreja=igreja, plan_changes=[op])
    asaas = _WorkerAsaas()
    notified = _spy_notify(monkeypatch)

    completed = run_pending_plan_changes(
        _Discovery([(op, _IGREJA_A)]),
        session_factory=_factory_queue([tenant]),
        asaas=asaas,
        evolution=object(),
    )

    assert completed == 1
    # PUT exatamente uma vez, no MESMO id remoto já rastreado.
    assert asaas.puts == 1
    assert asaas.put_targets == ["sub_asaas_1"]
    # Local só muda após a confirmação remota — e muda por inteiro.
    assert sub.plano == "101_200"
    assert sub.limite == 200
    assert igreja.plano == "101_200"
    assert op.status == "completed"
    assert sub.asaas_subscription_id == "sub_asaas_1"  # nunca outra recorrência
    # Notificação disparada UMA vez, depois da conclusão.
    assert notified == [_IGREJA_A]
    # Seam aplicado ANTES do processamento, sessão fechada ao fim.
    assert tenant.info[TENANT_IGREJA_KEY] == str(_IGREJA_A)
    assert tenant.info[TENANT_META_KEY]["source"] == "cron_billing"
    assert tenant.closed is True


def test_worker_put_failure_keeps_local_plan_and_operation_recoverable(
    monkeypatch,
) -> None:
    op = _op()
    sub = _sub()
    tenant = _WorkerSession(
        subscription=sub,
        igreja=SimpleNamespace(id=_IGREJA_A, plano="ate_100"),
        plan_changes=[op],
    )
    notified = _spy_notify(monkeypatch)

    completed = run_pending_plan_changes(
        _Discovery([(op, _IGREJA_A)]),
        session_factory=_factory_queue([tenant]),
        asaas=_WorkerAsaas(put_error=True),
        evolution=object(),
    )

    assert completed == 0
    # Plano local INTACTO; a operação fica recuperável para o próximo tick.
    assert sub.plano == "ate_100"
    assert sub.limite == 100
    assert op.status == "reconciling"
    assert notified == []
    assert tenant.closed is True


def test_worker_retry_reconciles_by_get_without_second_put(monkeypatch) -> None:
    op = _op(status="reconciling")
    sub = _sub()
    igreja = SimpleNamespace(id=_IGREJA_A, plano="ate_100")
    tenant = _WorkerSession(subscription=sub, igreja=igreja, plan_changes=[op])
    asaas = _WorkerAsaas(
        remote={
            "id": "sub_asaas_1",
            "value": 299.0,
            "description": "PastorAI — plano 101_200",
        }
    )
    notified = _spy_notify(monkeypatch)

    completed = run_pending_plan_changes(
        _Discovery([(op, _IGREJA_A)]),
        session_factory=_factory_queue([tenant]),
        asaas=asaas,
        evolution=object(),
    )

    assert completed == 1
    # O remoto já refletia o alvo: conclui por GET, sem repetir o PUT e sem
    # qualquer criação (os métodos de criação do fake explodem).
    assert asaas.puts == 0
    assert asaas.gets == 1
    assert op.status == "completed"
    assert sub.plano == "101_200"
    assert igreja.plano == "101_200"
    assert notified == [_IGREJA_A]


def test_worker_retries_the_put_when_remote_still_diverges(monkeypatch) -> None:
    # SELF-AUDIT-10 P1: o GET era a única saída de `reconciling` — e um remoto
    # divergente nunca mudaria sozinho. Agora o worker repete o PUT
    # idempotente com os alvos congelados e conclui.
    op = _op(status="reconciling")
    sub = _sub()
    igreja = SimpleNamespace(id=_IGREJA_A, plano="ate_100")
    tenant = _WorkerSession(subscription=sub, igreja=igreja, plan_changes=[op])
    asaas = _WorkerAsaas(remote={"id": "sub_asaas_1", "value": 149.0})
    notified = _spy_notify(monkeypatch)

    completed = run_pending_plan_changes(
        _Discovery([(op, _IGREJA_A)]),
        session_factory=_factory_queue([tenant]),
        asaas=asaas,
        evolution=object(),
    )

    assert completed == 1
    assert asaas.gets == 1  # reconcilia ANTES de escrever
    assert asaas.puts == 1  # exatamente um PUT, no mesmo id remoto
    assert asaas.put_targets == ["sub_asaas_1"]
    assert op.status == "completed"
    assert sub.plano == "101_200"
    assert igreja.plano == "101_200"
    assert notified == [_IGREJA_A]


def test_worker_processes_a_stuck_manual_plan_change(monkeypatch) -> None:
    # SELF-AUDIT-10 P1: a troca MANUAL cujo request morreu no PUT dependia de o
    # assinante repetir a solicitação — que as guardas do endpoint podem
    # recusar. O worker agora a descobre e conclui; sem notificar (manual nasce
    # com notify_status='skipped').
    manual = _op(origin="manual", status="reconciling", notify_status="skipped")
    sub = _sub()
    igreja = SimpleNamespace(id=_IGREJA_A, plano="ate_100")
    tenant = _WorkerSession(subscription=sub, igreja=igreja, plan_changes=[manual])
    asaas = _WorkerAsaas(remote={"id": "sub_asaas_1", "value": 149.0})
    notified = _spy_notify(monkeypatch)

    completed = run_pending_plan_changes(
        _Discovery([(manual, _IGREJA_A)]),
        session_factory=_factory_queue([tenant]),
        asaas=asaas,
        evolution=object(),
    )

    assert completed == 1
    assert asaas.puts == 1  # PUT in-place; os métodos de criação explodem
    assert manual.status == "completed"
    assert manual.origin == "manual"  # a origem é preservada
    assert manual.notify_status == "skipped"
    assert sub.plano == "101_200"
    assert notified == []  # troca manual NUNCA dispara aviso de auto-upgrade


def test_worker_requeues_growth_after_rejected_stuck_manual_change(
    monkeypatch,
) -> None:
    manual = _op(origin="manual", status="prepared", notify_status="skipped")
    sub = _sub(plano="ate_100", limite=100, pessoas=50)
    igreja = SimpleNamespace(id=_IGREJA_A, plano="ate_100")
    tenant = _WorkerSession(
        subscription=sub,
        igreja=igreja,
        plan_changes=[manual],
        planos=_ladder_catalog(),
    )
    tenant.pessoas_count = 250  # cresceu enquanto o claim manual estava aberto
    notified = _spy_notify(monkeypatch)

    completed = run_pending_plan_changes(
        _Discovery([(manual, _IGREJA_A)]),
        session_factory=_factory_queue([tenant]),
        asaas=_WorkerAsaas(put_rejected=True),
        evolution=object(),
    )

    assert completed == 0
    assert manual.status == "failed"
    queued = [
        o
        for o in tenant.added
        if isinstance(o, BillingPlanChangeOperation) and o.origin == "autoupgrade"
    ]
    assert len(queued) == 1
    assert queued[0].status == "prepared"
    assert queued[0].to_plano == "acima_201"
    assert sub.plano == "ate_100"
    assert igreja.plano == "ate_100"
    assert notified == []


def test_worker_does_not_loop_a_rejected_autoupgrade(monkeypatch) -> None:
    automatic = _op(origin="autoupgrade", status="prepared")
    sub = _sub(plano="ate_100", limite=100, pessoas=250)
    tenant = _WorkerSession(
        subscription=sub,
        igreja=SimpleNamespace(id=_IGREJA_A, plano="ate_100"),
        plan_changes=[automatic],
        planos=_ladder_catalog(),
    )
    tenant.pessoas_count = 250
    _spy_notify(monkeypatch)

    run_pending_plan_changes(
        _Discovery([(automatic, _IGREJA_A)]),
        session_factory=_factory_queue([tenant]),
        asaas=_WorkerAsaas(put_rejected=True),
        evolution=object(),
    )

    assert automatic.status == "failed"
    assert not [o for o in tenant.added if isinstance(o, BillingPlanChangeOperation)]


def test_worker_discovery_ignores_closed_operations(monkeypatch) -> None:
    finished = _op(status="completed", notify_status="sent")  # aviso já entregue
    failed = _op(status="failed", notify_status="pending")
    notified = _spy_notify(monkeypatch)
    asaas = _WorkerAsaas()
    factory = _factory_queue([])  # nenhuma sessão tenant deve ser criada

    completed = run_pending_plan_changes(
        _Discovery([(finished, _IGREJA_A), (failed, _IGREJA_A)]),
        session_factory=factory,
        asaas=asaas,
        evolution=object(),
    )

    assert completed == 0
    assert asaas.puts == 0
    assert asaas.gets == 0
    assert notified == []


def test_worker_skips_operation_closed_between_discovery_and_claim(
    monkeypatch,
) -> None:
    # A descoberta ainda viu a operação aberta, mas uma troca manual a
    # concluiu antes do claim do worker: recarregada no tenant, ela é pulada.
    stale_view = _op(status="prepared")
    current = _op(id=stale_view.id, status="completed")
    tenant = _WorkerSession(
        subscription=_sub(),
        igreja=SimpleNamespace(id=_IGREJA_A, plano="ate_100"),
        plan_changes=[current],
    )
    asaas = _WorkerAsaas()
    notified = _spy_notify(monkeypatch)

    completed = run_pending_plan_changes(
        _Discovery([(stale_view, _IGREJA_A)]),
        session_factory=_factory_queue([tenant]),
        asaas=asaas,
        evolution=object(),
    )

    assert completed == 0
    assert asaas.puts == 0
    assert asaas.gets == 0
    assert notified == []
    assert tenant.closed is True


def test_worker_tenant_failure_does_not_break_other_tenants(monkeypatch) -> None:
    op_a = _op()
    op_b = _op(
        id=uuid.uuid4(),
        subscription_id=uuid.UUID("00000000-0000-0000-0000-00000000ab02"),
        asaas_subscription_id="sub_asaas_2",
    )
    sub_b = _sub(
        id=op_b.subscription_id,
        igreja_id=_IGREJA_B,
        asaas_subscription_id="sub_asaas_2",
    )
    igreja_b = SimpleNamespace(id=_IGREJA_B, plano="ate_100")

    # Sessão da igreja A vem "suja" (pré-pinada em OUTRO tenant): o seam real
    # levanta TenantPinConflictError — a falha fica contida naquela iteração.
    broken = _WorkerSession(
        subscription=_sub(), igreja=SimpleNamespace(id=_IGREJA_A, plano="ate_100"),
        plan_changes=[op_a],
    )
    broken.info[TENANT_IGREJA_KEY] = str(uuid.uuid4())
    healthy = _WorkerSession(
        subscription=sub_b, igreja=igreja_b, plan_changes=[op_b]
    )
    asaas = _WorkerAsaas()
    notified = _spy_notify(monkeypatch)

    completed = run_pending_plan_changes(
        _Discovery([(op_a, _IGREJA_A), (op_b, _IGREJA_B)]),
        session_factory=_factory_queue([broken, healthy]),
        asaas=asaas,
        evolution=object(),
    )

    assert completed == 1
    assert broken.rolled_back is True
    assert broken.closed is True
    assert healthy.closed is True
    # Só a igreja saudável avançou — com o PUT no id remoto DELA.
    assert asaas.put_targets == ["sub_asaas_2"]
    assert op_a.status == "prepared"  # intacta, retry no próximo tick
    assert op_b.status == "completed"
    assert igreja_b.plano == "101_200"
    assert notified == [_IGREJA_B]


# ---------------------------------------------------------------------------
# CORRECTIVE-6 P2: entrega DURÁVEL da notificação — separada do financeiro.
# ---------------------------------------------------------------------------
def test_notification_failure_stays_pending_and_next_tick_delivers(
    monkeypatch,
) -> None:
    op = _op()
    sub = _sub()
    igreja = SimpleNamespace(id=_IGREJA_A, plano="ate_100")

    # Tick 1: troca CONCLUI, mas todos os envios falham -> segue 'pending'.
    failed_notify = _spy_notify(monkeypatch, outcome="retry")
    tick1 = _WorkerSession(subscription=sub, igreja=igreja, plan_changes=[op])
    completed = run_pending_plan_changes(
        _Discovery([(op, _IGREJA_A)]),
        session_factory=_factory_queue([tick1]),
        asaas=_WorkerAsaas(),
        evolution=object(),
    )
    assert completed == 1
    assert op.status == "completed"  # financeiro NUNCA é revertido pelo aviso
    assert op.notify_status == "pending"
    assert failed_notify == [_IGREJA_A]

    # Tick 2: a descoberta dedicada reencontra a operação COMPLETED pendente
    # de aviso e entrega — sem tocar o financeiro.
    ok_notify = _spy_notify(monkeypatch, outcome="sent")
    tick2 = _WorkerSession(subscription=sub, igreja=igreja, plan_changes=[op])
    completed2 = run_pending_plan_changes(
        _Discovery([(op, _IGREJA_A)]),
        session_factory=_factory_queue([tick2]),
        asaas=_WorkerAsaas(),
        evolution=object(),
    )
    assert completed2 == 0  # nada financeiro a concluir
    assert ok_notify == [_IGREJA_A]
    assert op.notify_status == "sent"

    # Tick 3: nada pendente — nenhuma chamada de notificação.
    quiet_notify = _spy_notify(monkeypatch, outcome="sent")
    completed3 = run_pending_plan_changes(
        _Discovery([(op, _IGREJA_A)]),
        session_factory=_factory_queue([]),
        asaas=_WorkerAsaas(),
        evolution=object(),
    )
    assert completed3 == 0
    assert quiet_notify == []


def test_notification_crash_keeps_pending_for_next_tick(monkeypatch) -> None:
    op = _op(status="completed")
    sub = _sub(plano="101_200", limite=200)

    def _boom(db, igreja_id, evolution, *, plano=None):
        raise RuntimeError("evolution indisponível")

    monkeypatch.setattr(billing_worker, "notify_autoupgrade", _boom)
    tick = _WorkerSession(
        subscription=sub,
        igreja=SimpleNamespace(id=_IGREJA_A, plano="101_200"),
        plan_changes=[op],
    )
    completed = run_pending_plan_changes(
        _Discovery([(op, _IGREJA_A)]),
        session_factory=_factory_queue([tick]),
        asaas=_WorkerAsaas(),
        evolution=object(),
    )
    assert completed == 0
    assert op.status == "completed"  # financeiro intacto
    assert op.notify_status == "pending"  # descobrível no próximo tick
    assert tick.closed is True


def test_retried_notification_uses_the_completed_operation_target(
    monkeypatch,
) -> None:
    """O plano corrente pode já estar um degrau à frente do aviso pendente."""
    op = _op(status="completed", to_plano="101_200", notify_status="pending")
    sub = _sub(plano="acima_201", limite=None)
    seen: list[tuple[uuid.UUID, str | None]] = []

    def _notify(db, igreja_id, evolution, *, plano=None):
        seen.append((igreja_id, plano))
        return "sent"

    monkeypatch.setattr(billing_worker, "notify_autoupgrade", _notify)
    tick = _WorkerSession(
        subscription=sub,
        igreja=SimpleNamespace(id=_IGREJA_A, plano="acima_201"),
        plan_changes=[op],
    )

    completed = run_pending_plan_changes(
        _Discovery([(op, _IGREJA_A)]),
        session_factory=_factory_queue([tick]),
        asaas=_WorkerAsaas(),
        evolution=object(),
    )

    assert completed == 0
    assert seen == [(_IGREJA_A, "101_200")]
    assert op.notify_status == "sent"


# ---------------------------------------------------------------------------
# CORRECTIVE-8 P1: porte cruzou MAIS de um degrau — o worker reavalia após
# concluir e persegue os degraus restantes no MESMO tick, sem depender de
# futura mutação de pessoas.
# ---------------------------------------------------------------------------
def test_multi_tier_upgrade_chases_second_step_in_same_tick(monkeypatch) -> None:
    op = _op()  # ate_100 -> 101_200 (criada pelo trigger coalescido)
    sub = _sub(pessoas=201)  # já cruzou DOIS tiers antes do primeiro tick
    igreja = SimpleNamespace(id=_IGREJA_A, plano="ate_100")
    catalogo = [
        SimpleNamespace(
            codigo="101_200", nome="101-200", preco_mensal=299.0,
            limite_pessoas=200, ativo=True,
        ),
        SimpleNamespace(
            codigo="acima_201", nome="201+", preco_mensal=499.0,
            limite_pessoas=None, ativo=True,
        ),
    ]
    tenant = _WorkerSession(
        subscription=sub, igreja=igreja, plan_changes=[op], planos=catalogo
    )
    asaas = _WorkerAsaas()
    notified = _spy_notify(monkeypatch)

    completed = run_pending_plan_changes(
        _Discovery([(op, _IGREJA_A)]),
        session_factory=_factory_queue([tenant]),
        asaas=asaas,
        evolution=object(),
    )

    assert completed == 1
    # DOIS PUTs no MESMO id remoto — um por degrau; nenhum POST (fake explode).
    assert asaas.puts == 2
    assert asaas.put_targets == ["sub_asaas_1", "sub_asaas_1"]
    # O degrau final é o alvo correto, com limite do catálogo.
    assert sub.plano == "acima_201"
    assert sub.limite is None
    assert igreja.plano == "acima_201"
    assert op.status == "completed"
    followup = next(
        o
        for o in tenant.added
        if isinstance(o, BillingPlanChangeOperation) and o.to_plano == "acima_201"
    )
    assert followup.status == "completed"
    assert followup.origin == "autoupgrade"
    assert float(followup.to_preco) == 499.0
    # Notificação por degrau concluído (cada plano tem marcador próprio).
    assert notified == [_IGREJA_A, _IGREJA_A]


def test_open_manual_change_has_precedence_over_autoupgrade(monkeypatch) -> None:
    # Uma troca MANUAL aberta tem precedência: o processamento da operação de
    # autoupgrade conflita (PlanChangeConflict) e NADA é atropelado — nem PUT,
    # nem plano local, nem a operação do assinante.
    op = _op()  # autoupgrade ate_100 -> 101_200 (do trigger)
    manual = _op(origin="manual", to_plano="acima_201", notify_status="skipped")
    sub = _sub(pessoas=201)
    tenant = _WorkerSession(
        subscription=sub,
        igreja=SimpleNamespace(id=_IGREJA_A, plano="ate_100"),
        plan_changes=[manual, op],  # manual é a operação ABERTA visível
    )
    _spy_notify(monkeypatch)
    asaas = _WorkerAsaas()

    completed = run_pending_plan_changes(
        _Discovery([(op, _IGREJA_A)]),
        session_factory=_factory_queue([tenant]),
        asaas=asaas,
        evolution=object(),
    )

    assert completed == 0
    assert asaas.puts == 0  # nenhuma escrita remota
    assert sub.plano == "ate_100"  # local intacto
    assert manual.status == "prepared"  # operação do assinante intocada
    assert tenant.closed is True


def test_inflight_notification_never_marks_sent(monkeypatch) -> None:
    op = _op(status="completed")
    sub = _sub(plano="101_200", limite=200)
    tenant = _WorkerSession(
        subscription=sub,
        igreja=SimpleNamespace(id=_IGREJA_A, plano="101_200"),
        plan_changes=[op],
    )
    # Reserva de OUTRO processo sem entrega comprovada: nunca vira 'sent'.
    _spy_notify(monkeypatch, outcome="inflight")

    completed = run_pending_plan_changes(
        _Discovery([(op, _IGREJA_A)]),
        session_factory=_factory_queue([tenant]),
        asaas=_WorkerAsaas(),
        evolution=object(),
    )

    assert completed == 0
    assert op.notify_status == "pending"  # descobrível no próximo tick


# ---------------------------------------------------------------------------
# SELF-AUDIT-10 P3: `queue_autoupgrade_if_over_limit` decidia pelo espelho
# `sub.pessoas` do objeto em memória — que, com `expire_on_commit=False`, é
# sempre o valor lido ANTES da chamada externa. Isso tornava a função INERTE
# justamente na corrida que ela existe para cobrir. Agora o porte vem da
# releitura canônica, e o worker conclui o degrau enfileirado.
# ---------------------------------------------------------------------------
def _ladder_catalog():
    return [
        SimpleNamespace(
            codigo="101_200", nome="101-200", preco_mensal=299.0,
            limite_pessoas=200, ativo=True,
        ),
        SimpleNamespace(
            codigo="acima_201", nome="201+", preco_mensal=499.0,
            limite_pessoas=None, ativo=True,
        ),
    ]


def test_queue_autoupgrade_reads_the_canonical_headcount_not_the_stale_mirror(
) -> None:
    sub = _sub(plano="101_200", limite=200, pessoas=50)  # espelho DEFASADO
    db = _WorkerSession(subscription=sub, planos=_ladder_catalog())
    db.pessoas_count = 250  # verdade canônica na tabela `pessoas`

    assert queue_autoupgrade_if_over_limit(db, sub) is True

    op = next(o for o in db.added if isinstance(o, BillingPlanChangeOperation))
    assert op.to_plano == "acima_201"
    assert op.origin == "autoupgrade"
    assert op.status == "prepared"
    assert sub.plano == "101_200"  # nada local muda no enfileiramento


def test_queue_autoupgrade_stays_quiet_when_the_plan_still_fits() -> None:
    sub = _sub(plano="101_200", limite=200, pessoas=50)
    db = _WorkerSession(subscription=sub, planos=_ladder_catalog())
    db.pessoas_count = 150  # dentro do limite

    assert queue_autoupgrade_if_over_limit(db, sub) is False
    assert not [o for o in db.added if isinstance(o, BillingPlanChangeOperation)]


def test_queue_autoupgrade_skips_inactive_next_tier() -> None:
    sub = _sub(plano="101_200", limite=200, pessoas=250)
    catalog = _ladder_catalog()
    catalog[-1].ativo = False
    db = _WorkerSession(subscription=sub, planos=catalog)
    db.pessoas_count = 250

    assert queue_autoupgrade_if_over_limit(db, sub) is False
    assert not [o for o in db.added if isinstance(o, BillingPlanChangeOperation)]


def test_queue_autoupgrade_advances_past_an_inactive_intermediate_tier() -> None:
    sub = _sub(plano="ate_100", limite=100, pessoas=50)
    catalog = _ladder_catalog()
    catalog[0].ativo = False
    db = _WorkerSession(subscription=sub, planos=catalog)
    db.pessoas_count = 250

    assert queue_autoupgrade_if_over_limit(db, sub) is True
    op = next(o for o in db.added if isinstance(o, BillingPlanChangeOperation))
    assert op.to_plano == "acima_201"
    assert op.to_limite is None


def test_worker_completes_the_queued_autoupgrade(monkeypatch) -> None:
    # Ponta a ponta: o endpoint enfileira (releitura canônica) e o worker
    # conclui pelo trilho durável — PUT in-place, nunca POST.
    sub = _sub(plano="101_200", limite=200, pessoas=50)
    igreja = SimpleNamespace(id=_IGREJA_A, plano="101_200")
    db = _WorkerSession(subscription=sub, igreja=igreja, planos=_ladder_catalog())
    db.pessoas_count = 250
    assert queue_autoupgrade_if_over_limit(db, sub) is True
    enfileirada = next(
        o for o in db.added if isinstance(o, BillingPlanChangeOperation)
    )

    tenant = _WorkerSession(
        subscription=sub,
        igreja=igreja,
        plan_changes=[enfileirada],
        planos=_ladder_catalog(),
    )
    tenant.pessoas_count = 250
    asaas = _WorkerAsaas()
    notified = _spy_notify(monkeypatch)

    completed = run_pending_plan_changes(
        _Discovery([(enfileirada, _IGREJA_A)]),
        session_factory=_factory_queue([tenant]),
        asaas=asaas,
        evolution=object(),
    )

    assert completed == 1
    assert asaas.puts == 1  # um PUT no id remoto já rastreado
    assert asaas.put_targets == ["sub_asaas_1"]
    assert enfileirada.status == "completed"
    assert sub.plano == "acima_201"
    assert sub.limite is None
    assert igreja.plano == "acima_201"
    assert notified == [_IGREJA_A]
