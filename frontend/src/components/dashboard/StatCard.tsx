/**
 * stat-card — cartão de indicador (estados normal/alert).
 * Composição plana fiel ao artifact (.stat / .stat.alert).
 */
import { Icon, type IconKey } from "@/lib/icons";

export interface StatCardData {
  icon: IconKey;
  label: string;
  value: number | string;
  delta?: string;
  /** alert realça o cartão (borda + valor em tom de aviso). */
  alert?: boolean;
}

export function StatCard({ icon, label, value, delta, alert }: StatCardData) {
  return (
    <div className={`stat${alert ? " alert" : ""}`}>
      <div className="lbl">
        <Icon name={icon} />
        {label}
      </div>
      <div className="val num">{value}</div>
      {delta ? <div className="delta">{delta}</div> : null}
    </div>
  );
}
