/**
 * Loaders compartilhados pelas telas sob demanda e pelo prefetch por intenção.
 * Manter a função de importação num único lugar garante que o Next reutilize o
 * mesmo chunk quando o usuário passa o mouse e quando a rota é renderizada.
 */
export const loadCalendarioScreen = () =>
  import("@/components/calendario/CalendarioScreen");
export const loadCelulasScreen = () => import("@/components/cells/CelulasScreen");
export const loadAgenteScreen = () => import("@/components/config/AgenteScreen");
export const loadAssinaturaScreen = () =>
  import("@/components/config/AssinaturaScreen");
export const loadEquipeScreen = () => import("@/components/config/EquipeScreen");
export const loadIdentidadeVisualScreen = () =>
  import("@/components/config/IdentidadeVisualScreen");
export const loadIntegracoesScreen = () =>
  import("@/components/config/IntegracoesScreen");
export const loadPermissoesScreen = () =>
  import("@/components/config/PermissoesScreen");
export const loadSetupChecklistScreen = () =>
  import("@/components/config/SetupChecklistScreen");
export const loadCentralCelulaScreen = () =>
  import("@/components/central-celula/CentralCelulaScreen");
export const loadMinhaCelulaEntry = () =>
  import("@/components/minha-celula/MinhaCelulaEntry");
export const loadComunicadosScreen = () =>
  import("@/components/comunicados/ComunicadosScreen");
export const loadConsolIndividualScreen = () =>
  import("@/components/consolidacao/ConsolIndividualScreen");
export const loadConsolidarScreen = () =>
  import("@/components/consolidacao/ConsolidarScreen");
export const loadLockedScreen = () =>
  import("@/components/consolidacao/LockedScreen");
export const loadContatosScreen = () =>
  import("@/components/contacts/ContatosScreen");
export const loadGanharScreen = () => import("@/components/contacts/GanharScreen");
export const loadDashboardScreen = () =>
  import("@/components/dashboard/DashboardScreen");
export const loadEnviarScreen = () => import("@/components/enviar/EnviarScreen");
export const loadG12Screen = () => import("@/components/g12/G12Screen");
export const loadInboxScreen = () => import("@/components/inbox/InboxScreen");
export const loadRelatoriosScreen = () =>
  import("@/components/reports/RelatoriosScreen");
export const loadWhatsappScreen = () =>
  import("@/components/whatsapp/WhatsappScreen");
export const loadPerfilScreen = () => import("@/components/profile/PerfilScreen");

const SCREEN_MODULE_LOADERS: Record<string, () => Promise<unknown>> = {
  calendario: loadCalendarioScreen,
  celulas: loadCelulasScreen,
  agente: loadAgenteScreen,
  assinatura: loadAssinaturaScreen,
  equipe: loadEquipeScreen,
  identidade: loadIdentidadeVisualScreen,
  integracoes: loadIntegracoesScreen,
  permissoes: loadPermissoesScreen,
  setup: loadSetupChecklistScreen,
  "central-celula": loadCentralCelulaScreen,
  "minha-celula": loadMinhaCelulaEntry,
  comunicados: loadComunicadosScreen,
  "consol-individual": loadConsolIndividualScreen,
  consolidar: loadConsolidarScreen,
  "universidade-vida": loadLockedScreen,
  capacitacao: loadLockedScreen,
  contatos: loadContatosScreen,
  ganhar: loadGanharScreen,
  dashboard: loadDashboardScreen,
  enviar: loadEnviarScreen,
  g12: loadG12Screen,
  inbox: loadInboxScreen,
  relatorios: loadRelatoriosScreen,
  whatsapp: loadWhatsappScreen,
  perfil: loadPerfilScreen,
};

/** Inicia o download do chunk sem bloquear o clique nem alterar a rota. */
export function preloadScreenModule(route: string): void {
  const load = SCREEN_MODULE_LOADERS[route];
  if (load) void load();
}
