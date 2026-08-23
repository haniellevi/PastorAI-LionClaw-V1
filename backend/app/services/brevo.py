"""Brevo (ex-Sendinblue) email client — team activation invites (RF-40).

Sends the activation link to a newly invited team member via Brevo's
transactional email API (`POST /v3/smtp/email`, `api-key` header). Failures are
normalized to `BrevoError` and logged without leaking the API key.
"""

from __future__ import annotations

from html import escape
import logging

import httpx

from app.config import Settings, get_settings
from app.services.outbound_guard import log_suppressed

logger = logging.getLogger("pastorai.brevo")


class BrevoError(Exception):
    """Raised when the Brevo API call fails or is misconfigured."""


def _email_document(
    *,
    preheader: str,
    eyebrow: str,
    title: str,
    greeting: str,
    paragraphs: tuple[str, ...],
    cta_label: str,
    cta_url: str,
    security_note: str,
    brand_url: str,
) -> str:
    """Render the shared, email-client-safe Igreja 12 transaction layout."""

    safe_url = escape(cta_url, quote=True)
    safe_brand_url = escape(brand_url.rstrip("/"), quote=True)
    safe_logo_url = f"{safe_brand_url}/brand/diamante-simbolo-128.png"
    paragraph_html = "".join(
        f'<p style="margin:0 0 16px;color:#3f5266;font-size:16px;line-height:1.65;">'
        f"{escape(paragraph)}</p>"
        for paragraph in paragraphs
    )
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
  <title>{escape(title)}</title>
  <style>
    @media only screen and (max-width: 620px) {{
      .email-shell {{ padding: 16px 10px !important; }}
      .email-header {{ padding: 22px 22px !important; }}
      .email-body {{ padding: 30px 22px 26px !important; }}
      .email-title {{ font-size: 27px !important; }}
      .email-button {{ display: block !important; text-align: center !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background:#f7fafd;color:#172b42;font-family:Arial,Helvetica,sans-serif;">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;">
    {escape(preheader)}&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;
  </div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;background:#f7fafd;">
    <tr>
      <td class="email-shell" align="center" style="padding:36px 16px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;max-width:600px;background:#ffffff;border:1px solid #d7e1eb;border-radius:20px;box-shadow:0 18px 50px rgba(9,32,56,.12);overflow:hidden;">
          <tr>
            <td class="email-header" style="padding:25px 34px;background:#092038;">
              <table role="presentation" cellspacing="0" cellpadding="0" border="0">
                <tr>
                  <td width="38" height="38" align="center" valign="middle" style="width:38px;height:38px;line-height:38px;"><img src="{safe_logo_url}" width="38" height="38" alt="" style="display:block;width:38px;height:38px;border:0;"></td>
                  <td style="padding-left:12px;color:#ffffff;font-size:17px;font-weight:700;letter-spacing:-.2px;">Igreja 12<br><span style="color:#b8cbe0;font-size:11px;font-weight:400;letter-spacing:.6px;text-transform:uppercase;">Gestão pastoral inteligente</span></td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td class="email-body" style="padding:38px 42px 34px;">
              <p style="margin:0 0 12px;color:#2b5cb4;font-size:12px;font-weight:700;letter-spacing:1.4px;text-transform:uppercase;">{escape(eyebrow)}</p>
              <h1 class="email-title" style="margin:0 0 22px;color:#172b42;font-size:32px;line-height:1.18;letter-spacing:-.8px;">{escape(title)}</h1>
              <p style="margin:0 0 16px;color:#172b42;font-size:16px;font-weight:700;line-height:1.6;">{escape(greeting)}</p>
              {paragraph_html}
              <table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin:27px 0 28px;">
                <tr>
                  <td bgcolor="#2b5cb4" style="border-radius:10px;">
                    <a class="email-button" href="{safe_url}" target="_blank" style="display:inline-block;padding:15px 24px;color:#ffffff;font-size:16px;font-weight:700;line-height:1;text-decoration:none;border-radius:10px;">{escape(cta_label)}</a>
                  </td>
                </tr>
              </table>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;margin:0 0 22px;background:#f1f6fc;border:1px solid #d7e1eb;border-radius:12px;">
                <tr>
                  <td style="padding:16px 18px;">
                    <p style="margin:0 0 7px;color:#31475f;font-size:12px;font-weight:700;">Se o botão não funcionar</p>
                    <p style="margin:0;color:#60758b;font-size:12px;line-height:1.55;">Copie e cole este endereço no navegador:</p>
                    <p style="margin:8px 0 0;font-size:12px;line-height:1.5;word-break:break-all;"><a href="{safe_url}" target="_blank" style="color:#2b5cb4;text-decoration:underline;">{safe_url}</a></p>
                  </td>
                </tr>
              </table>
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="width:100%;background:#fff8e8;border-radius:10px;">
                <tr>
                  <td width="34" valign="top" style="padding:15px 0 15px 16px;color:#9a6700;font-size:18px;">&#128274;</td>
                  <td style="padding:15px 16px 15px 8px;color:#76591b;font-size:13px;line-height:1.55;">{escape(security_note)}</td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:22px 34px;background:#f7fafd;border-top:1px solid #dfe7ef;color:#6b7f93;font-size:11px;line-height:1.6;text-align:center;">
              Este é um e-mail automático da Igreja 12. Não responda a esta mensagem.<br>
              <a href="{safe_brand_url}/privacidade" style="color:#415a73;text-decoration:underline;">Privacidade</a>
              &nbsp;&middot;&nbsp;
              <a href="{safe_brand_url}/termos" style="color:#415a73;text-decoration:underline;">Termos de uso</a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _activation_contents(nome: str, link: str, brand_url: str) -> tuple[str, str]:
    display_name = nome.strip() or "Olá"
    html = _email_document(
        preheader="Seu convite para acessar a Igreja 12 chegou.",
        eyebrow="Convite de equipe",
        title="Seu acesso está pronto",
        greeting=f"Olá, {display_name}!",
        paragraphs=(
            "Você foi convidado para fazer parte da equipe da sua igreja na plataforma Igreja 12.",
            "Ative o acesso e crie sua senha para entrar no painel com segurança.",
        ),
        cta_label="Ativar meu acesso",
        cta_url=link,
        security_note=(
            "Se você não esperava este convite, não clique no link e avise a liderança da sua igreja."
        ),
        brand_url=brand_url,
    )
    text = (
        f"Olá, {display_name}!\n\n"
        "Você foi convidado para fazer parte da equipe da sua igreja na plataforma Igreja 12.\n"
        "Ative o acesso e crie sua senha usando o link abaixo:\n\n"
        f"{link}\n\n"
        "Se você não esperava este convite, ignore a mensagem e avise a liderança da sua igreja."
    )
    return html, text


def _reset_contents(
    link: str,
    brand_url: str,
    ttl_minutes: int,
) -> tuple[str, str]:
    html = _email_document(
        preheader="Use este link seguro para criar uma nova senha na Igreja 12.",
        eyebrow="Segurança da conta",
        title="Crie uma nova senha",
        greeting="Olá!",
        paragraphs=(
            "Recebemos uma solicitação para redefinir a senha da sua conta na Igreja 12.",
            "Use o botão abaixo para escolher uma nova senha e recuperar seu acesso.",
        ),
        cta_label="Redefinir minha senha",
        cta_url=link,
        security_note=(
            f"O link expira em {ttl_minutes} minutos e só pode ser usado uma vez. "
            "Se você não fez o pedido, ignore este e-mail — sua senha continua a mesma."
        ),
        brand_url=brand_url,
    )
    text = (
        "Olá!\n\n"
        "Recebemos uma solicitação para redefinir a senha da sua conta na Igreja 12.\n"
        "Crie uma nova senha usando o link abaixo:\n\n"
        f"{link}\n\n"
        f"O link expira em {ttl_minutes} minutos e só pode ser usado uma vez. "
        "Se você não fez o pedido, ignore este e-mail — sua senha continua a mesma."
    )
    return html, text


class BrevoClient:
    """Thin HTTP client around the Brevo transactional-email endpoint."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _reject_suppressed_send(self, action: str, detail: str) -> None:
        """Bloqueia o envio sem devolver um falso sucesso ao chamador."""
        log_suppressed("Brevo", action)
        raise BrevoError(detail)

    def _assert_delivery_allowed(self, *, to_email: str, action: str) -> None:
        """Aplica o gate Brevo sem tocar no gate global de outros provedores."""
        mode = self._settings.brevo_send_mode
        if mode == "off":
            self._reject_suppressed_send(
                action, "Envio de e-mail desabilitado pelo modo Brevo off"
            )
        if mode != "canary":
            return  # `live` foi validado por Settings e libera qualquer destinatário.

        try:
            allowlist = self._settings.brevo_canary_recipient_allowlist
        except ValueError:
            self._reject_suppressed_send(
                action, "Configuração do canário Brevo é inválida"
            )
        if not allowlist:
            self._reject_suppressed_send(
                action, "Canário Brevo sem destinatário autorizado"
            )
        if to_email.strip().casefold() not in allowlist:
            self._reject_suppressed_send(
                action, "Destinatário não autorizado para o canário Brevo"
            )

    def _require_config(self) -> tuple[str, str, str, str]:
        base_url = self._settings.brevo_api_url
        api_key = self._settings.brevo_api_key
        from_email = self._settings.brevo_from_email
        from_name = self._settings.brevo_from_name
        if not base_url or not api_key or not from_email:
            raise BrevoError("Brevo API is not configured")
        return base_url.rstrip("/"), api_key, from_email, from_name

    def _send_transactional(
        self,
        *,
        to: list[dict[str, object]],
        subject: str,
        html_content: str,
        text_content: str,
    ) -> str:
        base_url, api_key, from_email, from_name = self._require_config()
        headers = {
            "api-key": api_key,
            "accept": "application/json",
            "content-type": "application/json",
        }
        payload = {
            "sender": {"name": from_name, "email": from_email},
            "to": to,
            "subject": subject,
            "htmlContent": html_content,
            "textContent": text_content,
        }
        try:
            with httpx.Client(base_url=base_url, timeout=15.0) as client:
                resp = client.post("/smtp/email", headers=headers, json=payload)
                resp.raise_for_status()
                body = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Brevo send failed: %s", type(exc).__name__)
            raise BrevoError("Falha ao enviar e-mail pelo Brevo") from exc
        except ValueError as exc:
            logger.warning("Unexpected Brevo response shape")
            raise BrevoError("Resposta inesperada do Brevo") from exc

        message_id = body.get("messageId") if isinstance(body, dict) else None
        if not isinstance(message_id, str) or not message_id.strip():
            logger.warning("Unexpected Brevo response shape")
            raise BrevoError("Resposta inesperada do Brevo")
        return message_id

    def send_invite(self, *, to_email: str, nome: str, activation_link: str) -> str:
        """Send the activation email; returns the Brevo message id."""
        self._assert_delivery_allowed(to_email=to_email, action="send_invite")
        html_content, text_content = _activation_contents(
            nome,
            activation_link,
            self._settings.frontend_url,
        )
        return self._send_transactional(
            to=[
                {
                    "email": to_email,
                    "name": nome,
                    "contactPixelTrackingConsent": False,
                }
            ],
            subject="Você foi convidado para a Igreja 12",
            html_content=html_content,
            text_content=text_content,
        )

    def send_password_reset(self, *, to_email: str, reset_link: str) -> str:
        """Send the password-reset email; returns the Brevo message id."""
        self._assert_delivery_allowed(to_email=to_email, action="send_password_reset")
        html_content, text_content = _reset_contents(
            reset_link,
            self._settings.frontend_url,
            self._settings.password_reset_ttl_minutes,
        )
        return self._send_transactional(
            to=[{"email": to_email, "contactPixelTrackingConsent": False}],
            subject="Redefina sua senha com segurança — Igreja 12",
            html_content=html_content,
            text_content=text_content,
        )


def get_brevo_client() -> BrevoClient:
    """FastAPI dependency / factory for the Brevo client."""
    return BrevoClient()
