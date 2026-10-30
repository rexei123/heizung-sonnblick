import { test, expect, type Page, type Route } from "./fixtures";

/**
 * „Übersteuern" und „Details" als zwei echte Knöpfe in der
 * Zimmerübersicht (30.10.2026).
 *
 * **Der Anlass ist ein Weg, nicht ein Wunsch.** Der häufigste Handgriff
 * der Rezeption lag hinter „Detail →", einem Seitenwechsel und einem
 * Reiter. Dieselbe Verlegung wie in Sprint 21 A2, eine Ebene höher.
 *
 * Geprüft wird, was man ohne Backend sehen kann:
 *
 * 1. **Wann der Knopf drückbar ist**, in allen vier Lagen: belegt, nicht
 *    belegt, dauerhaft gesperrt, gesperrt bis Check-out. Die Regel kommt
 *    aus `lib/uebersteuerung.ts` und spiegelt `override_service.create` —
 *    diese Tests sind die Probe darauf, dass die Liste nichts eigenes
 *    entscheidet.
 * 2. **Dass der Grund lesbar ist.** Ein ausgegrauter Knopf ohne Grund ist
 *    eine Sperre, die der Nutzer sich selbst erklärt, und zwar falsch
 *    (§5.57). Der Satz hängt am umschließenden `span`, weil ein
 *    `disabled`-Knopf `pointer-events-none` trägt und seinen eigenen
 *    Tooltip nie zeigen würde.
 * 3. **Dass der Dialog der Reiter ist, kein Nachbau.** Die Karte je Zone,
 *    das Häkchen aus T4-A2 mit denselben Regeln, die Dauer-Auswahl im
 *    Allgemeinbereich — alles aus `ManualOverridePanelList` (§5.53).
 * 4. **Dass man in der Liste bleibt** und die Spalte „Übersteuerung"
 *    danach nachzieht. Das zweite hing an einer Lücke: die Mutation
 *    verwarf `["room", id]`, nicht `["rooms"]`.
 * 5. **Beide Rollen**, ausdrücklich gesetzt und nicht über den Standard
 *    der Hülle (Bedingung des Betreibers vom 14.10.2026).
 *
 * **Ein Allgemeinbereich ist hier nicht ausgegraut** — und das ist eine
 * Abweichung von der Vorgabe, mit Beleg: `override_service.create` führt
 * einen Bereich mit der Quelle `frontend_bereich` am Belegungs-Gate
 * vorbei (`override_service.py:524-534`), und die Zimmerseite bietet den
 * Knopf dort seit Sprint 24d an (`sprint24d-allgemeinbereiche.spec.ts`
 * prüft genau das). Eine Liste, die ihn sperrt, wäre die dritte Meinung
 * zu einer Frage, die zwei Stellen schon beantworten.
 */

const ADMIN = {
  id: 1,
  email: "chef@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-30T06:00:00Z",
  last_login_at: "2026-10-30T06:00:00Z",
};

