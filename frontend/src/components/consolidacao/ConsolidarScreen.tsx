"use client";

/**
 * Tela #consolidar — Painel do Consolidar (US-37/38/40, delta-019).
 *
 * Área RESTRITA: só abre para CONSOLIDATION_ROLES (admin · pastor · lider_consol);
 * os demais papéis veem o access-denied. Reúne a fila de consolidação individual
 * (com deadline-badge de 24h nos visitantes), a prévia da próxima Universidade da
 * Vida (botão locked-em-breve) e a base 100% consolidada com filtros.
 *
 * Lançar decisão abre o decision-modal (célula/visitante). Ver progresso abre o
 * track-modal da trilha individual.
 */
import { useMemo, useState } from "react";

import { DeadlineBadge } from "@/components/dashboard/DeadlineBadge";
import { StatusPill } from "@/components/dashboard/StatusPill";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { canConsolidate, derivedStages, etapaLabel, mergeStages, nextMandatory } from "@/lib/consolidacao-api";
import type { Contact } from "@/lib/contacts-api";
import { computeDeadline } from "@/lib/deadline";
import { initials } from "@/lib/g12-api";
import { Icon, type IconKey } from "@/lib/icons";

import { AccessDenied } from "./AccessDenied";
import { DecisionModal } from "./DecisionModal";
import { TrackModal } from "./TrackModal";
import { isConsolidated, useConsolidation } from "./useConsolidation";

import "../contacts/people-ux-v2.css";

function genderLabel(g: string | null): string {
  if (g === "f") return "Feminino";
  if (g === "m") return "Masculino";
  return "—";
}

