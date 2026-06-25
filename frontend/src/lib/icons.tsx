/**
 * Ícones SVG inline portados fielmente do artifact travado.
 * Traço único `stroke-width=2`, sem dependência de biblioteca externa
 * (evita instalar pacotes desnecessários e mantém o lock visual).
 */
import type { ReactNode } from "react";

const base = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
} as const;

export type IconKey =
  | "brand"
  | "dashboard"
  | "chat"
  | "calendar"
  | "broadcast"
  | "team"
  | "ganhar"
  | "consolidar"
  | "consol-individual"
  | "university"
  | "discipular"
  | "capacitacao"
  | "g12"
  | "central-celula"
  | "enviar"
  | "whatsapp"
  | "agent"
  | "card"
  | "shield"
  | "lock"
  | "check"
  | "caret"
  | "chevron-left"
  | "logout"
  | "search"
  | "bell"
  | "sparkles"
  | "menu"
  | "construction"
  | "alert"
  | "clock"
  | "phone"
  | "user"
  | "document"
  | "refresh"
  | "link"
  | "plus"
  | "send"
  | "paperclip"
  | "image"
  | "download"
  | "close"
  | "trash"
  | "info"
  | "transfer"
  | "mic"
  | "eye"
  | "eye-off";

const PATHS: Record<IconKey, ReactNode> = {
  brand: <path d="M12 3v18M5 9h14M8 21h8" strokeLinecap="round" />,
  dashboard: (
    <>
      <rect x="3" y="3" width="7" height="9" rx="1" />
      <rect x="14" y="3" width="7" height="5" rx="1" />
      <rect x="14" y="12" width="7" height="9" rx="1" />
      <rect x="3" y="16" width="7" height="5" rx="1" />
    </>
  ),
  chat: (
    <path
      d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5Z"
      strokeLinejoin="round"
    />
  ),
  calendar: (
    <>
      <rect x="3" y="4" width="18" height="17" rx="2" />
      <path d="M3 9h18M8 2v4M16 2v4" />
    </>
  ),
  broadcast: <path d="M3 11l18-8-4 18-5-7-9-3Z" strokeLinejoin="round" />,
  team: (
    <>
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 11h-6" />
    </>
  ),
  ganhar: (
    <>
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M19 8v6M22 11h-6" />
    </>
  ),
  consolidar: <path d="M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />,
  "consol-individual": (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M6 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2" />
    </>
  ),
  university: (
    <>
      <path d="M22 10 12 5 2 10l10 5 10-5Z" />
      <path d="M6 12v5c0 1 2.7 2.5 6 2.5s6-1.5 6-2.5v-5" />
    </>
  ),
  discipular: (
    <>
      <circle cx="12" cy="4" r="2" />
      <circle cx="5" cy="14" r="2" />
      <circle cx="19" cy="14" r="2" />
      <path d="M12 6v3M12 9 6 12.5M12 9l6 3.5" />
    </>
  ),
  capacitacao: <path d="M12 2 3 6l9 4 9-4-9-4ZM3 6v6M21 6v6M7 13v4c2 1.5 8 1.5 10 0v-4" />,
  g12: (
    <>
      <circle cx="12" cy="4" r="2" />
      <circle cx="5" cy="14" r="2" />
      <circle cx="19" cy="14" r="2" />
      <path d="M12 6v3M12 9 6 12.5M12 9l6 3.5" />
    </>
  ),
  "central-celula": (
    <>
      <circle cx="12" cy="5" r="2.4" />
      <circle cx="5" cy="17" r="2.4" />
      <circle cx="19" cy="17" r="2.4" />
      <path d="M12 7.4 6.6 15M12 7.4 17.4 15M7.4 17h9.2" />
    </>
  ),
  enviar: <path d="M3 11l18-8-4 18-5-7-9-3Z" strokeLinejoin="round" />,
  whatsapp: (
    <>
      <path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5 8.5 8.5 0 0 1-3.8-.9L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5Z" />
      <path d="M8.5 9.5c0 3 2 5 5 5.5" strokeLinecap="round" />
    </>
  ),
  agent: (
    <>
      <rect x="4" y="8" width="16" height="12" rx="2" />
      <path d="M12 8V4M9 4h6M9 14h.01M15 14h.01" />
    </>
  ),
  card: (
    <>
      <rect x="2" y="5" width="20" height="14" rx="2" />
      <path d="M2 10h20" />
    </>
  ),
  shield: (
    <>
      <path d="M12 2l8 4v6c0 5-3.5 8-8 10-4.5-2-8-5-8-10V6l8-4Z" />
      <path d="M9 12l2 2 4-4" />
    </>
  ),
  lock: (
    <>
      <rect x="5" y="11" width="14" height="10" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </>
  ),
  check: <path d="M20 6 9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />,
  caret: <path d="M9 18l6-6-6-6" strokeLinecap="round" strokeLinejoin="round" />,
  "chevron-left": <path d="M15 18l-6-6 6-6" strokeLinecap="round" strokeLinejoin="round" />,
  logout: (
    <path
      d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </>
  ),
  bell: <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" />,
  sparkles: (
    <>
      <path d="M12 3l1.6 4.6L18 9l-4.4 1.4L12 15l-1.6-4.6L6 9l4.4-1.4L12 3Z" strokeLinejoin="round" />
      <path d="M19 14l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7.7-2Z" strokeLinejoin="round" />
    </>
  ),
  menu: <path d="M3 12h18M3 6h18M3 18h18" />,
  construction: (
    <>
      <rect x="3" y="9" width="18" height="11" rx="2" />
      <path d="M3 13h18M7 9V6a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v3" />
    </>
  ),
  alert: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v5M12 16h.01" strokeLinecap="round" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" strokeLinecap="round" strokeLinejoin="round" />
    </>
  ),
  phone: (
    <path
      d="M22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92Z"
      strokeLinejoin="round"
    />
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M6 21v-2a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v2" />
    </>
  ),
  document: (
    <>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
      <path d="M14 2v6h6M8 13h8M8 17h8M8 9h2" />
    </>
  ),
  refresh: (
    <path
      d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  ),
  link: (
    <>
      <path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1.5 1.5" />
      <path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1.5-1.5" />
    </>
  ),
  send: <path d="M3 11l18-8-4 18-5-7-9-3Z" strokeLinejoin="round" />,
  plus: <path d="M12 5v14M5 12h14" strokeLinecap="round" />,
  paperclip: (
    <path
      d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  ),
  image: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="8.5" cy="8.5" r="1.5" />
      <path d="m21 15-5-5L5 21" strokeLinejoin="round" />
    </>
  ),
  download: (
    <path
      d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  ),
  close: <path d="M18 6 6 18M6 6l12 12" strokeLinecap="round" />,
  trash: (
    <>
      <path d="M3 6h18" strokeLinecap="round" />
      <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
      <path d="M10 11v6M14 11v6" strokeLinecap="round" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5M12 8h.01" strokeLinecap="round" />
    </>
  ),
  transfer: (
    <path
      d="M7 4 3 8l4 4M3 8h13M17 20l4-4-4-4M21 16H8"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  ),
  mic: (
    <>
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6" strokeLinecap="round" />
    </>
  ),
  eye: (
    <>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" strokeLinejoin="round" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  "eye-off": (
    <>
      <path
        d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-10-7-10-7a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 10 7 10 7a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M2 2l20 20" strokeLinecap="round" />
    </>
  ),
};

export function Icon({
  name,
  className,
  size = 20,
}: {
  name: IconKey;
  className?: string;
  /** Tamanho-padrão do ícone (px). CSS por contexto (.empty-state svg etc.)
   *  ainda sobrescreve; isto só evita o SVG estourar onde não há regra. */
  size?: number;
}) {
  return (
    <svg {...base} width={size} height={size} className={className} aria-hidden="true">
      {PATHS[name]}
    </svg>
  );
}
