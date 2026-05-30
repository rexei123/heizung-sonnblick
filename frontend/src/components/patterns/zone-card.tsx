"use client";

/**
 * ZoneCard (Sprint 14b, T3).
 *
 * Eine Karte pro Heizzone im „Heizzonen"-Tab: Header (Name + ZoneHealthBadge
 * + Kind), Body (ThermostatBubbles), Footer (read-only Override-Banner bzw.
 * CTA zum Übersteuerung-Tab + Zone löschen).
 *
 * AE-61 / Drift-Resolution 2026-05-27 (Link-out): KEINE Override-Mutation
 * hier — Setzen/Aufheben läuft im Übersteuerung-Tab (ManualOverrideZoneCard).
 * Der aktive Override wird read-only aus ``zone.active_override``
 * (HeatingZoneRead, Sprint 14d FU-5) gelesen.
 *
 * Sprint 14e Header-Erweiterung:
 *  - FU-1 Ist-Temp: ``zone.mean_temperature_c`` (Aggregat ueber healthy +
 *    aktive Vickis, AE-51 §4.1), null → „—" (R2).
 *  - FU-2 Effektiver Setpoint (R1): bei aktivem Override dessen Wert + Source-
 *    Label-Badge, sonst ``zone.engine_setpoint_c`` (HARD_CLAMP-Spiegel, AE-55).
 *    null → „—". Eine Zahl, keine konkurrierenden Werte.
 *
 * Wording §5.20: „Thermostat"; „Vicki" höchstens im Tooltip.
 */

import { useState, type KeyboardEvent } from "react";

import { ThermostatBubble } from "@/components/patterns/thermostat-bubble";
import { ZoneHealthBadge } from "@/components/patterns/zone-health-badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/contexts/auth-context";
import { useDeleteHeatingZone, useUpdateHeatingZone } from "@/lib/api/hooks-rooms";
import { SOURCE_LABEL } from "@/lib/overrides-display";
import type { ApiError, Device, HeatingZone, HeatingZoneKind } from "@/lib/api/types";

const KIND_LABEL: Record<HeatingZoneKind, string> = {
  bedroom: "Schlafzimmer",
  bathroom: "Bad",
  living: "Wohnen",
  hallway: "Flur",
  other: "Sonstige",
};

interface Props {
  zone: HeatingZone;
  /** Room-weite Device-Liste; ZoneCard filtert intern auf die Zone. */
  devices: Device[];
  roomId: number;
  onDeleted?: () => void;
  onSwitchToOverrideTab?: () => void;
}

export function ZoneCard({ zone, devices, roomId, onDeleted, onSwitchToOverrideTab }: Props) {
  const deleteMut = useDeleteHeatingZone(roomId);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const zoneDevices = devices.filter((d) => d.heating_zone_id === zone.id);
  // Sprint 14d FU-5: aktiver Zone-Override direkt aus HeatingZoneRead
  // (zone.active_override) — der useZoneOverride-Roundtrip entfällt. Zone-Match
  // + Room-Scope-Fallback + revoked/expired-Filter passieren backendseitig
  // (override_service.get_active).
  const activeOverride = zone.active_override;

  const performDelete = async () => {
    setError(null);
    try {
      await deleteMut.mutateAsync(zone.id);
      setConfirmDelete(false);
      onDeleted?.();
    } catch (e) {
      setError(toMessage(e));
      setConfirmDelete(false);
    }
  };

  return (
    <div
      data-testid={`zone-card-${zone.id}`}
      className="bg-surface border border-border rounded-md p-5 space-y-4"
    >
      <div>
        <div className="flex items-center gap-2">
          {isAdmin ? (
            <ZoneNameInlineEdit zone={zone} roomId={roomId} />
          ) : (
            <h3
              className="text-base font-medium text-text-primary"
              data-testid={`zone-card-${zone.id}-name-readonly`}
            >
              {zone.name}
            </h3>
          )}
          <ZoneHealthBadge healthState={zone.health_state} variant="compact" />
        </div>
        <p className="text-xs text-text-tertiary mt-0.5">
          {KIND_LABEL[zone.kind]}
          {zone.is_towel_warmer ? " · Handtuchtrockner" : ""}
        </p>
        <ZoneHeaderMetrics zone={zone} />
      </div>

      {zoneDevices.length === 0 ? (
        <p className="text-sm text-text-tertiary italic">
          Keine Thermostate dieser Zone zugeordnet.
        </p>
      ) : (
        <div className="space-y-2">
          {zoneDevices.map((d) => (
            <ThermostatBubble key={d.id} device={d} />
          ))}
        </div>
      )}

      <div className="border-t border-border pt-3 flex items-end justify-between gap-4">
        <div className="min-w-0">
          {activeOverride ? (
            <div data-testid={`zone-card-${zone.id}-override-banner`}>
              <div className="flex items-baseline gap-1">
                <span className="text-2xl font-medium text-text-primary tabular-nums">
                  {Math.round(activeOverride.setpoint_celsius)}
                </span>
                <span className="text-sm text-text-secondary">°C</span>
                <span className="ml-2 text-xs text-text-tertiary">
                  Übersteuerung · {SOURCE_LABEL[activeOverride.source]}
                </span>
              </div>
              <p className="text-xs text-text-tertiary mt-1">
                läuft bis {new Date(activeOverride.expires_at).toLocaleString("de-AT")}
              </p>
              {onSwitchToOverrideTab ? (
                <Button
                  variant="secondary"
                  onClick={onSwitchToOverrideTab}
                  className="mt-2"
                  data-testid={`zone-card-${zone.id}-set-override-cta`}
                >
                  In Übersteuerung ändern →
                </Button>
              ) : (
                <p className="text-xs text-text-tertiary mt-2">
                  Änderung über den Übersteuerung-Tab.
                </p>
              )}
            </div>
          ) : onSwitchToOverrideTab ? (
            <Button
              variant="secondary"
              onClick={onSwitchToOverrideTab}
              data-testid={`zone-card-${zone.id}-set-override-cta`}
            >
              Wunschtemperatur setzen →
            </Button>
          ) : (
            <p className="text-xs text-text-tertiary">
              Wunschtemperatur über den Übersteuerung-Tab setzen.
            </p>
          )}
        </div>
        <Button
          variant="destructive"
          icon="delete"
          onClick={() => setConfirmDelete(true)}
          disabled={deleteMut.isPending}
          data-testid={`zone-card-${zone.id}-delete-button`}
        >
          Zone löschen
        </Button>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-error">
          {error}
        </p>
      ) : null}

      <ConfirmDialog
        open={confirmDelete}
        title="Heizzone löschen?"
        message={`Heizzone „${zone.name}" wird endgültig entfernt. Geräte bleiben erhalten (Zone-Zuordnung wird auf NULL gesetzt).`}
        confirmLabel="Endgültig löschen"
        loading={deleteMut.isPending}
        onConfirm={performDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}

