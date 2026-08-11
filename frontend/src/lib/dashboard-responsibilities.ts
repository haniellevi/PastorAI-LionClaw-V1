import type { Role } from "./roles";

export type DashboardQueueScope = "igreja" | "celula" | null;

export type DashboardShortcutTarget =
  | "central-celula"
  | "minha-celula"
  | "inbox"
  | "ganhar"
  | "consolidar"
  | "g12"
  | "enviar"
  | "calendario";

export interface DashboardResponsibilities {
  queueScope: DashboardQueueScope;
  hasWorkQueue: boolean;
  canAssignQueue: boolean;
  canLinkCell: boolean;
  showOverview: boolean;
  showTeamWorkload: boolean;
  queueTitle: string;
  queueHint: string;
  emptyQueueText: string;
  homeTitle: string;
  shortcutCandidates: DashboardShortcutTarget[];
}

const FULL_QUEUE_ROLES = new Set<Role>([
  "admin",
  "pastor",
  "lider_g12",
  "lider_consol",
]);

const SHORTCUTS_BY_ROLE: Record<Role, readonly DashboardShortcutTarget[]> = {
  admin: ["central-celula", "inbox", "calendario"],
  pastor: ["central-celula", "inbox", "ganhar", "calendario"],
  lider_g12: ["g12", "ganhar", "consolidar", "inbox", "calendario"],
  lider_consol: ["consolidar", "ganhar", "inbox", "calendario"],
  lider_celula: ["minha-celula", "ganhar", "inbox", "calendario"],
  lider_mult: ["minha-celula", "g12", "enviar", "calendario"],
  operador: ["inbox", "ganhar"],
  membro: ["minha-celula", "calendario"],
};

const SHORTCUT_ORDER: readonly DashboardShortcutTarget[] = [
  "minha-celula",
  "central-celula",
  "inbox",
  "consolidar",
  "ganhar",
  "g12",
  "enviar",
  "calendario",
];

function hasAny(roles: ReadonlySet<string>, candidates: ReadonlySet<Role>): boolean {
  return [...candidates].some((role) => roles.has(role));
}

function queueCopy(roles: ReadonlySet<string>, scope: DashboardQueueScope) {
  if (roles.has("pastor")) {
    return {
      title: "Fila pastoral da igreja",
      hint: "ações autorizadas no seu escopo atual",
      empty: "Nenhuma pendência pastoral aberta agora.",
    };
  }
  if (roles.has("admin")) {
    return {
      title: "Ações da igreja",
      hint: "o que precisa de atenção no seu escopo",
      empty: "Nenhuma ação da igreja pendente agora.",
    };
  }
  if (roles.has("lider_g12")) {
    return {
      title: "Ações da igreja sob sua responsabilidade",
      hint: "itens autorizados para seus papéis atuais",
      empty: "Nenhuma ação sob sua responsabilidade agora.",
    };
  }
  if (roles.has("lider_consol")) {
    return {
      title: "Ações de consolidação",
      hint: "pessoas e próximos passos autorizados",
      empty: "Nenhuma ação de consolidação pendente agora.",
    };
  }
  if (scope === "celula") {
    return {
      title: "Ações sob seus cuidados",
      hint: "sua célula e pessoas sob sua responsabilidade",
      empty: "Nenhuma ação da sua célula pendente agora.",
    };
  }
  return {
    title: "Ações sob sua responsabilidade",
    hint: "o que precisa de atenção",
    empty: "Nenhuma ação sob sua responsabilidade agora.",
  };
}

function homeTitle(roles: ReadonlySet<string>): string {
  const responsibilities = [
    "admin",
    "pastor",
    "lider_g12",
    "lider_consol",
    "lider_celula",
    "lider_mult",
    "operador",
  ].filter((role) => roles.has(role));

  if (responsibilities.length > 1) return "Seus espaços de atuação";
  if (roles.has("lider_mult")) return "Sua responsabilidade: Multiplicação";
  if (roles.has("operador")) return "Seus atendimentos";
  return "Para você";
}

export function resolveDashboardResponsibilities(
  inputRoles: readonly string[],
): DashboardResponsibilities {
  const roles = new Set(inputRoles);
  const fullQueue = hasAny(roles, FULL_QUEUE_ROLES);
  const cellQueue = roles.has("lider_celula");
  const queueScope: DashboardQueueScope = fullQueue
    ? "igreja"
    : cellQueue
      ? "celula"
      : null;
  const copy = queueCopy(roles, queueScope);

  const allowedShortcuts = new Set<DashboardShortcutTarget>();
  for (const role of Object.keys(SHORTCUTS_BY_ROLE) as Role[]) {
    if (!roles.has(role)) continue;
    for (const target of SHORTCUTS_BY_ROLE[role]) allowedShortcuts.add(target);
  }

  return {
    queueScope,
    hasWorkQueue: queueScope !== null,
    canAssignQueue: fullQueue,
    canLinkCell: roles.has("admin") || roles.has("pastor"),
    showOverview: queueScope !== null,
    showTeamWorkload: fullQueue,
    queueTitle: copy.title,
    queueHint: copy.hint,
    emptyQueueText: copy.empty,
    homeTitle: homeTitle(roles),
    shortcutCandidates: SHORTCUT_ORDER.filter((target) => allowedShortcuts.has(target)),
  };
}
