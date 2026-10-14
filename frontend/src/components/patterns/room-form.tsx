"use client";

/**
 * Zimmer-Form (Sprint 8.10, Sprint 8.15 Design-Fixes).
 */

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { useRoomTypes } from "@/lib/api/hooks-room-types";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
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
  /**
   * Sprint 21 A2: ohne Recht zum Speichern (`PATCH /rooms/{id}` ist
   * `require_admin`) bleibt das Formular lesbar, der Knopf ist gesperrt und
   * sagt warum. Vorher fuehrte "Aktualisieren" fuer Mitarbeiter in ein 403.
   */
  readOnly?: boolean;
}

export function RoomForm({
  initial,
  onSubmit,
  onCancel,
  submitting,
  error,
  readOnly = false,
}: Props) {
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
  const [bestaetigeAnhalten, setBestaetigeAnhalten] = useState<RoomStatus | null>(null);

  /**
   * Sprint 22 T7: „Reinigung" und „Gesperrt" nehmen das Zimmer aus der
   * Automatik — und zwar lautlos, bis jemand sie zurückstellt. Dafür gibt
   * es eine Bestätigung, wie im Gefahrenbereich.
   *
   * Die anderen drei Werte brauchen keine: sie werden binnen einer Minute
   * überschrieben, die Eingabe ist also folgenlos (der Hinweis unter dem
   * Feld sagt das).
   */
  const waehleStatus = (next: RoomStatus | "") => {
    if (next === "cleaning" || next === "blocked") {
      setBestaetigeAnhalten(next);
      return;
    }
    setStatus(next);
  };
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
              Status (automatisch aus Belegungen)
            </label>
            <select
              id="r-status"
              value={status}
              onChange={(e) => waehleStatus((e.target.value || "") as RoomStatus | "")}
              className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
            >
              <option value="">—</option>
              <option value="vacant">Frei</option>
              <option value="occupied">Belegt</option>
              <option value="reserved">Reserviert</option>
              <option value="cleaning">Reinigung</option>
              <option value="blocked">Gesperrt</option>
            </select>
            {/* Sprint 22 T7: das Feld ist **halb** automatisch, und das ist
                der ganze Hinweis. `sync_room_status` leitet den Status alle
                60 s aus den Belegungen ab — ausser bei „Reinigung" und
                „Gesperrt", die gelten als manuell gesetzt
                (`occupancy_service.py:242`). */}
            <p className="text-xs text-text-tertiary mt-1">
              Frei, Belegt und Reserviert werden laufend aus den Belegungen
              gesetzt — eine Eingabe hier wird binnen einer Minute
              überschrieben. <strong>Reinigung</strong> und{" "}
              <strong>Gesperrt</strong> bleiben stehen und halten den
              Abgleich für dieses Zimmer an.
            </p>
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

      <div className="flex gap-2 justify-end items-center">
        {readOnly ? (
          <p className="text-xs text-text-tertiary mr-auto">
            Stammdaten ändern ist Administratoren vorbehalten.
          </p>
        ) : null}
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
          disabled={readOnly || !number.trim() || roomTypeId === ""}
        >
          {initial ? "Aktualisieren" : "Anlegen"}
        </Button>
      </div>
      <ConfirmDialog
        open={bestaetigeAnhalten !== null}
        title="Automatik anhalten?"
        // Nicht `destructive`: hier wird nichts zerstoert, sondern ein
        // Abgleich angehalten — umkehrbar durch Zuruecksetzen des Status.
        // Rot an einer umkehrbaren Stelle entwertet Rot an der
        // zerstoerenden (§5.79, derselbe Gedanke eine Ebene hoeher).
        intent="primary"
        message={
          bestaetigeAnhalten === "blocked"
            ? "Mit „Gesperrt“ wird dieses Zimmer nicht mehr automatisch aus den Belegungen gesetzt — bis der Status wieder auf Frei, Belegt oder Reserviert steht. Anreisen und Abreisen wirken dann nicht mehr auf den Status."
            : "Mit „Reinigung“ wird dieses Zimmer nicht mehr automatisch aus den Belegungen gesetzt — bis der Status wieder auf Frei, Belegt oder Reserviert steht."
        }
        confirmLabel="Automatik anhalten"
        onConfirm={() => {
          if (bestaetigeAnhalten !== null) setStatus(bestaetigeAnhalten);
          setBestaetigeAnhalten(null);
        }}
        onCancel={() => setBestaetigeAnhalten(null)}
      />
    </form>
  );
}
