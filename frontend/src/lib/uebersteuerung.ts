/**
 * Darf hier übersteuert werden? — eine Quelle für die Oberfläche
 * (30.10.2026).
 *
 * **Was diese Datei nicht ist: ein Gate.** Abgewiesen wird im Dienst, und
 * zwar auch dann, wenn niemand einen Knopf gesehen hat. Sie entscheidet,
 * ob ein Knopf *drückbar* ist und welcher Satz daneben steht.
 *
 * Der Zweck ist §5.53 in Kleinformat. Bis hierher stand dieselbe Regel an
 * **drei** Stellen: in der Kopfzeile der Zimmerseite (`istBelegt ||
 * istBereich`), in den Bannern des Übersteuerungs-Reiters und — mit dem
 * Knopf in der Zimmerliste — beinahe ein drittes Mal. Drei Kopien einer
 * Regel laufen beim ersten Nachjustieren auseinander, und zwar stumm: die
 * Liste graut dann etwas aus, das die Zimmerseite anbietet, und der Dienst
 * hält eine dritte Meinung.
 *
 * **Das Vorbild ist `lib/auth/rechte.ts`:** jede Aussage nennt die Stelle
 * im Dienst, die sie spiegelt. Wer das Gate ändert, findet über diese
 * Datei die Oberfläche dazu — und umgekehrt. Ohne die Fundstellen wäre das
 * hier die zweite Wahrheit, die es verhindern soll.
 *
 * Gespiegelt wird `override_service.create`
 * (`backend/src/heizung/services/override_service.py`):
 *
 * | Zeile | Gate | hier |
 * |---|---|---|
 * | 501-504 | `guest_override_blocked` **und nicht** (`bis_checkout` und `frontend_*`) | `sperreDauerhaft` |
 * | 524-534 | Allgemeinbereich geht am Belegungs-Gate **vorbei** (Quelle `frontend_bereich`) | `istBereich` hebt `nichtBelegt` auf |
 * | 533-535 | sonst: `derive_room_status() != OCCUPIED` | `nichtBelegt` |
 */

import type { Room } from "@/lib/api/types";

/** Die Felder, aus denen die Lage folgt — mehr braucht niemand zu laden. */
export type Zimmerlage = Pick<
  Room,
  "status" | "guest_override_blocked" | "guest_block_bis_checkout" | "ist_allgemeinbereich"
>;

export type Uebersteuerungsgrund = "dauerhaft_gesperrt" | "nicht_belegt";

export interface Uebersteuerungslage {
  /** Darf die Rezeption hier einen Wert setzen? */
  erlaubt: boolean;
  /** Warum nicht — `null`, wenn erlaubt. */
  grund: Uebersteuerungsgrund | null;
  /**
   * Der Satz für Tooltip und `aria-describedby`. Er nennt den **Zustand
   * des Zimmers**, nicht die Regel: „Zimmer ist nicht belegt" sagt dem
   * Personal, was zu tun ist, „Gate ROOM_NOT_OCCUPIED" nicht.
   */
  hinweis: string | null;
  /**
   * Die **dauerhafte** Sperre. Sie nimmt das Formular weg (Sprint 12c) und
   * ist der einzige Grund, der auch einen Allgemeinbereich trifft.
   */
  sperreDauerhaft: boolean;
  /**
   * Die Sperre **bis Check-out** (Sprint 23 T4-A2). Sie nimmt dem *Gast*
   * das Rad, nicht der Rezeption die Eingabe — deshalb bleibt `erlaubt`
   * dabei `true`, genau wie das Gate im Dienst die `frontend_*`-Quellen
   * durchlässt.
   */
  sperreBisCheckout: boolean;
  /** Belegungs-Gate greift: nicht belegt **und** kein Allgemeinbereich. */
  nichtBelegt: boolean;
  /** Zimmer mit nicht buchbarem Raumtyp (Bar, Rezeption, Spa). */
  istBereich: boolean;
}

const FREI: Uebersteuerungslage = {
  erlaubt: true,
  grund: null,
  hinweis: null,
  sperreDauerhaft: false,
  sperreBisCheckout: false,
  nichtBelegt: false,
  istBereich: false,
};

/**
 * Die Lage eines Zimmers.
 *
 * `undefined` heißt **noch nicht geladen** und blockiert nichts. Das ist
 * Absicht und stand so schon im Übersteuerungs-Reiter: wer während des
 * ersten Ladens sperrt, lässt bei jedem Seitenaufruf einen Hinweis
 * aufblitzen, der gleich wieder verschwindet — und das liest sich wie ein
 * Fehler. In der Zimmerliste tritt der Fall nicht auf, die Zeilen kommen
 * aus derselben Antwort.
 */
export function uebersteuerungslage(room: Zimmerlage | undefined): Uebersteuerungslage {
  if (room === undefined) {
    return FREI;
  }

  const gesperrt = room.guest_override_blocked === true;
  const bisCheckout = room.guest_block_bis_checkout === true;
  const sperreDauerhaft = gesperrt && !bisCheckout;
  const sperreBisCheckout = gesperrt && bisCheckout;
  const istBereich = room.ist_allgemeinbereich === true;
  const nichtBelegt = room.status !== "occupied" && !istBereich;

  // Reihenfolge wie im Reiter und im Dienst: die Sperre zuerst. Sie ist
  // der bewusste Handgriff eines Mitarbeiters und hat deshalb Vorrang vor
  // einem Zustand, der sich mit dem nächsten Check-in von selbst löst.
  if (sperreDauerhaft) {
    return {
      erlaubt: false,
      grund: "dauerhaft_gesperrt",
      hinweis: "Übersteuerung gesperrt — bitte zuerst die Sperre aufheben",
      sperreDauerhaft,
      sperreBisCheckout,
      nichtBelegt,
      istBereich,
    };
  }

  if (nichtBelegt) {
    return {
      erlaubt: false,
      grund: "nicht_belegt",
      // **Nicht „Zimmer ist frei".** „Frei" ist einer von vier Status, die
      // hier landen; ein Zimmer in Reinigung ist nicht frei, und ein
      // reserviertes erst recht nicht. Der Satz nennt deshalb die
      // Bedingung und nicht einen der Status.
      hinweis: "Zimmer ist nicht belegt — Übersteuern nur bei belegten Zimmern",
      sperreDauerhaft,
      sperreBisCheckout,
      nichtBelegt,
      istBereich,
    };
  }

  return {
    erlaubt: true,
    grund: null,
    hinweis: null,
    sperreDauerhaft,
    sperreBisCheckout,
    nichtBelegt,
    istBereich,
  };
}
