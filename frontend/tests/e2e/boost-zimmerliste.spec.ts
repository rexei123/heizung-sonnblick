import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Boost in der Zimmerliste (02.11.2026).
 *
 * Geprüft wird, was man ohne Backend sehen kann, und das ist mehr als es
 * klingt — die Festlegungen des Betreibers sind fast alle Aussagen über
 * die Oberfläche:
 *
 * 1. **Der Knopf nennt die Endzeit vorher** („Boost bis 22:00"). Kein
 *    Mindestmaß: wer um 21:55 drückt, soll vorher sehen, dass es fünf
 *    Minuten sind.
 * 2. **Der Knopf „Temperatur" ist drückbar, solange einer der beiden
 *    Wege geht.** Ein freies Zimmer kann keinen Wert bekommen, aber einen
 *    Boost — und dann ist er nicht grau.
 * 3. **Kein Knopf ohne sichtbaren Grund** (§5.57): der Satz hängt am
 *    umschließenden `span` als Tooltip **und** als `sr-only`-Text, weil
 *    ein `disabled`-Knopf `pointer-events-none` trägt und seinen eigenen
 *    Tooltip nie zeigt.
 * 4. **Ein aktiver Boost bekommt eine eigene Kennzeichnung mit Endzeit**
 *    in der Spalte „Übersteuerung" — Flammen-Zeichen und „Boost bis
 *    20:00", nicht nur „Aktiv".
 * 5. **Die Gründe kommen aus dem Backend** und werden hier nicht
 *    nachgerechnet. Der Test schickt sie als Feld und prüft, dass sie
 *    ankommen.
 */

const ADMIN = {
  id: 1,
  email: "chef@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-11-02T06:00:00Z",
  last_login_at: "2026-11-02T06:00:00Z",
};

const RAUMTYP = {
  id: 1,
  name: "Standard",
  beds: 2,
  area_m2: 20,
  occupied_setpoint: "21",
  vacant_setpoint: "18",
  night_setback_offset: "2",
  frost_protection_setpoint: "8",
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-04-01T10:00:00Z",
};

const ZONE = {
  id: 201,
  room_id: 101,
  kind: "bedroom" as const,
  name: "Schlafzimmer",
  is_towel_warmer: false,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-04-01T10:00:00Z",
};

/** 22:00 Ortszeit im Winter = 21:00 UTC. */
const ENDE_UTC = "2026-11-02T21:00:00Z";

interface Lage {
  status?: string;
  blocked?: boolean;
  bereich?: boolean;
  boostMoeglich?: boolean;
  boostGrund?: string | null;
  boostHinweis?: string | null;
  boostEnde?: string | null;
  aktiveQuelle?: string | null;
  aktivesEnde?: string | null;
}

function raum(lage: Lage = {}): Record<string, unknown> {
  const boost = lage.boostMoeglich ?? true;
  return {
    id: 101,
    number: "101",
    display_name: "Gartenblick",
    room_type_id: 1,
    floor: 1,
    orientation: null,
    status: lage.status ?? "occupied",
    guest_override_blocked: lage.blocked ?? false,
    guest_block_bis_checkout: false,
    ist_allgemeinbereich: lage.bereich ?? false,
    has_active_override: lage.aktiveQuelle != null,
    uebersteuerung_quelle: lage.aktiveQuelle ?? null,
    uebersteuerung_ende: lage.aktivesEnde ?? null,
    boost_moeglich: boost,
    boost_grund: lage.boostGrund ?? null,
    boost_hinweis: lage.boostHinweis ?? null,
    boost_ende: lage.boostEnde !== undefined ? lage.boostEnde : ENDE_UTC,
    notes: null,
    created_at: "2026-04-01T10:00:00Z",
    updated_at: "2026-11-02T06:00:00Z",
    reference_zone_id: 201,
    mean_temperature_c: 19.2,
    engine_setpoint_c: 21,
  };
}

interface Steuerung {
  /** Wie oft der Boost-Weg gerufen wurde. */
  rufe: () => number;
  /** Der Rumpf des letzten Rufs — er soll leer sein. */
  rumpf: () => string | null;
}

async function mockApi(page: Page, lage: Lage = {}): Promise<Steuerung> {
  const json = (r: Route, body: unknown) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  let rufe = 0;
  let rumpf: string | null = null;
  let quelle = lage.aktiveQuelle ?? null;
  let ende = lage.aktivesEnde ?? null;

  await page.route("**/api/v1/**", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) => json(r, ADMIN));
  await page.route(/.*\/api\/v1\/room-types(\?.*)?$/, (r: Route) => json(r, [RAUMTYP]));
  await page.route(/.*\/api\/v1\/rooms\/101\/heating-zones(\?.*)?$/, (r: Route) =>
    json(r, [ZONE]),
  );
  await page.route(/.*\/api\/v1\/rooms\/101\/engine-trace(\?.*)?$/, (r: Route) => json(r, []));
  await page.route(/.*\/api\/v1\/rooms\/101\/overrides(\?.*)?$/, (r: Route) => json(r, []));
  await page.route(/.*\/api\/v1\/rooms\/101\/boost(\?.*)?$/, async (r: Route) => {
    rufe += 1;
    rumpf = r.request().postData();
    quelle = "frontend_boost";
    ende = ENDE_UTC;
    await r.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: 902,
        room_id: 101,
        heating_zone_id: null,
        setpoint: "24.0",
        source: "frontend_boost",
        expires_at: ENDE_UTC,
        reason: "Boost",
        created_at: "2026-11-02T18:00:00Z",
        created_by: ADMIN.email,
        revoked_at: null,
        revoked_reason: null,
        wirksam_gekappt_c: null,
      }),
    });
  });
  await page.route(/.*\/api\/v1\/rooms\/101(\?.*)?$/, (r: Route) => json(r, raum(lage)));
  await page.route(/.*\/api\/v1\/rooms(\?.*)?$/, (r: Route) =>
    json(r, [raum({ ...lage, aktiveQuelle: quelle, aktivesEnde: ende })]),
  );

  return { rufe: () => rufe, rumpf: () => rumpf };
}

