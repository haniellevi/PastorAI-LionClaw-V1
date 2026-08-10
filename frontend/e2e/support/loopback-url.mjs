const DEFAULT_APP_URL = "http://127.0.0.1:3109";
const DEFAULT_API_URL = "http://127.0.0.1:8009";
const HTTP_PREFIX = "http://";
const FORBIDDEN_RAW_CHARACTERS = /[\p{Cc}\p{White_Space}\\]/u;

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
  if (
    typeof rawValue !== "string" ||
    rawValue.length === 0 ||
    FORBIDDEN_RAW_CHARACTERS.test(rawValue) ||
    rawValue.includes("@") ||
    rawValue.includes("?") ||
    rawValue.includes("#") ||
    rawValue.slice(0, HTTP_PREFIX.length) !== HTTP_PREFIX
  ) {
    throw invalidUrl(name);
  }

  // Esta fronteira lexical não decide se o host é seguro. Ela impede que o
  // parser apague path/dot-segments antes da validação estrutural abaixo.
  const authorityAndRoot = rawValue.slice(HTTP_PREFIX.length);
  const firstSlash = authorityAndRoot.indexOf("/");
  if (
    authorityAndRoot.length === 0 ||
    (firstSlash !== -1 && firstSlash !== authorityAndRoot.length - 1)
  ) {
    throw invalidUrl(name);
  }

  let parsed;
  try {
    parsed = new URL(rawValue);
  } catch {
    throw invalidUrl(name);
  }

  const port = parsed.port === "" ? 80 : Number(parsed.port);
  const canonicalOrigin =
    rawValue.endsWith("/") ? `${parsed.origin}/` : parsed.origin;
  if (
    parsed.protocol !== "http:" ||
    parsed.username !== "" ||
    parsed.password !== "" ||
    parsed.pathname !== "/" ||
    parsed.search !== "" ||
    parsed.hash !== "" ||
    rawValue !== canonicalOrigin ||
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
