import assert from "node:assert/strict";
import http from "node:http";
import net from "node:net";

export function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      assert(address && typeof address === "object");
      const { port } = address;
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

export function request(port, path, host = `127.0.0.1:${port}`) {
  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        hostname: "127.0.0.1",
        port,
        path,
        method: "GET",
        headers: { Host: host, Connection: "close" },
      },
      (res) => {
        const chunks = [];
        res.once("error", reject);
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("end", () => {
          resolve({
            status: res.statusCode,
            headers: res.headers,
            cspHeaderCount: res.headersDistinct["content-security-policy"]?.length ?? 0,
            body: Buffer.concat(chunks).toString("utf8"),
          });
        });
      },
    );
    req.setTimeout(5_000, () => req.destroy(new Error("HTTP timeout")));
    req.once("error", reject);
    req.end();
  });
}

export function assertPublicPage(response, path) {
  assert.equal(response.status, 200, `${path}: status`);
  return response;
}
