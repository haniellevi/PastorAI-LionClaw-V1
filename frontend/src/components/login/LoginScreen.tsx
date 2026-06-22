"use client";

/**
 * Tela #login (US-01) com três modos, escolhidos pela hash:
 *  - login (padrão): e-mail + senha, autenticação via Clerk no backend (api-login);
 *  - esqueci-senha (#esqueci-senha): pede o e-mail e dispara o link de redefinição;
 *  - redefinir (#redefinir-senha/<token>): define a nova senha a partir do token.
 *
 * O fluxo de reset roda PRÉ-login (o usuário não está autenticado), por isso vive
 * aqui dentro da LoginScreen, que é o que a raiz renderiza quando não há sessão.
 */
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import {
  activateInvite,
  fetchInvite,
  LoginError,
  requestPasswordReset,
  resetPassword,
  type InviteInfo,
} from "@/lib/api";
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

const linkBtnStyle: React.CSSProperties = {
  background: "none",
  border: "none",
  color: "var(--accent)",
  cursor: "pointer",
  font: "inherit",
  fontSize: 13,
  padding: 0,
  marginTop: "var(--s2)",
  alignSelf: "center",
};

export function LoginScreen() {
  const { login, consumeReturnTo } = useAuth();
  const [route, navigate] = useHashRoute();

  // Modo derivado da hash. Tokens vêm como #redefinir-senha/<token> e #ativar/<token>.
  const resetToken = route.startsWith("redefinir-senha/")
    ? route.slice("redefinir-senha/".length)
    : "";
  const inviteToken = route.startsWith("ativar/")
    ? route.slice("ativar/".length)
    : "";
  const mode: "login" | "forgot" | "reset" | "activate" =
    route === "ativar" || route.startsWith("ativar/")
      ? "activate"
      : route === "redefinir-senha" || route.startsWith("redefinir-senha/")
        ? "reset"
        : route === "esqueci-senha"
          ? "forgot"
          : "login";

  // ---- login --------------------------------------------------------------
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

  // ---- esqueci a senha ----------------------------------------------------
  const [fEmail, setFEmail] = useState("");
  const [fEmailError, setFEmailError] = useState<string>();
  const [fStatus, setFStatus] = useState<"idle" | "loading" | "sent">("idle");

  async function handleForgot(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (fStatus === "loading") return;
    if (!fEmail.includes("@")) {
      setFEmailError("Informe um e-mail válido.");
      return;
    }
    setFEmailError(undefined);
    setFStatus("loading");
    await requestPasswordReset(fEmail.trim());
    setFStatus("sent");
  }

  // ---- redefinir senha ----------------------------------------------------
  const [rPass, setRPass] = useState("");
  const [rPass2, setRPass2] = useState("");
  const [rError, setRError] = useState<string>();
  const [rStatus, setRStatus] = useState<"idle" | "loading" | "done">("idle");

  async function handleReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (rStatus === "loading") return;
    if (rPass.length < 8) {
      setRError("A senha precisa ter ao menos 8 caracteres.");
      return;
    }
    if (rPass !== rPass2) {
      setRError("As senhas não conferem.");
      return;
    }
    setRError(undefined);
    setRStatus("loading");
    try {
      await resetPassword(resetToken, rPass);
      setRStatus("done");
    } catch (err) {
      setRError(
        err instanceof LoginError ? err.message : "Não foi possível redefinir. Tente novamente.",
      );
      setRStatus("idle");
    }
  }

  // ---- ativar convite -----------------------------------------------------
  const [aInfo, setAInfo] = useState<InviteInfo | null>(null);
  const [aInfoError, setAInfoError] = useState<string>();
  const [aLoading, setALoading] = useState(true);
  const [aPass, setAPass] = useState("");
  const [aPass2, setAPass2] = useState("");
  const [aTel, setATel] = useState("");
  const [aError, setAError] = useState<string>();
  const [aStatus, setAStatus] = useState<"idle" | "loading" | "done">("idle");

  // Valida o token do convite ao abrir a tela e busca os dados para exibir.
  useEffect(() => {
    if (mode !== "activate") return;
    if (!inviteToken) {
      setALoading(false);
      setAInfoError("Link de ativação inválido ou incompleto.");
      return;
    }
    let active = true;
    setALoading(true);
    fetchInvite(inviteToken)
      .then((info) => {
        if (!active) return;
        setAInfo(info);
        setAInfoError(undefined);
      })
      .catch((err) => {
        if (!active) return;
        setAInfoError(
          err instanceof LoginError ? err.message : "Convite inválido ou expirado.",
        );
      })
      .finally(() => {
        if (active) setALoading(false);
      });
    return () => {
      active = false;
    };
  }, [mode, inviteToken]);

  async function handleActivate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (aStatus === "loading") return;
    if (aPass.length < 8) {
      setAError("A senha precisa ter ao menos 8 caracteres.");
      return;
    }
    if (aPass !== aPass2) {
      setAError("As senhas não conferem.");
      return;
    }
    if (aInfo?.precisaCadastro && aTel.trim().length < 8) {
      setAError("Informe seu telefone/WhatsApp para concluir o cadastro.");
      return;
    }
    setAError(undefined);
    setAStatus("loading");
    try {
      await activateInvite(
        inviteToken,
        aPass,
        aInfo?.precisaCadastro ? aTel.trim() : undefined,
      );
      setAStatus("done");
    } catch (err) {
      setAError(
        err instanceof LoginError ? err.message : "Não foi possível ativar. Tente novamente.",
      );
      setAStatus("idle");
    }
  }

  return (
    <section id="login">
      <div className="login-wrap">
        <aside className="login-aside">
          <div
            style={{
              position: "relative",
              zIndex: 1,
              flex: 1,
              display: "flex",
              flexDirection: "column",
              justifyContent: "center",
            }}
          >
            <div className="brand">
              <span className="brand-mark">
                <Icon name="brand" />
              </span>
              Igreja 12
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
            Igreja 12 © 2026 · Sistema Agêntico Especialista na Gestão de Igrejas na
            Visão&nbsp;G12.
          </div>
        </aside>

        <main className="login-main">
          {mode === "login" ? (
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

              <button type="button" style={linkBtnStyle} onClick={() => navigate("esqueci-senha")}>
                Esqueci minha senha
              </button>
            </form>
          ) : mode === "forgot" ? (
            <form className="login-card" onSubmit={handleForgot} noValidate>
              <h1>Recuperar acesso</h1>
              <p className="sub">
                Informe o e-mail da sua conta. Se houver um cadastro, enviaremos um link
                para você criar uma nova senha.
              </p>

              {fStatus === "sent" ? (
                <>
                  <div className="auth-error" role="status" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
                    <Icon name="check" />
                    <span>
                      Se existir uma conta com esse e-mail, enviamos o link de
                      redefinição. Confira sua caixa de entrada (e o spam).
                    </span>
                  </div>
                  <button type="button" style={linkBtnStyle} onClick={() => navigate("login")}>
                    Voltar ao login
                  </button>
                </>
              ) : (
                <>
                  <Field
                    label="E-mail"
                    type="email"
                    name="forgot-email"
                    placeholder="seu@igreja.com.br"
                    autoComplete="username"
                    value={fEmail}
                    disabled={fStatus === "loading"}
                    error={fEmailError}
                    onChange={(e) => setFEmail(e.target.value)}
                  />
                  <Button
                    type="submit"
                    variant="primary"
                    block
                    loading={fStatus === "loading"}
                    loadingText="Enviando…"
                  >
                    Enviar link de redefinição
                  </Button>
                  <button type="button" style={linkBtnStyle} onClick={() => navigate("login")}>
                    Voltar ao login
                  </button>
                </>
              )}
            </form>
          ) : mode === "activate" ? (
            <form className="login-card" onSubmit={handleActivate} noValidate>
              <h1>Ativar acesso</h1>

              {aLoading ? (
                <p className="sub">Validando convite…</p>
              ) : aInfoError ? (
                <>
                  <div className="auth-error" role="alert">
                    <Icon name="alert" />
                    <span>{aInfoError}</span>
                  </div>
                  <button type="button" style={linkBtnStyle} onClick={() => navigate("login")}>
                    Ir para o login
                  </button>
                </>
              ) : aStatus === "done" ? (
                <>
                  <div
                    className="auth-error"
                    role="status"
                    style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
                  >
                    <Icon name="check" />
                    <span>Acesso ativado! Agora é só entrar com sua nova senha.</span>
                  </div>
                  <Button type="button" variant="primary" block onClick={() => navigate("login")}>
                    Ir para o login
                  </Button>
                </>
              ) : (
                <>
                  <p className="sub">
                    {aInfo ? (
                      <>
                        Olá, <strong>{aInfo.nome}</strong> —{" "}
                        {aInfo.precisaCadastro
                          ? "complete seu cadastro e defina sua senha para acessar "
                          : "defina sua senha para acessar "}
                        <strong>{aInfo.igreja}</strong>.
                      </>
                    ) : (
                      "Defina sua senha de acesso."
                    )}
                  </p>
                  {aInfo ? <div className="helper">Conta: {aInfo.email}</div> : null}
                  {aError ? (
                    <div className="auth-error" role="alert">
                      <Icon name="alert" />
                      <span>{aError}</span>
                    </div>
                  ) : null}
                  {aInfo?.precisaCadastro ? (
                    <Field
                      label="Telefone / WhatsApp"
                      type="tel"
                      name="activate-phone"
                      placeholder="(11) 90000-0000"
                      autoComplete="tel"
                      value={aTel}
                      disabled={aStatus === "loading"}
                      onChange={(e) => setATel(e.target.value)}
                    />
                  ) : null}
                  <Field
                    label="Senha"
                    type="password"
                    name="activate-password"
                    placeholder="••••••••"
                    autoComplete="new-password"
                    value={aPass}
                    disabled={aStatus === "loading"}
                    onChange={(e) => setAPass(e.target.value)}
                  />
                  <Field
                    label="Confirmar senha"
                    type="password"
                    name="activate-confirm"
                    placeholder="••••••••"
                    autoComplete="new-password"
                    value={aPass2}
                    disabled={aStatus === "loading"}
                    onChange={(e) => setAPass2(e.target.value)}
                  />
                  <Button
                    type="submit"
                    variant="primary"
                    block
                    loading={aStatus === "loading"}
                    loadingText="Ativando…"
                  >
                    Ativar e criar senha
                  </Button>
                </>
              )}
            </form>
          ) : (
            <form className="login-card" onSubmit={handleReset} noValidate>
              <h1>Criar nova senha</h1>

              {!resetToken ? (
                <>
                  <div className="auth-error" role="alert">
                    <Icon name="alert" />
                    <span>Link inválido ou incompleto. Peça um novo na tela de login.</span>
                  </div>
                  <button type="button" style={linkBtnStyle} onClick={() => navigate("login")}>
                    Voltar ao login
                  </button>
                </>
              ) : rStatus === "done" ? (
                <>
                  <div className="auth-error" role="status" style={{ background: "var(--accent-soft)", color: "var(--accent)" }}>
                    <Icon name="check" />
                    <span>Senha redefinida! Agora é só entrar com a nova senha.</span>
                  </div>
                  <Button type="button" variant="primary" block onClick={() => navigate("login")}>
                    Ir para o login
                  </Button>
                </>
              ) : (
                <>
                  <p className="sub">Escolha uma nova senha para sua conta (mínimo 8 caracteres).</p>
                  {rError ? (
                    <div className="auth-error" role="alert">
                      <Icon name="alert" />
                      <span>{rError}</span>
                    </div>
                  ) : null}
                  <Field
                    label="Nova senha"
                    type="password"
                    name="new-password"
                    placeholder="••••••••"
                    autoComplete="new-password"
                    value={rPass}
                    disabled={rStatus === "loading"}
                    onChange={(e) => setRPass(e.target.value)}
                  />
                  <Field
                    label="Confirmar nova senha"
                    type="password"
                    name="confirm-password"
                    placeholder="••••••••"
                    autoComplete="new-password"
                    value={rPass2}
                    disabled={rStatus === "loading"}
                    onChange={(e) => setRPass2(e.target.value)}
                  />
                  <Button
                    type="submit"
                    variant="primary"
                    block
                    loading={rStatus === "loading"}
                    loadingText="Redefinindo…"
                  >
                    Redefinir senha
                  </Button>
                </>
              )}
            </form>
          )}
        </main>
      </div>
    </section>
  );
}
