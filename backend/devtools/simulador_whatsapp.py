"""Evolution API simulada, para DEV, ambiente local e testes.

Implementa só os endpoints que ``app.services.evolution.EvolutionClient`` usa e
guarda as mensagens em memória. A página ``/`` faz o papel do celular de um
contato: a mensagem digitada vira um webhook ``messages.upsert`` igual ao da
Evolution, entregue ao backend com o segredo do webhook, e as respostas do bot
aparecem na mesma conversa.

O backend só fala com este serviço quando ``WHATSAPP_TRANSPORTE=simulado``
(recusado em produção). Nenhuma mensagem sai para a rede do WhatsApp.

Rodar fora do compose::

    SIMULADOR_WEBHOOK_URL=http://127.0.0.1:8000/whatsapp/webhook \\
    EVOLUTION_WEBHOOK_SECRET=... \\
    uvicorn devtools.simulador_whatsapp:create_app_from_env --factory --port 8090
"""

from __future__ import annotations

import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import SIMULADOR_NOMES_WEBHOOK, is_simulated_destination
from app.domain.phone import normalize_phone

NUMERO_OFICIAL_PADRAO = "5500900000000"


@dataclass
class MensagemSimulada:
    id: str
    direcao: str  # "entrada" (contato → igreja) ou "saida" (igreja → contato)
    instance: str
    telefone: str
    texto: str
    criada_em: str
    webhook_status: int | None = None


@dataclass
class EstadoSimulador:
    numero_oficial: str
    instancias: dict[str, str] = field(default_factory=dict)  # nome -> estado
    webhooks: dict[str, str] = field(default_factory=dict)  # nome -> url
    mensagens: list[MensagemSimulada] = field(default_factory=list)
    # Status HTTP a devolver nos próximos sendText, para exercitar retry.
    falhas_send_text: list[int] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def estado_de(self, instance: str) -> str:
        # Instância nunca vista conta como conectada: o DEV não tem QR real.
        return self.instancias.get(instance, "open")


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _payload_entrada(
    *, instance: str, telefone: str, texto: str, nome: str, numero_oficial: str, message_id: str
) -> dict[str, Any]:
    """Webhook ``messages.upsert`` no formato da Evolution v2."""
    return {
        "event": "messages.upsert",
        "instance": instance,
        "sender": f"{numero_oficial}@s.whatsapp.net",
        "data": {
            "key": {
                "remoteJid": f"{telefone}@s.whatsapp.net",
                "fromMe": False,
                "id": message_id,
            },
            "pushName": nome,
            "message": {"conversation": texto},
        },
    }


