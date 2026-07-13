/**
 * Assinatura horizontal: símbolo + wordmark "Igreja 12".
 * Wordmark em Sora 700 (self-hosted via @fontsource) — o 12 vive aqui, não na
 * geometria. Não fundir com a logo do tenant (bloco "Sua igreja" é separado).
 */
import { DiamondMark, type DiamondMarkVariant } from "./DiamondMark";

export interface BrandSignatureProps {
  /** Tamanho do símbolo em px; o wordmark escala proporcionalmente. */
  size?: number;
  variant?: DiamondMarkVariant;
  /** Cor do wordmark (e da silhueta quando mono); padrão diamond-900. */
  tone?: string;
  className?: string;
}

export function BrandSignature({
  size = 28,
  variant = "color",
  tone = "#1B3B6F",
  className,
}: BrandSignatureProps) {
  return (
    <span
      className={className}
      style={{ display: "inline-flex", alignItems: "center", gap: Math.round(size * 0.4) }}
    >
      <DiamondMark size={size} variant={variant} tone={tone} title="" />
      <span
        style={{
          fontFamily: "var(--font-display)",
          fontWeight: 700,
          fontSize: Math.round(size * 0.82),
          letterSpacing: "-0.015em",
          color: tone,
          lineHeight: 1,
        }}
      >
        Igreja 12
      </span>
    </span>
  );
}
