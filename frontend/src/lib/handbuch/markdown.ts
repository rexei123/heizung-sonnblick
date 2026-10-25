/**
 * Ein kleiner, vollständig benannter Markdown-Teilumfang (Paket 1).
 *
 * **Warum nicht `marked` oder `remark`.** Drei Gründe, in dieser
 * Reihenfolge:
 *
 * 1. **Keine `dangerouslySetInnerHTML`.** Der Parser hier liefert einen
 *    typisierten Baum, den die Anzeige als React-Elemente rendert. Damit
 *    gibt es keine Stelle, an der HTML aus einer Datei in die Seite
 *    gelangt — auch nicht versehentlich, wenn später jemand einen
 *    Artikel aus einer anderen Quelle einspielt.
 * 2. **Eine Abhängigkeit weniger, deren Version ein Urteil fällt.** Ein
 *    Markdown-Parser entscheidet, wie das Handbuch aussieht; ein
 *    Versionssprung zur falschen Zeit ist genau die Klasse aus §5.80.
 * 3. **Der Umfang ist klein und bekannt.** Was hier nicht steht, steht
 *    auch in keinem Artikel — und wenn doch, erscheint es als **Text**
 *    und nicht als Lücke (siehe unten).
 *
 * **Was nicht erkannt wird, wird gezeigt.** Eine Zeile, die zu keinem
 * Block passt, wird ein Absatz mit ihrem Rohtext. Sie verschwindet nicht.
 * Das ist die wichtigste Eigenschaft: ein Handbuch, das eine Zeile
 * stillschweigend wegläßt, ist schlimmer als eines, das sie unformatiert
 * zeigt — die zweite Variante sieht man.
 *
 * **Umfang:** `##`/`###`-Überschriften, Absätze, Listen mit `-` und
 * `1.`, Tabellen, Zitatblöcke mit `>`, Trennlinien `---`, und inline
 * `**fett**`, `` `code` `` sowie `[Text](Ziel)`.
 *
 * **Marken für lebende Inhalte:** eine Zeile `{{werte}}` oder
 * `{{karte}}` wird ein eigener Block, den die Anzeige durch eine
 * Komponente ersetzt. So stehen aktuelle Werte **aus der Datenbank** im
 * Artikel und nicht als Zahl im Text, die beim ersten Nachjustieren
 * falsch wird (§5.77).
 */

export type InlineTeil =
  | { art: "text"; text: string }
  | { art: "fett"; text: string }
  | { art: "code"; text: string }
  | { art: "link"; text: string; ziel: string };

export type Block =
  | { art: "ueberschrift"; stufe: 2 | 3; text: string; anker: string }
  | { art: "absatz"; teile: InlineTeil[] }
  | { art: "liste"; geordnet: boolean; punkte: InlineTeil[][] }
  | { art: "tabelle"; kopf: InlineTeil[][]; zeilen: InlineTeil[][][] }
  | { art: "zitat"; teile: InlineTeil[] }
  | { art: "trenner" }
  | { art: "marke"; name: string };

/**
 * Anker für Direktlinks auf einen Abschnitt.
 *
 * Kleinbuchstaben, Umlaute ausgeschrieben, alles andere zu `-`. Die
 * Umlaut-Ersetzung ist nicht Kosmetik: ein Anker mit `ü` landet
 * prozentkodiert in der Adresszeile und ist dann nicht mehr vorlesbar,
 * wenn jemand den Link am Telefon durchgibt.
 */
export function anker(text: string): string {
  return text
    .toLowerCase()
    .replace(/ä/g, "ae")
    .replace(/ö/g, "oe")
    .replace(/ü/g, "ue")
    .replace(/ß/g, "ss")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

/** Zerlegt eine Zeile in fett, Code, Links und Text. */
export function inline(zeile: string): InlineTeil[] {
  const teile: InlineTeil[] = [];
  // Eine Regex mit drei Alternativen und `exec` in der Schleife: so
  // bleibt die Reihenfolge erhalten, und der Text zwischen zwei Treffern
  // geht nicht verloren.
  const muster = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)/g;
  let zuletzt = 0;
  let treffer: RegExpExecArray | null;

  while ((treffer = muster.exec(zeile)) !== null) {
    if (treffer.index > zuletzt) {
      teile.push({ art: "text", text: zeile.slice(zuletzt, treffer.index) });
    }
    if (treffer[1] !== undefined) {
      teile.push({ art: "fett", text: treffer[1] });
    } else if (treffer[2] !== undefined) {
      teile.push({ art: "code", text: treffer[2] });
    } else if (treffer[3] !== undefined && treffer[4] !== undefined) {
      teile.push({ art: "link", text: treffer[3], ziel: treffer[4] });
    }
    zuletzt = treffer.index + treffer[0].length;
  }
  if (zuletzt < zeile.length) {
    teile.push({ art: "text", text: zeile.slice(zuletzt) });
  }
  return teile.length > 0 ? teile : [{ art: "text", text: "" }];
}

