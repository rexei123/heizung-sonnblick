"use client";

/**
 * Engine-Decision-Panel (Sprint 9.10).
 *
 * Zeigt die letzte Engine-Evaluation pro Schicht (Layer-Trace) und den
 * letzten Downlink im Zimmer-Detail. Killer-Feature aus dem Master-Plan:
 * der Hotelier sieht *warum* der Setpoint genau diesen Wert hat.
 *
 * Datenquelle: GET /api/v1/rooms/{id}/engine-trace (Sprint 9.5).
 * Refetch: alle 30 s (siehe useEngineTrace-Hook).
 */

import { useMemo } from "react";

import { useEngineTrace } from "@/lib/api/hooks-rooms";
import type {
  CommandReason,
  EventLogEntry,
  EventLogLayer,
  OverrideSource,
} from "@/lib/api/types";
import { SOURCE_ICON, SOURCE_LABEL, useRemainingTime } from "@/lib/overrides-display";

const LAYER_ORDER: EventLogLayer[] = [
  "summer_mode_fast_path",
  "base_target",
  "temporal_override",
  "manual_override",
  "guest_override",
  "window_safety",
  "hard_clamp",
];

const LAYER_LABEL: Record<EventLogLayer, string> = {
  summer_mode_fast_path: "Sommermodus",
  base_target: "Basis (Belegung)",
  temporal_override: "Zeitsteuerung",
  manual_override: "Manueller Override",
  guest_override: "Gast-Drehring",
  window_safety: "Fenster-Sicherheit",
  hard_clamp: "Sicherheits-Limit",
};

const REASON_LABEL: Record<CommandReason, string> = {
  occupied_setpoint: "Belegt-Sollwert",
  vacant_setpoint: "Frei-Sollwert",
  night_setback: "Nachtabsenkung",
  day_setback: "Tagabsenkung",
  preheat_checkin: "Vorheizen vor Check-in",
  checkout_setback: "Absenken nach Check-out",
  window_open: "Fenster offen",
  guest_override: "Gast-Override",
  long_vacant: "Langzeit unbelegt",
  frost_protection: "Frostschutz",
  summer_mode: "Sommermodus",
  manual: "Manuell",
  manual_event: "Manueller Event",
};

interface Props {
  roomId: number;
}

