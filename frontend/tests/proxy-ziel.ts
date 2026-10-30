/**
 * Schranke: ein Playwright-Lauf zeigt nur auf das Loopback-Interface.
 *
 * **Der Anlass.** Ungemockte API-Anfragen eines e2e-Laufs verschwinden
 * nicht — sie gehen über den Rewrite aus `next.config.mjs`
 * (`/api/v1/:path*` → `${API_PROXY_TARGET}/api/v1/:path*`) an das, was in
 * `API_PROXY_TARGET` steht. Lokal steht dort, was in `frontend/.env.local`
 * steht, und das ist beim Betreiber dieses Hauses
 * `https://heizung-test.hoteltec.at` — develop, also **die Produktion**.
 *
 * Im Lauf vom 25.10.2026 sah das so aus:
 *
 * > `Failed to proxy https://heizung-test.hoteltec.at/api/v1/devices/3/audit`
 * > `Error: write EPROTO ... tlsv1 alert internal error`
 *
 * Die Anfragen sind **am TLS-Handshake** gescheitert, nicht an einer
 * Schranke. Das ist Zufall: ein anderer Rechner, ein anderes Zertifikat,
 * eine andere Node-Version, und dieselben Anfragen kommen an. Ein
 * `POST`/`PATCH` aus einem Test, der seinen Mock verfehlt, schreibt dann in
 * die laufende Heizungssteuerung — das ist die §5.78-Familie: ein Eingriff,
 * dessen Nebenwirkung man nicht sieht.
 *
 * **Warum im Modul-Rumpf und nicht in `globalSetup`.** Die Prüfung muss
 * laufen, bevor Playwright den `webServer` startet — danach steht die
 * Umgebung des Next-Prozesses schon. Ob Playwright `globalSetup` vor oder
 * nach dem `webServer` ausführt, ist eine Eigenschaft der jeweiligen
 * Version und keine Zusicherung, auf die eine Schranke bauen soll (§5.83:
 * eine Zusicherung gilt nur auf der Ebene, auf der sie geprüft wurde). Der
 * Modul-Rumpf der Konfiguration läuft nachweislich vor allem, was
 * Playwright tut, weil Playwright ihn selbst lädt.
 *
 * **Warum die Schranke die Dateien selbst liest.** `process.env` allein
 * genügt nicht: `.env.local` liest **Next** in seinem eigenen Prozess, der
 * Playwright-Prozess sieht die Datei nie. Eine Schranke, die nur
 * `process.env.API_PROXY_TARGET` prüft, wäre also genau in dem Fall grün,
 * der den Anlass gegeben hat — unkonfigurierte Shell, Produktionsziel in
 * der Datei. Geprüft wird deshalb dieselbe Kette, die Next für
 * `next build && next start` liest, in derselben Reihenfolge.
 *
 * **Was mit dem geprüften Wert passiert.** Er wird dem `webServer` als
 * `env` übergeben, nicht der Datei überlassen. Damit prüft und benutzt der
 * Lauf **einen** Wert statt zweier getrennt ermittelter (§5.53:
 * Dual-Source-of-Truth). Nebeneffekt: ohne jede Konfiguration zeigt der
 * Rewrite nicht mehr auf den Compose-Namen `http://api:8000` — der löst in
 * CI nicht auf, aber „löst gerade nicht auf" ist kein Schutz.
 *
 * **Der Preis, und warum er bezahlt sein will.** Mit dieser Schranke
 * scheitern ungemockte Anfragen gegen das Loopback-Interface, also
 * sichtbar im eigenen Lauf statt unsichtbar beim Betreiber. Das
 * funktioniert nur, solange die Suite ihre Routen vollständig mockt — eine
 * Schranke, die bei jedem Lauf anschlägt, wird abgeschaltet (§5.79: ein
 * Melder, dem niemand mehr glaubt, überwacht nichts).
 */

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

/** Name der Variablen, die `next.config.mjs` liest. */
const VARIABLE = "API_PROXY_TARGET";

/**
 * Die Dateien, die Next für `next build` / `next start` liest, in
 * absteigender Priorität. `process.env` schlägt sie alle — Next
 * überschreibt keine bereits gesetzte Variable, und genau darauf beruht
 * der Hinweis in der Fehlermeldung.
 *
 * Nicht dabei ist `.env.development.local`: die liest Next nur für
 * `next dev`, und der `webServer` dieser Konfiguration fährt einen
 * Produktions-Build.
 */
const ENV_DATEIEN = [".env.production.local", ".env.local", ".env.production", ".env"] as const;

/**
 * Ziel, wenn nichts konfiguriert ist. Port 9 ist der Discard-Port; dort
 * lauscht nichts, eine ungemockte Anfrage scheitert also sofort mit
 * `ECONNREFUSED` statt in einen Timeout zu laufen.
 */
