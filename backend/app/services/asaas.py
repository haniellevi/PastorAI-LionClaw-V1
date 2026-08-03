"""Asaas billing client (US-36 / RF-42).

Creates a subscription checkout with a one-time setup fee and exposes a helper
to validate inbound webhook tokens. Asaas authenticates API calls with an
`access_token` header and signs webhooks with a shared `asaas-access-token`
header that we compare against `ASAAS_WEBHOOK_TOKEN`.

The client never raises raw HTTP errors to callers: failures are normalized to
`AsaasError` and logged without leaking the API key.
"""

from __future__ import annotations

import datetime as dt
import hmac
import logging
from collections.abc import Callable
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings, get_settings
from app.services.outbound_guard import external_sends_allowed, log_suppressed

logger = logging.getLogger("pastorai.asaas")
MIN_UNDEFINED_PAYMENT_VALUE = 5.0
# Descrição EXATA da cobrança avulsa de setup — também é o critério de
# reconciliação de setups legados no webhook (registros pré-migration).
SETUP_CHARGE_DESCRIPTION = "PastorAI — taxa de setup"
# Cobrança avulsa que recupera uma mensalidade ESTORNADA (nunca uma assinatura).
MONTHLY_RECOVERY_DESCRIPTION = "PastorAI — recuperação de mensalidade"
_SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")


def _sao_paulo_today(now: dt.datetime | None = None) -> dt.date:
    """Data civil do produto, independente do fuso configurado no host."""
    instant = now or dt.datetime.now(_SAO_PAULO_TZ)
    return instant.astimezone(_SAO_PAULO_TZ).date()

# Map Asaas event/payment status to our subscription_status enum (RF-42).
_STATUS_MAP = {
    "CONFIRMED": "ativa",
    "RECEIVED": "ativa",
    "RECEIVED_IN_CASH": "ativa",
    "PAYMENT_CONFIRMED": "ativa",
    "PAYMENT_RECEIVED": "ativa",
    "ACTIVE": "ativa",
    "PENDING": "pendente",
    "AWAITING_PAYMENT": "pendente",
    "PAYMENT_CREATED": "pendente",
    "OVERDUE": "inadimplente",
    "PAYMENT_OVERDUE": "inadimplente",
    # Reversões chegam como evento (PAYMENT_*) ou como payment.status cru
    # (REFUNDED/DELETED) — ambos derrubam a assinatura para inadimplente.
    "PAYMENT_DELETED": "inadimplente",
    "PAYMENT_REFUNDED": "inadimplente",
    "DELETED": "inadimplente",
    "REFUNDED": "inadimplente",
}


def map_payment_status(raw_status: str | None) -> str | None:
    """Translate an Asaas event/payment status into a subscription_status."""
    if not raw_status:
        return None
    return _STATUS_MAP.get(raw_status.strip().upper())


# Estorno/cancelamento: a cobrança deixa de existir para pagamento — diferente
# de OVERDUE (atrasada, mas ainda pagável pela mesma fatura). O TIPO importa:
# 'deleted' permite restaurar a mesma cobrança; 'refunded' não.
_REVERSAL_KINDS = {
    "REFUNDED": "refunded",
    "PAYMENT_REFUNDED": "refunded",
    "DELETED": "deleted",
    "PAYMENT_DELETED": "deleted",
}


def payment_reversal_kind(raw_status: str | None) -> str | None:
    """'refunded' | 'deleted' quando o evento/status indica reversão; senão None."""
    if not raw_status:
        return None
    return _REVERSAL_KINDS.get(raw_status.strip().upper())


def verify_webhook_token(expected: str, provided: str | None) -> bool:
    """Validate the Asaas webhook token in constant time."""
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided.strip())


def payment_invoice_url(payment: dict | None) -> str | None:
    """Public payment page of an Asaas payment payload (API or webhook)."""
    if not isinstance(payment, dict):
        return None
    value = payment.get("invoiceUrl") or payment.get("bankSlipUrl")
    return str(value) if value else None


