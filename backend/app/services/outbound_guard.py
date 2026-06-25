"""Guard de efeitos externos reais em ambientes não-produção (B2).

Efeitos externos — enviar WhatsApp (Evolution), cobrar (Asaas), e-mail (Brevo),
gastar token de LLM e criar/editar evento no Google Calendar — NÃO devem
disparar de local/staging. Produção permite; fora de produção fica bloqueado por
padrão, a menos que ``ALLOW_REAL_SENDS=true`` (apenas com credenciais sandbox).

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


def log_suppressed(channel: str, action: str) -> None:
    """Registra, sem segredo nem PII, um efeito externo suprimido fora de prod."""
    logger.info("[SANDBOX] %s suprimido em nao-producao: %s", channel, action)
