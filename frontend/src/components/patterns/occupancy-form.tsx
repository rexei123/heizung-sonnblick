"use client";

/**
 * Belegungs-Anlege-Form (Sprint 8.11, Sprint 8.15 Design-Fixes).
 */

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { useRooms } from "@/lib/api/hooks-rooms";
import type { OccupancyCreate } from "@/lib/api/types";

interface Props {
  onSubmit: (payload: OccupancyCreate) => Promise<void>;
  onCancel?: () => void;
  submitting?: boolean;
  error?: string | null;
  prefilledRoomId?: number;
}

function toIsoDatetimeLocal(d: Date): string {
  // Format yyyy-MM-ddTHH:mm fuer datetime-local input.
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

export function OccupancyForm({
  onSubmit,
  onCancel,
  submitting,
  error,
  prefilledRoomId,
}: Props) {
  const rooms = useRooms({ limit: 1000 });

  // Default: heute 14:00 - morgen 11:00 (Hotel-Standardzeiten)
  const today14 = new Date();
  today14.setHours(14, 0, 0, 0);
  const tomorrow11 = new Date(today14);
  tomorrow11.setDate(tomorrow11.getDate() + 1);
  tomorrow11.setHours(11, 0, 0, 0);

  const [roomId, setRoomId] = useState<number | "">(prefilledRoomId ?? "");
  const [checkIn, setCheckIn] = useState(toIsoDatetimeLocal(today14));
  const [checkOut, setCheckOut] = useState(toIsoDatetimeLocal(tomorrow11));
  const [guestCount, setGuestCount] = useState("");
  const [externalId, setExternalId] = useState("");

  const handle = async (e: FormEvent) => {
    e.preventDefault();
    if (roomId === "") return;
    const payload: OccupancyCreate = {
      room_id: roomId,
      // datetime-local sendet ohne Timezone-Marker. Wir interpretieren
      // als lokale Zeit und konvertieren in UTC-ISO-String.
      check_in: new Date(checkIn).toISOString(),
      check_out: new Date(checkOut).toISOString(),
      guest_count: guestCount.trim() === "" ? null : parseInt(guestCount, 10),
      external_id: externalId.trim() || null,
      source: "manual",
    };
    await onSubmit(payload);
  };

  return (
    <form onSubmit={handle} className="space-y-4">
      <div>
        <label htmlFor="o-room" className="block text-sm font-medium text-text-primary mb-1">
          Zimmer *
        </label>
        <select
          id="o-room"
          value={roomId}
          onChange={(e) =>
            setRoomId(e.target.value === "" ? "" : parseInt(e.target.value, 10))
          }
          required
          className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
        >
          <option value="">— bitte wählen —</option>
          {(rooms.data ?? []).map((r) => (
            <option key={r.id} value={r.id}>
              {r.number}
              {r.display_name ? ` — ${r.display_name}` : ""}
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label
            htmlFor="o-checkin"
            className="block text-sm font-medium text-text-primary mb-1"
          >
            Anreise *
          </label>
          <input
            id="o-checkin"
            type="datetime-local"
            value={checkIn}
            onChange={(e) => setCheckIn(e.target.value)}
            required
            className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
          />
        </div>
        <div>
          <label
            htmlFor="o-checkout"
            className="block text-sm font-medium text-text-primary mb-1"
          >
            Abreise *
          </label>
          <input
            id="o-checkout"
            type="datetime-local"
            value={checkOut}
            onChange={(e) => setCheckOut(e.target.value)}
            required
            className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
          />
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="o-guests" className="block text-sm font-medium text-text-primary mb-1">
            Personen
          </label>
          <input
            id="o-guests"
            type="number"
            min={1}
            max={20}
            value={guestCount}
            onChange={(e) => setGuestCount(e.target.value)}
            placeholder="z.B. 2"
            className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
          />
        </div>
        <div>
          <label htmlFor="o-ext" className="block text-sm font-medium text-text-primary mb-1">
            Externe ID (PMS)
          </label>
          <input
            id="o-ext"
            type="text"
            value={externalId}
            onChange={(e) => setExternalId(e.target.value)}
            maxLength={100}
            placeholder="optional"
            className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
          />
        </div>
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
          variant="add"
          icon="add"
          loading={submitting}
          disabled={roomId === ""}
        >
          Belegung anlegen
        </Button>
      </div>
    </form>
  );
}