class AsaasError(Exception):
    """Raised when an Asaas API call fails or the client is misconfigured."""


def subscription_description(plano: str) -> str:
    """Descrição canônica da assinatura recorrente de um plano.

    Fonte ÚNICA: o checkout, a troca de plano e a reconciliação usam a MESMA
    string — a descrição faz parte da identidade do alvo (dois planos podem
    ter o mesmo preço, então valor sozinho não distingue um PUT aplicado de
    um PUT perdido).
    """
    return f"PastorAI — plano {plano}"


class AsaasRejectedError(AsaasError):
    """Rejeição DEFINITIVA do Asaas (HTTP 4xx): nada foi criado.

    Diferente do timeout/5xx (resultado ambíguo → reconciliação), uma resposta
    4xx prova que o recurso não existe no Asaas — o chamador pode devolver a
    intenção a `prepared` e permitir um retry normal após correção dos dados.
    Usada apenas no caminho de criação de assinatura (CORRECTIVE-7).
    """


@dataclass(frozen=True)
class CheckoutResult:
    """Outcome of creating a subscription checkout.

    A taxa de setup NÃO é criada aqui: ela nasce como operação durável
    (billing_payment_operations) no router, com externalReference exclusiva —
    retry-safe por reconciliação.
    """

    customer_id: str
    subscription_id: str
    invoice_url: str | None
    status: str  # ativa | pendente | inadimplente
    # ID da primeira cobrança mensal (quando o Asaas já a gerou) — persistido
    # para recuperar/atualizar o link por cobrança exata nos ciclos seguintes.
    invoice_payment_id: str | None = None


