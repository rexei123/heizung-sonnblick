/**
 * Die Gegenprobe zur Schranke: greift sie noch?
 *
 * **Warum das in der Suite steht und nicht in einer Anleitung.** Eine
 * Schranke, die niemand prüft, ist nach dem ersten „Aufräumen" eine
 * Funktion, die `true` zurückgibt — und der grüne Lauf sagt dann nichts
 * mehr über das, was sie verhindern sollte (§5.82, dritter Teil: ein
 * Diagnose-Schalter, der nichts kostet, gehört eingeschaltet). Hier wird
 * deshalb nicht das Ergebnis eines Laufs geprüft, sondern die
 * Entscheidung selbst: welches Ziel `pruefeProxyZiel` durchlässt und
 * welches es abweist.
 *
 * **Diese Datei öffnet keinen Browser** und holt `test` deshalb aus
 * `@playwright/test` statt aus `./fixtures`. Die Hülle dort hängt am
 * `page`-Fixture — sie würde für jeden dieser Fälle einen Browser
 * starten, der nichts zu tun hat. Der Standard „immer aus ./fixtures"
 * gilt für alles, was eine Seite öffnet.
 *
 * **Seriell**, weil die Fälle `process.env.API_PROXY_TARGET` setzen und
 * zurücksetzen. Parallel im selben Worker würden sie sich gegenseitig die
 * Umgebung umschreiben.
 */

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, test } from "@playwright/test";

import { pruefeProxyZiel } from "../proxy-ziel";

const PRODUKTION = "https://heizung-test.hoteltec.at";

test.describe.configure({ mode: "serial" });

/** Ein leeres Verzeichnis als Ersatz für `frontend/` — ohne `.env`-Dateien. */
function leeresVerzeichnis(): string {
  return mkdtempSync(join(tmpdir(), "proxy-ziel-"));
}

test.describe("Schranke gegen ungemockte Anfragen an die Produktion", () => {
  let verzeichnis: string;
  let vorher: string | undefined;

  test.beforeEach(() => {
    verzeichnis = leeresVerzeichnis();
    vorher = process.env.API_PROXY_TARGET;
    delete process.env.API_PROXY_TARGET;
  });

  test.afterEach(() => {
    if (vorher === undefined) delete process.env.API_PROXY_TARGET;
    else process.env.API_PROXY_TARGET = vorher;
    rmSync(verzeichnis, { recursive: true, force: true });
  });

  test("das Produktionsziel aus der Umgebung wird abgewiesen", () => {
    process.env.API_PROXY_TARGET = PRODUKTION;
    // Die Meldung muss das Ziel nennen: wer sie liest, soll nicht raten
    // müssen, welcher Server gemeint ist.
    expect(() => pruefeProxyZiel(verzeichnis)).toThrow(/heizung-test\.hoteltec\.at/);
  });

  test("das Produktionsziel aus .env.local wird abgewiesen", () => {
    // Der Fall, der den Anlass gegeben hat: die Shell ist leer, der Wert
    // steht in der Datei des Betreibers. Eine Schranke, die nur
    // `process.env` prüft, wäre hier grün — den Next-Prozess erreicht die
    // Datei trotzdem.
    writeFileSync(join(verzeichnis, ".env.local"), `API_PROXY_TARGET=${PRODUKTION}\n`, "utf8");
    expect(() => pruefeProxyZiel(verzeichnis)).toThrow(/\.env\.local/);
  });

  test("Anführungszeichen und angehängter Kommentar ändern daran nichts", () => {
    writeFileSync(
      join(verzeichnis, ".env.local"),
      `API_PROXY_TARGET="${PRODUKTION}"   # Live-Daten ansehen\n`,
      "utf8",
    );
    expect(() => pruefeProxyZiel(verzeichnis)).toThrow(/heizung-test\.hoteltec\.at/);
  });

  test("die Umgebung schlägt die Datei — so wie bei Next", () => {
    // Next überschreibt keine bereits gesetzte Variable. Genau darauf
    // beruht der Hinweis in der Fehlermeldung („in der Shell setzen").
    // Stimmte die Reihenfolge hier nicht, wäre der Hinweis falsch.
    writeFileSync(join(verzeichnis, ".env.local"), `API_PROXY_TARGET=${PRODUKTION}\n`, "utf8");
    process.env.API_PROXY_TARGET = "http://127.0.0.1:8000";
    expect(pruefeProxyZiel(verzeichnis)).toBe("http://127.0.0.1:8000");
  });

  test("ohne jede Konfiguration zeigt das Ziel auf das Loopback-Interface", () => {
    // Nicht auf `http://api:8000` — den Vorgabewert aus next.config.mjs.
    // Dass der Name in CI nicht auflöst, ist kein Schutz.
    const ziel = pruefeProxyZiel(verzeichnis);
    expect(new URL(ziel).hostname).toBe("127.0.0.1");
  });

  for (const ziel of [
    "http://localhost:3000",
    "http://127.0.0.1:8000",
    "http://127.0.0.2:8000",
    "http://[::1]:8000",
  ]) {
    test(`lokales Ziel ${ziel} ist erlaubt`, () => {
      process.env.API_PROXY_TARGET = ziel;
      expect(pruefeProxyZiel(verzeichnis)).toBe(ziel);
    });
  }

  for (const ziel of [
    "https://heizung.hoteltec.at",
    "http://api:8000",
    "http://10.0.0.5:8000",
    "http://localhost.hoteltec.at",
    "localhost:8000",
  ]) {
    test(`fremdes oder unlesbares Ziel ${ziel} wird abgewiesen`, () => {
      // `localhost.hoteltec.at` steht hier mit Absicht: ein Name, der mit
      // „localhost" anfängt, ist ein fremder Host. Eine Prüfung per
      // `startsWith` hätte ihn durchgelassen.
      // `localhost:8000` ohne Schema ist für `new URL` kein Host — ein
      // Ziel, das die Schranke nicht lesen kann, wird nicht geraten.
      process.env.API_PROXY_TARGET = ziel;
      expect(() => pruefeProxyZiel(verzeichnis)).toThrow();
    });
  }
});
