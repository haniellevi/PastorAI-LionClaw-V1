"""Ponto de extensão de notificação — NO-OP absoluto (Células PR3-PR9).

RNF-09/20: este módulo é o ÚNICO ponto de acoplamento futuro entre os avisos de
célula e um eventual disparo (WhatsApp/Evolution/agente). No MVP PR3–PR9 ele é
deliberadamente inerte:

  - NÃO cria fila, worker, cron nem chama nenhum serviço externo;
  - NÃO importa Evolution/WhatsApp/Google/Brevo;
  - apenas PERSISTE INTENÇÃO/ESTADO carimbando ``celula_aviso.notificado_em``.

Assim o backend registra "a intenção de notificar existiu", sem entregar nada.
Quando a integração real chegar, basta trocar o corpo destas funções — a
superfície (assinaturas ``notify_*``) permanece estável para os routers.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy.orm import Session

from app.db.models import CelulaAviso

logger = logging.getLogger("pastorai.cell_notify")


def _now_utc(now: dt.datetime | None) -> dt.datetime:
    """Relógio injetável (UTC) para testes determinísticos."""
    return now or dt.datetime.now(dt.timezone.utc)


def notify_notice_published(
    db: Session,
    aviso: CelulaAviso,
    *,
    now: dt.datetime | None = None,
) -> None:
    """Registra a intenção de notificar um aviso recém-publicado (NO-OP).

    Carimba ``notificado_em`` na MESMA sessão/transação do router (apenas
    ``flush``; o ``commit`` continua sendo do chamador). NENHUMA mensagem é
    enviada: WhatsApp/Evolution não são tocados aqui (RNF-09/20).
    """
    aviso.notificado_em = _now_utc(now)
    db.flush()
    logger.debug(
        "cell_notify: intenção registrada para aviso %s (no-op, sem envio real)",
        aviso.id,
    )


def notify_notice_removed(
    db: Session,  # noqa: ARG001 - assinatura estável p/ integração futura
    aviso: CelulaAviso,
) -> None:
    """Ponto de extensão para a inativação de um aviso (NO-OP total).

    Hoje não há nada a fazer (nenhuma notificação foi entregue). Mantido apenas
    para estabilizar a superfície ``notify_*`` usada pelos routers.
    """
    logger.debug(
        "cell_notify: aviso %s inativado (no-op, sem envio real)", aviso.id
    )
