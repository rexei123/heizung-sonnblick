/**
 * Die Anzeige eines Handbuch-Artikels (Paket 1).
 *
 * **Kein `dangerouslySetInnerHTML`.** Der Parser liefert einen
 * typisierten Baum, und diese Datei macht React-Elemente daraus. Es gibt
 * damit keine Stelle, an der Text aus einer Datei als HTML in die Seite
 * gelangt.
 *
 * **Jede `##`-Überschrift trägt ihren Anker** und beim Darüberfahren ein
 * `#` zum Kopieren. Das ist der Direktlink auf einen Abschnitt, den der
 * Auftrag verlangt — und der Grund, warum die Suche auf Abschnitte
 * verlinken kann.
 *
 * **Druck:** die Klassen `handbuch-artikel` und `nicht-drucken` steuern
 * das Druckbild (`globals.css`). Gedruckt wird der Text, nicht die
 * Bedienung: Suchfeld, Seitenleiste und Anker-Zeichen verschwinden.
 */

import Link from "next/link";
import type { Route } from "next";

import { LebendeWerte } from "@/components/patterns/handbuch-werte";
import { HeizlogikKarte } from "@/components/patterns/heizlogik-karte";
import type { Block, InlineTeil } from "@/lib/handbuch/markdown";

function Inline({ teile }: { teile: InlineTeil[] }) {
  return (
    <>
      {teile.map((teil, i) => {
        switch (teil.art) {
          case "fett":
            return (
              <strong key={i} className="font-medium text-text-primary">
                {teil.text}
              </strong>
            );
          case "code":
            return (
              <code
                key={i}
                className="bg-surface-alt rounded-sm px-1 py-0.5 font-mono text-[0.9em]"
              >
                {teil.text}
              </code>
            );
          case "link":
            // Interne Ziele über `Link` (kein Neuladen), externe als
            // normaler Verweis mit `rel` — ein Handbuch verlinkt auf die
            // Hersteller-Doku, und die soll nicht im selben Reiter landen.
            return teil.ziel.startsWith("/") ? (
              <Link key={i} href={teil.ziel as Route} className="text-primary underline">
                {teil.text}
              </Link>
            ) : (
              <a
                key={i}
                href={teil.ziel}
                target="_blank"
                rel="noreferrer noopener"
                className="text-primary underline"
              >
                {teil.text}
              </a>
            );
          case "text":
            return <span key={i}>{teil.text}</span>;
        }
      })}
    </>
  );
}

/**
 * Auf der Sammel-Druckseite trägt jeder Artikel schon ein `h2`. Die
 * Überschriften im Text rücken dort um eine Stufe nach unten, damit die
 * Gliederung des Dokuments stimmt — ein `h2` unter einem `h2` ist für
 * einen Screenreader kein Unterabschnitt, sondern ein neues Kapitel.
 */
function Ueberschrift({
  block,
  drucken,
}: {
  block: Extract<Block, { art: "ueberschrift" }>;
  drucken: boolean;
}) {
  const oben = block.stufe === 2;
  const Tag = drucken ? (oben ? "h3" : "h4") : oben ? "h2" : "h3";
  const klasse = oben
    ? "text-text-primary mt-8 mb-3 scroll-mt-24 text-xl font-medium"
    : "text-text-primary mt-6 mb-2 scroll-mt-24 text-base font-medium";
  return (
    // Auf der Sammelseite stehen alle Artikel untereinander; dieselben
    // Anker zweimal wären doppelte `id`s im Dokument. Das Verzeichnis
    // dort springt auf den Artikel, nicht auf den Abschnitt.
    <Tag id={drucken ? undefined : block.anker} className={`group ${klasse}`}>
      {block.text}
      {drucken ? null : (
        <>
          {" "}
          <a
            href={`#${block.anker}`}
            className="text-text-tertiary nicht-drucken opacity-0 transition-opacity group-hover:opacity-100"
            aria-label={`Link zu „${block.text}“`}
          >
            #
          </a>
        </>
      )}
    </Tag>
  );
}

/**
 * @param drucken Für die Sammel-Druckseite: `{{werte}}` wird zu einem
 *   Hinweis statt zu einer Abfrage. Eine Tabelle mit Zahlen von heute
 *   liest sich auf Papier wie eine Zusicherung für morgen — und ein
 *   Papier lässt sich nicht nachladen (§5.77).
 */
export function HandbuchInhalt({
  blöcke,
  drucken = false,
}: {
  blöcke: Block[];
  drucken?: boolean;
}) {
  return (
    <div className="handbuch-artikel text-text-secondary max-w-prose text-sm leading-relaxed">
      {blöcke.map((block, i) => {
        switch (block.art) {
          case "ueberschrift":
            return <Ueberschrift key={i} block={block} drucken={drucken} />;

          case "absatz":
            return (
              <p key={i} className="mb-3">
                <Inline teile={block.teile} />
              </p>
            );

          case "liste":
            return block.geordnet ? (
              <ol key={i} className="mb-3 ml-5 list-decimal space-y-1">
                {block.punkte.map((punkt, j) => (
                  <li key={j}>
                    <Inline teile={punkt} />
                  </li>
                ))}
              </ol>
            ) : (
              <ul key={i} className="mb-3 ml-5 list-disc space-y-1">
                {block.punkte.map((punkt, j) => (
                  <li key={j}>
                    <Inline teile={punkt} />
                  </li>
                ))}
              </ul>
            );

          case "tabelle":
            return (
              <div key={i} className="mb-4 overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-border border-b">
                      {block.kopf.map((zelle, j) => (
                        // `scope="col"` gehört an jeden Tabellenkopf —
                        // ohne ihn ist die Spalte für einen Screenreader
                        // keine Spalte (Paket 3 macht das im Rest der
                        // Software nach).
                        <th
                          key={j}
                          scope="col"
                          className="text-text-primary py-2 pr-4 text-left font-medium"
                        >
                          <Inline teile={zelle} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-border divide-y">
                    {block.zeilen.map((zeile, j) => (
                      <tr key={j}>
                        {zeile.map((zelle, k) => (
                          <td key={k} className="py-2 pr-4 align-top">
                            <Inline teile={zelle} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );

          case "zitat":
            return (
              <blockquote
                key={i}
                className="border-primary bg-surface-alt text-text-secondary mb-4 border-l-2 px-4 py-2"
              >
                <Inline teile={block.teile} />
              </blockquote>
            );

          case "trenner":
            return <hr key={i} className="border-border my-6" />;

          case "marke":
            // Lebende Inhalte. Eine unbekannte Marke wird **gezeigt** und
            // nicht verschluckt: ein Handbuch mit einer leeren Stelle
            // sieht aus wie ein Handbuch ohne Lücke.
            if (block.name === "werte") {
              return drucken ? (
                <p key={i} className="bg-surface-alt border-border mb-4 rounded-md border p-3 text-sm">
                  Die aktuellen Temperaturen, Zeiten und Raumtyp-Werte stehen
                  in der Software: „Temperaturen &amp; Zeiten" für den
                  Hausstandard, „Raumtypen" für die Werte je Raumtyp samt der
                  Angabe, welcher davon wirkt. Auf Papier wären sie der Stand
                  des Ausdruckstages.
                </p>
              ) : (
                <LebendeWerte key={i} />
              );
            }
            if (block.name === "karte") return <HeizlogikKarte key={i} />;
            return (
              <p key={i} className="text-error mb-3 text-xs">
                Unbekannte Marke im Artikel: {`{{${block.name}}}`}
              </p>
            );
        }
      })}
    </div>
  );
}
