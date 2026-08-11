"""Auth router — api-login (SPEC 3.2: POST /auth/login -> {token, churchId}).

Login authenticates email+password via Clerk (RNF-01: no passwords stored),
resolves the linked igreja and returns a session token plus the churchId.

Security:
  - Invalid credentials return a single generic error that never reveals
    whether the email exists (US-01).
  - A suspended igreja blocks login; a delinquent owner receives a restricted
    session so the debt can be recovered (US-35).
  - A valid Clerk account with no linked app_user is rejected clearly (US-02).
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, noload

from app.config import get_settings
from app.db.models import AppUser, PasswordResetToken, Pessoa, UserRole
from app.db.session import get_db
from app.deps import (
    BLOCKING_IGREJA_STATUSES,
    REVOKED_USER_STATUS,
    CurrentUser,
    get_billing_recovery_user,
    get_current_user,
)
from app.domain.phone import normalize_phone, phone_suffix
from app.services.pessoa_dedup import (
    insert_pessoa_or_get_winner,
    lock_canonical_phone,
)
from app.services.brevo import BrevoClient, BrevoError, get_brevo_client
from app.services.cell_leadership import sync_role_after_activation
from app.services.clerk import (
    ClerkAuthError,
    ClerkClient,
    ClerkUnavailableError,
    get_clerk_client,
)
from app.services.rate_limit import RateLimiter, get_rate_limiter
from app.services.storage import logo_public_url

logger = logging.getLogger("pastorai.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

# Pragmatic email shape check (avoids an extra email-validator dependency).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Single generic message — must not distinguish unknown email vs wrong password.
_GENERIC_LOGIN_ERROR = "E-mail ou senha inválidos"
_AUTH_UNAVAILABLE = "Serviço de autenticação temporariamente indisponível"


class LoginRequest(BaseModel):
    """Login payload validated at the edge."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not _EMAIL_RE.match(value):
            raise ValueError("E-mail inválido")
        return value


class ForgotPasswordRequest(BaseModel):
    """Forgot-password payload (only an e-mail)."""

    email: str = Field(min_length=3, max_length=320)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class ResetPasswordRequest(BaseModel):
    """Reset payload: the link token + the new password."""

    token: str = Field(min_length=1)
    password: str = Field(min_length=8, max_length=256)


class InviteInfoResponse(BaseModel):
    """Dados do convite para a tela de ativação pré-preencher."""

    nome: str
    email: str
    igreja: str
    # Parte B (delta-049): o convidado ainda não é Pessoa — a ativação precisa
    # coletar o telefone/WhatsApp para completar o cadastro como membro.
    precisaCadastro: bool = False  # noqa: N815


class ActivateRequest(BaseModel):
    """Ativação: token do convite + senha escolhida (+ telefone na Parte B)."""

    token: str = Field(min_length=1)
    password: str = Field(min_length=8, max_length=256)
    telefone: str | None = Field(default=None, max_length=40)


class MeResponse(BaseModel):
    """Authenticated principal snapshot (handy for the frontend bootstrap)."""

    appUserId: str  # noqa: N815
    churchId: str  # noqa: N815
    email: str
    nome: str
    chatNome: str | None = None  # noqa: N815 - nome de exibição no chat (assinatura)
    roles: list[str]
    isOwner: bool = False  # noqa: N815 - dono (admin principal) da igreja (#4)
    # Missão 4 (branding): nome da igreja (fallback textual) + logo customizada.
    igrejaNome: str | None = None  # noqa: N815
    igrejaLogoUrl: str | None = None  # noqa: N815


class LoginResponse(MeResponse):
    """Login success contract, including the authenticated profile."""

    token: str


class UpdateMeRequest(BaseModel):
    """Edição do próprio perfil: nome da conta e/ou nome de exibição no chat.

    Semântica PATCH: campos ausentes (None) não mudam. `chatNome` vazio limpa a
    assinatura (volta a usar o nome da conta).
    """

    nome: str | None = Field(default=None, max_length=200)
    chatNome: str | None = Field(default=None, max_length=80)  # noqa: N815

    @field_validator("nome")
    @classmethod
    def _nome(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("nome não pode ser vazio")
        return value

    @field_validator("chatNome")
    @classmethod
    def _chat_nome(cls, value: str | None) -> str | None:
        # Mantém "" (sinal de limpar -> NULL no banco); só apara espaços.
        return value.strip() if value is not None else None


class ChangePasswordRequest(BaseModel):
    """Troca da própria senha — exige a senha atual."""

    currentPassword: str = Field(min_length=1, max_length=256)  # noqa: N815
    newPassword: str = Field(min_length=8, max_length=256)  # noqa: N815


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_GENERIC_LOGIN_ERROR,
    )