/** Eine Tabellenzeile `| a | b |` zu ihren Zellen. */
function zellen(zeile: string): InlineTeil[][] {
  return zeile
    .replace(/^\s*\|/, "")
    .replace(/\|\s*$/, "")
    .split("|")
    .map((z) => inline(z.trim()));
}

function istTrennzeile(zeile: string): boolean {
  // `|---|:---:|` — die Zeile unter dem Tabellenkopf.
  return /^\s*\|[\s|:-]+\|\s*$/.test(zeile);
}

/**
 * Markdown zu Blöcken.
 *
 * Ein Zeilen-Durchlauf ohne Rekursion: verschachtelte Listen gibt es im
 * Handbuch nicht, und sie zu erlauben hieße, einen Parser zu bauen, den
 * niemand mehr liest.
 */
export function parseMarkdown(quelle: string): Block[] {
  const zeilen = quelle.replace(/\r\n/g, "\n").split("\n");
  const blöcke: Block[] = [];
  let i = 0;

  while (i < zeilen.length) {
    const zeile = zeilen[i];
    const gekappt = zeile.trim();

    if (gekappt === "") {
      i += 1;
      continue;
    }

    // Marke für lebende Inhalte
    const marke = /^\{\{([a-z-]+)\}\}$/.exec(gekappt);
    if (marke !== null) {
      blöcke.push({ art: "marke", name: marke[1] });
      i += 1;
      continue;
    }

    if (gekappt === "---") {
      blöcke.push({ art: "trenner" });
      i += 1;
      continue;
    }

    const ueber = /^(##|###)\s+(.*)$/.exec(gekappt);
    if (ueber !== null) {
      const text = ueber[2].trim();
      blöcke.push({
        art: "ueberschrift",
        stufe: ueber[1].length === 2 ? 2 : 3,
        text,
        anker: anker(text),
      });
      i += 1;
      continue;
    }

    if (gekappt.startsWith("> ")) {
      // Mehrzeilige Zitate werden zu einem Block zusammengezogen.
      const teile: string[] = [];
      while (i < zeilen.length && zeilen[i].trim().startsWith("> ")) {
        teile.push(zeilen[i].trim().slice(2).trim());
        i += 1;
      }
      blöcke.push({ art: "zitat", teile: inline(teile.join(" ")) });
      continue;
    }

    if (gekappt.startsWith("| ")) {
      const kopf = zellen(zeilen[i]);
      i += 1;
      if (i < zeilen.length && istTrennzeile(zeilen[i])) {
        i += 1;
      }
      const reihen: InlineTeil[][][] = [];
      while (i < zeilen.length && zeilen[i].trim().startsWith("| ")) {
        reihen.push(zellen(zeilen[i]));
        i += 1;
      }
      blöcke.push({ art: "tabelle", kopf, zeilen: reihen });
      continue;
    }

    const listenMuster = /^(-|\d+\.)\s+(.*)$/;
    const erstePunkt = listenMuster.exec(gekappt);
    if (erstePunkt !== null) {
      const geordnet = erstePunkt[1] !== "-";
      const punkte: InlineTeil[][] = [];
      while (i < zeilen.length) {
        const m = listenMuster.exec(zeilen[i].trim());
        if (m === null) break;
        // Eine gemischte Liste (`-` und `1.` direkt untereinander) wäre
        // ein Schreibfehler im Artikel; sie wird hier getrennt, damit sie
        // auffällt.
        if ((m[1] !== "-") !== geordnet) break;
        punkte.push(inline(m[2].trim()));
        i += 1;
      }
      blöcke.push({ art: "liste", geordnet, punkte });
      continue;
    }

    // Absatz: alle folgenden Zeilen, bis eine leere oder ein anderer
    // Block beginnt. So bleibt ein umgebrochener Satz ein Satz.
    const absatz: string[] = [];
    while (i < zeilen.length) {
      const z = zeilen[i].trim();
      if (
        z === "" ||
        z === "---" ||
        z.startsWith("#") ||
        z.startsWith("> ") ||
        z.startsWith("| ") ||
        listenMuster.test(z) ||
        /^\{\{[a-z-]+\}\}$/.test(z)
      ) {
        break;
      }
      absatz.push(z);
      i += 1;
    }
    blöcke.push({ art: "absatz", teile: inline(absatz.join(" ")) });
  }

  return blöcke;
}

/** Der reine Text eines Blocks — für die Suche und die Vorschau. */
export function blockText(block: Block): string {
  switch (block.art) {
    case "ueberschrift":
      return block.text;
    case "absatz":
    case "zitat":
      return block.teile.map((t) => t.text).join("");
    case "liste":
      return block.punkte.map((p) => p.map((t) => t.text).join("")).join(" ");
    case "tabelle":
      return [block.kopf, ...block.zeilen]
        .map((reihe) => reihe.map((z) => z.map((t) => t.text).join("")).join(" "))
        .join(" ");
    case "trenner":
    case "marke":
      return "";
  }
}
