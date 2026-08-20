"""Guard de efeitos externos reais (B2).

Efeitos externos — enviar WhatsApp (Evolution), cobrar (Asaas), e-mail (Brevo),
gastar token de LLM e criar/editar evento no Google Calendar — NÃO devem
disparar antes de uma ativação operacional explícita. Todos os ambientes,
inclusive produção, ficam bloqueados até ``ALLOW_REAL_SENDS=true``. Cobrança
Asaas exige ainda o opt-in separado ``ASAAS_BILLING_ENABLED=true``.

O guard age na CAMADA DE SERVIÇO de propósito: alguns envios são disparados de
forma autônoma (worker do agente, cron de SLA) sem passar por nenhum router —
um guard apenas nos endpoints não cobriria esses caminhos.

`log_suppressed` nunca registra segredo nem PII: apenas o canal e a ação.
"""

from __future__ import annotations

import logging

from app.config import Settings, get_settings

logger = logging.getLogger("pastorai.outbound")


def external_sends_allowed(settings: Settings | None = None) -> bool:
    """True quando efeitos externos reais podem disparar neste ambiente.

    Usa o ``settings`` informado (clientes de serviço injetam o seu) ou cai no
    global (``get_settings()``) para caminhos sem settings próprio, como o LLM.
    """
    return (settings or get_settings()).external_sends_enabled


def asaas_billing_writes_allowed(settings: Settings | None = None) -> bool:
    """True apenas quando os gates global E financeiro autorizam cobrança.

    Leituras Asaas e webhooks autenticados são deliberadamente independentes:
    esta função existe exclusivamente para POST/PUT financeiros.
    """
    return (settings or get_settings()).asaas_billing_writes_enabled


def log_suppressed(channel: str, action: str) -> None:
    """Registra, sem segredo nem PII, um efeito externo suprimido pelo gate."""
    logger.info("[OUTBOUND_DISABLED] %s suprimido: %s", channel, action)