const MITARBEITER = {
  ...ADMIN,
  id: 2,
  email: "rezeption@hotel.example.com",
  role: "mitarbeiter" as const,
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

interface RaumLage {
  nummer?: string;
  status?: string;
  blocked?: boolean;
  bisCheckout?: boolean;
  bereich?: boolean;
  aktiverOverride?: boolean;
}

function raum(lage: RaumLage = {}): Record<string, unknown> {
  return {
    id: 101,
    number: lage.nummer ?? "101",
    display_name: "Gartenblick",
    room_type_id: 1,
    floor: 1,
    orientation: null,
    // Ein Allgemeinbereich bleibt vom Belegungs-Abgleich unberührt und
    // steht deshalb auf `vacant` — genau der Fall, in dem `istBereich`
    // das Belegungs-Gate aufhebt.
    status: lage.status ?? (lage.bereich ? "vacant" : "occupied"),
    guest_override_blocked: lage.blocked ?? false,
    guest_block_bis_checkout: lage.bisCheckout ?? false,
    ist_allgemeinbereich: lage.bereich ?? false,
    has_active_override: lage.aktiverOverride ?? false,
    notes: null,
    created_at: "2026-04-01T10:00:00Z",
    updated_at: "2026-10-30T06:00:00Z",
    reference_zone_id: 201,
    mean_temperature_c: 20.4,
    engine_setpoint_c: 21,
  };
}

interface Steuerung {
  /** Der Rumpf des letzten POST auf die Übersteuerungen, oder `null`. */
  gesendet: () => Record<string, unknown> | null;
}

/**
 * Mockt die Zimmerliste **und** den Dialog-Inhalt. Nach einem POST liefert
 * `/rooms` das Zimmer mit `has_active_override: true` — so wird prüfbar,
 * ob die Liste überhaupt neu lädt.
 */
async function mockApi(
  page: Page,
  lage: RaumLage = {},
  rolle: typeof ADMIN | typeof MITARBEITER = ADMIN,
): Promise<Steuerung> {
  const json = (r: Route, body: unknown) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  let gesendet: Record<string, unknown> | null = null;
  let aktiv = lage.aktiverOverride ?? false;
  const angelegt: Record<string, unknown>[] = [];

  // Catch-all zuerst: Playwright trifft die **zuletzt** registrierte Route
  // zuerst, der Rückhalt steht also unten in der Trefferreihenfolge.
  await page.route("**/api/v1/**", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) => json(r, rolle));
  await page.route(/.*\/api\/v1\/room-types(\?.*)?$/, (r: Route) => json(r, [RAUMTYP]));
  await page.route(/.*\/api\/v1\/rooms\/101\/heating-zones(\?.*)?$/, (r: Route) =>
    json(r, [ZONE]),
  );
  await page.route(/.*\/api\/v1\/rooms\/101\/engine-trace(\?.*)?$/, (r: Route) =>
    json(r, []),
  );
  await page.route(/.*\/api\/v1\/rooms\/101\/overrides(\?.*)?$/, async (r: Route) => {
    if (r.request().method() === "POST") {
      gesendet = JSON.parse(r.request().postData() ?? "{}") as Record<string, unknown>;
      aktiv = true;
      // Der angelegte Eintrag kommt beim nächsten Lesen zurück — sonst
      // wäre nicht prüfbar, dass der Dialog die **Bestätigung** zeigt.
      angelegt.push({
        id: 901,
        room_id: 101,
        heating_zone_id: 201,
        setpoint: String(gesendet.setpoint ?? "21"),
        source: gesendet.source ?? "frontend_24h",
        expires_at: "2099-01-01T00:00:00Z",
        reason: null,
        created_at: "2026-10-30T09:00:00Z",
        created_by: rolle.email,
        revoked_at: null,
        revoked_reason: null,
        wirksam_gekappt_c: null,
      });
      await r.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(angelegt[0]),
      });
      return;
    }
    await json(r, angelegt);
  });
  await page.route(/.*\/api\/v1\/rooms\/101(\?.*)?$/, (r: Route) => json(r, raum(lage)));
  await page.route(/.*\/api\/v1\/rooms(\?.*)?$/, (r: Route) =>
    json(r, [raum({ ...lage, aktiverOverride: aktiv })]),
  );

  return { gesendet: () => gesendet };
}

/**
 * Die Dauer im Auswahlfeld der Zone setzen — **im Dialog**. Die Seite
 * selbst hat drei Filter-Felder, und ein `<select>` trägt dieselbe Rolle
 * wie der Auswahlknopf des Formulars.
 */
async function waehleDauer(page: Page, label: RegExp): Promise<void> {
  await page.getByTestId("uebersteuern-dialog").getByRole("combobox").first().click();
  await page.getByRole("option", { name: label }).click();
}