def create_app(
    *,
    webhook_url: str,
    webhook_secret: str,
    numero_oficial: str = NUMERO_OFICIAL_PADRAO,
    webhook_client: httpx.Client | None = None,
) -> FastAPI:
    """Monta o simulador. ``webhook_client`` permite injetar o backend nos testes."""
    if not is_simulated_destination(webhook_url, SIMULADOR_NOMES_WEBHOOK):
        raise ValueError(
            "SIMULADOR_WEBHOOK_URL deve ser http(s) em IP de loopback, localhost "
            "ou backend, sem credenciais embutidas"
        )
    if not webhook_secret:
        raise ValueError("EVOLUTION_WEBHOOK_SECRET é obrigatório no simulador")

    estado = EstadoSimulador(numero_oficial=numero_oficial)
    cliente = webhook_client or httpx.Client(timeout=15.0)
    app = FastAPI(title="Simulador de WhatsApp (Evolution)", docs_url=None, redoc_url=None)
    app.state.simulador = estado

    def _registrar(**campos: Any) -> MensagemSimulada:
        msg = MensagemSimulada(
            id=campos.pop("id", None) or uuid.uuid4().hex.upper(),
            criada_em=_agora(),
            **campos,
        )
        with estado.lock:
            estado.mensagens.append(msg)
        return msg

    # ---- Endpoints da Evolution usados pelo EvolutionClient ----------------

    @app.post("/instance/create", status_code=201)
    def instance_create(body: dict = Body(default_factory=dict)) -> dict:
        nome = str(body.get("instanceName") or "")
        with estado.lock:
            estado.instancias.setdefault(nome, "open")
        return {"instance": {"instanceName": nome, "status": "created"}}

    @app.get("/instance/connect/{instance}")
    def instance_connect(instance: str) -> dict:
        with estado.lock:
            estado.instancias[instance] = "open"
        return {"instance": {"instanceName": instance, "state": "open"}}

    @app.put("/instance/restart/{instance}")
    def instance_restart(instance: str) -> dict:
        with estado.lock:
            estado.instancias[instance] = "open"
        return {"instance": {"instanceName": instance, "state": "open"}}

    @app.delete("/instance/logout/{instance}")
    def instance_logout(instance: str) -> dict:
        with estado.lock:
            estado.instancias[instance] = "close"
        return {"status": "SUCCESS", "error": False}

    @app.delete("/instance/delete/{instance}")
    def instance_delete(instance: str) -> dict:
        with estado.lock:
            estado.instancias.pop(instance, None)
            estado.webhooks.pop(instance, None)
        return {"status": "SUCCESS", "error": False, "response": {"message": "Instance deleted"}}

    @app.get("/instance/fetchInstances")
    def fetch_instances(instance_name: str = Query(alias="instanceName")) -> list[dict]:
        return [
            {
                "name": instance_name,
                "connectionStatus": estado.estado_de(instance_name),
                "ownerJid": f"{estado.numero_oficial}@s.whatsapp.net",
            }
        ]

    @app.post("/webhook/set/{instance}")
    def webhook_set(instance: str, body: dict = Body(default_factory=dict)) -> dict:
        config = body.get("webhook") if isinstance(body.get("webhook"), dict) else body
        with estado.lock:
            estado.webhooks[instance] = str(config.get("url") or "")
        return {"webhook": {"enabled": True}}

    @app.post("/message/sendText/{instance}")
    def send_text(instance: str, body: dict = Body(...)) -> JSONResponse:
        with estado.lock:
            falha = estado.falhas_send_text.pop(0) if estado.falhas_send_text else None
        if falha is not None:
            return JSONResponse(status_code=falha, content={"error": "falha simulada"})
        if estado.estado_de(instance) != "open":
            return JSONResponse(status_code=400, content={"error": "instância desconectada"})
        telefone = str(body.get("number") or "")
        msg = _registrar(
            direcao="saida",
            instance=instance,
            telefone=normalize_phone(telefone) or telefone,
            texto=str(body.get("text") or ""),
        )
        return JSONResponse(
            status_code=201,
            content={
                "key": {"remoteJid": f"{telefone}@s.whatsapp.net", "fromMe": True, "id": msg.id},
                "status": "PENDING",
            },
        )

    @app.post("/message/sendMedia/{instance}")
    def send_media(instance: str, body: dict = Body(...)) -> JSONResponse:
        telefone = str(body.get("number") or "")
        legenda = str(body.get("caption") or "")
        msg = _registrar(
            direcao="saida",
            instance=instance,
            telefone=normalize_phone(telefone) or telefone,
            texto=f"[mídia: {body.get('mediatype') or 'arquivo'}] {legenda}".strip(),
        )
        return JSONResponse(status_code=201, content={"key": {"id": msg.id}, "status": "PENDING"})

    @app.post("/chat/fetchProfilePictureUrl/{instance}")
    def profile_picture(instance: str) -> dict:
        return {"profilePictureUrl": None}

    @app.post("/chat/getBase64FromMediaMessage/{instance}")
    def media_base64(instance: str) -> JSONResponse:
        return JSONResponse(status_code=404, content={"error": "simulador não guarda mídia"})

    # ---- Controles do simulador -----------------------------------------

    @app.get("/simulador/saude")
    def saude() -> dict:
        return {"ok": True}

    @app.post("/simulador/mensagens")
    def enviar_como_contato(body: dict = Body(...)) -> dict:
        """O contato manda uma mensagem: grava e entrega o webhook ao backend."""
        instance = str(body.get("instance") or "").strip()
        # O JID leva o número completo, como o WhatsApp; a conversa guarda o
        # número normalizado, igual ao que o backend usa para casar a pessoa.
        digitos = re.sub(r"\D", "", str(body.get("telefone") or ""))
        telefone = normalize_phone(digitos)
        texto = str(body.get("texto") or "")
        if not instance or not telefone or not texto.strip():
            raise HTTPException(status_code=422, detail="instance, telefone e texto são obrigatórios")
        message_id = f"SIM{uuid.uuid4().hex.upper()}"
        payload = _payload_entrada(
            instance=instance,
            telefone=digitos,
            texto=texto,
            nome=str(body.get("nome") or "Contato simulado"),
            numero_oficial=estado.numero_oficial,
            message_id=message_id,
        )
        try:
            resposta = cliente.post(
                webhook_url, json=payload, headers={"x-webhook-token": webhook_secret}
            )
            status = resposta.status_code
        except httpx.HTTPError:
            status = 0
        msg = _registrar(
            id=message_id,
            direcao="entrada",
            instance=instance,
            telefone=telefone,
            texto=texto,
            webhook_status=status,
        )
        return asdict(msg)

    @app.get("/simulador/mensagens")
    def listar(
        instance: str | None = None, telefone: str | None = None
    ) -> list[dict]:
        alvo = normalize_phone(telefone) if telefone else None
        with estado.lock:
            itens = list(estado.mensagens)
        return [
            asdict(m)
            for m in itens
            if (instance is None or m.instance == instance)
            and (alvo is None or m.telefone == alvo)
        ]

    @app.delete("/simulador/mensagens")
    def limpar() -> dict:
        with estado.lock:
            estado.mensagens.clear()
            estado.falhas_send_text.clear()
        return {"ok": True}

    @app.post("/simulador/falhas")
    def programar_falhas(body: dict = Body(...)) -> dict:
        """Os próximos sendText devolvem estes status HTTP, um por chamada."""
        codigos = body.get("send_text")
        if not isinstance(codigos, list) or not all(
            isinstance(c, int) and 400 <= c <= 599 for c in codigos
        ):
            raise HTTPException(status_code=422, detail="send_text: lista de status 4xx/5xx")
        with estado.lock:
            estado.falhas_send_text = list(codigos)
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def pagina() -> str:
        return _PAGINA

    return app


