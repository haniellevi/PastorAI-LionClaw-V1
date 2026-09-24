"""Console Master: status da triagem Jev (TypeSafe) em modo sombra.

Somente leitura da configuração de deploy + um teste de conexão com mensagem
sintética fixa. A chave e a lista de igrejas continuam no ambiente
(`TYPESAFE_API_KEY`, `JEV_SHADOW_TRIAGE_IGREJA_IDS`): gravar segredo de
plataforma no banco exige migration própria, hoje bloqueada. A chave nunca é
devolvida, nem parcialmente.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Igreja, PlatformAuditLog
from app.db.session import get_db
from app.deps import PlatformAdminUser, get_platform_admin
from app.services import semantic_triage as jev_triage
from app.services.outbound_guard import external_sends_allowed
from app.services.rate_limit import RateLimiter, get_rate_limiter

router = APIRouter(prefix="/admin", tags=["platform-admin-jev"])

INTEGRADO_AO_AGENTE = False

# Cada teste gasta tokens de terceiro: poucos por janela por operador.
TESTE_LIMITE_POR_JANELA = 10

# Mensagem inventada: o teste nunca envia dado de pessoa real.
MENSAGEM_TESTE = "Estou muito triste, perdi minha avó semana passada. Orem por mim."


class JevIgrejaOut(BaseModel):
    id: str
    nome: str | None = None  # None: id listado não existe na plataforma


class JevStatusOut(BaseModel):
    configurado: bool
    # Nenhum turno do agente chama a triagem ainda (gate D3): a lista não gera
    # evento algum até a integração. Troca para True no PR que ligar o runtime.
    integradoAoAgente: bool  # noqa: N815
    # Guard global ALLOW_REAL_SENDS: fechado, nada sai (nem o teste).
    enviosExternosPermitidos: bool  # noqa: N815
    modelo: str
    timeoutSegundos: float  # noqa: N815
    igrejas: list[JevIgrejaOut]
    idsInvalidos: int  # noqa: N815


class JevTesteOut(BaseModel):
    ok: bool
    modelo: str
    latenciaMs: int  # noqa: N815
    intencao: str
    riscoPastoral: float  # noqa: N815
    pedeOptout: float  # noqa: N815


def _actor_uuid(admin: PlatformAdminUser) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(admin.app_user_id))
    except (ValueError, TypeError):
        return None


@router.get("/jev", response_model=JevStatusOut)
def get_jev_status(
    db: Session = Depends(get_db),
    _admin: PlatformAdminUser = Depends(get_platform_admin),
) -> JevStatusOut:
    settings = jev_triage.get_triage_settings()
    allowed, invalid = jev_triage.parse_allowlist(
        settings.jev_shadow_triage_igreja_ids
    )
    nomes: dict[str, str] = {}
    if allowed:
        rows = db.execute(select(Igreja).where(Igreja.id.in_(allowed))).scalars()
        nomes = {str(i.id): i.nome for i in rows.all()}
    return JevStatusOut(
        configurado=jev_triage.is_configured(settings),
        integradoAoAgente=INTEGRADO_AO_AGENTE,
        enviosExternosPermitidos=external_sends_allowed(),
        modelo=settings.typesafe_model,
        timeoutSegundos=settings.typesafe_timeout_seconds,
        igrejas=[
            JevIgrejaOut(id=str(i), nome=nomes.get(str(i)))
            for i in sorted(allowed, key=str)
        ],
        idsInvalidos=invalid,
    )


@router.post("/jev/teste", response_model=JevTesteOut)
def post_jev_teste(
    db: Session = Depends(get_db),
    admin: PlatformAdminUser = Depends(get_platform_admin),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> JevTesteOut:
    """Chama o Jev com a mensagem sintética fixa e devolve as respostas."""
    settings = jev_triage.get_triage_settings()
    if not jev_triage.is_configured(settings):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="TYPESAFE_API_KEY não configurada no ambiente",
        )
    if not external_sends_allowed():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Envios externos desligados (ALLOW_REAL_SENDS)",
        )
    limiter.enforce_account(
        str(admin.app_user_id), "platform-jev-teste", TESTE_LIMITE_POR_JANELA
    )
    result = jev_triage.run_shadow_triage(
        settings,
        MENSAGEM_TESTE,
        termo_pendente=False,
        remetente_ministerial=False,
    )
    db.add(
        PlatformAuditLog(
            actor_id=_actor_uuid(admin),
            actor_email=None,
            acao="jev_testar",
            alvo_tipo="plataforma",
            alvo_id=None,
            alvo_nome="Triagem Jev",
            detalhe={"ok": result is not None},
        )
    )
    db.commit()
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Jev indisponível ou resposta inesperada",
        )
    return JevTesteOut(
        ok=True,
        modelo=result.modelo,
        latenciaMs=result.latencia_ms,
        intencao=result.intencao,
        riscoPastoral=round(result.risco_pastoral, 3),
        pedeOptout=round(result.pede_optout, 3),
    )
