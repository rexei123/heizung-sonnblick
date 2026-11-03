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
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useBoostRoom } from "@/lib/api/hooks-overrides";
import type { Room } from "@/lib/api/types";
import { formatTime } from "@/lib/format";

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
            Temperatur · {room.ist_allgemeinbereich ? "Bereich" : "Zimmer"} {room.number}
          </DialogTitle>
          <DialogDescription>
            {room.display_name ? `${room.display_name} · ` : ""}
            Zwei Wege: ein Wert je Heizzone, oder Boost bis zum Nachtbeginn.
            Die Liste dahinter bleibt offen.
          </DialogDescription>
        </DialogHeader>
        <BoostZeile room={room} />
        <ManualOverridePanelList roomId={room.id} kompakt />
      </DialogContent>
    </Dialog>
  );
}


/**
 * Der Boost: **ein** Knopf, der vorher sagt, bis wann.
 *
 * **Warum hier kein Wert und keine Dauer zu wählen ist.** Beides rechnet
 * das Backend — der Wert aus `rule_config.boost_temperature` (oder dem
 * Höchstwert des Gastes), das Ende aus dem Nachtfenster des Zimmers. Ein
 * Feld, das man setzen kann, wird irgendwann gesetzt; der Endpunkt hat
 * deshalb keinen Rumpf.
 *
 * **Die Endzeit steht in der Beschriftung** (Festlegung des Betreibers
 * vom 31.10.2026): „Boost bis 20:00", wobei die Uhrzeit der Nachtbeginn
 * des Hauses ist und mit ihm wandert. Kein Mindestmaß — ein Boost kurz
 * davor endet kurz danach, und der Knopf sagt das vorher. Deshalb darf
 * die Zeit nicht fehlen: ohne sie wäre der Knopf eine Zusage ohne
 * Inhalt.
 *
 * **Geht es nicht, steht der Grund da** und nicht nur ein grauer Knopf
 * (§5.57). Der Satz kommt aus dem Backend, weil dort die Regelkette und
 * der Sommermodus bekannt sind — die Oberfläche soll das nicht
 * nachrechnen (§5.53).
 */
function BoostZeile({ room }: { room: Room }) {
  const boost = useBoostRoom(room.id);
  const bis = room.boost_ende !== null ? formatTime(room.boost_ende) : null;
  const grundId = `boost-grund-${room.id}`;

  return (
    <div
      className="border-border bg-surface-alt flex flex-wrap items-center justify-between gap-3 rounded-md border p-3"
      data-testid="boost-zeile"
    >
      <div className="min-w-0">
        <p className="text-text-primary text-sm font-medium">Boost</p>
        <p className="text-text-tertiary text-xs" data-testid="boost-erklaerung">
          {room.boost_moeglich
            ? bis !== null
              ? `Heizt bis ${bis} auf den Boost-Wert, danach gilt wieder die Nachtregel.`
              : "Heizt bis zum nächsten Wechsel des Nachtfensters."
            : (room.boost_hinweis ?? "Boost ist hier nicht möglich.")}
        </p>
        {!room.boost_moeglich && room.boost_hinweis !== null ? (
          <span id={grundId} className="sr-only">
            {room.boost_hinweis}
          </span>
        ) : null}
      </div>

      {/* Der Grund hängt am umschließenden `span`: ein `disabled`-Knopf
          bekommt aus dem Design-System `pointer-events-none`, ein `title`
          an ihm selbst erschiene nie (dieselbe Stelle wie in der
          Zimmerliste). */}
      <span title={room.boost_moeglich ? undefined : (room.boost_hinweis ?? undefined)}>
        <Button
          variant="secondary"
          icon="local_fire_department"
          onClick={() => boost.mutate()}
          disabled={!room.boost_moeglich || boost.isPending}
          aria-describedby={!room.boost_moeglich && room.boost_hinweis ? grundId : undefined}
          data-testid="boost-knopf"
        >
          {boost.isPending ? "Boost läuft an …" : bis !== null ? `Boost bis ${bis}` : "Boost"}
        </Button>
      </span>

      {boost.isError ? (
        <p className="text-error w-full text-xs" data-testid="boost-fehler">
          {boost.error instanceof Error ? boost.error.message : "Boost fehlgeschlagen."}
        </p>
      ) : null}
      {boost.isSuccess ? (
        <p className="text-success w-full text-xs" data-testid="boost-erfolg">
          Boost läuft{bis !== null ? ` bis ${bis}` : ""}.
        </p>
      ) : null}
    </div>
  );
}
