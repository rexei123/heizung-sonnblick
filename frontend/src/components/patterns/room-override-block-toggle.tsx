"use client";

/**
 * Sprint 12c (AE-58) — Uebersteuerungs-Sperre togglen.
 *
 * Mitarbeiter-Aktion: ``room.guest_override_blocked`` an/aus. Sichtbar im
 * Zimmer-Detail-Header neben Zimmer-Nummer/Display-Name.
 *
 * Wording strict (siehe AE-58):
 * - Toggle-On-State: „Uebersteuerung gesperrt"
 *   (NICHT „Zimmer gesperrt" — das ist ``RoomStatus.BLOCKED``).
 * - Toggle-Off-State: „Uebersteuerung freigegeben".
 *
 * Toggle-On (False -> True) bei aktiven Overrides loest serverseitig
 * einen Auto-Revoke aus (alle Overrides des Raums, source-agnostic,
 * ``revoked_reason="room_override_blocked"``). Der Confirm-Dialog kommt
 * nur, wenn ``activeOverridesCount > 0`` ist — sonst direkter Mutate
 * (S6: Komplexitaet traegt Beweislast, kein Confirm-Klick wenn nichts
 * verworfen wird).
 *
 * Toggle-Off (True -> False) ist immer ohne Confirm: kein
 * destruktiver Effekt.
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useSetRoomOverrideBlockState } from "@/lib/api/hooks-rooms";
import type { Room } from "@/lib/api/types";

interface Props {
  room: Room;
  activeOverridesCount: number;
}

export function RoomOverrideBlockToggle({ room, activeOverridesCount }: Props) {
  const mut = useSetRoomOverrideBlockState(room.id);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [feedback, setFeedback] = useState<
    { kind: "success" | "error"; text: string } | null
  >(null);

  const isBlocked = room.guest_override_blocked;

  const runMutate = async (next: boolean) => {
    setFeedback(null);
    try {
      await mut.mutateAsync(next);
      setFeedback({
        kind: "success",
        text: next ? "Übersteuerung gesperrt." : "Übersteuerung freigegeben.",
      });
    } catch (e) {
      setFeedback({
        kind: "error",
        text: e instanceof Error ? e.message : "Aktion fehlgeschlagen.",
      });
    }
  };

  const handleClick = () => {
    if (isBlocked) {
      void runMutate(false);
      return;
    }
    if (activeOverridesCount > 0) {
      setConfirmOpen(true);
      return;
    }
    void runMutate(true);
  };

  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        variant={isBlocked ? "secondary" : "primary"}
        icon={isBlocked ? "lock" : "lock_open"}
        onClick={handleClick}
        loading={mut.isPending}
        aria-pressed={isBlocked}
        aria-label={
          isBlocked
            ? "Übersteuerung freigeben"
            : "Übersteuerung sperren"
        }
      >
        {isBlocked ? "Übersteuerung gesperrt" : "Übersteuerung sperren"}
      </Button>
      {feedback ? (
        <p
          role="status"
          aria-live="polite"
          className={`text-xs ${
            feedback.kind === "error" ? "text-error" : "text-text-secondary"
          }`}
        >
          {feedback.text}
        </p>
      ) : null}

      <ConfirmDialog
        open={confirmOpen}
        title="Übersteuerung sperren?"
        message={`${activeOverridesCount} aktive ${
          activeOverridesCount === 1 ? "Übersteuerung wird" : "Übersteuerungen werden"
        } aufgehoben. Fortfahren?`}
        confirmLabel="Sperren"
        intent="destructive"
        loading={mut.isPending}
        onConfirm={() => {
          setConfirmOpen(false);
          void runMutate(true);
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
