import { expect, test } from "./fixtures";

/**
 * Alle Dashboard-Kacheln sind gleich hoch (Vorgabe des Betreibers, 10.11.2026).
 *
 * **Was hier geprüft wird, und warum es ein eigener Test ist.** „Gleich
 * hoch" ist eine Eigenschaft des **Rasters**, nicht einer Komponente —
 * sie entsteht aus `auto-rows-fr` am Container **und** `h-full` an jeder
 * Hülle **und** `h-full` an der Karte. Fällt eines der drei weg, sieht
 * man es an keinem Komponenten-Test, sondern nur an den gemessenen
 * Höhen. Deshalb misst diese Datei `boundingBox()` statt Klassennamen zu
 * prüfen: eine Klasse, die da steht, ist kein Beleg dafür, dass sie
 * wirkt.
 *
 * Drei Breiten, weil das Raster drei Formen hat: eine Spalte (mobil),
 * zwei (Tablet), drei (Desktop). „Gleich hoch über das ganze Raster"
 * heißt bei zwei Spalten etwas anderes als bei drei — bei drei Spalten
 * kann eine hohe Karte in Zeile 1 alle Zeilen mitziehen.
 *
 * **Die Toleranz von 1 px** ist Rundung im Layout-Engine, nicht
 * Nachlässigkeit: `1fr`-Zeilen kommen bei ungerader Pixelhöhe als
 * `.5`-Werte heraus.
 */

interface Kpi {
  rooms_occupied: number;
  rooms_total: number;
  avg_temperature_celsius: number | null;
  devices_online: number;
  devices_assigned: number;
  devices_pool: number;
  active_overrides: number;
  zones_window_open: number;
  last_engine_tick: string | null;
  battery_low_count: number;
  valve_check_count: number;
  room_too_warm_count: number;
  funkempfang_stufe: "online" | "verzoegert" | "keine_meldungen" | "unbekannt";
  funkempfang_letzte_meldung: string | null;
  funkempfang_alter_min: number | null;
  funkempfang_meldungen_10min: number;
  fenstererkennung_aktiv: boolean;
  befehle_nicht_angenommen: number;
  relais_zonen_stumm: number;
  relais_zonen_stille_min: number | null;
}

const BASE_KPI: Kpi = {
  rooms_occupied: 1,
  rooms_total: 30,
  avg_temperature_celsius: 21.4,
  devices_online: 4,
  devices_assigned: 4,
  devices_pool: 0,
  active_overrides: 0,
  zones_window_open: 0,
  last_engine_tick: new Date(Date.now() - 60_000).toISOString(),
  battery_low_count: 0,
  valve_check_count: 0,
  room_too_warm_count: 0,
  funkempfang_stufe: "online" as const,
  funkempfang_letzte_meldung: new Date(Date.now() - 60_000).toISOString(),
  funkempfang_alter_min: 1,
  funkempfang_meldungen_10min: 104,
  fenstererkennung_aktiv: false,
  befehle_nicht_angenommen: 0,
  relais_zonen_stumm: 0,
  relais_zonen_stille_min: null,
};

async function mockDashboard(
  page: import("@playwright/test").Page,
  payload: Partial<Kpi> = {},
): Promise<void> {
  await page.route("**/api/v1/dashboard/kpi", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...BASE_KPI, ...payload }),
    });
  });
  // Die Belegungsliste hat eine eigene Datenquelle und zählt als Kachel
  // mit. Ohne Mock liefe sie in den Fehlerzustand — und der hat eine
  // andere Höhe, womit der Test etwas anderes messen würde als gemeint.
  await page.route(
    "**/api/v1/integrations/occupancy-import/log",
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "green",
          last_success_at: new Date(Date.now() - 3_600_000).toISOString(),
          expected_by_local: "12:00",
          expected_by_local_label: "12:00 MEZ",
          today_received: true,
          imports: [],
        }),
      });
    },
  );
}

async function kachelHoehen(
  page: import("@playwright/test").Page,
): Promise<number[]> {
  const karten = page.getByTestId("kpi-card");
  await expect(karten.first()).toBeVisible();
  // **Erst messen, wenn die Schriften geladen sind.** Vorher rendert der
  // Browser die Material-Symbols-Ligaturen als Text, und der verändert
  // das Layout — zwei Tests dieser Datei sind genau daran gescheitert,
  // und nur im Dateilauf, nicht einzeln. Das ist keine Nachsicht
  // gegenüber dem Produkt: dass die Kacheln **auch** während des
  // Ladens gleich hoch bleiben, sichert `overflow-hidden` am
  // Symbol-Kasten. Hier wird die gesetzte Lage gemessen, nicht der
  // Übergang.
  await page.evaluate(() => document.fonts.ready);
  // **Alle Höhen in einem Durchgang**, nicht zwölf Einzelabfragen.
  // Zwischen zwei `boundingBox()`-Aufrufen kann React neu zeichnen — die
  // Belegungsliste hat eine eigene Abfrage und trifft später ein —, und
  // dann zeigt der Locator auf ein abgelöstes Element und liefert
  // `null`. Genau daran ist diese Datei am 10.11.2026 gescheitert: allein
  // grün, im Dateilauf rot. Eine Messung, die mitten im Neuzeichnen
  // stattfindet, misst nichts.
  return karten.evaluateAll((els) =>
    els.map((e) => e.getBoundingClientRect().height),
  );
}

