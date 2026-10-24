import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Sprint 24d — Allgemeinbereiche: Betrieb statt Belegt, und eine
 * Übersteuerung ohne Belegung.
 *
 * **Was hier geprüft wird, und warum es nicht im Backend geprüft werden
 * kann.** Die Zusicherungen dieses Sprints sind zur Hälfte Beschriftungen:
 * dass ein Bereich nicht „Frei" heißt, dass seine Raumtyp-Seite „Betrieb"
 * sagt, dass ein Feld ohne Wirkung das zugibt, und dass der Satz nach dem
 * Setzen keinen Check-in erwähnt, den es dort nie gibt. Nichts davon ist
 * am Endpunkt sichtbar.
 *
 * **Beide Rollen ausdrücklich gesetzt**, nicht über den Standard der Hülle
 * (`fixtures.ts`): ein Rollen-Test, der sich auf den Standard verlässt,
 * prüft nur „Admin sieht den Knopf" und nie die andere Richtung.
 *
 * **Routen-Reihenfolge:** Playwright trifft die **zuletzt** registrierte
 * Route zuerst, und `**\/api/v1/room-types` greift auch auf
 * `/room-types/sollwert-wirksamkeit`. Die spezifischen Wege stehen deshalb
 * hinter den allgemeinen — in Sprint 24b hat die umgekehrte Reihenfolge
 * eine Stunde gekostet.
 */

const ADMIN = {
  id: 1,
  email: "chef@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-24T06:00:00Z",
  last_login_at: "2026-10-24T06:00:00Z",
};

const MITARBEITER = { ...ADMIN, id: 2, email: "rezeption@hotel.example.com", role: "mitarbeiter" as const };

/** „Raum intern" — der Raumtyp der Bar. Nicht buchbar. */
const RT_BEREICH = {
  id: 5,
  name: "Raum intern",
  description: null,
  is_bookable: false,
  default_t_occupied: "21.0",
  default_t_vacant: "21.0",
  default_t_night: "20.0",
  max_temp_celsius: "25.0",
  min_temp_celsius: "16.0",
  treat_unoccupied_as_vacant_after_hours: null,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-10-24T06:00:00Z",
};

const RT_GAST = {
  ...RT_BEREICH,
  id: 1,
  name: "Doppelzimmer",
  is_bookable: true,
  default_t_vacant: "18.0",
  default_t_night: "19.0",
};

/** Die Bar: Zimmer mit nicht buchbarem Raumtyp. */
const BAR = {
  id: 3,
  number: "Bar",
  display_name: "Barbereich",
  room_type_id: 5,
  floor: 0,
  orientation: null,
  status: "vacant" as const,
  guest_override_blocked: false,
  notes: null,
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-24T07:00:00Z",
  has_active_override: false,
  reference_zone_id: null,
  mean_temperature_c: 19.4,
  engine_setpoint_c: 21,
  ist_allgemeinbereich: true,
  betriebszeit_von: "15:00:00",
  betriebszeit_bis: "00:00:00",
};

const GASTZIMMER = {
  ...BAR,
  id: 4,
  number: "208",
  display_name: null,
  room_type_id: 1,
  floor: 2,
  ist_allgemeinbereich: false,
  betriebszeit_von: null,
  betriebszeit_bis: null,
};

/**
 * Die Zone der Bar — **vollständig** nachgebildet.
 *
 * Die erste Fassung ließ `health_state` weg, und das hat die ganze Seite
 * umgeworfen: `CONFIG[undefined]` ist `undefined`, und der Zugriff auf
 * `cfg.badgeClass` nimmt den React-Baum mit. Übrig blieb eine leere Seite
 * ohne Fehlermeldung — ein Mock, der weniger liefert als die API, prüft
 * nicht weniger, sondern etwas anderes.
 *
 * `geraete_luecke: "kein_stellglied"` ist der Zustand des Hauses: der Zone
 * ist die Fühler-Vicki 027 zugeordnet, ein Stellglied noch nicht.
 */
