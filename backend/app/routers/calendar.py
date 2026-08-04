"""Calendar router — connect a church's existing Google Calendar (events F1).

OAuth web flow (offline → refresh_token) com **PKCE S256** e estado no servidor
(OAUTH-CALENDAR-V1). O consentimento é concluído em DOIS tempos:

1. ``POST /calendar/connect`` (admin) recebe o e-mail Google que o admin DECLARA
   que vai conectar, cria uma linha em ``calendar_oauth_flows`` com o
   ``code_verifier`` cifrado e o ``expected_email`` normalizado, e devolve a URL
   de consentimento, um ``flowSecret`` e o ``expiresAt`` REAL da linha. O painel
   guarda segredo e prazo no ``localStorage`` da PRÓPRIA origem (host irmão não
   lê nem grava) — ``localStorage``, e não ``sessionStorage``, porque uma PWA iOS
   pode ser encerrada em segundo plano e relançada.
2. ``GET /calendar/callback`` é PÚBLICO e só **estaciona** o ``code``. Não lê
   sessão, não fala com o Google, não grava ``calendar_sync``.
3. ``POST /calendar/connect/finish`` (admin, Bearer) apresenta o ``flowSecret``,
   compara ``app_user_id`` + ``igreja_id``, **consome** o fluxo, troca o ``code``
   e então **verifica no Google QUAL conta consentiu** (userinfo). Só persiste se
   o e-mail verificado bater com o declarado. O ``flowSecret`` é **OBRIGATÓRIO**:
   sem posse dele nenhum fluxo é concluído, em nenhuma superfície.

Essa separação é o que fecha o account-linking CSRF: um consentimento iniciado
por alguém só conclui na sessão de quem o iniciou.

Identidade autenticada **não substitui** o segredo. ``app_user_id`` +
``igreja_id`` provam apenas QUEM finaliza, nunca QUAL conta Google consentiu;
achar o fluxo só por eles deixaria um ``state`` vazado virar vinculação de conta
silenciosa na próxima montagem da tela, sem clique nenhum do admin.

E o segredo, sozinho, também não prova a conta Google: PKCE não impede que
alguém abra a URL de autorização ORIGINAL noutro navegador e consinta com outra
conta — o ``code`` sai amarrado ao MESMO ``code_challenge`` e a troca sucede.
Por isso o ``expected_email`` + userinfo: sem os dois, "conectado" significaria
apenas "alguém autorizou alguma conta".

ATENÇÃO: o callback é anônimo e usa ``get_db``, que não aplica tenant context —
roda no papel de conexão com BYPASSRLS. **RLS não é defesa do callback**; a
autorização dele é o ``state`` inadivinhável mais as condições do ``WHERE``.

Tokens are stored encrypted at rest (reusing the BYO-credential crypto). The
key never leaves the server; status/list never echo it.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import uuid
from urllib.parse import urlparse

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    AgendaAlertRecipient,
    CalendarOAuthFlow,
    CalendarSync,
    Event,
    Igreja,
)
from app.db.session import get_db
from app.deps import CurrentUser, require_role
from app.domain.phone import normalize_phone
from app.services.calendar_oauth_flows import hash_secret, new_pkce_pair, new_secret
from app.services.crypto import SecretDecryptionError, decrypt_secret, encrypt_secret
from app.services.google_oauth import (
    GoogleOAuthClient,
    GoogleOAuthError,
    get_google_oauth_client,
)

logger = logging.getLogger("pastorai.calendar")

router = APIRouter(prefix="/calendar", tags=["calendar"])

# Marcadores de rota do retorno. O parser do shell divide no PRIMEIRO "/"
# (frontend/src/components/shell/AdminAppShell.tsx), então `integracoes/callback/
# <marker>` resolve a base `integracoes` e preserva o sufixo. Query string no
# hash NÃO funciona: o shell trataria a string inteira como nome de rota.
_MARKER_READY = "ready"
_MARKER_CANCELLED = "cancelled"
# Caminho por superfície, escolhido no SERVIDOR a partir do host da origem
# persistida. Espelha o mapa de rotas de frontend/src/lib/navigation.ts:103
# ("admin.<domínio> → /gestao"); se aquela tabela mudar, esta constante muda.
_RETURN_PATH_ADMIN = "/#integracoes/callback/"
_RETURN_PATH_APP = "/gestao#integracoes/callback/"
_INTEGRATIONS_PATH_ADMIN = "/#integracoes"
_INTEGRATIONS_PATH_APP = "/gestao#integracoes"

# Mesmo corpo para TODA rejeição do finish — sem oráculo de causa. A ÚNICA
# exceção é a divergência de conta, que precisa ser acionável: o admin tem de
# saber que autorizou a conta errada, e qual.
_FINISH_GENERIC = "Não foi possível concluir a conexão com o Google."
_MISMATCH_CODE = "conta_divergente"
_REIDENTIFIED_CODE = "conta_reidentificada"
# Mesma conta declarada, `sub` diferente do já conectado. Nunca revela o sub.
_REIDENTIFIED = (
    "Esse endereço agora pertence a outra conta Google. Desconecte a agenda "
    "atual antes de conectar esta conta."
)

# Checagem pragmática de formato (evita a dependência email-validator), igual à
# de app/routers/auth.py.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _return_url(origin: str, marker: str) -> str:
    """URL de retorno para uma origem JÁ validada contra a allowlist."""
    host = urlparse(origin).hostname or ""
    path = _RETURN_PATH_ADMIN if host.startswith("admin.") else _RETURN_PATH_APP
    return f"{origin}{path}{marker}"


def _integrations_url(origin: str) -> str:
    """Tela base de Integrações para uma origem JÁ validada."""
    host = urlparse(origin).hostname or ""
    path = (
        _INTEGRATIONS_PATH_ADMIN
        if host.startswith("admin.")
        else _INTEGRATIONS_PATH_APP
    )
    return f"{origin}{path}"


def _is_master_console_origin(origin: str) -> bool:
    """O console ``painel.*`` não hospeda o card que conclui o OAuth."""
    return (urlparse(origin).hostname or "").lower().startswith("painel.")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ConnectRequest(BaseModel):
    """Conta Google que o admin DECLARA antes de sair para o consentimento.

    É a intenção explícita contra a qual o ``finish`` compara o e-mail verificado
    no userinfo. Sem ela, "conectado" significaria só "alguém autorizou alguma
    conta". Normalizada aqui (trim + lowercase) para que a comparação lá seja
    mecânica, e nunca em query string nem em log.
    """

    expectedGoogleEmail: str = Field(min_length=3, max_length=320)  # noqa: N815

    @field_validator("expectedGoogleEmail")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL_RE.match(value):
            raise ValueError("E-mail inválido")
        return value


class ConnectUrlOut(BaseModel):
    authUrl: str  # noqa: N815 - external contract camelCase
    # Segredo do fluxo, distinto do `state`. O painel guarda no localStorage da
    # PRÓPRIA origem e nunca viaja para o Google nem entra em access log.
    flowSecret: str  # noqa: N815
    # Expiração REAL do fluxo — o MESMO valor gravado em
    # `calendar_oauth_flows.expires_at`. O cliente não deriva TTL nenhum: ele
    # apenas descarta o segredo quando este instante passa. O servidor segue
    # sendo a autoridade final e revalida `expires_at` no `finish`.
    expiresAt: dt.datetime  # noqa: N815


class FinishRequest(BaseModel):
    """A posse do ``flowSecret`` é OBRIGATÓRIA — não há caminho por identidade.

    Um corpo sem segredo é recusado pelo schema (422) **antes** do handler, então
    nenhuma linha de ``calendar_oauth_flows`` é lida, travada ou consumida.
    """

    flowSecret: str = Field(min_length=1, max_length=400)  # noqa: N815


class FinishOut(BaseModel):
    """200 = conectado; 202 = callback pendente ou finish em processamento."""

    status: str
    connected: bool
    calendarId: str | None = None  # noqa: N815
    # E-mail VERIFICADO da conta conectada. `None` em conexão legada (anterior ao
    # binding). Nunca o `sub`, nunca token.
    googleAccountEmail: str | None = None  # noqa: N815
    # Revisão opaca da conexão atual. O cliente a devolve ao escolher uma
    # agenda, para que uma escolha iniciada sob outra conta não sobreviva a uma
    # troca concorrente de identidade.
    connectionVersion: dt.datetime | None = None  # noqa: N815


class StatusOut(BaseModel):
    connected: bool
    calendarId: str | None = None  # noqa: N815
    googleAccountEmail: str | None = None  # noqa: N815
    connectionVersion: dt.datetime | None = None  # noqa: N815


class CalendarItem(BaseModel):
    id: str
    summary: str | None = None
    primary: bool = False


class CalendarListOut(BaseModel):
    calendars: list[CalendarItem]
    # Revisão da conexão DEPOIS da manutenção de token feita por esta chamada.
    # Sem ela, uma conexão legada (revisão = `atualizado_em`) que renova o access
    # token ao listar deixaria o cliente com a revisão anterior e a seleção
    # seguinte levaria 409 sem que a identidade Google tivesse mudado.
    connectionVersion: dt.datetime | None = None  # noqa: N815


class SelectCalendarRequest(BaseModel):
    calendarId: str = Field(min_length=1, max_length=300)  # noqa: N815
    # Opcional só para devolver 409 acionável a clientes antigos. Sem uma
    # revisão que bata com a conexão travada, esta request nunca escreve.
    connectionVersion: dt.datetime | None = None  # noqa: N815


class PreviewEventItem(BaseModel):
    googleEventId: str  # noqa: N815
    titulo: str | None = None
    descricao: str | None = None
    data: str | None = None  # YYYY-MM-DD
    hora: str | None = None  # HH:MM (None for all-day)
    fim: str | None = None  # HH:MM end (None for all-day / unset)
    recorrente: bool = False


class ImportPreviewOut(BaseModel):
    calendarId: str  # noqa: N815
    events: list[PreviewEventItem]
    # Mesma razão de `CalendarListOut`: este endpoint também renova o token e
    # comita, portanto também pode avançar a revisão da conexão.
    connectionVersion: dt.datetime | None = None  # noqa: N815


# EVT-6 PR6.2 — eventos importados do Google nascem pendentes de confirmação,
# marcados como origem Google e tratados como pontuais (têm data específica).
_IMPORT_STATUS = "a_confirmar"
_IMPORT_ORIGEM = "google"
_IMPORT_RECORRENCIA = "pontual"


class ImportResultItem(BaseModel):
    id: str
    googleEventId: str  # noqa: N815
    titulo: str


class ImportResultOut(BaseModel):
    created: int
    skipped: int
    events: list[ImportResultItem]
    # Mesma razão de `CalendarListOut`: importar renova o token e comita.
    connectionVersion: dt.datetime | None = None  # noqa: N815


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sync_for(db: Session, igreja_id: uuid.UUID) -> CalendarSync | None:
    return db.execute(
        select(CalendarSync).where(CalendarSync.igreja_id == igreja_id)
    ).scalar_one_or_none()


def _locked_sync_for(db: Session, igreja_id: uuid.UUID) -> CalendarSync | None:
    """Serializa toda decisão de identidade, inclusive a primeira conexão.

    Travar a igreja, e não só ``calendar_sync``, cobre também o caso em que a
    linha de sync ainda não existe. O lock permanece até o commit final.
    """
    igreja = db.execute(
        select(Igreja).where(Igreja.id == igreja_id).with_for_update()
    ).scalar_one_or_none()
    if igreja is None:
        raise _finish_rejected()
    return _sync_for(db, igreja_id)


def _connected(sync: CalendarSync | None) -> bool:
    return sync is not None and bool(sync.refresh_token_encrypted)


def _selection_version(sync: CalendarSync | None) -> dt.datetime | None:
    """Return the opaque revision that authorizes a calendar selection.

    New connections carry ``connected_em``, which changes whenever the Google
    identity changes.  Older valid rows predate that column and therefore use
    their already-persisted ``atualizado_em`` as a safe row revision instead.
    """
    if sync is None:
        return None
    return sync.connected_em or sync.atualizado_em


def _parse_date(value: str | None) -> dt.date | None:
    """Parse a preview ``'YYYY-MM-DD'`` into a date, or None when absent/invalid."""
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _valid_access_token(
    db: Session, sync: CalendarSync, oauth: GoogleOAuthClient
) -> str:
    """Return a usable token without ending the caller's identity lock.

    Every caller that can reach Google first locks the stable ``igrejas`` row.
    A commit here would release that lock before the Google operation finishes,
    allowing a concurrent ``connect/finish`` to switch accounts mid-request.
    The endpoint commits only after its Google call (and any import) completes.
    """
    now = dt.datetime.now(dt.timezone.utc)
    if (
        sync.access_token_encrypted
        and sync.access_token_expira_em
        and sync.access_token_expira_em > now + dt.timedelta(seconds=60)
    ):
        try:
            return decrypt_secret(sync.access_token_encrypted)
        except SecretDecryptionError:
            pass  # fall through to a refresh
    if not sync.refresh_token_encrypted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Agenda não conectada"
        )
    try:
        refresh = decrypt_secret(sync.refresh_token_encrypted)
    except SecretDecryptionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Reconecte a agenda do Google",
        ) from exc
    try:
        tokens = oauth.refresh_access_token(refresh)
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    sync.access_token_encrypted = encrypt_secret(tokens.access_token)
    sync.access_token_expira_em = now + dt.timedelta(seconds=tokens.expires_in)
    sync.atualizado_em = now
    db.flush()
    return tokens.access_token


# ---------------------------------------------------------------------------
# Endpoints (admin only, tenant-scoped) — except the public callback
# ---------------------------------------------------------------------------
@router.post("/connect", response_model=ConnectUrlOut)
def connect(
    payload: ConnectRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
    oauth: GoogleOAuthClient = Depends(get_google_oauth_client),
) -> ConnectUrlOut:
    """Cria o fluxo OAuth e devolve a URL de consentimento + o ``flowSecret``.

    POST (não GET) porque agora carrega corpo: o e-mail Google declarado, que
    fica só no corpo — nunca em query string, nunca em log.

    A origem de retorno vem do header ``Origin`` e é validada por IGUALDADE
    EXATA contra ``calendar_oauth_return_origins`` — nunca ``Referer``, nunca
    path do cliente. A allowlist de retorno é mais restrita, mas também precisa
    pertencer a ``cors_origins``; do contrário o navegador nem conseguiria
    chamar este POST. Origem ausente ou fora de qualquer lista falha em 400.
    """
    settings = get_settings()
    origin = (request.headers.get("origin") or "").strip().rstrip("/")
    if (
        not origin
        or origin not in settings.calendar_oauth_return_origin_allowlist
        or origin not in settings.cors_origins
        or _is_master_console_origin(origin)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Origem não autorizada para conectar a agenda",
        )

    state = new_secret()
    flow_secret = new_secret()
    verifier, challenge = new_pkce_pair()
    try:
        url = oauth.build_consent_url(
            state=state,
            code_challenge=challenge,
        )
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    now = dt.datetime.now(dt.timezone.utc)
    # Um único `expires_at`: o que grava a linha é o mesmo que volta ao cliente.
    # Devolver o instante (e não o TTL) evita que o painel recalcule prazo com o
    # relógio dele, que pode estar adiantado.
    expires_at = now + dt.timedelta(
        minutes=settings.calendar_oauth_flow_ttl_minutes
    )
    db.add(
        CalendarOAuthFlow(
            state_hash=hash_secret(state),
            flow_secret_hash=hash_secret(flow_secret),
            igreja_id=uuid.UUID(current_user.igreja_id),
            app_user_id=uuid.UUID(current_user.app_user_id),
            return_origin=origin,
            verifier_encrypted=encrypt_secret(verifier),
            expected_email=payload.expectedGoogleEmail,
            expires_at=expires_at,
        )
    )
    db.commit()
    return ConnectUrlOut(
        authUrl=url, flowSecret=flow_secret, expiresAt=expires_at
    )


def _flow_redirect(db: Session, state_hash: str, fallback: str) -> RedirectResponse:
    """Redirect de leitura pura para callback repetido ou interrompido.

    Um ``error`` que chegue DEPOIS de um park legítimo devolve ``ready`` — nunca
    ``cancelled`` — para que um ``state`` vazado não consiga cancelar visualmente
    um fluxo que já está pronto para ser concluído.

    Um fluxo que já terminou com sucesso não tem mais code nem segredo para o
    frontend concluir. Repetir o callback dele volta direto para Integrações:
    emitir ``cancelled`` nessa situação esconderia uma conexão que já existe.
    """
    row = db.execute(
        select(
            CalendarOAuthFlow.return_origin,
            CalendarOAuthFlow.code_encrypted,
            CalendarOAuthFlow.consumed_at,
            CalendarOAuthFlow.finish_result,
        ).where(CalendarOAuthFlow.state_hash == state_hash)
    ).first()
    if row is None:
        return RedirectResponse(url=_return_url(fallback, _MARKER_CANCELLED))
    origin, parked, consumed_at, finish_result = row
    if consumed_at is not None:
        if finish_result == "connected":
            return RedirectResponse(url=_integrations_url(origin))
        if finish_result is None:
            # `_burn()` committed, but the first `/finish` is still exchanging
            # the code (or its HTTP response was interrupted).  It remains a
            # recoverable processing state, never a cancellation.
            return RedirectResponse(url=_return_url(origin, _MARKER_READY))
    marker = _MARKER_READY if parked else _MARKER_CANCELLED
    return RedirectResponse(url=_return_url(origin, marker))


@router.get("/callback")
def callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Callback público: **só estaciona** o ``code``. Não troca nada.

    Um único UPDATE condicional (primeira escrita vence); ``rowcount`` nunca é
    exposto e a resposta é sempre um 3xx. Nenhuma chamada ao Google, nenhuma
    leitura de sessão, nenhuma escrita em ``calendar_sync``.

    ``error``/``code`` ausente é terminal para a jornada mas **não queima** o
    fluxo: queimar aqui daria a quem tivesse um ``state`` vazado um DoS sobre um
    consentimento já estacionado. O fluxo morre no TTL e o purge o apaga.
    """
    fallback = get_settings().frontend_url.rstrip("/")
    if not state:
        return RedirectResponse(url=_return_url(fallback, _MARKER_CANCELLED))
    state_hash = hash_secret(state)
    now = dt.datetime.now(dt.timezone.utc)
    try:
        if error or not code:
            return _flow_redirect(db, state_hash, fallback)
        result = db.execute(
            update(CalendarOAuthFlow)
            .where(
                CalendarOAuthFlow.state_hash == state_hash,
                CalendarOAuthFlow.consumed_at.is_(None),
                CalendarOAuthFlow.code_encrypted.is_(None),
                CalendarOAuthFlow.expires_at > now,
            )
            .values(code_encrypted=encrypt_secret(code), atualizado_em=now)
            .returning(CalendarOAuthFlow.return_origin)
        )
        origin = result.scalar_one_or_none()
        db.commit()
        if origin:
            return RedirectResponse(url=_return_url(origin, _MARKER_READY))
        # Nada atualizado: inexistente, já estacionado, consumido ou expirado.
        return _flow_redirect(db, state_hash, fallback)
    except Exception:  # noqa: BLE001 - o callback nunca devolve 5xx ao navegador
        db.rollback()
        logger.warning("Google OAuth callback rejected")
        return RedirectResponse(url=_return_url(fallback, _MARKER_CANCELLED))


