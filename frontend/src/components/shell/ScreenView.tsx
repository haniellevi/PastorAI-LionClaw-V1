"use client";

/**
 * Casca de tela: roteia para a implementação real quando existe (ex.: dashboard)
 * e, para as demais rotas, mantém a casca + cabeçalho — provando que a navegação
 * por hash troca de tela sem reload.
 */
import { CalendarioScreen } from "@/components/calendario/CalendarioScreen";
import { CelulasScreen } from "@/components/cells/CelulasScreen";
import { AgenteScreen } from "@/components/config/AgenteScreen";
import { AssinaturaScreen } from "@/components/config/AssinaturaScreen";
import { EquipeScreen } from "@/components/config/EquipeScreen";
import { PermissoesScreen } from "@/components/config/PermissoesScreen";
import { CentralCelulaScreen } from "@/components/central-celula/CentralCelulaScreen";
import { ComunicadosScreen } from "@/components/comunicados/ComunicadosScreen";
import { ConsolIndividualScreen } from "@/components/consolidacao/ConsolIndividualScreen";
import { ConsolidarScreen } from "@/components/consolidacao/ConsolidarScreen";
import { LockedScreen } from "@/components/consolidacao/LockedScreen";
import { ContatosScreen } from "@/components/contacts/ContatosScreen";
import { GanharScreen } from "@/components/contacts/GanharScreen";
import { DashboardScreen } from "@/components/dashboard/DashboardScreen";
import { EnviarScreen } from "@/components/enviar/EnviarScreen";
import { G12Screen } from "@/components/g12/G12Screen";
import { InboxScreen } from "@/components/inbox/InboxScreen";
import { RelatoriosScreen } from "@/components/reports/RelatoriosScreen";
import { WhatsappScreen } from "@/components/whatsapp/WhatsappScreen";
import { Icon } from "@/lib/icons";
import { SCREEN_META } from "@/lib/navigation";

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
    return <G12Screen />;
  }
  if (route === "enviar") {
    return <EnviarScreen />;
  }
  if (route === "consolidar") {
    return <ConsolidarScreen />;
  }
  if (route === "consol-individual") {
    return <ConsolIndividualScreen />;
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
    return <CentralCelulaScreen />;
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
  if (route === "universidade-vida") {
    return <LockedScreen variant="universidade-vida" />;
  }
  if (route === "capacitacao") {
    return <LockedScreen variant="capacitacao" />;
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
