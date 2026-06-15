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
  dashboard: { title: "Dashboard", crumb: "Pendências de hoje" },
  inbox: { title: "Chat", crumb: "WhatsApp da Igreja" },
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
  ganhar: { title: "Ganhar", crumb: "Novos contatos e visitantes" },
  consolidar: { title: "Consolidar", crumb: "Fila de consolidação" },
  "consol-individual": { title: "Consolidação Individual", crumb: "Acompanhamento 1:1" },
  "universidade-vida": { title: "Universidade da Vida", crumb: "Em breve" },
  capacitacao: { title: "Capacitação Destino", crumb: "Em breve" },
  g12: { title: "G12 · Descendências", crumb: "Organograma" },
  "central-celula": { title: "Central de Célula", crumb: "Líderes e relatórios" },
  enviar: { title: "Enviar", crumb: "Multiplicações" },
  whatsapp: { title: "Conexão WhatsApp", crumb: "Configuração" },
  agente: { title: "Agente IA", crumb: "Configuração" },
  assinatura: { title: "Assinatura", crumb: "Configuração" },
  permissoes: { title: "Permissões", crumb: "Matriz papel × tela" },
  contatos: { title: "Contatos", crumb: "Cadastro" },
  celulas: { title: "Células", crumb: "Cadastro" },
  relatorios: { title: "Relatórios", crumb: "Recebidos e pendentes" },
};
