"use client";

/**
 * overview-section — faixa "Visão geral" do dashboard (#2): KPIs + totais por
 * tipo de pessoa e por etapa G12. Escopo vem do backend (igreja inteira para
 * admin/pastor/sênior; só as células do líder de célula).
 */
import { StatCard, type StatCardData } from "./StatCard";
import type { OverviewStats } from "@/lib/dashboard-api";
import type { IconKey } from "@/lib/icons";

// "lider" saiu de porTipo: líder de célula é DERIVADO (lideresCelula, do
// vínculo celulas.lider_id em célula ativa) — regra 2026-07-06.
const TIPO_ORDER: Array<[string, string]> = [
  ["contato", "Contatos"],
  ["visitante", "Visitantes"],
  ["discipulo", "Discípulos"],
  ["membro", "Membros"],
  ["pastor", "Pastores"],
  ["sem_interesse", "Sem interesse"],
];

const ETAPA_ORDER: Array<[string, string, IconKey]> = [
  ["ganhar", "Ganhar", "ganhar"],
  ["consolidar", "Consolidar", "consolidar"],
  ["discipular", "Discipular", "discipular"],
  ["enviar", "Enviar", "enviar"],
];

export function OverviewSection({ stats }: { stats: OverviewStats }) {
  // Pills "Por tipo" + o contador derivado de líderes (após Membros).
  const tipoPills: Array<{ key: string; label: string; value: number }> = [
    ...TIPO_ORDER.slice(0, 4).map(([key, label]) => ({
      key,
      label,
      value: stats.porTipo[key] ?? 0,
    })),
    {
      key: "lideres_celula",
      label: "Líderes de célula",
      value: stats.lideresCelula ?? 0,
    },
    ...TIPO_ORDER.slice(4).map(([key, label]) => ({
      key,
      label,
      value: stats.porTipo[key] ?? 0,
    })),
  ];

  const kpis: StatCardData[] = [
    { icon: "team", label: "Pessoas", value: stats.total, delta: "no total" },
    {
      icon: "check",
      label: "Decisões por Jesus",
      value: stats.decisoesJesus,
      delta: "decisões registradas",
    },
    {
      icon: "central-celula",
      label: "Células ativas",
      value: stats.celulasAtivas,
      delta: "com líder",
    },
    {
      icon: "alert",
      label: "Sem interesse (CSIM)",
      value: stats.semInteresse,
      delta: "fora do funil",
    },
  ];

  return (
    <section className="overview" aria-label="Visão geral">
      <h3 className="ov-head">
        Visão geral
        <span className="ov-scope">
          {stats.scope === "celula" ? "totais da sua célula" : "totais da igreja"}
        </span>
      </h3>

      <div className="stat-grid">
        {kpis.map((k) => (
          <StatCard key={k.label} {...k} />
        ))}
      </div>

      <div className="overview-breakdown">
        <div className="card card-pad">
          <h4 className="ov-title">Por tipo</h4>
          <div className="ov-pills">
            {tipoPills.map((p) => (
              <span className="ov-pill" key={p.key}>
                <span className="ov-pill-label">{p.label}</span>
                <span className="ov-pill-val num">{p.value}</span>
              </span>
            ))}
          </div>
        </div>

        <div className="card card-pad">
          <h4 className="ov-title">Por etapa (G12)</h4>
          <div className="ov-pills">
            {ETAPA_ORDER.map(([key, label]) => (
              <span className="ov-pill" key={key}>
                <span className="ov-pill-label">{label}</span>
                <span className="ov-pill-val num">{stats.porEtapa[key] ?? 0}</span>
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