def _mark_password_changed(db: Session, clerk_user_id: str) -> None:
    """Registra `password_changed_at` (SEC-3A/MEDIO-002).

    Invalida sessões (JWT próprio) emitidas antes deste instante — ver o check
    em `app/deps.py`. Sem app_user vinculado a esse clerk_user_id (ex.: conta
    Clerk ainda não linkada a nenhuma igreja) não há sessão pra invalidar;
    segue silencioso, sem revelar o estado da conta.
    """
    app_user = db.execute(
        select(AppUser).where(AppUser.clerk_user_id == clerk_user_id)
    ).scalar_one_or_none()
    if app_user is None:
        return
    app_user.password_changed_at = datetime.now(timezone.utc)
    db.commit()


def _login_profile(db: Session, app_user: AppUser) -> MeResponse:
    """Build the same principal snapshot returned by ``GET /auth/me``."""
    roles = db.execute(
        select(UserRole.papel).where(UserRole.user_id == app_user.id)
    ).scalars().all()
    igreja = app_user.igreja
    return MeResponse(
        appUserId=str(app_user.id),
        churchId=str(app_user.igreja_id),
        email=app_user.email,
        nome=app_user.nome,
        chatNome=app_user.chat_nome,
        roles=sorted(roles),
        isOwner=bool(igreja and igreja.dono_id == app_user.id),
        igrejaNome=igreja.nome if igreja else None,
        igrejaLogoUrl=logo_public_url(igreja.logo_path if igreja else None),
    )


def _authentication_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_AUTH_UNAVAILABLE,
    )


@router.post("/login", response_model=LoginResponse)
def login(
    request: Request,
    payload: LoginRequest,
    db: Session = Depends(get_db),
    clerk: ClerkClient = Depends(get_clerk_client),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> LoginResponse:
    """Authenticate and return the token plus the bootstrap profile.

    Failure modes return the same generic 401 to avoid leaking which emails
    exist; billing blocks return a distinct 403 with billing context.
    Rate-limited by IP and by account (ALTO-002) before any Clerk call.
    """
    settings = get_settings()
    limiter.enforce_ip(request, "login", settings.rate_limit_login_ip_limit)
    limiter.enforce_account(
        payload.email, "login", settings.rate_limit_login_account_limit
    )
    try:
        token, clerk_user_id = clerk.authenticate_password(
            payload.email, payload.password
        )
    except ClerkUnavailableError:
        raise _authentication_unavailable() from None
    except ClerkAuthError:
        # Generic — never reveals whether the email is registered.
        raise _unauthorized() from None

    app_user = db.execute(
        select(AppUser)
        .options(noload(AppUser.roles))
        .where(AppUser.clerk_user_id == clerk_user_id)
    ).scalar_one_or_none()

    if app_user is None:
        # Authenticated at Clerk but not linked to an igreja: keep it generic
        # at login to avoid disclosing account state to anonymous callers.
        logger.info("Login with no linked app_user for clerk_user_id (masked)")
        raise _unauthorized() from None

    if app_user.status == REVOKED_USER_STATUS:
        # Access revoked (RF-04): no token is issued. Generic 401 — does not
        # disclose that the account exists but was revoked (US-01).
        logger.info("Login attempt by revoked app_user (masked)")
        raise _unauthorized() from None

    igreja_status = app_user.igreja.status if app_user.igreja else None
    delinquent_owner = bool(
        igreja_status == "inadimplente"
        and app_user.igreja
        and app_user.igreja.dono_id == app_user.id
    )
    if igreja_status in BLOCKING_IGREJA_STATUSES and not delinquent_owner:
        pending = igreja_status == "aguardando_aprovacao"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "pending_approval" if pending else "billing_blocked",
                "message": (
                    "Cadastro em análise — o acesso é liberado assim que a "
                    "plataforma aprovar a sua igreja."
                    if pending
                    else "Acesso bloqueado por pendência de assinatura. "
                    "Contate o administrador da igreja."
                ),
                "igrejaStatus": igreja_status,
            },
        )

    profile = _login_profile(db, app_user)
    return LoginResponse(token=token, **profile.model_dump())


