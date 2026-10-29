/**
 * Das ganze Handbuch auf einer Seite, zum Ausdrucken (Paket 1).
 *
 * **Warum es diese Seite gibt.** An der Rezeption hängt ein Ordner. Wer
 * im Jänner um drei Uhr morgens nachsehen muss, warum ein Zimmer kalt
 * ist, hat vielleicht kein Gerät zur Hand — und wenn die Steuerung
 * selbst das Problem ist, hat er das Handbuch erst recht nicht.
 *
 * **Die lebenden Werte fehlen hier bewusst.** `{{werte}}` und `{{karte}}`
 * sind Platzhalter, die im Browser Daten holen; auf Papier wären sie eine
 * Momentaufnahme mit dem Anspruch einer Tabelle. Statt der Werte steht
 * ein Satz, wo sie zu finden sind — die gedruckte Fassung sagt damit von
 * sich aus, was sie nicht weiß (§5.77 in Papierform).
 *
 * Die Karte der Heizlogik wird gedruckt: sie zeigt die Reihenfolge der
 * Schichten, und die ändert sich nicht mit einem Sollwert.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { HandbuchInhalt } from "@/components/patterns/handbuch-inhalt";
import { ladeArtikel } from "@/lib/handbuch/artikel";

export const dynamic = "error";

export const metadata: Metadata = {
  title: "Handbuch zum Ausdrucken | Heizung Sonnblick",
};

export default function DruckSeite() {
  const artikel = ladeArtikel();
  const stand = artikel
    .map((a) => a.stand)
    .filter((s) => s !== "")
    .sort()
    .at(-1);

  return (
    <div className="p-6 max-w-content mx-auto">
      <nav className="mb-4 text-sm nicht-drucken" aria-label="Zurück zum Handbuch">
        <Link href="/handbuch" className="text-primary hover:underline">
          ← Handbuch
        </Link>
      </nav>

      <header className="mb-8">
        <h1 className="text-2xl font-medium text-text-primary">
          Handbuch Heizungssteuerung Hotel Sonnblick
        </h1>
        <p className="text-text-secondary mt-1 text-sm">
          Alle {artikel.length} Artikel, Stand {stand ?? "—"}. Die aktuellen
          Temperaturen und Zeiten stehen nicht auf Papier — sie sind in der
          Software unter „Temperaturen &amp; Zeiten" und auf jeder
          Raumtyp-Seite zu sehen.
        </p>
        <p className="text-text-tertiary mt-2 text-xs nicht-drucken">
          Mit Strg+P drucken. Seitenleiste, Suchfeld und Verweise werden
          dabei weggelassen.
        </p>
      </header>

      <nav className="mb-8" aria-label="Inhaltsverzeichnis">
        <h2 className="text-text-primary mb-2 text-lg font-medium">Inhalt</h2>
        <ol className="text-text-secondary ml-5 list-decimal space-y-1 text-sm">
          {artikel.map((a) => (
            <li key={a.slug}>
              <a href={`#artikel-${a.slug}`} className="hover:underline">
                {a.titel}
              </a>
              <span className="text-text-tertiary"> — {a.kategorie}</span>
            </li>
          ))}
        </ol>
      </nav>

      {artikel.map((a) => (
        <article
          key={a.slug}
          id={`artikel-${a.slug}`}
          className="handbuch-druck-artikel border-border mb-8 border-t pt-6"
        >
          <p className="text-text-tertiary text-xs">{a.kategorie}</p>
          <h2 className="text-text-primary mb-1 text-xl font-medium">{a.titel}</h2>
          <p className="text-text-tertiary mb-4 text-xs">
            Stand {a.stand === "" ? "— ohne Datum" : a.stand}
          </p>
          <HandbuchInhalt blöcke={a.blöcke} drucken />
        </article>
      ))}
    </div>
  );
}
