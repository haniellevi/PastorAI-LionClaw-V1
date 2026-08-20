"use strict";

const fs = require("node:fs");

const FALLBACK_CHECK = {
  name: "external-probe",
  ok: false,
  detail: "relatório ausente ou inválido",
};

function fallbackReport() {
  return { ok: false, checks: [FALLBACK_CHECK] };
}

function normalizedCheck(value, index) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {
      name: `external-probe-${index + 1}`,
      ok: false,
      detail: "item de relatório inválido",
    };
  }
  return {
    name: typeof value.name === "string" && value.name ? value.name : `external-probe-${index + 1}`,
    ok: value.ok === true,
    detail: typeof value.detail === "string" && value.detail ? value.detail : "sem detalhe público",
  };
}

function normalizeReport(value) {
  if (!value || typeof value !== "object" || Array.isArray(value) || !Array.isArray(value.checks) || value.checks.length === 0) {
    return fallbackReport();
  }
  const checks = value.checks.map(normalizedCheck);
  return {
    ok: value.ok === true && checks.every((check) => check.ok),
    checks,
    checkedAt: typeof value.checked_at === "string" ? value.checked_at : undefined,
  };
}

function readReport(reportPath = "production-monitor-report.json") {
  try {
    return normalizeReport(JSON.parse(fs.readFileSync(reportPath, "utf8")));
  } catch (_) {
    return fallbackReport();
  }
}

function reportTime(report, now) {
  return report.checkedAt || now();
}

function failureLines(report) {
  const failed = report.checks.filter((check) => !check.ok);
  return failed.length
    ? failed.map((check) => `- **${check.name}**: ${check.detail}`).join("\n")
    : "- Falha sem detalhe público.";
}

async function maintainIncident({ github, context, probeOutcome, reportPath, now = () => new Date().toISOString() }) {
  const owner = context.repo.owner;
  const repo = context.repo.repo;
  const label = "production-monitor";
  const title = "[Monitor] Produção PastorAI indisponível";
  const report = readReport(reportPath);
  const healthy = probeOutcome === "success" && report.ok === true;

  try {
    await github.rest.issues.getLabel({ owner, repo, name: label });
  } catch (error) {
    if (error.status !== 404) throw error;
    await github.rest.issues.createLabel({
      owner,
      repo,
      name: label,
      color: "B60205",
      description: "Incidente detectado pelo monitor de produção",
    });
  }

  const open = await github.paginate(github.rest.issues.listForRepo, {
    owner,
    repo,
    state: "open",
    labels: label,
    per_page: 100,
  });
  const incidents = open.filter((item) => !item.pull_request && item.title === title);
  const checkedAt = reportTime(report, now);

  if (!healthy && incidents.length === 0) {
    await github.rest.issues.create({
      owner,
      repo,
      title,
      body: `O monitor externo detectou uma falha.\n\n${failureLines(report)}\n\nVerificação: ${checkedAt}`,
      labels: [label],
    });
  } else if (!healthy && incidents.length > 0) {
    await github.rest.issues.update({
      owner,
      repo,
      issue_number: incidents[0].number,
      body: `O monitor externo ainda detecta falha.\n\n${failureLines(report)}\n\nVerificação: ${checkedAt}`,
    });
  } else if (healthy) {
    for (const incident of incidents) {
      await github.rest.issues.createComment({
        owner,
        repo,
        issue_number: incident.number,
        body: `Produção recuperada em ${checkedAt}.`,
      });
      await github.rest.issues.update({
        owner,
        repo,
        issue_number: incident.number,
        state: "closed",
        state_reason: "completed",
      });
    }
  }

  return healthy;
}

module.exports = { maintainIncident, normalizeReport, readReport };