def create_app_from_env() -> FastAPI:
    """Fábrica para ``uvicorn --factory``; lê a configuração do ambiente."""
    return create_app(
        webhook_url=os.environ.get(
            "SIMULADOR_WEBHOOK_URL", "http://127.0.0.1:8000/whatsapp/webhook"
        ),
        webhook_secret=os.environ.get("EVOLUTION_WEBHOOK_SECRET", ""),
        numero_oficial=os.environ.get("SIMULADOR_NUMERO_OFICIAL", NUMERO_OFICIAL_PADRAO),
    )


_PAGINA = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Simulador de WhatsApp</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 0; background: #ece5dd; color: #111; }
  header { background: #075e54; color: #fff; padding: 12px 16px; }
  header small { opacity: .8; display: block; }
  form.cfg { display: flex; flex-wrap: wrap; gap: 8px; padding: 8px 16px; background: #fff; }
  form.cfg label { font-size: 13px; display: flex; flex-direction: column; }
  #conversa { padding: 16px; display: flex; flex-direction: column; gap: 8px;
              max-width: 720px; margin: 0 auto; min-height: 50vh; }
  .msg { max-width: 75%; padding: 8px 10px; border-radius: 8px; white-space: pre-wrap;
         box-shadow: 0 1px 1px rgba(0,0,0,.1); }
  .entrada { align-self: flex-end; background: #dcf8c6; }
  .saida { align-self: flex-start; background: #fff; }
  .meta { font-size: 11px; color: #555; margin-top: 4px; }
  form.envio { display: flex; gap: 8px; padding: 12px 16px; max-width: 720px; margin: 0 auto; }
  form.envio input { flex: 1; padding: 10px; font-size: 16px; }
  button { padding: 10px 16px; }
</style>
</head>
<body>
<header>Simulador de WhatsApp<small>Nada aqui sai para o WhatsApp real.
Você é o contato; as respostas são do bot.</small></header>
<form class="cfg" onsubmit="return false">
  <label>Instância <input id="instance" value="igreja-dev"></label>
  <label>Telefone do contato <input id="telefone" value="5500988887777"></label>
  <label>Nome <input id="nome" value="Contato simulado"></label>
</form>
<div id="conversa"></div>
<form class="envio" id="envio">
  <input id="texto" placeholder="Mensagem" autocomplete="off">
  <button type="submit">Enviar</button>
</form>
<script>
const $ = (id) => document.getElementById(id);
for (const id of ["instance", "telefone", "nome"]) {
  try { const v = localStorage.getItem("sim-" + id); if (v) $(id).value = v; } catch (e) {}
  $(id).addEventListener("change", () => {
    try { localStorage.setItem("sim-" + id, $(id).value); } catch (e) {}
    carregar();
  });
}
async function carregar() {
  const q = new URLSearchParams({instance: $("instance").value, telefone: $("telefone").value});
  const r = await fetch("/simulador/mensagens?" + q);
  if (!r.ok) return;
  const itens = await r.json();
  const box = $("conversa");
  box.replaceChildren();
  for (const m of itens) {
    const div = document.createElement("div");
    div.className = "msg " + m.direcao;
    div.textContent = m.texto;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = new Date(m.criada_em).toLocaleTimeString() +
      (m.direcao === "entrada" && m.webhook_status !== 202
        ? " · webhook " + (m.webhook_status || "sem resposta do backend") : "");
    div.appendChild(meta);
    box.appendChild(div);
  }
}
$("envio").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const texto = $("texto").value;
  if (!texto.trim()) return;
  $("texto").value = "";
  await fetch("/simulador/mensagens", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({instance: $("instance").value, telefone: $("telefone").value,
                          nome: $("nome").value, texto}),
  });
  carregar();
});
carregar();
setInterval(carregar, 1500);
</script>
</body>
</html>
"""
