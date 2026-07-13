"use client";

/**
 * Harness interno da fundação "Diamante Lapidado" (Gate 5).
 * Prova visual + medições em runtime (contraste WCAG, fontes carregadas,
 * alvos de toque). Não é funcionalidade do produto — page.tsx dá notFound
 * em produção.
 */
import { useEffect, useRef, useState } from "react";

import "@/app/design-tokens.css";
import "@/app/ds.css";

import { BrandSignature } from "@/components/brand/BrandSignature";
import { DiamondMark } from "@/components/brand/DiamondMark";
import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { Dialog } from "@/components/ds/Dialog";
import { DsEmptyState } from "@/components/ds/EmptyState";
import { DsField } from "@/components/ds/Field";
import { DsIconButton } from "@/components/ds/IconButton";
import { DsPageHeader } from "@/components/ds/PageHeader";
import { Tabs } from "@/components/ds/Tabs";
import { DsToast, DsToastRegion } from "@/components/ds/Toast";

/* ---------- medição de cor/contraste (runtime) ---------- */

type Rgb = [number, number, number];

/** Resolve qualquer cor CSS (incl. oklch) para sRGB via canvas. */
function resolveRgb(raw: string): Rgb | null {
  const canvas = document.createElement("canvas");
  canvas.width = 1;
  canvas.height = 1;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  ctx.fillStyle = raw;
  ctx.fillRect(0, 0, 1, 1);
  const d = ctx.getImageData(0, 0, 1, 1).data;
  return [d[0] ?? 0, d[1] ?? 0, d[2] ?? 0];
}

