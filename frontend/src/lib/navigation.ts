/**
 * Estrutura da sidebar-nav (paridade protótipo "Igreja 12" — F2 flat).
 * Grupos planos (sem accordion/expand): Gestão, A Jornada G12, Igreja e
 * Configuração (adminOnly). Cada item referencia o screenId/rota por hash
 * (#target). Os `stages` da Jornada guardam head + `subs`: a Sidebar renderiza
 * SÓ o head (flat), e as subs continuam acessíveis via ModuleTabs/deep-link
 * (fonte única — ModuleTabs deriva as abas daqui).
 */
import type { IconKey } from "./icons";

export interface NavItem {
  /** screenId / alvo da rota por hash (#target). */
  target: string;
  label: string;
  icon: IconKey;
  /** Tela bloqueada no MVP (locked-em-breve) — não navega. */
  locked?: boolean;
  /** Badge numérico (ex.: pendências de chat). */
  badge?: string;
  /** Cor do bloco do ícone (protótipo). Default = teal do tema. */
  accent?: "rose" | "amber" | "green" | "indigo" | "whats";
}

export interface NavStage {
  /** Estágio da escada do sucesso (cor própria). */
  stage: "ganhar" | "consolidar" | "discipular" | "enviar";
  /** Cabeçalho do estágio (navega para o painel do estágio). */
  head: NavItem;
  /** Submenus rebaixados (acessíveis via ModuleTabs, não na sidebar flat). */
  subs?: NavItem[];
}

export interface NavSection {
  id: string;
  label: string;
  /** Visível somente para admin (grupo Configuração). */
  adminOnly?: boolean;
  /** Itens diretos (nível 1). */
  items?: NavItem[];
  /** Estágios da escada (a sidebar flat mostra só o head). */
  stages?: NavStage[];
}

export const NAV_SECTIONS: NavSection[] = [
  {
    id: "gestao",
    label: "Igreja",
    items: [
      { target: "dashboard", label: "Painel de Hoje", icon: "dashboard" },
      { target: "minha-celula", label: "Minha Célula", icon: "central-celula" },
      { target: "calendario", label: "Agenda", icon: "calendar" },
      { target: "inbox", label: "Conversas", icon: "chat" },
    ],
  },
  {
    id: "jornada",
    label: "A Jornada G12",
    stages: [
      {
        stage: "ganhar",
        head: { target: "ganhar", label: "Ganhar", icon: "ganhar" },
      },
      {
        stage: "consolidar",
        head: { target: "consolidar", label: "Consolidar", icon: "consolidar" },
        subs: [
          {
            target: "consol-individual",
            label: "Consolidação Individual",
            icon: "consol-individual",
          },
          {
            target: "universidade-vida",
            label: "Universidade da Vida",
            icon: "university",
            locked: true,
          },
        ],
      },
      {
        stage: "discipular",
        head: { target: "g12", label: "Discipular", icon: "discipular" },
        subs: [
          {
            target: "capacitacao",
            label: "Capacitação Destino",
            icon: "capacitacao",
            locked: true,
          },
          { target: "g12", label: "G12 · Descendências", icon: "g12" },
          { target: "central-celula", label: "Central de Célula", icon: "central-celula" },
        ],
      },
      {
        stage: "enviar",
        head: { target: "enviar", label: "Enviar", icon: "enviar" },
      },
    ],
  },
];

/**
 * Seções da superfície administrativa da igreja (admin.<domínio> → /gestao).
 * Reúne as telas que SÓ o admin opera — antes na seção "Configuração" do menu
 * operacional. O painel operacional (app.) não as expõe mais; o admin chega
 * aqui pelo botão "Admin". 'assinatura' segue owner-only (gate isOwner
 * preservado no AdminAppShell e no Sidebar).
 */
