"use client";

/**
 * Triagem Jev (TypeSafe) em modo sombra: status e configuração para o master.
 *
 * A chave, o modelo, o timeout, a data do DPA e as igrejas são salvos pelo
 * console (PUT /admin/jev/config) e valem na hora; campo vazio cai no ambiente
 * do backend. A chave só é gravada: o backend devolve apenas se está
 * configurada, nunca o valor. O guard ALLOW_REAL_SENDS e a URL da API ficam só
 * no servidor. "Testar conexão" usa uma mensagem sintética fixa do backend.
 */
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { Button } from "@/components/ui/Button";
import {
  AdminSessionExpiredError,
  type AdminJevStatus,
  type AdminJevTeste,
  fetchJevStatus,
  saveJevConfig,
  testJev,
} from "@/lib/admin-api";

export interface JevModalProps {
  token: string;
  /** Igrejas da plataforma, para escolher as que ficam em modo sombra. */
  igrejas?: { id: string; nome: string }[];
  onClose: () => void;
  onExpired: () => void;
}

const pct = (v: number) => `${Math.round(v * 100)}%`;

/** "2026-09-20" → "20/09/2026", sem passar por fuso horário. */
function formatDia(isoDate: string): string {
  const [ano, mes, dia] = isoDate.slice(0, 10).split("-");
  return `${dia}/${mes}/${ano}`;
}

function descreverChave(status: AdminJevStatus): string {
  if (status.chaveIlegivel) {
    return "A chave salva não pode ser lida (a chave de cifra do servidor mudou): cole a chave de novo";
  }
  if (!status.configurado) return "Não configurada";
  if (status.chaveOrigem === "console") {
    const quando = status.chaveAtualizadaEm
      ? ` em ${new Date(status.chaveAtualizadaEm).toLocaleDateString("pt-BR")}`
      : "";
    return `Configurada no console${quando}`;
  }
  return "Configurada no ambiente do servidor";
}