const ZONE_BEREICH = {
  id: 9,
  room_id: 3,
  kind: "common_area" as const,
  name: "Barbereich",
  is_towel_warmer: false,
  health_state: "healthy" as const,
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-20T10:00:00Z",
  active_override: null,
  mean_temperature_c: 19.4,
  engine_setpoint_c: 21,
  mean_temperature_at: "2026-10-24T07:50:00Z",
  geraete_luecke: "kein_stellglied" as const,
};

/** Die Vorschau: beim Bereich stimmt es, beim Gästezimmer nicht. */
const WIRKSAMKEIT = [
  {
    room_type_id: 5,
    name: "Raum intern",
    is_bookable: false,
    zeile_vorhanden: true,
    wuerde_sich_aendern: false,
    felder: [
      { feld: "default_t_occupied", angezeigt: 21.0, wirksam: 21.0, quelle: "raumtyp" },
      { feld: "default_t_vacant", angezeigt: 21.0, wirksam: 21.0, quelle: "raumtyp" },
      { feld: "default_t_night", angezeigt: 20.0, wirksam: 20.0, quelle: "raumtyp" },
    ],
  },
  {
    room_type_id: 1,
    name: "Doppelzimmer",
    is_bookable: true,
    zeile_vorhanden: false,
    wuerde_sich_aendern: true,
    felder: [
      { feld: "default_t_occupied", angezeigt: 21.0, wirksam: 21.0, quelle: "global" },
      { feld: "default_t_vacant", angezeigt: 18.0, wirksam: 16.0, quelle: "global" },
      { feld: "default_t_night", angezeigt: 19.0, wirksam: 19.0, quelle: "global" },
    ],
  },
];

function trace(): unknown[] {
  const evalId = "00000000-0000-0000-0000-0000000024d0";
  const now = new Date().toISOString();
  return [
    {
      time: now,
      room_id: 3,
      evaluation_id: evalId,
      layer: "base_target",
      device_id: null,
      setpoint_in: "21.0",
      setpoint_out: "21.0",
      reason: "vacant_setpoint",
      details: {
        detail: "status=vacant",
        sollwert_quelle: "raumtyp",
        betriebsbereich: true,
      },
    },
    {
      time: now,
      room_id: 3,
      evaluation_id: evalId,
      layer: "window_safety",
      device_id: null,
      setpoint_in: "21.0",
      setpoint_out: "21.0",
      reason: "vacant_setpoint",
      details: { detail: "no_open_window", open_zones: [] },
    },
    {
      time: now,
      room_id: 3,
      evaluation_id: evalId,
      layer: "hard_clamp",
      device_id: null,
      setpoint_in: "21.0",
      setpoint_out: "21.0",
      reason: "vacant_setpoint",
      details: { detail: "within [16,25]" },
    },
  ];
}

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function mock(
  page: Page,
  { nutzer, overrides }: { nutzer?: unknown; overrides?: unknown[] } = {},
): Promise<void> {
  const angemeldet = nutzer ?? ADMIN;
  const historie = overrides ?? [];
  await page.route("**/api/v1/**", (r: Route) => json(r, []));
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) => json(r, angemeldet));
  await page.route(/.*\/api\/v1\/rooms(\?.*)?$/, (r: Route) => json(r, [BAR, GASTZIMMER]));
  await page.route(/.*\/api\/v1\/room-types(\?.*)?$/, (r: Route) =>
    json(r, [RT_GAST, RT_BEREICH]),
  );
  // Hinter der Raumtyp-Liste — siehe Kopf.
  await page.route(/.*\/api\/v1\/room-types\/sollwert-wirksamkeit$/, (r: Route) =>
    json(r, WIRKSAMKEIT),
  );
  await page.route("**/api/v1/rooms/3", (r: Route) => json(r, BAR));
  await page.route("**/api/v1/rooms/3/heating-zones", (r: Route) => json(r, [ZONE_BEREICH]));
  await page.route("**/api/v1/rooms/3/engine-trace*", (r: Route) => json(r, trace()));
  await page.route(/.*\/api\/v1\/rooms\/3\/overrides(\?.*)?$/, (r: Route) => {
    if (r.request().method() !== "GET") return r.fallback();
    return json(r, historie);
  });
}

