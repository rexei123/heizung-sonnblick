/**
 * Welcher Handbuch-Artikel zu welcher Seite gehört (Paket 1).
 *
 * **Warum diese Liste doppelt aussieht und es nicht ist.** Jeder Artikel
 * trägt seine Route in den Kopfdaten (`route:`), und `artikel.ts` liest
 * sie — aber dieses Modul liest sie nicht nach, weil es im **Browser**
 * läuft: die Kontext-Hilfe sitzt in der Hülle der Anwendung und kennt
 * nur `usePathname()`, keine Dateien. Ein Modul mit `node:fs` lässt sich
 * dort nicht laden.
 *
 * Damit die zwei Stellen nicht auseinanderlaufen (§5.53), prüft der
 * Spiegel-Test `backend/tests/test_handbuch_spiegel.py` beide Richtungen:
 *
 * * jede Route hier hat einen Artikel, der dieselbe Route in seinen
 *   Kopfdaten führt, und
 * * jede Route der Seitenleiste steht hier.
 *
 * Fällt eine der beiden Prüfungen, ist die Antwort **nicht**, die Liste
 * nachzuziehen und weiterzugehen: eine Seite ohne Artikel ist eine Seite,
 * zu der das Handbuch schweigt, und genau das soll der Test melden.
 */

/**
 * Route → Dateiname des Artikels (ohne `.md`).
 *
 * Die Reihenfolge ist die der Seitenleiste; `laengste Route gewinnt` beim
 * Auflösen, deshalb darf `/einstellungen/hotel` neben `/einstellungen`
 * stehen, ohne sich zu stören.
 */
export const ROUTE_ZU_ARTIKEL: Record<string, string> = {
  "/": "seite-dashboard",
  "/zimmer": "seite-zimmeruebersicht",
  "/zimmer/[id]": "seite-zimmer-detail",
  "/belegungen": "seite-belegungen",
  "/einstellungen/temperaturen-zeiten": "seite-temperaturen-zeiten",
  "/raumtypen": "seite-raumtypen",
  "/profile": "seite-profile",
  "/szenarien": "seite-szenarien",
  "/devices": "seite-thermostate",
  "/einstellungen/gateway": "seite-gateway",
  "/analyse/temperaturverlauf": "seite-temperaturverlauf",
  "/einstellungen/hotel": "seite-hotel",
  "/einstellungen/saison": "seite-saison",
  "/einstellungen/benutzer": "seite-benutzer",
  "/einstellungen/api": "seite-api",
};

/**
 * Der Artikel zur gerade geöffneten Adresse, oder `undefined`.
 *
 * **Die längste passende Route gewinnt.** `/einstellungen/gateway` ist
 * ein eigener Eintrag und darf nicht vom Präfix `/einstellungen`
 * eingefangen werden; umgekehrt soll `/zimmer/14` beim Detail-Artikel
 * landen und nicht bei der Übersicht.
 *
 * `/` ist der Sonderfall: als Präfix passt es auf alles, deshalb nur
 * exakt (dieselbe Regel wie `isActive` in der Seitenleiste).
 */
export function artikelZurRoute(pfad: string): string | undefined {
  // Eine Zimmer-Detailseite hat eine Zahl im Pfad; sie auf das
  // Platzhalter-Muster abzubilden ist einfacher und ehrlicher, als ein
  // zweites Mal zu raten.
  const normiert = /^\/zimmer\/[^/]+$/.test(pfad) ? "/zimmer/[id]" : pfad;

  if (normiert === "/") {
    return ROUTE_ZU_ARTIKEL["/"];
  }

  let treffer: string | undefined;
  let laenge = 0;
  for (const [route, slug] of Object.entries(ROUTE_ZU_ARTIKEL)) {
    if (route === "/") continue;
    const passt = normiert === route || normiert.startsWith(route + "/");
    if (passt && route.length > laenge) {
      treffer = slug;
      laenge = route.length;
    }
  }
  return treffer;
}
