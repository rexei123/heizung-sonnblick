"use client";

/**
 * Zimmer-Liste (Sprint 8.10, Sprint 8.15 Design-Fixes).
 */

import Link from "next/link";
import { useState } from "react";

import { RoomForm } from "@/components/patterns/room-form";
import { UebersteuernDialog } from "@/components/patterns/uebersteuern-dialog";
import { Button } from "@/components/ui/button";
import { useRoomTypes } from "@/lib/api/hooks-room-types";
import { useCreateRoom, useRooms } from "@/lib/api/hooks-rooms";
import { useAuth } from "@/contexts/auth-context";
import { darfStammdatenAendern, darfTemperaturAendern } from "@/lib/auth/rechte";
import { formatTemperature } from "@/lib/format";
import { uebersteuerungslage } from "@/lib/uebersteuerung";
import type {
  ApiError,
  Room,
  RoomCreate,
  RoomStatus,
  RoomUpdate,
} from "@/lib/api/types";

const STATUS_LABEL: Record<RoomStatus, string> = {
  vacant: "Frei",
  occupied: "Belegt",
  reserved: "Reserviert",
  cleaning: "Reinigung",
  blocked: "Gesperrt",
};

const STATUS_COLOR: Record<RoomStatus, string> = {
  vacant: "text-text-tertiary",
  occupied: "text-success",
  reserved: "text-warning",
  cleaning: "text-warning",
  blocked: "text-error",
};

/**
 * Sprint 24d: ein Allgemeinbereich hat keinen Belegungsstatus.
 *
 * Bar, Rezeption und Spa standen bis hierher als „Frei" in der Liste —
 * und „frei" heißt bei einem Zimmer „kein Gast drin". Bei einer Bar ist
 * das keine Auskunft, sondern eine Verwechslung: der Bereich ist nicht
 * leer, er hat Betrieb. Der Belegungsabgleich lässt die Spalte dort
 * seither unberührt (`occupancy_service.sync_room_status`).
 *
 * **„Reinigung" und „Gesperrt" gewinnen trotzdem**, und das ist der
 * Punkt: beide heißen „Automatik angehalten", und ein Bereich kann außer
 * Betrieb sein. Wer sie hinter der Bereichs-Marke verstecken würde,
 * nähme dem Bereich genau die Anzeige, die ein Eingreifen auslöst.
 */
function statusAnzeige(r: Room): { text: string; klasse: string } {
  if (r.status === "cleaning" || r.status === "blocked") {
    return { text: STATUS_LABEL[r.status], klasse: STATUS_COLOR[r.status] };
  }
  if (r.ist_allgemeinbereich) {
    return { text: "Allgemeinbereich", klasse: "text-text-secondary" };
  }
  return { text: STATUS_LABEL[r.status], klasse: STATUS_COLOR[r.status] };
}

