import { test, expect } from "./fixtures";

/**
 * Paket 1 — Handbuch in der Software.
 *
 * Geprüft wird, was man von außen sehen kann und was beim Umbau leise
 * kaputtgehen würde:
 *
 * 1. Die Seite lädt und zeigt Artikel — ohne Backend. Das ist der
 *    eigentliche Punkt: das Handbuch ist genau dann wichtig, wenn etwas
 *    anderes nicht geht. Eine Hilfeseite, die eine laufende API braucht,
 *    schweigt im Ernstfall (§5.76, Wirkung statt Mechanik).
 * 2. Die Suche findet eine Fundstelle und springt auf den **Abschnitt**.
 * 3. Das „?" auf einer Seite führt zu dem Artikel, der zu ihr gehört —
 *    und erscheint nicht dort, wo es keinen gibt.
 * 4. Die Druckansicht trägt alle Artikel und keine lebenden Zahlen.
 *
 * **Die Artikel sind beim Bauen in die Seite gewandert** (statisch
 * vorgerendert, `dynamic = "error"` in jeder der drei Seiten). Deshalb
 * fängt dieser Test alle API-Aufrufe mit einer leeren Antwort ab: was
 * trotzdem noch steht, steht wirklich in der Seite.
 */

test.describe("Paket 1 Handbuch", () => {
  test.beforeEach(async ({ page }) => {
    // Alles aus dem Netz leer beantworten. Die Hülle registriert ihre
    // `/auth/me`-Route davor; Playwright trifft die zuletzt registrierte
    // zuerst, deshalb steht dieser Fang hier und nicht nach einer
    // eigenen Rollen-Route (Begründung in `fixtures.ts`).
    await page.route("**/api/v1/**", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
    );
  });

  test("Übersicht listet die Artikel auch ohne Backend", async ({ page }) => {
    await page.goto("/handbuch");

    await expect(page.getByRole("heading", { level: 1, name: "Handbuch" })).toBeVisible();

    // Mindestens die drei Pflichtstücke aus dem Auftrag: Heizlogik,
    // ein Seiten-Artikel, ein Ablauf an der Rezeption.
    const treffer = page.getByTestId("handbuch-treffer");
    expect(await treffer.count()).toBeGreaterThanOrEqual(20);
    await expect(treffer.filter({ hasText: "Wie das Haus heizt" })).toHaveCount(1);
    await expect(treffer.filter({ hasText: "Glossar" })).toHaveCount(1);
  });

  test("Suche liefert Fundstelle und Sprungziel im Abschnitt", async ({ page }) => {
    await page.goto("/handbuch");

    await page.getByTestId("handbuch-suche").fill("Betriebszeit");

    const treffer = page.getByTestId("handbuch-treffer");
    expect(await treffer.count()).toBeGreaterThan(0);

    // Die Trefferzahl nennt die Frage — eine Liste ohne Bezug zur
    // Eingabe wäre nicht unterscheidbar von einer ungefilterten.
    await expect(page.getByTestId("handbuch-trefferzahl")).toContainText("Betriebszeit");

    // Mindestens ein Treffer zeigt eine hervorgehobene Fundstelle.
    expect(await page.locator("mark").count()).toBeGreaterThan(0);

    // Und führt auf einen Artikel; wenn der Fund in einem Abschnitt
    // stand, mit Anker.
    const ziel = await treffer.first().getAttribute("href");
    expect(ziel).toMatch(/^\/handbuch\/[a-z0-9-]+(#[a-z0-9-]+)?$/);
  });

  test("Suche ohne Treffer sagt es statt leer zu bleiben", async ({ page }) => {
    await page.goto("/handbuch");

    await page.getByTestId("handbuch-suche").fill("xyzqwertznichtvorhanden");

    await expect(page.getByTestId("handbuch-kein-treffer")).toBeVisible();
    await expect(page.getByTestId("handbuch-treffer")).toHaveCount(0);
  });

  test("Artikel zeigt Stand, Abschnitts-Anker und den Weg zur Seite", async ({ page }) => {
    await page.goto("/handbuch/seite-zimmer-detail");

    await expect(
      page.getByRole("heading", { level: 1, name: "Ein Zimmer im Detail" }),
    ).toBeVisible();
    await expect(page.getByText(/Stand 20\d\d-\d\d-\d\d/)).toBeVisible();

    // Verweis auf die beschriebene Seite der Software.
    await expect(page.getByRole("link", { name: /Zur Seite in der Software/ })).toBeVisible();

    // Jede Hauptüberschrift trägt ihren Anker — das ist die Grundlage
    // dafür, dass die Suche auf einen Abschnitt verlinken kann.
    const ueberschriften = page.locator("h2[id]");
    expect(await ueberschriften.count()).toBeGreaterThan(0);
  });

  test("unbekannter Artikel ergibt 404 statt einer leeren Seite", async ({ page }) => {
    const antwort = await page.goto("/handbuch/gibt-es-nicht");
    expect(antwort?.status()).toBe(404);
  });

  test("das ? führt von der Zimmerliste zum passenden Artikel", async ({ page }) => {
    await page.goto("/zimmer");

    const hilfe = page.getByTestId("seiten-hilfe");
    await expect(hilfe).toBeVisible();
    await expect(hilfe).toHaveAttribute("href", "/handbuch/seite-zimmeruebersicht");
    // Ein Link, der den Reiter wechselt, sagt es in seiner Beschriftung.
    await expect(hilfe).toHaveAttribute("aria-label", /neuer Reiter/);
  });

  test("auf dem Handbuch selbst gibt es kein ?", async ({ page }) => {
    await page.goto("/handbuch");
    await expect(page.getByTestId("seiten-hilfe")).toHaveCount(0);
  });

  test("Druckansicht trägt alle Artikel und keine lebenden Zahlen", async ({ page }) => {
    await page.goto("/handbuch/drucken");

    // Erst auf etwas warten, dann zählen. `locator.count()` wartet
    // **nicht** — der Zähler lief hier zuerst vor dem Rendern und
    // meldete 0, was wie eine leere Druckseite aussah. Dieselbe Falle
    // steckt in jeder `count()`-Prüfung ohne vorangehendes `expect`.
    await expect(
      page.getByRole("heading", { level: 1, name: /Handbuch Heizungssteuerung/ }),
    ).toBeVisible();

    const artikel = page.locator(".handbuch-druck-artikel");
    await expect(artikel.first()).toBeVisible();
    expect(await artikel.count()).toBeGreaterThanOrEqual(20);

    // Die Marke `{{werte}}` wird auf Papier zu einem Hinweis, nicht zu
    // einer Tabelle vom Ausdruckstag.
    await expect(page.getByTestId("handbuch-werte")).toHaveCount(0);
    await expect(
      page.getByText(/Auf Papier wären sie der Stand des Ausdruckstages/),
    ).toBeVisible();

    // Die Karte der Heizlogik wird gedruckt — die Reihenfolge der
    // Schichten ändert sich nicht mit einem Sollwert.
    await expect(page.getByTestId("heizlogik-karte")).toHaveCount(1);
  });

  test("keine unbekannte Marke und keine Konsolenfehler im Artikel", async ({ page }) => {
    // §5.86: die Messung gehört in die Suite, nicht in eine Anleitung.
    const fehler: string[] = [];
    page.on("console", (m) => {
      if (m.type() === "error") fehler.push(m.text());
    });

    await page.goto("/handbuch/heizlogik");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

    await expect(page.getByText(/Unbekannte Marke im Artikel/)).toHaveCount(0);
    expect(fehler, `Konsolenfehler: ${fehler.join(" | ")}`).toHaveLength(0);
  });
});
