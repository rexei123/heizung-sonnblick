/**
 * Die Suche im Handbuch (Paket 1).
 *
 * **Eine reine Funktion über den Index, im Browser.** Kein Dienst, kein
 * Netzaufruf, kein Tippen-Verzug: der Index liegt als Daten in der Seite,
 * und bei 24 Artikeln ist eine Schleife schneller als jede Abfrage. Wer
 * später 200 Artikel hat, braucht etwas anderes — bis dahin wäre jede
 * Zusatzschicht Arbeit ohne Wirkung.
 *
 * **Die Fundstelle gehört zum Treffer.** Eine Trefferliste, die nur
 * Titel zeigt, verlangt vom Leser, den Artikel selbst zu durchsuchen —
 * und genau das wollte er nicht. Deshalb liefert die Suche den Ausschnitt
 * um den Fund und den Anker des Abschnitts.
 */

import type { SuchEintrag, Treffer } from "./artikel";

/** Zeichen, die die Fundstelle markieren. Die Anzeige ersetzt sie durch Hervorhebung. */
export const MARKE_AUF = "«";
export const MARKE_ZU = "»";

const UMGEBUNG = 60;

function ausschnitt(text: string, stelle: number, länge: number): string {
  const von = Math.max(0, stelle - UMGEBUNG);
  const bis = Math.min(text.length, stelle + länge + UMGEBUNG);
  const vorne = von > 0 ? "… " : "";
  const hinten = bis < text.length ? " …" : "";
  return (
    vorne +
    text.slice(von, stelle) +
    MARKE_AUF +
    text.slice(stelle, stelle + länge) +
    MARKE_ZU +
    text.slice(stelle + länge, bis) +
    hinten
  );
}

/**
 * Sucht `frage` in Titel, Überschriften, Text und Stichworten.
 *
 * Ohne Groß- und Kleinschreibung, als Teilzeichenfolge. **Kein
 * Wortstamm-Abgleich und keine Tippfehler-Toleranz** — beides wäre eine
 * Vermutung darüber, was gemeint war, und eine falsche Vermutung ist in
 * einer Suche teurer als kein Treffer: wer „Sollwert" tippt und
 * „Sollwerte" findet, ist zufrieden; wer „Sollwert" tippt und einen
 * Artikel über Sommermodus bekommt, sucht weiter.
 *
 * @param kategorie leer = alle Kategorien.
 */
export function suche(
  index: SuchEintrag[],
  frage: string,
  kategorie = "",
): Treffer[] {
  const gesucht = frage.trim().toLowerCase();
  const treffer: Treffer[] = [];

  for (const eintrag of index) {
    if (kategorie !== "" && eintrag.kategorie !== kategorie) {
      continue;
    }

    // Leere Frage: der Artikel selbst ist der Treffer, ohne Fundstelle.
    if (gesucht === "") {
      treffer.push({
        slug: eintrag.slug,
        titel: eintrag.titel,
        kategorie: eintrag.kategorie,
        rollen: eintrag.rollen,
        stelle: "",
      });
      continue;
    }

    // Reihenfolge der Prüfung = Reihenfolge der Güte: Titel, dann
    // Stichwort, dann Überschrift, dann Text. Der erste Treffer je
    // Artikel gewinnt — eine Liste mit demselben Artikel fünfmal ist
    // keine Hilfe.
    if (eintrag.titel.toLowerCase().includes(gesucht)) {
      const i = eintrag.titel.toLowerCase().indexOf(gesucht);
      treffer.push({
        slug: eintrag.slug,
        titel: eintrag.titel,
        kategorie: eintrag.kategorie,
        rollen: eintrag.rollen,
        stelle: ausschnitt(eintrag.titel, i, gesucht.length),
      });
      continue;
    }

    const stichwort = eintrag.stichworte.find((s) => s.toLowerCase().includes(gesucht));
    if (stichwort !== undefined) {
      treffer.push({
        slug: eintrag.slug,
        titel: eintrag.titel,
        kategorie: eintrag.kategorie,
        rollen: eintrag.rollen,
        stelle: `Stichwort: ${MARKE_AUF}${stichwort}${MARKE_ZU}`,
      });
      continue;
    }

    let gefunden = false;
    for (const abschnitt of eintrag.abschnitte) {
      const inTitel = abschnitt.titel.toLowerCase().indexOf(gesucht);
      if (inTitel !== -1) {
        treffer.push({
          slug: eintrag.slug,
          titel: eintrag.titel,
          kategorie: eintrag.kategorie,
          rollen: eintrag.rollen,
          stelle: `Abschnitt: ${ausschnitt(abschnitt.titel, inTitel, gesucht.length)}`,
          anker: abschnitt.anker === "" ? undefined : abschnitt.anker,
        });
        gefunden = true;
        break;
      }
      const imText = abschnitt.text.toLowerCase().indexOf(gesucht);
      if (imText !== -1) {
        treffer.push({
          slug: eintrag.slug,
          titel: eintrag.titel,
          kategorie: eintrag.kategorie,
          rollen: eintrag.rollen,
          stelle: ausschnitt(abschnitt.text, imText, gesucht.length),
          anker: abschnitt.anker === "" ? undefined : abschnitt.anker,
        });
        gefunden = true;
        break;
      }
    }
    if (gefunden) continue;
  }

  return treffer;
}

/** Die Kategorien im Index, in stabiler Reihenfolge. */
export function kategorien(index: SuchEintrag[]): string[] {
  return [...new Set(index.map((e) => e.kategorie))].sort((a, b) => a.localeCompare(b));
}
