/**
 * Die Handbuch-Artikel: laden, Kopfdaten lesen, Suchindex bauen (Paket 1).
 *
 * **Die Artikel liegen als Markdown im Repo** (`frontend/content/handbuch`)
 * und werden im **Build** gelesen — nicht zur Laufzeit aus einer
 * Datenbank. Drei Folgen, alle gewollt:
 *
 * * Ein Artikel wandert durch denselben Pull Request wie die Änderung,
 *   die er beschreibt. Genau deshalb steht die Regel „Handbuch angepasst /
 *   nicht nötig, weil …" in der PR-Vorlage: ein Handbuch, das man
 *   getrennt pflegen muss, ist nach drei Sprints falsch (§5.77 in
 *   Buchform).
 * * Die Suche braucht keinen Dienst. Der Index entsteht beim Bauen und
 *   liegt als Daten in der Seite.
 * * Es gibt keine Oberfläche zum Bearbeiten, und das ist kein Mangel:
 *   wer das Handbuch ändert, ändert Software-Verhalten oder beschreibt
 *   es — beides gehört in einen PR.
 *
 * **Kopfdaten** (die ersten Zeilen zwischen `---`):
 *
 * ```
 * ---
 * titel: Übersteuerung
 * kategorie: Heizlogik
 * stichworte: Wunschtemperatur, Gast, Rang, Kappung
 * rollen: alle
 * stand: 2026-10-25
 * ---
 * ```
 *
 * `rollen` ist eine **Angabe**, keine Zugangsbeschränkung: das Handbuch
 * ist für alle Rollen lesbar (Vorgabe des Betreibers). `admin` heißt
 * „beschreibt etwas, das nur ein Administrator tun kann" — die Anzeige
 * kennzeichnet es, versteckt es nicht. Eine versteckte Seite erzeugt die
 * Frage „wo ist das hin" statt der Antwort „das darf ich nicht ändern"
 * (dieselbe Entscheidung wie in der Seitenleiste, Sprint 22 T6).
 *
 * `stand` ist Pflicht und wird vom Spiegel-Test geprüft. Ein Artikel ohne
 * Datum ist eine Behauptung ohne Zeitpunkt, und genau daraus ist §5.79
 * entstanden.
 */

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { type Block, blockText, parseMarkdown } from "./markdown";

const ORDNER = join(process.cwd(), "content", "handbuch");

export interface ArtikelKopf {
  slug: string;
  titel: string;
  kategorie: string;
  stichworte: string[];
  rollen: "alle" | "admin";
  stand: string;
  /** Die Route der Software, die dieser Artikel beschreibt. */
  route?: string;
}

export interface Artikel extends ArtikelKopf {
  blöcke: Block[];
  /** Kleingeschriebener Volltext für die Suche. */
  suchtext: string;
  /** Die `##`-Überschriften mit Anker, für das Inhaltsverzeichnis. */
  abschnitte: { text: string; anker: string }[];
}

/** Ein Treffer der Suche, mit der Fundstelle. */
export interface Treffer {
  slug: string;
  titel: string;
  kategorie: string;
  rollen: "alle" | "admin";
  /** Der Textausschnitt um die Fundstelle, mit `«` `»` um den Fund. */
  stelle: string;
  /** Anker des Abschnitts, in dem gefunden wurde — falls bekannt. */
  anker?: string;
}

function kopfdaten(roh: string): { kopf: Record<string, string>; rest: string } {
  if (!roh.startsWith("---")) {
    return { kopf: {}, rest: roh };
  }
  const ende = roh.indexOf("\n---", 3);
  if (ende === -1) {
    return { kopf: {}, rest: roh };
  }
  const kopf: Record<string, string> = {};
  for (const zeile of roh.slice(3, ende).split("\n")) {
    const doppelpunkt = zeile.indexOf(":");
    if (doppelpunkt === -1) continue;
    kopf[zeile.slice(0, doppelpunkt).trim()] = zeile.slice(doppelpunkt + 1).trim();
  }
  return { kopf, rest: roh.slice(ende + 4) };
}

