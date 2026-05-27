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
 * Der aktive Override wird read-only aus ``device.active_override`` der
 * Zone-Geräte gespiegelt (zone-scoped Override ist pro Zone identisch).
 *
 * Wording §5.20: „Thermostat"; „Vicki" höchstens im Tooltip.
 */

import { useState } from "react";

import { ThermostatBubble } from "@/components/patterns/thermostat-bubble";
import { ZoneHealthBadge } from "@/components/patterns/zone-health-badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useZoneOverride } from "@/lib/api/hooks-overrides";
import { useDeleteHeatingZone } from "@/lib/api/hooks-rooms";
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

  const zoneDevices = devices.filter((d) => d.heating_zone_id === zone.id);
  // T9.5: aktiver Zone-Override read-only über den Bestand-Convenience-Hook
  // useZoneOverride (Zone-Match + Room-Scope-Fallback, revoked/expired
  // gefiltert, jüngster gewinnt — identisch zu ManualOverridePanelList).
  // Semantisch sauber (kein device.active_override-Edge bei Mehrfach-Vicki /
  // geräteloser Zone). Backlog B-14b-FU-5: HeatingZoneRead.active_override
  // backendseitig nachziehen, dann entfällt der Hook-Roundtrip.
  const activeOverride = useZoneOverride(roomId, zone.id).data ?? null;

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
          <h3 className="text-base font-medium text-text-primary">{zone.name}</h3>
          <ZoneHealthBadge healthState={zone.health_state} variant="compact" />
        </div>
        <p className="text-xs text-text-tertiary mt-0.5">
          {KIND_LABEL[zone.kind]}
          {zone.is_towel_warmer ? " · Handtuchtrockner" : ""}
        </p>
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
                  {Math.round(parseFloat(activeOverride.setpoint))}
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

function toMessage(err: unknown): string {
  const e = err as ApiError | Error;
  if (typeof e === "object" && e !== null && "detail" in e) {
    const d = (e as ApiError).detail;
    return typeof d === "string" ? d : JSON.stringify(d);
  }
  return e instanceof Error ? e.message : "Unbekannter Fehler";
}
