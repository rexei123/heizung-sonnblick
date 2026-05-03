"use client";

/**
 * Heizzonen-Liste fuer die Zimmer-Detail-Seite (Sprint 8.10).
 * Inline anlegen + loeschen (kein Edit, weil zu selten — Tab-Wechsel-Friction).
 */

import { useState } from "react";

import {
  useCreateHeatingZone,
  useDeleteHeatingZone,
  useHeatingZones,
} from "@/lib/api/hooks-rooms";
import type { ApiError, HeatingZoneKind } from "@/lib/api/types";

const KINDS: HeatingZoneKind[] = ["bedroom", "bathroom", "living", "hallway", "other"];

interface Props {
  roomId: number;
}

export function HeatingZoneList({ roomId }: Props) {
  const list = useHeatingZones(roomId);
  const createMut = useCreateHeatingZone(roomId);
  const deleteMut = useDeleteHeatingZone(roomId);

  const [name, setName] = useState("");
  const [kind, setKind] = useState<HeatingZoneKind>("bedroom");
  const [isTowel, setIsTowel] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAdd = async () => {
    setError(null);
    try {
      await createMut.mutateAsync({ kind, name: name.trim(), is_towel_warmer: isTowel });
      setName("");
      setKind("bedroom");
      setIsTowel(false);
    } catch (e) {
      setError(toMessage(e));
    }
  };

  const handleDelete = async (zoneId: number) => {
    if (!confirm("Heizzone loeschen? Geraete bleiben erhalten (Zone-Zuordnung wird auf NULL).")) {
      return;
    }
    setError(null);
    try {
      await deleteMut.mutateAsync(zoneId);
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
          <p className="text-sm text-domain-heating-off">Fehler beim Laden.</p>
        ) : (list.data ?? []).length === 0 ? (
          <p className="text-sm text-text-secondary italic">
            Noch keine Heizzonen. Lege z.B. Schlafzimmer + Bad an.
          </p>
        ) : (
          <ul className="bg-surface border border-border rounded-md overflow-hidden">
            {list.data!.map((z) => (
              <li
                key={z.id}
                className="flex items-center justify-between px-3 py-2 border-b border-border last:border-b-0"
              >
                <div>
                  <div className="font-medium text-text-primary text-sm">
                    {z.name}{" "}
                    {z.is_towel_warmer ? (
                      <span className="text-xs text-text-tertiary">(Handtuchtrockner)</span>
                    ) : null}
                  </div>
                  <div className="text-xs text-text-tertiary">{z.kind}</div>
                </div>
                <button
                  type="button"
                  onClick={() => handleDelete(z.id)}
                  className="text-xs text-domain-heating-off hover:underline"
                  disabled={deleteMut.isPending}
                >
                  Loeschen
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="border-t border-border pt-4">
        <h3 className="text-sm font-medium text-text-primary mb-3">Neue Heizzone</h3>
        <div className="grid grid-cols-1 sm:grid-cols-[1fr_120px_auto] gap-2">
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
                {k}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={handleAdd}
            disabled={createMut.isPending || !name.trim()}
            className="px-4 py-2 bg-primary text-on-primary rounded-md disabled:opacity-50 text-sm"
          >
            Hinzufuegen
          </button>
        </div>
        <label className="flex items-center gap-2 mt-2 text-sm text-text-primary">
          <input
            type="checkbox"
            checked={isTowel}
            onChange={(e) => setIsTowel(e.target.checked)}
          />
          Handtuchtrockner (eigene Regel-Logik in Sprint 9)
        </label>

        {error ? (
          <div
            role="alert"
            className="mt-2 text-sm text-domain-heating-off bg-surface-alt border border-domain-heating-off rounded-md px-3 py-2"
          >
            {error}
          </div>
        ) : null}
      </div>
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