let gespeichert: Artikel[] | null = null;

/**
 * Alle Artikel, nach Kategorie und Titel sortiert.
 *
 * Das Ergebnis wird im Modul behalten: Next ruft die Funktion beim Bauen
 * für jede Seite auf, und 24 Dateien 20-mal zu lesen ist Arbeit ohne
 * Ergebnis.
 */
export function ladeArtikel(): Artikel[] {
  if (gespeichert !== null) {
    return gespeichert;
  }

  const dateien = readdirSync(ORDNER).filter((d) => d.endsWith(".md"));
  const artikel: Artikel[] = dateien.map((datei) => {
    const roh = readFileSync(join(ORDNER, datei), "utf-8");
    const { kopf, rest } = kopfdaten(roh);
    const blöcke = parseMarkdown(rest);
    const slug = datei.replace(/\.md$/, "");

    // Fehlende Kopfdaten werden **nicht** stillschweigend ergänzt: ein
    // Artikel ohne Titel oder Stand soll auffallen, und der Spiegel-Test
    // prüft beides. Was hier steht, ist der Rohwert.
    return {
      slug,
      titel: kopf.titel ?? slug,
      kategorie: kopf.kategorie ?? "Ohne Kategorie",
      stichworte: (kopf.stichworte ?? "")
        .split(",")
        .map((s) => s.trim())
        .filter((s) => s !== ""),
      rollen: kopf.rollen === "admin" ? "admin" : "alle",
      stand: kopf.stand ?? "",
      route: kopf.route,
      blöcke,
      suchtext: [
        kopf.titel ?? slug,
        kopf.stichworte ?? "",
        ...blöcke.map(blockText),
      ]
        .join(" \n ")
        .toLowerCase(),
      abschnitte: blöcke
        .filter((b): b is Extract<Block, { art: "ueberschrift" }> => b.art === "ueberschrift")
        .filter((b) => b.stufe === 2)
        .map((b) => ({ text: b.text, anker: b.anker })),
    };
  });

  artikel.sort(
    (a, b) => a.kategorie.localeCompare(b.kategorie) || a.titel.localeCompare(b.titel),
  );
  gespeichert = artikel;
  return artikel;
}

export function ladeArtikelNachSlug(slug: string): Artikel | undefined {
  return ladeArtikel().find((a) => a.slug === slug);
}

/** Die Artikel in der Form, die der Browser für die Suche braucht. */
export interface SuchEintrag {
  slug: string;
  titel: string;
  kategorie: string;
  rollen: "alle" | "admin";
  stand: string;
  stichworte: string[];
  /** Je `##`-Abschnitt: Anker und der Text darunter, kleingeschrieben. */
  abschnitte: { anker: string; titel: string; text: string }[];
}

/**
 * Baut den Index für die Suche im Browser.
 *
 * **Abschnittsweise und nicht als ein Textklotz je Artikel.** Nur so kann
 * ein Treffer auf den Abschnitt verlinken, in dem er steht — und ein
 * Handbuch, dessen Suche auf den Artikelanfang springt, lässt den Leser
 * dann selbst suchen.
 */
export function baueSuchIndex(): SuchEintrag[] {
  return ladeArtikel().map((a) => {
    const abschnitte: SuchEintrag["abschnitte"] = [
      { anker: "", titel: a.titel, text: "" },
    ];
    for (const block of a.blöcke) {
      if (block.art === "ueberschrift" && block.stufe === 2) {
        abschnitte.push({ anker: block.anker, titel: block.text, text: "" });
        continue;
      }
      const text = blockText(block);
      if (text !== "") {
        const letzter = abschnitte[abschnitte.length - 1];
        letzter.text = `${letzter.text} ${text}`.trim();
      }
    }
    return {
      slug: a.slug,
      titel: a.titel,
      kategorie: a.kategorie,
      rollen: a.rollen,
      stand: a.stand,
      stichworte: a.stichworte,
      abschnitte,
    };
  });
}
