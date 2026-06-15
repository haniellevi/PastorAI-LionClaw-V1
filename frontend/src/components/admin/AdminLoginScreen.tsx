"use client";

/**
 * Login do console Super-Admin. Reaproveita o mesmo POST /auth/login do painel,
 * mas valida o acesso de plataforma em seguida (/admin/me). Uma conta válida de
 * igreja que NÃO seja platform admin recebe uma recusa explícita aqui.
 */
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { AdminAuthError } from "@/lib/admin-api";
import { LoginError } from "@/lib/api";
import { useAdminAuth } from "@/lib/admin-auth-context";

export function AdminLoginScreen() {
  const { login } = useAdminAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loading) return;
    if (!email.includes("@") || !password) {
      setError("Informe e-mail e senha.");
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
    <section
      style={{
        minHeight: "100dvh",
        display: "grid",
        placeItems: "center",
        padding: "var(--s4)",
      }}
    >
      <form
        className="login-card"
        onSubmit={handleSubmit}
        noValidate
        style={{ maxWidth: 380, width: "100%" }}
      >
        <h1>Console da Plataforma</h1>
        <p className="sub">Administração multi-igreja do Igreja 12. Acesso restrito.</p>

        {error ? (
          <div className="auth-error block" role="alert">
            <span>{error}</span>
          </div>
        ) : null}

        <Field
          label="E-mail"
          type="email"
          name="email"
          placeholder="voce@igreja12.com.br"
          autoComplete="username"
          value={email}
          disabled={loading}
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
          onChange={(e) => setPassword(e.target.value)}
        />
        <Button type="submit" variant="primary" block loading={loading} loadingText="Entrando…">
          Entrar
        </Button>
      </form>
    </section>
  );
}
