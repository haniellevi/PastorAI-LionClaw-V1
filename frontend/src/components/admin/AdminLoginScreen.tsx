"use client";

/**
 * Login do console Super-Admin. Usa o POST /admin/login dedicado,
 * mas valida o acesso de plataforma em seguida (/admin/me). Uma conta válida de
 * igreja que NÃO seja platform admin recebe uma recusa explícita aqui.
 */
import { useState, type FormEvent } from "react";

import { AuthLayout } from "@/components/auth/AuthLayout";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { AdminAuthError } from "@/lib/admin-api";
import { LoginError } from "@/lib/api";
import { useAdminAuth } from "@/lib/admin-auth-context";

export function AdminLoginScreen() {
  const { login, accessMessage } = useAdminAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [emailError, setEmailError] = useState<string>();
  const [passwordError, setPasswordError] = useState<string>();
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loading) return;
    const invalidEmail = !email.includes("@");
    setEmailError(invalidEmail ? "Informe um e-mail válido." : undefined);
    setPasswordError(!password ? "Informe sua senha." : undefined);
    if (invalidEmail || !password) {
      (event.currentTarget.elements.namedItem(invalidEmail ? "email" : "password") as HTMLInputElement | null)?.focus();
      return;
    }
    setError(undefined);
    setLoading(true);
    try {
      await login(email.trim(), password);
      // Sucesso: o provider passa a status "authenticated" e a página troca
      // para o console. Não navegamos manualmente.
    } catch (err) {
      if (err instanceof AdminAuthError && err.kind === "forbidden") {
        setError("Esta conta não tem acesso à administração da plataforma.");
      } else if (err instanceof LoginError) {
        setError(err.message);
      } else {
        setError("Não foi possível entrar. Tente novamente.");
      }
      setLoading(false);
    }
  }

  return (
    <AuthLayout>
      <form
        className="login-card"
        onSubmit={handleSubmit}
        noValidate
      >
        <header className="login-card-head">
          <h1>Console da Plataforma</h1>
          <p className="sub">Use sua conta com permissão para administrar a plataforma.</p>
        </header>

        {error || accessMessage ? (
          <div className="auth-error block" role="alert">
            <span>{error ?? accessMessage}</span>
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
        <Button type="submit" variant="primary" block loading={loading} loadingText="Entrando…">
          Entrar
        </Button>
      </form>
    </AuthLayout>
  );
}
