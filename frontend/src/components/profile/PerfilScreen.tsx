"use client";

/**
 * Tela #perfil — o próprio usuário edita seus dados de acesso: nome de exibição
 * e senha. Acessível a qualquer papel (cada um edita a própria conta).
 * Consome PATCH /auth/me e POST /auth/change-password.
 */
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { changePassword, LoginError, SessionExpiredError, updateMe } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

type Status = "idle" | "loading" | "ok";

export function PerfilScreen() {
  const { token, user, updateNome, updateChatNome, expireSession } = useAuth();

  // ---- nome de exibição ---------------------------------------------------
  const [nome, setNome] = useState(user?.nome ?? "");
  const [nomeStatus, setNomeStatus] = useState<Status>("idle");
  const [nomeError, setNomeError] = useState<string>();

  async function saveNome(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (nomeStatus === "loading" || !token) return;
    if (!nome.trim()) {
      setNomeError("Informe seu nome.");
      return;
    }
    setNomeError(undefined);
    setNomeStatus("loading");
    try {
      const me = await updateMe(token, { nome: nome.trim() });
      updateNome(me.nome);
      setNomeStatus("ok");
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return;
      }
      setNomeError(err instanceof LoginError ? err.message : "Não foi possível salvar.");
      setNomeStatus("idle");
    }
  }

  // ---- nome de exibição no chat do WhatsApp (assinatura) ------------------
  const [chatNome, setChatNome] = useState(user?.chatNome ?? "");
  const [chatStatus, setChatStatus] = useState<Status>("idle");
  const [chatError, setChatError] = useState<string>();

  async function saveChatNome(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (chatStatus === "loading" || !token) return;
    setChatError(undefined);
    setChatStatus("loading");
    try {
      // "" limpa a assinatura (volta a usar o nome da conta).
      const me = await updateMe(token, { chatNome: chatNome.trim() });
      updateChatNome(me.chatNome);
      setChatStatus("ok");
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return;
      }
      setChatError(err instanceof LoginError ? err.message : "Não foi possível salvar.");
      setChatStatus("idle");
    }
  }

  // ---- trocar senha -------------------------------------------------------
  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const [nw2, setNw2] = useState("");
  const [pwStatus, setPwStatus] = useState<Status>("idle");
  const [pwError, setPwError] = useState<string>();

  async function savePw(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pwStatus === "loading" || !token) return;
    if (nw.length < 8) {
      setPwError("A nova senha precisa de ao menos 8 caracteres.");
      return;
    }
    if (nw !== nw2) {
      setPwError("As senhas não conferem.");
      return;
    }
    setPwError(undefined);
    setPwStatus("loading");
    try {
      await changePassword(token, cur, nw);
      setPwStatus("ok");
      setCur("");
      setNw("");
      setNw2("");
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return;
      }
      setPwError(err instanceof LoginError ? err.message : "Não foi possível alterar a senha.");
      setPwStatus("idle");
    }
  }

  const okBanner = (text: string) => (
    <div
      className="error-banner"
      role="status"
      style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
    >
      <span>{text}</span>
    </div>
  );

  return (
    <div className="screen" key="perfil">
      <div className="dash-grid">
        <form className="card card-pad" onSubmit={saveNome}>
          <h3>Dados de exibição</h3>
          <p className="sub" style={{ color: "var(--muted)", marginBottom: "var(--s3)" }}>
            Conta: <strong>{user?.email}</strong>
          </p>
          {nomeError ? (
            <div className="error-banner" role="alert">
              <span>{nomeError}</span>
            </div>
          ) : null}
          {nomeStatus === "ok" ? okBanner("Nome atualizado.") : null}
          <Field
            label="Nome"
            value={nome}
            onChange={(e) => {
              setNome(e.target.value);
              setNomeStatus("idle");
            }}
          />
          <Button type="submit" variant="primary" loading={nomeStatus === "loading"} loadingText="Salvando…">
            Salvar nome
          </Button>
        </form>

        <form className="card card-pad" onSubmit={saveChatNome}>
          <h3>Nome no chat do WhatsApp</h3>
          <p className="sub" style={{ color: "var(--muted)", marginBottom: "var(--s3)" }}>
            Aparece nas suas respostas no WhatsApp (ex.: “Pastor Raniel Levi”). Em
            branco, usa seu nome: <strong>{user?.nome}</strong>.
          </p>
          {chatError ? (
            <div className="error-banner" role="alert">
              <span>{chatError}</span>
            </div>
          ) : null}
          {chatStatus === "ok" ? okBanner("Nome de exibição atualizado.") : null}
          <Field
            label="Nome de exibição"
            value={chatNome}
            placeholder={user?.nome ?? ""}
            onChange={(e) => {
              setChatNome(e.target.value);
              setChatStatus("idle");
            }}
          />
          <Button type="submit" variant="primary" loading={chatStatus === "loading"} loadingText="Salvando…">
            Salvar
          </Button>
        </form>

        <form className="card card-pad" onSubmit={savePw}>
          <h3>Trocar senha</h3>
          <p className="sub" style={{ color: "var(--muted)", marginBottom: "var(--s3)" }}>
            Informe a senha atual para confirmar a troca.
          </p>
          {pwError ? (
            <div className="error-banner" role="alert">
              <span>{pwError}</span>
            </div>
          ) : null}
          {pwStatus === "ok" ? okBanner("Senha alterada com sucesso.") : null}
          <Field
            label="Senha atual"
            type="password"
            autoComplete="current-password"
            value={cur}
            onChange={(e) => setCur(e.target.value)}
          />
          <Field
            label="Nova senha"
            type="password"
            autoComplete="new-password"
            value={nw}
            onChange={(e) => setNw(e.target.value)}
          />
          <Field
            label="Confirmar nova senha"
            type="password"
            autoComplete="new-password"
            value={nw2}
            onChange={(e) => setNw2(e.target.value)}
          />
          <Button type="submit" variant="primary" loading={pwStatus === "loading"} loadingText="Alterando…">
            Alterar senha
          </Button>
        </form>
      </div>
    </div>
  );
}
