"use client";

/**
 * Casca de tela: roteia para a implementação real quando existe (ex.: dashboard)
 * e, para as demais rotas, mantém a casca + cabeçalho — provando que a navegação
 * por hash troca de tela sem reload.
 */
import dynamic from "next/dynamic";

import { ModuleTabs } from "./ModuleTabs";
import {
  loadAgenteScreen,
  loadAssinaturaScreen,
  loadCalendarioScreen,
  loadCelulasScreen,
  loadCentralCelulaScreen,
  loadComunicadosScreen,
  loadConsolIndividualScreen,
  loadConsolidarScreen,
  loadContatosScreen,
  loadDashboardScreen,
  loadEnviarScreen,
  loadEquipeScreen,
  loadG12Screen,
  loadGanharScreen,
  loadIdentidadeVisualScreen,
  loadInboxScreen,
  loadIntegracoesScreen,
  loadLockedScreen,
  loadMinhaCelulaEntry,
  loadPerfilScreen,
  loadPermissoesScreen,
  loadRelatoriosScreen,
  loadSetupChecklistScreen,
  loadWhatsappScreen,
} from "./screen-loaders";
import { Icon } from "@/lib/icons";
import { SCREEN_META } from "@/lib/navigation";

function ScreenLoading() {
  return (
    <div className="screen" role="status" aria-live="polite" aria-busy="true">
      <div className="card" style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span className="spinner" aria-hidden="true" />
        <span>Carregando tela…</span>
      </div>
    </div>
  );
}

const CalendarioScreen = dynamic(
  () => loadCalendarioScreen().then((m) => m.CalendarioScreen),
  { loading: ScreenLoading },
);
const CelulasScreen = dynamic(
  () => loadCelulasScreen().then((m) => m.CelulasScreen),
  { loading: ScreenLoading },
);
const AgenteScreen = dynamic(
  () => loadAgenteScreen().then((m) => m.AgenteScreen),
  { loading: ScreenLoading },
);
const AssinaturaScreen = dynamic(
  () => loadAssinaturaScreen().then((m) => m.AssinaturaScreen),
  { loading: ScreenLoading },
);
const EquipeScreen = dynamic(
  () => loadEquipeScreen().then((m) => m.EquipeScreen),
  { loading: ScreenLoading },
);
const IdentidadeVisualScreen = dynamic(
  () => loadIdentidadeVisualScreen().then((m) => m.IdentidadeVisualScreen),
  { loading: ScreenLoading },
);
const IntegracoesScreen = dynamic(
  () => loadIntegracoesScreen().then((m) => m.IntegracoesScreen),
  { loading: ScreenLoading },
);
const PermissoesScreen = dynamic(
  () => loadPermissoesScreen().then((m) => m.PermissoesScreen),
  { loading: ScreenLoading },
);
const SetupChecklistScreen = dynamic(
  () => loadSetupChecklistScreen().then((m) => m.SetupChecklistScreen),
  { loading: ScreenLoading },
);
const CentralCelulaScreen = dynamic(
  () => loadCentralCelulaScreen().then((m) => m.CentralCelulaScreen),
  { loading: ScreenLoading },
);
const MinhaCelulaEntry = dynamic(
  () => loadMinhaCelulaEntry().then((m) => m.MinhaCelulaEntry),
  { loading: ScreenLoading },
);
const ComunicadosScreen = dynamic(
  () => loadComunicadosScreen().then((m) => m.ComunicadosScreen),
  { loading: ScreenLoading },
);
const ConsolIndividualScreen = dynamic(
  () => loadConsolIndividualScreen().then((m) => m.ConsolIndividualScreen),
  { loading: ScreenLoading },
);
const ConsolidarScreen = dynamic(
  () => loadConsolidarScreen().then((m) => m.ConsolidarScreen),
  { loading: ScreenLoading },
);
const LockedScreen = dynamic(
  () => loadLockedScreen().then((m) => m.LockedScreen),
  { loading: ScreenLoading },
);
const ContatosScreen = dynamic(
  () => loadContatosScreen().then((m) => m.ContatosScreen),
  { loading: ScreenLoading },
);
const GanharScreen = dynamic(
  () => loadGanharScreen().then((m) => m.GanharScreen),
  { loading: ScreenLoading },
);
const DashboardScreen = dynamic(
  () => loadDashboardScreen().then((m) => m.DashboardScreen),
  { loading: ScreenLoading },
);
const EnviarScreen = dynamic(
  () => loadEnviarScreen().then((m) => m.EnviarScreen),
  { loading: ScreenLoading },
);
const G12Screen = dynamic(
  () => loadG12Screen().then((m) => m.G12Screen),
  { loading: ScreenLoading },
);
const InboxScreen = dynamic(
  () => loadInboxScreen().then((m) => m.InboxScreen),
  { loading: ScreenLoading },
);
const RelatoriosScreen = dynamic(
  () => loadRelatoriosScreen().then((m) => m.RelatoriosScreen),
  { loading: ScreenLoading },
);
const WhatsappScreen = dynamic(
  () => loadWhatsappScreen().then((m) => m.WhatsappScreen),
  { loading: ScreenLoading },
);
const PerfilScreen = dynamic(
  () => loadPerfilScreen().then((m) => m.PerfilScreen),
  { loading: ScreenLoading },
);

