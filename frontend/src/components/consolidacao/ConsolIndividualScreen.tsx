"use client";

/**
 * Tela #consol-individual — Consolidação Individual (US-37/39, api-pipeline).
 *
 * Área RESTRITA (CONSOLIDATION_ROLES). Lista quem está em consolidação e, ao
 * clicar numa pessoa, abre o track-modal da trilha — onde só o consolidador
 * responsável confirma etapas (gate de identidade) e concluir exige todas as
 * etapas obrigatórias. Lançar decisão na própria tela abre o decision-modal.
 */
import { DataTable, type Column } from "@/components/ui/DataTable";
import { StatusPill } from "@/components/dashboard/StatusPill";
import {
  MANDATORY_ETAPAS,
  TRACK_STEPS,
  canConsolidate,
  countMandatory,
  derivedStages,
  etapaLabel,
  mergeStages,
  nextMandatory,
} from "@/lib/consolidacao-api";
import { Icon } from "@/lib/icons";

import { AccessDenied } from "./AccessDenied";
import { DecisionModal } from "./DecisionModal";
import { TrackModal } from "./TrackModal";
import { useConsolidation } from "./useConsolidation";

import "../contacts/people-ux-v2.css";

export function ConsolIndividualScreen() {
  const c = useConsolidation();
  const allowed = canConsolidate(c.roles);

  // storeVersion no closure garante recomputo após confirmações de etapa.
  void c.storeVersion;
  const rows = c.people.map((p) => {
    const session = c.sessionFor(p.id);
    const stages = mergeStages(derivedStages(p), session?.confirmedStages);
    return {
      contact: p,
      done: countMandatory(stages),
      next: nextMandatory(stages),
      consolidador: c.consolidadorName(p.id),
    };
  });

  if (!allowed) {
    return <AccessDenied title="Consolidação Individual" route="consol-individual" />;
  }

  const total = MANDATORY_ETAPAS.length;
  const showSkeleton = c.loading && !c.loaded;

  const columns: Array<Column<(typeof rows)[number]>> = [
    { header: "Pessoa", cell: ({ contact }) => <span className="nm">{contact.nome}</span> },
    { header: "Consolidador", cell: ({ consolidador }) => consolidador ?? <StatusPill tone="warn">Não informado</StatusPill> },
    { header: "Etapas registradas", cell: ({ done, next }) => (
      <><div className="num">{done} de {total} obrigatórias</div><div className="people-meta">{next ? `Próxima: ${etapaLabel(next)}` : "Etapas obrigatórias registradas"}</div></>
    ) },
    { header: "Acompanhamento", cell: ({ contact }) => (
      <button type="button" className="btn btn-sm" aria-label={`Abrir trilha de ${contact.nome}`}
        onKeyDown={(e) => e.stopPropagation()}
        onClick={(e) => { e.stopPropagation(); c.openTrack(contact); }}>
        Abrir trilha
      </button>
    ) },
  ];

  return (
    <div className="screen journey-screen journey-screen--consolidar people-ux" key="consol-individual">
      <div className="screen-head">
        <div className="titles">
          <h2>Consolidação individual</h2>
          <p>Confira os registros e confirme a próxima etapa de cada pessoa.</p>
        </div>
        <div className="actions">
          <button type="button" className="btn btn-primary" onClick={() => c.openDecision()}>
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

      <div className="people-work-list">
        <div className="card">
          <div className="panel-title">
            <span>Em andamento</span>
            <span className="count">{showSkeleton ? "Carregando…" : c.loaded ? `${rows.length} ${rows.length === 1 ? "pessoa" : "pessoas"} na lista` : "Lista indisponível"}</span>
          </div>
          {showSkeleton ? (
            <div className="queue">
              {Array.from({ length: 4 }).map((_, i) => (
                <div className="qitem skeleton" key={i}>
                  <span className="qicon sk-icon" />
                  <div className="qbody">
                    <div className="sk-line sk-md" />
                    <div className="sk-line sk-sm" />
                  </div>
                </div>
              ))}
            </div>
          ) : !c.loaded ? null : rows.length === 0 ? (
            <div className="empty-state" style={{ padding: "var(--s6)" }}>
              <Icon name="consol-individual" />
              <p>
                <strong>Nenhuma consolidação em andamento.</strong> Lance uma decisão
                por Jesus para iniciar o acompanhamento individual.
              </p>
            </div>
          ) : (
            <DataTable
              className="people-table"
              columns={columns}
              rows={rows}
              rowKey={({ contact }) => contact.id}
              onRowClick={({ contact }) => c.openTrack(contact)}
              empty={{ icon: "consol-individual", title: "Nenhuma consolidação nesta lista." }}
            />
          )}
        </div>

        <details className="people-disclosure people-overview">
          <summary>Como funciona a trilha</summary>
          <div className="track">
            {TRACK_STEPS.map((step, i) => {
              // Sequência informativa, sem simular progresso de uma pessoa.
              const cls = "stop";
              return (
                <div className={cls} key={step.etapa}>
                  <span className="dot">
                    {i + 1}
                  </span>
                  <div>
                    <div className="nm">
                      {step.label}
                      {step.optional ? <span className="seg-chip">opcional</span> : null}
                    </div>
                    <div className="sub" style={{ color: "var(--muted)" }}>
                      {step.desc}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          <p className="lock-note" style={{ marginTop: "var(--s3)" }}>
            <Icon name="lock" />
            Concluídas todas as visitas, a pessoa é marcada como consolidada individual
            no registro. A gestão de turmas da Universidade da Vida ainda está indisponível.
          </p>
        </details>
      </div>

      {c.decisionOpen ? (
        <DecisionModal
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