export const ADMIN_NAV_SECTIONS: NavSection[] = [
  {
    id: "gestao",
    label: "Gestão",
    items: [
      { target: "setup", label: "Configuração Inicial", icon: "check" },
      { target: "contatos", label: "Pessoas", icon: "team" },
      { target: "comunicados", label: "Comunicação", icon: "broadcast" },
      { target: "identidade", label: "Identidade Visual", icon: "image" },
      { target: "equipe", label: "Membros da Igreja", icon: "team" },
      { target: "permissoes", label: "Permissões", icon: "lock" },
      // Config admin da Agenda (Google + destinatários), antes embutida em
      // #calendario. A operação de eventos (criar/confirmar) segue no app.
      // Rota preservada (`integracoes`); só o rótulo virou "Calendário".
      { target: "integracoes", label: "Calendário", icon: "calendar" },
    ],
  },
  {
    id: "sistema",
    label: "Sistema",
    items: [
      { target: "whatsapp", label: "Conexão WhatsApp", icon: "whatsapp", accent: "whats" },
      { target: "agente", label: "Agente IA", icon: "agent" },
    ],
  },
  {
    id: "financas",
    label: "Finanças",
    // 'assinatura' segue owner-only (o Sidebar remove p/ não-dono); o grupo
    // some inteiro para admin que não é o dono.
    items: [
      { target: "assinatura", label: "Minha Assinatura", icon: "card" },
    ],
  },
];

/** Cor do bloco de ícone por estágio da Jornada (protótipo). */
export const STAGE_ACCENT: Record<NavStage["stage"], NonNullable<NavItem["accent"]>> = {
  ganhar: "rose",
  consolidar: "amber",
  discipular: "green",
  enviar: "indigo",
};

/** Estágio da Jornada G12 a que um screenId pertence (head ou sub-tela);
 *  null se a tela não faz parte da Jornada. Usado pelo JourneyStepper para
 *  destacar a etapa atual mesmo em sub-telas (ex.: consol-individual →
 *  consolidar; g12/central-celula → discipular). */
export function journeyStageOf(target: string): NavStage["stage"] | null {
  const jornada = NAV_SECTIONS.find((s) => s.id === "jornada");
  for (const st of jornada?.stages ?? []) {
    if (st.head.target === target) return st.stage;
    if (st.subs?.some((s) => s.target === target)) return st.stage;
  }
  return null;
}

/** Estágios da Jornada na ordem do contrato (fonte única — NAV_SECTIONS). */
export function journeyStages(): NavStage[] {
  return NAV_SECTIONS.find((s) => s.id === "jornada")?.stages ?? [];
}

/** Rótulo do grupo (eyebrow da topbar) que contém um screenId. */
export function groupLabelForScreen(target: string): string | null {
  for (const section of NAV_SECTIONS) {
    if (section.items?.some((i) => i.target === target)) return section.label;
    const inStage = section.stages?.some(
      (st) => st.head.target === target || st.subs?.some((s) => s.target === target),
    );
    if (inStage) return section.label;
  }
  return null;
}

/** Metadados de tela (título/crumb + info da topbar) para as rotas conhecidas. */
export const SCREEN_META: Record<
  string,
  { title: string; crumb: string; info?: string }
