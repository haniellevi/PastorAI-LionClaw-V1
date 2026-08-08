"use client";

/**
 * Casca de tela: roteia para a implementação real quando existe (ex.: dashboard)
 * e, para as demais rotas, mantém a casca + cabeçalho — provando que a navegação
 * por hash troca de tela sem reload.
 */
import dynamic from "next/dynamic";

import { ModuleTabs } from "./ModuleTabs";
import { Icon } from "@/lib/icons";
import { SCREEN_META } from "@/lib/navigation";

function ScreenLoading() {
  return (
    <div className="full-loader" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span className="sr-only">Carregando tela…</span>
    </div>
  );
}

const CalendarioScreen = dynamic(
  () => import("@/components/calendario/CalendarioScreen").then((module) => module.CalendarioScreen),
  { loading: ScreenLoading },
);
const CelulasScreen = dynamic(
  () => import("@/components/cells/CelulasScreen").then((module) => module.CelulasScreen),
  { loading: ScreenLoading },
);
const AgenteScreen = dynamic(
  () => import("@/components/config/AgenteScreen").then((module) => module.AgenteScreen),
  { loading: ScreenLoading },
);
const AssinaturaScreen = dynamic(
  () => import("@/components/config/AssinaturaScreen").then((module) => module.AssinaturaScreen),
  { loading: ScreenLoading },
);
const EquipeScreen = dynamic(
  () => import("@/components/config/EquipeScreen").then((module) => module.EquipeScreen),
  { loading: ScreenLoading },
);
const IdentidadeVisualScreen = dynamic(
  () =>
    import("@/components/config/IdentidadeVisualScreen").then(
      (module) => module.IdentidadeVisualScreen,
    ),
  { loading: ScreenLoading },
);
const IntegracoesScreen = dynamic(
  () => import("@/components/config/IntegracoesScreen").then((module) => module.IntegracoesScreen),
  { loading: ScreenLoading },
);
const PermissoesScreen = dynamic(
  () => import("@/components/config/PermissoesScreen").then((module) => module.PermissoesScreen),
  { loading: ScreenLoading },
);
const SetupChecklistScreen = dynamic(
  () =>
    import("@/components/config/SetupChecklistScreen").then(
      (module) => module.SetupChecklistScreen,
    ),
  { loading: ScreenLoading },
);
const CentralCelulaScreen = dynamic(
  () =>
    import("@/components/central-celula/CentralCelulaScreen").then(
      (module) => module.CentralCelulaScreen,
    ),
  { loading: ScreenLoading },
);
const MinhaCelulaEntry = dynamic(
  () =>
    import("@/components/minha-celula/MinhaCelulaEntry").then(
      (module) => module.MinhaCelulaEntry,
    ),
  { loading: ScreenLoading },
);
const ComunicadosScreen = dynamic(
  () =>
    import("@/components/comunicados/ComunicadosScreen").then(
      (module) => module.ComunicadosScreen,
    ),
  { loading: ScreenLoading },
);
const ConsolIndividualScreen = dynamic(
  () =>
    import("@/components/consolidacao/ConsolIndividualScreen").then(
      (module) => module.ConsolIndividualScreen,
    ),
  { loading: ScreenLoading },
);
const ConsolidarScreen = dynamic(
  () =>
    import("@/components/consolidacao/ConsolidarScreen").then(
      (module) => module.ConsolidarScreen,
    ),
  { loading: ScreenLoading },
);
const LockedScreen = dynamic(
  () => import("@/components/consolidacao/LockedScreen").then((module) => module.LockedScreen),
  { loading: ScreenLoading },
);
const ContatosScreen = dynamic(
  () => import("@/components/contacts/ContatosScreen").then((module) => module.ContatosScreen),
  { loading: ScreenLoading },
);
const GanharScreen = dynamic(
  () => import("@/components/contacts/GanharScreen").then((module) => module.GanharScreen),
  { loading: ScreenLoading },
);
const DashboardScreen = dynamic(
  () =>
    import("@/components/dashboard/DashboardScreen").then((module) => module.DashboardScreen),
  { loading: ScreenLoading },
);
const EnviarScreen = dynamic(
  () => import("@/components/enviar/EnviarScreen").then((module) => module.EnviarScreen),
  { loading: ScreenLoading },
);
const G12Screen = dynamic(
  () => import("@/components/g12/G12Screen").then((module) => module.G12Screen),
  { loading: ScreenLoading },
);
const InboxScreen = dynamic(
  () => import("@/components/inbox/InboxScreen").then((module) => module.InboxScreen),
  { loading: ScreenLoading },
);
const RelatoriosScreen = dynamic(
  () => import("@/components/reports/RelatoriosScreen").then((module) => module.RelatoriosScreen),
  { loading: ScreenLoading },
);
const WhatsappScreen = dynamic(
  () => import("@/components/whatsapp/WhatsappScreen").then((module) => module.WhatsappScreen),
  { loading: ScreenLoading },
);
const PerfilScreen = dynamic(
  () => import("@/components/profile/PerfilScreen").then((module) => module.PerfilScreen),
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
