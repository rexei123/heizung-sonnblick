import { test, expect, type Page } from "@playwright/test";

/**
 * Sprint 20c (B-20c-1) — die Geräteliste darf nicht still abschneiden.
 *
 * **Befund, 01.10.2026 auf dem Server belegt:** `device` hatte 104 Zeilen,
 * `/devices` zeigte 100. Gefehlt haben die vier mit den höchsten IDs — die
 * zuletzt eingepairten, also genau die, die bei der Montage gebraucht
 * werden. Ohne Fehlermeldung: die Liste sah vollständig aus.
 *
 * Ursache war nicht der Endpoint, sondern der Client. `GET /api/v1/devices`
 * ist paginiert und liefert ohne `limit` 100 Zeilen; `devicesApi.list` hat
 * eine Seite geholt und sie für die ganze Liste genommen. Seit 20c holt es
 * alle Seiten (`SEITE = 100`, dieselbe Zahl wie der Server-Default).
 *
 * Diese Datei prüft die **Schleife**, nicht die Oberfläche: der Mock wertet
 * `limit` und `offset` aus und liefert echte Teilmengen. Ein Mock, der
 * unabhängig von den Parametern immer alles zurückgibt, hätte den Bug nie
 * gezeigt — er war ja genau die Annahme, die falsch war.
 *
 * Die Zählung der Requests gehört mit zur Prüfung. Ohne sie wäre „105 Zeilen
 * sichtbar" auch mit einem Mock erfüllt, der `limit` ignoriert.
 *
 * Route-Muster ist eine **Regex mit `$`** (§5.54): sie erfasst die URL mit
 * und ohne Query-String und trifft `/devices/5/hardware-status` nicht.
 */

const NOW = Date.now();
const iso = (offsetMs = 0) => new Date(NOW - offsetMs).toISOString();

/** Seitengröße in `devicesApi.list`. Muss mit `devices.ts` übereinstimmen. */
const SEITE = 100;

function makeDevice(id: number) {
  const nr = String(id).padStart(3, "0");
  return {
    id,
    dev_eui: id.toString(16).padStart(16, "0"),
    app_eui: null,
    kind: "thermostat" as const,
    vendor: "mclimate" as const,
    model: "vicki",
    label: `Vicki-${nr}`,
    heating_zone_id: null,
    retired_at: null,
    retired_reason: null,
    replaced_by_device_id: null,
    last_seen_at: iso(5 * 60 * 1000),
    firmware_version: "4.2",
    health_state: "healthy" as const,
    battery_state: "ok" as const,
    battery_voltage_median: 3.2,
    battery_jump_at: null,
    battery_last_voltage: 3.2,
    battery_last_at: iso(5 * 60 * 1000),
    created_at: iso(86400 * 1000),
    updated_at: iso(),
    hardware_number: null,
    heating_zone: null,
    active_override: null,
    latest_reading: null,
  };
}

interface Aufrufe {
  /** Je Request das Paar, mit dem er kam — in der Reihenfolge des Eintreffens. */
  seiten: { limit: number; offset: number }[];
}

/**
 * Mockt den Listen-Endpoint als **echte** Paginierung über `gesamt` Geräte.
 *
 * `limit`/`offset` werden ausgewertet und eine Teilmenge geliefert, genau wie
 * das Backend es tut. Fehlt `limit`, greift der Server-Default 100 — damit
 * fällt auch auf, wenn der Client das Setzen vergisst.
 */
async function mockPaginiert(
  page: Page,
  gesamt: number,
): Promise<Aufrufe> {
  const alle = Array.from({ length: gesamt }, (_, i) => makeDevice(i + 1));
  const aufrufe: Aufrufe = { seiten: [] };

  await page.route(/.*\/api\/v1\/devices(\?.*)?$/, (route) => {
    const url = new URL(route.request().url());
    const limit = Number(url.searchParams.get("limit") ?? String(SEITE));
    const offset = Number(url.searchParams.get("offset") ?? "0");
    aufrufe.seiten.push({ limit, offset });
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(alle.slice(offset, offset + limit)),
    });
  });

  // HardwareStatusBadge fetcht je Gerät — generisch und billig beantworten.
  await page.route("**/api/v1/devices/*/hardware-status", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "inactive",
        last_seen: null,
        frames_in_window: 0,
        window_minutes: 30,
      }),
    }),
  );

  return aufrufe;
}