class AsaasClient:
    """Thin HTTP client around the Asaas customer/subscription endpoints."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _require_config(self) -> tuple[str, str]:
        base_url = self._settings.asaas_api_url
        api_key = self._settings.asaas_api_key
        if not base_url or not api_key:
            raise AsaasError("Asaas API is not configured")
        return base_url.rstrip("/"), api_key

    def _headers(self, api_key: str) -> dict[str, str]:
        return {
            "access_token": api_key,
            "Content-Type": "application/json",
            "User-Agent": "PastorAI/1.0 (Python; billing)",
        }

    def create_checkout(
        self,
        *,
        nome: str,
        email: str,
        plano: str,
        valor: float,
        ciclo: str = "MONTHLY",
        cpf_cnpj: str | None = None,
        external_reference: str | None = None,
        on_customer_resolved: Callable[[str], None] | None = None,
        on_subscription_created: Callable[[str, str], None] | None = None,
    ) -> CheckoutResult:
        """Create (or reuse) a customer and open the recurring subscription.

        ``on_customer_resolved(customer_id)`` is invoked as soon as the
        customer exists, BEFORE the subscription POST — the caller persists it
        there, so a later ambiguous failure is known to belong to the
        subscription POST (and must be reconciled, never blindly retried).
        ``on_subscription_created(customer_id, subscription_id)`` is invoked
        IMMEDIATELY after the subscription POST succeeds, before any further
        remote call — the caller persists the tracking there, so a later
        failure can never leave a live Asaas subscription without a local link
        (a retry would duplicate it). A taxa de setup NÃO é criada aqui: o
        router a emite como operação durável retry-safe.
        """
        if not external_sends_allowed(self._settings):
            log_suppressed("Asaas", "create_checkout")
            return CheckoutResult(
                customer_id="sandbox",
                subscription_id="sandbox",
                invoice_url=None,
                status="pendente",
                invoice_payment_id=None,
            )
        if not cpf_cnpj:
            raise AsaasError("CPF ou CNPJ é obrigatório para o checkout")
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)

        try:
            with httpx.Client(base_url=base_url, timeout=20.0) as client:
                customer_id = self._ensure_customer(
                    client, headers, nome=nome, email=email, cpf_cnpj=cpf_cnpj
                )
                if on_customer_resolved is not None:
                    on_customer_resolved(customer_id)
                sub = self._create_subscription(
                    client,
                    headers,
                    customer_id=customer_id,
                    valor=valor,
                    ciclo=ciclo,
                    descricao=subscription_description(plano),
                    external_reference=external_reference,
                )
                subscription_id = str(sub["id"])
                if on_subscription_created is not None:
                    on_subscription_created(customer_id, subscription_id)
                try:
                    monthly_payment = self._latest_subscription_payment(
                        client, headers, subscription_id=subscription_id
                    )
                except (httpx.HTTPError, ValueError, KeyError):
                    # Leitura OPCIONAL: falha aqui não pode abortar um checkout
                    # cuja assinatura já existe no Asaas — o GET /subscription
                    # recupera o link depois pelos ids persistidos.
                    logger.warning(
                        "Asaas first-payment lookup failed; continuing without link"
                    )
                    monthly_payment = None
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            logger.warning("Asaas checkout failed: HTTP %s", code)
            if 400 <= code < 500:
                # Resposta DEFINITIVA: o Asaas processou e rejeitou — nada foi
                # criado. O chamador pode voltar a intenção para `prepared`.
                raise AsaasRejectedError(
                    "O Asaas rejeitou os dados do checkout"
                ) from exc
            raise AsaasError("Falha ao criar checkout no Asaas") from exc
        except httpx.HTTPError as exc:
            # Timeout/erro de transporte: resultado AMBÍGUO — só reconciliação.
            logger.warning("Asaas checkout failed: %s", type(exc).__name__)
            raise AsaasError("Falha ao criar checkout no Asaas") from exc
        except (ValueError, KeyError) as exc:
            logger.warning("Unexpected Asaas response shape")
            raise AsaasError("Resposta inesperada do Asaas") from exc

        status = map_payment_status(
            monthly_payment.get("status") if monthly_payment else None
        ) or map_payment_status(sub.get("status")) or "pendente"
        return CheckoutResult(
            customer_id=customer_id,
            subscription_id=subscription_id,
            invoice_url=payment_invoice_url(monthly_payment),
            status=status,
            invoice_payment_id=(
                str(monthly_payment["id"])
                if monthly_payment and monthly_payment.get("id")
                else None
            ),
        )

    def get_subscription_payment(self, subscription_id: str) -> dict | None:
        """Most recent payment payload of an existing subscription.

        Read-only (never creates charges): used by checkout resume and link
        recovery. Returns None when Asaas has not generated the payment yet or
        sends are sandboxed in this environment.
        """
        if not external_sends_allowed(self._settings):
            log_suppressed("Asaas", "get_subscription_payment")
            return None
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        try:
            with httpx.Client(base_url=base_url, timeout=20.0) as client:
                return self._latest_subscription_payment(
                    client, headers, subscription_id=subscription_id
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "Asaas subscription payment lookup failed: %s", type(exc).__name__
            )
            raise AsaasError("Falha ao consultar a assinatura no Asaas") from exc
        except (ValueError, KeyError) as exc:
            logger.warning("Unexpected Asaas response shape")
            raise AsaasError("Resposta inesperada do Asaas") from exc

    def get_subscription_invoice_url(self, subscription_id: str) -> str | None:
        """Public payment page of a subscription's first charge (read-only)."""
        return payment_invoice_url(self.get_subscription_payment(subscription_id))

    def get_subscription(self, subscription_id: str) -> dict | None:
        """Full payload of an existing subscription (read-only reconciliation)."""
        if not external_sends_allowed(self._settings):
            log_suppressed("Asaas", "get_subscription")
            return None
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        try:
            with httpx.Client(base_url=base_url, timeout=20.0) as client:
                resp = client.get(f"/subscriptions/{subscription_id}", headers=headers)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Asaas subscription lookup failed: %s", type(exc).__name__)
            raise AsaasError("Falha ao consultar a assinatura no Asaas") from exc
        except (ValueError, KeyError) as exc:
            logger.warning("Unexpected Asaas response shape")
            raise AsaasError("Resposta inesperada do Asaas") from exc
        return body if isinstance(body, dict) else None

    def update_subscription(
        self, subscription_id: str, *, valor: float, descricao: str
    ) -> dict | None:
        """Update the EXISTING recurring subscription in place (plan change).

        PUT /subscriptions/{id} com ``updatePendingPayments=false``: cobranças
        já emitidas ficam intocadas e o novo valor vale a partir do próximo
        ciclo — nunca cria outra recorrência. Returns None when external sends
        are sandboxed.
        """
        if not external_sends_allowed(self._settings):
            log_suppressed("Asaas", "update_subscription")
            return None
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        payload: dict[str, object] = {
            "value": valor,
            "description": descricao,
            "updatePendingPayments": False,
        }
        try:
            with httpx.Client(base_url=base_url, timeout=20.0) as client:
                resp = client.put(
                    f"/subscriptions/{subscription_id}", headers=headers, json=payload
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            logger.warning("Asaas subscription update failed: HTTP %s", code)
            if 400 <= code < 500:
                # DEFINITIVO: o PUT foi processado e rejeitado — o remoto
                # ficou como estava; o chamador pode fechar a operação.
                raise AsaasRejectedError(
                    "O Asaas rejeitou a atualização da assinatura"
                ) from exc
            raise AsaasError("Falha ao atualizar a assinatura no Asaas") from exc
        except httpx.HTTPError as exc:
            # Timeout/transporte: resultado AMBÍGUO — reconciliação por GET.
            logger.warning("Asaas subscription update failed: %s", type(exc).__name__)
            raise AsaasError("Falha ao atualizar a assinatura no Asaas") from exc
        except (ValueError, KeyError) as exc:
            logger.warning("Unexpected Asaas response shape")
            raise AsaasError("Resposta inesperada do Asaas") from exc
        return body if isinstance(body, dict) else None

    def create_one_time_charge(
        self,
        *,
        customer_id: str,
        valor: float,
        description: str,
        external_reference: str,
    ) -> dict | None:
        """One-time charge (setup / recuperação mensal) on an EXISTING customer.

        SEMPRE chamado por uma operação durável: ``external_reference`` é a
        operation_key exclusiva persistida antes do POST — o retry reconcilia
        por ela em vez de repetir a chamada. Returns None when external sends
        are sandboxed.
        """
        if not external_sends_allowed(self._settings):
            log_suppressed("Asaas", "create_one_time_charge")
            return None
        if 0 < valor < MIN_UNDEFINED_PAYMENT_VALUE:
            # Validação LOCAL que comprova a não-criação: rejeição definitiva.
            raise AsaasRejectedError("A cobrança precisa ser de pelo menos R$ 5,00")
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        try:
            with httpx.Client(base_url=base_url, timeout=20.0) as client:
                return self._create_one_time_charge(
                    client,
                    headers,
                    customer_id=customer_id,
                    valor=valor,
                    description=description,
                    external_reference=external_reference,
                )
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            logger.warning("Asaas one-time charge failed: HTTP %s", code)
            if 400 <= code < 500:
                # DEFINITIVO: o Asaas processou e rejeitou — nada foi criado.
                raise AsaasRejectedError(
                    "O Asaas rejeitou a cobrança"
                ) from exc
            raise AsaasError("Falha ao criar a cobrança no Asaas") from exc
        except httpx.HTTPError as exc:
            # Timeout/transporte: resultado AMBÍGUO — só reconciliação.
            logger.warning("Asaas one-time charge failed: %s", type(exc).__name__)
            raise AsaasError("Falha ao criar a cobrança no Asaas") from exc
        except (ValueError, KeyError) as exc:
            logger.warning("Unexpected Asaas response shape")
            raise AsaasError("Resposta inesperada do Asaas") from exc

    def find_subscriptions_by_external_reference(
        self, external_reference: str
    ) -> list[dict]:
        """All subscriptions carrying this externalReference (reconciliation).

        Read-only: caminho de RECONCILIAÇÃO da criação de assinatura — uma
        resposta perdida de POST /subscriptions é resolvida procurando pela
        operation_key da intenção durável (a externalReference localiza, mas
        NÃO é garantia de idempotência do POST), nunca repetindo o POST.
        """
        if not external_sends_allowed(self._settings):
            log_suppressed("Asaas", "find_subscriptions_by_external_reference")
            return []
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        try:
            with httpx.Client(base_url=base_url, timeout=20.0) as client:
                resp = client.get(
                    "/subscriptions",
                    headers=headers,
                    params={"externalReference": external_reference},
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Asaas subscription search failed: %s", type(exc).__name__)
            raise AsaasError("Falha ao consultar assinaturas no Asaas") from exc
        except (ValueError, KeyError) as exc:
            logger.warning("Unexpected Asaas response shape")
            raise AsaasError("Resposta inesperada do Asaas") from exc
        subscriptions = body.get("data") if isinstance(body, dict) else None
        if not isinstance(subscriptions, list):
            return []
        return [s for s in subscriptions if isinstance(s, dict)]

    def find_payments_by_external_reference(self, external_reference: str) -> list[dict]:
        """All payments carrying this externalReference (reconciliation).

        Read-only: é o caminho de RECONCILIAÇÃO das operações duráveis — uma
        resposta perdida de POST /payments é resolvida procurando a cobrança
        pela operation_key, nunca repetindo o POST às cegas.
        """
        if not external_sends_allowed(self._settings):
            log_suppressed("Asaas", "find_payments_by_external_reference")
            return []
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        try:
            with httpx.Client(base_url=base_url, timeout=20.0) as client:
                resp = client.get(
                    "/payments",
                    headers=headers,
                    params={"externalReference": external_reference},
                )
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Asaas payment search failed: %s", type(exc).__name__)
            raise AsaasError("Falha ao consultar cobranças no Asaas") from exc
        except (ValueError, KeyError) as exc:
            logger.warning("Unexpected Asaas response shape")
            raise AsaasError("Resposta inesperada do Asaas") from exc
        payments = body.get("data") if isinstance(body, dict) else None
        if not isinstance(payments, list):
            return []
        return [p for p in payments if isinstance(p, dict)]

    def get_payment(self, payment_id: str) -> dict | None:
        """Full payload of an existing payment (read-only)."""
        if not external_sends_allowed(self._settings):
            log_suppressed("Asaas", "get_payment")
            return None
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        try:
            with httpx.Client(base_url=base_url, timeout=20.0) as client:
                resp = client.get(f"/payments/{payment_id}", headers=headers)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Asaas payment lookup failed: %s", type(exc).__name__)
            raise AsaasError("Falha ao consultar a cobrança no Asaas") from exc
        except (ValueError, KeyError) as exc:
            logger.warning("Unexpected Asaas response shape")
            raise AsaasError("Resposta inesperada do Asaas") from exc
        return body if isinstance(body, dict) else None

    def get_payment_invoice_url(self, payment_id: str) -> str | None:
        """Public payment page of an existing one-time charge (read-only)."""
        return payment_invoice_url(self.get_payment(payment_id))

    def restore_payment(self, payment_id: str) -> dict | None:
        """Restore a DELETED payment via the official endpoint.

        Only meaningful for excluded (not refunded) charges. The caller checks
        the current payment state first — restore is NOT assumed idempotent.
        Returns None when external sends are sandboxed.
        """
        if not external_sends_allowed(self._settings):
            log_suppressed("Asaas", "restore_payment")
            return None
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        try:
            with httpx.Client(base_url=base_url, timeout=20.0) as client:
                resp = client.post(f"/payments/{payment_id}/restore", headers=headers)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Asaas payment restore failed: %s", type(exc).__name__)
            raise AsaasError("Falha ao restaurar a cobrança no Asaas") from exc
        except (ValueError, KeyError) as exc:
            logger.warning("Unexpected Asaas response shape")
            raise AsaasError("Resposta inesperada do Asaas") from exc
        return body if isinstance(body, dict) else None

    # ---- helpers ------------------------------------------------------------
    def _ensure_customer(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        *,
        nome: str,
        email: str,
        cpf_cnpj: str,
    ) -> str:
        """Find an existing customer by document or create a new one."""
        resp = client.get("/customers", headers=headers, params={"cpfCnpj": cpf_cnpj})
        resp.raise_for_status()
        data = resp.json()
        existing = (data.get("data") or []) if isinstance(data, dict) else []
        if existing:
            return str(existing[0]["id"])

        payload: dict[str, object] = {"name": nome, "email": email, "cpfCnpj": cpf_cnpj}
        resp = client.post("/customers", headers=headers, json=payload)
        resp.raise_for_status()
        return str(resp.json()["id"])

    def _create_subscription(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        *,
        customer_id: str,
        valor: float,
        ciclo: str,
        descricao: str,
        external_reference: str | None,
    ) -> dict:
        payload: dict[str, object] = {
            "customer": customer_id,
            "billingType": "UNDEFINED",
            "value": valor,
            "cycle": ciclo,
            # A primeira cobrança precisa de uma data explícita no contrato do
            # Asaas. Hoje preserva o checkout imediato esperado pelo produto.
            "nextDueDate": _sao_paulo_today().isoformat(),
            "description": descricao,
        }
        if external_reference:
            payload["externalReference"] = external_reference
        resp = client.post("/subscriptions", headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()

    def _latest_subscription_payment(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        *,
        subscription_id: str,
    ) -> dict | None:
        """Return the newest generated payment, scanning every Asaas page.

        The endpoint is paginated and does not promise that ``data[0]`` is the
        current billing cycle.  Checkout resume therefore orders the complete
        result locally by due date (then creation date/id as deterministic
        tie-breakers) instead of accidentally reviving the first settled bill.
        """
        offset = 0
        latest: dict | None = None
        latest_key: tuple[str, str, str] | None = None
        while True:
            resp = client.get(
                f"/subscriptions/{subscription_id}/payments",
                headers=headers,
                params={"limit": 100, "offset": offset},
            )
            resp.raise_for_status()
            body = resp.json()
            payments = body.get("data") if isinstance(body, dict) else None
            if not isinstance(payments, list) or not payments:
                break
            for payment in payments:
                if not isinstance(payment, dict):
                    continue
                key = (
                    str(payment.get("dueDate") or ""),
                    str(payment.get("dateCreated") or ""),
                    str(payment.get("id") or ""),
                )
                if latest_key is None or key > latest_key:
                    latest = payment
                    latest_key = key
            if not bool(body.get("hasMore")):
                break
            offset += len(payments)
        return latest

    def _create_one_time_charge(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        *,
        customer_id: str,
        valor: float,
        description: str,
        external_reference: str,
    ) -> dict:
        """One-time charge (setup / monthly recovery) as a single payment."""
        payload: dict[str, object] = {
            "customer": customer_id,
            "billingType": "UNDEFINED",
            "value": valor,
            "dueDate": _sao_paulo_today().isoformat(),
            "description": description,
            "externalReference": external_reference,
        }
        resp = client.post("/payments", headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


def get_asaas_client() -> AsaasClient:
    """FastAPI dependency / factory for the Asaas client."""
    return AsaasClient()