> = {
  setup: {
    title: "Configuração Inicial",
    crumb: "Primeiros passos",
    info: "Itens de configuração recomendados para começar a usar o sistema. Nada aqui bloqueia o uso — são só pendências reais, com atalho para a tela de cada uma.",
  },
  dashboard: {
    title: "Painel de Hoje",
    crumb: "Pendências de hoje",
    info: "Fila de trabalho pastoral — o que exige sua ação hoje.",
  },
  inbox: {
    title: "Conversas",
    crumb: "WhatsApp da Igreja",
    info: "Conversas pelo número oficial. Apenas o número da igreja é registrado — conversas pessoais do pastor não entram aqui.",
  },
  calendario: {
    title: "Agenda da Igreja",
    crumb: "Eventos e cultos",
    info: "Eventos da igreja, sincronizados com o Google Calendar.",
  },
  comunicados: {
    title: "Comunicação",
    crumb: "Envios segmentados",
    info: "Envio segmentado pelo WhatsApp oficial. Contatos com opt-out são excluídos automaticamente.",
  },
  equipe: {
    title: "Membros da Igreja",
    crumb: "Quem tem acesso ao painel",
    info: "Quem tem login no sistema. Cada pessoa acumula papéis, e o menu e o dashboard são a união deles (o que cada papel enxerga é definido em Permissões).",
  },
  contatos: {
    title: "Pessoas",
    crumb: "Todas as pessoas da igreja",
    info: "Lista geral de contatos, visitantes, membros e líderes — filtre por papel/status. O admin pode editar os dados de cada pessoa.",
  },
  ganhar: {
    title: "Ganhar",
    crumb: "Novos contatos e visitantes",
    info: "Quem fala com a igreja vira contato; quem já foi à célula ou a um evento vira visitante — até aceitar Jesus ou completar 3 presenças.",
  },
  consolidar: {
    title: "Consolidar",
    crumb: "Fila de consolidação",
    info: "Quem decidiu por Jesus e precisa de acompanhamento no prazo, da fonovisita à conexão com uma célula.",
  },
  "consol-individual": {
    title: "Consolidação Individual",
    crumb: "Acompanhamento 1:1",
    info: "Acompanhamento individual (1:1) da trilha de consolidação, etapa por etapa.",
  },
  "universidade-vida": {
    title: "Universidade da Vida",
    crumb: "Em breve",
    info: "Trilha de discipulado da Universidade da Vida (em breve).",
  },
  capacitacao: {
    title: "Capacitação Destino",
    crumb: "Em breve",
    info: "Trilha de capacitação de líderes (em breve).",
  },
  g12: {
    title: "G12 · Descendências",
    crumb: "Organograma",
    info: "Organograma G12 e descendências de liderança da igreja.",
  },
  "central-celula": {
    title: "Central de Célula",
    crumb: "Líderes e relatórios",
    info: "Central de células: líderes, relatórios semanais e supervisão.",
  },
  "minha-celula": {
    title: "Minha Célula",
    crumb: "Reunião, avisos e histórico",
    info: "Sua célula: próxima reunião, confirmação de presença, indicação de visitantes, avisos, materiais e seu histórico.",
  },
  enviar: {
    title: "Enviar",
    crumb: "Multiplicações",
    info: "Multiplicação de células — o envio na visão G12.",
  },
  whatsapp: {
    title: "Conexão WhatsApp",
    crumb: "Configuração",
    info: "Conexão do número oficial de WhatsApp da igreja (QR Code e status).",
  },
  agente: {
    title: "Agente IA",
    crumb: "Configuração",
    info: "Configuração do agente de IA: comportamento e credencial do modelo (BYO).",
  },
  identidade: {
    title: "Identidade Visual",
    crumb: "Gestão",
    info: "Logo e aparência da igreja no sistema. Opcional: sem logo, mostramos o nome da igreja.",
  },
  integracoes: {
    title: "Calendário",
    crumb: "Google Agenda e avisos",
    info: "Conexão com o Google Agenda e destinatários dos avisos da Agenda.",
  },
  assinatura: {
    title: "Minha Assinatura",
    crumb: "Finanças",
    info: "Plano e assinatura da igreja.",
  },
  permissoes: {
    title: "Permissões",
    crumb: "Matriz papel × tela",
    info: "Matriz papel × tela: o que cada papel enxerga no menu e no dashboard.",
  },
  celulas: {
    title: "Células",
    crumb: "Cadastro",
    info: "Cadastro das células da igreja, com líder e cobertura.",
  },
  relatorios: {
    title: "Relatórios",
    crumb: "Recebidos e pendentes",
    info: "Relatórios semanais de célula: recebidos e pendentes.",
  },
  perfil: {
    title: "Meu Perfil",
    crumb: "Conta",
    info: "Seus dados de acesso: nome de exibição e senha.",
  },
};
