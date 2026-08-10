const DEFAULT_APP_URL = "http://127.0.0.1:3109";
const DEFAULT_API_URL = "http://127.0.0.1:8009";

function invalidUrl(name) {
  return new Error(
    `[M09] ${name} invalida: use somente HTTP em loopback, sem credenciais, caminho, query ou fragmento.`,
  );
}

function isLoopbackHostname(hostname) {
  const normalized = hostname.toLowerCase();
  if (normalized === "localhost" || normalized === "[::1]") return true;

  const octets = normalized.split(".");
  return (
    octets.length === 4 &&
    octets.every((octet) => /^\d{1,3}$/.test(octet) && Number(octet) <= 255) &&
    Number(octets[0]) === 127
  );
}

export function assertM09LoopbackUrl(name, rawValue) {
  if (typeof rawValue !== "string" || rawValue.length === 0 || rawValue !== rawValue.trim()) {
    throw invalidUrl(name);
  }

  let parsed;
  try {
    parsed = new URL(rawValue);
  } catch {
    throw invalidUrl(name);
  }

  const port = parsed.port === "" ? 80 : Number(parsed.port);
  if (
    parsed.protocol !== "http:" ||
    parsed.username !== "" ||
    parsed.password !== "" ||
    parsed.href !== `${parsed.origin}/` ||
    !isLoopbackHostname(parsed.hostname) ||
    !Number.isInteger(port) ||
    port < 1 ||
    port > 65_535
  ) {
    throw invalidUrl(name);
  }

  return Object.freeze({
    origin: parsed.origin,
    hostname: parsed.hostname === "[::1]" ? "::1" : parsed.hostname,
    port,
  });
}

export function resolveM09Urls(environment = process.env) {
  const appValue =
    environment.M09_APP_URL ??
    (environment.M09_APP_PORT
      ? `http://127.0.0.1:${environment.M09_APP_PORT}`
      : DEFAULT_APP_URL);
  const apiValue =
    environment.M09_API_URL ??
    (environment.M09_API_PORT
      ? `http://127.0.0.1:${environment.M09_API_PORT}`
      : DEFAULT_API_URL);

  return Object.freeze({
    app: assertM09LoopbackUrl("M09_APP_URL", appValue),
    api: assertM09LoopbackUrl("M09_API_URL", apiValue),
  });
}
