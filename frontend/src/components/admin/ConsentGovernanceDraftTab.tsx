"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import {
  AdminRequestError,
  AdminSessionExpiredError,
  CONSENT_GOVERNANCE_PURPOSES,
  fetchIgrejaConsentGovernance,
  initializeIgrejaConsentGovernance,
  updateIgrejaConsentGovernancePurpose,
  type AdminConsentGovernancePurposeDraft,
  type AdminConsentGovernanceState,
  type ConsentGovernanceDecisionPayload,
  type ConsentGovernancePurpose,
} from "@/lib/admin-api";

const FIELD_MAX_LENGTH = 4_000;
const PAYLOAD_MAX_LENGTH = 16_000;

const PURPOSE_LABELS: Record<ConsentGovernancePurpose, string> = {
  atendimento_solicitado: "Atendimento solicitado",
  cuidado_pastoral: "Cuidado pastoral",
  tarefas_operacionais: "Tarefas operacionais",
  comunicados: "Comunicados",
};

const DRAFT_FIELDS = [
  {
    key: "realProcessingAgents",
    label: "Quem participa do processamento",
    help: "Liste somente funções, equipes e tipos de fornecedor, sem identificar pessoas.",
  },
  {
    key: "operationsAndMinimumData",
    label: "Operações e dados mínimos",
    help: "Descreva operações e categorias de dados, sem exemplos, valores ou registros reais.",
  },
  {
    key: "dataSensitivityAssessment",
    label: "Avaliação operacional da sensibilidade",
    help: "Classifique categorias que exigem proteção adicional, sem reproduzir dados reais.",
  },
  {
    key: "operationalNeed",
    label: "Necessidade operacional",
    help: "Explique o processo e o objetivo institucional, sem relatar casos individuais.",
  },
  {
    key: "systemsAndRecipients",
    label: "Sistemas e destinatários",
    help: "Informe sistemas e categorias de destinatários, sem nomes ou contatos pessoais.",
  },
  {
    key: "retentionAndDisposalInventory",
    label: "Inventário de retenção e descarte",
    help: "Mapeie retenção e descarte por categoria, sem copiar registros armazenados.",
  },
  {
    key: "operatorInstructions",
    label: "Instruções para operadores",
    help: "Descreva procedimentos gerais, sem usar situações ou conversas de pessoas reais.",
  },
  {
    key: "openQuestions",
    label: "Questões em aberto",
    help: "Registre dúvidas de política em termos gerais, sem casos, mensagens ou identidades.",
  },
] as const satisfies ReadonlyArray<{
  key: keyof ConsentGovernanceDecisionPayload;
  label: string;
  help: string;
}>;

type DraftField = (typeof DRAFT_FIELDS)[number]["key"];
type DraftForm = Record<DraftField, string>;

const EMPTY_FORM: DraftForm = {
  realProcessingAgents: "",
  operationsAndMinimumData: "",
  dataSensitivityAssessment: "",
  operationalNeed: "",
  systemsAndRecipients: "",
  retentionAndDisposalInventory: "",
  operatorInstructions: "",
  openQuestions: "",
};

function toForm(payload: ConsentGovernanceDecisionPayload): DraftForm {
  return Object.fromEntries(
    DRAFT_FIELDS.map(({ key }) => [key, payload[key] ?? ""]),
  ) as DraftForm;
}

function toPayload(form: DraftForm): ConsentGovernanceDecisionPayload {
  const value = (key: DraftField) => form[key].trim() || null;
  return {
    realProcessingAgents: value("realProcessingAgents"),
    operationsAndMinimumData: value("operationsAndMinimumData"),
    dataSensitivityAssessment: value("dataSensitivityAssessment"),
    operationalNeed: value("operationalNeed"),
    systemsAndRecipients: value("systemsAndRecipients"),
    retentionAndDisposalInventory: value("retentionAndDisposalInventory"),
    operatorInstructions: value("operatorInstructions"),
    openQuestions: value("openQuestions"),
  };
}

function findPurpose(
  state: AdminConsentGovernanceState,
  purpose: ConsentGovernancePurpose,
): AdminConsentGovernancePurposeDraft | undefined {
  return state.purposes.find((item) => item.purpose === purpose);
}

function completedFields(draft: AdminConsentGovernancePurposeDraft): number {
  return DRAFT_FIELDS.filter(({ key }) => Boolean(draft.decisionPayload[key]?.trim()))
    .length;
}

export interface ConsentGovernanceDraftTabProps {
  token: string;
  igrejaId: string;
  initialState: AdminConsentGovernanceState;
  onExpired: () => void;
  onStateChange?: (state: AdminConsentGovernanceState) => void;
}

/**
 * Preparação operacional do pacote D2B2b3A. Não contém ações de aprovação,
 * catálogo, ativação ou escrita de consentimento.
 */