function alleGleich(hoehen: number[]): void {
  expect(hoehen.length).toBeGreaterThan(1);
  const erste = hoehen[0];
  for (const [i, h] of hoehen.entries()) {
    expect(
      Math.abs(h - erste),
      `Kachel ${i} ist ${h} px hoch, die erste ${erste} px — ` +
        `alle Kacheln müssen gleich hoch sein (auto-rows-fr + h-full)`,
    ).toBeLessThanOrEqual(1);
  }
}

test.describe("Dashboard-Kacheln: gleiche Höhe", () => {
  for (const [name, breite, hoehe] of [
    ["Desktop, drei Spalten", 1280, 900],
    ["Tablet, zwei Spalten", 768, 1024],
    ["Mobil, eine Spalte", 390, 844],
  ] as const) {
    test(`${name}: alle Kacheln gleich hoch`, async ({ page }) => {
      await page.setViewportSize({ width: breite, height: hoehe });
      await mockDashboard(page);
      await page.goto("/");
      alleGleich(await kachelHoehen(page));
    });
  }

  test("ein langer Wert macht die Kachel nicht höher", async ({ page }) => {
    // „keine Meldungen" ist der längste Wert, den das Raster heute
    // kennt. Ohne `truncate` bricht er in der schmalen Spalte um, die
    // Karte wird eine Zeile höher — und weil die Zeilen gleich hoch
    // sind, **alle anderen mit ihr**. Genau diese Kopplung macht den
    // Umbruch von einem Schönheitsfehler zu einem Rasterfehler.
    await page.setViewportSize({ width: 768, height: 1024 });
    await mockDashboard(page, {
      funkempfang_stufe: "keine_meldungen",
      funkempfang_alter_min: 42,
    });
    await page.goto("/");

    const hoehen = await kachelHoehen(page);
    alleGleich(hoehen);

    // Und der Wert selbst steht auf **einer** Zeile. 2xl ist 32 px
    // Zeilenhöhe; alles über 40 px ist ein Umbruch.
    const wert = page.getByText("keine Meldungen", { exact: true });
    await expect(wert).toBeVisible();
    const box = await wert.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.height, "der große Wert ist umgebrochen").toBeLessThan(40);
  });

  test("ohne Symbol-Schrift bleiben die Kacheln gleich hoch", async ({
    page,
  }) => {
    // Die Kacheln sind auch dann gleich hoch, wenn die Symbol-Schrift
    // **gar nicht** kommt — dann rendert der Browser die Ligatur-Namen
    // als Text, und das ist der Zustand, in dem ein Layout gern kippt.
    //
    // **Was dieser Test nicht belegt** (Richtigstellung vom 10.11.2026):
    // er sichert **nicht** `overflow-hidden` am Symbol-Kasten ab. Die
    // Probe „Klasse entfernt" bleibt grün, weil die Höhe an `h-10`
    // hängt, nicht am Inhalt. Die Klasse verhindert, dass der
    // Ligatur-Text sichtbar ins Etikett läuft — das ist Aussehen, nicht
    // Layout, und dafür gibt es hier keinen Test.
    //
    // Was er **belegt**: dass eine fehlende Schrift die Zeilenhöhen
    // nicht verschiebt. Nimmt jemand dem Symbol-Kasten seine feste
    // Größe (`h-10 w-10 shrink-0`), fällt dieser Test.
    await page.route("**/fonts/material-symbols-outlined-*.woff2", (route) =>
      route.abort(),
    );
    await page.setViewportSize({ width: 768, height: 1024 });
    await mockDashboard(page);
    await page.goto("/");

    // Ohne Schrift gibt es kein `document.fonts.ready` abzuwarten — der
    // Helfer tut es trotzdem, und das ist richtig: er wartet dann auf
    // die übrigen Schriften und damit auf eine gesetzte Lage.
    alleGleich(await kachelHoehen(page));
  });

  test("der große Wert trägt seinen vollen Text als title", async ({
    page,
  }) => {
    // Zweiter Test aus einer Probe, die nichts fand: `title` am Wert
    // entfernt → alles grün. Gekürzt wird mit `truncate`, und ein
    // gekürzter Wert ohne `title` ist eine Zahl, die man nicht mehr
    // lesen kann — die Kürzung ist nur zumutbar, weil der volle Text
    // beim Darüberfahren erscheint.
    await mockDashboard(page, { funkempfang_stufe: "keine_meldungen" });
    await page.goto("/");
    const wert = page.getByText("keine Meldungen", { exact: true });
    await expect(wert).toHaveAttribute("title", "keine Meldungen");
  });

  test("Lade-Skelett ist so hoch wie die fertige Kachel", async ({ page }) => {
    // Der Grund für diesen Test: vorher hatte das Skelett eine feste
    // Höhe (`h-28`, 112 px) und die fertige Karte 118 — die Seite ist
    // bei jedem Aufruf gesprungen. Eine Zahl, die niemand nachrechnet,
    // altert mit der ersten neuen Zeile.
    let freigeben: () => void = () => {};
    const warten = new Promise<void>((resolve) => {
      freigeben = resolve;
    });
    await page.route("**/api/v1/dashboard/kpi", async (route) => {
      await warten;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(BASE_KPI),
      });
    });
    await page.route(
      "**/api/v1/integrations/occupancy-import/log",
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            status: "green",
            last_success_at: new Date(Date.now() - 3_600_000).toISOString(),
            expected_by_local: "12:00",
            expected_by_local_label: "12:00 MEZ",
            today_received: true,
            imports: [],
          }),
        });
      },
    );

    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/");

    const skelette = page.locator(
      '[data-testid="kpi-card"][aria-busy="true"]',
    );
    await expect(skelette.first()).toBeVisible();
    // Alle Karten, nicht nur die beschäftigten: siehe die Begründung
    // unten am Vergleich.
    const anzahlWaehrendLaden = await page.getByTestId("kpi-card").count();
    const skelettBox = await skelette.first().boundingBox();
    expect(skelettBox).not.toBeNull();

    freigeben();
    await expect(
      page.locator('[data-testid="kpi-card"][aria-busy="true"]'),
    ).toHaveCount(0);
    const fertig = (await kachelHoehen(page))[0];

    expect(
      Math.abs(skelettBox!.height - fertig),
      `Skelett ${skelettBox!.height} px, fertige Kachel ${fertig} px — ` +
        `die Seite springt beim Laden`,
    ).toBeLessThanOrEqual(2);

    // **Und die Anzahl, nicht nur die Höhe.** Gleich hohe Platzhalter in
    // der falschen Zahl lassen die Seite genauso springen — wer eine
    // Kachel in `buildCards` ergänzt und in `CARD_META` vergisst, baut
    // genau das. Eine Mutationsprobe am 13.11.2026 hat gezeigt, dass
    // dafür kein Test existierte: Eintrag aus `CARD_META` entfernt, 23
    // von 23 grün.
    //
    // **Geprüft wird die Eigenschaft, nicht die Zahl:** die Zahl der
    // Karten darf sich beim Eintreffen der Daten nicht ändern. Eine Zahl
    // im Test wäre eine zweite Stelle, die bei jeder neuen Kachel
    // nachzuziehen ist — und die man dann nachzieht, ohne zu prüfen.
    //
    // Gezählt werden **alle** Karten, nicht nur die beschäftigten. Die
    // Kachel „Belegungsliste" steht in `buildCards` und bewusst nicht in
    // `CARD_META` (Begründung dort), bringt aber ihren eigenen
    // Platzhalter mit, solange ihre eigene Abfrage lädt. In der Summe
    // stimmen beide Phasen deshalb überein — und genau diese Summe ist
    // das, was der Betrachter sieht.
    const fertigeKarten = await page.getByTestId("kpi-card").count();
    expect(
      anzahlWaehrendLaden,
      `${anzahlWaehrendLaden} Karten beim Laden, danach ${fertigeKarten} — ` +
        `die Seite springt beim Laden`,
    ).toBe(fertigeKarten);
  });

  test('Fenster offen: Wert „inaktiv", Grund in der Zusatzzeile', async ({
    page,
  }) => {
    await mockDashboard(page, { fenstererkennung_aktiv: false });
    await page.goto("/");

    await expect(page.getByText("Fenster offen")).toBeVisible();
    await expect(page.getByText("inaktiv", { exact: true })).toBeVisible();
    await expect(
      page.getByText("Erkennung im Gerät ausgeschaltet"),
    ).toBeVisible();
    // Die 0 wäre die gefährlichere Anzeige: sie liest sich als „es ist
    // kein Fenster offen" statt als „niemand hat gemessen".
    await expect(page.getByText("keine Rückmeldung vom Gerät")).toHaveCount(0);
  });

  test("Fenster offen: bei aktiver Erkennung wieder die Zahl", async ({
    page,
  }) => {
    // Die Gegenprobe. Ohne sie könnte die Kachel dauerhaft „inaktiv"
    // zeigen, und niemand würde es merken, solange die Erkennung aus
    // ist — also genau so lange, wie heute.
    await mockDashboard(page, {
      fenstererkennung_aktiv: true,
      zones_window_open: 3,
    });
    await page.goto("/");

    await expect(page.getByText("Fenster offen")).toBeVisible();
    await expect(page.getByText("3", { exact: true }).first()).toBeVisible();
    await expect(
      page.getByText("Erkennung im Gerät ausgeschaltet"),
    ).toHaveCount(0);
  });
});
