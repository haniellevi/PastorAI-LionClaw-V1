"use client";

/**
 * US-21 — MaterialsManager (Central). Publica material exigindo URL http/https
 * válida (toast "Material publicado."), lista os materiais ativos e permite
 * INATIVAR (deleteMaterial). Sem upload de arquivo no MVP. Líder e discípulo têm
 * somente leitura (E14) — a gestão é aqui. Estados: loading · empty · erro (retry).
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import {
  createMaterial,
  deleteMaterial,
  listMaterials,
  type Material,
} from "@/lib/cell-materials-api";
import { formatPublishedAt } from "@/components/minha-celula/format";
import type { FlashToast } from "./types";

const URL_RE = /^https?:\/\/.+/i;

export function MaterialsPanel({
  token,
  onToast,
  onChanged,
}: {
  token: string;
  onToast: FlashToast;
  onChanged?: () => void;
}) {
  const [items, setItems] = useState<Material[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const [titulo, setTitulo] = useState("");
  const [url, setUrl] = useState("");
  const [descricao, setDescricao] = useState("");
  const [errors, setErrors] = useState<{ titulo?: string; url?: string }>({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (mode: "initial" | "reload") => {
      if (mode === "initial") setLoading(true);
      setError(null);
      try {
        const page = await listMaterials(token);
        setItems(page.items.filter((m) => m.ativo));
        setLoaded(true);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Não foi possível carregar os materiais.");
      } finally {
        setLoading(false);
      }
    },
    [token],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  function validate(): boolean {
    const next: typeof errors = {};
    if (!titulo.trim()) next.titulo = "Informe um título.";
    if (!url.trim()) next.url = "Informe a URL do material.";
    else if (!URL_RE.test(url.trim())) next.url = "A URL deve começar com http:// ou https://";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function publish() {
    if (busy) return;
    if (!validate()) return;
    setBusy(true);
    try {
      const material = await createMaterial(token, {
        titulo: titulo.trim(),
        url: url.trim(),
        descricao: descricao.trim() || null,
      });
      onToast({ kind: "ok", text: "Material publicado." });
      setTitulo("");
      setUrl("");
      setDescricao("");
      setErrors({});
      setItems((prev) => [material, ...prev]);
      onChanged?.();
    } catch (err) {
      onToast({
        kind: "err",
        text: err instanceof ApiError ? err.message : "Não foi possível publicar o material.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function inactivate(material: Material) {
    if (pendingId) return;
    setPendingId(material.id);
    try {
      await deleteMaterial(token, material.id);
      onToast({ kind: "ok", text: "Material inativado." });
      setItems((prev) => prev.filter((m) => m.id !== material.id));
      onChanged?.();
    } catch (err) {
      onToast({
        kind: "err",
        text: err instanceof ApiError ? err.message : "Não foi possível inativar o material.",
      });
    } finally {
      setPendingId(null);
    }
  }

  const showSkeleton = loading && !loaded;

  return (
    <div className="central-stack">
      <section className="card" aria-label="Publicar material">
        <div className="panel-title">
          <Icon name="link" /> Publicar material
        </div>
        <div className="section-body" style={{ display: "grid", gap: "var(--s3)" }}>
          <div className={`field${errors.titulo ? " invalid" : ""}`}>
            <label htmlFor="mat-titulo">Título</label>
            <input
              id="mat-titulo"
              value={titulo}
              maxLength={120}
              onChange={(e) => {
                setTitulo(e.target.value);
                if (errors.titulo) setErrors((p) => ({ ...p, titulo: undefined }));
              }}
              aria-invalid={errors.titulo ? true : undefined}
              placeholder="Ex.: Estudo da semana"
            />
            {errors.titulo ? (
              <div className="err" role="alert">
                {errors.titulo}
              </div>
            ) : null}
          </div>

          <div className={`field${errors.url ? " invalid" : ""}`}>
            <label htmlFor="mat-url">URL</label>
            <input
              id="mat-url"
              value={url}
              maxLength={2048}
              inputMode="url"
              onChange={(e) => {
                setUrl(e.target.value);
                if (errors.url) setErrors((p) => ({ ...p, url: undefined }));
              }}
              aria-invalid={errors.url ? true : undefined}
              placeholder="https://…"
            />
            {errors.url ? (
              <div className="err" role="alert">
                {errors.url}
              </div>
            ) : null}
          </div>

          <div className="field">
            <label htmlFor="mat-desc">Descrição (opcional)</label>
            <textarea
              id="mat-desc"
              value={descricao}
              rows={2}
              maxLength={2000}
              onChange={(e) => setDescricao(e.target.value)}
              placeholder="Um resumo do material."
            />
          </div>

          <div>
            <Button
              variant="primary"
              size="sm"
              onClick={() => void publish()}
              loading={busy}
              loadingText="Publicando…"
            >
              <Icon name="send" />
              <span>Publicar material</span>
            </Button>
          </div>
        </div>
      </section>

      <section className="card" aria-label="Materiais publicados">
        <div className="panel-title">
          <Icon name="document" /> Materiais ativos
          {items.length ? <span className="count">· {items.length}</span> : null}
        </div>

        {error ? (
          <div className="error-banner" role="alert">
            <Icon name="alert" />
            <span>{error}</span>
            <button type="button" className="btn btn-sm" onClick={() => void load("initial")} disabled={loading}>
              Tentar novamente
            </button>
          </div>
        ) : null}

        {showSkeleton ? (
          <div className="section-body">
            {Array.from({ length: 2 }).map((_, i) => (
              <div className="sk-line sk-lg" key={i} style={{ marginBottom: "var(--s3)" }} />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="empty-state" style={{ padding: "var(--s6)" }}>
            <Icon name="document" />
            <p>
              <strong>Nenhum material publicado.</strong>
            </p>
          </div>
        ) : (
          <div>
            {items.map((m) => (
              <div className="material-item" key={m.id}>
                <span className="grow">
                  <a
                    href={m.url ?? "#"}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="nm"
                    style={{ display: "block" }}
                  >
                    {m.titulo}
                  </a>
                  {m.descricao ? <span className="sub">{m.descricao}</span> : null}
                  {m.publicado_em ? (
                    <span className="notice-time" style={{ display: "block" }}>
                      {formatPublishedAt(m.publicado_em)}
                    </span>
                  ) : null}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void inactivate(m)}
                  loading={pendingId === m.id}
                  loadingText="Inativando…"
                  disabled={pendingId !== null && pendingId !== m.id}
                >
                  <Icon name="trash" />
                  <span>Inativar</span>
                </Button>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