export function ConsentGovernanceDraftTab({
  token,
  igrejaId,
  initialState,
  onExpired,
  onStateChange,
}: ConsentGovernanceDraftTabProps) {
  const [state, setState] = useState(initialState);
  const [selectedPurpose, setSelectedPurpose] =
    useState<ConsentGovernancePurpose | null>(null);
  const [form, setForm] = useState<DraftForm>(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selectedDraft = selectedPurpose
    ? findPurpose(state, selectedPurpose)
    : undefined;
  const totalLength = useMemo(
    () => DRAFT_FIELDS.reduce((total, { key }) => total + form[key].length, 0),
    [form],
  );
  const dirty = selectedDraft
    ? DRAFT_FIELDS.some(({ key }) => {
        const current = form[key].trim() || null;
        const saved = selectedDraft.decisionPayload[key]?.trim() || null;
        return current !== saved;
      })
    : false;

  if (!state.enabled) return null;

  const applyState = (next: AdminConsentGovernanceState) => {
    setState(next);
    onStateChange?.(next);
  };

  const handleError = (err: unknown, fallback: string): string | null => {
    if (err instanceof AdminSessionExpiredError) {
      onExpired();
      return null;
    }
    return err instanceof Error ? err.message : fallback;
  };

  const refreshAfterConflict = async (message: string) => {
    try {
      const current = await fetchIgrejaConsentGovernance(token, igrejaId);
      applyState(current);
      if (selectedPurpose) {
        const currentDraft = findPurpose(current, selectedPurpose);
        if (currentDraft) setForm(toForm(currentDraft.decisionPayload));
      }
      setError(message);
    } catch (err) {
      const nextError = handleError(
        err,
        "O rascunho mudou em outra sessão e não foi possível recarregá-lo.",
      );
      if (nextError) setError(nextError);
    }
  };

  const initialize = async () => {
    if (
      !window.confirm(
        "Iniciar os quatro rascunhos operacionais desta igreja? Isso não aprova, " +
          "não ativa e não publica nenhuma finalidade.",
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await initializeIgrejaConsentGovernance(token, igrejaId);
      applyState(next);
      setNotice("Quatro rascunhos operacionais iniciados.");
    } catch (err) {
      if (err instanceof AdminRequestError && err.status === 409) {
        await refreshAfterConflict(
          "Os rascunhos já foram iniciados em outra sessão. Exibimos a versão atual.",
        );
      } else {
        const nextError = handleError(err, "Não foi possível iniciar os rascunhos.");
        if (nextError) setError(nextError);
      }
    } finally {
      setBusy(false);
    }
  };

  const openEditor = (purpose: ConsentGovernancePurpose) => {
    const draft = findPurpose(state, purpose);
    if (!draft) return;
    if (
      dirty &&
      !window.confirm("Descartar as alterações não salvas deste rascunho?")
    ) {
      return;
    }
    setSelectedPurpose(purpose);
    setForm(toForm(draft.decisionPayload));
    setError(null);
    setNotice(null);
  };

  const save = async () => {
    if (!selectedPurpose || !selectedDraft || busy) return;
    if (totalLength > PAYLOAD_MAX_LENGTH) {
      setError(
        `O conjunto dos campos ultrapassa ${PAYLOAD_MAX_LENGTH.toLocaleString("pt-BR")} caracteres.`,
      );
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await updateIgrejaConsentGovernancePurpose(
        token,
        igrejaId,
        selectedPurpose,
        {
          expectedRevision: selectedDraft.revision,
          decisionPayload: toPayload(form),
        },
      );
      applyState(next);
      const savedDraft = findPurpose(next, selectedPurpose);
      if (savedDraft) setForm(toForm(savedDraft.decisionPayload));
      setNotice("Rascunho operacional salvo. Ele continua não aprovado.");
    } catch (err) {
      if (err instanceof AdminRequestError && err.status === 409) {
        await refreshAfterConflict(
          "Este rascunho foi alterado em outra sessão. Recarregamos a versão atual; revise antes de salvar novamente.",
        );
      } else {
        const nextError = handleError(err, "Não foi possível salvar o rascunho.");
        if (nextError) setError(nextError);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <section aria-labelledby="consent-governance-title">
      <div
        data-testid="draft-only-banner"
        role="status"
        aria-live="polite"
        className="card card-pad"
        style={{
          marginBottom: "var(--s4)",
          borderColor: "var(--warn)",
          background: "var(--surface-2)",
        }}
      >
        <h2 id="consent-governance-title" style={{ margin: 0, fontSize: "1rem" }}>
          Rascunho, não aprovado
        </h2>
        <p className="sub" style={{ margin: "var(--s1) 0 0", color: "var(--muted)" }}>
          O Master prepara fatos e propostas operacionais. Este espaço não registra
          aprovação da igreja, não publica conteúdo e não libera o agente.
        </p>
        <p className="sub" style={{ margin: "var(--s2) 0 0", color: "var(--danger)" }}>
          <strong>Não inclua dados pessoais:</strong> nomes, telefones, e-mails,
          documentos, mensagens, relatos ou qualquer dado de uma pessoa real.
        </p>
      </div>

      {error ? (
        <div className="error-banner" role="alert" style={{ marginBottom: "var(--s3)" }}>
          <span>{error}</span>
        </div>
      ) : null}
      {notice ? (
        <div
          className="error-banner"
          role="status"
          style={{
            marginBottom: "var(--s3)",
            background: "var(--accent-soft)",
            color: "var(--accent)",
          }}
        >
          <span>{notice}</span>
        </div>
      ) : null}

      {!state.initialized ? (
        <div className="card card-pad">
          <h3 style={{ marginTop: 0 }}>Preparar a governança desta igreja</h3>
          <p className="sub" style={{ color: "var(--muted)" }}>
            A inicialização cria quatro rascunhos vazios e separados por finalidade.
            Nenhum deles terá autoridade operacional.
          </p>
          <Button
            variant="primary"
            size="sm"
            loading={busy}
            loadingText="Iniciando…"
            onClick={() => void initialize()}
          >
            Iniciar quatro rascunhos
          </Button>
        </div>
      ) : (
        <>
          <div
            aria-label="Finalidades em preparação"
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))",
              gap: "var(--s3)",
              marginBottom: "var(--s4)",
            }}
          >
            {CONSENT_GOVERNANCE_PURPOSES.map((purpose) => {
              const draft = findPurpose(state, purpose);
              return (
                <article
                  key={purpose}
                  data-testid="governance-purpose-card"
                  className="card card-pad"
                  aria-labelledby={`purpose-${purpose}`}
                >
                  <h3 id={`purpose-${purpose}`} style={{ margin: 0, fontSize: "1rem" }}>
                    {draft?.purposeLabel || PURPOSE_LABELS[purpose]}
                  </h3>
                  <p className="sub" style={{ color: "var(--muted)" }}>
                    Rascunho, não aprovado
                    {draft
                      ? ` · ${completedFields(draft)} de ${DRAFT_FIELDS.length} campos preenchidos`
                      : " · indisponível"}
                  </p>
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={!draft || busy}
                    aria-controls="governance-draft-editor"
                    aria-expanded={selectedPurpose === purpose}
                    onClick={() => openEditor(purpose)}
                  >
                    Editar rascunho
                  </Button>
                </article>
              );
            })}
          </div>

          {selectedPurpose && selectedDraft ? (
            <form
              id="governance-draft-editor"
              className="card card-pad"
              aria-labelledby="governance-editor-title"
              onSubmit={(event) => {
                event.preventDefault();
                void save();
              }}
            >
              <div style={{ marginBottom: "var(--s4)" }}>
                <h3 id="governance-editor-title" style={{ margin: 0 }}>
                  {selectedDraft.purposeLabel || PURPOSE_LABELS[selectedPurpose]}
                </h3>
                <p className="sub" style={{ margin: "var(--s1) 0 0", color: "var(--muted)" }}>
                  Registre fatos observáveis e propostas operacionais. Deixe decisões
                  jurídicas ou aprovações para as etapas humanas próprias.
                </p>
              </div>

              {DRAFT_FIELDS.map(({ key, label, help }) => {
                const helpId = `governance-${selectedPurpose}-${key}-help`;
                return (
                  <div className="field" key={key} style={{ marginBottom: "var(--s3)" }}>
                    <label htmlFor={`governance-${selectedPurpose}-${key}`}>{label}</label>
                    <textarea
                      id={`governance-${selectedPurpose}-${key}`}
                      rows={4}
                      maxLength={FIELD_MAX_LENGTH}
                      value={form[key]}
                      disabled={busy}
                      aria-describedby={`${helpId} governance-payload-total`}
                      onChange={(event) =>
                        setForm((current) => ({ ...current, [key]: event.target.value }))
                      }
                    />
                    <span id={helpId} className="sub" style={{ color: "var(--muted)" }}>
                      {help} {form[key].length.toLocaleString("pt-BR")}/
                      {FIELD_MAX_LENGTH.toLocaleString("pt-BR")}
                    </span>
                  </div>
                );
              })}

              <div
                id="governance-payload-total"
                role={totalLength > PAYLOAD_MAX_LENGTH ? "alert" : undefined}
                style={{
                  color: totalLength > PAYLOAD_MAX_LENGTH ? "var(--danger)" : "var(--muted)",
                  marginBottom: "var(--s3)",
                }}
              >
                Total: {totalLength.toLocaleString("pt-BR")}/
                {PAYLOAD_MAX_LENGTH.toLocaleString("pt-BR")} caracteres
              </div>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                loading={busy}
                loadingText="Salvando…"
                disabled={!dirty || totalLength > PAYLOAD_MAX_LENGTH}
              >
                Salvar rascunho
              </Button>
            </form>
          ) : null}
        </>
      )}

      <p className="sub" style={{ color: "var(--muted)", marginTop: "var(--s3)" }}>
        Contrato {state.schemaVersion} · revisão {state.revision}
      </p>
    </section>
  );
}
