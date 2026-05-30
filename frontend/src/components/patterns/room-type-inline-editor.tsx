"use client";

/**
 * Sprint 14e T5b — Room.room_type_id Inline-Select mit Confirm + Audit.
 *
 * Bedienpfad: Admin sieht Pill mit room_type-Namen, Klick oeffnet Select
 * (DropDown), Wahl eines anderen room_type triggert ConfirmDialog mit
 * Engine-Wirkungs-Warnung. Backend (T4) schreibt einen
 * ``ROOM_TYPE_CHANGED``-business_audit Eintrag inkl.
 * ``engine_effect=rule_config_scope_room_type``.
 *
 * Affordance-Gating (R5): nur Admins sehen den Edit-Button. Mitarbeiter
 * sehen den room_type-Namen read-only. Backend-Security ist unabhaengig
 * (``require_admin``).
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useAuth } from "@/contexts/auth-context";
import { useRoomTypes } from "@/lib/api/hooks-room-types";
import { useUpdateRoom } from "@/lib/api/hooks-rooms";
import type { ApiError, Room } from "@/lib/api/types";

interface Props {
  room: Room;
}

export function RoomTypeInlineEditor({ room }: Props) {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const roomTypes = useRoomTypes();
  const updateMut = useUpdateRoom(room.id);
  const [pendingId, setPendingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const currentName =
    (roomTypes.data ?? []).find((rt) => rt.id === room.room_type_id)?.name ??
    `Typ ${room.room_type_id}`;
  const pendingName =
    pendingId != null
      ? ((roomTypes.data ?? []).find((rt) => rt.id === pendingId)?.name ??
        `Typ ${pendingId}`)
      : null;

  const confirm = async () => {
    if (pendingId === null) return;
    setError(null);
    try {
      await updateMut.mutateAsync({ room_type_id: pendingId });
      setPendingId(null);
    } catch (e) {
      const apiErr = e as ApiError | Error;
      setError(
        "detail" in apiErr && typeof apiErr.detail === "string"
          ? apiErr.detail
          : apiErr instanceof Error
            ? apiErr.message
            : "Fehler beim Speichern",
      );
    }
  };

  return (
    <div
      className="border border-border rounded-md p-3 flex items-center justify-between gap-3"
      data-testid="room-type-inline-editor"
    >
      <div className="flex items-center gap-3">
        <span className="material-symbols-outlined text-text-secondary" aria-hidden>
          category
        </span>
        <div>
          <p className="text-xs text-text-tertiary">Raumtyp</p>
          <p
            className="text-base font-medium text-text-primary"
            data-testid="room-type-inline-current"
          >
            {currentName}
          </p>
        </div>
      </div>

      {isAdmin ? (
        <div className="flex items-center gap-2">
          <label htmlFor={`rt-select-${room.id}`} className="sr-only">
            Raumtyp auswaehlen
          </label>
          <select
            id={`rt-select-${room.id}`}
            value={room.room_type_id}
            onChange={(e) => {
              const next = parseInt(e.target.value, 10);
              if (next !== room.room_type_id) {
                setPendingId(next);
              }
            }}
            disabled={updateMut.isPending}
            className="h-9 px-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus text-sm"
            data-testid="room-type-inline-select"
          >
            {(roomTypes.data ?? []).map((rt) => (
              <option key={rt.id} value={rt.id}>
                {rt.name}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="text-sm text-error">
          {error}
        </p>
      ) : null}

      <ConfirmDialog
        open={pendingId !== null}
        title="Raumtyp ändern?"
        message={
          `Heizverhalten ändert sich beim nächsten Engine-Tick (~60 s):\n` +
          `Belegt-, Leer-, Nacht- und Frostschutz-Solltemperaturen ` +
          `wechseln auf die Werte von „${pendingName ?? ""}". ` +
          `Betrifft auch belegte Zimmer.`
        }
        confirmLabel="Raumtyp ändern"
        loading={updateMut.isPending}
        onConfirm={confirm}
        onCancel={() => setPendingId(null)}
      />
      {/* Cancel-Button als Fallback fuer Tests/Reset (falls Confirm-Dialog
          nicht via UI sondern direkt geschlossen werden soll). */}
      {pendingId !== null && updateMut.isPending ? (
        <Button
          variant="ghost"
          onClick={() => setPendingId(null)}
          disabled={updateMut.isPending}
        >
          Abbrechen
        </Button>
      ) : null}
    </div>
  );
}