@router.post("/forgot-password")
def forgot_password(
    request: Request,
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
    clerk: ClerkClient = Depends(get_clerk_client),
    mailer: BrevoClient = Depends(get_brevo_client),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> dict[str, str]:
    """Send a password-reset link if the e-mail exists — always returns 200.

    Never reveals whether the e-mail is registered (US-01): the response is the
    same with or without a matching user. The send is best-effort. Rate-limited
    by IP and by account (ALTO-002) — the 429, when it happens, is identical
    regardless of whether the account exists. Records the token's `jti` +
    expiry (SEC-3B/MEDIO-003) so it can be redeemed at most once.
    """
    settings = get_settings()
    limiter.enforce_ip(
        request, "forgot-password", settings.rate_limit_forgot_password_ip_limit
    )
    limiter.enforce_account(
        payload.email,
        "forgot-password",
        settings.rate_limit_forgot_password_account_limit,
    )
    try:
        clerk_user_id = clerk.find_user_id_by_email(payload.email)
    except ClerkAuthError:
        clerk_user_id = None

    if clerk_user_id:
        token, jti, expires_at = clerk.mint_reset_token(clerk_user_id)
        db.add(
            PasswordResetToken(
                jti=uuid.UUID(jti),
                clerk_user_id=clerk_user_id,
                expires_at=expires_at,
            )
        )
        db.commit()
        base = get_settings().frontend_url.rstrip("/")
        link = f"{base}/#redefinir-senha/{token}"
        try:
            mailer.send_password_reset(to_email=payload.email, reset_link=link)
        except BrevoError:
            logger.warning("Password-reset e-mail failed to send")

    return {"status": "ok"}


@router.post("/reset-password")
def reset_password(
    request: Request,
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
    clerk: ClerkClient = Depends(get_clerk_client),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> dict[str, str]:
    """Set a new password from a valid reset token.

    Rate-limited by IP (ALTO-002) — there is no e-mail in this payload, only
    the opaque reset token, so an account-scoped limit does not apply here.
    The JWT signature/expiry only proves the link was minted by us and hasn't
    expired; single-use (SEC-3B/MEDIO-003) is enforced by claiming the token's
    `password_reset_tokens` row (`SELECT ... FOR UPDATE` then `used_at = now()`)
    BEFORE calling Clerk, so two concurrent requests with the same link can't
    both succeed and a previously-redeemed link can't be replayed. Marks
    `password_changed_at` (SEC-3A/MEDIO-002) so any session issued before this
    reset stops being accepted.
    """
    settings = get_settings()
    limiter.enforce_ip(
        request, "reset-password", settings.rate_limit_reset_password_ip_limit
    )
    invalid = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Link inválido ou expirado. Peça um novo.",
    )
    try:
        clerk_user_id, jti = clerk.verify_reset_token(payload.token)
    except ClerkAuthError:
        raise invalid from None

    token_row = db.execute(
        select(PasswordResetToken)
        .where(PasswordResetToken.jti == uuid.UUID(jti))
        .with_for_update()
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if token_row is None or token_row.used_at is not None or token_row.expires_at <= now:
        raise invalid
    # Security trade-off: claim before Clerk call prevents replay; a downstream Clerk failure burns the link and user must request a new one.
    token_row.used_at = now
    db.commit()

    try:
        clerk.set_user_password(clerk_user_id, payload.password)
    except ClerkAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível redefinir a senha. Tente novamente.",
        ) from exc
    _mark_password_changed(db, clerk_user_id)
    return {"status": "ok"}


def _resolve_invite(
    token: str,
    db: Session,
    clerk: ClerkClient,
    *,
    for_update: bool = False,
) -> AppUser:
    """Valida o token de convite e devolve o app_user 'convidado' alvo.

    Pré-login (sem sessão): roda como o role de conexão, então acha o app_user
    de qualquer igreja pelo id do token — que é assinado, logo não forjável.
    """
    invalid = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Convite inválido ou expirado. Peça um novo.",
    )
    try:
        app_user_id = clerk.verify_invite_token(token)
        au_uuid = uuid.UUID(app_user_id)
    except (ClerkAuthError, ValueError):
        raise invalid from None

    statement = select(AppUser).where(AppUser.id == au_uuid)
    if for_update:
        # AppUser.igreja é eager via LEFT JOIN; limitar o lock evita o erro do
        # PostgreSQL ao tentar travar o lado anulável do outer join.
        statement = statement.with_for_update(of=AppUser)
    app_user = db.execute(statement).scalar_one_or_none()
    if app_user is None:
        raise invalid
    if app_user.clerk_user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este convite já foi ativado. Faça login normalmente.",
        )
    # Um token antigo nunca reabre acesso revogado. Somente a máquina de estado
    # convidado -> ativo é válida; a resposta genérica não revela o status.
    if app_user.status != "convidado":
        raise invalid
    return app_user


