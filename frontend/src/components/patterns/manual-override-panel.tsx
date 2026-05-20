"use client";

/**
 * Manual-Override-Pattern (Sprint 9.9 T8 + Sprint 12b Refactor).
 *
 * Datei haelt die Sub-Komponenten fuer das Pro-Zone-Override-UI. Container
 * (Liste aller Zonen + Backward-Compat-Room-Card + Historie) ist
 * ``manual-override-panel-list.tsx``.
 *
 * Sprint-12b-Refactor: aus EINEM Room-Panel (Sprint 9.9) werden N
 * Pro-Zone-Cards plus optional eine read-only Room-Scope-Card fuer
 * Bestandsdaten mit ``heating_zone_id === null`` (Lazy-Migration aus
 * 12a T1).
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useCreateRoomOverride, useRevokeOverride } from "@/lib/api/hooks-overrides";
import { mapOverrideError } from "@/lib/api/override-errors";
import type {
  FrontendOverrideSource,
  HeatingZone,
  HeatingZoneKind,
  ManualOverride,
  OverrideSource,
} from "@/lib/api/types";
import { SOURCE_ICON, SOURCE_LABEL, useRemainingTime } from "@/lib/overrides-display";

const FRONTEND_SOURCES: FrontendOverrideSource[] = [
  "frontend_4h",
  "frontend_midnight",
  "frontend_checkout",
];

/**
 * Sprint 12b: Zone-Kind-Labels + Material-Symbols-Icons. Quelle der
 * Wahrheit fuer Labels ist ``heating-zone-list.tsx`` (Sprint 8.10); hier
 * bewusst dupliziert weil nur 5 Eintraege und Cross-Component-Import
 * der Konstanten ungewollte Kopplung schafft.
 */
export const ZONE_KIND_LABEL: Record<HeatingZoneKind, string> = {
  bedroom: "Schlafzimmer",
  bathroom: "Bad",
  living: "Wohnen",
  hallway: "Flur",
  other: "Sonstige",
};

export const ZONE_KIND_ICON: Record<HeatingZoneKind, string> = {
  bedroom: "bed",
  bathroom: "shower",
  living: "weekend",
  hallway: "door_open",
  other: "category",
};

// ---------------------------------------------------------------------------
// Zone-Card (eine Card pro HeatingZone, Sprint 12b)
// ---------------------------------------------------------------------------

interface ZoneCardProps {
  roomId: number;
  zone: HeatingZone;
  /** true wenn `detect_open_window_zones` diese Zone als offen liefert. */
  isWindowOpen: boolean;
  /**
   * ISO-Timestamp der juengsten Engine-Eval; rendert „Stand: vor Xs"
   * unter dem Window-Open-Hinweis (Brief R1: 90s-Latenz transparent).
   */
  lastEvalTime: string | null;
  /** Aktiver Zone-Override (heating_zone_id === zone.id), sonst null. */
  activeOverride: ManualOverride | null;
}

export function ManualOverrideZoneCard({
  roomId,
  zone,
  isWindowOpen,
  lastEvalTime,
  activeOverride,
}: ZoneCardProps) {
  return (
    <div className="bg-surface border border-border rounded-md p-5">
      <ZoneHeader zone={zone} />
      {activeOverride ? (
        <ActiveOverrideDisplay
          roomId={roomId}
          override={activeOverride}
          revokeLabel="Übersteuerung aufheben"
        />
      ) : (
        <CreateOverrideForm
          roomId={roomId}
          heatingZoneId={zone.id}
          isWindowOpen={isWindowOpen}
          lastEvalTime={lastEvalTime}
        />
      )}
    </div>
  );
}

