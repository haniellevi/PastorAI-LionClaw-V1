"use client";

import "@/components/config/administration-ux-v2.css";

/**
 * Tela "Identidade Visual" da superfície admin (admin.<domínio> → /gestao).
 * O admin da igreja envia, pré-visualiza e remove a LOGO DA IGREJA (identidade
 * do tenant). A marca do produto "Igreja 12" é outra coisa e não é tocada aqui.
 * Sem logo, a prévia cai no nome completo da igreja. O nome é read-only (só o
 * master edita). O backend (church.py) revalida formato/tamanho/magic bytes.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import {
  deleteChurchLogo,
  getChurchBranding,
  LOGO_ACCEPT_ATTR,
  uploadChurchLogo,
  validateLogoFile,
  type ChurchBranding,
} from "@/lib/branding-api";
import { Icon } from "@/lib/icons";
import { DsButton } from "@/components/ds/Button";

type Toast = { kind: "ok" | "err"; text: string };

export function IdentidadeVisualScreen() {
  const { token, expireSession } = useAuth();

  const [branding, setBranding] = useState<ChurchBranding | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);
  const [imgFailed, setImgFailed] = useState(false);

  // Arquivo escolhido (ainda não enviado) + preview local via objectURL.
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flash = useCallback((t: Toast) => {
    setToast(t);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3600);
  }, []);

  const onErr = useCallback(
    (e: unknown, fallback: string) => {
      if (e instanceof SessionExpiredError) {
        expireSession();
        return;
      }
      setError(e instanceof ApiError ? e.message : fallback);
    },
    [expireSession],
  );

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      setBranding(await getChurchBranding(token));
      setImgFailed(false);
    } catch (e) {
      onErr(e, "Não foi possível carregar a identidade da igreja.");
    } finally {
      setLoading(false);
    }
  }, [token, onErr]);

  useEffect(() => {
    void load();
  }, [load]);

  // Revoga o objectURL do preview ao trocar/limpar (evita vazar memória).
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  useEffect(() => {
    return () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    };
  }, []);

  const clearSelection = useCallback(() => {
    setFile(null);
    setPreviewUrl((old) => {
      if (old) URL.revokeObjectURL(old);
      return null;
    });
    if (inputRef.current) inputRef.current.value = "";
  }, []);

  const onPick = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setError(null);
      const chosen = e.target.files?.[0] ?? null;
      if (!chosen) return;
      const problem = validateLogoFile(chosen);
      if (problem) {
        setError(problem);
        clearSelection();
        return;
      }
      setPreviewUrl((old) => {
        if (old) URL.revokeObjectURL(old);
        return URL.createObjectURL(chosen);
      });
      setFile(chosen);
    },
    [clearSelection],
  );

  const submit = useCallback(async () => {
    if (!token || !file) return;
    setBusy(true);
    setError(null);
    try {
      const next = await uploadChurchLogo(token, file);
      setBranding(next);
      setImgFailed(false);
      clearSelection();
      flash({ kind: "ok", text: "Logo atualizada." });
    } catch (e) {
      onErr(e, "Não foi possível enviar a logo. Tente novamente.");
    } finally {
      setBusy(false);
    }
  }, [token, file, clearSelection, flash, onErr]);

  const remove = useCallback(async () => {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      const next = await deleteChurchLogo(token);
      setBranding(next);
      setImgFailed(false);
      flash({ kind: "ok", text: "Logo removida. Voltamos a exibir o nome da igreja." });
    } catch (e) {
      onErr(e, "Não foi possível remover a logo. Tente novamente.");
    } finally {
      setBusy(false);
    }
  }, [token, flash, onErr]);

  const nome = branding?.nome || "Sua igreja";
  const savedLogo = branding?.logoUrl ?? null;
  const showSavedLogo = Boolean(savedLogo) && !imgFailed;
  // A prévia mostra: o arquivo recém-escolhido; senão a logo salva; senão o nome.
  const previewLogo = previewUrl ?? (showSavedLogo ? savedLogo : null);

  return (
    <div className="screen admin-screen identity-screen administration-ux" key="identidade">
      <div className="screen-head">
        <div className="titles">
          <h2>Identidade da igreja</h2>
          <p>Atualize a logo exibida no painel.</p>
        </div>
      </div>
      <div className="card card-pad ds-mb-4">
        <div className="panel-title">
          <Icon name="image" /> Identidade Visual
        </div>
        <p className="sub ds-muted ds-m-0 ds-mt-2 ds-mb-3">
          Logo da igreja exibida no sistema. É opcional: sem logo, mostramos o nome da
          igreja. (Isto não altera a marca do produto “Igreja 12”.)
        </p>

        {loading ? (
          <p className="sub ds-muted">Carregando…</p>
        ) : (
          <>
            {/* Nome da igreja — read-only (só o master edita). */}
            <label className="ds-block ds-mb-3">
              <span className="sub ds-muted">Nome da igreja</span>
              <input
                className="input admin-input-block"
                type="text"
                value={nome}
                readOnly
                disabled
                title={nome}
              />
              <span className="sub ds-muted identity-name-hint">
                Para alterar o nome da igreja, fale com o suporte.
              </span>
            </label>

            {/* Prévia: arquivo escolhido, ou logo salva, ou fallback pelo nome. */}
            <div className="sub ds-muted ds-mb-1">
              {previewUrl ? "Prévia (ainda não salva)" : "Logo atual"}
            </div>
            <div className="identity-preview">
              {previewLogo ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={previewLogo}
                  alt={`Logo de ${nome}`}
                  title={nome}
                  onError={() => {
                    // Se a logo salva falhar ao carregar, cai para o nome.
                    if (!previewUrl) setImgFailed(true);
                  }}
                />
              ) : (
                <span
                  className="identity-preview-name"
                  title={nome}
                >
                  {nome}
                </span>
              )}
            </div>

            <p className="sub ds-muted ds-mb-3">
              PNG, JPG ou WebP · até 1 MB · recomendado horizontal (ex.: 512×160).
            </p>

            {error ? (
              <p className="sub ds-text-danger ds-mb-3" role="alert">
                {error}
              </p>
            ) : null}

            <input
              ref={inputRef}
              type="file"
              accept={LOGO_ACCEPT_ATTR}
              onChange={onPick}
              hidden
            />

            <div className="ds-flex ds-gap-2 ds-wrap">
              <DsButton
                variant="secondary"
                onClick={() => inputRef.current?.click()}
                disabled={busy}
              >
                <Icon name="image" />
                <span>{file ? "Trocar imagem" : "Escolher imagem"}</span>
              </DsButton>

              {file ? (
                <>
                  <DsButton
                    onClick={() => void submit()}
                    disabled={busy}
                  >
                    <Icon name="check" />
                    <span>{busy ? "Enviando…" : "Enviar logo"}</span>
                  </DsButton>
                  <DsButton
                    variant="secondary"
                    onClick={clearSelection}
                    disabled={busy}
                  >
                    <span>Cancelar</span>
                  </DsButton>
                </>
              ) : savedLogo ? (
                <DsButton
                  variant="danger"
                  onClick={() => {
                    if (window.confirm(`Remover a logo de ${nome}? O painel passa a exibir o nome da igreja.`)) void remove();
                  }}
                  disabled={busy}
                >
                  <Icon name="trash" />
                  <span>{busy ? "Removendo…" : "Remover logo"}</span>
                </DsButton>
              ) : null}
            </div>
          </>
        )}
      </div>

      {toast ? (
        <div className={`toast ${toast.kind}`} role="status">
          <Icon name={toast.kind === "ok" ? "check" : "alert"} />
          <span>{toast.text}</span>
        </div>
      ) : null}
    </div>
  );
}