@router.get("/invite/{token}", response_model=InviteInfoResponse)
def invite_info(
    token: str,
    db: Session = Depends(get_db),
    clerk: ClerkClient = Depends(get_clerk_client),
) -> InviteInfoResponse:
    """Valida o token do convite e devolve dados para a tela de ativação."""
    app_user = _resolve_invite(token, db, clerk)
    return InviteInfoResponse(
        nome=app_user.nome,
        email=app_user.email,
        igreja=app_user.igreja.nome if app_user.igreja else "",
        precisaCadastro=app_user.pessoa_id is None,
    )


def _lock_pessoa_and_assert_unique_access(
    db: Session, *, app_user: AppUser, pessoa_id: uuid.UUID
) -> Pessoa:
    """Trava/revalida a Pessoa e impede um segundo acesso ao mesmo cadastro."""

    pessoa = db.execute(
        select(Pessoa)
        .where(
            Pessoa.id == pessoa_id,
            Pessoa.igreja_id == app_user.igreja_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não foi possível vincular este convite ao cadastro",
        )
    # O domínio pode mudar entre a emissão e o clique. Um convite antigo não
    # reabre acesso para Pessoa arquivada ou classificada como CSIM.
    if (
        getattr(pessoa, "arquivada_em", None) is not None
        or bool(getattr(pessoa, "sem_interesse", False))
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este cadastro não está disponível para acesso ao painel",
        )
    linked = db.execute(
        select(AppUser.id)
        .where(
            AppUser.igreja_id == app_user.igreja_id,
            AppUser.pessoa_id == pessoa_id,
            AppUser.id != app_user.id,
        )
        .limit(1)
    ).scalar_one_or_none()
    if linked is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este cadastro já possui outro acesso ao painel",
        )
    return pessoa


def _lock_invite_for_activation(db: Session, app_user_id: uuid.UUID) -> AppUser:
    """Trava e relê o convite depois da Pessoa, preservando a ordem de locks."""

    app_user = db.execute(
        select(AppUser)
        .where(AppUser.id == app_user_id)
        .with_for_update(of=AppUser)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if app_user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Convite inválido ou expirado. Peça um novo.",
        )
    if app_user.clerk_user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este convite já foi ativado. Faça login normalmente.",
        )
    if app_user.status != "convidado":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Convite inválido ou expirado. Peça um novo.",
        )
    return app_user


