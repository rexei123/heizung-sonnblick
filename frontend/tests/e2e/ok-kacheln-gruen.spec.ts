/**
 * Grüne Icons bei Ok-Kacheln — die Regeln, an einer Stelle geprüft.
 *
 * **Vorgabe des Betreibers, 16.11.2026:** grün NUR, wenn der Zustand
 * belegt in Ordnung ist. Unbekannt oder inaktiv bleibt grau, ein Problem
 * bleibt orange oder rot wie bisher.
 *
 * Geprüft wird `data-tone` an der Karte, nicht die Tailwind-Klasse. Die
 * Klasse ist die Umsetzung, `data-tone` ist die **Entscheidung** — und die
 * Entscheidung ist das, was vorgegeben wurde. Ein Test auf die Klasse
 * würde beim ersten Umbenennen eines Tokens rot, ohne dass sich an der
 * Aussage etwas ändert.
 *
 * **Jede Kachel steht hier zweimal:** einmal im Ok-Zustand und einmal
 * gestört. Nur im Ok-Zustand zu prüfen hieße, nicht zeigen zu können,
 * dass die Regel überhaupt greift — der Fehler vom 15.11. am ADR-Plugin,
 * nur in der Oberfläche (§5.55).
 *
 * **Der wichtigste Fall ist „Fenster offen" bei ausgeschalteter
 * Erkennung.** Dort steht 0, und 0 sieht aus wie ein Befund. Grün wäre
 * eine Entwarnung für eine Messung, die nicht läuft — am 07.11.2026 stand
 * hausweit keine einzige Zeile `open_window = true`, bei 49 belegten
 * Temperatureinbrüchen allein in Zimmer 306.
 */

import { expect, test } from "./fixtures";

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
  platte_prozent: number;
  platte_frei_gb: number;
  platte_warnt: boolean;
}

/** Der Normalfall: alles in Ordnung, nichts unbekannt. */
const GESUND: Kpi = {
  rooms_occupied: 0,
  rooms_total: 47,
  avg_temperature_celsius: 21.4,
  devices_online: 103,
  devices_assigned: 103,
  devices_pool: 3,
  active_overrides: 0,
  zones_window_open: 0,
  last_engine_tick: new Date(Date.now() - 60_000).toISOString(),
  battery_low_count: 0,
  valve_check_count: 0,
  room_too_warm_count: 0,
  funkempfang_stufe: "online",
  funkempfang_letzte_meldung: new Date(Date.now() - 60_000).toISOString(),
  funkempfang_alter_min: 1,
  funkempfang_meldungen_10min: 104,
  // **Aktiv und null offene Fenster** ist der einzige Ok-Zustand dieser
  // Kachel. Der Normalfall im Haus ist seit dem 07.11. ein anderer, und
  // genau deshalb steht der unten als eigener Fall.
  fenstererkennung_aktiv: true,
  befehle_nicht_angenommen: 0,
  relais_zonen_stumm: 0,
  relais_zonen_stille_min: null,
  platte_prozent: 66,
  platte_frei_gb: 25.0,
  platte_warnt: false,
};

async function mockKpi(
  page: import("@playwright/test").Page,
  payload: Partial<Kpi>,
): Promise<void> {
  await page.route("**/api/v1/dashboard/kpi", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ ...GESUND, ...payload }),
    });
  });
  // Die Belegungsliste hat eine eigene Quelle und liefe sonst in den
  // Fehlerzustand — sie zählt als Karte mit und würde die Suche nach
  // Labels nicht stören, aber ein Fehlerzustand im Raster macht die
  // Fehlersuche unnötig schwer.
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
          expected_by_local_label: "12:00 MESZ",
          today_received: true,
          imports: [],
        }),
      });
    },
  );
}

async function tonVon(
  page: import("@playwright/test").Page,
  kachel: string,
): Promise<string | null> {
  const karte = page.getByTestId("kpi-card").filter({ hasText: kachel });
  await expect(karte).toBeVisible();
  return karte.getAttribute("data-tone");
}

interface Fall {
  kachel: string;
  /** Was die Kachel im Ok-Zustand zeigen muss. */
  ok: string;
  /** Die Störung und der Ton, den sie bekommt. */
  stoerung: Partial<Kpi>;
  gestoert: string;
  /** Warum dieser Ton — steht in der Testausgabe, wenn es rot wird. */
  grund: string;
}

