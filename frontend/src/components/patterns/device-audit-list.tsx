"use client";

/**
 * Geräte-Historie (Sprint 24c).
 *
 * **Wozu.** Die Handgriffe an einem Gerät — Rolle umschalten, Relais in
 * Betrieb nehmen, Schutz-Sperre aufheben — sind Admin-Entscheidungen
 * über ein Gerät, das Netzspannung schaltet oder eine Zone heizt. Sie
 * werden seit Sprint 24b auditiert, aber das Audit lag nur in der
 * Datenbank. Wer wissen wollte, wer eine Rolle gesetzt hat, brauchte
 * einen SQL-Zugang.
 *
 * **Lesen darf jeder angemeldete Nutzer**, nicht nur ein Admin. Die
 * Historie ist der Gegenpol zu den Admin-Handgriffen: wer sie nicht
 * ausführen darf, soll trotzdem sehen können, dass und von wem sie
 * ausgeführt wurden. Eine Rollensperre auf dem Lesen nähme die
 * Nachvollziehbarkeit genau dort weg, wo sie gebraucht wird.
 *
 * **Die Aktionen bekommen deutsche Texte, der Rohwert bleibt der
 * Rückfall.** Ein unbekannter Wert — etwa eine Aktion aus einem späteren
 * Sprint — erscheint als er selbst und nicht als „unbekannt". Dieselbe
 * Regel wie bei `revoked_reason` in der Übersteuerungs-Historie: eine
 * falsche Beschriftung ist schlechter als eine rohe.
 */

import { useQuery } from "@tanstack/react-query";

import { fetchDeviceAudit, type DeviceAuditEintrag } from "@/lib/api/devices-audit";
import { formatDateTime } from "@/lib/format";

/** Deutsche Texte für die Aktionen, die ein Gerät betreffen können. */
const AKTION_TEXT: Record<string, string> = {
  DEVICE_MEASURE_ONLY_TOGGLED: "Rolle „nur messen“ geändert",
  RELAY_PROVISIONED: "Relais provisioniert",
  RELAY_COMMISSIONED: "Relais in Betrieb genommen",
  RELAY_DECOMMISSIONED: "Inbetriebnahme zurückgenommen",
  RELAY_PROTECTION_RELEASED: "Schutz-Sperre aufgehoben",
  DEVICE_REPLACED: "Gerät getauscht",
  DEVICE_RETIRED: "Gerät stillgelegt",
};

function aktionText(action: string): string {
  return AKTION_TEXT[action] ?? action;
}

/** Das Wesentliche aus den JSONB-Werten, in einem Satz. */
function detail(eintrag: DeviceAuditEintrag): string | null {
  if (eintrag.action !== "DEVICE_MEASURE_ONLY_TOGGLED") {
    return null;
  }
  const neu = eintrag.neu as { measure_only?: boolean } | null;
  if (neu === null || typeof neu.measure_only !== "boolean") {
    return null;
  }
  return neu.measure_only ? "auf „nur messen“ gesetzt" : "zurückgenommen";
}

export function DeviceAuditList({ deviceId }: { deviceId: number }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["device-audit", deviceId],
    queryFn: () => fetchDeviceAudit(deviceId),
  });

  return (
    <section
      className="bg-surface rounded-lg border border-border p-6"
      data-testid="device-audit"
    >
      <header className="mb-4">
        <h2 className="text-lg font-medium text-text-primary">Historie</h2>
        <p className="text-text-tertiary text-xs">
          Handgriffe an diesem Gerät, neueste zuerst.
        </p>
      </header>

      {isLoading && <p className="text-text-tertiary text-sm">wird geladen …</p>}

      {isError && (
        <p className="text-error text-sm">Die Historie ist nicht abrufbar.</p>
      )}

      {data !== undefined && data.length === 0 && (
        <p className="text-text-tertiary text-sm" data-testid="device-audit-leer">
          Noch kein Handgriff an diesem Gerät.
        </p>
      )}

      {data !== undefined && data.length > 0 && (
        <ul className="divide-y divide-border">
          {data.map((eintrag, index) => {
            const zusatz = detail(eintrag);
            return (
              <li
                key={`${eintrag.ts}-${index}`}
                className="flex items-baseline justify-between gap-4 py-2"
                data-testid="device-audit-zeile"
              >
                <div className="min-w-0">
                  <div className="text-text-primary text-sm">
                    {aktionText(eintrag.action)}
                    {zusatz !== null && (
                      <span className="text-text-secondary"> — {zusatz}</span>
                    )}
                  </div>
                  <div className="text-text-tertiary text-xs">
                    {/* ``null`` heisst Systempfad und nicht "fehlt". */}
                    {eintrag.benutzer ?? "System"}
                  </div>
                </div>
                <span className="text-text-tertiary shrink-0 text-xs">
                  {formatDateTime(eintrag.ts)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
