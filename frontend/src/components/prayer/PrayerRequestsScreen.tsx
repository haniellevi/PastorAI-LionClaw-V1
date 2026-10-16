"use client";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { prayerFetch, type PrayerRequest } from "./api";
const STATES = {
  open: "Novo",
  assigned: "Em acompanhamento",
  closed: "Encerrado",
};
export function PrayerRequestsScreen() {
  const { token, user } = useAuth();
  const [data, setData] = useState<{
    token: string;
    rows: PrayerRequest[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  useEffect(() => {
    setError(null);
    setSelected(null);
    if (!token) return;
    const abort = new AbortController();
    void prayerFetch<PrayerRequest[]>(token, "", { signal: abort.signal })
      .then((rows) => {
        if (!abort.signal.aborted) setData({ token, rows });
      })
      .catch(() => {
        if (!abort.signal.aborted)
          setError("Não foi possível carregar os pedidos autorizados.");
      });
    return () => abort.abort();
  }, [token]);
  async function change(id: string, action: "assume" | "close") {
    if (!token) return;
    setBusy(id);
    setError(null);
    try {
      const updated = await prayerFetch<PrayerRequest>(
        token,
        `/${id}/${action}`,
        { method: "POST" },
      );
      setData((previous) =>
        previous?.token === token
          ? {
              token,
              rows: previous.rows.map((r) => (r.id === id ? updated : r)),
            }
          : previous,
      );
    } catch {
      setData(null);
      setError(
        "Não foi possível atualizar. Seu acesso ou o responsável pelo pedido pode ter mudado.",
      );
    } finally {
      setBusy(null);
    }
  }
  const rows = data?.token === token ? data.rows : null;
  return (
    <section className="screen" aria-labelledby="screen-title">
      <header className="screen-head">
        <h1 id="screen-title">Pedidos de oração</h1>
        <p>Pedidos compartilhados com você para acompanhamento pastoral.</p>
      </header>
      {error ? <p role="alert">{error}</p> : null}
      {!rows && !error ? <p role="status">Carregando pedidos…</p> : null}
      {rows?.length === 0 ? (
        <p>Nenhum pedido autorizado para você neste momento.</p>
      ) : null}
      {rows?.map((row) => (
        <article
          className="card"
          key={row.id}
          style={{ padding: 20, marginBottom: 16 }}
        >
          <h2>{row.pessoa_nome}</h2>
          <p>
            {STATES[row.state]} ·{" "}
            {new Date(row.created_at).toLocaleDateString("pt-BR")}
          </p>
          <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
            {row.summary}
          </p>
          <button
            type="button"
            className="btn"
            aria-expanded={selected === row.id}
            onClick={() => setSelected(selected === row.id ? null : row.id)}
          >
            Ver detalhes
          </button>
          {selected === row.id ? (
            <p>
              Compartilhamento autorizado:{" "}
              {row.audience === "pastoral"
                ? "equipe pastoral"
                : "equipe pastoral e líder da célula"}
              . Encerrar o acompanhamento não apaga o pedido.
            </p>
          ) : null}
          {row.state === "open" ||
          (row.state === "assigned" &&
            row.responsavel_id !== user?.appUserId &&
            user?.roles.includes("pastor")) ? (
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy === row.id}
              onClick={() => void change(row.id, "assume")}
            >
              Assumir
            </button>
          ) : null}
          {row.state === "assigned" &&
          row.responsavel_id === user?.appUserId ? (
            <button
              type="button"
              className="btn btn-primary"
              disabled={busy === row.id}
              onClick={() => void change(row.id, "close")}
            >
              Encerrar
            </button>
          ) : null}
        </article>
      ))}
    </section>
  );
}
