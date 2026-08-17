import type { Contact } from "@/lib/contacts-api";
import type { TeamMember } from "@/lib/dashboard-api";

export interface CellLeaderOption {
  id: string;
  nome: string;
  selectable: boolean;
  current: boolean;
  blocksSave: boolean;
  reason: string | null;
}

/** Status legado NULL e o status explícito `ativo` representam acesso pronto. */
export function hasActivePanelAccess(status: string | null | undefined): boolean {
  return status === null || status === "ativo";
}

function accessReason(members: readonly TeamMember[]): string | null {
  const active = members.filter((member) => hasActivePanelAccess(member.status));
  if (active.length === 1) return null;
  if (active.length > 1) return "Mais de um acesso ativo";
  if (members.length === 0) return "Sem acesso ao painel";
  if (members.some((member) => member.status === "convidado")) {
    return "Acesso ainda não ativado";
  }
  if (members.some((member) => member.status === "revogado")) return "Acesso revogado";
  return `Acesso indisponível (${members[0]?.status ?? "desconhecido"})`;
}

/**
 * Combina a aptidão pastoral da Pessoa com o acesso operacional da Equipe.
 * Candidatos sem acesso pronto permanecem visíveis, mas não selecionáveis. O
 * líder atual continua visível; se estiver irregular, a pendência bloqueia o
 * salvamento até a regularização ou a escolha de outro líder.
 */
export function buildCellLeaderOptions(
  contacts: readonly Contact[],
  team: readonly TeamMember[],
  currentLeaderId: string | null | undefined,
): CellLeaderOption[] {
  const teamByPerson = new Map<string, TeamMember[]>();
  for (const member of team) {
    if (!member.pessoaId) continue;
    const group = teamByPerson.get(member.pessoaId) ?? [];
    group.push(member);
    teamByPerson.set(member.pessoaId, group);
  }

  return contacts
    .filter((contact) => {
      const current = contact.id === currentLeaderId;
      if (current) return true;
      return contact.aptoLider && !contact.liderDeCelula && !contact.semInteresse;
    })
    .map((contact): CellLeaderOption => {
      const current = contact.id === currentLeaderId;
      const members = teamByPerson.get(contact.id) ?? [];
      const unavailableAccess = accessReason(members);

      if (current) {
        const nonBlockingWarnings = [
          !contact.aptoLider ? "não atende aos critérios atuais de liderança" : null,
          contact.semInteresse ? "está classificado como sem interesse ministerial" : null,
        ].filter((item): item is string => Boolean(item));
        const blocksSave = unavailableAccess !== null;
        const accessBlock = unavailableAccess?.toLowerCase() ?? null;
        const nonBlockingNotice = nonBlockingWarnings.length
          ? ` Aviso cadastral não bloqueante: ${nonBlockingWarnings.join("; ")}.`
          : "";
        let reason = "Líder atual";
        if (blocksSave) {
          reason = `Pendência bloqueante no acesso do líder atual: ${accessBlock}. Regularize o acesso ou escolha outro líder antes de salvar.${nonBlockingNotice}`;
        } else if (nonBlockingWarnings.length) {
          reason = `Líder atual. Aviso cadastral não bloqueante: ${nonBlockingWarnings.join("; ")}`;
        }
        return {
          id: contact.id,
          nome: contact.nome,
          selectable: !blocksSave,
          current: true,
          blocksSave,
          reason,
        };
      }

      return {
        id: contact.id,
        nome: contact.nome,
        selectable: unavailableAccess === null,
        current: false,
        blocksSave: false,
        reason: unavailableAccess,
      };
    })
    .sort(
      (a, b) =>
        Number(b.current) - Number(a.current) ||
        a.nome.localeCompare(b.nome, "pt-BR", { sensitivity: "base" }),
    );
}

/** Opção mínima para superfícies fora da Central, sempre somente leitura. */
export function currentLeaderReadOnlyOption(
  contacts: readonly Contact[],
  currentLeaderId: string | null | undefined,
): CellLeaderOption[] {
  if (!currentLeaderId) return [];
  const current = contacts.find((contact) => contact.id === currentLeaderId);
  return current
    ? [
        {
          id: current.id,
          nome: current.nome,
          selectable: true,
          current: true,
          blocksSave: false,
          reason: "Líder atual",
        },
      ]
    : [];
}