def _burn(
    db: Session,
    flow: CalendarOAuthFlow,
    now: dt.datetime,
    *,
    finish_result: str | None = None,
) -> None:
    """Consome o fluxo e apaga os segredos, no MESMO update. Commit solta o lock."""
    flow.consumed_at = now
    flow.verifier_encrypted = None
    flow.code_encrypted = None
    flow.finish_result = finish_result
    flow.finished_at = now if finish_result else None
    flow.atualizado_em = now
    db.commit()


def _mark_finish_failed(db: Session, flow: CalendarOAuthFlow) -> None:
    """Fecha durablemente um finish já consumido que não produziu conexão."""
    finished_at = dt.datetime.now(dt.timezone.utc)
    flow.finish_result = "failed"
    flow.finished_at = finished_at
    flow.atualizado_em = finished_at
    db.commit()


def _finish_rejected() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail=_FINISH_GENERIC
    )


@router.post("/connect/finish", response_model=FinishOut)
def finish_connection(
    payload: FinishRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
    oauth: GoogleOAuthClient = Depends(get_google_oauth_client),
) -> FinishOut:
    """Consome o fluxo e persiste a conexão. Só quem tem o ``flowSecret`` conclui.

    A linha é localizada **exclusivamente** pelo hash do segredo. Não existe
    caminho por identidade: ``app_user_id`` + ``igreja_id`` são VALIDAÇÃO depois
    de achar a linha, nunca chave de busca. Achar por eles deixaria a posse de um
    ``state`` vazado bastar — o terceiro consente com a conta Google dele, o
    callback estaciona o ``code``, e o fluxo fecharia sozinho na próxima
    montagem da tela do admin.

    Ordem obrigatória: identidade ANTES de qualquer sinal sobre o estado do
    fluxo (senão o 202 vira oráculo de existência), e queima ANTES da troca com
    o Google (o commit solta o lock antes da chamada de 15s). O resultado final
    fica gravado no próprio fluxo para tornar um replay do MESMO segredo seguro
    depois de uma resposta HTTP perdida.
    """
    flow = db.execute(
        select(CalendarOAuthFlow)
        .where(CalendarOAuthFlow.flow_secret_hash == hash_secret(payload.flowSecret))
        .with_for_update()
    ).scalar_one_or_none()
    if flow is None:
        raise _finish_rejected()

    now = dt.datetime.now(dt.timezone.utc)
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    if flow.app_user_id != uuid.UUID(current_user.app_user_id):
        _burn(db, flow, now, finish_result="failed")
        raise _finish_rejected()
    if flow.igreja_id != igreja_uuid:
        _burn(db, flow, now, finish_result="failed")
        raise _finish_rejected()

    # Replay depois de resposta HTTP perdida: só um resultado DURÁVEL deste
    # mesmo fluxo pode comprovar sucesso. O e-mail/connected antigos não bastam.
    if flow.finish_result == "connected":
        sync = _locked_sync_for(db, igreja_uuid)
        if (
            sync is not None
            and flow.finished_at is not None
            and sync.connected_em == flow.finished_at
            and (sync.google_account_email or "") == (flow.expected_email or "")
        ):
            result = FinishOut(
                status="conectado",
                connected=True,
                calendarId=sync.google_calendar_id,
                googleAccountEmail=sync.google_account_email,
                connectionVersion=_selection_version(sync),
            )
            db.rollback()  # só leitura; libera as duas travas
            return result
        db.rollback()
        raise _finish_rejected()
    if flow.finish_result == "failed":
        db.rollback()
        raise _finish_rejected()
    if flow.consumed_at is not None:
        db.rollback()
        # A primeira request queimou o fluxo e ainda está processando (ou foi
        # interrompida). Não declare falha nem sucesso: preserve o segredo para
        # um replay posterior até o TTL/purge.
        response.status_code = status.HTTP_202_ACCEPTED
        return FinishOut(status="processando", connected=False)
    if flow.expires_at <= now:
        _burn(db, flow, now, finish_result="failed")
        raise _finish_rejected()
    if not flow.code_encrypted:
        # Callback ainda não estacionou (reload/back/corrida). NÃO consome.
        db.rollback()
        response.status_code = status.HTTP_202_ACCEPTED
        return FinishOut(status="aguardando_callback", connected=False)

    # Lidos ANTES da queima: o commit do `_burn` expira os atributos do objeto.
    expected_email = (flow.expected_email or "").strip().lower()
    try:
        code = decrypt_secret(flow.code_encrypted)
        verifier = decrypt_secret(flow.verifier_encrypted or "")
    except (SecretDecryptionError, ValueError) as exc:
        _burn(db, flow, now, finish_result="failed")
        raise _finish_rejected() from exc
    if not expected_email:
        # Fluxo legado, criado antes do binding de identidade. Não há contra o
        # que comparar => fail-closed. Queima porque nunca vai poder concluir.
        _burn(db, flow, now, finish_result="failed")
        raise _finish_rejected()

    _burn(db, flow, now)

    try:
        tokens = oauth.exchange_code(code, verifier)
        # Quem de fato consentiu. Só isto distingue "a conta que o admin quis" de
        # "alguma conta que autorizou usando esta URL".
        identity = oauth.fetch_userinfo(tokens.access_token)
    except GoogleOAuthError as exc:
        _mark_finish_failed(db, flow)
        raise _finish_rejected() from exc

    if identity.email != expected_email:
        # ÚNICA rejeição com detalhe: sem saber qual conta autorizou, o admin não
        # tem como corrigir. Nada foi escrito e a conexão anterior segue intacta;
        # os tokens novos morrem aqui, em memória.
        _mark_finish_failed(db, flow)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": _MISMATCH_CODE,
                "expected": expected_email,
                "verified": identity.email,
            },
        )

    # A decisão de preservar/trocar identidade e refresh token precisa observar
    # o último estado commitado. Sem este lock, dois finishes concorrentes
    # podem combinar a identidade de um fluxo com o refresh token do outro.
    sync = _locked_sync_for(db, igreja_uuid)
    previous_sub = (sync.google_account_sub or "") if sync else ""
    # Continuidade é decidida pelo `sub`, NUNCA pelo e-mail: e-mail troca de dono.
    same_identity = bool(previous_sub) and previous_sub == identity.sub

    if (
        sync is not None
        and previous_sub
        and not same_identity
        and (sync.google_account_email or "") == identity.email
    ):
        # Mesmo endereço, conta Google diferente. Terminal e acionável, sem
        # revelar o `sub`. A conexão anterior fica intacta.
        _mark_finish_failed(db, flow)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": _REIDENTIFIED_CODE, "message": _REIDENTIFIED},
        )

    # Refresh token de outra identidade NUNCA é reaproveitado. Preservar só vale
    # quando o `sub` é o mesmo — `prompt=consent` não é garantia de token novo.
    can_preserve = same_identity and bool(sync and sync.refresh_token_encrypted)
    if not tokens.refresh_token and not can_preserve:
        _mark_finish_failed(db, flow)
        raise _finish_rejected()

    try:
        # PROBE de capacidade: `connected` passa a significar "verificadamente
        # utilizável". O campo `scope` da resposta do token NÃO é usado como
        # condição — sua semântica não é garantida e ausência não reprova.
        oauth.list_calendars(tokens.access_token)
    except GoogleOAuthError as exc:
        _mark_finish_failed(db, flow)
        raise _finish_rejected() from exc

    if sync is None:
        sync = CalendarSync(igreja_id=igreja_uuid)
        db.add(sync)
    if tokens.refresh_token:
        sync.refresh_token_encrypted = encrypt_secret(tokens.refresh_token)
    if not same_identity:
        # Identidade desconhecida ou trocada: a agenda escolhida pertencia à
        # conta anterior e não pode ser herdada.
        sync.google_calendar_id = None
    sync.google_account_email = identity.email
    sync.google_account_sub = identity.sub
    sync.connected_by_app_user_id = uuid.UUID(current_user.app_user_id)
    completed_at = dt.datetime.now(dt.timezone.utc)
    sync.connected_em = completed_at
    sync.access_token_encrypted = encrypt_secret(tokens.access_token)
    sync.access_token_expira_em = now + dt.timedelta(seconds=tokens.expires_in)
    sync.atualizado_em = now
    flow.finish_result = "connected"
    flow.finished_at = completed_at
    flow.atualizado_em = completed_at
    db.commit()
    # Sem e-mail, sem `sub`, sem token na linha de log.
    logger.info("Google Calendar connected for an igreja (scope=%s)", tokens.scope)
    return FinishOut(
        status="conectado",
        connected=True,
        calendarId=sync.google_calendar_id,
        googleAccountEmail=sync.google_account_email,
        connectionVersion=_selection_version(sync),
    )


