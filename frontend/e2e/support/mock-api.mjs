import { createServer } from "node:http";

import { resolveM09Urls } from "./loopback-url.mjs";

const { app, api } = resolveM09Urls();
const host = api.hostname;
const port = api.port;
const token = "m09-local-e2e-token";
const qrPixel =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII=";

const profile = {
  appUserId: "00000000-0000-4000-8000-000000000001",
  churchId: "00000000-0000-4000-8000-000000000002",
  email: "admin.e2e@example.test",
  nome: "Admin E2E",
  chatNome: "Admin",
  roles: ["admin", "pastor"],
  isOwner: true,
  igrejaNome: "Igreja Laboratório",
  igrejaLogoUrl: null,
};

let requests = [];
let nextRequestId = 1;
let selectedModel = "gpt-5.6-luna";
let whatsapp = { numero: null, status: "offline", ultimaSync: null };

function resetState() {
  requests = [];
  nextRequestId = 1;
  selectedModel = "gpt-5.6-luna";
  whatsapp = { numero: null, status: "offline", ultimaSync: null };
}

function delayFor(pathname) {
  if (pathname === "/auth/login") return 280;
  if (pathname === "/auth/me") return 320;
  if (
    pathname === "/work-queue" ||
    pathname === "/team/lookup" ||
    pathname === "/cells" ||
    pathname === "/dashboard/overview"
  ) {
    return 140;
  }
  return 80;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function corsHeaders() {
  return {
    "Access-Control-Allow-Origin": app.origin,
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Cache-Control": "no-store",
    Vary: "Origin",
  };
}

function sendJson(response, status, body) {
  response.writeHead(status, {
    ...corsHeaders(),
    "Content-Type": "application/json; charset=utf-8",
  });
  response.end(JSON.stringify(body));
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    let raw = "";
    request.setEncoding("utf8");
    request.on("data", (chunk) => {
      raw += chunk;
      if (raw.length > 65_536) reject(new Error("payload muito grande"));
    });
    request.on("end", () => {
      if (!raw) {
        resolve(null);
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch {
        reject(new Error("JSON inválido"));
      }
    });
    request.on("error", reject);
  });
}

function safeBody(_pathname, body) {
  if (Array.isArray(body)) return body.map((item) => safeBody("", item));
  if (!body || typeof body !== "object") return body;
  return Object.fromEntries(
    Object.entries(body).map(([key, value]) => [
      key,
      /password|api.?key|token|secret|authorization/i.test(key)
        ? "[redacted]"
        : safeBody("", value),
    ]),
  );
}