export function JevModal({ token, igrejas, onClose, onExpired }: JevModalProps) {
  const [status, setStatus] = useState<AdminJevStatus | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [teste, setTeste] = useState<AdminJevTeste | null>(null);
  const [salvo, setSalvo] = useState(false);

  const [apiKey, setApiKey] = useState("");
  const [removerChave, setRemoverChave] = useState(false);
  const [modelo, setModelo] = useState("");
  const [timeoutSeg, setTimeoutSeg] = useState("");
  const [dpa, setDpa] = useState("");
  const [selecionadas, setSelecionadas] = useState<string[]>([]);

  const handleErr = useCallback(
    (err: unknown, fallback: string): string | null => {
      if (err instanceof AdminSessionExpiredError) {
        onExpired();
        return null;
      }
      return err instanceof Error ? err.message : fallback;
    },
    [onExpired],
  );

  const preencher = useCallback((s: AdminJevStatus) => {
    setStatus(s);
    setModelo(s.modelo);
    setTimeoutSeg(String(s.timeoutSegundos));
    setDpa(s.dpaAssinadoEm ?? "");
    setSelecionadas(s.igrejas.map((i) => i.id));
  }, []);

  useEffect(() => {
    let alive = true;
    fetchJevStatus(token)
      .then((s) => {
        if (!alive) return;
        preencher(s);
        setLoaded(true);
      })
      .catch((err) => {
        if (!alive) return;
        const m = handleErr(err, "Não foi possível carregar o status do Jev.");
        if (m) {
          setError(m);
          setLoaded(true);
        }
      });
    return () => {
      alive = false;
    };
  }, [token, handleErr, preencher]);

  const runTest = async () => {
    setBusy(true);
    setError(null);
    setTeste(null);
    try {
      setTeste(await testJev(token));
    } catch (err) {
      const m = handleErr(err, "Não foi possível testar o Jev.");
      if (m) setError(m);
    } finally {
      setBusy(false);
    }
  };

  const alternarIgreja = (id: string, marcada: boolean) => {
    setSelecionadas((atual) =>
      marcada ? [...new Set([...atual, id])] : atual.filter((x) => x !== id),
    );
  };

  const salvar = async (e: FormEvent) => {
    e.preventDefault();
    const timeout = timeoutSeg.trim() ? Number(timeoutSeg.replace(",", ".")) : null;
    if (timeout !== null && !Number.isFinite(timeout)) {
      setError("Timeout inválido.");
      return;
    }
    // Igreja excluída da plataforma sai da lista ao salvar.
    const conhecidas = igrejas ? new Set(igrejas.map((i) => i.id)) : null;
    const ids = conhecidas ? selecionadas.filter((id) => conhecidas.has(id)) : selecionadas;
    setSaving(true);
    setError(null);
    setSalvo(false);
    try {
      const s = await saveJevConfig(token, {
        apiKey: apiKey.trim() || undefined,
        removerChave: removerChave || undefined,
        modelo: modelo.trim() || null,
        timeoutSegundos: timeout,
        dpaAssinadoEm: dpa || null,
        igrejaIds: dpa ? ids : [],
      });
      preencher(s);
      setApiKey("");
      setRemoverChave(false);
      setSalvo(true);
    } catch (err) {
      const m = handleErr(err, "Não foi possível salvar a configuração do Jev.");
      if (m) setError(m);
    } finally {
      setSaving(false);
    }
  };

  const ocupado = busy || saving;

  return (
    <DsDialog
      open
      onClose={() => {
        if (!ocupado) onClose();
      }}
      title="Triagem Jev"
      footer={
        loaded ? (
          <>
            <button type="button" className="btn btn-sm" onClick={onClose} disabled={ocupado}>
              Fechar
            </button>
            <Button
              type="button"
              variant="primary"
              size="sm"
              loading={busy}
              loadingText="Testando…"
              disabled={saving || !status?.configurado || !status?.enviosExternosPermitidos}
              onClick={() => void runTest()}
            >
              Testar conexão
            </Button>
          </>
        ) : undefined
      }
    >
      <p className="sub" style={{ color: "var(--muted)", marginBottom: "var(--s2)" }}>
        Modo sombra: o Jev só registra probabilidades ao lado da decisão das
        regras; não muda rota, resposta, consentimento nem etapa. O que você salva
        aqui vale na hora, e campo vazio usa o ambiente do servidor. O guard{" "}
        <code>ALLOW_REAL_SENDS</code> e a URL da API ficam só no servidor.
      </p>

      {error ? (
        <div className="error-banner" role="alert">
          <span>{error}</span>
        </div>
      ) : null}

      {salvo ? (
        <div className="info-banner" role="status">
          <span>Configuração salva.</span>
        </div>
      ) : null}

      {!loaded ? (
        <div style={{ padding: "var(--s5)", textAlign: "center", color: "var(--muted)" }}>
          <span className="spinner" aria-hidden="true" />
          <div className="sub" style={{ marginTop: "var(--s2)" }}>
            Carregando…
          </div>
        </div>
      ) : status ? (
        <>
          <dl style={{ display: "grid", gap: "var(--s2)", margin: 0 }}>
            <div>
              <dt className="sub">Integração com o agente</dt>
              <dd style={{ margin: 0 }}>
                {status.integradoAoAgente
                  ? "Ligada: turnos das igrejas listadas geram eventos de sombra"
                  : "Não integrada: nenhum turno chama o Jev ainda, a lista não tem efeito"}
              </dd>
            </div>
            <div>
              <dt className="sub">Chave de API</dt>
              <dd style={{ margin: 0 }}>{descreverChave(status)}</dd>
            </div>
            <div>
              <dt className="sub">Envios externos (ALLOW_REAL_SENDS)</dt>
              <dd style={{ margin: 0 }}>
                {status.enviosExternosPermitidos
                  ? "Permitidos"
                  : "Desligados — nenhuma chamada ao Jev sai do servidor"}
              </dd>
            </div>
            <div>
              <dt className="sub">Modelo</dt>
              <dd style={{ margin: 0 }}>
                {status.modelo} · timeout {status.timeoutSegundos}s
              </dd>
            </div>
            <div>
              <dt className="sub">DPA com a TypeSafe</dt>
              <dd style={{ margin: 0 }}>
                {status.dpaAssinadoEm
                  ? `Assinado em ${formatDia(status.dpaAssinadoEm)}`
                  : "Não informado"}
              </dd>
            </div>
            <div>
              <dt className="sub">
                {status.integradoAoAgente
                  ? "Igrejas em modo sombra"
                  : "Igrejas na lista (sem efeito até a integração)"}
              </dt>
              <dd style={{ margin: 0 }}>
                {status.igrejas.length === 0 ? (
                  "Nenhuma (desligado)"
                ) : (
                  <ul style={{ margin: 0, paddingLeft: "var(--s4)" }}>
                    {status.igrejas.map((i) => (
                      <li key={i.id}>{i.nome ?? `${i.id} (não encontrada)`}</li>
                    ))}
                  </ul>
                )}
                {status.idsInvalidos > 0 ? (
                  <div className="sub" style={{ color: "var(--danger, var(--muted))" }}>
                    {status.idsInvalidos} id(s) inválido(s) ignorado(s) na lista.
                  </div>
                ) : null}
              </dd>
            </div>
          </dl>

          <form
            aria-label="Configuração do Jev"
            onSubmit={(e) => void salvar(e)}
            style={{ marginTop: "var(--s4)" }}
          >
            <h3 style={{ fontSize: 14, margin: "0 0 var(--s3)" }}>Configuração</h3>
            <div className="field">
              <label htmlFor="jev-chave">Chave da TypeSafe</label>
              <input
                id="jev-chave"
                type="password"
                autoComplete="off"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={
                  status.configurado
                    ? "Deixe em branco para manter a chave atual"
                    : "Cole a chave da TypeSafe"
                }
              />
              <div className="helper">Fica cifrada no banco e não aparece de novo.</div>
              {status.chaveOrigem === "console" ? (
                <label style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 6 }}>
                  <input
                    type="checkbox"
                    checked={removerChave}
                    onChange={(e) => setRemoverChave(e.target.checked)}
                  />
                  Remover a chave salva no console
                </label>
              ) : null}
            </div>
            <div className="field">
              <label htmlFor="jev-modelo">Modelo</label>
              <input
                id="jev-modelo"
                value={modelo}
                onChange={(e) => setModelo(e.target.value)}
                placeholder="jev-latest"
              />
              <div className="helper">Fixe uma versão (ex.: jev-1.13) antes de usar limiares.</div>
            </div>
            <div className="field">
              <label htmlFor="jev-timeout">Timeout (segundos)</label>
              <input
                id="jev-timeout"
                type="number"
                min="0.5"
                max="10"
                step="0.5"
                value={timeoutSeg}
                onChange={(e) => setTimeoutSeg(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="jev-dpa">DPA com a TypeSafe assinado em</label>
              <input
                id="jev-dpa"
                type="date"
                value={dpa}
                onChange={(e) => setDpa(e.target.value)}
              />
              <div className="helper">
                Sem esta data, nenhuma igreja pode ficar em modo sombra.
              </div>
            </div>
            <fieldset
              className="field"
              disabled={!dpa}
              style={{ border: 0, padding: 0, margin: "0 0 var(--s4)" }}
            >
              <legend style={{ fontSize: 12.5, fontWeight: 560, marginBottom: 6 }}>
                Igrejas em modo sombra
              </legend>
              {!igrejas || igrejas.length === 0 ? (
                <div className="helper">Nenhuma igreja carregada.</div>
              ) : (
                igrejas.map((i) => (
                  <label
                    key={i.id}
                    style={{ display: "flex", gap: 8, alignItems: "center", fontWeight: 400 }}
                  >
                    <input
                      type="checkbox"
                      checked={selecionadas.includes(i.id)}
                      onChange={(e) => alternarIgreja(i.id, e.target.checked)}
                    />
                    {i.nome}
                  </label>
                ))
              )}
              <div className="helper">
                {dpa
                  ? "Sem efeito até a integração ao agente."
                  : "Libera depois de informar a data do DPA."}
              </div>
            </fieldset>
            <Button
              type="submit"
              variant="primary"
              size="sm"
              loading={saving}
              loadingText="Salvando…"
              disabled={busy}
            >
              Salvar configuração
            </Button>
          </form>
        </>
      ) : null}

      {teste ? (
        <div
          className="info-banner"
          role="status"
          style={{
            background: "var(--accent-soft)",
            color: "var(--accent)",
            marginTop: "var(--s3)",
          }}
        >
          <span>
            Conectado ({teste.modelo}, {teste.latenciaMs} ms): intenção{" "}
            <strong>{teste.intencao}</strong>, risco pastoral {pct(teste.riscoPastoral)},
            opt-out {pct(teste.pedeOptout)}.
          </span>
        </div>
      ) : null}
    </DsDialog>
  );
}
