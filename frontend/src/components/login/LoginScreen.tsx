"use client";

/**
 * Tela #login (US-01). Renderiza form-field + btn-primary conforme o artifact
 * travado e dispara a autenticação via Clerk (no backend, por api-login).
 *
 * Estados: idle | loading | error | success.
 *  - erro de credencial: mensagem genérica (não revela e-mail);
 *  - igreja suspensa / conta sem igreja: banner de bloqueio dedicado;
 *  - sucesso: redireciona para a rota de retorno (ou #dashboard).
 */
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { LoginError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { Icon } from "@/lib/icons";
import { useHashRoute } from "@/lib/use-hash-route";

type Status = "idle" | "loading" | "error" | "success";

interface AuthMessage {
  text: string;
  /** banner de bloqueio (warn) vs. erro de credencial (danger). */
  block: boolean;
}

const ASIDE_POINTS = [
  "Trilha de crescimento G12, do visitante ao líder",
  "Consolidação e discipulado conduzidos pelo agente",
  "Gestão de células e líderes saudáveis na palma da mão",
  "Decisões pastorais sem trocar de tela — tudo via mensagem",
];

export function LoginScreen() {
  const { login, consumeReturnTo } = useAuth();
  const [, navigate] = useHashRoute();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [emailError, setEmailError] = useState<string>();
  const [passwordError, setPasswordError] = useState<string>();
  const [status, setStatus] = useState<Status>("idle");
  const [authMessage, setAuthMessage] = useState<AuthMessage | null>(null);

  const loading = status === "loading";

  function validate(): boolean {
    let ok = true;
    if (!email.includes("@")) {
      setEmailError("Informe um e-mail válido.");
      ok = false;
    } else {
      setEmailError(undefined);
    }
    if (!password) {
      setPasswordError("Informe sua senha.");
      ok = false;
    } else {
      setPasswordError(undefined);
    }
    return ok;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loading) return;
    setAuthMessage(null);
    if (!validate()) return;

    setStatus("loading");
    try {
      await login(email.trim(), password);
      setStatus("success");
      const returnTo = consumeReturnTo();
      navigate(returnTo ?? "dashboard");
    } catch (err) {
      const block = err instanceof LoginError && (err.kind === "billing_blocked" || err.kind === "no_church");
      const text =
        err instanceof LoginError
          ? err.message
          : "Não foi possível autenticar. Tente novamente.";
      setAuthMessage({ text, block });
      setStatus("error");
    }
  }

  return (
    <section id="login">
      <div className="login-wrap">
        <aside className="login-aside">
          <div style={{ position: "relative", zIndex: 1 }}>
            <div className="brand">
              <span className="brand-mark">
                <Icon name="brand" />
              </span>
              PastorAI
            </div>
            <span className="aside-kicker">Visão G12 · Agentes de IA · WhatsApp</span>
            <h2>O primeiro sistema de gestão para igreja na Visão&nbsp;G12.</h2>
            <p className="lead">
              Agentes de IA orquestram consolidação, discipulado e células — e tudo
              acontece conversando no WhatsApp da sua igreja.
            </p>
            <div className="aside-list">
              {ASIDE_POINTS.map((point) => (
                <div className="aside-item" key={point}>
                  <Icon name="check" />
                  {point}
                </div>
              ))}
            </div>
          </div>
          <div className="aside-foot">
            PastorAI © 2026 · Sistema Agêntico Especialista na Gestão de Igrejas na
            Visão&nbsp;G12.
          </div>
        </aside>

        <main className="login-main">
          <form className="login-card" onSubmit={handleSubmit} noValidate>
            <h1>Entrar no painel</h1>
            <p className="sub">Use as credenciais da sua igreja para acessar o dashboard.</p>

            {authMessage ? (
              <div className={`auth-error${authMessage.block ? " block" : ""}`} role="alert">
                <Icon name={authMessage.block ? "lock" : "alert"} />
                <span>{authMessage.text}</span>
              </div>
            ) : null}

            <Field
              label="E-mail"
              type="email"
              name="email"
              placeholder="seu@igreja.com.br"
              autoComplete="username"
              value={email}
              disabled={loading}
              error={emailError}
              onChange={(e) => setEmail(e.target.value)}
            />

            <Field
              label="Senha"
              type="password"
              name="password"
              placeholder="••••••••"
              autoComplete="current-password"
              value={password}
              disabled={loading}
              helper="Autenticação via Clerk. Demais métodos habilitados pela igreja."
              error={passwordError}
              onChange={(e) => setPassword(e.target.value)}
            />

            <Button
              type="submit"
              variant="primary"
              block
              loading={loading}
              loadingText="Autenticando…"
            >
              Entrar
            </Button>
          </form>
        </main>
      </div>
    </section>
  );
}
