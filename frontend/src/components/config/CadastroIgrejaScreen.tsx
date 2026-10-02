"use client";

import "@/components/config/administration-ux-v2.css";

import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  fetchChurchCadastroCapability, getChurchCadastro, saveChurchCadastro,
  type ChurchCadastro,
} from "@/lib/church-cadastro-api";
import { isAdmin } from "@/lib/roles";

const EMPTY: ChurchCadastro = { enderecoInstitucional: null, horariosCulto: null };
const optional = (value: string) => value.trim() || null;

export function CadastroIgrejaScreen() {
  const { token, user, expireSession } = useAuth();
  const [reload, setReload] = useState(0);
  const scope = useMemo(
    () => ({ token, appUserId: user?.appUserId, churchId: user?.churchId, reload }),
    [token, user?.appUserId, user?.churchId, reload],
  );
  const currentScope = useRef<typeof scope | null>(scope);
  currentScope.current = scope;
  const [viewScope, setViewScope] = useState<typeof scope | null>(null);
  const scoped = viewScope === scope;
  const [supported, setSupported] = useState(false);
  const [facts, setFacts] = useState<ChurchCadastro>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const saveRequest = useRef<AbortController | null>(null);
  const allowed = Boolean(token && user && isAdmin(user.roles));

  useEffect(() => {
    const controller = new AbortController();
    setViewScope(scope);
    setSupported(false);
    setFacts(EMPTY);
    setLoading(allowed);
    setSaving(false);
    setError(null);
    setSuccess(false);
    if (allowed && token) {
      void (async () => {
        try {
          const capability = await fetchChurchCadastroCapability(token, controller.signal);
          if (currentScope.current !== scope || controller.signal.aborted) return;
          if (!capability) return;
          const data = await getChurchCadastro(token, controller.signal);
          if (currentScope.current !== scope || controller.signal.aborted) return;
          setFacts(data);
          setSupported(true);
        } catch (reason) {
          if (currentScope.current !== scope || controller.signal.aborted) return;
          if (reason instanceof SessionExpiredError) expireSession();
          else setError("Não foi possível carregar o cadastro da igreja.");
        } finally {
          if (currentScope.current === scope && !controller.signal.aborted) setLoading(false);
        }
      })();
    }
    return () => {
      controller.abort();
      saveRequest.current?.abort();
      saveRequest.current = null;
      if (currentScope.current === scope) currentScope.current = null;
    };
  }, [scope, allowed, token, expireSession]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!scoped || !allowed || !supported || loading || saving || !token || saveRequest.current) return;
    const payload: ChurchCadastro = {
      enderecoInstitucional: optional(facts.enderecoInstitucional ?? ""),
      horariosCulto: optional(facts.horariosCulto ?? ""),
    };
    if ((payload.enderecoInstitucional?.length ?? 0) > 400 || (payload.horariosCulto?.length ?? 0) > 400) {
      setError("Cada campo aceita até 400 caracteres.");
      return;
    }
    const controller = new AbortController();
    saveRequest.current = controller;
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const saved = await saveChurchCadastro(token, payload, controller.signal);
      if (currentScope.current !== scope || controller.signal.aborted) return;
      setFacts(saved);
      setSuccess(true);
    } catch (reason) {
      if (currentScope.current !== scope || controller.signal.aborted) return;
      if (reason instanceof SessionExpiredError) expireSession();
      else setError("Não foi possível salvar o cadastro da igreja.");
    } finally {
      if (currentScope.current === scope && !controller.signal.aborted) {
        saveRequest.current = null;
        setSaving(false);
      }
    }
  }

  return (
    <div className="screen admin-screen administration-ux" key="cadastro-igreja">
      <div className="screen-head"><div className="titles">
        <h2>Cadastro da igreja</h2>
        <p>Informe o endereço institucional e os horários dos cultos para consultas públicas.</p>
      </div></div>
      {!allowed ? <p role="alert">Somente administradores podem editar este cadastro.</p> : null}
      {allowed && (!scoped || loading) ? <p role="status">Carregando cadastro…</p> : null}
      {allowed && scoped && !loading && !supported ? (
        <div className="card card-pad">
          <p role="status">Cadastro indisponível nesta versão do servidor.</p>
          {error ? <p role="alert">{error}</p> : null}
          <button type="button" className="btn" onClick={() => setReload((value) => value + 1)}>Tentar novamente</button>
        </div>
      ) : null}
      {allowed && scoped && supported && !loading ? (
        <form className="card card-pad" onSubmit={(event) => { void submit(event); }}>
          <div className="panel-title">Informações institucionais</div>
          <div className="field">
            <label htmlFor="cadastroEndereco">Endereço institucional</label>
            <input id="cadastroEndereco" maxLength={400}
              value={facts.enderecoInstitucional ?? ""}
              onChange={(event) => { setFacts((current) => ({ ...current, enderecoInstitucional: event.target.value })); setSuccess(false); }} />
          </div>
          <div className="field">
            <label htmlFor="cadastroHorarios">Horários dos cultos</label>
            <textarea id="cadastroHorarios" rows={2} maxLength={400}
              value={facts.horariosCulto ?? ""}
              onChange={(event) => { setFacts((current) => ({ ...current, horariosCulto: event.target.value })); setSuccess(false); }} />
          </div>
          {error ? <p role="alert">{error}</p> : null}
          {success ? <p role="status">Cadastro salvo.</p> : null}
          <Button type="submit" variant="primary" loading={saving} loadingText="Salvando…">Salvar cadastro</Button>
        </form>
      ) : null}
    </div>
  );
}
