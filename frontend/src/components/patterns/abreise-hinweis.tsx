/**
 * Hinweis „Abreise überschritten" auf dem Dashboard (27.11.2026).
 *
 * **Der Fall steht seit dem 25.10.2026 im Handbuch** (Artikel „Abreise
 * verschiebt sich"): ein Gast bleibt länger, niemand ändert das
 * Abreisedatum, und die Steuerung setzt das Zimmer am ursprünglichen
 * Abreisetag auf frei. Der Gast kommt abends in ein kühles Zimmer
 * zurück, obwohl niemand etwas falsch gemacht hat.
 *
 * Das Handbuch sagt, was zu tun ist. Es sagt nicht, **wann** — und genau
 * da fällt der Fall durch: wer das Datum vergisst, liest den Artikel
 * nicht. Deshalb steht der Hinweis dort, wo die Rezeption ohnehin
 * hinsieht.
 *
 * **Oben, nicht als Kachel.** Eine Kachel mit „3" wäre auf dieser Seite
 * nicht handlungsfähig — die Rezeption müsste danach 47 Belegungen
 * durchsehen, um die drei zu finden. Der Hinweis nennt die Zimmer und
 * verlinkt die Liste.
 *
 * **Er verschwindet von selbst.** Keine Liste, die man wegklicken muss:
 * eine Abreise verlässt das Fenster nach 24 Stunden, und eine
 * verlängerte Belegung nimmt das Zimmer sofort heraus. Ein Hinweis, den
 * man schließen kann, ist am dritten Tag geschlossen.
 */

import Link from "next/link";

import type { AbreiseZimmer } from "@/lib/api/types";

/** „vor 3 h" / „in dieser Stunde" — die Form, in der jemand es liest. */
function seit(stunden: number): string {
  if (stunden <= 0) return "in dieser Stunde";
  if (stunden === 1) return "vor 1 Stunde";
  return `vor ${stunden} Stunden`;
}

/**
 * Was die Spur bedeutet, in einem Halbsatz.
 *
 * `null` für `keines`: dort steht **nichts**, und das ist richtig. Ein
 * „keine Spur" hinter jedem Zimmer wäre eine Beruhigung, für die es
 * keinen Grund gibt — die meisten Gäste drehen nicht am Thermostat.
 */
function spur(zeichen: AbreiseZimmer["zeichen"]): string | null {
  if (zeichen === "drehrad") return "jemand hat am Thermostat gedreht";
  if (zeichen === "uebersteuerung") return "Wunschtemperatur gesetzt";
  return null;
}

export function AbreiseHinweis({ zimmer }: { zimmer: AbreiseZimmer[] }) {
  if (zimmer.length === 0) return null;

  // Zimmer mit einer Spur zuerst: dort ist der Verdacht belegt und nicht
  // nur möglich. Die Reihenfolge innerhalb der Gruppen bleibt die des
  // Servers (jüngste Abreise zuerst).
  const sortiert = [...zimmer].sort((a, b) => {
    const gewicht = (z: AbreiseZimmer) => (z.zeichen === "keines" ? 1 : 0);
    return gewicht(a) - gewicht(b);
  });

  return (
    <section
      className="border-warning/40 bg-warning-soft mb-6 rounded-lg border p-4"
      data-testid="abreise-hinweis"
      aria-labelledby="abreise-hinweis-titel"
    >
      <h2
        id="abreise-hinweis-titel"
        className="text-text-primary text-sm font-medium"
      >
        Abreise überschritten — sind diese Zimmer noch belegt?
      </h2>
      <p className="text-text-secondary mt-1 text-sm">
        Die Abreise ist vorbei, eine neue Belegung steht nicht. Bleibt ein Gast
        länger, heizt das Zimmer nur weiter, wenn die{" "}
        <Link href={"/belegungen" as never} className="underline">
          Abreise in der Belegung
        </Link>{" "}
        nachgezogen wird.
      </p>
      <ul className="mt-3 space-y-1 text-sm">
        {sortiert.map((z) => {
          const hinweis = spur(z.zeichen);
          return (
            <li key={z.room_id} data-testid={`abreise-hinweis-${z.room_id}`}>
              <Link
                href={`/zimmer/${z.room_id}` as never}
                className="text-text-primary font-medium underline"
              >
                {z.zimmer}
              </Link>
              <span className="text-text-secondary">
                {" "}
                — {seit(z.stunden_her)}
              </span>
              {hinweis ? (
                <span className="text-text-primary font-medium">
                  {" "}
                  · {hinweis}
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
