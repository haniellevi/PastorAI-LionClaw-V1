"""Application settings loaded from environment variables.

Centralizes configuration and validates required variables at startup
(SPEC 5.3 / .env.example). Secrets are never logged.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    google_calendar_access_token: str = Field(default="")
    # Target calendar id; defaults to the primary calendar of the credential.
    google_calendar_id: str = Field(default="primary")

    # ---- SLA engine + cron worker (O5) --------------------------------------
    # Seconds between cron_worker ticks (SLA scan + cron dispatch).
    cron_tick_seconds: int = Field(default=300, ge=10)
    # Default model used by the panel assistant (api-assistant) when an igreja
    # has not overridden it. The assistant is a separate channel from the
    # WhatsApp orchestrator but reuses the igreja's BYO LLM credential.
    assistant_default_model: str = Field(default="gpt-4o-mini")

    @property
    def cors_origins(self) -> list[str]:
        """Allowed CORS origins. Frontend URL plus base URL in dev.

        Trailing slashes are stripped: browsers send the ``Origin`` header
        as scheme+host+port with no path, so a configured ``https://host/``
        would never match the browser-sent ``https://host`` and every
        cross-origin auth call (login, forgot-password) would be rejected.
        """
        origins = {self.frontend_url.rstrip("/"), self.app_base_url.rstrip("/")}
        # O console master tem subdomínio dedicado (admin.<dominio>), servido
        # pela MESMA app na Vercel. Libera-o automaticamente junto do
        # app.<dominio>, senão o login do console (POST /admin/login) feito a
        # partir de admin.igreja12.com.br cai em CORS (origem diferente).
        for origin in list(origins):
            if "://app." in origin:
                origins.add(origin.replace("://app.", "://admin.", 1))
        return [o for o in origins if o]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def effective_jwks_url(self) -> str:
        """Resolved JWKS endpoint for Clerk token verification."""
        if self.clerk_jwks_url:
            return self.clerk_jwks_url
        if self.clerk_jwt_issuer:
            return f"{self.clerk_jwt_issuer.rstrip('/')}/.well-known/jwks.json"
        return ""

    @property
    def effective_session_secret(self) -> str:
        """Secret used to sign/verify PastorAI's own session JWTs."""
        return self.session_jwt_secret or self.clerk_secret_key

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str) -> str:
        # SQLAlchemy expects the psycopg2 driver scheme explicitly.
        if value and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg2://", 1)
        return value

    def assert_production_ready(self) -> None:
        """Validate that critical secrets are present in production.

        Called at startup. In non-production environments we tolerate missing
        values so the app and tests can boot, but in production a missing secret
        is a hard failure (explicit, fail-fast).
        """
        if not self.is_production:
            return

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
        }
        missing = [name for name, val in required.items() if not val]
        if missing:
            raise RuntimeError(
                "Missing required environment variables for production: "
                + ", ".join(sorted(missing))
            )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (one read per process)."""
    return Settings()