export default function ZimmerPage() {
  const [filterRoomTypeId, setFilterRoomTypeId] = useState<number | "">("");
  const [filterStatus, setFilterStatus] = useState<RoomStatus | "">("");
  const [filterFloor, setFilterFloor] = useState<string>("");
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const roomTypes = useRoomTypes();
  const list = useRooms({
    room_type_id: filterRoomTypeId === "" ? undefined : filterRoomTypeId,
    status: filterStatus === "" ? undefined : filterStatus,
    floor: filterFloor.trim() === "" ? undefined : parseInt(filterFloor, 10),
  });
  // Sprint 22 T5: `POST /rooms` ist `require_admin` (`api/v1/rooms.py:80`).
  const { user } = useAuth();
  const darfAendern = darfStammdatenAendern(user);
  const createMut = useCreateRoom();

  const handleCreate = async (payload: RoomCreate | RoomUpdate) => {
    setError(null);
    try {
      await createMut.mutateAsync(payload as RoomCreate);
      setShowCreate(false);
    } catch (e) {
      setError(toMessage(e));
    }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-medium text-text-primary">Zimmer</h1>
          <p className="text-sm text-text-secondary mt-1">
            {list.data?.length ?? 0} Zimmer angezeigt.
          </p>
        </div>
        {!darfAendern ? null : showCreate ? (
          <Button variant="secondary" onClick={() => setShowCreate(false)}>
            Abbrechen
          </Button>
        ) : (
          <Button
            variant="add"
            icon="add"
            onClick={() => {
              setError(null);
              setShowCreate(true);
            }}
          >
            Neues Zimmer
          </Button>
        )}
      </header>

      {showCreate ? (
        <div className="bg-surface border border-border rounded-md p-5 mb-6">
          <h2 className="text-lg font-medium text-text-primary mb-4">Neues Zimmer</h2>
          <RoomForm
            onSubmit={handleCreate}
            onCancel={() => setShowCreate(false)}
            submitting={createMut.isPending}
            error={error}
          />
        </div>
      ) : null}

      <div className="bg-surface border border-border rounded-md p-4 mb-4 grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div>
          <label className="block text-xs text-text-secondary mb-1">Raumtyp</label>
          <select
            value={filterRoomTypeId}
            onChange={(e) =>
              setFilterRoomTypeId(e.target.value === "" ? "" : parseInt(e.target.value, 10))
            }
            className="w-full px-2 py-1.5 border border-border rounded-md bg-surface text-sm"
          >
            <option value="">Alle</option>
            {(roomTypes.data ?? []).map((rt) => (
              <option key={rt.id} value={rt.id}>
                {rt.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-text-secondary mb-1">Status</label>
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus((e.target.value || "") as RoomStatus | "")}
            className="w-full px-2 py-1.5 border border-border rounded-md bg-surface text-sm"
          >
            <option value="">Alle</option>
            <option value="vacant">Frei</option>
            <option value="occupied">Belegt</option>
            <option value="reserved">Reserviert</option>
            <option value="cleaning">Reinigung</option>
            <option value="blocked">Gesperrt</option>
          </select>
        </div>
        <div>
          <label className="block text-xs text-text-secondary mb-1">Etage</label>
          <input
            type="number"
            value={filterFloor}
            onChange={(e) => setFilterFloor(e.target.value)}
            placeholder="Alle"
            className="w-full px-2 py-1.5 border border-border rounded-md bg-surface text-sm"
          />
        </div>
      </div>

      <RoomTable list={list.data ?? []} loading={list.isLoading} error={list.isError} />
    </div>
  );
}

/**
 * „Das Zimmer ist deutlich kaelter als es sein soll" — die Bedingung der
 * Hervorhebung (15.10.2026).
 *
 * **Mehr als 2 °C**, also echt groesser: bei genau 2,0 K bleibt die Zahl
 * grau. Die Grenze ist eine Betriebsentscheidung des Hoteliers, keine
 * Herleitung — und sie ist **kein Alarm**. Ein Zimmer kann aus guten
 * Gruenden kalt sein (gerade angereist, Vorheizen laeuft noch), deshalb
 * faerbt die Zelle und schickt keine Mail.
 *
 * Fehlt einer der beiden Werte, gibt es keinen Vergleich — und damit auch
 * keine Hervorhebung. Eine Faerbung „weil nichts da ist" waere eine
 * Aussage ueber ein Zimmer, ueber das wir nichts wissen.
 */
function zuKalt(ist: number | null, soll: number | null): boolean {
  if (ist === null || soll === null) return false;
  return soll - ist > 2;
}

interface TableProps {
  list: Room[];
  loading: boolean;
  error: boolean;
}

/**
 * Die Zeilen-Knöpfe, seit dem 30.10.2026 zwei echte statt eines Links.
 *
 * Der häufigste Handgriff der Rezeption ist „Wert setzen", und er lag
 * hinter zwei Klicks und einem Seitenwechsel: „Detail →", dann der Reiter
 * Übersteuerung. Dieselbe Verlegung wie in Sprint 21 A2 auf der
 * Zimmerseite, eine Ebene höher.
 *
 * **Beide sind `secondary` bzw. `ghost`, keiner ist `primary`.** Das
 * Design-System lässt einen Haupt-Knopf je Region zu (§6.1), und bei 104
 * Zeilen wären das 104 — die Seite hätte dann keinen Schwerpunkt mehr,
 * sondern 104 davon. Die Reihenfolge trägt die Gewichtung: „Übersteuern"
 * steht links mit Umrandung, „Details" rechts als Text, so wie der Link
 * vorher aussah.
 */
function RoomTable({ list, loading, error }: TableProps) {
  // Sprint 22 T5 / `rechte.ts`: `POST /rooms/{id}/overrides` ist
  // `require_mitarbeiter`. Wer nicht darf, sieht den Knopf nicht — statt
  // ihn zu sehen und 403 zu bekommen.
  const { user } = useAuth();
  const darfTemperatur = darfTemperaturAendern(user);
  // Ein Dialog für die ganze Tabelle, nicht einer je Zeile. Welches
  // Zimmer offen ist, steht hier; `null` heißt zu.
  const [offenesZimmer, setOffenesZimmer] = useState<Room | null>(null);

  if (loading) {
    return (
      <div className="bg-surface border border-border rounded-md p-4 text-sm text-text-secondary">
        Lade…
      </div>
    );
  }
  if (error) {
    return (
      <div className="bg-surface border border-border rounded-md p-4 text-sm text-error">
        Fehler beim Laden.
      </div>
    );
  }
  if (list.length === 0) {
    return (
      <div className="bg-surface border border-border rounded-md p-4 text-sm text-text-secondary">
        Keine Zimmer mit diesen Filtern.
      </div>
    );
  }
  return (
    /* Die zwei Knoepfe machen die Zeile breiter als ein Link.
       `overflow-x-auto` statt `overflow-hidden`, damit am Handy gescrollt
       und nicht abgeschnitten wird (§5.66, gleiche Klasse wie die
       Geraeteliste). */
    <div className="bg-surface border border-border rounded-md overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-alt border-b border-border">
          <tr>
            <th className="text-left px-3 py-2 font-medium text-text-secondary">Nummer</th>
            <th className="text-left px-3 py-2 font-medium text-text-secondary">Etage</th>
            <th className="text-left px-3 py-2 font-medium text-text-secondary">Orient.</th>
            <th className="text-left px-3 py-2 font-medium text-text-secondary">Status</th>
            {/* Ist und Soll der Referenzzone (15.10.2026). Sichtbarer
                Header-Text, auch wenn die Spalte schmal ist (§5.57). */}
            <th className="text-left px-3 py-2 font-medium text-text-secondary">Ist</th>
            <th className="text-left px-3 py-2 font-medium text-text-secondary">Soll</th>
            {/* Sprint 12c.a: Block-Indikator-Spalte. Live-Verify-Befund 12c.a:
                Header braucht sichtbaren Text — Tooltip allein ist semantisch
                blind, weil er nur beim Hover greift. */}
            <th className="text-left px-3 py-2 font-medium text-text-secondary">
              Übersteuerung
            </th>
            {/* §5.57: eine Spalte mit Handlungen am Tabellen-Ende darf
                ohne sichtbaren Kopf stehen — aber nicht ohne Kopf. */}
            <th className="text-right px-3 py-2 font-medium text-text-secondary">
              <span className="sr-only">Aktionen</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {list.map((r) => (
            <tr key={r.id} className="border-b border-border last:border-b-0 hover:bg-surface-alt">
              <td className="px-3 py-2">
                <Link
                  href={`/zimmer/${r.id}` as never}
                  className="font-medium text-text-primary hover:text-primary"
                >
                  {r.number}
                </Link>
                {r.display_name ? (
                  <div className="text-xs text-text-tertiary">{r.display_name}</div>
                ) : null}
              </td>
              <td className="px-3 py-2 text-text-secondary">{r.floor ?? "—"}</td>
              <td className="px-3 py-2 text-text-secondary">{r.orientation ?? "—"}</td>
              <td className="px-3 py-2">
                <span
                  className={statusAnzeige(r).klasse}
                  data-testid="zimmer-status"
                  data-allgemeinbereich={r.ist_allgemeinbereich ? "true" : "false"}
                >
                  {statusAnzeige(r).text}
                </span>
                {/* Sprint 22 T7: „Reinigung" und „Gesperrt" halten den
                    Belegungs-Abgleich an (`occupancy_service.py:242`). Das
                    stand bisher nirgends — ein angehaltenes Zimmer sah aus
                    wie jedes andere. */}
                {r.status === "cleaning" || r.status === "blocked" ? (
                  <span className="ml-2 text-xs text-warning">· Automatik angehalten</span>
                ) : null}
              </td>
              {/* Ist der Referenzzone. `formatTemperature` liefert „–" bei
                  `null` — kein Gerät, kein Messwert oder kein Schlafzimmer
                  sehen in der Zeile gleich aus, und das ist richtig: die
                  Spalte sagt „kein Wert", nicht warum. Das Warum steht im
                  Zimmer. */}
              <td className="px-3 py-2">
                <span
                  className={
                    zuKalt(r.mean_temperature_c, r.engine_setpoint_c)
                      ? "text-info font-medium"
                      : "text-text-secondary"
                  }
                  data-testid={`ist-${r.number}`}
                >
                  {formatTemperature(r.mean_temperature_c)}
                </span>
              </td>
              <td className="px-3 py-2 text-text-secondary" data-testid={`soll-${r.number}`}>
                {formatTemperature(r.engine_setpoint_c)}
              </td>
              {/* **Schloss und Übersteuerung stehen zusammen**, seit dem
                  31.10.2026 (Befund des Betreibers aus dem Rad-Test).

                  Hier stand: „EINE Zelle, drei exklusive Zustände —
                  gesperrt > aktive Übersteuerung > leer. Nie kombiniert."
                  (Sprint 14d R-B.) Das war richtig, solange die Sperre
                  jede Übersteuerung ausschloss: der Sperr-Knopf hebt beim
                  Sperren alle laufenden auf, danach konnte es keine geben.

                  Mit dem Häkchen aus T4-A2 ist die Kombination der
                  **Regelfall** — der ganze Zweck ist „Wert setzen und
                  gleich festhalten". In Zimmer 107 stand deshalb nur ein
                  Schloss, während 23 °C bis Check-out galten, und die
                  Spalte verschwieg genau die Zahl, nach der man sie
                  fragt. */}
              <td className="px-3 py-2">
                <span className="inline-flex items-center gap-2">
                  {r.guest_override_blocked ? (
                    <span
                      className="material-symbols-outlined text-text-secondary"
                      aria-label="Übersteuerung gesperrt"
                      title="Übersteuerung gesperrt"
                      style={{ fontSize: 18 }}
                      data-testid={`sperre-${r.number}`}
                    >
                      lock
                    </span>
                  ) : null}
                  {r.has_active_override ? (
                    <span
                      className="inline-flex items-center gap-1 text-warning"
                      aria-label="Übersteuerung aktiv"
                      title="Übersteuerung aktiv"
                      data-testid={`uebersteuerung-aktiv-${r.number}`}
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
                        tune
                      </span>
                      <span className="text-xs font-medium">Aktiv</span>
                    </span>
                  ) : null}
                </span>
              </td>
              <td className="px-3 py-2">
                <ZeilenKnoepfe
                  room={r}
                  darfTemperatur={darfTemperatur}
                  onUebersteuern={() => setOffenesZimmer(r)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {/* Radix hängt den Inhalt in einen Portal am Seitenende ein — der
          Dialog steht hier also im Markup, aber nicht in der Tabelle. */}
      <UebersteuernDialog room={offenesZimmer} onClose={() => setOffenesZimmer(null)} />
    </div>
  );
}

interface ZeilenKnoepfeProps {
  room: Room;
  darfTemperatur: boolean;
  onUebersteuern: () => void;
}

/**
 * Zwei Knöpfe, und bei einem von beiden ein Grund.
 *
 * **Am Handy nur die Symbole.** Die Beschriftung liegt in einem
 * `hidden sm:inline` — weg ist sie damit nur fürs Auge: `aria-label` und
 * `title` tragen den Text in jeder Breite, sonst hätte die Rezeption am
 * Telefon zwei Symbole ohne Namen (§5.57, eine Ebene kleiner).
 *
 * **Warum der Grund an einem umschließenden `span` hängt.** Ein
 * `disabled`-Knopf bekommt aus dem Design-System `pointer-events-none` —
 * ein `title` an ihm selbst würde nie erscheinen, also genau dort nicht,
 * wo er gebraucht wird. Der Umschlag bekommt die Maus-Ereignisse
 * stattdessen; für Vorleseprogramme steht derselbe Satz als
 * `aria-describedby` daneben. Zwei Wege, weil keiner allein beide
 * Benutzergruppen erreicht.
 */
function ZeilenKnoepfe({ room, darfTemperatur, onUebersteuern }: ZeilenKnoepfeProps) {
  const lage = uebersteuerungslage(room);
  const grundId = `uebersteuern-grund-${room.id}`;

  return (
    <div className="flex items-center justify-end gap-1">
      {darfTemperatur ? (
        <span title={lage.hinweis ?? "Übersteuern"}>
          <Button
            variant="secondary"
            icon="tune"
            className="px-3 sm:px-4"
            onClick={onUebersteuern}
            disabled={!lage.erlaubt}
            aria-label={`Zimmer ${room.number} übersteuern`}
            aria-describedby={lage.hinweis ? grundId : undefined}
            data-testid={`uebersteuern-${room.number}`}
          >
            <span className="hidden sm:inline">Übersteuern</span>
          </Button>
          {lage.hinweis ? (
            <span id={grundId} className="sr-only">
              {lage.hinweis}
            </span>
          ) : null}
        </span>
      ) : null}
      {/* `asChild` schaltet die Icon-Logik des Knopfs ab (Slot nimmt genau
          ein Kind) — das Zeichen steht deshalb im Link, und zwar hinter
          der Beschriftung: ein Pfeil nach rechts vor dem Wort zeigt in die
          falsche Richtung. */}
      <Button variant="ghost" className="px-3 sm:px-4" asChild>
        <Link
          href={`/zimmer/${room.id}` as never}
          aria-label={`Details zu Zimmer ${room.number}`}
          data-testid={`details-${room.number}`}
        >
          <span className="hidden sm:inline">Details</span>
          <span className="material-symbols-outlined" style={{ fontSize: 18 }} aria-hidden>
            chevron_right
          </span>
        </Link>
      </Button>
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
