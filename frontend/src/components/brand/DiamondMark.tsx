/**
 * Símbolo "Diamante Lapidado" (rota A aprovada — Gates 4/4.1).
 *
 * Geometria canônica FIXA: diamante fechado; linhas internas = planos gráficos
 * simplificados (8 planos), não contagem de facetas. Proibido alterar para
 * incluir fenda/linha vertical central, estrela, brilho, glow ou gradiente.
 * O número 12 pertence ao wordmark (ver BrandSignature), nunca à geometria.
 *
 * Regra de leitura (aprovada nos Gates 4/4.1): em 16px a silhueta sólida é
 * obrigatória; a partir de 24px a versão com linhas é legível e aprovada
 * (sidebar 24/32px usa linhas). O componente força silhueta quando size < 24.
 * Espelhos estáticos em public/brand/*.svg (favicon/uso externo).
 */
import type { SVGProps } from "react";

export type DiamondMarkVariant = "color" | "mono" | "silhouette";

export interface DiamondMarkProps extends Omit<SVGProps<SVGSVGElement>, "children"> {
  /** Tamanho renderizado em px (width = height). */
  size?: number;
  variant?: DiamondMarkVariant;
  /** Cor da silhueta/mono; padrão diamond-900. Aceita currentColor. */
  tone?: string;
  /** Rótulo acessível; use "" + aria-hidden externo quando decorativo. */
  title?: string;
}

const OUTLINE = "14,18 86,18 96,42 50,90 4,42";

// Planos (fills = render hex dos tokens diamond-700/600/900; linhas ice-50).
const PLANES: Array<{ points: string; fill: string }> = [
  { points: "14,18 38,18 26,42 4,42", fill: "#2B5CB4" },
  { points: "38,18 26,42 50,42", fill: "#2E77D0" },
  { points: "38,18 62,18 50,42", fill: "#2E77D0" },
  { points: "62,18 74,42 50,42", fill: "#2E77D0" },
  { points: "62,18 86,18 96,42 74,42", fill: "#2B5CB4" },
  { points: "4,42 26,42 50,90", fill: "#1B3B6F" },
  { points: "26,42 74,42 50,90", fill: "#2B5CB4" },
  { points: "74,42 96,42 50,90", fill: "#1B3B6F" },
];

export function DiamondMark({
  size = 24,
  variant = "color",
  tone = "#1B3B6F",
  title = "Igreja 12",
  ...rest
}: DiamondMarkProps) {
  // Silhueta obrigatória em tamanhos minúsculos: as linhas internas viram ruído.
  const effective: DiamondMarkVariant = size < 24 ? "silhouette" : variant;
  const solid = effective !== "color";
  const decorative = title === "";

  return (
    <svg
      viewBox="0 0 100 100"
      width={size}
      height={size}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : title}
      aria-hidden={decorative ? true : undefined}
      focusable="false"
      {...rest}
    >
      {solid ? (
        <polygon points={OUTLINE} fill={effective === "silhouette" && variant === "color" ? "#2B5CB4" : tone} />
      ) : (
        <g stroke="#F7FAFD" strokeWidth={2.5} strokeLinejoin="round">
          {PLANES.map((p) => (
            <polygon key={p.points} points={p.points} fill={p.fill} />
          ))}
        </g>
      )}
    </svg>
  );
}
