"use client";

/**
 * Tela #consol-individual — Consolidação Individual (US-37/39, api-pipeline).
 *
 * Área RESTRITA (CONSOLIDATION_ROLES). Lista quem está em consolidação e, ao
 * clicar numa pessoa, abre o track-modal da trilha — onde só o consolidador
 * responsável confirma etapas (gate de identidade) e concluir exige todas as
 * etapas obrigatórias. Lançar decisão na própria tela abre o decision-modal.
 */
import { StatusPill } from "@/components/dashboard/StatusPill";
import {
  MANDATORY_ETAPAS,
  TRACK_STEPS,
  canConsolidate,
  countMandatory,
  derivedStages,
  mergeStages,
  nextMandatory,
} from "@/lib/consolidacao-api";
import type { Contact } from "@/lib/contacts-api";
import { Icon } from "@/lib/icons";

import { AccessDenied } from "./AccessDenied";
import { DecisionModal } from "./DecisionModal";
import { TrackModal } from "./TrackModal";
import { useConsolidation } from "./useConsolidation";

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
      consolidador: c.consolidadorName(p.id),
    };
  });

  if (!allowed) {
    return <AccessDenied title="Consolidação Individual" route="consol-individual" />;
  }

  const total = MANDATORY_ETAPAS.length;
  const showSkeleton = c.loading && !c.loaded;

  return (
    <div className="screen" key="consol-individual">
      <div className="screen-head">
        <div className="titles">
          <h2>Consolidação Individual</h2>
          <p>
            Acompanhamento um a um de quem decidiu por Jesus. Clique numa pessoa para
            abrir a trilha. Quem confirma cada visita é o consolidador dela — a central
            apenas supervisiona, e o orquestrador lembra quem estiver em atraso.
          </p>
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

      <div className="grid-2" style={{ alignItems: "start" }}>
        <div className="card">
          <div className="panel-title">
            <span>Em andamento</span>
            <span className="count">· clique para abrir a trilha</span>
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
          ) : rows.length === 0 ? (
            <div className="empty-state" style={{ padding: "var(--s6)" }}>
              <Icon name="consol-individual" />
              <p>
                <strong>Nenhuma consolidação em andamento.</strong> Lance uma decisão
                por Jesus para iniciar o acompanhamento individual.
              </p>
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Pessoa</th>
                  <th>Consolidador</th>
                  <th className="num">Progresso</th>
                  <th style={{ width: "1px" }} />
                </tr>
              </thead>
              <tbody>
                {rows.map(({ contact, done, consolidador }) => (
                  <TrackRow
                    key={contact.id}
                    contact={contact}
                    done={done}
                    total={total}
                    consolidador={consolidador}
                    onOpen={() => c.openTrack(contact)}
                  />
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card card-pad">
          <div className="panel-title" style={{ padding: "0 0 var(--s3)" }}>
            Como funciona a trilha
          </div>
          <div className="track">
            {TRACK_STEPS.map((step, i) => {
              // Card informativo: ilustra done (1-2), now (fonovisita) e pendente.
              const cls =
                i < 2 ? "stop done" : i === 2 ? "stop now" : "stop";
              return (
                <div className={cls} key={step.etapa}>
                  <span className="dot">
                    {i < 2 ? <Icon name="check" /> : i + 1}
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
            e entra no critério para a Universidade da Vida.
          </p>
        </div>
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

function TrackRow({
  contact,
  done,
  total,
  consolidador,
  onOpen,
}: {
  contact: Contact;
  done: number;
  total: number;
  consolidador: string | null;
  onOpen: () => void;
}) {
  return (
    <tr
      className="row-link"
      onClick={onOpen}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
    >
      <td className="nm">{contact.nome}</td>
      <td>
        {consolidador ? (
          <span className="sub">{consolidador}</span>
        ) : (
          <StatusPill tone="warn">Sem consolidador</StatusPill>
        )}
      </td>
      <td className="num">
        {done} / {total}
      </td>
      <td>
        <Icon name="caret" />
      </td>
    </tr>
  );
}