@router.get("/status", response_model=StatusOut)
def get_status(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> StatusOut:
    """Whether the igreja has a connected calendar (no secret echoed).

    ``googleAccountEmail`` é `None` em conexão legada — anterior ao binding de
    identidade. O `sub` e os tokens nunca saem daqui.
    """
    sync = _sync_for(db, uuid.UUID(current_user.igreja_id))
    if not _connected(sync):
        return StatusOut(connected=False)
    return StatusOut(
        connected=True,
        calendarId=sync.google_calendar_id,
        googleAccountEmail=sync.google_account_email,
        connectionVersion=_selection_version(sync),
    )


@router.get("/list", response_model=CalendarListOut)
def list_calendars(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
    oauth: GoogleOAuthClient = Depends(get_google_oauth_client),
) -> CalendarListOut:
    """List the connected account's calendars so the admin can pick one."""
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    sync = _locked_sync_for(db, igreja_uuid)
    if not _connected(sync):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Agenda não conectada"
        )
    token = _valid_access_token(db, sync, oauth)
    try:
        cals = oauth.list_calendars(token)
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    db.commit()
    return CalendarListOut(
        calendars=[CalendarItem(**c) for c in cals],
        connectionVersion=_selection_version(sync),
    )


@router.get("/import/preview", response_model=ImportPreviewOut)
def import_preview(
    timeMin: str | None = Query(default=None),  # noqa: N803 - external camelCase
    timeMax: str | None = Query(default=None),  # noqa: N803
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["pastor"])),
    oauth: GoogleOAuthClient = Depends(get_google_oauth_client),
) -> ImportPreviewOut:
    """Read-only preview of the igreja's Google Calendar events (EVT-6 PR6.1).

    Lists events using the per-igreja OAuth token (``calendar_sync``); nothing is
    written to ``events``. Defaults to a safe forward window (now → +90d) when
    the range is omitted. 409 when the igreja has no calendar connected.
    """
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    sync = _locked_sync_for(db, igreja_uuid)
    if not _connected(sync):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Agenda não conectada"
        )
    now = dt.datetime.now(dt.timezone.utc)
    time_min = timeMin or now.isoformat()
    time_max = timeMax or (now + dt.timedelta(days=90)).isoformat()
    token = _valid_access_token(db, sync, oauth)
    # ponytail: default to "primary" when no calendar selected yet — same
    # convention as the legacy client and Google's own default.
    calendar_id = sync.google_calendar_id or "primary"
    try:
        events = oauth.list_events(token, calendar_id, time_min, time_max)
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc
    db.commit()
    return ImportPreviewOut(
        calendarId=calendar_id,
        events=[PreviewEventItem(**e) for e in events],
        connectionVersion=_selection_version(sync),
    )


