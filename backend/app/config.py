"""Application settings loaded from environment variables.

Centralizes configuration and validates required variables at startup
(SPEC 5.3 / .env.example). Secrets are never logged.
"""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Minimum length (chars) for a dedicated production session secret (BAIXO-001).
MIN_SESSION_SECRET_LEN = 32

# Hostnames that are never acceptable as a production CORS origin (MEDIO-001).
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _is_valid_production_origin(url: str) -> bool:
    """True if ``url`` is usable as an explicit-https CORS origin in production.

    Rejects missing values, non-https schemes, missing/wildcard host, and
    loopback/localhost hosts (case-insensitive, incl. the 127.0.0.0/8 range and
    IPv6 ``::1``). A trailing slash alone is tolerated — browsers send the
    ``Origin`` header as scheme+host+port with no path, and ``cors_origins``
    already strips it (see test_config_cors.py: a stored trailing slash once
    broke every cross-origin auth call in production). Any other path, a
    query string or a fragment is rejected.
    """
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return False
    host = parsed.hostname
    if not host or host == "*":
        return False
    if host in _LOOPBACK_HOSTS or host.startswith("127."):
        return False
    if parsed.path not in ("", "/"):
        return False
    return not (parsed.query or parsed.fragment)


class Settings(BaseSettings):
    """Typed application settings.

    Values come from environment variables (or a local .env in development).
    Required variables that are missing will raise at startup, giving a clear
    and explicit failure instead of a runtime error deep in a request.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- App -----------------------------------------------------------------
    app_env: str = Field(default="development")
    app_base_url: str = Field(default="http://localhost:8000")
    frontend_url: str = Field(default="http://localhost:3000")

    # ---- Guard de envios externos (B2) --------------------------------------
    # Fora de produção, efeitos REAIS (WhatsApp, cobrança, e-mail, LLM, agenda)
    # ficam DESLIGADOS por padrão. Este flag liga-os explicitamente — use apenas
    # com credenciais de SANDBOX, nunca de produção. Ver external_sends_enabled.
    allow_real_sends: bool = Field(default=False)

    # ---- Agenda: aviso de confirmação (EVT-7 PR1) ---------------------------
    # Liga o aviso síncrono à equipe interna quando um evento é confirmado
    # (POST /events/{id}/confirm). Default OFF, inclusive em produção, até uma
    # env explícita ligar. Ortogonal ao guard B2: mesmo ligado, o envio real só
    # sai se external_sends_enabled também permitir (send_text respeita o guard).
    agenda_notify_enabled: bool = Field(default=False)

    # ---- Células: escrita sensível (Solicitações/Multiplicação, PR3-PR9) -----
    # Gate de rollout do fluxo Solicitação→Aprovação (criação/decisão/reenvio/
    # cancelamento/multiplicação). Default OFF, inclusive em produção, até o fluxo
    # estar validado ponta-a-ponta; liga por env explícita e, depois, gradual por
    # igreja. As LEITURAS de célula (reuniões, presença, materiais, avisos) NÃO
    # dependem deste flag. Espelha a disciplina do PLANO-IMPLEMENTACAO-CELULAS.
    celulas_requests_enabled: bool = Field(default=False)

    # ---- Clerk (Auth - US-01 / RNF-01) --------------------------------------
    clerk_publishable_key: str = Field(default="")
    clerk_secret_key: str = Field(default="")
    clerk_jwt_issuer: str = Field(default="")
    # Optional explicit JWKS url; derived from issuer when empty.
    clerk_jwks_url: str = Field(default="")

    # ---- Supabase / Postgres (US-02 / RNF-02) -------------------------------
    supabase_url: str = Field(default="")
    supabase_anon_key: str = Field(default="")
    supabase_service_role_key: str = Field(default="")
    database_url: str = Field(default="")

    # ---- Secrets encryption (RNF-03) ----------------------------------------
    secrets_encryption_key: str = Field(default="")

    # ---- Session token (panel session — backend-issued JWT) -----------------
    # PastorAI signs its own session JWT at login so the panel session is not
    # bound to Clerk's ~1 min session-token TTL. Falls back to clerk_secret_key
    # when empty, so no new required env var is introduced.
    session_jwt_secret: str = Field(default="")
    session_ttl_hours: int = Field(default=8, ge=1, le=720)
    # TTL do link de redefinição de senha (fluxo "esqueci a senha").
    password_reset_ttl_minutes: int = Field(default=30, ge=5, le=240)

    # ---- Evolution API (WhatsApp - US-05..US-08) ----------------------------
    evolution_api_url: str = Field(default="")
    evolution_api_key: str = Field(default="")
    # Shared secret used to validate inbound webhooks (HMAC or `?token=`).
    evolution_webhook_secret: str = Field(default="")
    # URL the Evolution instance calls back to deliver inbound events. The
    # backend registers it on the instance at connect time so a number paired
    # via the panel QR actually forwards messages (without this the instance is
    # "deaf"). Evolution v2 self-hosted has no custom webhook headers, so the
    # shared secret is appended as a `?token=` query param. Use the address
    # Evolution reaches the backend at — e.g. the internal container name on the
    # shared Docker network: http://pastorai_backend:8000/whatsapp/webhook
    evolution_webhook_callback_url: str = Field(default="")

    # ---- Worker / Filas (RNF-17) --------------------------------------------
    redis_url: str = Field(default="redis://localhost:6379/0")

    # ---- Agente Orquestrador / LLM BYO (US-08/US-27 / delta-034) ------------
    # Default OpenAI key is optional: each igreja brings its own encrypted key.
    openai_api_key: str = Field(default="")
    # LangGraph checkpoint store (RNF-08/15). Empty -> in-memory checkpointer.
    agent_graph_checkpoint_url: str = Field(default="")
    # Default model used by the orchestrator when an igreja has not overridden it.
    agent_default_model: str = Field(default="gpt-4o-mini")
    # Current LGPD consent term version (delta-040). Bumping it forces re-accept.
    agent_term_version: str = Field(default="v1")

    # ---- Asaas (billing/assinatura - US-36/RF-42) ---------------------------
    asaas_api_url: str = Field(default="https://api.asaas.com/v3")
    asaas_api_key: str = Field(default="")
    # Shared token used to validate inbound Asaas webhooks (asaas-access-token).
    asaas_webhook_token: str = Field(default="")
    # One-time setup fee charged on the first checkout (BRL).
    asaas_setup_fee: float = Field(default=0.0, ge=0)

    # ---- Brevo (ex-Sendinblue) — convites de equipe (RF-40) -----------------
    brevo_api_url: str = Field(default="https://api.brevo.com/v3")
    brevo_api_key: str = Field(default="")
    brevo_from_email: str = Field(default="no-reply@igreja12.com.br")
    brevo_from_name: str = Field(default="Igreja 12")

    # ---- Google Calendar (sync de eventos - RF-39) --------------------------
    google_calendar_api_url: str = Field(
        default="https://www.googleapis.com/calendar/v3"
    )
    # OAuth access token (or service-account derived token) with Calendar scope.
    # Legacy: used by the static GoogleCalendarClient. The events module (F1)
    # connects each igreja's own calendar via OAuth below instead.
    google_calendar_access_token: str = Field(default="")
    # Target calendar id; defaults to the primary calendar of the credential.
    google_calendar_id: str = Field(default="primary")

    # ---- Google OAuth 2.0 (conectar a agenda existente por igreja - eventos F1)
    google_oauth_client_id: str = Field(default="")
    google_oauth_client_secret: str = Field(default="")
    # Backend callback registrado no Google Cloud Console (ex.:
    # https://api.igreja12.com.br/calendar/callback).
    google_oauth_redirect_uri: str = Field(default="")
    google_oauth_auth_url: str = Field(
        default="https://accounts.google.com/o/oauth2/v2/auth"
    )
    google_oauth_token_url: str = Field(default="https://oauth2.googleapis.com/token")
    # Endpoint OIDC de userinfo — é ele que diz QUAL conta Google consentiu.
    # Default = o publicado no discovery document do Google.
    google_oauth_userinfo_url: str = Field(
        default="https://openidconnect.googleapis.com/v1/userinfo"
    )

    # ---- OAuth Calendar V1: origens de retorno do consentimento -------------
    # Conceito SEPARADO, mas necessariamente SUBCONJUNTO de `cors_origins`.
    # Aquela responde "quem pode chamar a API"; esta responde "quem hospeda o
    # card de Integrações" e é a ÚNICA fonte do redirect do callback. Uma origem
    # de retorno fora do CORS nunca conseguiria iniciar o fluxo no navegador.
    #
    # CSV e não `list[str]`: pydantic-settings parseia campos complexos vindos do
    # env como JSON, o que obrigaria `["https://..."]` no `.env` e quebraria a
    # convenção KEY=VALUE do arquivo inteiro.
    calendar_oauth_return_origins: str = Field(default="")
    # TTL de um fluxo OAuth em voo (minutos). Paridade com o TTL do state antigo.
    calendar_oauth_flow_ttl_minutes: int = Field(default=10, ge=1)

    # ---- SLA engine + cron worker (O5) --------------------------------------
    # Seconds between cron_worker ticks (SLA scan + cron dispatch).
    cron_tick_seconds: int = Field(default=300, ge=10)
    # Default model used by the panel assistant (api-assistant) when an igreja
    # has not overridden it. The assistant is a separate channel from the
    # WhatsApp orchestrator but reuses the igreja's BYO LLM credential.
    assistant_default_model: str = Field(default="gpt-4o-mini")

    # ---- Rate limiting nos endpoints de autenticação (ALTO-002) -------------
    # Kill switch de emergência: desliga todo o rate limiting de auth sem
    # precisar reverter deploy. Contadores de janela fixa no Redis já usado
    # pelo worker (REDIS_URL) — ver app/services/rate_limit.py.
    rate_limit_auth_enabled: bool = Field(default=True)
    rate_limit_window_seconds: int = Field(default=60, ge=1)
    # Bloqueio temporário aplicado à CONTA (não ao IP) ao estourar o limite —
    # encarece brute-force/credential-stuffing sem depender só da janela.
    rate_limit_block_seconds: int = Field(default=300, ge=1)
    rate_limit_login_ip_limit: int = Field(default=10, ge=1)
    rate_limit_login_account_limit: int = Field(default=5, ge=1)
    rate_limit_forgot_password_ip_limit: int = Field(default=5, ge=1)
    rate_limit_forgot_password_account_limit: int = Field(default=3, ge=1)
    rate_limit_reset_password_ip_limit: int = Field(default=10, ge=1)
    rate_limit_activate_ip_limit: int = Field(default=10, ge=1)
    rate_limit_change_password_ip_limit: int = Field(default=10, ge=1)
    rate_limit_change_password_account_limit: int = Field(default=5, ge=1)

    @property
    def cors_origins(self) -> list[str]:
        """Allowed CORS origins. Frontend URL plus base URL in dev.

        Trailing slashes are stripped: browsers send the ``Origin`` header
        as scheme+host+port with no path, so a configured ``https://host/``
        would never match the browser-sent ``https://host`` and every
        cross-origin auth call (login, forgot-password) would be rejected.
        """
        origins = {self.frontend_url.rstrip("/"), self.app_base_url.rstrip("/")}
        # As superfícies painel.<dominio> (console master) e admin.<dominio>
        # (admin da igreja) são servidas pela MESMA app na Vercel a partir do
        # app.<dominio>. Libera-as automaticamente, senão o login feito a partir
        # desses hosts (ex.: POST /admin/login, POST /auth/login) cai em CORS.
        for origin in list(origins):
            if "://app." in origin:
                origins.add(origin.replace("://app.", "://admin.", 1))
                origins.add(origin.replace("://app.", "://painel.", 1))
        return [o for o in origins if o]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def external_sends_enabled(self) -> bool:
        """Se efeitos externos reais podem disparar (guard B2).

        Produção permite; fora de produção fica bloqueado por padrão, a menos
        que ``ALLOW_REAL_SENDS`` seja ligado explicitamente (só com credenciais
        sandbox). É a trava dupla que protege local/staging de enviar WhatsApp,
        cobrar, mandar e-mail, gastar token de LLM ou mexer no Google Calendar.
        """
        return self.is_production or self.allow_real_sends

    @property
    def effective_jwks_url(self) -> str:
        """Resolved JWKS endpoint for Clerk token verification."""
        if self.clerk_jwks_url:
            return self.clerk_jwks_url
        if self.clerk_jwt_issuer:
            return f"{self.clerk_jwt_issuer.rstrip('/')}/.well-known/jwks.json"
        return ""

    @property
    def calendar_oauth_return_origin_allowlist(self) -> frozenset[str]:
        """Origens que podem receber o retorno do OAuth do Google Calendar.

        CSV; espaços em volta e barra final são normalizados. A validação no
        ``/calendar/connect`` é por IGUALDADE EXATA contra este conjunto — nunca
        prefixo, sufixo de domínio, ``Referer`` ou campo do cliente.
        """
        return frozenset(
            origin.strip().rstrip("/")
            for origin in self.calendar_oauth_return_origins.split(",")
            if origin.strip()
        )

    @property
    def effective_session_secret(self) -> str:
        """Secret used to sign/verify PastorAI's own session JWTs.

        Production requires a dedicated ``SESSION_JWT_SECRET`` (enforced by
        ``assert_production_ready``), so it never falls back to the Clerk secret
        there (BAIXO-001). Dev/test keep the fallback so they boot without an
        extra env var.
        """
        if self.is_production:
            return self.session_jwt_secret
        return self.session_jwt_secret or self.clerk_secret_key

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        # SQLAlchemy expects the psycopg2 driver scheme explicitly.
        if value and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg2://", 1)
        return value

    def assert_production_ready(self) -> None:
        """Validate that critical secrets/config are present in production.

        Called at startup. In non-production environments we tolerate missing
        values so the app and tests can boot, but in production a missing or
        insecure value is a hard failure (explicit, fail-fast). Covers the
        dedicated session secret (BAIXO-001) and explicit CORS origins
        (MEDIO-001) in addition to the base required secrets.
        """
        if not self.is_production:
            return

        problems: list[str] = []

        required = {
            "CLERK_SECRET_KEY": self.clerk_secret_key,
            "CLERK_JWT_ISSUER": self.clerk_jwt_issuer,
            "SUPABASE_URL": self.supabase_url,
            "SUPABASE_SERVICE_ROLE_KEY": self.supabase_service_role_key,
            "DATABASE_URL": self.database_url,
            "SECRETS_ENCRYPTION_KEY": self.secrets_encryption_key,
            "EVOLUTION_API_URL": self.evolution_api_url,
            "EVOLUTION_API_KEY": self.evolution_api_key,
            "EVOLUTION_WEBHOOK_SECRET": self.evolution_webhook_secret,
            "REDIS_URL": self.redis_url,
            # Dedicated backend session-signing secret (BAIXO-001).
            "SESSION_JWT_SECRET": self.session_jwt_secret,
        }
        problems += [f"missing {name}" for name, val in required.items() if not val]

        # SESSION_JWT_SECRET must be strong and must NOT reuse the Clerk secret
        # (BAIXO-001). Only checked when present; absence is already reported above.
        if self.session_jwt_secret:
            if len(self.session_jwt_secret) < MIN_SESSION_SECRET_LEN:
                problems.append(
                    f"SESSION_JWT_SECRET too short (min {MIN_SESSION_SECRET_LEN} chars)"
                )
            if self.session_jwt_secret == self.clerk_secret_key:
                problems.append("SESSION_JWT_SECRET must differ from CLERK_SECRET_KEY")

        # CORS origins must be explicit https hosts in production — never the
        # localhost defaults and never a wildcard with credentials (MEDIO-001).
        for name, url in (
            ("FRONTEND_URL", self.frontend_url),
            ("APP_BASE_URL", self.app_base_url),
        ):
            if not _is_valid_production_origin(url):
                problems.append(
                    f"{name} must be an explicit https URL "
                    "(no wildcard/localhost/loopback/path/query)"
                )

        # OAUTH-CALENDAR-V1: a allowlist de retorno é a única fonte do destino do
        # redirect do callback. Vazia em produção = fluxo OAuth ligado sem destino
        # válido, então falha fechada no boot em vez de 400 silencioso por request.
        allowlist = self.calendar_oauth_return_origin_allowlist
        if not allowlist:
            problems.append(
                "CALENDAR_OAUTH_RETURN_ORIGINS must list at least one origin"
            )
        api_origin = self.app_base_url.rstrip("/")
        cors_allowlist = set(self.cors_origins)
        for origin in sorted(allowlist):
            if not _is_valid_production_origin(origin):
                problems.append(
                    f"CALENDAR_OAUTH_RETURN_ORIGINS entry {origin!r} must be an "
                    "explicit https URL (no wildcard/localhost/loopback/path/query)"
                )
            if origin == api_origin:
                problems.append(
                    "CALENDAR_OAUTH_RETURN_ORIGINS must not include the API origin"
                )
            if origin not in cors_allowlist:
                problems.append(
                    "CALENDAR_OAUTH_RETURN_ORIGINS entries must also be "
                    f"CORS-enabled: {origin!r}"
                )
            if (urlparse(origin).hostname or "").lower().startswith("painel."):
                problems.append(
                    "CALENDAR_OAUTH_RETURN_ORIGINS must not include the painel.* "
                    "master-console origin"
                )

        if problems:
            raise RuntimeError(
                "Invalid production configuration: " + "; ".join(sorted(problems))
            )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (one read per process)."""
    return Settings()
