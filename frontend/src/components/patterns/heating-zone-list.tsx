"use client";

/**
 * Heizzonen-Liste fuer die Zimmer-Detail-Seite (Sprint 8.10, Sprint 8.15
 * Design-Fixes; Sprint 14b: Zone-Karten statt flacher Liste).
 *
 * Sprint 14b: Die flache `<li>`-Liste ist durch vertikal gestapelte
 * `ZoneCard`s ersetzt (Header + ZoneHealthBadge + Thermostat-Bubbles +
 * read-only Override-Banner/CTA + Zone löschen). Das „Neue Heizzone"-Anlege-
 * Formular bleibt unverändert darunter. Löschen läuft jetzt aus der ZoneCard
 * heraus (useDeleteHeatingZone dort) — die Query-Invalidation aktualisiert
 * diese Liste automatisch.
 */

import { useState } from "react";

import { ZoneCard } from "@/components/patterns/zone-card";
import { Button } from "@/components/ui/button";
import { useDevices } from "@/lib/api/hooks";
import { useCreateHeatingZone, useHeatingZones } from "@/lib/api/hooks-rooms";
import { fehlerText } from "@/lib/api/fehler";
import type { HeatingZoneKind } from "@/lib/api/types";
import { useAuth } from "@/contexts/auth-context";
import { darfStammdatenAendern } from "@/lib/auth/rechte";

const KINDS: HeatingZoneKind[] = [
  "bedroom",
  "bathroom",
  "living",
  "hallway",
  "common_area",
  "other",
];
const KIND_LABEL: Record<HeatingZoneKind, string> = {
  bedroom: "Schlafzimmer",
  bathroom: "Bad",
  living: "Wohnen",
  hallway: "Flur",
  common_area: "Allgemeinbereich",
  other: "Sonstige",
};

interface Props {
  roomId: number;
  /** Sprint 14b: programmatischer Wechsel auf den Übersteuerung-Tab (Link-out). */
  onSwitchToOverrideTab?: () => void;
}

export function HeatingZoneList({ roomId, onSwitchToOverrideTab }: Props) {
  const list = useHeatingZones(roomId);
  const allDevices = useDevices();
  const createMut = useCreateHeatingZone(roomId);
  // Sprint 22 T3: das Anlege-Formular war fuer jede Rolle sichtbar
  // (Befund des Hoteliers, 14.10.2026). `POST .../heating-zones` ist
  // `require_admin` (`api/v1/heating_zones.py:157`).
  const { user } = useAuth();
  const darfAendern = darfStammdatenAendern(user);

  const [name, setName] = useState("");
  const [kind, setKind] = useState<HeatingZoneKind>("bedroom");
  const [isTowel, setIsTowel] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAdd = async () => {
    setError(null);
    try {
      await createMut.mutateAsync({
        kind,
        name: name.trim(),
        is_towel_warmer: isTowel,
      });
      setName("");
      setKind("bedroom");
      setIsTowel(false);
    } catch (e) {
      setError(toMessage(e));
    }
  };

  return (
    <div className="space-y-4">
      <div>
        {list.isLoading ? (
          <p className="text-sm text-text-secondary">Lade…</p>
        ) : list.isError ? (
          <p className="text-sm text-error">Fehler beim Laden.</p>
        ) : (list.data ?? []).length === 0 ? (
          <p className="text-sm text-text-secondary italic">
            Noch keine Heizzonen. Lege z.B. Schlafzimmer + Bad an.
          </p>
        ) : (
          <div className="space-y-4">
            {list.data!.map((z) => (
              <ZoneCard
                key={z.id}
                zone={z}
                devices={allDevices.data ?? []}
                roomId={roomId}
                onSwitchToOverrideTab={onSwitchToOverrideTab}
              />
            ))}
          </div>
        )}
      </div>

      {!darfAendern ? null : (
        <div className="border-t border-border pt-4">
          <h3 className="text-sm font-medium text-text-primary mb-3">
            Neue Heizzone
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-[1fr_140px_auto] gap-2">
            <input
              type="text"
              placeholder="Name (z.B. Schlafzimmer)"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={100}
              className="px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus text-sm"
            />
            <select
              value={kind}
              onChange={(e) => setKind(e.target.value as HeatingZoneKind)}
              className="px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus text-sm"
            >
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {KIND_LABEL[k]}
                </option>
              ))}
            </select>
            <Button
              variant="add"
              icon="add"
              onClick={handleAdd}
              loading={createMut.isPending}
              disabled={!name.trim()}
            >
              Hinzufügen
            </Button>
          </div>
          <label className="flex items-center gap-2 mt-2 text-sm text-text-primary">
            <input
              type="checkbox"
              checked={isTowel}
              onChange={(e) => setIsTowel(e.target.checked)}
            />
            {/* Sprint 22 T7-Vorgriff: der Klammerzusatz „(eigene Regel-Logik
              in Sprint 9)" stand hier seit Sprint 8 und versprach eine
              Logik, die es nicht gibt — `is_towel_warmer` ist ein Marker
              ohne Engine-Konsument (§5.43 hat genau das belegt). Ein
              Hinweis, der eine Wirkung behauptet, ist §5.77. */}
            Handtuchtrockner
          </label>

          {error ? (
            <div
              role="alert"
              className="mt-2 text-sm text-error bg-error-soft border border-error rounded-md px-3 py-2"
            >
              {error}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

// Sprint 24e: dieselbe Frage, eine Antwort. Die eigene Fassung hier war
// richtig und hat trotzdem dazu beigetragen, dass sechs andere Stellen
// ihre eigene geschrieben haben — vier davon falsch (`fehler.message` auf
// einem Objekt, das keine `Error`-Instanz ist).
function toMessage(err: unknown): string {
  return fehlerText(err);
}