@router.post("/import", response_model=ImportResultOut)
def import_events(
    timeMin: str | None = Query(default=None),  # noqa: N803 - external camelCase
    timeMax: str | None = Query(default=None),  # noqa: N803
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["pastor"])),
    oauth: GoogleOAuthClient = Depends(get_google_oauth_client),
) -> ImportResultOut:
    """Importa eventos do Google como ``a_confirmar`` / ``origem='google'`` (PR6.2).

    Lê o Google **por igreja** (read-only, mesma janela do preview) e **persiste**
    localmente, tenant-scoped, **sem confirmar** e **sem enviar** nada (WhatsApp/
    e-mail só no fluxo de confirmação/worker, não aqui). Dedup **simples em código**
    por ``(igreja_id, google_event_id)`` — o índice único parcial vem no PR6.3.
    Não escreve no Google (só ``events.list``). 409 quando a igreja não está
    conectada; 502 em falha do Google.
    """
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    sync = _locked_sync_for(db, igreja_uuid)
    if not _connected(sync):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Agenda não conectada"
        )
    now = dt.datetime.now(dt.timezone.utc)
    time_min = timeMin or now.isoformat()
    time_max = timeMax or (now + dt.timedelta(days=90)).isoformat()
    token = _valid_access_token(db, sync, oauth)
    calendar_id = sync.google_calendar_id or "primary"
    try:
        previews = oauth.list_events(token, calendar_id, time_min, time_max)
    except GoogleOAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    # Dedup tenant-scoped: ids já importados NESTA igreja (RLS + filtro igreja_id,
    # defesa em profundidade). Eventos de outro tenant com o mesmo google_event_id
    # não aparecem aqui, então não bloqueiam este tenant.
    candidate_ids = [p["googleEventId"] for p in previews if p.get("googleEventId")]
    seen: set[str] = set()
    if candidate_ids:
        rows = db.execute(
            select(Event.google_event_id).where(
                Event.igreja_id == igreja_uuid,
                Event.google_event_id.in_(candidate_ids),
            )
        ).scalars().all()
        seen.update(r for r in rows if r)

    created: list[Event] = []
    skipped = 0
    for p in previews:
        gid = p.get("googleEventId")
        data = _parse_date(p.get("data"))
        # Pula: sem id Google, já importado (dedup), ou sem data — 'pontual' exige
        # data NOT NULL pela CHECK events_recorrencia_chk (recorrente fica p/ depois).
        if not gid or gid in seen or data is None:
            skipped += 1
            continue
        seen.add(gid)
        event = Event(
            igreja_id=igreja_uuid,
            # ponytail: placeholder se o Google não expõe summary — evita violar
            # events.titulo NOT NULL; o usuário ajusta o título ao confirmar.
            titulo=p.get("titulo") or "(sem título)",
            descricao=p.get("descricao"),
            data=data,
            hora=p.get("hora"),
            google_event_id=gid,
            status=_IMPORT_STATUS,
            origem=_IMPORT_ORIGEM,
            recorrencia=_IMPORT_RECORRENCIA,
        )
        db.add(event)
        created.append(event)

    if created:
        db.flush()
        for event in created:
            db.refresh(event)
    db.commit()

    return ImportResultOut(
        created=len(created),
        skipped=skipped,
        connectionVersion=_selection_version(sync),
        events=[
            ImportResultItem(
                id=str(e.id),
                googleEventId=e.google_event_id or "",
                titulo=e.titulo,
            )
            for e in created
        ],
    )