export function EngineDecisionPanel({ roomId }: Props) {
  const traceQuery = useEngineTrace(roomId);

  // Alle Eintraege der NEUESTEN Evaluation gruppieren (engineTrace ist
  // ORDER BY time DESC -> der erste Eintrag haengt zur juengsten Eval).
  const grouped = useMemo(() => groupByEvaluation(traceQuery.data ?? []), [traceQuery.data]);
  const latest = grouped[0];

  if (traceQuery.isLoading) {
    return <p className="text-base text-text-secondary">Lade Engine-Trace…</p>;
  }
  if (traceQuery.isError) {
    return <p className="text-base text-error">Fehler beim Laden des Engine-Trace.</p>;
  }
  if (!latest) {
    return (
      <div className="text-center py-12">
        <span
          className="material-symbols-outlined text-text-tertiary"
          style={{ fontSize: 48 }}
          aria-hidden
        >
          psychology
        </span>
        <p className="mt-2 text-base text-text-secondary">
          Noch keine Engine-Evaluation für dieses Zimmer.
        </p>
        <p className="mt-1 text-sm text-text-tertiary">
          Sobald eine Belegung angelegt wird, evaluiert die Engine automatisch.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <SummaryCard latest={latest} />
      <LayerTrace entries={latest.entries} />
      <HistoryList groups={grouped.slice(1, 6)} />
    </div>
  );
}

interface EvalGroup {
  evaluationId: string;
  time: string;
  entries: EventLogEntry[];
  finalSetpoint: number | null;
}

function groupByEvaluation(entries: EventLogEntry[]): EvalGroup[] {
  const map = new Map<string, EvalGroup>();
  for (const e of entries) {
    let g = map.get(e.evaluation_id);
    if (!g) {
      g = { evaluationId: e.evaluation_id, time: e.time, entries: [], finalSetpoint: null };
      map.set(e.evaluation_id, g);
    }
    g.entries.push(e);
    // Finale Schicht = hard_clamp (oder die juengste in LAYER_ORDER, die existiert)
    if (e.layer === "hard_clamp" && e.setpoint_out !== null) {
      g.finalSetpoint = parseFloat(e.setpoint_out);
    }
  }
  // Innerhalb jeder Gruppe nach Layer-Order sortieren
  for (const g of map.values()) {
    g.entries.sort(
      (a, b) => LAYER_ORDER.indexOf(a.layer) - LAYER_ORDER.indexOf(b.layer),
    );
  }
  // Zeitlich neueste Gruppe zuerst
  return [...map.values()].sort((a, b) => b.time.localeCompare(a.time));
}

function SummaryCard({ latest }: { latest: EvalGroup }) {
  const setpoint = latest.finalSetpoint;
  const baseEntry = latest.entries.find((e) => e.layer === "base_target");
  // Stale-Hinweis: wenn die juengste Evaluation > 1 h zurueck — Engine
  // sollte alle 60 s laufen (Sprint 9.7 Scheduler), oder wir haben einen Bug.
  const ageMs = Date.now() - new Date(latest.time).getTime();
  const isStale = ageMs > 60 * 60 * 1000;
  return (
    <div className="bg-surface border border-border rounded-md p-5">
      <div className="flex items-baseline gap-3">
        <span className="text-3xl font-medium text-primary">
          {setpoint !== null ? `${setpoint}°C` : "—"}
        </span>
        <span className="text-base text-text-secondary">aktueller Sollwert</span>
      </div>
      {baseEntry?.reason ? (
        <p className="mt-2 text-base text-text-secondary">
          Grund: <strong className="text-text-primary">{REASON_LABEL[baseEntry.reason]}</strong>
        </p>
      ) : null}
      <p
        className={`mt-1 text-sm ${
          isStale ? "text-warning font-medium" : "text-text-tertiary"
        }`}
      >
        Letzte Evaluation: {formatRelative(latest.time)}
        {isStale ? " · veraltet — Engine evaluiert alle 60 s sobald Scheduler aktiv ist" : ""}
      </p>
    </div>
  );
}

function LayerTrace({ entries }: { entries: EventLogEntry[] }) {
  return (
    <div className="bg-surface border border-border rounded-md overflow-hidden">
      <header className="px-4 py-3 border-b border-border bg-surface-alt">
        <h3 className="text-base font-medium text-text-primary">Schicht-Trace</h3>
        <p className="text-sm text-text-secondary">
          So hat die Engine den Setpoint berechnet — Schritt für Schritt.
        </p>
      </header>
      <table className="w-full text-base">
        <thead className="bg-surface-alt text-text-secondary text-sm">
          <tr>
            <th className="text-left px-4 py-2 font-medium">Schicht</th>
            <th className="text-left px-4 py-2 font-medium">Setpoint</th>
            <th className="text-left px-4 py-2 font-medium">Grund</th>
            <th className="text-left px-4 py-2 font-medium">Detail</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr
              key={`${e.evaluation_id}-${e.layer}`}
              className="border-t border-border"
            >
              <td className="px-4 py-2 font-medium text-text-primary">
                {LAYER_LABEL[e.layer]}
              </td>
              <td className="px-4 py-2">
                {e.setpoint_out !== null ? (
                  <span className="font-medium">{parseFloat(e.setpoint_out)}°C</span>
                ) : (
                  <span className="text-text-tertiary">—</span>
                )}
              </td>
              <td className="px-4 py-2 text-text-secondary">
                {e.reason ? REASON_LABEL[e.reason] : "—"}
              </td>
              <td className="px-4 py-2 text-sm text-text-tertiary">
                {e.layer === "manual_override" ? (
                  <ManualOverrideDetail entry={e} />
                ) : (
                  ((e.details && typeof e.details.detail === "string"
                    ? e.details.detail
                    : null) ?? "—")
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ManualOverrideDetail({ entry }: { entry: EventLogEntry }) {
  const details = entry.details ?? {};
  const sourceRaw = details["source"];
  const expiresAtRaw = details["expires_at"];
  const source: OverrideSource | null =
    typeof sourceRaw === "string" && sourceRaw in SOURCE_LABEL
      ? (sourceRaw as OverrideSource)
      : null;
  const expiresAt = typeof expiresAtRaw === "string" ? expiresAtRaw : null;

  if (source === null) {
    return <span className="italic text-text-tertiary">kein aktiver Override</span>;
  }
  return <ActiveOverrideDetail source={source} expiresAt={expiresAt} />;
}

function ActiveOverrideDetail({
  source,
  expiresAt,
}: {
  source: OverrideSource;
  expiresAt: string | null;
}) {
  const remaining = useRemainingTime(expiresAt ?? new Date(0).toISOString());
  return (
    <div className="flex flex-col gap-1">
      <span className="inline-flex items-center gap-1 text-text-primary">
        <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
          {SOURCE_ICON[source]}
        </span>
        {SOURCE_LABEL[source]}
      </span>
      {expiresAt ? (
        <span className="text-xs text-text-tertiary">
          läuft ab in {remaining} ·{" "}
          {new Date(expiresAt).toLocaleString("de-AT")}
        </span>
      ) : null}
    </div>
  );
}

function HistoryList({ groups }: { groups: EvalGroup[] }) {
  if (groups.length === 0) return null;
  return (
    <div className="bg-surface border border-border rounded-md overflow-hidden">
      <header className="px-4 py-3 border-b border-border bg-surface-alt">
        <h3 className="text-base font-medium text-text-primary">Vorherige Evaluationen</h3>
      </header>
      <ul className="divide-y divide-border">
        {groups.map((g) => {
          const sp = g.finalSetpoint;
          const base = g.entries.find((e) => e.layer === "base_target");
          return (
            <li key={g.evaluationId} className="px-4 py-2 flex justify-between items-center">
              <span className="text-base">
                {sp !== null ? <strong>{sp}°C</strong> : <span>—</span>}
                {base?.reason ? (
                  <span className="text-text-secondary"> · {REASON_LABEL[base.reason]}</span>
                ) : null}
              </span>
              <span className="text-sm text-text-tertiary">{formatRelative(g.time)}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diffSec = Math.round((now - then) / 1000);
  if (diffSec < 60) return `vor ${diffSec} s`;
  if (diffSec < 3600) return `vor ${Math.round(diffSec / 60)} Min`;
  if (diffSec < 86400) return `vor ${Math.round(diffSec / 3600)} h`;
  return new Date(iso).toLocaleString("de-AT");
}