/**
 * Sprint 14e T5a — Zone-Name als Inline-Edit fuer Admins (AE-46).
 *
 * Pattern aus ``app/devices/page.tsx`` LabelCell (Sprint 14a). Admin-Gating
 * (R5) liegt am Aufrufer; diese Komponente vertraut darauf, dass sie nur fuer
 * Admins gerendert wird. Backend-Security bleibt unabhaengig
 * (``require_admin`` an PATCH /heating-zones, Sprint 14e T4-Audit).
 *
 * Kein Confirm-Dialog (Brief T5: ``name`` ohne Warnung, ohne Engine-Wirkung).
 */
function ZoneNameInlineEdit({ zone, roomId }: { zone: HeatingZone; roomId: number }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(zone.name);
  const [error, setError] = useState<string | null>(null);
  const updateMut = useUpdateHeatingZone(roomId);

  const save = async () => {
    const trimmed = draft.trim();
    if (trimmed.length === 0) {
      setError("Name darf nicht leer sein");
      return;
    }
    if (trimmed === zone.name) {
      setEditing(false);
      return;
    }
    setError(null);
    try {
      await updateMut.mutateAsync({ zoneId: zone.id, payload: { name: trimmed } });
      setEditing(false);
    } catch (e) {
      setError(toMessage(e));
    }
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void save();
    } else if (e.key === "Escape") {
      e.preventDefault();
      setDraft(zone.name);
      setError(null);
      setEditing(false);
    }
  };

  if (editing) {
    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKey}
            onBlur={() => void save()}
            autoFocus
            autoComplete="off"
            disabled={updateMut.isPending}
            className="h-8 text-base"
            aria-label="Zonenname bearbeiten"
            data-testid={`zone-card-${zone.id}-name-input`}
          />
        </div>
        {error ? (
          <span role="alert" className="text-xs text-error">
            {error}
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setEditing(true)}
      className="text-base font-medium text-text-primary hover:text-text-secondary text-left"
      data-testid={`zone-card-${zone.id}-name-edit`}
    >
      {zone.name}
    </button>
  );
}

/**
 * Sprint 14e (FU-1 + FU-2): zwei Zeilen unter Kind-Label.
 *
 * Zeile 1: Ist-Temp aus zone.mean_temperature_c.
 * Zeile 2: Effektiver Setpoint (R1) — active_override > engine_setpoint_c >
 * „—". Bei aktivem Override Source-Badge dahinter, weil dann die Quelle
 * (Gast/Mitarbeiter) für den Hotelier relevant ist.
 */
function ZoneHeaderMetrics({ zone }: { zone: HeatingZone }) {
  const override = zone.active_override;
  const effectiveSetpoint = override ? override.setpoint_celsius : zone.engine_setpoint_c;
  return (
    <dl className="mt-2 grid grid-cols-1 gap-1 text-sm">
      <div
        className="flex items-baseline gap-2"
        data-testid={`zone-card-${zone.id}-mean-temp`}
      >
        <dt className="text-text-tertiary inline-flex items-center gap-1">
          <span className="material-symbols-outlined text-base" aria-hidden>
            thermostat
          </span>
          Ist-Temp
        </dt>
        <dd className="tabular-nums text-text-primary">
          {zone.mean_temperature_c === null
            ? "—"
            : `${zone.mean_temperature_c.toFixed(1)} °C`}
        </dd>
      </div>
      <div
        className="flex items-baseline gap-2"
        data-testid={`zone-card-${zone.id}-effective-setpoint`}
      >
        <dt className="text-text-tertiary inline-flex items-center gap-1">
          <span className="material-symbols-outlined text-base" aria-hidden>
            target
          </span>
          Soll
        </dt>
        <dd className="tabular-nums text-text-primary">
          {effectiveSetpoint === null ? "—" : `${effectiveSetpoint.toFixed(1)} °C`}
        </dd>
        {override ? (
          <dd
            className="text-xs text-text-tertiary"
            data-testid={`zone-card-${zone.id}-soll-source`}
          >
            {SOURCE_LABEL[override.source]}
          </dd>
        ) : null}
      </div>
    </dl>
  );
}

function toMessage(err: unknown): string {
  const e = err as ApiError | Error;
  if (typeof e === "object" && e !== null && "detail" in e) {
    const d = (e as ApiError).detail;
    return typeof d === "string" ? d : JSON.stringify(d);
  }
  return e instanceof Error ? e.message : "Unbekannter Fehler";
}
