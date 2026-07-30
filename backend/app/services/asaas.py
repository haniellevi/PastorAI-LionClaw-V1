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
from dataclasses import dataclass

import httpx

from app.config import Settings, get_settings
from app.services.outbound_guard import external_sends_allowed, log_suppressed

logger = logging.getLogger("pastorai.asaas")
MIN_UNDEFINED_PAYMENT_VALUE = 5.0

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
    "PAYMENT_DELETED": "inadimplente",
    "PAYMENT_REFUNDED": "inadimplente",
}


def map_payment_status(raw_status: str | None) -> str | None:
    """Translate an Asaas event/payment status into a subscription_status."""
    if not raw_status:
        return None
    return _STATUS_MAP.get(raw_status.strip().upper())


def verify_webhook_token(expected: str, provided: str | None) -> bool:
    """Validate the Asaas webhook token in constant time."""
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided.strip())


class AsaasError(Exception):
    """Raised when an Asaas API call fails or the client is misconfigured."""


@dataclass(frozen=True)
class CheckoutResult:
    """Outcome of creating a subscription checkout."""

    customer_id: str
    subscription_id: str
    setup_charge_id: str | None
    invoice_url: str | None
    setup_invoice_url: str | None
    status: str  # ativa | pendente | inadimplente


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
        setup_fee: float | None = None,
        cpf_cnpj: str | None = None,
        external_reference: str | None = None,
    ) -> CheckoutResult:
        """Create (or reuse) a customer and open a subscription + setup charge.

        The setup fee is charged as a one-time payment alongside the recurring
        subscription. Both are created via the official Asaas v3 endpoints.
        """
        if not external_sends_allowed(self._settings):
            log_suppressed("Asaas", "create_checkout")
            return CheckoutResult(
                customer_id="sandbox",
                subscription_id="sandbox",
                setup_charge_id=None,
                invoice_url=None,
                setup_invoice_url=None,
                status="pendente",
            )
        if not cpf_cnpj:
            raise AsaasError("CPF ou CNPJ é obrigatório para o checkout")
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        fee = self._settings.asaas_setup_fee if setup_fee is None else setup_fee
        if 0 < fee < MIN_UNDEFINED_PAYMENT_VALUE:
            raise AsaasError("A taxa de setup precisa ser de pelo menos R$ 5,00")

        try:
            with httpx.Client(base_url=base_url, timeout=20.0) as client:
                customer_id = self._ensure_customer(
                    client, headers, nome=nome, email=email, cpf_cnpj=cpf_cnpj
                )
                sub = self._create_subscription(
                    client,
                    headers,
                    customer_id=customer_id,
                    valor=valor,
                    ciclo=ciclo,
                    descricao=f"PastorAI — plano {plano}",
                    external_reference=external_reference,
                )
                subscription_id = str(sub["id"])
                monthly_payment = self._first_subscription_payment(
                    client, headers, subscription_id=subscription_id
                )
                setup_charge_id: str | None = None
                setup_invoice_url: str | None = None
                if fee and fee > 0:
                    setup_charge = self._create_setup_charge(
                        client,
                        headers,
                        customer_id=customer_id,
                        valor=fee,
                        external_reference=external_reference,
                    )
                    setup_charge_id = str(setup_charge["id"])
                    setup_invoice_url = self._invoice_url(setup_charge)
        except httpx.HTTPError as exc:
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
            setup_charge_id=setup_charge_id,
            invoice_url=self._invoice_url(monthly_payment),
            setup_invoice_url=setup_invoice_url,
            status=status,
        )

    def get_subscription_invoice_url(self, subscription_id: str) -> str | None:
        """Re-read the public payment page of a subscription's first charge.

        Read-only recovery path (never creates charges): used when the checkout
        response was lost before persistence. Returns None when Asaas has not
        generated the payment yet or sends are sandboxed in this environment.
        """
        if not external_sends_allowed(self._settings):
            log_suppressed("Asaas", "get_subscription_invoice_url")
            return None
        base_url, api_key = self._require_config()
        headers = self._headers(api_key)
        try:
            with httpx.Client(base_url=base_url, timeout=20.0) as client:
                payment = self._first_subscription_payment(
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
        return self._invoice_url(payment)

    def get_payment_invoice_url(self, payment_id: str) -> str | None:
        """Re-read the public payment page of an existing one-time charge.

        Read-only recovery path for the setup fee — looks up by the stored
        charge id, never creates a new payment.
        """
        if not external_sends_allowed(self._settings):
            log_suppressed("Asaas", "get_payment_invoice_url")
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
        return self._invoice_url(body if isinstance(body, dict) else None)

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
            "nextDueDate": dt.date.today().isoformat(),
            "description": descricao,
        }
        if external_reference:
            payload["externalReference"] = external_reference
        resp = client.post("/subscriptions", headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()

    def _first_subscription_payment(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        *,
        subscription_id: str,
    ) -> dict | None:
        """Return the first generated payment for a new subscription, if ready."""
        resp = client.get(
            f"/subscriptions/{subscription_id}/payments",
            headers=headers,
            params={"limit": 1},
        )
        resp.raise_for_status()
        body = resp.json()
        payments = body.get("data") if isinstance(body, dict) else None
        if not isinstance(payments, list) or not payments:
            return None
        payment = payments[0]
        return payment if isinstance(payment, dict) else None

    @staticmethod
    def _invoice_url(payment: dict | None) -> str | None:
        """Extract the public payment page without exposing provider payloads."""
        if not payment:
            return None
        value = payment.get("invoiceUrl") or payment.get("bankSlipUrl")
        return str(value) if value else None

    def _create_setup_charge(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        *,
        customer_id: str,
        valor: float,
        external_reference: str | None,
    ) -> dict:
        """One-time setup fee charged as a single payment."""
        payload: dict[str, object] = {
            "customer": customer_id,
            "billingType": "UNDEFINED",
            "value": valor,
            "dueDate": dt.date.today().isoformat(),
            "description": "PastorAI — taxa de setup",
        }
        if external_reference:
            payload["externalReference"] = external_reference
        resp = client.post("/payments", headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


def get_asaas_client() -> AsaasClient:
    """FastAPI dependency / factory for the Asaas client."""
    return AsaasClient()
