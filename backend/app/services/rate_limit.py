"""Rate limiting dos endpoints de autenticação (ALTO-002).

Limites por IP e por conta/e-mail aplicados aos endpoints de auth (login,
forgot-password, reset-password, activate, change-password). O estado é
distribuído no Redis (REDIS_URL) — o mesmo já usado pelo worker/SLA — via
contadores de janela fixa (INCR + EXPIRE), baratos e atômicos.

Princípios de segurança:

- **Não vaza existência de conta**: a chave por conta usa o e-mail *hasheado*
  (nunca PII em texto claro no Redis) e o 429 devolvido é sempre idêntico
  (mesmo corpo + Retry-After), com ou sem conta correspondente.
- **Backoff por conta**: ao exceder o limite, a conta entra em bloqueio
  temporário (``rate_limit_block_seconds``), encarecendo o brute-force.
- **Fail-open**: se o Redis estiver indisponível a requisição NÃO é bloqueada
  (indisponibilidade de infra não pode derrubar o login) — o erro é apenas
  logado. Rate limiting é defesa em profundidade, não o único controle de auth.

O handler HTTP que traduz :class:`RateLimitExceeded` em 429 fica em
``app/main.py`` (registrado uma única vez no boot).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from fastapi import Request

from app.config import get_settings

logger = logging.getLogger("pastorai.rate_limit")

# Prefixo das chaves no Redis (namespacing p/ não colidir com a fila do worker).
_KEY_PREFIX = "ratelimit"


class RateLimitExceeded(Exception):
    """Sinaliza que um limite foi excedido; carrega o Retry-After (segundos)."""

    def __init__(self, retry_after: int) -> None:
        # Nunca menos de 1s para o header Retry-After ser sempre útil/válido.
        self.retry_after = max(1, int(retry_after))
        super().__init__("rate limit exceeded")


def client_ip(request: Request) -> str:
    """Deriva o IP do cliente respeitando o proxy reverso (X-Forwarded-For).

    O backend roda atrás de proxy (VPS/Vercel), então ``request.client.host``
    seria o IP do proxy. Cada proxy no caminho ACRESCENTA o peer que observou
    ao final da lista de ``X-Forwarded-For`` (convenção padrão do Caddy/nginx)
    — o último hop não vazio é o mais próximo do nosso proxy e, portanto, o
    confiável; o primeiro valor é o que o cliente original mandou e pode ser
    forjado livremente (ex.: ``curl -H "X-Forwarded-For: 1.2.3.4"``), o que
    bypassaria o rate limit por IP se fosse usado. Cai em ``X-Real-IP`` e
    depois no peer direto quando não há um hop válido.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1]
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def _account_hash(account: str) -> str:
    """Hash estável do e-mail/conta — evita PII em texto claro nas chaves Redis."""
    normalized = account.strip().lower().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()[:32]


class RateLimiter:
    """Contadores de janela fixa no Redis com bloqueio temporário por conta."""

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client

    @property
    def _client(self) -> Any:
        if self._redis is None:
            self._redis = _build_redis()
        return self._redis

    # ---- API pública ---------------------------------------------------------
    def enforce_ip(self, request: Request, scope: str, limit: int) -> None:
        """Limita por IP dentro de ``scope`` (ex.: 'login', 'reset')."""
        settings = get_settings()
        if not settings.rate_limit_auth_enabled:
            return
        key = f"{scope}:ip:{client_ip(request)}"
        self._hit_window(
            key, limit=limit, window_seconds=settings.rate_limit_window_seconds
        )

    def enforce_account(self, account: str, scope: str, limit: int) -> None:
        """Limita por conta/e-mail com bloqueio temporário (backoff)."""
        settings = get_settings()
        if not settings.rate_limit_auth_enabled or not account:
            return
        key = f"{scope}:acct:{_account_hash(account)}"
        self._hit_with_block(
            key,
            limit=limit,
            window_seconds=settings.rate_limit_window_seconds,
            block_seconds=settings.rate_limit_block_seconds,
        )

    # ---- Internos -------------------------------------------------------------
    def _hit_window(self, key: str, *, limit: int, window_seconds: int) -> None:
        """Contador de janela fixa: INCR + EXPIRE na primeira batida."""
        full_key = f"{_KEY_PREFIX}:{key}"
        try:
            count = int(self._client.incr(full_key))
            if count == 1:
                self._client.expire(full_key, window_seconds)
            if count > limit:
                ttl = self._client.ttl(full_key)
                raise RateLimitExceeded(
                    ttl if isinstance(ttl, int) and ttl > 0 else window_seconds
                )
        except RateLimitExceeded:
            raise
        except Exception:  # noqa: BLE001 - fail-open em qualquer erro de infra
            logger.warning(
                "rate limit backend indisponível; liberando requisição (fail-open)",
                exc_info=True,
            )

    def _hit_with_block(
        self, key: str, *, limit: int, window_seconds: int, block_seconds: int
    ) -> None:
        """Como _hit_window, mas ao exceder ativa um bloqueio temporário."""
        counter_key = f"{_KEY_PREFIX}:{key}"
        block_key = f"{_KEY_PREFIX}:block:{key}"
        try:
            block_ttl = self._client.ttl(block_key)
            if isinstance(block_ttl, int) and block_ttl > 0:
                raise RateLimitExceeded(block_ttl)

            count = int(self._client.incr(counter_key))
            if count == 1:
                self._client.expire(counter_key, window_seconds)
            if count > limit:
                # Ativa o backoff e zera o contador da janela.
                self._client.set(block_key, "1", ex=block_seconds)
                self._client.delete(counter_key)
                raise RateLimitExceeded(block_seconds)
        except RateLimitExceeded:
            raise
        except Exception:  # noqa: BLE001 - fail-open em qualquer erro de infra
            logger.warning(
                "rate limit backend indisponível; liberando requisição (fail-open)",
                exc_info=True,
            )


def _build_redis() -> Any:
    """Cria um cliente Redis a partir de REDIS_URL (import preguiçoso)."""
    import redis  # lazy import: mantém o pacote opcional para testes unitários

    settings = get_settings()
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


# Singleton por processo — reusa uma única conexão/pool Redis. Injetável nos
# endpoints via Depends(get_rate_limiter); nos testes basta sobrescrever a
# dependency com um RateLimiter(redis_client=fake).
_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    """FastAPI dependency: devolve o RateLimiter compartilhado do processo."""
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter
