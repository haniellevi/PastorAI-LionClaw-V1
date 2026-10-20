"""Datas civis da igreja, independentes do fuso do servidor."""
from datetime import date, datetime
from zoneinfo import ZoneInfo


def hoje_da_igreja() -> date:
    """Dia corrente no fuso operacional America/Sao_Paulo."""
    return datetime.now(ZoneInfo("America/Sao_Paulo")).date()
