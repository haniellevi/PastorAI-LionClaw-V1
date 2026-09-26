"""Console Master: configuração e status da triagem Jev (TypeSafe).

O master salva pelo console a chave (cifrada, nunca devolvida nem em parte),
o modelo, o timeout, a data do DPA e as igrejas em modo sombra; campo nulo cai
no ambiente (`TYPESAFE_*`, `JEV_SHADOW_TRIAGE_IGREJA_IDS`). Ficam só no
ambiente, de propósito, o guard `ALLOW_REAL_SENDS` e a URL da API. "Testar
conexão" usa uma mensagem sintética fixa.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Igreja, PlatformAuditLog, PlatformJevSettings
from app.db.session import get_db
from app.deps import PlatformAdminUser, get_platform_admin
from app.services import semantic_triage as jev_triage
from app.services.crypto import SecretsConfigError, encrypt_secret
from app.services.outbound_guard import external_sends_allowed
from app.services.rate_limit import RateLimiter, get_rate_limiter

router = APIRouter(prefix="/admin", tags=["platform-admin-jev"])

INTEGRADO_AO_AGENTE = False

# Cada teste gasta tokens de terceiro: poucos por janela por operador.
TESTE_LIMITE_POR_JANELA = 10

# Mensagem inventada: o teste nunca envia dado de pessoa real.
MENSAGEM_TESTE = "Estou muito triste, perdi minha avó semana passada. Orem por mim."

# Mesmo formato do CHECK da migration: só modelos do Jev.
_MODELO_RE = re.compile(r"^jev-[a-z0-9.-]{1,40}$")


class JevIgrejaOut(BaseModel):
    id: str
    nome: str | None = None  # None: id listado não existe na plataforma


class JevStatusOut(BaseModel):
    configurado: bool
    # De onde vem a chave em uso: "console", "ambiente" ou None.
    chaveOrigem: str | None = None  # noqa: N815
    # A chave salva não decifra (SECRETS_ENCRYPTION_KEY trocada): cadastrar de novo.
    chaveIlegivel: bool = False  # noqa: N815
    chaveAtualizadaEm: str | None = None  # noqa: N815
    dpaAssinadoEm: str | None = None  # noqa: N815
    # Nenhum turno do agente chama a triagem ainda: a lista não gera evento
    # algum até a integração. Troca para True no PR que ligar o runtime.
    integradoAoAgente: bool  # noqa: N815
    # Guard global ALLOW_REAL_SENDS: fechado, nada sai (nem o teste).
    enviosExternosPermitidos: bool  # noqa: N815
    modelo: str
    timeoutSegundos: float  # noqa: N815
    igrejas: list[JevIgrejaOut]
    idsInvalidos: int  # noqa: N815


class JevConfigIn(BaseModel):
    # Omitida ou vazia mantém a chave salva. Nunca é devolvida.
    apiKey: str | None = Field(default=None, max_length=512)  # noqa: N815
    removerChave: bool = False  # noqa: N815
    # Nulo usa o valor do ambiente.
    modelo: str | None = Field(default=None, max_length=64)
    timeoutSegundos: float | None = None  # noqa: N815
    dpaAssinadoEm: dt.date | None = None  # noqa: N815
    igrejaIds: list[uuid.UUID] = Field(default_factory=list, max_length=200)  # noqa: N815


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


def _status(db: Session) -> JevStatusOut:
    efetiva = jev_triage.effective_settings(db)
    settings = efetiva.settings
    allowed, invalid = jev_triage.parse_allowlist(
        settings.jev_shadow_triage_igreja_ids
    )
    nomes: dict[str, str] = {}
    if allowed:
        rows = db.execute(select(Igreja).where(Igreja.id.in_(allowed))).scalars()
        nomes = {str(i.id): i.nome for i in rows.all()}
    atualizada = efetiva.chave_atualizada_em
    return JevStatusOut(
        configurado=jev_triage.is_configured(settings),
        chaveOrigem=efetiva.chave_origem,
        chaveIlegivel=efetiva.chave_ilegivel,
        chaveAtualizadaEm=atualizada.isoformat() if atualizada else None,
        dpaAssinadoEm=(
            efetiva.dpa_assinado_em.isoformat() if efetiva.dpa_assinado_em else None
        ),
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


@router.get("/jev", response_model=JevStatusOut)
def get_jev_status(
    db: Session = Depends(get_db),
    _admin: PlatformAdminUser = Depends(get_platform_admin),
) -> JevStatusOut:
    return _status(db)


def _invalido(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


@router.put("/jev/config", response_model=JevStatusOut)
def put_jev_config(
    payload: JevConfigIn,
    db: Session = Depends(get_db),
    admin: PlatformAdminUser = Depends(get_platform_admin),
) -> JevStatusOut:
    """Salva a configuração do console; a chave vai cifrada e não volta."""
    chave = (payload.apiKey or "").strip()
    if chave and (len(chave) < 8 or any(c.isspace() for c in chave)):
        raise _invalido("Chave inválida: cole a chave da TypeSafe, sem espaços.")
    if chave and payload.removerChave:
        raise _invalido("Escolha entre salvar uma chave nova e remover a salva.")
    modelo = (payload.modelo or "").strip().lower() or None
    if modelo and not _MODELO_RE.fullmatch(modelo):
        raise _invalido("Modelo inválido: use jev-latest ou uma versão, como jev-1.13.")
    timeout = payload.timeoutSegundos
    if timeout is not None:
        # A coluna guarda uma casa decimal: 0,04 viraria 0,0 e violaria o CHECK.
        timeout = round(timeout, 1)
        if not 0 < timeout <= 10:
            raise _invalido("O timeout deve ficar entre 0,1 e 10 segundos.")
    ids = list(dict.fromkeys(payload.igrejaIds))
    dpa = payload.dpaAssinadoEm
    if ids and dpa is None:
        # Modo sombra envia texto pastoral a processador terceiro (AGENTS.md).
        raise _invalido("Informe a data do DPA com a TypeSafe antes de listar igrejas.")
    if dpa is not None and dpa > dt.date.today():
        raise _invalido("A data do DPA não pode estar no futuro.")
    if ids:
        existentes = {
            i.id
            for i in db.execute(select(Igreja).where(Igreja.id.in_(ids))).scalars().all()
        }
        faltando = [i for i in ids if i not in existentes]
        if faltando:
            raise _invalido(f"{len(faltando)} igreja(s) não encontrada(s).")

    row = jev_triage.load_console_settings(db)
    if row is None:
        row = PlatformJevSettings(id=1, igreja_ids=[])
        db.add(row)
    agora = dt.datetime.now(dt.UTC)
    acao_chave = "mantida"
    if chave:
        try:
            row.api_key_encrypted = encrypt_secret(chave)
        except SecretsConfigError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="SECRETS_ENCRYPTION_KEY ausente no servidor: a chave não pode ser salva.",
            ) from exc
        row.api_key_updated_at = agora
        acao_chave = "alterada"
    elif payload.removerChave and row.api_key_encrypted:
        row.api_key_encrypted = None
        row.api_key_updated_at = agora
        acao_chave = "removida"
    row.modelo = modelo
    row.timeout_seconds = timeout
    row.dpa_assinado_em = dpa
    row.igreja_ids = ids
    row.updated_at = agora
    row.updated_by = _actor_uuid(admin)
    db.add(
        PlatformAuditLog(
            actor_id=_actor_uuid(admin),
            actor_email=None,
            acao="jev_configurar",
            alvo_tipo="plataforma",
            alvo_id=None,
            alvo_nome="Triagem Jev",
            # Nunca a chave: só o que mudou nela.
            detalhe={
                "chave": acao_chave,
                "modelo": modelo,
                "timeoutSegundos": timeout,
                "igrejas": len(ids),
                "dpa": dpa.isoformat() if dpa else None,
            },
        )
    )
    db.commit()
    return _status(db)


@router.post("/jev/teste", response_model=JevTesteOut)
def post_jev_teste(
    db: Session = Depends(get_db),
    admin: PlatformAdminUser = Depends(get_platform_admin),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> JevTesteOut:
    """Chama o Jev com a mensagem sintética fixa e devolve as respostas."""
    settings = jev_triage.effective_settings(db).settings
    if not jev_triage.is_configured(settings):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chave da TypeSafe não configurada (console ou ambiente)",
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