test.describe("Allgemeinbereiche", () => {
  test("die Zimmerliste nennt den Bereich einen Bereich", async ({ page }) => {
    await mock(page);
    await page.goto("/zimmer");

    const zeilen = page.getByTestId("zimmer-status");
    await expect(zeilen).toHaveCount(2);
    // Der Bereich.
    await expect(
      zeilen.filter({ has: page.locator('[data-allgemeinbereich="true"]') }),
    ).toHaveCount(0); // der Marker sitzt am Element selbst, nicht an einem Kind
    const bereich = page.locator('[data-testid="zimmer-status"][data-allgemeinbereich="true"]');
    await expect(bereich).toHaveText("Allgemeinbereich");
    // Und das Gästezimmer bleibt „Frei" — ohne diese Hälfte wäre der Test
    // auch grün, wenn jede Zeile „Allgemeinbereich" hieße.
    const gast = page.locator('[data-testid="zimmer-status"][data-allgemeinbereich="false"]');
    await expect(gast).toHaveText("Frei");
  });

  test("die Raumtyp-Seite sagt Betrieb statt Belegt", async ({ page }) => {
    await mock(page);
    await page.goto("/raumtypen");

    await page.getByRole("listitem").filter({ hasText: "Raum intern" }).click();

    // ``exact: true`` ist Pflicht: ``getByLabel`` sucht sonst als
    // Teilzeichenfolge, und „Langzeit-Absenkung nach Stunden" enthält
    // „Absenkung". Ohne das Flag prüft der Test zwei Felder als eines.
    const felder = page.getByTestId("rt-sollwerte");
    await expect(felder).toHaveAttribute("data-bereich", "true");
    await expect(page.getByLabel("Betrieb", { exact: true })).toBeVisible();
    // „Absenkung" und nicht „Nacht": für eine Bar um 01:00 wäre „Nacht"
    // eine Aussage über die Uhrzeit und nicht über den Betrieb.
    await expect(page.getByLabel("Absenkung", { exact: true })).toBeVisible();
    // „Belegt" und „Frei" gibt es dort nicht — ein Bereich hat keinen Gast.
    await expect(page.getByLabel("Belegt", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("Frei", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("Nacht", { exact: true })).toHaveCount(0);
    await expect(page.getByTestId("rt-bereich-hinweis")).toContainText("kein Check-in");
  });

  test("ein Gästezimmer-Raumtyp behält Belegt und Frei", async ({ page }) => {
    // Die Gegenprobe. Ohne sie wäre der Test oben auch grün, wenn jede
    // Raumtyp-Seite „Betrieb" zeigte.
    await mock(page);
    await page.goto("/raumtypen");

    await page.getByRole("listitem").filter({ hasText: "Doppelzimmer" }).click();

    await expect(page.getByTestId("rt-sollwerte")).toHaveAttribute("data-bereich", "false");
    await expect(page.getByLabel("Belegt", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Frei", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Nacht", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Betrieb", { exact: true })).toHaveCount(0);
    await expect(page.getByLabel("Absenkung", { exact: true })).toHaveCount(0);
  });

  test("das Feld ohne Wirkung sagt, dass es nichts tut", async ({ page }) => {
    await mock(page);
    await page.goto("/raumtypen");

    await page.getByRole("listitem").filter({ hasText: "Raum intern" }).click();

    await expect(page.getByTestId("rt-langzeit-hinweis")).toContainText(
      "noch nicht gelesen",
    );
  });

  test("die Wirksamkeit steht neben den Werten", async ({ page }) => {
    await mock(page);
    await page.goto("/raumtypen");

    await page.getByRole("listitem").filter({ hasText: "Raum intern" }).click();

    const karte = page.getByTestId("sollwert-wirksamkeit");
    await expect(karte).toHaveAttribute("data-wuerde-sich-aendern", "false");
    // Beim Bereich sind „Betrieb" und „Nacht" aufgeführt, „Belegt" nicht —
    // es ist dort ungenutzt.
    await expect(karte.getByTestId("wirksamkeit-zeile")).toHaveCount(2);
    await expect(karte).toContainText("Raumtyp");
    await expect(karte.getByTestId("wirksamkeit-uebernehmen")).toHaveCount(0);
  });

  test("beim Gästezimmer-Raumtyp zeigt sie die Abweichung und den Knopf", async ({
    page,
  }) => {
    await mock(page);
    await page.goto("/raumtypen");

    await page.getByRole("listitem").filter({ hasText: "Doppelzimmer" }).click();

    const karte = page.getByTestId("sollwert-wirksamkeit");
    await expect(karte).toHaveAttribute("data-wuerde-sich-aendern", "true");
    await expect(karte.getByTestId("wirksamkeit-hinweis")).toContainText(
      "gelten noch nicht",
    );
    // Der abweichende Wert ist markiert, der stimmige nicht.
    const frei = karte.locator('[data-feld="default_t_vacant"] [data-abweichend="true"]');
    await expect(frei).toHaveCount(1);
    await expect(karte.getByTestId("wirksamkeit-uebernehmen")).toBeVisible();
  });

  test("ein Mitarbeiter sieht die Wirksamkeit, aber keinen Knopf", async ({ page }) => {
    await mock(page, { nutzer: MITARBEITER });
    await page.goto("/raumtypen");

    await page.getByRole("listitem").filter({ hasText: "Doppelzimmer" }).click();

    await expect(page.getByTestId("sollwert-wirksamkeit")).toBeVisible();
    await expect(page.getByTestId("wirksamkeit-uebernehmen")).toHaveCount(0);
  });

  test("der Trace nennt Betrieb-Sollwert und die Quelle", async ({ page }) => {
    await mock(page);
    await page.goto("/zimmer/3");
    // Der Trace liegt im Reiter „Engine" — die Reiter sind Knöpfe, keine
    // ARIA-Tabs (gewachsene Form der Seite, nicht Teil dieses Sprints).
    await page.getByRole("button", { name: "Engine", exact: true }).click();

    await expect(page.getByTestId("trace-grund")).toHaveText("Betrieb-Sollwert");
    await expect(page.getByTestId("trace-quelle")).toContainText("Raumtyp");
  });

  test("die Zimmerseite des Bereichs erlaubt Temperatur ändern", async ({ page }) => {
    await mock(page);
    await page.goto("/zimmer/3");

    await expect(page.getByTestId("bereich-hinweis")).toContainText("kein Check-in");
    // Vor diesem Sprint war der Knopf grau: das Zimmer ist nicht belegt.
    await expect(page.getByTestId("temperatur-aendern")).toBeEnabled();
  });

  test("Übersteuerung mit Dauer setzen, Satz ohne Check-in", async ({ page }) => {
    await mock(page);

    let gesendet: Record<string, unknown> | null = null;
    const ablauf = new Date(Date.now() + 2 * 3600 * 1000).toISOString();
    await page.route(/.*\/api\/v1\/rooms\/3\/overrides(\?.*)?$/, async (r: Route) => {
      if (r.request().method() === "POST") {
        gesendet = JSON.parse(r.request().postData() ?? "{}") as Record<string, unknown>;
        return json(
          r,
          {
            id: 77,
            room_id: 3,
            heating_zone_id: 9,
            setpoint: "23.0",
            source: "frontend_bereich",
            expires_at: ablauf,
            reason: null,
            created_by: "chef@hotel.example.com",
            created_at: new Date().toISOString(),
            revoked_at: null,
            revoked_reason: null,
          },
          201,
        );
      }
      return json(r, gesendet === null ? [] : [
        {
          id: 77,
          room_id: 3,
          heating_zone_id: 9,
          setpoint: "23.0",
          source: "frontend_bereich",
          expires_at: ablauf,
          reason: null,
          created_by: "chef@hotel.example.com",
          created_at: new Date().toISOString(),
          revoked_at: null,
          revoked_reason: null,
        },
      ]);
    });

    await page.goto("/zimmer/3");
    await page.getByTestId("temperatur-aendern").click();

    // Kein „ab dem Check-in" — den gibt es hier nicht.
    await expect(page.getByText("Zimmer ist nicht belegt")).toHaveCount(0);

    // Die Dauer ist eine Auswahl in Minuten, keine Quellen-Auswahl.
    await expect(page.getByTestId("bereich-dauer")).toBeVisible();
    await page.getByLabel("Setpoint (°C)").fill("23");
    await page.getByRole("button", { name: "Anwenden" }).click();

    await expect(page.getByTestId("bereich-satz")).toContainText("danach wieder Plan");
    await expect(page.getByTestId("bereich-satz")).toContainText("23 °C");

    // Und der Körper trägt Quelle und Dauer.
    expect(gesendet).not.toBeNull();
    expect(gesendet!.source).toBe("frontend_bereich");
    expect(gesendet!.dauer_minuten).toBe(240);
  });

  test("die Betriebszeit steht in den Stammdaten und wird gespeichert", async ({
    page,
  }) => {
    await mock(page);

    let gesendet: Record<string, unknown> | null = null;
    await page.route("**/api/v1/rooms/3/betriebszeit", async (r: Route) => {
      gesendet = JSON.parse(r.request().postData() ?? "{}") as Record<string, unknown>;
      return json(r, {
        ...BAR,
        betriebszeit_von: "15:00:00",
        betriebszeit_bis: "00:00:00",
      });
    });

    await page.goto("/zimmer/3");
    await expect(page.getByTestId("bereich-hinweis")).toBeVisible();

    const form = page.getByTestId("betriebszeit-form");
    await expect(form).toBeVisible();
    // Der gespeicherte Stand steht im Feld, ohne die Sekunden.
    await expect(page.getByTestId("betriebszeit-von")).toHaveValue("15:00");

    await page.getByTestId("betriebszeit-bis").fill("24:00");
    await page.getByTestId("betriebszeit-speichern").click();

    await expect(page.getByTestId("betriebszeit-meldung")).toContainText("gespeichert");
    expect(gesendet).not.toBeNull();
    // „24:00" geht **so** hinaus — die Umrechnung auf Mitternacht ist
    // Sache des Servers und nicht der Oberfläche.
    expect(gesendet!.bis).toBe("24:00");
  });

  test("ein Gästezimmer hat keine Betriebszeit", async ({ page }) => {
    // Die Gegenprobe: dasselbe Feld wäre dort das Nacht-Fenster, und es
    // unter dem Namen „Betriebszeit" zu zeigen hieße, zwei Dinge gleich zu
    // nennen, die verschieden gemeint sind.
    await mock(page);
    await page.route("**/api/v1/rooms/4", (r: Route) => json(r, GASTZIMMER));
    await page.route("**/api/v1/rooms/4/heating-zones", (r: Route) => json(r, []));
    await page.route("**/api/v1/rooms/4/engine-trace*", (r: Route) => json(r, []));

    await page.goto("/zimmer/4");

    await expect(page.getByText("Zimmer 208")).toBeVisible();
    await expect(page.getByTestId("betriebszeit-form")).toHaveCount(0);
  });

  test("die Zone sagt, dass das Stellglied fehlt — nicht das Gerät", async ({ page }) => {
    await mock(page);
    await page.goto("/zimmer/3");
    await expect(page.getByTestId("bereich-hinweis")).toBeVisible();
    await page.getByRole("button", { name: "Heizzonen", exact: true }).click();

    // „Kein Gerät" war der Befund des Betreibers: die Zone **hat** einen
    // Fühler, ihr fehlt ein Stellglied.
    await expect(page.getByText("Kein Stellglied")).toBeVisible();
    await expect(page.getByText("Kein Gerät")).toHaveCount(0);
  });

  test("die Zonenkarte zeigt den wirksamen Sollwert und den Stand der Messung", async ({
    page,
  }) => {
    // **Mutationsprobe M26.** Der Raumtyp zeigt 21 an; wirksam ist, was
    // die Engine geschrieben hat. Hier sind beide gleich — deshalb trägt
    // der Mock einen **abweichenden** Engine-Wert, sonst prüfte der Test
    // nicht, welcher von beiden gezeigt wird.
    await mock(page);
    await page.route("**/api/v1/rooms/3/heating-zones", (r: Route) =>
      json(r, [{ ...ZONE_BEREICH, engine_setpoint_c: 17 }]),
    );

    await page.goto("/zimmer/3");
    await expect(page.getByTestId("bereich-hinweis")).toBeVisible();
    await page.getByRole("button", { name: "Heizzonen", exact: true }).click();

    await expect(page.getByTestId("zone-card-9-effective-setpoint")).toContainText("17.0 °C");
    // Und der Stand der Ist-Messung steht daneben.
    await expect(page.getByTestId("zone-card-9-ist-stand")).toBeVisible();
  });

  test("die globale Seite nennt ein leeres Feld nicht festgelegt", async ({ page }) => {
    // **Abschlusskriterium 5.** Bis zum 24.10.2026 stand dort 21,0 bzw.
    // 18,0, obwohl beide Felder leer sind — ein Speichern hätte sie
    // wirksam gemacht und jeden Raumtyp überstimmt.
    await mock(page);
    await page.route(/.*\/api\/v1\/rule-configs\/global$/, (r: Route) =>
      json(r, {
        id: 1,
        t_occupied: null,
        t_vacant: null,
        t_night: "19.0",
        night_start: "20:00:00",
        night_end: "06:00:00",
        preheat_minutes_before_checkin: 60,
        created_at: "2026-04-01T10:00:00Z",
        updated_at: "2026-10-21T10:00:00Z",
      }),
    );
    await page.route(/.*\/api\/v1\/rule-configs\/global\/nutzung$/, (r: Route) =>
      json(r, [
        {
          feld: "t_vacant",
          gesetzt: false,
          raumtypen_nutzen: 4,
          raumtypen_eigen: 2,
          zimmer_eigen: 0,
        },
      ]),
    );

    await page.goto("/einstellungen/temperaturen-zeiten");

    await expect(
      page.getByRole("heading", { name: /Hausstandard/ }),
    ).toBeVisible();
    await page.getByRole("tab", { name: "Globale Temperaturen" }).click();

    // Zwei leere Felder sagen das, eines zeigt seine Zahl.
    await expect(page.getByText("nicht festgelegt — Raumtyp entscheidet")).toHaveCount(2);
    await expect(page.getByText("19.0 °C")).toBeVisible();
  });

  test("die Zonen-Art Allgemeinbereich ist wählbar", async ({ page }) => {
    await mock(page);
    await page.goto("/zimmer/3");
    // Erst auf die geladene Seite warten: ein Klick auf einen Reiter, der
    // noch nicht da ist, laeuft in den Timeout statt in eine Fehlermeldung.
    await expect(page.getByTestId("bereich-hinweis")).toBeVisible();

    await page.getByRole("button", { name: "Heizzonen", exact: true }).click();

    // Die Zonen-Art ist ein ``<select>`` ohne Beschriftung; geprüft wird
    // die Option selbst und nicht der Text des Feldes — ``hasText`` auf
    // einem ``select`` greift nicht auf seine Optionen.
    const auswahl = page.locator("select").first();
    await expect(auswahl).toBeVisible();
    await expect(auswahl.locator('option[value="common_area"]')).toHaveText(
      "Allgemeinbereich",
    );

    // Und sie ist wählbar, nicht nur vorhanden.
    await auswahl.selectOption("common_area");
    await expect(auswahl).toHaveValue("common_area");
  });
});