const SACKGASSE = "http://127.0.0.1:9";

/** Woher der Wert kam — nur für die Meldung. */
type Herkunft = { wert: string; quelle: string } | undefined;

/**
 * Liest `API_PROXY_TARGET` aus einer `.env`-Datei.
 *
 * Bewusst klein gehalten: gesucht wird genau diese eine Variable, nicht
 * das ganze dotenv-Format. Umschließende Anführungszeichen und ein
 * angehängter Kommentar werden entfernt, weil Next (dotenv) das auch tut
 * und die Schranke sonst einen Wert prüft, den Next anders liest.
 */
function ausDatei(pfad: string): string | undefined {
  if (!existsSync(pfad)) return undefined;

  let inhalt: string;
  try {
    inhalt = readFileSync(pfad, "utf8");
  } catch {
    return undefined;
  }

  for (const zeile of inhalt.split(/\r?\n/)) {
    const treffer = zeile.match(/^\s*(?:export\s+)?API_PROXY_TARGET\s*=\s*(.*)$/);
    if (!treffer) continue;

    let wert = treffer[1].trim();
    const anfuehrung = wert.match(/^(['"])([\s\S]*?)\1\s*$/);
    if (anfuehrung) {
      wert = anfuehrung[2];
    } else {
      wert = wert.replace(/\s+#.*$/, "").trim();
    }
    if (wert !== "") return wert;
  }

  return undefined;
}

/**
 * Zeigt das Ziel nachweislich auf das Loopback-Interface?
 *
 * Erlaubt sind `localhost`, `::1` und das ganze Netz `127.0.0.0/8`.
 * **Nicht** erlaubt sind Namen wie `app.localhost`: dass sie auf Loopback
 * zeigen, ist Konvention des Resolvers (RFC 6761), keine Eigenschaft, die
 * diese Funktion prüfen kann. Eine Schranke, die auf einer Konvention
 * steht, hat die Ebene gewechselt, ohne es zu sagen (§5.83).
 */
function istLoopback(ziel: string): boolean {
  let url: URL;
  try {
    url = new URL(ziel);
  } catch {
    return false;
  }

  const host = url.hostname.replace(/^\[/, "").replace(/\]$/, "").toLowerCase();
  return host === "localhost" || host === "::1" || /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(host);
}

function meldung({ wert, quelle }: { wert: string; quelle: string }): string {
  return [
    `${VARIABLE} zeigt nicht auf localhost — Playwright-Lauf abgebrochen.`,
    "",
    `  Ziel:   ${wert}`,
    `  Quelle: ${quelle}`,
    "",
    "Ungemockte Anfragen eines e2e-Laufs gehen über den Rewrite aus",
    "next.config.mjs an dieses Ziel. heizung-test ist die Produktion dieses",
    "Hauses — ein Testlauf darf dort nichts lesen und nichts schreiben.",
    "",
    "Für einen lokalen Lauf das Ziel in der Shell setzen (gewinnt gegen",
    "jede .env-Datei, die Datei selbst bleibt unverändert):",
    "",
    `  PowerShell:  $env:${VARIABLE} = "${SACKGASSE}"; npx playwright test`,
    `  Bash:        ${VARIABLE}=${SACKGASSE} npx playwright test`,
    "",
    "Dort lauscht nichts — das ist beabsichtigt. Eine Anfrage, die dort",
    "ankommt, ist ein fehlender Mock und soll im Lauf auffallen.",
  ].join("\n");
}

/**
 * Ermittelt das Proxy-Ziel wie Next und wirft, wenn es nicht auf das
 * Loopback-Interface zeigt.
 *
 * @param verzeichnis Verzeichnis, in dem die `.env`-Dateien liegen — das
 *   Verzeichnis der Playwright-Konfiguration, weil der `webServer` von dort
 *   startet und Next die Dateien aus seinem Arbeitsverzeichnis liest.
 * @returns Das geprüfte Ziel, zum Weitergeben an `webServer.env`.
 */
export function pruefeProxyZiel(verzeichnis: string): string {
  let gefunden: Herkunft;

  const ausUmgebung = process.env[VARIABLE]?.trim();
  if (ausUmgebung) {
    gefunden = { wert: ausUmgebung, quelle: `Umgebungsvariable ${VARIABLE}` };
  } else {
    for (const datei of ENV_DATEIEN) {
      const wert = ausDatei(join(verzeichnis, datei));
      if (wert) {
        gefunden = { wert, quelle: `frontend/${datei}` };
        break;
      }
    }
  }

  if (!gefunden) {
    return SACKGASSE;
  }

  if (!istLoopback(gefunden.wert)) {
    throw new Error(meldung(gefunden));
  }

  return gefunden.wert;
}