export function ConsolidarScreen() {
  const c = useConsolidation();
  const [fCelula, setFCelula] = useState("");
  const [fGen, setFGen] = useState("");

  const allowed = canConsolidate(c.roles);

  const { pending, consolidated } = useMemo(() => {
    const pendingList: Contact[] = [];
    const consolidatedList: Contact[] = [];
    for (const p of c.people) {
      if (isConsolidated(p)) consolidatedList.push(p);
      else pendingList.push(p);
    }
    return { pending: pendingList, consolidated: consolidatedList };
  }, [c.people]);

  const lateCount = useMemo(
    () =>
      pending.filter((p) => {
        const prazo = c.prazoByPessoa.get(p.id) ?? null;
        return computeDeadline(prazo, c.now).tone === "late";
      }).length,
    [pending, c.prazoByPessoa, c.now],
  );

  const filteredConsolidated = useMemo(
    () =>
      consolidated.filter(
        (p) =>
          (!fCelula || p.celulaId === fCelula) && (!fGen || p.genero === fGen),
      ),
    [consolidated, fCelula, fGen],
  );

  // ---- early returns ------------------------------------------------------
  if (!allowed) {
    return <AccessDenied title="Consolidar" route="consolidar" />;
  }

  const showSkeleton = c.loading && !c.loaded;

  const stats: Array<{ icon: IconKey; label: string; value: string | number; delta: string; alert?: boolean }> = [
    {
      icon: "user",
      label: "Em acompanhamento",
      value: pending.length,
      delta: "acompanhamento pendente",
      alert: pending.length > 0,
    },
    {
      icon: "check",
      label: "Consolidação concluída",
      value: consolidated.length,
      delta: "individual e/ou UV",
    },
    {
      icon: "clock",
      label: "Visitantes em atraso",
      value: c.deadlinesReady ? lateCount : "…",
      delta: c.deadlinesReady ? "prazo de 24h vencido" : "prazos aguardando confirmação",
      alert: lateCount > 0,
    },
  ];

  const consColumns: Array<Column<Contact>> = [
    {
      header: "Pessoa",
      cell: (p) => (
        <>
          <div className="nm">{p.nome}</div>
          <div className="sub">Consolidação concluída</div>
        </>
      ),
    },
    { header: "Célula", cell: (p) => c.cellName(p.celulaId) },
    { header: "Gênero", cell: (p) => genderLabel(p.genero) },
    {
      header: "Consolidação",
      cell: () => <StatusPill tone="ok">Consolidado</StatusPill>,
    },
  ];

  return (
    <div className="screen journey-screen journey-screen--consolidar people-ux" key="consolidar">
      <div className="screen-head">
        <div className="titles">
          <h2>Cuidado de novos discípulos</h2>
          <p>Acompanhe os cuidados em andamento.</p>
        </div>
        <div className="actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => c.openDecision()}
          >
            <Icon name="plus" />
            <span>Lançar decisão</span>
          </button>
        </div>
      </div>

      {c.error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{c.error}</span>
          <button type="button" className="btn btn-sm" onClick={c.reload} disabled={c.loading}>
            Tentar novamente
          </button>
        </div>
      ) : null}

      {c.supportError ? <p role="status" className="people-meta">{c.supportError}</p> : null}
      {c.hasMore ? <div className="people-toolbar"><span role="status">{c.people.length} de {c.pipelineTotal} pessoas carregadas</span><button type="button" className="btn btn-sm" disabled={c.loadingMore || c.loading} onClick={() => void c.loadMore()}>{c.loadingMore ? "Carregando…" : "Carregar mais pessoas"}</button></div> : null}
      <div className="people-work-list">
        <div className="card">
          <div className="panel-title">
            <span>
              <Icon name="user" /> Em acompanhamento
            </span>
            <span className="count">{showSkeleton ? "Carregando…" : c.loaded ? `${pending.length} pessoas na lista` : "Lista indisponível"}</span>
          </div>
          {showSkeleton ? (
            <div className="queue">
              {Array.from({ length: 3 }).map((_, i) => (
                <div className="qitem skeleton" key={i}>
                  <span className="qicon sk-icon" />
                  <div className="qbody">
                    <div className="sk-line sk-md" />
                    <div className="sk-line sk-sm" />
                  </div>
                </div>
              ))}
            </div>
          ) : !c.loaded ? null : pending.length === 0 ? (
            <div className="empty-state" style={{ padding: "var(--s6)" }}>
              <Icon name="check" />
              <p>
                <strong>{c.hasMore ? "Nenhum acompanhamento entre as pessoas carregadas." : "Nenhum acompanhamento pendente nesta lista."}</strong> Decisões
                registradas no estágio Consolidar aparecem aqui.
              </p>
            </div>
          ) : (
            <div className="queue">
              {pending.map((p) => {
                const prazo = c.prazoByPessoa.get(p.id) ?? null;
                const stages = mergeStages(derivedStages(p), c.sessionFor(p.id)?.confirmedStages);
                const next = nextMandatory(stages);
                const responsavel = c.consolidadorName(p.id);
                return (
                  <div className="qitem" key={p.id}>
                    <span className="qicon v">
                      <Icon name="user" />
                    </span>
                    <div className="qbody">
                      <strong>{p.nome}</strong>
                      <div className="meta">
                        {p.celulaId
                          ? c.cellName(p.celulaId)
                          : "Nenhuma célula vinculada"}
                      </div>
                      <div className="people-meta">{responsavel ? `Consolidador: ${responsavel}` : "Consolidador não informado"}</div>
                      <div className="people-next-label">
                        {next ? `Próxima etapa: ${etapaLabel(next)}` : "Etapas obrigatórias registradas"}
                      </div>
                      {prazo ? (
                        <DeadlineBadge prazo={prazo} now={c.now} prefix="prazo 24h" />
                      ) : null}
                    </div>
                    <div className="qactions">
                      <button
                        type="button"
                        className="btn btn-sm"
                        aria-label={`Ver progresso de ${p.nome}`}
                        onClick={() => c.openTrack(p)}
                      >
                        Ver progresso
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

      </div>

      <div className="card" style={{ marginTop: "var(--s4)" }}>
        <div className="panel-title">
          <span>
            <Icon name="check" /> Consolidação concluída
          </span>
          <span className="count">· individual e/ou UV</span>
        </div>
        <div className="filter-bar">
          <div className="fg">
            <label htmlFor="f-celula">Célula</label>
            <select id="f-celula" value={fCelula} onChange={(e) => setFCelula(e.target.value)}>
              <option value="">Todas</option>
              {c.cells.map((cell) => (
                <option key={cell.id} value={cell.id}>
                  {cell.nome}
                </option>
              ))}
            </select>
          </div>
          <div className="fg">
            <label htmlFor="f-gen">Gênero</label>
            <select id="f-gen" value={fGen} onChange={(e) => setFGen(e.target.value)}>
              <option value="">Todos</option>
              <option value="f">Feminino</option>
              <option value="m">Masculino</option>
            </select>
          </div>
          {c.loaded ? <div className="fcount">
            <strong>{filteredConsolidated.length}</strong> pessoas
          </div> : null}
        </div>
        {showSkeleton ? (
          <div className="queue">
            {Array.from({ length: 3 }).map((_, i) => (
              <div className="qitem skeleton" key={i}>
                <span className="qicon sk-icon" />
                <div className="qbody">
                  <div className="sk-line sk-md" />
                  <div className="sk-line sk-sm" />
                </div>
              </div>
            ))}
          </div>
        ) : !c.loaded ? null : (
          <DataTable
            className="people-table"
            columns={consColumns}
            rows={filteredConsolidated}
            rowKey={(p) => p.id}
            empty={{
              icon: "check",
              title: "Nenhuma consolidação concluída com esses filtros.",
              hint: "Conclua trilhas individuais para ver a base consolidada crescer.",
            }}
          />
        )}
      </div>

      {c.loaded || showSkeleton ? <details className="people-disclosure people-overview">
        <summary>Resumo do acompanhamento</summary>
      <div className="stat-grid">
        {showSkeleton
          ? Array.from({ length: 4 }).map((_, i) => (
              <div className="stat skeleton" key={i}>
                <div className="sk-line sk-sm" />
                <div className="sk-line sk-lg" />
              </div>
            ))
          : stats.map((s) => (
              <div className={`stat${s.alert ? " alert" : ""}`} key={s.label}>
                <div className="lbl">
                  <Icon name={s.icon} />
                  {s.label}
                </div>
                <div className="val num">{s.value}</div>
                <div className="delta">{s.delta}</div>
              </div>
            ))}
      </div>

        <p className="people-meta">Contagens das pessoas carregadas dentro do seu acesso atual.</p>
      </details> : null}
      <details className="people-disclosure people-overview">
        <summary>Universidade da Vida: disponibilidade</summary>
          <div className="people-module-info">
            <div className="panel-title">
              <span>
                <Icon name="document" /> Universidade da Vida
              </span>
              <span className="count">· módulo indisponível</span>
            </div>
            {!c.loaded ? null : consolidated.length === 0 ? (
              <div className="empty-state" style={{ padding: "var(--s6)" }}>
                <Icon name="university" />
                <p>
                  <strong>Nenhuma consolidação concluída nesta lista.</strong> A gestão
                  de turmas da Universidade da Vida ainda está indisponível.
                </p>
              </div>
            ) : (
              <div>
                {consolidated.slice(0, 5).map((p) => (
                  <div className="list-row" key={p.id}>
                    <span className="avatar">{initials(p.nome)}</span>
                    <div style={{ flex: 1 }}>
                      <div className="nm">{p.nome}</div>
                      <div className="sub">
                        {p.celulaId ? `${c.cellName(p.celulaId)} · ` : ""}
                        consolidado individual
                      </div>
                    </div>
                    <span className="pill muted">Consolidado</span>
                  </div>
                ))}
              </div>
            )}
            <div style={{ padding: "var(--s3) var(--s4)" }}>
              <button
                type="button"
                className="btn btn-sm locked-soon"
                disabled
                aria-disabled
                title="A gestão de turmas da Universidade da Vida ainda está indisponível"
              >
                Abrir turma da UV <Icon name="clock" />
              </button>
            </div>
          </div>
      </details>

      {c.decisionOpen ? (
        <DecisionModal
          token={c.token}
          onSessionExpired={c.expireSession}
          contacts={c.contacts}
          cells={c.cells}
          defaultPessoaId={c.decisionPessoa}
          busy={c.decisionBusy}
          error={c.decisionError}
          onClose={c.closeDecision}
          onSubmit={(input) => void c.handleLaunch(input)}
        />
      ) : null}

      {c.trackContact ? (
        <TrackModal
          contact={c.trackContact}
          session={c.sessionFor(c.trackContact.id)}
          selfId={c.selfId}
          consolidadorName={c.consolidadorName(c.trackContact.id)}
          now={c.now}
          busy={c.trackBusy}
          error={c.trackError}
          onClose={c.closeTrack}
          onConfirm={(etapa) => void c.handleConfirm(etapa)}
          onConclude={() => void c.handleConclude()}
        />
      ) : null}

      {c.toast ? (
        <div className={`toast ${c.toast.kind}`} role="status">
          <Icon name={c.toast.kind === "ok" ? "check" : "alert"} />
          <span>{c.toast.text}</span>
        </div>
      ) : null}
    </div>
  );
}
