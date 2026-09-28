"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { SessionExpiredError } from "@/lib/api";
import { ApiError, confirmAgentIdentity } from "@/lib/dashboard-api";

export function AgentIdentityConfirmation({ token, appUserId, churchId, expireSession }: {
  token: string;
  appUserId: string;
  churchId: string;
  expireSession: () => void;
}) {
  const [challenge, setChallenge] = useState("");
  const [pending, setPending] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scope = useMemo(() => ({ token, appUserId, churchId }), [token, appUserId, churchId]);
  const currentScope = useRef<typeof scope | null>(scope);
  currentScope.current = scope;
  const [viewScope, setViewScope] = useState(scope);
  const inFlight = useRef<AbortController | null>(null);
  const sameSession = viewScope === scope;

  useEffect(() => {
    currentScope.current = scope;
    setViewScope(scope);
    setChallenge("");
    setPending(false);
    setConfirmed(false);
    setError(null);
    return () => {
      inFlight.current?.abort();
      inFlight.current = null;
      if (currentScope.current === scope) currentScope.current = null;
    };
  }, [scope]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = challenge.trim();
    if (!sameSession || !code || code.length > 128 || inFlight.current) return;
    const controller = new AbortController();
    inFlight.current = controller;
    setChallenge("");
    setPending(true);
    setConfirmed(false);
    setError(null);
    try {
      await confirmAgentIdentity(token, code, controller.signal);
      if (currentScope.current === scope) setConfirmed(true);
    } catch (reason) {
      if (currentScope.current !== scope) return;
      if (reason instanceof SessionExpiredError) {
        expireSession();
      } else if (reason instanceof ApiError && [400, 403, 409, 410, 422].includes(reason.status)) {
        setError("Código inválido, expirado ou já usado. Para obter outro, repita a consulta sensível no WhatsApp.");
      } else if (reason instanceof ApiError && [404, 405, 501].includes(reason.status)) {
        setError("Confirmação de conversa indisponível nesta versão. Continue pelo WhatsApp e tente após a atualização.");
      } else if (reason instanceof ApiError && reason.status === 429) {
        setError("Muitas tentativas. Aguarde antes de solicitar outro código.");
      } else {
        setError("Não foi possível confirmar a conversa. Verifique no WhatsApp e solicite novo código se necessário.");
      }
    } finally {
      if (currentScope.current === scope) {
        inFlight.current = null;
        setPending(false);
      }
    }
  }

  return (
    <form className="card card-pad" onSubmit={(event) => { void submit(event); }}>
      <h3>Confirmar conversa do WhatsApp</h3>
      <p className="sub">Para receber um código, peça no WhatsApp da igreja uma consulta sensível, por exemplo: “consulte meu vínculo”. Entre em Meu perfil no painel e cole o código recebido. A confirmação vale por 15 minutos; depois, repita a consulta no WhatsApp para obter outro código.</p>
      <Field
        label="Código recebido no WhatsApp"
        value={sameSession ? challenge : ""}
        onChange={(event) => { setChallenge(event.target.value); setConfirmed(false); setError(null); }}
        autoComplete="off"
        autoCapitalize="off"
        maxLength={128}
        spellCheck={false}
        disabled={!sameSession || pending}
        error={sameSession ? error ?? undefined : undefined}
      />
      <Button type="submit" variant="primary" loading={sameSession && pending} loadingText="Confirmando…" disabled={!sameSession || !challenge.trim() || challenge.trim().length > 128}>
        Confirmar conversa
      </Button>
      {sameSession && confirmed ? (
        <>
          <p role="status">Conversa confirmada. Volte ao WhatsApp.</p>
          <p className="sub">Esta confirmação vale por 15 minutos.</p>
        </>
      ) : null}
    </form>
  );
}
