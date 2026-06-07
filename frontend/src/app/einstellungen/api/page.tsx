"use client";

/**
 * API & Webhooks — Belegungs-Import-Detailseite (Sprint 15f, AE-66).
 *
 * Liest NUR ``GET /api/v1/integrations/occupancy-import/log``. ``status`` ist
 * backend-berechnet; hier nur Anzeige (Ampel + letzte 30 Importe). Zeiten
 * UTC -> Europe/Vienna nur bei der Anzeige (§5.65); ``list_date`` ist ein
 * Kalendertag und läuft NICHT durch die UTC-Pipeline.
 */

import { Badge } from "@/components/ui/badge";
import { useOccupancyImportLog } from "@/lib/api/hooks-occupancy-import";
import type { OccupancyImportStatus } from "@/lib/api/types";
import { formatCalendarDate, formatDateTime, formatRelative } from "@/lib/format";

const STATUS_META: Record<OccupancyImportStatus, { label: string; cls: string }> = {
  green: { label: "Aktuell", cls: "bg-success-soft text-success" },
  yellow: { label: "Heute noch kein Import", cls: "bg-warning-soft text-warning" },
  red: { label: "Veraltet", cls: "bg-danger-soft text-danger" },
};

export default function ApiWebhooksPage() {
  const q = useOccupancyImportLog();

  return (
    <div className="p-6 max-w-content mx-auto space-y-6">
      <header>
        <h1 className="text-2xl font-medium text-text-primary">API &amp; Webhooks</h1>
        <p className="text-sm text-text-secondary mt-1">
          Täglicher Belegungs-Import aus dem PMS (Casablanca). Status der letzten Importe.
        </p>
      </header>

      {q.isLoading ? (
        <div className="h-24 rounded-lg bg-surface-alt animate-pulse" />
      ) : q.isError || !q.data ? (
        <section className="bg-surface rounded-lg border border-border p-6">
          <p className="text-sm text-warning">
            Import-Status nicht verfügbar. Bitte später erneut versuchen.
          </p>
        </section>
      ) : (
        <>
          {/* Status-Kopf: Ampel + zuletzt eingegangen + Erwartung. */}
          <section className="bg-surface rounded-lg border border-border p-6">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
              <Badge
                className={`border-transparent ${STATUS_META[q.data.status].cls}`}
                data-testid="import-status-badge"
              >
                {STATUS_META[q.data.status].label}
              </Badge>
              <span className="text-sm text-text-secondary">
                Zuletzt eingegangen:{" "}
                <span className="text-text-primary">
                  {q.data.last_success_at
                    ? `${formatRelative(q.data.last_success_at)} (${formatDateTime(q.data.last_success_at)})`
                    : "noch nie"}
                </span>
              </span>
              <span className="text-sm text-text-secondary">
                Erwartet bis{" "}
                <span className="text-text-primary">{q.data.expected_by_local} Uhr</span>
              </span>
            </div>
          </section>

          {/* Liste der letzten Importe (neueste zuerst, Backend liefert max. 30). */}
          <section className="bg-surface rounded-lg border border-border overflow-hidden">
            <header className="px-6 py-4 border-b border-border">
              <h2 className="text-lg font-medium text-text-primary">Letzte Importe</h2>
            </header>
            {q.data.imports.length === 0 ? (
              <div className="p-6 text-center text-sm text-text-tertiary">
                Noch keine Importe vorhanden.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-surface-alt text-text-secondary">
                    <tr>
                      <th className="text-left px-6 py-2 font-medium">Eingegangen</th>
                      <th className="text-left px-6 py-2 font-medium">Listendatum</th>
                      <th className="text-left px-6 py-2 font-medium">Belegt</th>
                      <th className="text-left px-6 py-2 font-medium">Geschlossen</th>
                      <th className="text-left px-6 py-2 font-medium">Konflikte</th>
                      <th className="text-left px-6 py-2 font-medium">Ergebnis</th>
                    </tr>
                  </thead>
                  <tbody>
                    {q.data.imports.map((row, idx) => {
                      const flagged = row.result === "rejected" || row.conflicts > 0;
                      return (
                        <tr
                          key={`${row.external_id}-${row.list_date}-${idx}`}
                          data-testid="import-row"
                          className={
                            flagged
                              ? "border-t border-border bg-warning-soft"
                              : "border-t border-border"
                          }
                        >
                          <td className="px-6 py-2 text-text-secondary">
                            {formatDateTime(row.received_at)}
                          </td>
                          <td className="px-6 py-2 text-text-secondary">
                            {formatCalendarDate(row.list_date)}
                          </td>
                          <td className="px-6 py-2">{row.rooms_occupied}</td>
                          <td className="px-6 py-2 text-text-secondary">{row.rooms_closed}</td>
                          <td
                            className={`px-6 py-2 ${row.conflicts > 0 ? "text-warning" : "text-text-secondary"}`}
                          >
                            {row.conflicts}
                          </td>
                          <td className="px-6 py-2">
                            {row.result === "applied" ? (
                              <Badge className="border-transparent bg-success-soft text-success">
                                Übernommen
                              </Badge>
                            ) : (
                              <Badge className="border-transparent bg-danger-soft text-danger">
                                Abgewiesen
                              </Badge>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
