/**
 * Endereço do backend, fixado no build pelo Next (`NEXT_PUBLIC_*` é embutido
 * no bundle e não muda depois). Em desenvolvimento e testes, sem a variável,
 * usa a API local. No build de produção, a ausência falha o build em vez de
 * publicar um painel que chamaria `localhost` no navegador de quem acessa.
 */
const DEV_API_BASE = "http://localhost:8000";

export function resolveApiBase(
  configured: string | undefined,
  nodeEnv: string | undefined,
): string {
  const value = configured?.trim();
  if (value) return value.replace(/\/$/, "");
  if (nodeEnv === "production") {
    throw new Error(
      "NEXT_PUBLIC_API_URL não foi definida no build de produção: o painel não saberia o endereço da API.",
    );
  }
  return DEV_API_BASE;
}

export const API_BASE = resolveApiBase(
  process.env.NEXT_PUBLIC_API_URL,
  process.env.NODE_ENV,
);