function ZoneHeader({ zone }: { zone: HeatingZone }) {
  return (
    <div className="flex items-center gap-2 mb-4">
      <span
        className="material-symbols-outlined text-text-secondary"
        style={{ fontSize: 22 }}
        aria-hidden
      >
        {ZONE_KIND_ICON[zone.kind]}
      </span>
      <div>
        <h3 className="text-base font-medium text-text-primary">{zone.name}</h3>
        <p className="text-xs text-text-tertiary">{ZONE_KIND_LABEL[zone.kind]}</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Room-Scope-Card (Backward-Compat fuer Altbestand-Overrides, Sprint 12b E4)
// ---------------------------------------------------------------------------

/**
 * Read-only Card fuer einen aktiven Override mit ``heating_zone_id ===
 * null`` (Lazy-Migration aus Sprint 12a T1: Bestandsrows bleiben Room-
 * Scope bis Erneuerung). Wird vom Container nur dann gerendert, wenn so
 * ein Override aktiv ist. Neuanlage geht ausschliesslich pro Zone — kein
 * CreateOverrideForm hier.
 */
export function ManualOverrideRoomCard({
  roomId,
  override,
}: {
  roomId: number;
  override: ManualOverride;
}) {
  return (
    <div className="bg-surface border border-border rounded-md p-5">
      <div className="flex items-center gap-2 mb-4">
        <span
          className="material-symbols-outlined text-text-secondary"
          style={{ fontSize: 22 }}
          aria-hidden
        >
          meeting_room
        </span>
        <div>
          <h3 className="text-base font-medium text-text-primary">Raum (alle Zonen)</h3>
          <p className="text-xs text-text-tertiary">
            Altbestand-Eintrag — neue Übersteuerungen werden pro Zone angelegt.
          </p>
        </div>
      </div>
      <ActiveOverrideDisplay
        roomId={roomId}
        override={override}
        revokeLabel="Übersteuerung aufheben"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Aktiv-Anzeige (gemeinsam fuer Zone + Room Card)
// ---------------------------------------------------------------------------

interface ActiveDisplayProps {
  roomId: number;
  override: ManualOverride;
  revokeLabel: string;
}

function ActiveOverrideDisplay({ roomId, override, revokeLabel }: ActiveDisplayProps) {
  const revokeMut = useRevokeOverride(roomId);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const remaining = useRemainingTime(override.expires_at);
  // Sprint 9.9a Hotfix A2: Engine quantisiert Setpoint auf ganze Grad
  // (rules.engine._quantize). Wir spiegeln das an der Anzeige — der DB-
  // Wert kann bei alten Records noch Decimal sein.
  const displaySetpoint = Math.round(parseFloat(override.setpoint));

  const performRevoke = async () => {
    setError(null);
    try {
      await revokeMut.mutateAsync(override.id);
      setConfirmRevoke(false);
    } catch (e) {
      setError(mapOverrideError(e));
      setConfirmRevoke(false);
    }
  };

  return (
    <div>
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-baseline gap-2">
            <span className="text-4xl font-medium text-text-primary tabular-nums">
              {displaySetpoint}
            </span>
            <span className="text-xl text-text-secondary">°C</span>
          </div>
          <SourceBadge source={override.source} className="mt-2" />
          <p className="text-sm text-text-secondary mt-3">
            Läuft ab in <span className="font-medium">{remaining}</span> ·{" "}
            {new Date(override.expires_at).toLocaleString("de-AT")}
          </p>
          {override.reason ? (
            <p className="text-sm text-text-secondary mt-1">Grund: {override.reason}</p>
          ) : null}
        </div>
        <Button
          variant="destructive"
          icon="cancel"
          onClick={() => setConfirmRevoke(true)}
          disabled={revokeMut.isPending}
        >
          {revokeLabel}
        </Button>
      </div>

      {error ? <p className="text-sm text-error mt-3">{error}</p> : null}

      <ConfirmDialog
        open={confirmRevoke}
        title="Übersteuerung aufheben?"
        message={`Setpoint ${displaySetpoint} °C (${SOURCE_LABEL[override.source]}) wird sofort beendet. Engine fällt auf den regulären Setpoint zurück.`}
        confirmLabel="Aufheben"
        loading={revokeMut.isPending}
        onConfirm={performRevoke}
        onCancel={() => setConfirmRevoke(false)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create-Form (pro Zone, mit Window-Pre-Check)
// ---------------------------------------------------------------------------

interface CreateFormProps {
  roomId: number;
  heatingZoneId: number;
  isWindowOpen: boolean;
  lastEvalTime: string | null;
}

function CreateOverrideForm({
  roomId,
  heatingZoneId,
  isWindowOpen,
  lastEvalTime,
}: CreateFormProps) {
  const createMut = useCreateRoomOverride(roomId);
  const [setpoint, setSetpoint] = useState("21");
  const [source, setSource] = useState<FrontendOverrideSource>("frontend_4h");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (isWindowOpen) {
      // Defensive: Pre-Check verhindert Submit bereits via disabled-Button.
      // Hier nur Fallback wenn Race-Bedingung den State umgeht.
      return;
    }
    try {
      await createMut.mutateAsync({
        setpoint,
        source,
        reason: reason.trim() ? reason.trim() : null,
        heating_zone_id: heatingZoneId,
      });
      setReason("");
    } catch (err) {
      setError(mapOverrideError(err));
    }
  };

  return (
    <form onSubmit={submit} className="space-y-4">
      {isWindowOpen ? (
        <WindowOpenBlocker lastEvalTime={lastEvalTime} />
      ) : (
        <p className="text-sm text-text-secondary">
          Aktuell keine manuelle Übersteuerung. Engine arbeitet nach den regulären Regeln.
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <label className="block">
          <span className="text-sm font-medium text-text-primary mb-1 block">Setpoint (°C)</span>
          <Input
            type="number"
            step="1"
            min="5"
            max="30"
            value={setpoint}
            onChange={(e) => setSetpoint(e.target.value)}
            required
            disabled={isWindowOpen}
          />
        </label>

        <label className="block">
          <span className="text-sm font-medium text-text-primary mb-1 block">Dauer</span>
          <Select
            value={source}
            onValueChange={(v) => setSource(v as FrontendOverrideSource)}
            disabled={isWindowOpen}
          >
            <SelectTrigger>
              <SelectValue placeholder="Bitte wählen" />
            </SelectTrigger>
            <SelectContent>
              {FRONTEND_SOURCES.map((s) => (
                <SelectItem key={s} value={s}>
                  {SOURCE_LABEL[s]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </label>
      </div>

      <label className="block">
        <span className="text-sm font-medium text-text-primary mb-1 block">Grund (optional)</span>
        <Input
          type="text"
          maxLength={500}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="z.B. Wunsch des Gastes"
          disabled={isWindowOpen}
        />
      </label>

      {error ? <p className="text-sm text-error">{error}</p> : null}

      <div>
        <Button
          type="submit"
          variant="primary"
          loading={createMut.isPending}
          disabled={isWindowOpen}
        >
          Anwenden
        </Button>
      </div>
    </form>
  );
}

function WindowOpenBlocker({ lastEvalTime }: { lastEvalTime: string | null }) {
  const sinceText = lastEvalTime ? formatRelativeShort(lastEvalTime) : null;
  return (
    <div className="rounded-md border border-warning/50 bg-warning/10 p-3 flex items-start gap-2">
      <span
        className="material-symbols-outlined text-warning"
        style={{ fontSize: 20 }}
        aria-hidden
      >
        sensor_door
      </span>
      <div className="flex-1">
        <p className="text-sm font-medium text-text-primary">
          Fenster offen — Übersteuerung nicht möglich
        </p>
        {sinceText ? (
          <p className="text-xs text-text-tertiary mt-1">Stand: vor {sinceText}</p>
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Historie (Sprint 9.9 T8, Sprint 12b: Zone-Label pro Zeile)
// ---------------------------------------------------------------------------

const HISTORY_PAGE_SIZE = 20;

export function HistoryCard({
  items,
  zones,
  loading,
}: {
  items: ManualOverride[];
  zones: HeatingZone[];
  loading: boolean;
}) {
  const [limit, setLimit] = useState(HISTORY_PAGE_SIZE);
  const visible = items.slice(0, limit);
  return (
    <div className="bg-surface border border-border rounded-md p-5">
      <h2 className="text-lg font-medium text-text-primary mb-4">Historie</h2>
      <HistoryTable items={visible} zones={zones} loading={loading} />
      {items.length > limit ? (
        <div className="mt-3 text-center">
          <Button variant="ghost" onClick={() => setLimit((n) => n + HISTORY_PAGE_SIZE)}>
            Mehr laden
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function HistoryTable({
  items,
  zones,
  loading,
}: {
  items: ManualOverride[];
  zones: HeatingZone[];
  loading: boolean;
}) {
  if (loading) {
    return <p className="text-sm text-text-secondary">Lade…</p>;
  }
  if (items.length === 0) {
    return (
      <p className="text-sm text-text-secondary italic">
        Noch keine Übersteuerungen für dieses Zimmer.
      </p>
    );
  }
  const zoneById = new Map(zones.map((z) => [z.id, z]));
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-text-tertiary border-b border-border">
            <th className="py-2 pr-4 font-medium">Zeitpunkt</th>
            <th className="py-2 pr-4 font-medium">Bereich</th>
            <th className="py-2 pr-4 font-medium">Setpoint</th>
            <th className="py-2 pr-4 font-medium">Quelle</th>
            <th className="py-2 pr-4 font-medium">Status</th>
            <th className="py-2 pr-4 font-medium">Grund</th>
          </tr>
        </thead>
        <tbody>
          {items.map((o) => {
            const zone = o.heating_zone_id !== null ? zoneById.get(o.heating_zone_id) : null;
            const bereichLabel = zone
              ? zone.name
              : o.heating_zone_id === null
                ? "Raum (alle Zonen)"
                : `Zone ${o.heating_zone_id}`;
            return (
              <tr key={o.id} className="border-b border-border last:border-b-0">
                <td className="py-2 pr-4 text-text-secondary tabular-nums">
                  {new Date(o.created_at).toLocaleString("de-AT")}
                </td>
                <td className="py-2 pr-4 text-text-secondary">{bereichLabel}</td>
                <td className="py-2 pr-4 font-medium text-text-primary tabular-nums">
                  {Math.round(parseFloat(o.setpoint))} °C
                </td>
                <td className="py-2 pr-4">
                  <SourceBadge source={o.source} />
                </td>
                <td className="py-2 pr-4">
                  <StatusBadge override={o} />
                </td>
                <td className="py-2 pr-4 text-text-secondary">{o.reason ?? "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Subkomponenten
// ---------------------------------------------------------------------------

function SourceBadge({ source, className }: { source: OverrideSource; className?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded bg-surface-alt text-xs text-text-primary ${className ?? ""}`}
    >
      <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
        {SOURCE_ICON[source]}
      </span>
      {SOURCE_LABEL[source]}
    </span>
  );
}

function StatusBadge({ override }: { override: ManualOverride }) {
  if (override.revoked_at !== null) {
    return <span className="text-xs text-text-tertiary">manuell aufgehoben</span>;
  }
  if (new Date(override.expires_at) <= new Date()) {
    return <span className="text-xs text-text-tertiary">abgelaufen</span>;
  }
  return <span className="text-xs text-primary font-medium">aktiv</span>;
}

// ---------------------------------------------------------------------------
// Helpers (Sprint 12b T3: Error-Mapping in mapOverrideError — siehe Doku
// am Symbol selbst; siehe `lib/api/override-errors.ts` fuer typisierten
// Helper).
// ---------------------------------------------------------------------------

/**
 * Sprint 12b: Helper zum kurzen Relativ-Zeit-Format (Sekunden/Minuten).
 * Bewusst nicht ueber Intl.RelativeTimeFormat — wir wollen kompakte
 * deutsche Strings „45s", „2m", „1m 30s".
 */
function formatRelativeShort(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const totalSec = Math.max(0, Math.floor(diffMs / 1000));
  if (totalSec < 60) return `${totalSec}s`;
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  if (mins < 5) return `${mins}m ${secs}s`;
  return `${mins}m`;
}
