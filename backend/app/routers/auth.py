"""Auth router — api-login (SPEC 3.2: POST /auth/login -> {token, churchId}).

Login authenticates email+password via Clerk (RNF-01: no passwords stored),
resolves the linked igreja and returns a session token plus the churchId.

Security:
  - Invalid credentials return a single generic error that never reveals
    whether the email exists (US-01).
  - A suspended/delinquent igreja blocks login with a billing notice (US-35).
  - A valid Clerk account with no linked app_user is rejected clearly (US-02).
"""

from __future__ import annotations

import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AppUser, Pessoa
from app.db.session import get_db
from app.deps import (
    BLOCKING_IGREJA_STATUSES,
    REVOKED_USER_STATUS,
    CurrentUser,
    get_current_user,
)
from app.domain.phone import normalize_phone, phone_suffix
from app.routers._common import ensure_tenant_context
from app.services.brevo import BrevoClient, BrevoError, get_brevo_client
from app.services.clerk import ClerkAuthError, ClerkClient, get_clerk_client

logger = logging.getLogger("pastorai.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

# Pragmatic email shape check (avoids an extra email-validator dependency).
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Single generic message — must not distinguish unknown email vs wrong password.
_GENERIC_LOGIN_ERROR = "E-mail ou senha inválidos"


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


class LoginResponse(BaseModel):
    """Login success contract."""

    token: str
    churchId: str  # noqa: N815 - external contract uses camelCase


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


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
    clerk: ClerkClient = Depends(get_clerk_client),
) -> LoginResponse:
    """Authenticate and return {token, churchId}.

    Failure modes return the same generic 401 to avoid leaking which emails
    exist; billing blocks return a distinct 403 with billing context.
    """
    try:
        token, clerk_user_id = clerk.authenticate_password(
            payload.email, payload.password
        )
    except ClerkAuthError:
        # Generic — never reveals whether the email is registered.
        raise _unauthorized() from None

    app_user = db.execute(
        select(AppUser).where(AppUser.clerk_user_id == clerk_user_id)
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
    if igreja_status in BLOCKING_IGREJA_STATUSES:
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

    return LoginResponse(token=token, churchId=str(app_user.igreja_id))


@router.post("/forgot-password")
def forgot_password(
    payload: ForgotPasswordRequest,
    clerk: ClerkClient = Depends(get_clerk_client),
    mailer: BrevoClient = Depends(get_brevo_client),
) -> dict[str, str]:
    """Send a password-reset link if the e-mail exists — always returns 200.

    Never reveals whether the e-mail is registered (US-01): the response is the
    same with or without a matching user. The send is best-effort.
    """
    try:
        clerk_user_id = clerk.find_user_id_by_email(payload.email)
    except ClerkAuthError:
        clerk_user_id = None

    if clerk_user_id:
        token = clerk.mint_reset_token(clerk_user_id)
        base = get_settings().frontend_url.rstrip("/")
        link = f"{base}/#redefinir-senha/{token}"
        try:
            mailer.send_password_reset(to_email=payload.email, reset_link=link)
        except BrevoError:
            logger.warning("Password-reset e-mail failed to send")

    return {"status": "ok"}


@router.post("/reset-password")
def reset_password(
    payload: ResetPasswordRequest,
    clerk: ClerkClient = Depends(get_clerk_client),
) -> dict[str, str]:
    """Set a new password from a valid reset token."""
    try:
        clerk_user_id = clerk.verify_reset_token(payload.token)
    except ClerkAuthError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Link inválido ou expirado. Peça um novo.",
        ) from None
    try:
        clerk.set_user_password(clerk_user_id, payload.password)
    except ClerkAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível redefinir a senha. Tente novamente.",
        ) from exc
    return {"status": "ok"}


def _resolve_invite(token: str, db: Session, clerk: ClerkClient) -> AppUser:
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

    app_user = db.execute(
        select(AppUser).where(AppUser.id == au_uuid)
    ).scalar_one_or_none()
    if app_user is None:
        raise invalid
    if app_user.clerk_user_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este convite já foi ativado. Faça login normalmente.",
        )
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


def _complete_cadastro_pessoa(
    db: Session, app_user: AppUser, telefone_raw: str, normalized: str
) -> None:
    """Parte B: cria/vincula a Pessoa-membro do convidado na ativação.

    Pré-login (service role / BYPASSRLS), por isso TODA query é escopada
    explicitamente por ``app_user.igreja_id``. Dedup canônico por telefone
    (mesmo critério de create_contact): se já existe uma Pessoa com esse número
    na igreja, vincula a ela (adotando a célula pendente só se ela ainda não tem
    célula — não transfere); senão cria a Pessoa-membro na célula pendente.
    """
    igreja_uuid = app_user.igreja_id
    celula_id = app_user.celula_pendente_id

    stored_digits = func.regexp_replace(Pessoa.telefone, r"\D", "", "g")
    candidates = db.execute(
        select(Pessoa).where(
            Pessoa.igreja_id == igreja_uuid,
            func.right(stored_digits, 8) == phone_suffix(normalized),
        )
    ).scalars().all()
    existing = next(
        (p for p in candidates if normalize_phone(p.telefone) == normalized),
        None,
    )

    if existing is not None:
        app_user.pessoa_id = existing.id
        if existing.celula_id is None and celula_id is not None:
            existing.celula_id = celula_id
    else:
        pessoa = Pessoa(
            igreja_id=igreja_uuid,
            nome=app_user.nome,
            telefone=telefone_raw.strip(),
            email=app_user.email,
            tipo="membro",
            celula_id=celula_id,
        )
        db.add(pessoa)
        db.flush()  # fires person/cell triggers; assigns id
        app_user.pessoa_id = pessoa.id

    app_user.celula_pendente_id = None


@router.post("/activate")
def activate(
    payload: ActivateRequest,
    db: Session = Depends(get_db),
    clerk: ClerkClient = Depends(get_clerk_client),
) -> dict[str, str]:
    """Ativa o convite: cria o acesso no Clerk + define a senha + vincula.

    Parte B (delta-049): quando o convidado ainda não é Pessoa, o telefone é
    obrigatório e a ativação cria/vincula a Pessoa-membro na célula pendente.
    Idempotência: um convite já ativado (app_user com clerk_user_id) → 409.
    """
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

    try:
        clerk_user_id = clerk.create_user(app_user.email, payload.password)
    except ClerkAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Não foi possível criar o acesso. Tente novamente.",
        ) from exc

    if needs_cadastro:
        _complete_cadastro_pessoa(db, app_user, payload.telefone or "", normalized)

    app_user.clerk_user_id = clerk_user_id
    app_user.status = "ativo"
    db.commit()
    return {"status": "ok"}


@router.get("/me", response_model=MeResponse)
def me(current_user: CurrentUser = Depends(get_current_user)) -> MeResponse:
    """Return the resolved identity for the current session token."""
    return MeResponse(
        appUserId=current_user.app_user_id,
        churchId=current_user.igreja_id,
        email=current_user.email,
        nome=current_user.nome,
        chatNome=current_user.chat_nome,
        roles=sorted(current_user.roles),
        isOwner=current_user.is_owner,
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
    ensure_tenant_context(db, current_user)
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
    )


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    clerk: ClerkClient = Depends(get_clerk_client),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, str]:
    """Troca a própria senha. Exige a senha atual, verificada no Clerk."""
    try:
        clerk.authenticate_password(current_user.email, payload.currentPassword)
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
    return {"status": "ok"}
