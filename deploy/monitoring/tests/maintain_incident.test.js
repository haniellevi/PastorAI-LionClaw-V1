"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { maintainIncident, normalizeReport } = require("../maintain_incident.js");

async function withReport(contents, callback) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "pastorai-monitor-"));
  const reportPath = path.join(directory, "production-monitor-report.json");
  fs.writeFileSync(reportPath, contents, "utf8");
  try {
    return await callback(reportPath);
  } finally {
    fs.rmSync(directory, { recursive: true, force: true });
  }
}

test("normalizeReport accepts a healthy structured report", () => {
  const report = normalizeReport({
    ok: true,
    checked_at: "2026-08-20T00:00:00Z",
    checks: [{ name: "api-readiness", ok: true, detail: "HTTP 200 HTTPS" }],
  });

  assert.deepEqual(report, {
    ok: true,
    checkedAt: "2026-08-20T00:00:00Z",
    checks: [{ name: "api-readiness", ok: true, detail: "HTTP 200 HTTPS" }],
  });
});

test("normalizeReport fails closed for invalid roots and missing checks", () => {
  for (const value of [null, [], {}, { ok: true }, { ok: true, checks: [] }]) {
    assert.deepEqual(normalizeReport(value), {
      ok: false,
      checks: [
        {
          name: "external-probe",
          ok: false,
          detail: "relatório ausente ou inválido",
        },
      ],
    });
  }
});

test("normalizeReport converts malformed checks into safe failures", () => {
  const report = normalizeReport({
    ok: true,
    checks: [null, { name: "api-readiness", ok: "true", detail: 404 }],
  });

  assert.equal(report.ok, false);
  assert.deepEqual(report.checks, [
    {
      name: "external-probe-1",
      ok: false,
      detail: "item de relatório inválido",
    },
    {
      name: "api-readiness",
      ok: false,
      detail: "sem detalhe público",
    },
  ]);
});

test("maintainIncident records an incident when a valid JSON report has an invalid shape", async () => {
  const created = [];
  const github = {
    rest: {
      issues: {
        getLabel: async () => ({}),
        create: async (payload) => created.push(payload),
      },
    },
    paginate: async () => [],
  };

  await withReport("null", async (reportPath) => {
    const healthy = await maintainIncident({
      github,
      context: { repo: { owner: "owner", repo: "repo" } },
      probeOutcome: "success",
      reportPath,
      now: () => "2026-08-20T00:00:00Z",
    });

    assert.equal(healthy, false);
  });

  assert.equal(created.length, 1);
  assert.match(created[0].body, /relatório ausente ou inválido/);
});