def _prepare_cadastro_pessoa(
    db: Session, app_user: AppUser, telefone_raw: str, normalized: str
) -> None:
    """Parte B: cria/vincula a Pessoa-membro do convidado na ativação.

    Pré-login (service role / BYPASSRLS), por isso TODA query é escopada
    explicitamente por ``app_user.igreja_id``. O telefone auto-declarado não
    prova identidade: se o dedupe canônico encontrar Pessoa existente, falha
    antes do Clerk e exige novo convite Parte A apontando ``pessoaId``. Parte B
    cria somente Pessoa nova, sempre sem vínculo de célula. O campo legado
    ``celula_pendente_id`` é descartado.
    """
    igreja_uuid = app_user.igreja_id

    lock_canonical_phone(db, igreja_id=igreja_uuid, canonical=normalized)

    stored_digits = func.regexp_replace(Pessoa.telefone, r"\D", "", "g")
    candidates = db.execute(
        select(Pessoa)
        .where(
            Pessoa.igreja_id == igreja_uuid,
            func.right(stored_digits, 8) == phone_suffix(normalized),
        )
        .order_by(Pessoa.id.asc())
        .with_for_update()
    ).scalars().all()
    # Histórico arquivado também reserva a identidade: nunca recriar/adotar
    # automaticamente só porque o telefone foi auto-declarado no convite.
    matches = [p for p in candidates if normalize_phone(p.telefone) == normalized]
    if matches:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Já existe uma pessoa com este telefone. Peça ao administrador "
                "um convite vinculado ao cadastro correto."
            ),
        )

    new_pessoa = Pessoa(
        igreja_id=igreja_uuid,
        nome=app_user.nome,
        telefone=telefone_raw.strip(),
        email=app_user.email,
        tipo="membro",
        celula_id=None,
    )
    pessoa = insert_pessoa_or_get_winner(
        db, new_pessoa, igreja_id=igreja_uuid, canonical=normalized
    )
    if str(pessoa.id) != str(new_pessoa.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Já existe uma pessoa com este telefone. Peça ao administrador "
                "um convite vinculado ao cadastro correto."
            ),
        )
    pessoa = _lock_pessoa_and_assert_unique_access(
        db, app_user=app_user, pessoa_id=pessoa.id
    )
    app_user.pessoa_id = pessoa.id

    app_user.celula_pendente_id = None


@router.post("/activate")
def activate(
    request: Request,
    payload: ActivateRequest,
    db: Session = Depends(get_db),
    clerk: ClerkClient = Depends(get_clerk_client),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> dict[str, str]:
    """Ativa o convite: cria o acesso no Clerk + define a senha + vincula.

    Parte B (delta-049): quando o convidado ainda não é Pessoa, o telefone é
    obrigatório e a ativação cria/vincula somente o cadastro de Pessoa. Mesmo
    convites legados com célula pendente não criam nem alteram membresia.
    Idempotência: um convite já ativado (app_user com clerk_user_id) → 409.
    Rate-limitada por IP (ALTO-002) — o token do convite já é o segredo
    validado abaixo; o limite aqui é só contra brute-force de tokens.
    """
    settings = get_settings()
    limiter.enforce_ip(request, "activate", settings.rate_limit_activate_ip_limit)
    app_user = _resolve_invite(payload.token, db, clerk)
    needs_cadastro = app_user.pessoa_id is None

    # Parte B: valida o telefone ANTES de criar a conta (evita conta órfã).
    normalized = ""
    if needs_cadastro:
        normalized = normalize_phone(payload.telefone or "")
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Informe um telefone/WhatsApp válido para concluir o cadastro.",
            )

    # Toda validação/mutação local possível acontece antes do Clerk. Se o
    # provedor falhar, rollback explícito desfaz Pessoa/vínculo preparados.
    try:
        if needs_cadastro:
            _prepare_cadastro_pessoa(
                db, app_user, payload.telefone or "", normalized
            )
        else:
            _lock_pessoa_and_assert_unique_access(
                db,
                app_user=app_user,
                pessoa_id=uuid.UUID(str(app_user.pessoa_id)),
            )
        # Ordem comum de concorrência: Pessoa -> AppUser. A releitura sob lock
        # fecha duas ativações do mesmo token, mesmo se enviarem telefones
        # diferentes (o advisory lock canônico cobre o mesmo telefone).
        app_user = _lock_invite_for_activation(
            db, uuid.UUID(str(app_user.id))
        )
    except HTTPException:
        db.rollback()
        raise

    try:
        clerk_existing = clerk.find_user_id_by_email(app_user.email)
    except ClerkAuthError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível validar o e-mail para ativação",
        ) from exc
    if clerk_existing is not None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este e-mail não está disponível para um novo acesso",
        )

    try:
        clerk_user_id = clerk.create_user(app_user.email, payload.password)
    except ClerkAuthError as exc:
        db.rollback()
        # Fecha a corrida lookup -> create sem reutilizar/redefinir senha.
        try:
            conflict_after_create = clerk.find_user_id_by_email(app_user.email)
        except ClerkAuthError:
            conflict_after_create = None
        if conflict_after_create is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Este e-mail não está disponível para um novo acesso",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível criar o acesso. Tente novamente.",
        ) from exc

    try:
        app_user.clerk_user_id = clerk_user_id
        app_user.status = "ativo"
        sync_role_after_activation(db, app_user=app_user)
        db.commit()
    except Exception:
        db.rollback()
        # create_user não reutiliza identidade: este id pertence à operação
        # corrente e pode ser apagado com segurança como compensação best-effort.
        try:
            clerk.delete_user(clerk_user_id)
        except ClerkAuthError:
            logger.error(
                "Activation Clerk compensation failed after database error",
                exc_info=True,
            )
        logger.exception("Activation database commit failed after Clerk mutation")
        raise
    return {"status": "ok"}