function luminance([r, g, b]: Rgb): number {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function contrastRatio(a: Rgb, b: Rgb): number {
  const la = luminance(a);
  const lb = luminance(b);
  const hi = Math.max(la, lb);
  const lo = Math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

const TOKEN_NAMES = [
  "--diamond-950",
  "--diamond-900",
  "--diamond-700",
  "--diamond-600",
  "--diamond-500",
  "--diamond-300",
  "--diamond-100",
  "--ice-50",
  "--ink-950",
  "--ink-700",
  "--ink-600",
  "--line-200",
  "--surface-canvas",
  "--surface-panel",
  "--surface-raised",
  "--text-primary",
  "--text-secondary",
  "--text-on-action",
  "--border-subtle",
  "--border-emphasis",
  "--focus-ring",
  "--action-primary",
  "--action-primary-hover",
  "--selection-soft",
  "--selection-strong",
  "--state-ok",
  "--state-ok-soft",
  "--state-warn",
  "--state-warn-soft",
  "--state-danger",
  "--state-danger-strong",
  "--state-danger-soft",
  "--state-info",
  "--state-info-soft",
];

const CONTRAST_PAIRS: Array<{ label: string; fg: string; bg: string }> = [
  { label: "text-primary / canvas", fg: "--text-primary", bg: "--surface-canvas" },
  { label: "text-secondary / canvas", fg: "--text-secondary", bg: "--surface-canvas" },
  { label: "text-on-action / action-primary", fg: "--text-on-action", bg: "--action-primary" },
  { label: "action-primary / canvas", fg: "--action-primary", bg: "--surface-canvas" },
  { label: "state-ok / ok-soft", fg: "--state-ok", bg: "--state-ok-soft" },
  { label: "state-warn / warn-soft", fg: "--state-warn", bg: "--state-warn-soft" },
  { label: "state-danger / danger-soft", fg: "--state-danger", bg: "--state-danger-soft" },
  { label: "state-info / info-soft", fg: "--state-info", bg: "--state-info-soft" },
  { label: "text-on-action / danger-strong (hover destrutivo)", fg: "--text-on-action", bg: "--state-danger-strong" },
];

const TYPE_ROLES = ["display", "h1", "h2", "h3", "body", "label", "meta"] as const;

const SECTIONS: Array<[string, string]> = [
  ["marca", "Marca"],
  ["paleta", "Paleta e contraste"],
  ["tipografia", "Tipografia"],
  ["botoes", "Botões"],
  ["iconbutton", "IconButton"],
  ["fields", "Fields"],
  ["dialog", "Dialog"],
  ["sheet", "Sheet"],
  ["toast-banner", "Toast e Banner"],
  ["empty", "EmptyState"],
  ["tabs", "Tabs Central (mobile)"],
  ["pageheader", "PageHeader"],
  ["estados", "Estados sistêmicos"],
  ["motion", "Motion"],
];

const BRAND_SVGS = [
  "diamante-simbolo",
  "diamante-mono",
  "diamante-silhueta-16",
  "diamante-compacta",
  "assinatura-horizontal",
];

const CENTRAL_TABS = [
  { id: "dashboard", label: "Dashboard" },
  { id: "gerenciar", label: "Gerenciar células" },
  { id: "solicitacoes", label: "Solicitações", badge: 2 },
  { id: "avisos", label: "Avisos" },
  { id: "materiais", label: "Materiais" },
];

const BTN_VARIANTS = ["primary", "secondary", "tertiary", "danger"] as const;

/* ---------- Motion: encaixe do diamante (uma vez, sem loop) ---------- */

// Mesma geometria canônica do DiamondMark; fills nos tokens da família diamond.
const MOTION_PLANES: Array<{ points: string; fill: string; offset: string }> = [
  { points: "14,18 38,18 26,42 4,42", fill: "var(--diamond-700)", offset: "translate(-16px, -10px)" },
  { points: "38,18 26,42 50,42", fill: "var(--diamond-600)", offset: "translate(-7px, -13px)" },
  { points: "38,18 62,18 50,42", fill: "var(--diamond-600)", offset: "translate(0, -16px)" },
  { points: "62,18 74,42 50,42", fill: "var(--diamond-600)", offset: "translate(7px, -13px)" },
  { points: "62,18 86,18 96,42 74,42", fill: "var(--diamond-700)", offset: "translate(16px, -10px)" },
  { points: "4,42 26,42 50,90", fill: "var(--diamond-900)", offset: "translate(-13px, 11px)" },
  { points: "26,42 74,42 50,90", fill: "var(--diamond-700)", offset: "translate(0, 16px)" },
  { points: "74,42 96,42 50,90", fill: "var(--diamond-900)", offset: "translate(13px, 11px)" },
];

function MotionDiamond() {
  const [assembled, setAssembled] = useState(true);

  function play() {
    setAssembled(false);
    // Dois frames: garante que o estado "afastado" pinta antes da transição.
    requestAnimationFrame(() => requestAnimationFrame(() => setAssembled(true)));
  }

  return (
    <div className="hx-row">
      <svg viewBox="0 0 100 100" width="160" height="160" role="img" aria-label="Encaixe dos planos do diamante">
        <g stroke="var(--ice-50)" strokeWidth={2.5} strokeLinejoin="round">
          {MOTION_PLANES.map((p, i) => (
            <polygon
              key={p.points}
              points={p.points}
              fill={p.fill}
              style={{
                transformBox: "fill-box",
                transformOrigin: "center",
                transform: assembled ? "none" : p.offset,
                opacity: assembled ? 1 : 0,
                transition:
                  "transform var(--motion-expressive) var(--ease-out-expressive), opacity var(--motion-expressive) var(--ease-out-expressive)",
                transitionDelay: `${i * 45}ms`,
              }}
            />
          ))}
        </g>
      </svg>
      <DsButton variant="secondary" onClick={play}>
        Reproduzir encaixe
      </DsButton>
    </div>
  );
}

/* ---------- CSS exclusivo do harness (layout + simulações de estado) ---------- */

const HARNESS_CSS = `
.hx-root { background: var(--surface-canvas); min-height: 100dvh; color: var(--text-primary); font: var(--type-body); }
.hx-main { max-width: 1100px; margin: 0 auto; padding: var(--s5) var(--s4) var(--s8); }
.hx-nav { display: flex; flex-wrap: wrap; gap: var(--s2) var(--s4); padding: var(--s3) 0; border-bottom: 1px solid var(--border-subtle); }
.hx-nav a { color: var(--action-primary); font: 650 13px/1.4 var(--font); text-decoration: none; }
.hx-nav a:hover { text-decoration: underline; }
.hx-nav a:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }
.hx-section { margin-top: var(--s7); display: grid; gap: var(--s4); }
.hx-section > h2 { font: var(--type-h2); color: var(--text-primary); margin: 0; }
.hx-note { font: var(--type-meta); color: var(--text-secondary); margin: 0; }
.hx-row { display: flex; flex-wrap: wrap; gap: var(--s4); align-items: center; }
.hx-row--end { align-items: flex-end; }
.hx-row--scroll { flex-wrap: nowrap; overflow-x: auto; padding-bottom: var(--s2); min-width: 0; max-width: 100%; }
.hx-section { min-width: 0; }
/* Itens do grid não podem alargar a página (min-width:auto padrão do grid) */
.hx-section > * { min-width: 0; }
.hx-card { min-width: 0; }
.hx-fig { margin: 0; display: grid; gap: var(--s1); justify-items: center; }
.hx-fig figcaption { font: var(--type-meta); color: var(--text-secondary); }
.hx-card { background: var(--surface-raised); border: 1px solid var(--border-subtle); border-radius: var(--radius-panel); padding: var(--s4); display: grid; gap: var(--s3); }
.hx-table { border-collapse: collapse; width: 100%; font: var(--type-meta); }
/* Em viewports estreitos a tabela rola no próprio contêiner (nunca alarga a página) */
table.hx-table { display: block; overflow-x: auto; max-width: 100%; }
table.hx-table thead, table.hx-table tbody { display: table; width: 100%; min-width: max-content; }
.hx-table th, .hx-table td { text-align: left; padding: var(--s2) var(--s3); border-bottom: 1px solid var(--border-subtle); }
.hx-table th { color: var(--text-secondary); }
.hx-swatch { width: 44px; height: 28px; border-radius: var(--radius-control); border: 1px solid var(--border-subtle); }
.hx-mono { font-family: ui-monospace, monospace; font-size: 12px; }
/* max-width em viewport (não em %): o grid dimensiona o track pelo conteúdo, o que anularia % */
.hx-phone { width: 390px; max-width: calc(100dvw - 2 * var(--s4) - 2px); border: 1px solid var(--border-emphasis); border-radius: var(--radius-panel); padding: var(--s3); background: var(--surface-raised); }
.hx-dim { opacity: 0.5; }
.hx-foot { margin-top: var(--s8); padding-top: var(--s4); border-top: 1px solid var(--border-subtle); font: var(--type-meta); color: var(--text-secondary); }
/* Simulações de estado dos botões (só no harness) */
.hx-hover.ds-btn--primary { background: var(--action-primary-hover); }
.hx-hover.ds-btn--secondary { background: var(--selection-soft); }
.hx-hover.ds-btn--tertiary { text-decoration: underline; }
.hx-active.ds-btn { transform: translateY(1px); }
/* Chip de seleção (demo de transição produtiva) */
.hx-chip { border: 1px solid var(--border-subtle); background: var(--surface-raised); color: var(--text-secondary); min-height: 40px; padding: 0 var(--s4); border-radius: var(--radius-pill); font: 650 13px/1 var(--font); cursor: pointer; transition: background-color var(--motion-fast) var(--ease-out-productive), border-color var(--motion-fast) var(--ease-out-productive); }
.hx-chip[aria-pressed="true"] { background: var(--selection-soft); border-color: var(--selection-strong); color: var(--action-primary); }
.hx-chip:focus-visible { outline: 2px solid var(--focus-ring); outline-offset: 2px; }
`;

/* ---------- página ---------- */

export function HarnessClient() {
  const [swatches, setSwatches] = useState<Array<{ name: string; raw: string; rgb: string }>>([]);
  const [pairs, setPairs] = useState<Array<{ label: string; ratio: number }>>([]);
  const [typeFamilies, setTypeFamilies] = useState<Record<string, string>>({});
  const [fontChecks, setFontChecks] = useState<{ sora: boolean; jakarta: boolean } | null>(null);
  const [iconDims, setIconDims] = useState("");
  const [tabHeight, setTabHeight] = useState<number | null>(null);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [okToast, setOkToast] = useState(false);
  const [okSeq, setOkSeq] = useState(0);
  // Demo de CONTRATO do Toast (Gate 5.2): mesma instância mudando kind/duration.
  const [cKind, setCKind] = useState<"ok" | "err" | null>(null);
  const [cDur, setCDur] = useState(1500);
  const [errToast, setErrToast] = useState(false);
  // Prova mobile abre em "Gerenciar células" (2ª tab), com "Solicitações 2"
  // totalmente legível — cenário aprovado no Gate 4.1.
  const [tabA, setTabA] = useState("gerenciar");
  const [tabB, setTabB] = useState("dashboard");
  const [chip, setChip] = useState("hoje");

  const iconWrapRef = useRef<HTMLSpanElement | null>(null);
  const phoneTabsRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const rootStyle = getComputedStyle(document.documentElement);

    setSwatches(
      TOKEN_NAMES.map((name) => {
        const raw = rootStyle.getPropertyValue(name).trim();
        const rgb = resolveRgb(raw);
        return { name, raw, rgb: rgb ? `rgb(${rgb[0]} ${rgb[1]} ${rgb[2]})` : "—" };
      }),
    );

    setPairs(
      CONTRAST_PAIRS.map(({ label, fg, bg }) => {
        const a = resolveRgb(rootStyle.getPropertyValue(fg).trim());
        const b = resolveRgb(rootStyle.getPropertyValue(bg).trim());
        return { label, ratio: a && b ? contrastRatio(a, b) : 0 };
      }),
    );

    const families: Record<string, string> = {};
    document.querySelectorAll<HTMLElement>("[data-typerole]").forEach((el) => {
      const role = el.dataset.typerole;
      if (role) families[role] = getComputedStyle(el).fontFamily;
    });
    setTypeFamilies(families);

    const iconBtn = iconWrapRef.current?.querySelector("button");
    if (iconBtn) setIconDims(`${iconBtn.offsetWidth}×${iconBtn.offsetHeight}px`);

    const tab = phoneTabsRef.current?.querySelector<HTMLElement>('[role="tab"]');
    if (tab) setTabHeight(tab.offsetHeight);

    // Prova de carregamento real das webfonts (após document.fonts.ready).
    // fonts.check() dá falso-negativo com faces subsetadas por unicode-range
    // (@fontsource); a prova correta é contar FontFaces com status "loaded".
    let alive = true;
    document.fonts.ready.then(() => {
      if (!alive) return;
      const faces = Array.from(document.fonts);
      const loaded = (family: string) =>
        faces.filter((f) => f.family.replace(/['"]/g, "") === family && f.status === "loaded").length;
      setFontChecks({
        sora: loaded("Sora") > 0,
        jakarta: loaded("Plus Jakarta Sans") > 0,
      });
    });
    return () => {
      alive = false;
    };
  }, []);

  // Gate 5.1: o auto-dismiss agora é contrato do próprio DsToast (duration).
  // key=okSeq remonta o toast (e o timer) a cada disparo — sem rAF, que fica
  // suspenso em página sem foco.
  function fireOkToast() {
    setOkSeq((s) => s + 1);
    setOkToast(true);
  }

  return (
    <div className="hx-root">
      {/* dangerouslySetInnerHTML: SSR e cliente serializam o texto do <style> de formas diferentes */}
      <style dangerouslySetInnerHTML={{ __html: HARNESS_CSS }} />
      <main className="hx-main">
        <DsPageHeader
          title="Harness — fundação visual"
          context="Diamante Lapidado · Gate 5"
          sub="Primitives ds-*, tokens e medições em runtime. Superfície interna de desenvolvimento."
        />

        <nav className="hx-nav" aria-label="Seções do harness">
          {SECTIONS.map(([id, label]) => (
            <a key={id} href={`#${id}`}>
              {label}
            </a>
          ))}
        </nav>

        {/* 1. Marca */}
        <section id="marca" className="hx-section">
          <h2>Marca</h2>
          <p className="hx-note">Escala de produto (16–48px) — abaixo de 24px a silhueta é automática.</p>
          <div className="hx-row hx-row--end">
            {[16, 24, 32, 48].map((s) => (
              <figure key={s} className="hx-fig">
                <DiamondMark size={s} />
                <figcaption>
                  {s}px{s === 16 ? " · silhueta (automático)" : ""}
                </figcaption>
              </figure>
            ))}
          </div>
          <p className="hx-note">Espécimes grandes (180 e 512px) — separados da escala de produto; a faixa rola no próprio contêiner.</p>
          <div className="hx-row hx-row--scroll hx-row--end">
            {[180, 512].map((s) => (
              <figure key={s} className="hx-fig">
                <DiamondMark size={s} />
                <figcaption>{s}px</figcaption>
              </figure>
            ))}
          </div>
          <div className="hx-row hx-row--end">
            <figure className="hx-fig">
              <DiamondMark size={48} variant="mono" />
              <figcaption>mono</figcaption>
            </figure>
            <figure className="hx-fig">
              <DiamondMark size={48} variant="silhouette" />
              <figcaption>silhueta</figcaption>
            </figure>
            <figure className="hx-fig">
              <BrandSignature size={32} />
              <figcaption>BrandSignature</figcaption>
            </figure>
          </div>
          <p className="hx-note">Espelhos estáticos em public/brand:</p>
          <div className="hx-row hx-row--scroll hx-row--end">
            {BRAND_SVGS.map((n) => (
              <figure key={n} className="hx-fig">
                {/* eslint-disable-next-line @next/next/no-img-element -- espelho estático do SVG, sem otimização */}
                <img src={`/brand/${n}.svg`} alt={`${n}.svg`} style={{ height: 48, width: "auto" }} />
                <figcaption>{n}.svg</figcaption>
              </figure>
            ))}
          </div>
        </section>

        {/* 2. Paleta e contraste */}
        <section id="paleta" className="hx-section">
          <h2>Paleta e contraste</h2>
          <table className="hx-table">
            <thead>
              <tr>
                <th scope="col">Token</th>
                <th scope="col">Amostra</th>
                <th scope="col">Declarado (computado)</th>
                <th scope="col">sRGB resolvido</th>
              </tr>
            </thead>
            <tbody>
              {swatches.map((s) => (
                <tr key={s.name}>
                  <td className="hx-mono">{s.name}</td>
                  <td>
                    <span className="hx-swatch" style={{ display: "inline-block", background: `var(${s.name})` }} />
                  </td>
                  <td className="hx-mono">{s.raw}</td>
                  <td className="hx-mono">{s.rgb}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <table className="hx-table">
            <thead>
              <tr>
                <th scope="col">Par texto/fundo</th>
                <th scope="col">Ratio (runtime)</th>
                <th scope="col">AA texto (≥4.5)</th>
                <th scope="col">AA grande (≥3)</th>
              </tr>
            </thead>
            <tbody>
              {pairs.map((p) => (
                <tr key={p.label}>
                  <td>{p.label}</td>
                  <td className="hx-mono">{p.ratio ? `${p.ratio.toFixed(2)}:1` : "—"}</td>
                  <td>{p.ratio >= 4.5 ? "✓" : "✗"}</td>
                  <td>{p.ratio >= 3 ? "✓" : "✗"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="hx-note">
            {pairs.length} pares medidos · {pairs.length * 2} avaliações (AA texto 4.5:1 e AA grande 3:1 por par) ·{" "}
            {pairs.filter((p) => p.ratio >= 4.5).length} pares ≥4.5 · aprovados:{" "}
            {pairs.filter((p) => p.ratio >= 3).length}/{pairs.length} em ≥3.
          </p>
        </section>

        {/* 3. Tipografia */}
        <section id="tipografia" className="hx-section">
          <h2>Tipografia</h2>
          <p className="hx-note">
            FontFaces com status &quot;loaded&quot; após document.fonts.ready —{" "}
            {fontChecks
              ? `Sora: ${fontChecks.sora ? "✓ carregada" : "✗ ausente"} · Plus Jakarta Sans: ${
                  fontChecks.jakarta ? "✓ carregada" : "✗ ausente"
                }`
              : "verificando…"}
          </p>
          <div className="hx-card">
            {TYPE_ROLES.map((role) => (
              <div key={role}>
                <div data-typerole={role} style={{ font: `var(--type-${role})`, color: "var(--text-primary)" }}>
                  A jornada G12: ganhar, consolidar, discipular, enviar
                </div>
                <p className="hx-note">
                  --type-{role} · família computada: <span className="hx-mono">{typeFamilies[role] ?? "…"}</span>
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* 4. Botões */}
        <section id="botoes" className="hx-section">
          <h2>Botões</h2>
          {(["md", "lg"] as const).map((size) => (
            <div key={size} className="hx-card">
              <p className="hx-note">size=&quot;{size}&quot; — foco visível: navegue com Tab (outline 2px --focus-ring)</p>
              <table className="hx-table">
                <thead>
                  <tr>
                    <th scope="col">variant</th>
                    <th scope="col">default</th>
                    <th scope="col">hover (simulado)</th>
                    <th scope="col">active (simulado)</th>
                    <th scope="col">disabled</th>
                    <th scope="col">loading</th>
                  </tr>
                </thead>
                <tbody>
                  {BTN_VARIANTS.map((v) => (
                    <tr key={v}>
                      <td className="hx-mono">{v}</td>
                      <td>
                        <DsButton variant={v} size={size}>
                          Ação
                        </DsButton>
                      </td>
                      <td>
                        <DsButton variant={v} size={size} className="hx-hover">
                          Ação
                        </DsButton>
                      </td>
                      <td>
                        <DsButton variant={v} size={size} className="hx-active">
                          Ação
                        </DsButton>
                      </td>
                      <td>
                        <DsButton variant={v} size={size} disabled>
                          Ação
                        </DsButton>
                      </td>
                      <td>
                        <DsButton variant={v} size={size} loading>
                          Salvando…
                        </DsButton>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))}
          <div className="hx-row">
            <div style={{ width: 280 }}>
              <DsButton block>Bloco (block)</DsButton>
            </div>
          </div>
        </section>

        {/* 5. IconButton */}
        <section id="iconbutton" className="hx-section">
          <h2>IconButton</h2>
          <div className="hx-row">
            <span ref={iconWrapRef}>
              <DsIconButton label="Editar célula">
                <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
                  <path
                    d="M13.6 3.2l3.2 3.2L7 16.2l-4 .8.8-4 9.8-9.8z"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.6"
                    strokeLinejoin="round"
                  />
                </svg>
              </DsIconButton>
            </span>
            <p className="hx-note">Alvo medido em runtime: {iconDims || "…"} (mínimo exigido: 44×44px)</p>
          </div>
        </section>

        {/* 6. Fields */}
        <section id="fields" className="hx-section">
          <h2>Fields</h2>
          <div className="hx-card" style={{ maxWidth: 420 }}>
            <DsField label="Nome completo" placeholder="Maria da Silva" />
            <DsField label="WhatsApp" helper="Com DDD, só números." placeholder="11 91234-5678" />
            <DsField label="E-mail" error="Informe um e-mail válido." defaultValue="maria@" />
            <DsField label="Igreja" disabled defaultValue="Igreja 12 — Sede" />
            <DsField label="Estágio da jornada" as="select" defaultValue="consolidar">
              <option value="ganhar">Ganhar</option>
              <option value="consolidar">Consolidar</option>
              <option value="discipular">Discipular</option>
              <option value="enviar">Enviar</option>
            </DsField>
            <DsField label="Observações" as="textarea" helper="Visível só para a liderança." rows={3} />
          </div>
        </section>

        {/* 7. Dialog */}
        <section id="dialog" className="hx-section">
          <h2>Dialog</h2>
          <p className="hx-note">Esc fecha; Tab fica preso dentro; ao fechar, o foco volta ao botão que abriu.</p>
          <DsButton onClick={() => setDialogOpen(true)}>Abrir dialog</DsButton>
          <Dialog
            open={dialogOpen}
            onClose={() => setDialogOpen(false)}
            title="Confirmar aprovação"
            description="A solicitação de multiplicação será aprovada e o líder notificado."
            footer={
              <>
                <DsButton variant="secondary" onClick={() => setDialogOpen(false)}>
                  Cancelar
                </DsButton>
                <DsButton onClick={() => setDialogOpen(false)}>Aprovar</DsButton>
              </>
            }
          >
            <DsField label="Observação (opcional)" placeholder="Mensagem para o líder" />
          </Dialog>
        </section>

        {/* 8. Sheet */}
        <section id="sheet" className="hx-section">
          <h2>Sheet</h2>
          <p className="hx-note">Mesmo primitive com sheet; em ≤860px o Dialog inteiro ancora embaixo automaticamente.</p>
          <DsButton variant="secondary" onClick={() => setSheetOpen(true)}>
            Abrir sheet
          </DsButton>
          <Dialog
            open={sheetOpen}
            onClose={() => setSheetOpen(false)}
            sheet
            title="Nova solicitação"
            description="Escolha o tipo de solicitação para a Central de Célula."
            footer={<DsButton onClick={() => setSheetOpen(false)}>Continuar</DsButton>}
          >
            <DsField label="Tipo" as="select" defaultValue="multiplicacao">
              <option value="multiplicacao">Multiplicação de célula</option>
              <option value="membro">Vincular membro</option>
            </DsField>
          </Dialog>
        </section>

        {/* 9. Toast e Banner */}
        <section id="toast-banner" className="hx-section">
          <h2>Toast e Banner</h2>
          <div className="hx-row">
            <DsButton onClick={fireOkToast}>Disparar toast ok (duration 5000ms + ação)</DsButton>
            <DsButton variant="danger" onClick={() => setErrToast(true)}>
              Disparar toast err (persistente)
            </DsButton>
          </div>
          <div className="hx-card" data-demo="toast-contract">
            <p className="hx-note">
              Contrato (mesma instância; kind/duration mudam por props): ok some na duração; ok→err limpa o
              timer e persiste; err→ok cria novo timer; duration nova vale na hora.
            </p>
            <div className="hx-row">
              <DsButton variant="secondary" onClick={() => { setCDur(1500); setCKind("ok"); }}>
                Contrato: ok 1500ms
              </DsButton>
              <DsButton variant="secondary" onClick={() => { setCDur(4000); setCKind("ok"); }}>
                Contrato: ok 4000ms
              </DsButton>
              <DsButton variant="secondary" onClick={() => setCKind("err")}>
                Contrato: → err
              </DsButton>
            </div>
            <div data-contract-slot>
              {cKind === "ok" ? (
                <DsToast kind="ok" duration={cDur} text={`Contrato ok (${cDur}ms).`} onDismiss={() => setCKind(null)} />
              ) : cKind === "err" ? (
                <DsToast kind="err" text="Contrato err (persistente)." onDismiss={() => setCKind(null)} />
              ) : (
                <p className="hx-note">— sem toast montado —</p>
              )}
            </div>
          </div>
          <div style={{ display: "grid", gap: "var(--s3)" }}>
            <DsBanner kind="info" action={<DsButton variant="tertiary">Ver detalhes</DsButton>}>
              O relatório semanal da célula já está disponível.
            </DsBanner>
            <DsBanner kind="warning" action={<DsButton variant="tertiary">Revisar</DsButton>}>
              3 discípulos sem contato há mais de 14 dias.
            </DsBanner>
            <DsBanner kind="error" action={<DsButton variant="tertiary">Tentar de novo</DsButton>}>
              Não foi possível salvar a solicitação.
            </DsBanner>
            <DsBanner kind="degraded" action={<DsButton variant="tertiary">Reconectar</DsButton>}>
              WhatsApp parcialmente indisponível — mensagens podem atrasar.
            </DsBanner>
          </div>
        </section>

        {/* 10. EmptyState */}
        <section id="empty" className="hx-section">
          <h2>EmptyState</h2>
          <div className="hx-row hx-row--end">
            <div className="hx-card" style={{ flex: 1, minWidth: 280 }}>
              <DsEmptyState
                title="Nenhuma célula cadastrada"
                hint="Crie a primeira célula para começar a acompanhar a jornada."
                action={<DsButton>Criar célula</DsButton>}
                illustration={<DiamondMark size={32} variant="silhouette" tone="currentColor" title="" />}
              />
            </div>
            <div className="hx-card" style={{ flex: 1, minWidth: 280 }}>
              <DsEmptyState title="Sem avisos por aqui" hint="Quando a liderança publicar um aviso, ele aparece nesta lista." />
            </div>
          </div>
        </section>

        {/* 11. Tabs Central (mobile) */}
        <section id="tabs" className="hx-section">
          <h2>Tabs Central (mobile)</h2>
          <p className="hx-note">Altura computada da tab em runtime: {tabHeight !== null ? `${tabHeight}px` : "…"} (mínimo 44px)</p>
          <div className="hx-phone" ref={phoneTabsRef}>
            <Tabs tabs={CENTRAL_TABS} active={tabA} onChange={setTabA} label="Central de Célula">
              Conteúdo da aba “{CENTRAL_TABS.find((t) => t.id === tabA)?.label}”.
            </Tabs>
          </div>
          <div>
            <Tabs tabs={CENTRAL_TABS} active={tabB} onChange={setTabB} label="Central de Célula (largura cheia)">
              Conteúdo da aba “{CENTRAL_TABS.find((t) => t.id === tabB)?.label}”.
            </Tabs>
          </div>
        </section>

        {/* 12. PageHeader */}
        <section id="pageheader" className="hx-section">
          <h2>PageHeader</h2>
          <div className="hx-card">
            <DsPageHeader
              context="Jornada G12 · Discipular"
              title="Central de Célula"
              sub="Solicitações, células e materiais da rede em um só lugar."
              action={<DsButton>Nova solicitação</DsButton>}
            />
          </div>
        </section>

        {/* 13. Estados sistêmicos */}
        <section id="estados" className="hx-section">
          <h2>Estados sistêmicos</h2>
          <div className="hx-row hx-row--end">
            <div className="hx-card" style={{ flex: 1, minWidth: 260 }}>
              <p className="hx-note">Loading (ds-skeleton — respiro estático)</p>
              <div className="ds-skeleton" style={{ width: "60%" }} />
              <div className="ds-skeleton" style={{ width: "85%" }} />
              <div className="ds-skeleton" style={{ width: "40%" }} />
            </div>
            <div className="hx-card" style={{ flex: 1, minWidth: 260 }}>
              <p className="hx-note">Vazio</p>
              <DsEmptyState title="Fila zerada." hint="Nenhuma pendência pastoral aberta agora." />
            </div>
          </div>
          <div className="hx-row hx-row--end">
            <div className="hx-card" style={{ flex: 1, minWidth: 260 }}>
              <p className="hx-note">Erro (conteúdo esmaecido + valor “—”)</p>
              <DsBanner kind="error" action={<DsButton variant="tertiary">Tentar de novo</DsButton>}>
                Falha ao carregar os indicadores.
              </DsBanner>
              <div className="hx-dim">
                <p style={{ font: "var(--type-h2)", margin: 0 }}>—</p>
                <p className="hx-note">Discípulos ativos</p>
              </div>
            </div>
            <div className="hx-card" style={{ flex: 1, minWidth: 260 }}>
              <p className="hx-note">Sucesso (toast estático)</p>
              {/* espécime estático: onDismiss noop mantém o exemplo na tela */}
              <DsToast kind="ok" text="Solicitação aprovada." onDismiss={() => {}} />
            </div>
            <div className="hx-card" style={{ flex: 1, minWidth: 260 }}>
              <p className="hx-note">Acesso negado</p>
              <DsEmptyState title="Acesso restrito" hint="A Central de Célula é exclusiva de pastores e administradores." />
            </div>
          </div>
        </section>

        {/* 14. Motion */}
        <section id="motion" className="hx-section">
          <h2>Motion</h2>
          <MotionDiamond />
          <div className="hx-row" role="group" aria-label="Demo de seleção produtiva">
            {[
              ["hoje", "Hoje"],
              ["semana", "Semana"],
              ["mes", "Mês"],
            ].map(([id, label]) => (
              <button key={id} type="button" className="hx-chip" aria-pressed={chip === id} onClick={() => setChip(id ?? "hoje")}>
                {label}
              </button>
            ))}
          </div>
          <p className="hx-note">
            Encaixe expressivo roda UMA vez por acionamento (sem loop); seleção usa transição produtiva
            (--motion-fast). prefers-reduced-motion: o bloco global zera todas as durações.
          </p>
        </section>

        <footer className="hx-foot">
          Harness interno de desenvolvimento — não é funcionalidade do produto. Indisponível em produção (notFound).
        </footer>
      </main>

      {/* Região live PERSISTENTE (sempre montada) — leitores anunciam o conteúdo que entra. */}
      <DsToastRegion>
        {okToast ? (
          <DsToast
            key={okSeq}
            kind="ok"
            text="Alterações salvas."
            duration={5000}
            action={
              <DsButton variant="tertiary" onClick={() => setOkToast(false)}>
                Desfazer
              </DsButton>
            }
            onDismiss={() => setOkToast(false)}
          />
        ) : null}
        {errToast ? <DsToast kind="err" text="Não foi possível enviar. Tente de novo." onDismiss={() => setErrToast(false)} /> : null}
      </DsToastRegion>
    </div>
  );
}