function page(items) {
  return { items, page: 1, pageSize: 200, total: items.length };
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", api.origin);
  const method = (request.method ?? "GET").toUpperCase();
  const pathname = url.pathname;

  if (method === "OPTIONS") {
    response.writeHead(204, corsHeaders());
    response.end();
    return;
  }

  if (method === "GET" && pathname === "/__e2e/health") {
    sendJson(response, 200, { status: "ok" });
    return;
  }
  if (method === "GET" && pathname === "/__e2e/requests") {
    sendJson(response, 200, { requests });
    return;
  }
  if (method === "POST" && pathname === "/__e2e/reset") {
    resetState();
    sendJson(response, 200, { status: "reset" });
    return;
  }

  const startedAt = Date.now();
  const record = {
    id: nextRequestId++,
    method,
    path: pathname,
    query: url.search,
    startedAt,
    finishedAt: null,
    durationMs: null,
    status: null,
    body: null,
  };
  requests.push(record);

  try {
    const body = method === "GET" ? null : await readBody(request);
    record.body = safeBody(pathname, body);
    await sleep(delayFor(pathname));

    const protectedRoute = pathname !== "/auth/login";
    if (protectedRoute && request.headers.authorization !== `Bearer ${token}`) {
      record.status = 401;
      sendJson(response, 401, { detail: "Sessão E2E ausente." });
      return;
    }

    if (method === "POST" && pathname === "/auth/login") {
      record.status = 200;
      sendJson(response, 200, { token, ...profile });
      return;
    }
    if (method === "GET" && pathname === "/auth/me") {
      record.status = 200;
      sendJson(response, 200, profile);
      return;
    }
    if (method === "GET" && pathname === "/work-queue") {
      record.status = 200;
      sendJson(
        response,
        200,
        page([
          {
            id: "00000000-0000-4000-8000-000000000010",
            tipo: "visitante",
            titulo: "Acompanhar visitante E2E",
            contexto: "Fluxo local sem envio externo",
            status: "pendente",
            pessoaId: "00000000-0000-4000-8000-000000000011",
            responsavelId: null,
            prioridade: 1,
            prazo: "2099-01-01T12:00:00-03:00",
          },
        ]),
      );
      return;
    }
    if (method === "GET" && pathname === "/team/lookup") {
      record.status = 200;
      sendJson(response, 200, page([{ ...profile, usuarioId: profile.appUserId, status: "ativo", papeis: profile.roles, pessoaId: null }]));
      return;
    }
    if (method === "GET" && pathname === "/cells") {
      record.status = 200;
      sendJson(response, 200, page([{ id: "00000000-0000-4000-8000-000000000020", nome: "Célula E2E", liderId: profile.appUserId, ativo: true }]));
      return;
    }
    if (method === "GET" && pathname === "/dashboard/overview") {
      record.status = 200;
      sendJson(response, 200, {
        scope: "igreja",
        total: 12,
        decisoesJesus: 2,
        celulasAtivas: 1,
        lideresCelula: 1,
        semInteresse: 0,
        porTipo: { visitante: 1, membro: 8 },
        porEtapa: { ganhar: 1, consolidar: 2 },
      });
      return;
    }
    if (method === "GET" && pathname === "/events") {
      record.status = 200;
      sendJson(response, 200, page([]));
      return;
    }
    if (method === "GET" && pathname === "/agent/credential") {
      record.status = 200;
      sendJson(response, 200, { status: "active", provedor: "openai", modelo: selectedModel });
      return;
    }
    if (method === "GET" && pathname === "/agent/models") {
      record.status = 200;
      sendJson(response, 200, {
        padrao: "gpt-5.6-luna",
        precosAtualizadosEm: "2026-08-01",
        modelos: [
          {
            modelo: "gpt-5.6-luna",
            nome: "GPT-5.6 Luna",
            perfil: "Econômico para rotinas.",
            precoEntradaUsdMilhao: 0.2,
            precoSaidaUsdMilhao: 1.0,
            recomendado: true,
            fallback: [],
          },
          {
            modelo: "gpt-5.6-terra",
            nome: "GPT-5.6 Terra",
            perfil: "Equilíbrio entre custo e qualidade.",
            precoEntradaUsdMilhao: 0.8,
            precoSaidaUsdMilhao: 3.2,
            recomendado: false,
            fallback: ["gpt-5.6-luna"],
          },
        ],
      });
      return;
    }
    if (method === "GET" && pathname === "/agent/config") {
      record.status = 200;
      sendJson(response, 200, {
        configured: true,
        nome: "PastorAI",
        tom: "acolhedor",
        comportamento: "Atender com segurança no laboratório E2E.",
        publicoAlvo: ["visitantes"],
        acessos: ["agenda"],
        ativo: true,
      });
      return;
    }
    if (method === "GET" && pathname === "/agent/crons") {
      record.status = 200;
      sendJson(response, 200, []);
      return;
    }
    if (method === "GET" && pathname === "/agent/config/requests") {
      record.status = 200;
      sendJson(response, 200, []);
      return;
    }
    if (method === "PUT" && pathname === "/agent/model") {
      if (!body || (body.modelo !== "gpt-5.6-luna" && body.modelo !== "gpt-5.6-terra")) {
        record.status = 422;
        sendJson(response, 422, { detail: "Modelo E2E não permitido." });
        return;
      }
      selectedModel = body.modelo;
      record.status = 200;
      sendJson(response, 200, { modelo: selectedModel, validado: true });
      return;
    }
    if (method === "GET" && pathname === "/whatsapp/connection") {
      record.status = 200;
      sendJson(response, 200, whatsapp);
      return;
    }
    if (method === "POST" && pathname === "/whatsapp/connection") {
      if (!body || !["connect", "reconnect", "disconnect"].includes(body.action)) {
        record.status = 422;
        sendJson(response, 422, { detail: "Ação E2E inválida." });
        return;
      }
      if (body.action === "disconnect") {
        whatsapp = { numero: null, status: "offline", ultimaSync: new Date().toISOString() };
        record.status = 200;
        sendJson(response, 200, { status: "offline", qr: null, pairingCode: null });
        return;
      }
      whatsapp = { ...whatsapp, status: "reconectando", ultimaSync: new Date().toISOString() };
      record.status = 200;
      sendJson(response, 200, {
        status: "reconectando",
        qr: body.numero ? null : qrPixel,
        pairingCode: body.numero ? "12345678" : null,
      });
      return;
    }

    record.status = 501;
    sendJson(response, 501, {
      detail: `Endpoint não previsto pelo laboratório M09: ${method} ${pathname}`,
    });
  } catch (error) {
    record.status = 400;
    sendJson(response, 400, {
      detail: error instanceof Error ? error.message : "Requisição inválida.",
    });
  } finally {
    record.finishedAt = Date.now();
    record.durationMs = record.finishedAt - record.startedAt;
  }
});

server.listen(port, host, () => {
  console.log(`M09 mock API em ${api.origin}`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