const FAELLE: Fall[] = [
  {
    kachel: "Geräte online",
    ok: "success-soft",
    stoerung: { devices_online: 101 },
    gestoert: "warning-soft",
    grund: "grün, wenn alle zugeordneten Geräte online sind (Lager zählt nicht)",
  },
  {
    kachel: "Funk-Empfang",
    ok: "success-soft",
    stoerung: { funkempfang_stufe: "verzoegert" },
    gestoert: "warning-soft",
    grund: "grün bei „online“",
  },
  {
    kachel: "Letzter Algorithmen-Lauf",
    ok: "success-soft",
    stoerung: {
      last_engine_tick: new Date(Date.now() - 3_600_000).toISOString(),
    },
    gestoert: "warning-soft",
    grund: "grün, wenn jünger als die Schwelle",
  },
  {
    kachel: "Schwache Batterie",
    ok: "success-soft",
    stoerung: { battery_low_count: 3 },
    gestoert: "warning-soft",
    grund: "grün bei 0",
  },
  {
    kachel: "Befehle nicht angenommen",
    ok: "success-soft",
    stoerung: { befehle_nicht_angenommen: 2 },
    gestoert: "warning-soft",
    grund: "grün bei 0",
  },
  {
    kachel: "Relais-Zone stumm",
    ok: "success-soft",
    stoerung: { relais_zonen_stumm: 1, relais_zonen_stille_min: 840 },
    gestoert: "danger-soft",
    grund: "grün bei 0, rot ab 1",
  },
  {
    kachel: "Ventil prüfen",
    ok: "success-soft",
    stoerung: { valve_check_count: 2 },
    gestoert: "warning-soft",
    grund: "grün bei 0 — nicht in der Liste, aber dieselbe Familie",
  },
  {
    kachel: "Zimmer zu warm",
    ok: "success-soft",
    stoerung: { room_too_warm_count: 1 },
    gestoert: "danger-soft",
    grund: "grün bei 0, rot ab 1",
  },
  {
    kachel: "Plattenplatz",
    ok: "success-soft",
    stoerung: { platte_prozent: 91, platte_frei_gb: 6.5, platte_warnt: true },
    gestoert: "danger-soft",
    grund: "grün unter der Warnschwelle (die steht im Backend)",
  },
];

test.describe("Grüne Icons bei Ok-Kacheln (16.11.2026)", () => {
  for (const fall of FAELLE) {
    test(`${fall.kachel}: grün im Ok-Zustand — ${fall.grund}`, async ({
      page,
    }) => {
      await mockKpi(page, {});
      await page.goto("/");
      expect(await tonVon(page, fall.kachel)).toBe(fall.ok);
    });

    test(`${fall.kachel}: nicht grün, wenn gestört`, async ({ page }) => {
      await mockKpi(page, fall.stoerung);
      await page.goto("/");
      expect(await tonVon(page, fall.kachel)).toBe(fall.gestoert);
    });
  }

  test("Fenster offen bleibt GRAU, solange die Erkennung aus ist", async ({
    page,
  }) => {
    // **Der Fall, für den die Dreistufigkeit gebaut ist.** Die Kachel
    // zeigt dann „inaktiv" und keine Zahl; grün wäre eine Entwarnung für
    // eine Messung, die nicht läuft.
    await mockKpi(page, { fenstererkennung_aktiv: false, zones_window_open: 0 });
    await page.goto("/");
    const karte = page.getByTestId("kpi-card").filter({ hasText: "Fenster offen" });
    await expect(karte).toContainText("inaktiv");
    expect(await karte.getAttribute("data-tone")).toBe("neutral");
  });

  test("Fenster offen wird grün, wenn die Erkennung läuft und nichts offen ist", async ({
    page,
  }) => {
    await mockKpi(page, { fenstererkennung_aktiv: true, zones_window_open: 0 });
    await page.goto("/");
    expect(await tonVon(page, "Fenster offen")).toBe("success-soft");
  });

  test("Fenster offen wird orange, wenn die Erkennung läuft und etwas offen ist", async ({
    page,
  }) => {
    await mockKpi(page, { fenstererkennung_aktiv: true, zones_window_open: 2 });
    await page.goto("/");
    expect(await tonVon(page, "Fenster offen")).toBe("warning-soft");
  });

  test("Zahlen ohne Urteil bleiben neutral, auch mit großen Werten", async ({
    page,
  }) => {
    // 47 belegte Zimmer sind nicht besser als 0, und 27 Übersteuerungen
    // sind kein Fehler. Diese drei Kacheln dürfen nie grün werden — sonst
    // liest der Betreiber eine Bewertung, wo eine Zahl steht.
    await mockKpi(page, {
      rooms_occupied: 47,
      active_overrides: 27,
      avg_temperature_celsius: 22.8,
    });
    await page.goto("/");
    for (const kachel of [
      "Belegte Zimmer",
      "Ø Raumtemperatur",
      "Aktive Übersteuerungen",
    ]) {
      expect(await tonVon(page, kachel)).toBe("neutral");
    }
  });

  test("Funk-Empfang „unbekannt“ bleibt grau und wird nicht grün", async ({
    page,
  }) => {
    // „Noch keine einzige Meldung" heißt frisch aufgesetztes Haus. Grün
    // wäre eine Aussage über eine Anlage, die es noch nicht gibt; rot
    // wäre eine Störung, die niemand verursacht hat.
    await mockKpi(page, {
      funkempfang_stufe: "unbekannt",
      funkempfang_alter_min: null,
      funkempfang_letzte_meldung: null,
      funkempfang_meldungen_10min: 0,
    });
    await page.goto("/");
    expect(await tonVon(page, "Funk-Empfang")).toBe("neutral");
  });
});
