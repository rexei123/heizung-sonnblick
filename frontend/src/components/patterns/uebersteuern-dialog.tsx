"use client";

/**
 * Übersteuern aus der Zimmerliste, ohne Seitenwechsel (30.10.2026).
 *
 * **Der Inhalt ist der Übersteuerungs-Reiter selbst**, nicht eine zweite,
 * schlankere Eingabe daneben: `ManualOverridePanelList` wird eingebettet,
 * mit `kompakt`. Damit gilt in der Liste genau das, was auf der Zimmerseite
 * gilt — die Karte je Heizzone, das Häkchen aus T4-A2 mit seinen Regeln,
 * die Sperr-Banner, die Fenster-Blockade. Ein Nachbau hätte all das
 * doppelt, und ab dem nächsten Sprint verschieden (§5.53).
 *
 * **Warum das Einbetten hier geht** (§5.69 verlangt den Sub-Audit vorher):
 *
 * | Geprüft | Befund |
 * |---|---|
 * | eigene Karten-Umrandung | keine. Die Liste ist ein `space-y-6`, die Umrandungen sitzen an den Karten darin — kein Karte-in-Karte |
 * | eigene Überschrift | ja, und sie wäre neben dem Dialog-Titel die zweite. Deshalb `kompakt` |
 * | Daten vom Eltern-Teil | **keine.** Die Liste holt Zonen, Trace, Übersteuerungen und Zimmer selbst, allein aus `roomId` |
 *
 * Der dritte Punkt ist der Grund, warum hier eingebettet und nicht
 * verlinkt wird. In Sprint 14b lag der Fall anders: dort hätte die
 * aufnehmende Karte `isWindowOpen` und `lastEvalTime` beschaffen und
 * durchreichen müssen, und das wäre ein Daten-Duplikat geworden — deshalb
 * stand am Ende ein Link. Diese Komponente braucht nichts durchgereicht.
 *
 * **Der Dialog schließt sich nach dem Abschicken nicht von selbst.** Das
 * Formular meldet seinen Erfolg nicht nach außen, und es müsste dafür
 * umgebaut werden; wichtiger aber: was danach dasteht, ist die Antwort —
 * die Karte zeigt den gesetzten Wert mit Restzeit. Ein Dialog, der im
 * Moment des Erfolgs verschwindet, nimmt die Bestätigung mit. Die Spalte
 * dahinter ist zu diesem Zeitpunkt schon nachgezogen
 * (`useCreateRoomOverride` verwirft auch `["rooms"]`).
 */

import { ManualOverridePanelList } from "@/components/patterns/manual-override-panel-list";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Room } from "@/lib/api/types";

interface Props {
  /** Das Zimmer, oder `null` — dann ist der Dialog zu und lädt nichts. */
  room: Room | null;
  onClose: () => void;
}

export function UebersteuernDialog({ room, onClose }: Props) {
  // Radix montiert den Inhalt erst beim Öffnen; zusätzlich hängt die
  // Komponente an `room !== null`. Ohne das zweite stünden 104 Dialoge in
  // der Seite, von denen 103 nie geöffnet werden.
  if (room === null) {
    return null;
  }

  return (
    <Dialog
      open
      onOpenChange={(offen) => {
        if (!offen) onClose();
      }}
    >
      <DialogContent
        className="max-w-2xl max-h-[85vh] overflow-y-auto"
        data-testid="uebersteuern-dialog"
      >
        <DialogHeader>
          <DialogTitle>
            {room.ist_allgemeinbereich ? "Bereich" : "Zimmer"} {room.number} übersteuern
          </DialogTitle>
          <DialogDescription>
            {room.display_name ? `${room.display_name} · ` : ""}
            Der Wert wird je Heizzone gesetzt. Die Liste dahinter bleibt offen.
          </DialogDescription>
        </DialogHeader>
        <ManualOverridePanelList roomId={room.id} kompakt />
      </DialogContent>
    </Dialog>
  );
}
