/**
 * Das Handbuch: Übersicht und Suche (Paket 1).
 *
 * **Eine Server-Komponente, und zwar eine statisch gebaute.** Die Artikel
 * liegen als Dateien im Repo und werden beim **Bauen** gelesen; im
 * fertigen Abbild gibt es den Ordner `content/` nicht mehr (der
 * Standalone-Output kopiert ihn nicht). Würde diese Seite zur Laufzeit
 * gerendert, griffe sie auf eine Datei zu, die es dort nicht gibt — und
 * zwar erst im Betrieb, nicht im Bau.
 *
 * `dynamic = "error"` ist genau dagegen gesetzt: wer hier später
 * `searchParams`, `cookies()` oder `headers()` benutzt, bekommt einen
 * **Bau-Fehler** statt einer Seite, die auf dem Server stirbt. Das ist
 * der Unterschied aus §5.83 — die Zusicherung „die Seite ist statisch"
 * wird auf der Ebene geprüft, auf der sie gelten muss.
 *
 * Der Suchindex geht als Daten in die Seite und wird im Browser
 * durchsucht (`handbuch-suche.tsx`).
 */

import type { Metadata } from "next";
import Link from "next/link";

import { baueSuchIndex, ladeArtikel } from "@/lib/handbuch/artikel";

import { HandbuchSuche } from "./handbuch-suche";

export const dynamic = "error";

export const metadata: Metadata = {
  title: "Handbuch | Heizung Sonnblick",
  description: "Bedienung und Heizlogik der Heizungssteuerung Hotel Sonnblick",
};

export default function HandbuchSeite() {
  const index = baueSuchIndex();
  const artikel = ladeArtikel();

  // Das jüngste Stand-Datum über alle Artikel. Es sagt mehr als das
  // Datum dieser Seite: wer wissen will, ob das Handbuch zum Programm
  // passt, vergleicht es mit dem letzten Merge.
  const stand = artikel
    .map((a) => a.stand)
    .filter((s) => s !== "")
    .sort()
    .at(-1);

  return (
    <div className="p-6 max-w-content mx-auto">
      <header className="mb-6">
        <h1 className="text-2xl font-medium text-text-primary">Handbuch</h1>
        <p className="text-text-secondary mt-1 text-sm">
          Wie das Haus heizt, was jede Seite tut, und was die Rezeption bei
          den sechs häufigen Fällen macht.
          {stand !== undefined ? ` Jüngster Stand: ${stand}.` : null}
        </p>
      </header>

      <div className="mb-6 flex flex-wrap gap-3 nicht-drucken">
        <Link
          href={"/handbuch/heizlogik" as never}
          className="border-border bg-surface hover:border-primary hover:text-primary text-text-secondary rounded-md border px-3 py-2 text-sm transition-colors"
        >
          <span
            className="material-symbols-outlined mr-1 align-[-5px]"
            aria-hidden
            style={{ fontSize: 18 }}
          >
            device_thermostat
          </span>
          Wie das Haus heizt
        </Link>
        <Link
          href="/handbuch/drucken"
          className="border-border bg-surface hover:border-primary hover:text-primary text-text-secondary rounded-md border px-3 py-2 text-sm transition-colors"
        >
          <span
            className="material-symbols-outlined mr-1 align-[-5px]"
            aria-hidden
            style={{ fontSize: 18 }}
          >
            print
          </span>
          Alles zum Ausdrucken
        </Link>
      </div>

      <HandbuchSuche index={index} />
    </div>
  );
}