test.describe("Zimmerübersicht — Übersteuern direkt in der Liste", () => {
  test("belegtes Zimmer: der Knopf ist drückbar und öffnet den Dialog", async ({ page }) => {
    await mockApi(page);
    await page.goto("/zimmer");

    const knopf = page.getByTestId("uebersteuern-101");
    await expect(knopf).toBeEnabled();
    await knopf.click();

    const dialog = page.getByTestId("uebersteuern-dialog");
    await expect(dialog).toBeVisible();
    // Es ist der Reiter, nicht ein zweites Formular: die Karte je Zone
    // samt Häkchen aus T4-A2 steht drin.
    await expect(dialog.getByRole("heading", { name: "Schlafzimmer" })).toBeVisible();
    await expect(dialog.getByTestId("gast-sperre-haken")).toBeVisible();

    // Kein Seitenwechsel.
    expect(new URL(page.url()).pathname).toBe("/zimmer");
  });

  test("freies Zimmer: ausgegraut, und der Grund steht daneben", async ({ page }) => {
    await mockApi(page, { status: "vacant" });
    await page.goto("/zimmer");

    const knopf = page.getByTestId("uebersteuern-101");
    await expect(knopf).toBeDisabled();
    // Der Satz nennt die Bedingung, nicht einen der vier Status, die hier
    // landen — ein Zimmer in Reinigung ist nicht „frei".
    //
    // Zwei Wege, beide geprüft: der Tooltip hängt am umschließenden
    // `span`, weil der gesperrte Knopf `pointer-events-none` trägt und
    // seinen eigenen nie zeigen würde; derselbe Satz steht als `sr-only`
    // für Vorleseprogramme daneben.
    await expect(knopf.locator("xpath=..")).toHaveAttribute(
      "title",
      /Übersteuern nur bei belegten Zimmern/,
    );
    await expect(page.getByText(/Übersteuern nur bei belegten Zimmern/)).toBeAttached();
  });

  test('Zimmer in Reinigung: derselbe Grund, nicht „frei“', async ({ page }) => {
    await mockApi(page, { status: "cleaning" });
    await page.goto("/zimmer");

    await expect(page.getByTestId("uebersteuern-101")).toBeDisabled();
    await expect(page.getByText(/Übersteuern nur bei belegten Zimmern/)).toBeAttached();
  });

  test("dauerhaft gesperrt: ausgegraut mit der Sperre als Grund", async ({ page }) => {
    await mockApi(page, { blocked: true });
    await page.goto("/zimmer");

    await expect(page.getByTestId("uebersteuern-101")).toBeDisabled();
    await expect(page.getByText(/Übersteuerung gesperrt/).first()).toBeAttached();
  });

  test("gesperrt bis Check-out: der Knopf bleibt drückbar", async ({ page }) => {
    // Sprint 23 T4-A2: diese Sperre nimmt dem **Gast** das Rad, nicht der
    // Rezeption die Eingabe. Das Gate im Dienst lässt die
    // `frontend_*`-Quellen aus demselben Grund durch. Wäre der Knopf hier
    // grau, müsste die Rezeption für eine Korrektur den Umweg „aufheben,
    // setzen, wieder sperren" gehen — mit einer Lücke in der Mitte.
    await mockApi(page, { blocked: true, bisCheckout: true });
    await page.goto("/zimmer");

    await expect(page.getByTestId("uebersteuern-101")).toBeEnabled();
  });

  test("Allgemeinbereich: drückbar, und der Dialog zeigt die Dauer", async ({ page }) => {
    // Abweichung von der Vorgabe, belegt im Kopf dieser Datei: der Dienst
    // führt einen Bereich am Belegungs-Gate vorbei, die Zimmerseite bietet
    // den Knopf an. Das Häkchen aus T4-A2 fehlt dort zu Recht — ein
    // Bereich hat keine Abreise, an der die Sperre enden könnte.
    await mockApi(page, { bereich: true });
    await page.goto("/zimmer");

    await page.getByTestId("uebersteuern-101").click();

    const dialog = page.getByTestId("uebersteuern-dialog");
    await expect(dialog.getByTestId("bereich-dauer")).toBeVisible();
    await expect(dialog.getByTestId("gast-sperre-haken")).toHaveCount(0);
  });

  test("Abschicken aus der Liste (Mitarbeiter): Spalte zieht nach", async ({ page }) => {
    const ctrl = await mockApi(page, {}, MITARBEITER);
    await page.goto("/zimmer");

    const zeile = page.getByRole("row").filter({ hasText: "101" });
    await expect(zeile.getByLabel("Übersteuerung aktiv")).toHaveCount(0);

    await page.getByTestId("uebersteuern-101").click();
    const dialog = page.getByTestId("uebersteuern-dialog");
    await dialog.getByRole("button", { name: "Anwenden" }).click();

    await expect.poll(() => ctrl.gesendet()).toMatchObject({
      setpoint: "21",
      source: "frontend_24h",
      heating_zone_id: 201,
    });

    // Der Dialog bleibt offen und zeigt den gesetzten Wert — das ist die
    // Bestätigung, und sie ist der Grund, warum er sich nicht selbst
    // schließt.
    await expect(dialog.getByRole("button", { name: "Übersteuerung aufheben" })).toBeVisible();

    // Zu — und die Spalte dahinter sagt jetzt „Aktiv". Erst hier geprüft,
    // weil Radix den Rest der Seite währenddessen `aria-hidden` setzt:
    // rollen-basierte Suchen finden die Tabelle dann nicht, ganz
    // unabhängig davon, ob sie neu geladen hat.
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);

    expect(new URL(page.url()).pathname).toBe("/zimmer");
    await expect(zeile.getByLabel("Übersteuerung aktiv")).toBeVisible();
  });

  test("Abschicken aus der Liste (Admin): derselbe Weg", async ({ page }) => {
    const ctrl = await mockApi(page, {}, ADMIN);
    await page.goto("/zimmer");

    await page.getByTestId("uebersteuern-101").click();
    await page
      .getByTestId("uebersteuern-dialog")
      .getByRole("button", { name: "Anwenden" })
      .click();

    await expect.poll(() => ctrl.gesendet()).toMatchObject({ heating_zone_id: 201 });
    expect(new URL(page.url()).pathname).toBe("/zimmer");
  });

  test("das Häkchen gilt im Dialog mit denselben Regeln", async ({ page }) => {
    const ctrl = await mockApi(page);
    await page.goto("/zimmer");
    await page.getByTestId("uebersteuern-101").click();

    const haken = page.getByTestId("uebersteuern-dialog").getByTestId("gast-sperre-haken");
    // Vorauswahl ist „24 Stunden" — also gesperrt, mit Grund.
    await expect(haken).toBeDisabled();

    await waehleDauer(page, /Bis Check-out/);
    await expect(haken).toBeEnabled();
    await haken.check();
    await page.getByRole("button", { name: "Anwenden" }).click();

    await expect.poll(() => ctrl.gesendet()).toMatchObject({
      source: "frontend_checkout",
      gast_sperre_bis_checkout: true,
    });
  });

  test("Details führt auf die Zimmerseite", async ({ page }) => {
    await mockApi(page);
    await page.goto("/zimmer");

    await page.getByTestId("details-101").click();

    await expect(page).toHaveURL(/\/zimmer\/101$/);
  });
});