test.describe("Sprint 20c — Geräteliste über alle Seiten", () => {
  test("105 Geräte: alle sichtbar, zwei Seiten geholt", async ({ page }) => {
    // Der Befund selbst, einen Hauch größer als der Hotel-Bestand von 104.
    const aufrufe = await mockPaginiert(page, 105);
    await page.goto("/devices?sort=label");

    await expect(page.locator("tbody tr")).toHaveCount(105);
    // Das Gerät mit der höchsten ID ist das, das vorher gefehlt hat.
    await expect(page.locator("tbody tr").last()).toContainText("Vicki-105");

    expect(aufrufe.seiten).toEqual([
      { limit: SEITE, offset: 0 },
      { limit: SEITE, offset: SEITE },
    ]);
  });

  test("Grenzfall genau 100: zweite Seite ist leer, Liste trotzdem komplett", async ({
    page,
  }) => {
    // Hier entscheidet die Abbruchbedingung: die erste Seite kommt VOLL
    // zurück, und damit ist offen, ob es weitergeht. Wer „voll" als „fertig"
    // liest, hat genau den Bug von vorher — nur ohne sichtbare Lücke, weil
    // es zufällig passt.
    const aufrufe = await mockPaginiert(page, 100);
    await page.goto("/devices?sort=label");

    await expect(page.locator("tbody tr")).toHaveCount(100);

    expect(aufrufe.seiten).toEqual([
      { limit: SEITE, offset: 0 },
      { limit: SEITE, offset: SEITE },
    ]);
  });

  test("Grenzfall 101: der eine auf der zweiten Seite fehlt nicht", async ({
    page,
  }) => {
    const aufrufe = await mockPaginiert(page, 101);
    await page.goto("/devices?sort=label");

    await expect(page.locator("tbody tr")).toHaveCount(101);
    await expect(page.locator("tbody tr").last()).toContainText("Vicki-101");

    expect(aufrufe.seiten).toHaveLength(2);
  });

  test("99 Geräte: ein Aufruf genügt, es wird nicht blind weitergeblättert", async ({
    page,
  }) => {
    // Die Gegenprobe zur Schleife. Ohne sie könnte der Client bei jedem
    // Laden eine überflüssige leere Seite holen, und niemand würde es
    // merken — fünf Aufrufer auf jeder Seite der Oberfläche.
    const aufrufe = await mockPaginiert(page, 99);
    await page.goto("/devices?sort=label");

    await expect(page.locator("tbody tr")).toHaveCount(99);

    expect(aufrufe.seiten).toEqual([{ limit: SEITE, offset: 0 }]);
  });
});

test.describe("Sprint 20c — die Zuordnung sieht alle Pool-Geräte", () => {
  test("Pairing-Auswahl listet alle 105 unzugeordneten Geräte", async ({
    page,
  }) => {
    // Der teuerste der fünf Aufrufer: hier wird montiert. Alle 105 Geräte
    // sind Pool-Geräte (heating_zone_id = null), und die höchsten IDs sind
    // die zuletzt eingepairten — vorher waren genau die nicht auswählbar.
    const aufrufe = await mockPaginiert(page, 105);
    await page.route(/.*\/api\/v1\/rooms(\?.*)?$/, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      }),
    );

    await page.goto("/devices/pair");

    await expect(
      page.getByText("105 Gerät(e) noch keiner Heizzone zugeordnet:"),
    ).toBeVisible();
    expect(aufrufe.seiten).toHaveLength(2);
  });
});
