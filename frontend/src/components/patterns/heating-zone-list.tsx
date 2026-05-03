"use client";

/**
 * Heizzonen-Liste fuer die Zimmer-Detail-Seite (Sprint 8.10, Sprint 8.15 Design-Fixes).
 * Inline anlegen + löschen.
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  useCreateHeatingZone,
  useDeleteHeatingZone,
  useHeatingZones,
} from "@/lib/api/hooks-rooms";
import type { ApiError, HeatingZone, HeatingZoneKind } from "@/lib/api/types";

const KINDS: HeatingZoneKind[] = ["bedroom", "bathroom", "living", "hallway", "other"];
const KIND_LABEL: Record<HeatingZoneKind, string> = {
  bedroom: "Schlafzimmer",
  bathroom: "Bad",
  living: "Wohnen",
  hallway: "Flur",
  other: "Sonstige",
};

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
  const [confirmDelete, setConfirmDelete] = useState<HeatingZone | null>(null);

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

  const performDelete = async () => {
    if (!confirmDelete) return;
    setError(null);
    try {
      await deleteMut.mutateAsync(confirmDelete.id);
      setConfirmDelete(null);
    } catch (e) {
      setError(toMessage(e));
      setConfirmDelete(null);
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
                  <div className="text-xs text-text-tertiary">{KIND_LABEL[z.kind]}</div>
                </div>
                <Button
                  variant="destructive"
                  icon="delete"
                  onClick={() => setConfirmDelete(z)}
                  disabled={deleteMut.isPending}
                >
                  Löschen
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="border-t border-border pt-4">
        <h3 className="text-sm font-medium text-text-primary mb-3">Neue Heizzone</h3>
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
          Handtuchtrockner (eigene Regel-Logik in Sprint 9)
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

      <ConfirmDialog
        open={confirmDelete !== null}
        title="Heizzone löschen?"
        message={
          confirmDelete
            ? `Heizzone „${confirmDelete.name}“ wird endgültig entfernt. Geräte bleiben erhalten (Zone-Zuordnung wird auf NULL gesetzt).`
            : ""
        }
        confirmLabel="Endgültig löschen"
        loading={deleteMut.isPending}
        onConfirm={performDelete}
        onCancel={() => setConfirmDelete(null)}
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
