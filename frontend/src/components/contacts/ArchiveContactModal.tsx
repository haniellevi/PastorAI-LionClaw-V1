"use client";

/**
 * Confirmação de arquivamento de Pessoa (M7B-W3.2B — só frontend; backend já
 * em produção). Preflight (GET .../offboarding-preflight) decide se pode
 * arquivar agora: havendo bloqueadores, a confirmação nem aparece — só a
 * lista do que precisa ser resolvido antes. Sem bloqueadores, mostra os
 * efeitos automáticos e os dados preservados, e exige motivo (nunca hard
 * delete: cadastro e histórico continuam intactos).
 */
import { useState } from "react";

import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { DsField } from "@/components/ds/Field";
import type { Contact, OffboardingPreflight, OffboardingPreflightItem } from "@/lib/contacts-api";
import { Icon } from "@/lib/icons";

function PreflightItems({ items }: { items: OffboardingPreflightItem[] }) {
  return (
    <ul style={{ margin: "6px 0 0", paddingLeft: "1.1em" }}>
      {items.map((item, i) => (
        <li key={`${item.tipo}-${item.recurso_id ?? i}`}>
          <strong>{item.rotulo}</strong>
          {item.recurso_nome ? <>: {item.recurso_nome}</> : null}
          {item.acao_recomendada ? <div className="sub">{item.acao_recomendada}</div> : null}
        </li>
      ))}
    </ul>
  );
}

export function ArchiveContactModal({
  contact,
  preflight,
  preflightLoading,
  preflightError,
  busy,
  error,
  onRetryPreflight,
  onClose,
  onConfirm,
}: {
  contact: Contact;
  preflight: OffboardingPreflight | null;
  preflightLoading: boolean;
  preflightError: string | null;
  busy: boolean;
  error: string | null;
  onRetryPreflight: () => void;
  onClose: () => void;
  onConfirm: (motivo: string) => void;
}) {
  const [motivo, setMotivo] = useState("");
  const [touched, setTouched] = useState(false);

  const podeArquivar = preflight?.pode_arquivar ?? false;
  const motivoError = touched && !motivo.trim() ? "Informe o motivo do arquivamento." : undefined;

  function submit() {
    setTouched(true);
    if (!motivo.trim() || busy) return;
    onConfirm(motivo.trim());
  }

  return (
    <DsDialog
      open
      onClose={() => {
        if (!busy) onClose();
      }}
      title="Arquivar pessoa"
      description={`Arquivar ${contact.nome} não exclui o cadastro nem o histórico.`}
      footer={
        <>
          <DsButton variant="tertiary" onClick={onClose} disabled={busy}>
            {podeArquivar ? "Cancelar" : "Fechar"}
          </DsButton>
          {podeArquivar ? (
            <DsButton variant="danger" loading={busy} onClick={submit}>
              <Icon name="lock" />
              <span>{busy ? "Arquivando…" : "Arquivar pessoa"}</span>
            </DsButton>
          ) : null}
        </>
      }
    >
      <>
        {preflightLoading ? (
          <p className="sub">Verificando vínculos ativos…</p>
        ) : preflightError ? (
          <DsBanner
            kind="error"
            action={
              <DsButton variant="tertiary" onClick={onRetryPreflight}>
                Tentar novamente
              </DsButton>
            }
          >
            {preflightError}
          </DsBanner>
        ) : preflight ? (
          <>
            <div className="preserve-note" role="note">
              <Icon name="shield" />
              <span>
                O cadastro <strong>não é excluído</strong>. Arquivar apenas marca a pessoa
                como desligada — o histórico abaixo é preservado por completo:
                <PreflightItems items={preflight.preservados} />
              </span>
            </div>

            {preflight.bloqueadores.length > 0 ? (
              <DsBanner kind="error">
                <strong>Não é possível arquivar agora.</strong> Resolva antes de continuar:
                <PreflightItems items={preflight.bloqueadores} />
              </DsBanner>
            ) : null}

            {podeArquivar && preflight.automaticos.length > 0 ? (
              <DsBanner kind="warning">
                <strong>Efeito automático ao arquivar:</strong>
                <PreflightItems items={preflight.automaticos} />
              </DsBanner>
            ) : null}

            {podeArquivar ? (
              <form
                className="modal-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  submit();
                }}
              >
                <DsField
                  as="textarea"
                  label="Motivo do arquivamento"
                  rows={3}
                  maxLength={2000}
                  value={motivo}
                  onChange={(e) => setMotivo(e.target.value)}
                  error={motivoError}
                  disabled={busy}
                  placeholder="Explique por que esta pessoa está sendo desligada."
                  data-autofocus=""
                />
              </form>
            ) : null}

            {error ? <DsBanner kind="error">{error}</DsBanner> : null}
          </>
        ) : null}
      </>
    </DsDialog>
  );
}
