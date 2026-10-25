"use client";

/**
 * Sprint 12c (AE-58) — Uebersteuerungs-Sperre togglen.
 * Sprint 23 T4-A — und zwar in zwei Formen: dauerhaft oder bis zur Abreise.
 *
 * Mitarbeiter-Aktion: ``room.guest_override_blocked`` an/aus. Sichtbar im
 * Zimmer-Detail-Header neben Zimmer-Nummer/Display-Name.
 *
 * Wording strict (siehe AE-58):
 * - Toggle-On-State: „Uebersteuerung gesperrt"
 *   (NICHT „Zimmer gesperrt" — das ist ``RoomStatus.BLOCKED``).
 * - Toggle-Off-State: „Uebersteuerung freigegeben".
 *
 * **Warum die Form abgefragt wird und nicht voreingestellt ist (T4-A).**
 * Der Regelfall ist ein Gast, der am Rad dreht und sich danach beschwert —
 * eine Sache für *diesen Aufenthalt*. Eine dauerhafte Sperre, die niemand
 * zurücknimmt, hinterlässt dem **nächsten** Gast ein Rad, das nichts
 * bewirkt, und an der Rezeption keine Erklärung dafür. Deshalb steht die
 * Frage vor dem Sperren, und „Bis Check-out" steht zuerst.
 *
 * **Zwei Knöpfe statt Auswahlfeld plus Bestätigung.** Jeder Knopf nennt
 * seine Handlung, und damit ist die Auswahl schon die Bestätigung — ein
 * Knopf, der einen Zustand anzeigt statt einer Handlung, liest sich wie
 * eine Beschriftung (§5.85).
 *
 * **Im Allgemeinbereich gibt es nur „dauerhaft".** Ein Bereich wechselt
 * nie auf „frei" (Sprint 24d), eine Sperre „bis Check-out" würde dort nie
 * enden. Der Server weist sie mit 422 ab; die Oberfläche bietet sie
 * deshalb nicht an — die Abweisung ist der Rückhalt, nicht die erste
 * Verteidigungslinie (§5.30).
 *
 * Toggle-On bei aktiven Overrides löst serverseitig einen Auto-Revoke aus
 * (alle Overrides des Raums, ``revoked_reason="room_override_blocked"``).
 * Der Hinweis darauf steht in der Auswahl; ein eigener Bestätigungsschritt
 * davor wäre ein zweiter Klick für dieselbe Entscheidung.
 *
 * Toggle-Off ist immer ohne Rückfrage: kein destruktiver Effekt.
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { fehlerText } from "@/lib/api/fehler";
import { useSetRoomOverrideBlockState } from "@/lib/api/hooks-rooms";
import type { Room } from "@/lib/api/types";

interface Props {
  room: Room;
  activeOverridesCount: number;
}

export function RoomOverrideBlockToggle({ room, activeOverridesCount }: Props) {
  const mut = useSetRoomOverrideBlockState(room.id);
  const [auswahlOffen, setAuswahlOffen] = useState(false);
  const [feedback, setFeedback] = useState<
    { kind: "success" | "error"; text: string } | null
  >(null);

  const isBlocked = room.guest_override_blocked;
  const bisCheckout = room.guest_block_bis_checkout;
  const istBereich = room.ist_allgemeinbereich;

  const runMutate = async (blocked: boolean, bisCheckoutNeu = false) => {
    setFeedback(null);
    setAuswahlOffen(false);
    try {
      await mut.mutateAsync({ blocked, bisCheckout: bisCheckoutNeu });
      setFeedback({
        kind: "success",
        text: !blocked
          ? "Übersteuerung freigegeben."
          : bisCheckoutNeu
            ? "Gesperrt bis zur Abreise."
            : "Dauerhaft gesperrt.",
      });
    } catch (e) {
      // `apiClient` wirft ein einfaches Objekt, keine `Error`-Instanz —
      // `e.message` wäre `undefined` und der Kasten leer (§24e). Hier
      // zählt das besonders: die beiden 422 dieses Endpoints sind
      // genau die Sätze, die der Nutzer lesen muss.
      setFeedback({ kind: "error", text: fehlerText(e) });
    }
  };

  const handleClick = () => {
    if (isBlocked) {
      void runMutate(false);
      return;
    }
    setAuswahlOffen(true);
  };

  return (
    <div className="flex flex-col items-end gap-1">
      {/* Sprint 21 A2: immer Umriss. Der primaere Knopf der Kopfzeile ist
          "Temperatur aendern" — die Sperre ist der seltene Handgriff. */}
      <Button
        variant="secondary"
        icon={isBlocked ? "lock" : "lock_open"}
        onClick={handleClick}
        loading={mut.isPending}
        aria-pressed={isBlocked}
        aria-label={isBlocked ? "Übersteuerung freigeben" : "Übersteuerung sperren"}
        data-testid="sperre-knopf"
      >
        {isBlocked ? "Übersteuerung gesperrt" : "Übersteuerung sperren"}
      </Button>

      {/* **Die Form steht dabei, wenn gesperrt ist.** „Gesperrt" allein
          sagt nicht, ob sich jemand nach der Abreise darum kümmern muss —
          und genau das ist die Information, die an der Rezeption
          gebraucht wird. */}
      {isBlocked ? (
        <p className="text-text-tertiary text-xs" data-testid="sperre-form">
          {bisCheckout
            ? "endet mit der Abreise"
            : "dauerhaft — bleibt auch für den nächsten Gast"}
        </p>
      ) : null}

      {auswahlOffen ? (
        <div
          className="border-border bg-surface mt-1 w-72 rounded-md border p-3 text-left shadow-md"
          data-testid="sperre-auswahl"
        >
          <p className="text-text-primary mb-1 text-sm font-medium">
            Wie lange soll die Sperre gelten?
          </p>
          {activeOverridesCount > 0 ? (
            <p className="text-text-secondary mb-2 text-xs">
              {activeOverridesCount === 1
                ? "1 aktive Übersteuerung wird aufgehoben."
                : `${activeOverridesCount} aktive Übersteuerungen werden aufgehoben.`}
            </p>
          ) : null}

          <div className="flex flex-col gap-2">
            {istBereich ? (
              <p className="text-text-tertiary text-xs">
                Ein Allgemeinbereich hat keine Abreise — hier gilt nur die
                dauerhafte Sperre.
              </p>
            ) : (
              <Button
                variant="primary"
                onClick={() => void runMutate(true, true)}
                loading={mut.isPending}
              >
                Bis Check-out sperren
              </Button>
            )}
            <Button
              variant="secondary"
              onClick={() => void runMutate(true, false)}
              loading={mut.isPending}
            >
              Dauerhaft sperren
            </Button>
            <Button variant="ghost" onClick={() => setAuswahlOffen(false)}>
              Abbrechen
            </Button>
          </div>
        </div>
      ) : null}

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
    </div>
  );
}
