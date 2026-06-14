/**
 * access-denied — bloqueio de papel das telas de consolidação.
 * #consolidar e #consol-individual abrem apenas para CONSOLIDATION_ROLES
 * (admin · pastor · lider_consol). Os demais papéis veem este aviso, sem
 * qualquer chamada operacional à API.
 */
import { Icon } from "@/lib/icons";

export function AccessDenied({ title, route }: { title: string; route: string }) {
  return (
    <div className="screen" key={route}>
      <div className="screen-head">
        <div className="titles">
          <h2>{title}</h2>
          <p>Área restrita ao ministério de consolidação.</p>
        </div>
      </div>
      <div className="card">
        <div className="access-denied">
          <Icon name="lock" className="access-ic" />
          <h3>Acesso restrito</h3>
          <p>
            Esta área é exclusiva da liderança de consolidação (Administrador,
            Pastor ou Líder de Consolidação). Fale com a liderança da sua igreja se
            precisar de acesso.
          </p>
        </div>
      </div>
    </div>
  );
}
