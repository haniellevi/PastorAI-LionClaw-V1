/**
 * Estrutura da sidebar-nav (seção 4.2 / artifact travado).
 * Grupos: Igreja (Gestão), Visão G12 (escada do sucesso) e Configuração
 * (adminOnly). Cada item referencia o screenId/rota por hash (#target).
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
}

export interface NavStage {
  /** Estágio da escada do sucesso (cor própria). */
  stage: "ganhar" | "consolidar" | "discipular" | "enviar";
  /** Cabeçalho do estágio (navega para o painel do estágio). */
  head: NavItem;
  /** Submenus rebaixados (nível 3). */
  subs?: NavItem[];
}

export interface NavSection {
  id: string;
  label: string;
  /** Visível somente para admin (grupo Configuração). */
  adminOnly?: boolean;
  /** Itens diretos (nível 1). */
  items?: NavItem[];
  /** Estágios da escada (nível 2/3). */
  stages?: NavStage[];
  /** Estado inicial expandido. */
  defaultOpen?: boolean;
}

export const NAV_SECTIONS: NavSection[] = [
  {
    id: "igreja",
    label: "Igreja",
    defaultOpen: true,
    items: [
      { target: "dashboard", label: "Dashboard", icon: "dashboard" },
      { target: "inbox", label: "Chat", icon: "chat" },
      { target: "calendario", label: "Agenda da Igreja", icon: "calendar" },
      { target: "comunicados", label: "Comunicação", icon: "broadcast" },
      { target: "equipe", label: "Equipe", icon: "team" },
    ],
  },
  {
    id: "g12",
    label: "Visão G12",
    defaultOpen: false,
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
  {
    id: "config",
    label: "Configuração",
    adminOnly: true,
    defaultOpen: false,
    items: [
      { target: "whatsapp", label: "Conexão WhatsApp", icon: "whatsapp" },
      { target: "agente", label: "Agente IA", icon: "agent" },
      { target: "assinatura", label: "Assinatura", icon: "card" },
      { target: "permissoes", label: "Permissões", icon: "lock" },
    ],
  },
];

/** Metadados de tela (título/crumb + info da topbar) para as rotas conhecidas. */
export const SCREEN_META: Record<
  string,
  { title: string; crumb: string; info?: string }
> = {
  dashboard: {
    title: "Dashboard",
    crumb: "Pendências de hoje",
    info: "Fila de trabalho pastoral — o que exige sua ação hoje.",
  },
  inbox: {
    title: "Chat",
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
    title: "Equipe",
    crumb: "Quem usa o sistema",
    info: "Quem tem acesso ao painel. Cada pessoa acumula papéis, e o menu e o dashboard são a união deles (o que cada papel enxerga é definido em Permissões).",
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
  assinatura: {
    title: "Assinatura",
    crumb: "Configuração",
    info: "Plano e assinatura da igreja.",
  },
  permissoes: {
    title: "Permissões",
    crumb: "Matriz papel × tela",
    info: "Matriz papel × tela: o que cada papel enxerga no menu e no dashboard.",
  },
  contatos: {
    title: "Contatos",
    crumb: "Cadastro",
    info: "Todas as pessoas da igreja. Filtre por acompanhamento e conecte a células.",
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
};