test.describe("Boost in der Zimmerliste", () => {
  test("der Knopf nennt die Endzeit vorher", async ({ page }) => {
    // **Festlegung 4 des Betreibers: kein Mindestmaß.** Ein Boost um
    // 21:55 endet um 22:00 — deshalb muss die Zeit am Knopf stehen,
    // bevor jemand drückt.
    await mockApi(page);
    await page.goto("/zimmer");
    await page.getByTestId("uebersteuern-101").click();

    await expect(page.getByTestId("boost-knopf")).toContainText("Boost bis 22:00");
    await expect(page.getByTestId("boost-knopf")).toBeEnabled();
  });

  test("ein Klick genügt, und der Rumpf bleibt leer", async ({ page }) => {
    // Wert und Ende rechnet das Backend. Ein Feld, das man setzen kann,
    // wird irgendwann gesetzt — deshalb hat dieser Weg keines.
    const ctrl = await mockApi(page);
    await page.goto("/zimmer");
    await page.getByTestId("uebersteuern-101").click();
    await page.getByTestId("boost-knopf").click();

    await expect.poll(() => ctrl.rufe()).toBe(1);
    expect(ctrl.rumpf()).toBe("{}");
    await expect(page.getByTestId("boost-erfolg")).toContainText("Boost läuft bis 22:00");
  });

  test("ein aktiver Boost steht mit Endzeit in der Spalte", async ({ page }) => {
    // **Festlegung des Betreibers vom 01.11.2026:** eigene
    // Kennzeichnung mit Endzeit, nicht nur die Endzeit — und nicht nur
    // „Aktiv", wie es bis zum 02.11. dort stand.
    await mockApi(page, { aktiveQuelle: "frontend_boost", aktivesEnde: ENDE_UTC });
    await page.goto("/zimmer");

    const marke = page.getByTestId("uebersteuerung-aktiv-101");
    await expect(marke).toContainText("Boost bis 22:00");
    await expect(marke.locator("span.material-symbols-outlined")).toHaveText(
      "local_fire_department",
    );
  });

  test("eine gewöhnliche Übersteuerung bleibt bei „Aktiv“ — mit Endzeit", async ({
    page,
  }) => {
    await mockApi(page, { aktiveQuelle: "frontend_24h", aktivesEnde: ENDE_UTC });
    await page.goto("/zimmer");

    const marke = page.getByTestId("uebersteuerung-aktiv-101");
    await expect(marke).toContainText("Aktiv bis 22:00");
    await expect(marke.locator("span.material-symbols-outlined")).toHaveText("tune");
  });

  test("freies Zimmer: der Knopf bleibt drückbar, weil Boost geht", async ({ page }) => {
    // **Festlegung 2: eine Regel für belegt und frei.** Ein Wert geht
    // hier nicht (AE-58), ein Boost schon — und ein grauer Knopf wäre
    // dann falsch.
    await mockApi(page, { status: "vacant", boostMoeglich: true });
    await page.goto("/zimmer");

    await expect(page.getByTestId("uebersteuern-101")).toBeEnabled();
  });

  test("Sommermodus: ausgegraut, und der Grund steht zweimal da", async ({ page }) => {
    await mockApi(page, {
      boostMoeglich: false,
      boostGrund: "sommermodus",
      boostHinweis: "Sommermodus aktiv",
      boostEnde: null,
    });
    await page.goto("/zimmer");

    const knopf = page.getByTestId("uebersteuern-101");
    await expect(knopf).toBeDisabled();
    // Zwei Wege, beide geprüft: Tooltip am umschließenden `span` (der
// gesperrte Knopf trägt `pointer-events-none`) und `sr-only` daneben.
    await expect(knopf.locator("xpath=..")).toHaveAttribute("title", "Sommermodus aktiv");
    await expect(page.getByText("Sommermodus aktiv")).toBeAttached();
  });

  test("ohne Nachtfenster: ausgegraut mit dem Satz des Backends", async ({ page }) => {
    // **Festlegung 3: keine erfundene Dauer.** Der Satz kommt aus dem
    // Backend, weil dort die Regelkette steht — die Oberfläche rechnet
    // ihn nicht nach (§5.53).
    await mockApi(page, {
      status: "vacant",
      boostMoeglich: false,
      boostGrund: "kein_nachtfenster",
      boostHinweis: "Kein Nachtfenster konfiguriert",
      boostEnde: null,
    });
    await page.goto("/zimmer");

    const knopf = page.getByTestId("uebersteuern-101");
    await expect(knopf).toBeDisabled();
    await expect(knopf.locator("xpath=..")).toHaveAttribute(
      "title",
      "Kein Nachtfenster konfiguriert",
    );
  });

  test("dauerhaft gesperrt: der kürzere Satz des Betreibers", async ({ page }) => {
    await mockApi(page, { blocked: true, boostMoeglich: false, boostGrund: "dauerhaft_gesperrt" });
    await page.goto("/zimmer");

    const knopf = page.getByTestId("uebersteuern-101");
    await expect(knopf).toBeDisabled();
    await expect(knopf.locator("xpath=..")).toHaveAttribute("title", "Dauerhaft gesperrt");
  });

  test("laufende Übersteuerung: der Dialog sagt, wo der Wert zu ändern ist", async ({
    page,
  }) => {
    // **Festlegung 1, Variante (c).** Boost ersetzt eine laufende
    // Übersteuerung nicht und legt sich nicht darüber — er wird
    // abgewiesen, und der Satz nennt den Weg. Der Knopf „Temperatur"
    // bleibt drückbar, weil der Wert dort zu ändern ist.
    await mockApi(page, {
      aktiveQuelle: "frontend_24h",
      aktivesEnde: ENDE_UTC,
      boostMoeglich: false,
      boostGrund: "uebersteuerung_aktiv",
      boostHinweis: "Übersteuerung aktiv (23 °C bis 22:00) – Wert dort ändern",
      boostEnde: ENDE_UTC,
    });
    await page.goto("/zimmer");

    await expect(page.getByTestId("uebersteuern-101")).toBeEnabled();
    await page.getByTestId("uebersteuern-101").click();

    await expect(page.getByTestId("boost-knopf")).toBeDisabled();
    await expect(page.getByTestId("boost-erklaerung")).toHaveText(
      "Übersteuerung aktiv (23 °C bis 22:00) – Wert dort ändern",
    );
  });

  test("Allgemeinbereich: Knopf drückbar, Boost nicht", async ({ page }) => {
    // Die Abweichung, die beim Betreiber liegt (siehe
    // `lib/uebersteuerung.ts::temperaturknopf`): der Knopf bleibt
    // drückbar, weil die Übersteuerung eines Bereichs seit dem 30.10. in
    // der Liste geht. Der Satz des Betreibers steht am Boost.
    await mockApi(page, {
      bereich: true,
      status: "vacant",
      boostMoeglich: false,
      boostGrund: "allgemeinbereich",
      boostHinweis: "Allgemeinbereich – Übersteuerung über Zimmerseite",
      boostEnde: null,
    });
    await page.goto("/zimmer");

    await expect(page.getByTestId("uebersteuern-101")).toBeEnabled();
    await page.getByTestId("uebersteuern-101").click();

    await expect(page.getByTestId("boost-knopf")).toBeDisabled();
    await expect(page.getByTestId("boost-erklaerung")).toHaveText(
      "Allgemeinbereich – Übersteuerung über Zimmerseite",
    );
  });

  test("der Knopf heißt „Temperatur“ und bleibt es auch gesperrt", async ({ page }) => {
    // **Festlegung des Betreibers vom 01.11.2026:** die Beschriftung
    // wechselt nicht in den Grund. Ein Knopf, der seinen Namen verliert,
    // ist beim nächsten Blick ein anderer Knopf.
    await mockApi(page, { boostMoeglich: false, boostGrund: "sommermodus", boostHinweis: "Sommermodus aktiv" });
    await page.goto("/zimmer");

    const knopf = page.getByTestId("uebersteuern-101");
    await expect(knopf).toContainText("Temperatur");
    await expect(knopf).toBeDisabled();
  });
});
