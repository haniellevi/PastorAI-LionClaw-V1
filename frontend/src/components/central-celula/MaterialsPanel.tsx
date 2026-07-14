"use client";

/**
 * US-21 — MaterialsManager (Central). Publica material exigindo URL http/https
 * válida (toast "Material publicado."), lista os materiais ativos e permite
 * INATIVAR (deleteMaterial). Sem upload de arquivo no MVP. Líder e discípulo têm
 * somente leitura (E14) — a gestão é aqui. Estados: loading · empty · erro (retry).
 */
import { useCallback, useEffect, useState } from "react";

import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { DsEmptyState } from "@/components/ds/EmptyState";
import { DsField } from "@/components/ds/Field";
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
          <DsField
            label="Título"
            value={titulo}
            maxLength={120}
            onChange={(e) => {
              setTitulo(e.target.value);
              if (errors.titulo) setErrors((p) => ({ ...p, titulo: undefined }));
            }}
            error={errors.titulo}
            placeholder="Ex.: Estudo da semana"
          />

          <DsField
            label="URL"
            type="url"
            value={url}
            maxLength={2048}
            inputMode="url"
            onChange={(e) => {
              setUrl(e.target.value);
              if (errors.url) setErrors((p) => ({ ...p, url: undefined }));
            }}
            error={errors.url}
            placeholder="https://…"
          />

          <DsField
            label="Descrição (opcional)"
            as="textarea"
            value={descricao}
            rows={2}
            maxLength={2000}
            onChange={(e) => setDescricao(e.target.value)}
            placeholder="Um resumo do material."
          />

          <div>
            <DsButton variant="primary" onClick={() => void publish()} loading={busy}>
              <Icon name="send" />
              <span>Publicar material</span>
            </DsButton>
          </div>
        </div>
      </section>

      <section className="card" aria-label="Materiais publicados">
        <div className="panel-title">
          <Icon name="document" /> Materiais ativos
          {items.length ? <span className="count">· {items.length}</span> : null}
        </div>

        {error ? (
          <DsBanner
            kind="error"
            action={
              <DsButton variant="secondary" onClick={() => void load("initial")} disabled={loading}>
                Tentar novamente
              </DsButton>
            }
          >
            {error}
          </DsBanner>
        ) : null}

        {showSkeleton ? (
          <div className="section-body">
            {Array.from({ length: 2 }).map((_, i) => (
              <div className="sk-line sk-lg" key={i} style={{ marginBottom: "var(--s3)" }} />
            ))}
          </div>
        ) : items.length === 0 ? (
          <DsEmptyState illustration={<Icon name="document" />} title="Nenhum material publicado." />
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
                <DsButton
                  variant="tertiary"
                  onClick={() => void inactivate(m)}
                  loading={pendingId === m.id}
                  disabled={pendingId !== null && pendingId !== m.id}
                >
                  <Icon name="trash" />
                  <span>Inativar</span>
                </DsButton>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
