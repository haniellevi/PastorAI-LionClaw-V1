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
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { AuthLayout } from "@/components/auth/AuthLayout";
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

function AuthCardHeading({
  title,
  children,
  focus = false,
}: {
  title: string;
  children?: ReactNode;
  focus?: boolean;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (focus) heading.current?.focus();
  }, [focus, title]);

  return (
    <header className="login-card-head">
      <h1 ref={heading} tabIndex={-1}>{title}</h1>
      {children ? <p className="sub">{children}</p> : null}
    </header>
  );
}

function AuthSecurityNote() {
  return (
    <p className="login-security-note">
      <Icon name="lock" />
      A Igreja 12 nunca pede sua senha por e-mail ou WhatsApp.
    </p>
  );
}

export function LoginScreen() {
  const [route, navigate] = useHashRoute();
  return <LoginForm key={route} route={route} navigate={navigate} />;
}

function LoginForm({ route, navigate }: { route: string; navigate: (route: string) => void }) {
  const { login, logout, consumeReturnTo, accessMessage } = useAuth();
  // Um link novo começa com estados próprios. Respostas do link anterior não
  // podem encerrar a sessão ou anunciar sucesso no contexto recém-aberto.
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);

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

  function validate(form: HTMLFormElement): boolean {
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
    if (!ok) {
      const name = !email.includes("@") ? "email" : "password";
      (form.elements.namedItem(name) as HTMLInputElement | null)?.focus();
    }
    return ok;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loading) return;
    setAuthMessage(null);
    if (!validate(event.currentTarget)) return;

    setStatus("loading");
    try {
      await login(email.trim(), password);
      // O provider pode desmontar este formulário ao autenticar. O destino
      // ainda precisa ser consumido e restaurado depois desse handoff.
      setStatus("success");
      const returnTo = consumeReturnTo();
      navigate(returnTo ?? "dashboard");
    } catch (err) {
      if (!active.current) return;
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
      (event.currentTarget.elements.namedItem("forgot-email") as HTMLInputElement | null)?.focus();
      return;
    }
    setFEmailError(undefined);
    setFStatus("loading");
    await requestPasswordReset(fEmail.trim());
    if (!active.current) return;
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
      (event.currentTarget.elements.namedItem("new-password") as HTMLInputElement | null)?.focus();
      return;
    }
    if (rPass !== rPass2) {
      setRError("As senhas não conferem.");
      (event.currentTarget.elements.namedItem("confirm-password") as HTMLInputElement | null)?.focus();
      return;
    }
    setRError(undefined);
    setRStatus("loading");
    try {
      await resetPassword(resetToken, rPass);
      if (!active.current) return;
      logout();
      setRStatus("done");
    } catch (err) {
      if (!active.current) return;
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
      (event.currentTarget.elements.namedItem("activate-password") as HTMLInputElement | null)?.focus();
      return;
    }
    if (aPass !== aPass2) {
      setAError("As senhas não conferem.");
      (event.currentTarget.elements.namedItem("activate-confirm") as HTMLInputElement | null)?.focus();
      return;
    }
    if (aInfo?.precisaCadastro && aTel.trim().length < 8) {
      setAError("Informe seu telefone/WhatsApp para concluir o cadastro.");
      (event.currentTarget.elements.namedItem("activate-phone") as HTMLInputElement | null)?.focus();
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
      if (!active.current) return;
      logout();
      setAStatus("done");
    } catch (err) {
      if (!active.current) return;
      setAError(
        err instanceof LoginError ? err.message : "Não foi possível ativar. Tente novamente.",
      );
      setAStatus("idle");
    }
  }

  return (
    <AuthLayout purpose="Cuide das pessoas e organize os próximos passos.">
          {mode === "login" ? (
            <form className="login-card" onSubmit={handleSubmit} noValidate>
              <AuthCardHeading title="Entre na sua igreja">
                Use o e-mail e a senha do seu acesso.
              </AuthCardHeading>

              {authMessage || accessMessage ? (
                <div
                  className={`auth-error${authMessage?.block || accessMessage ? " block" : ""}`}
                  role="alert"
                >
                  <Icon name={authMessage?.block || accessMessage ? "lock" : "alert"} />
                  <span>{authMessage?.text ?? accessMessage}</span>
                </div>
              ) : null}

              <Field
                label="E-mail"
                type="email"
                name="email"
                placeholder="usuario@example.com"
                autoComplete="username"
                spellCheck={false}
                autoCapitalize="none"
                inputMode="email"
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

              <a className="auth-link-button" href="#esqueci-senha">
                Esqueci minha senha
              </a>
              <AuthSecurityNote />
            </form>
          ) : mode === "forgot" ? (
            <form className="login-card" onSubmit={handleForgot} noValidate>
              <AuthCardHeading title={fStatus === "sent" ? "Confira seu e-mail" : "Recuperar acesso"} focus>
                {fStatus === "sent" ? "Confira também a pasta de spam." : "Informe o e-mail que você usa para entrar."}
              </AuthCardHeading>

              {fStatus === "sent" ? (
                <>
                  <div className="auth-error success" role="status">
                    <Icon name="check" />
                    <span>
                      Se houver uma conta com esse e-mail, você receberá um link para criar uma nova senha.
                    </span>
                  </div>
                  <a className="auth-link-button" href="#login">
                    Voltar ao login
                  </a>
                </>
              ) : (
                <>
                  <Field
                    label="E-mail"
                    type="email"
                    name="forgot-email"
                    placeholder="usuario@example.com"
                    autoComplete="username"
                    spellCheck={false}
                    autoCapitalize="none"
                    inputMode="email"
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
                    Pedir novo link
                  </Button>
                  <a className="auth-link-button" href="#login">
                    Voltar ao login
                  </a>
                </>
              )}
              <AuthSecurityNote />
            </form>
          ) : mode === "activate" ? (
            <form className="login-card" onSubmit={handleActivate} noValidate>
              <AuthCardHeading title={aStatus === "done" ? "Acesso ativado" : "Ativar acesso"} focus />

              {aLoading ? (
                <p className="sub" role="status">Validando convite…</p>
              ) : aInfoError ? (
                <>
                  <div className="auth-error" role="alert">
                    <Icon name="alert" />
                    <span>{aInfoError}</span>
                  </div>
                  <a className="auth-link-button" href="#login">
                    Ir para o login
                  </a>
                </>
              ) : aStatus === "done" ? (
                <>
                  <div
                    className="auth-error success"
                    role="status"
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
                        Olá, <strong>{aInfo.nome}</strong>.{" "}
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
                      placeholder="5500000000000"
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
                    helper="Ao menos 8 caracteres."
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
              {!aInfoError && aStatus !== "done" ? <a className="auth-link-button" href="#login">Voltar ao login</a> : null}
              <AuthSecurityNote />
            </form>
          ) : (
            <form className="login-card" onSubmit={handleReset} noValidate>
              <AuthCardHeading title={rStatus === "done" ? "Senha atualizada" : "Criar nova senha"} focus />

              {!resetToken ? (
                <>
                  <div className="auth-error" role="alert">
                    <Icon name="alert" />
                    <span>Link inválido ou incompleto. Peça um novo para criar sua senha.</span>
                  </div>
                  <a className="auth-link-button" href="#esqueci-senha">Pedir novo link</a>
                </>
              ) : rStatus === "done" ? (
                <>
                  <div className="auth-error success" role="status">
                    <Icon name="check" />
                    <span>Senha redefinida! Agora é só entrar com a nova senha.</span>
                  </div>
                  <Button type="button" variant="primary" block onClick={() => navigate("login")}>
                    Ir para o login
                  </Button>
                </>
              ) : (
                <>
                  <p className="sub">Escolha e confirme sua nova senha.</p>
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
                    helper="Ao menos 8 caracteres."
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
              {rStatus !== "done" ? <a className="auth-link-button" href="#login">Voltar ao login</a> : null}
              <AuthSecurityNote />
            </form>
          )}
    </AuthLayout>
  );
}