@router.put("", response_model=StatusOut)
def select_calendar(
    payload: SelectCalendarRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> StatusOut:
    """Set a calendar only for the exact Google connection the admin saw.

    The igreja row is locked before comparing the opaque connection revision.
    Thus a request from account A that waits behind a finish switching to B is
    rejected after the lock is released instead of storing A's calendar under B.
    """
    sync = _locked_sync_for(db, uuid.UUID(current_user.igreja_id))
    if not _connected(sync):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Agenda não conectada"
        )
    selection_version = _selection_version(sync)
    if (
        selection_version is None
        or payload.connectionVersion is None
        or payload.connectionVersion != selection_version
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A conexão da agenda mudou. Atualize a página e selecione novamente.",
        )
    sync.google_calendar_id = payload.calendarId
    sync.atualizado_em = dt.datetime.now(dt.timezone.utc)
    db.commit()
    return StatusOut(
        connected=True,
        calendarId=sync.google_calendar_id,
        googleAccountEmail=sync.google_account_email,
        connectionVersion=_selection_version(sync),
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> None:
    """Disconnect the igreja's Google Calendar (drops stored tokens)."""
    sync = _locked_sync_for(db, uuid.UUID(current_user.igreja_id))
    if sync is not None:
        db.delete(sync)
        db.commit()
    return None


# ---------------------------------------------------------------------------
# EVT-7 PR2 — destinatários de alerta da Agenda (admin-only, tenant-scoped)
#
# Config explícita de quem recebe os avisos internos da Agenda por WhatsApp,
# independente de papel / AppUser.pessoa_id (ver ADR EVT-7-destinatarios-alerta).
# Estes endpoints só CONFIGURAM — nada é enviado aqui (o envio é do event_notify,
# atrás da flag AGENDA_NOTIFY_ENABLED). `telefone` é guardado normalizado
# (só-dígitos), como conversations.telefone.
# ---------------------------------------------------------------------------
class RecipientOut(BaseModel):
    id: str
    nome: str
    telefone: str
    ativo: bool

    @classmethod
    def from_model(cls, r: AgendaAlertRecipient) -> "RecipientOut":
        return cls(id=str(r.id), nome=r.nome, telefone=r.telefone, ativo=r.ativo)


class RecipientListOut(BaseModel):
    recipients: list[RecipientOut]


class CreateRecipientRequest(BaseModel):
    nome: str = Field(min_length=1, max_length=200)
    telefone: str = Field(min_length=1, max_length=40)

    @field_validator("nome")
    @classmethod
    def _nome(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("nome obrigatório")
        return value

    @field_validator("telefone")
    @classmethod
    def _telefone(cls, value: str) -> str:
        canonical = normalize_phone(value)
        if not canonical:
            raise ValueError("telefone deve conter dígitos")
        return canonical


class UpdateRecipientRequest(BaseModel):
    """Edição parcial de um destinatário (EVT-7 PR2). None = inalterado."""

    nome: str | None = Field(default=None, max_length=200)
    telefone: str | None = Field(default=None, max_length=40)
    ativo: bool | None = None

    @field_validator("nome")
    @classmethod
    def _nome(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("nome não pode ser vazio")
        return value

    @field_validator("telefone")
    @classmethod
    def _telefone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        canonical = normalize_phone(value)
        if not canonical:
            raise ValueError("telefone deve conter dígitos")
        return canonical


def _recipient_for(
    db: Session, current_user: CurrentUser, recipient_id: str
) -> AgendaAlertRecipient:
    """Busca um destinatário do tenant por id ou levanta 404 (RLS + igreja_id)."""
    try:
        rid = uuid.UUID(recipient_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Destinatário não encontrado"
        ) from exc
    recipient = db.execute(
        select(AgendaAlertRecipient).where(
            AgendaAlertRecipient.id == rid,
            AgendaAlertRecipient.igreja_id == uuid.UUID(current_user.igreja_id),
        )
    ).scalar_one_or_none()
    if recipient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Destinatário não encontrado"
        )
    return recipient


def _active_dup_exists(
    db: Session, igreja_id: uuid.UUID, telefone: str, *, exclude_id: uuid.UUID | None
) -> bool:
    """Já existe outro destinatário ATIVO com esse telefone nesta igreja?

    Espelha o índice único parcial (igreja_id, telefone) WHERE ativo — devolve um
    409 limpo em vez de deixar o INSERT/UPDATE estourar IntegrityError.
    """
    rows = db.execute(
        select(AgendaAlertRecipient.id).where(
            AgendaAlertRecipient.igreja_id == igreja_id,
            AgendaAlertRecipient.telefone == telefone,
            AgendaAlertRecipient.ativo.is_(True),
        )
    ).scalars().all()
    return any(rid != exclude_id for rid in rows)


@router.get("/recipients", response_model=RecipientListOut)
def list_recipients(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> RecipientListOut:
    """Lista os destinatários de alerta da igreja (ativos e inativos)."""
    rows = db.execute(
        select(AgendaAlertRecipient)
        .where(AgendaAlertRecipient.igreja_id == uuid.UUID(current_user.igreja_id))
        .order_by(AgendaAlertRecipient.created_at.asc())
    ).scalars().all()
    return RecipientListOut(recipients=[RecipientOut.from_model(r) for r in rows])


@router.post("/recipients", response_model=RecipientOut)
def create_recipient(
    payload: CreateRecipientRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> RecipientOut:
    """Cadastra um destinatário de alerta (opt-in). Nada é enviado aqui."""
    igreja_uuid = uuid.UUID(current_user.igreja_id)
    if _active_dup_exists(db, igreja_uuid, payload.telefone, exclude_id=None):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um destinatário ativo com esse telefone",
        )
    recipient = AgendaAlertRecipient(
        igreja_id=igreja_uuid,
        nome=payload.nome,
        telefone=payload.telefone,
    )
    db.add(recipient)
    db.flush()
    db.refresh(recipient)
    db.commit()
    return RecipientOut.from_model(recipient)


@router.put("/recipients/{recipient_id}", response_model=RecipientOut)
def update_recipient(
    recipient_id: str,
    payload: UpdateRecipientRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> RecipientOut:
    """Edita/desativa um destinatário (parcial). Campos None ficam inalterados."""
    recipient = _recipient_for(db, current_user, recipient_id)

    novo_telefone = payload.telefone if payload.telefone is not None else recipient.telefone
    novo_ativo = payload.ativo if payload.ativo is not None else recipient.ativo
    if novo_ativo and _active_dup_exists(
        db, recipient.igreja_id, novo_telefone, exclude_id=recipient.id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um destinatário ativo com esse telefone",
        )

    if payload.nome is not None:
        recipient.nome = payload.nome
    if payload.telefone is not None:
        recipient.telefone = payload.telefone
    if payload.ativo is not None:
        recipient.ativo = payload.ativo
    recipient.updated_at = dt.datetime.now(dt.timezone.utc)

    db.flush()
    db.refresh(recipient)
    db.commit()
    return RecipientOut.from_model(recipient)


@router.delete("/recipients/{recipient_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recipient(
    recipient_id: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_role(["admin"])),
) -> Response:
    """Remove um destinatário de alerta do tenant (RLS + igreja_id)."""
    recipient = _recipient_for(db, current_user, recipient_id)
    db.delete(recipient)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
