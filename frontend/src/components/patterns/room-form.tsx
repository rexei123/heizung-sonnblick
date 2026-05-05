"use client";

/**
 * Zimmer-Form (Sprint 8.10, Sprint 8.15 Design-Fixes).
 */

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { useRoomTypes } from "@/lib/api/hooks-room-types";
import type {
  Orientation,
  Room,
  RoomCreate,
  RoomStatus,
  RoomUpdate,
} from "@/lib/api/types";

const ORIENTATIONS: Orientation[] = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

interface Props {
  initial?: Room;
  onSubmit: (payload: RoomCreate | RoomUpdate) => Promise<void>;
  onCancel?: () => void;
  submitting?: boolean;
  error?: string | null;
}

export function RoomForm({ initial, onSubmit, onCancel, submitting, error }: Props) {
  const roomTypes = useRoomTypes();

  const [number, setNumber] = useState(initial?.number ?? "");
  const [displayName, setDisplayName] = useState(initial?.display_name ?? "");
  const [roomTypeId, setRoomTypeId] = useState<number | "">(
    initial?.room_type_id ?? "",
  );
  const [floor, setFloor] = useState(initial?.floor != null ? String(initial.floor) : "");
  const [orientation, setOrientation] = useState<Orientation | "">(
    initial?.orientation ?? "",
  );
  const [status, setStatus] = useState<RoomStatus | "">(initial?.status ?? "");
  const [notes, setNotes] = useState(initial?.notes ?? "");

  const handle = async (e: FormEvent) => {
    e.preventDefault();
    if (roomTypeId === "") return;
    const payload: RoomCreate | RoomUpdate = {
      number: number.trim(),
      display_name: displayName.trim() || null,
      room_type_id: roomTypeId,
      floor: floor.trim() === "" ? null : parseInt(floor, 10),
      orientation: orientation === "" ? null : orientation,
      notes: notes.trim() || null,
      ...(initial && status !== "" ? { status } : {}),
    };
    await onSubmit(payload);
  };

  return (
    <form onSubmit={handle} className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="r-number" className="block text-sm font-medium text-text-primary mb-1">
            Zimmernummer *
          </label>
          <input
            id="r-number"
            type="text"
            value={number}
            onChange={(e) => setNumber(e.target.value)}
            required
            maxLength={20}
            className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
          />
        </div>
        <div>
          <label htmlFor="r-floor" className="block text-sm font-medium text-text-primary mb-1">
            Etage
          </label>
          <input
            id="r-floor"
            type="number"
            min={-5}
            max={50}
            value={floor}
            onChange={(e) => setFloor(e.target.value)}
            className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
          />
        </div>
      </div>

      <div>
        <label htmlFor="r-display" className="block text-sm font-medium text-text-primary mb-1">
          Anzeigename
        </label>
        <input
          id="r-display"
          type="text"
          value={displayName ?? ""}
          onChange={(e) => setDisplayName(e.target.value)}
          maxLength={100}
          className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
        />
      </div>

      <div>
        <label htmlFor="r-type" className="block text-sm font-medium text-text-primary mb-1">
          Raumtyp *
        </label>
        <select
          id="r-type"
          value={roomTypeId}
          onChange={(e) =>
            setRoomTypeId(e.target.value === "" ? "" : parseInt(e.target.value, 10))
          }
          required
          className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
        >
          <option value="">— bitte wählen —</option>
          {(roomTypes.data ?? []).map((rt) => (
            <option key={rt.id} value={rt.id}>
              {rt.name}
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="r-orient" className="block text-sm font-medium text-text-primary mb-1">
            Orientierung
          </label>
          <select
            id="r-orient"
            value={orientation}
            onChange={(e) => setOrientation((e.target.value || "") as Orientation | "")}
            className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
          >
            <option value="">—</option>
            {ORIENTATIONS.map((o) => (
              <option key={o} value={o}>
                {o}
              </option>
            ))}
          </select>
        </div>
        {initial ? (
          <div>
            <label htmlFor="r-status" className="block text-sm font-medium text-text-primary mb-1">
              Status (manuell)
            </label>
            <select
              id="r-status"
              value={status}
              onChange={(e) => setStatus((e.target.value || "") as RoomStatus | "")}
              className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
            >
              <option value="">—</option>
              <option value="vacant">Frei</option>
              <option value="occupied">Belegt</option>
              <option value="reserved">Reserviert</option>
              <option value="cleaning">Reinigung</option>
              <option value="blocked">Gesperrt</option>
            </select>
          </div>
        ) : null}
      </div>

      <div>
        <label htmlFor="r-notes" className="block text-sm font-medium text-text-primary mb-1">
          Notizen
        </label>
        <textarea
          id="r-notes"
          value={notes ?? ""}
          onChange={(e) => setNotes(e.target.value)}
          maxLength={1000}
          rows={2}
          className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
        />
      </div>

      {error ? (
        <div
          role="alert"
          className="text-sm text-error bg-error-soft border border-error rounded-md px-3 py-2"
        >
          {error}
        </div>
      ) : null}

      <div className="flex gap-2 justify-end">
        {onCancel ? (
          <Button variant="secondary" onClick={onCancel}>
            Abbrechen
          </Button>
        ) : null}
        <Button
          type="submit"
          variant={initial ? "primary" : "add"}
          icon={initial ? undefined : "add"}
          loading={submitting}
          disabled={!number.trim() || roomTypeId === ""}
        >
          {initial ? "Aktualisieren" : "Anlegen"}
        </Button>
      </div>
    </form>
  );
}