@router.get("/me", response_model=MeResponse)
def me(
    current_user: CurrentUser = Depends(get_billing_recovery_user),
) -> MeResponse:
    """Return the resolved identity for the current session token."""
    return MeResponse(
        appUserId=current_user.app_user_id,
        churchId=current_user.igreja_id,
        email=current_user.email,
        nome=current_user.nome,
        chatNome=current_user.chat_nome,
        roles=sorted(current_user.roles),
        isOwner=current_user.is_owner,
        igrejaNome=current_user.igreja_nome,
        igrejaLogoUrl=logo_public_url(current_user.igreja_logo_path),
    )


@router.patch("/me", response_model=MeResponse)
def update_me(
    payload: UpdateMeRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> MeResponse:
    """Atualiza os próprios dados de perfil: nome da conta e/ou nome de exibição.

    Tenant-scoped via RLS; cada usuário só edita o próprio app_user. Semântica
    PATCH: só os campos enviados mudam. `chatNome` vazio limpa a assinatura.
    """
    app_user = db.execute(
        select(AppUser).where(AppUser.id == uuid.UUID(current_user.app_user_id))
    ).scalar_one_or_none()

    nome = current_user.nome
    chat_nome = current_user.chat_nome
    if app_user is not None:
        if payload.nome is not None:
            app_user.nome = payload.nome
            nome = payload.nome
        if payload.chatNome is not None:
            app_user.chat_nome = payload.chatNome or None
            chat_nome = app_user.chat_nome
        db.commit()

    return MeResponse(
        appUserId=current_user.app_user_id,
        churchId=current_user.igreja_id,
        email=current_user.email,
        nome=nome,
        chatNome=chat_nome,
        roles=sorted(current_user.roles),
        isOwner=current_user.is_owner,
        igrejaNome=current_user.igreja_nome,
        igrejaLogoUrl=logo_public_url(current_user.igreja_logo_path),
    )


@router.post("/change-password")
def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    clerk: ClerkClient = Depends(get_clerk_client),
    current_user: CurrentUser = Depends(get_current_user),
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> dict[str, str]:
    """Troca a própria senha. Exige a senha atual, verificada no Clerk.

    Rate-limitada por IP e por conta (ALTO-002) — mesmo autenticada, essa rota
    aceita uma senha atual incorreta repetidamente e não pode virar um oráculo
    de brute-force contra a senha real. Marca `password_changed_at`
    (SEC-3A/MEDIO-002): a PRÓPRIA sessão usada nesta chamada também deixa de
    ser aceita a partir de agora — força um novo login após a troca.
    """
    settings = get_settings()
    limiter.enforce_ip(
        request, "change-password", settings.rate_limit_change_password_ip_limit
    )
    limiter.enforce_account(
        current_user.email,
        "change-password",
        settings.rate_limit_change_password_account_limit,
    )
    try:
        clerk.authenticate_password(current_user.email, payload.currentPassword)
    except ClerkUnavailableError:
        raise _authentication_unavailable() from None
    except ClerkAuthError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Senha atual incorreta",
        ) from None
    try:
        clerk.set_user_password(current_user.clerk_user_id, payload.newPassword)
    except ClerkAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível alterar a senha. Tente novamente.",
        ) from exc
    _mark_password_changed(db, current_user.clerk_user_id)
    return {"status": "ok"}