export function ScreenView({ route, param }: { route: string; param?: string | null }) {
  const meta = SCREEN_META[route] ?? { title: "Tela", crumb: "" };

  // Telas implementadas.
  if (route === "dashboard") {
    return <DashboardScreen />;
  }
  if (route === "ganhar") {
    return <GanharScreen />;
  }
  if (route === "contatos") {
    return <ContatosScreen selectedId={param ?? null} />;
  }
  if (route === "celulas") {
    return <CelulasScreen />;
  }
  if (route === "g12") {
    return (
      <>
        <ModuleTabs group="discipular" />
        <G12Screen />
      </>
    );
  }
  if (route === "enviar") {
    return <EnviarScreen />;
  }
  if (route === "consolidar") {
    return (
      <>
        <ModuleTabs group="consolidar" />
        <ConsolidarScreen />
      </>
    );
  }
  if (route === "consol-individual") {
    return (
      <>
        <ModuleTabs group="consolidar" />
        <ConsolIndividualScreen />
      </>
    );
  }
  if (route === "inbox") {
    return <InboxScreen />;
  }
  if (route === "whatsapp") {
    return <WhatsappScreen />;
  }
  if (route === "relatorios") {
    return <RelatoriosScreen />;
  }
  if (route === "central-celula") {
    return (
      <>
        <ModuleTabs group="discipular" />
        <CentralCelulaScreen />
      </>
    );
  }
  if (route === "minha-celula") {
    return <MinhaCelulaEntry />;
  }
  if (route === "comunicados") {
    return <ComunicadosScreen />;
  }
  if (route === "calendario") {
    return <CalendarioScreen />;
  }
  if (route === "equipe") {
    return <EquipeScreen />;
  }
  if (route === "permissoes") {
    return <PermissoesScreen />;
  }
  if (route === "assinatura") {
    return <AssinaturaScreen />;
  }
  if (route === "agente") {
    return <AgenteScreen />;
  }
  if (route === "identidade") {
    return <IdentidadeVisualScreen />;
  }
  if (route === "setup") {
    return <SetupChecklistScreen />;
  }
  if (route === "integracoes") {
    return <IntegracoesScreen />;
  }
  if (route === "universidade-vida") {
    return <LockedScreen variant="universidade-vida" />;
  }
  if (route === "capacitacao") {
    return <LockedScreen variant="capacitacao" />;
  }
  if (route === "perfil") {
    return <PerfilScreen />;
  }

  return (
    <div className="screen" key={route}>
      <div className="screen-head">
        <div className="titles">
          <h2>{meta.title}</h2>
          {meta.crumb ? <p>{meta.crumb}</p> : null}
        </div>
      </div>

      <div className="card">
        <div className="scaffold">
          <Icon name="construction" className="scaffold-ic" />
          <h3>Casca pronta — conteúdo na próxima sprint</h3>
          <p>
            A fundação visual, o roteamento por hash e a sidebar já estão ativos. A
            implementação completa desta tela chega nas próximas entregas do roadmap.
          </p>
          <span className="route-tag">#{route}</span>
        </div>
      </div>
    </div>
  );
}
