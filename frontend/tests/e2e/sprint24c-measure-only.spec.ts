import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Sprint 24c — Umschalter „nur messen“ auf der Geräteseite.
 *
 * **Das Abschlusskriterium, Browser-Hälfte.** Ein Admin schaltet eine
 * Vicki auf „nur messen“, das Kennzeichen erscheint, und der Zustand der
 * Kindersicherung wird angezeigt. Die Engine-Hälfte (Trace zeigt den
 * Raumtyp-Sollwert statt 10 °C) prüft `test_measure_only_trace.py`.
 *
 * **Beide Rollen ausdrücklich gesetzt**, nicht über den Standard der
 * Hülle (`fixtures.ts`): ein Rollen-Test, der sich auf den Standard
 * verlässt, prüft nur „Admin sieht den Knopf" und nie die andere
 * Richtung. Mutationsprobe **M14** greift hier an.
 *
 * **Die Server-Seite prüft dieser Test nicht.** Dass ein Mitarbeiter mit
 * gültiger Sitzung 403 bekommt, steht in `test_api_relays.py` — und
 * zwar mit injizierter Rolle und nicht mit fehlendem Cookie, weil unter
 * `AUTH_ENABLED=false` ein fehlendes Cookie einen System-Admin ergibt
 * (Lehre aus 24b).
 *
 * **Routen-Reihenfolge:** Playwright trifft die **zuletzt** registrierte
 * Route zuerst, und das Muster auf `api/v1/devices/77` greift auch auf
 * `/devices/77/audit`. Die spezifischen Wege stehen deshalb hinter dem
 * Geräte-Weg — in 24b hat die umgekehrte Reihenfolge eine Stunde
 * gekostet.
 */

const ADMIN = {
  id: 1,
  email: "admin@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-24T06:00:00Z",
  last_login_at: "2026-10-24T06:00:00Z",
};

const MITARBEITER = { ...ADMIN, id: 2, role: "mitarbeiter" as const };

const VICKI = {
  id: 77,
  dev_eui: "beef000000000077",
  app_eui: null,
  kind: "thermostat" as const,
  vendor: "mclimate" as const,
  model: "vicki",
  label: "Vicki 027",
  heating_zone_id: 9,
  retired_at: null,
  retired_reason: null,
  replaced_by_device_id: null,
  last_seen_at: "2026-10-24T07:55:00Z",
  firmware_version: "4.4",
  health_state: "healthy" as const,
  valve_state: "unbekannt" as const,
  valve_delta_k: null,
  battery_state: "ok" as const,
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-24T07:55:00Z",
  hardware_number: null,
  measure_only: false,
  child_lock_state: "ausstehend" as const,
  // Normales Thermostat ohne Gast-Sperre: das Rad soll frei sein. Die
  // Fixtures darunter setzen es um, wo die Rolle oder die Sperre greift.
  rad_gesperrt_gewollt: false,
  heating_zone: {
    id: 9,
    name: "Barbereich",
    health_state: "healthy",
    room: { id: 3, number: "Bar", room_type: { id: 5, name: "Raum intern" } },
  },
  active_override: null,
  latest_reading: null,
};

/** Dieselbe Vicki mit gesetzter Rolle und bestätigter Sperre. */
const VICKI_FUEHLER = {
  ...VICKI,
  measure_only: true,
  child_lock_state: "bestaetigt" as const,
  rad_gesperrt_gewollt: true,
};

/** Rolle gesetzt, aber das Gerät meldet das Rad als frei. */
const VICKI_SPERRE_FEHLT = {
  ...VICKI,
  measure_only: true,
  child_lock_state: "fehlgeschlagen" as const,
  rad_gesperrt_gewollt: true,
};

const HW_STATUS = {
  device_id: 77,
  status: "ok" as const,
  source: "window" as const,
  mounted_confirmed_at: null,
  frames_in_window: 3,
  window_minutes: 30,
};

const AUDIT = [
  {
    ts: "2026-10-24T08:10:00Z",
    action: "DEVICE_MEASURE_ONLY_TOGGLED",
    benutzer: "admin@hotel.example.com",
    alt: { measure_only: false },
    neu: { measure_only: true, kindersicherung_gesendet: true },
  },
];

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function mock(
  page: Page,
  { device, nutzer, audit = [] }: { device: unknown; nutzer: unknown; audit?: unknown[] },
) {
  await page.route("**/api/v1/**", (r: Route) => json(r, {}));
  await page.route("**/api/v1/auth/me", (r: Route) => json(r, nutzer));
  await page.route("**/api/v1/devices/77/hardware-status", (r: Route) => json(r, HW_STATUS));
  await page.route("**/api/v1/devices/77/sensor-readings*", (r: Route) => json(r, []));
  await page.route("**/api/v1/devices/77", (r: Route) => {
    if (r.request().method() !== "GET") return r.fallback();
    return json(r, device);
  });
  // Hinter dem Geraete-Weg — siehe Kopf.
  await page.route("**/api/v1/devices/77/audit", (r: Route) => json(r, audit));
}

test.describe("Umschalter „nur messen“", () => {
  test("ein Administrator sieht die Rolle und den Umschalter", async ({ page }) => {
    await mock(page, { device: VICKI, nutzer: ADMIN });
    await page.goto("/devices/77");

    await expect(page.getByTestId("measure-only-card")).toBeVisible();
    await expect(page.getByTestId("measure-only-zustand")).toHaveAttribute(
      "data-measure-only",
      "false",
    );
    await expect(page.getByTestId("measure-only-zustand")).toContainText("stellt und misst");
    await expect(page.getByTestId("measure-only-toggle")).toBeVisible();
  });

  test("der Dialog nennt alle drei Folgen im Klartext", async ({ page }) => {
    await mock(page, { device: VICKI, nutzer: ADMIN });
    await page.goto("/devices/77");

    await page.getByTestId("measure-only-toggle").click();

    // Keine Sollwerte, Rad ohne Wirkung, nicht in der Geräte-Sicherheit.
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("keine Sollwerte");
    await expect(dialog).toContainText("Rad wird ignoriert");
    await expect(dialog).toContainText("Geräte-Sicherheit");
    await expect(dialog).toContainText("Kindersicherung");
  });

  test("Umschalten setzt die Rolle, das Kennzeichen erscheint", async ({ page }) => {
    // Erst der Zustand ohne Rolle, nach dem PATCH der mit.
    let umgeschaltet = false;
    await page.route("**/api/v1/**", (r: Route) => json(r, {}));
    await page.route("**/api/v1/auth/me", (r: Route) => json(r, ADMIN));
    await page.route("**/api/v1/devices/77/hardware-status", (r: Route) => json(r, HW_STATUS));
    await page.route("**/api/v1/devices/77/sensor-readings*", (r: Route) => json(r, []));
    await page.route("**/api/v1/devices/77", (r: Route) => {
      if (r.request().method() !== "GET") return r.fallback();
      return json(r, umgeschaltet ? VICKI_FUEHLER : VICKI);
    });
    await page.route("**/api/v1/devices/77/audit", (r: Route) => json(r, umgeschaltet ? AUDIT : []));
    await page.route("**/api/v1/devices/77/measure-only", (r: Route) => {
      umgeschaltet = true;
      return json(r, {
        device_id: 77,
        measure_only: true,
        kindersicherung_gesendet: true,
        hinweis:
          "Die Kindersicherung wird mit dem naechsten Keepalive bestaetigt (Feld child_lock).",
      });
    });

    await page.goto("/devices/77");
    await expect(page.getByTestId("fuehler-badge")).toHaveCount(0);

    await page.getByTestId("measure-only-toggle").click();
    await page.getByRole("button", { name: "Umstellen" }).click();

    // Die Meldung sagt, dass die Bestätigung noch aussteht.
    await expect(page.getByTestId("measure-only-meldung")).toContainText("Keepalive");
    // Und der Zustand ist umgeschaltet.
    await expect(page.getByTestId("measure-only-zustand")).toHaveAttribute(
      "data-measure-only",
      "true",
    );
    await expect(page.getByTestId("measure-only-zustand")).toContainText("Nur messen");
  });

  test("der Zustand der Kindersicherung wird angezeigt", async ({ page }) => {
    await mock(page, { device: VICKI_FUEHLER, nutzer: ADMIN });
    await page.goto("/devices/77");

    const status = page.getByTestId("child-lock-status");
    await expect(status).toHaveAttribute("data-zustand", "bestaetigt");
    // Sprint 23 T4-B: der Satz nennt **beides** — was gelten soll und ob
    // das Gerät es bestätigt hat. „Kindersicherung bestätigt" genügte,
    // solange nur Fühler eine Sperre hatten und der gewollte Zustand
    // damit immer „gesperrt" war.
    await expect(status).toContainText("Rad gesperrt · bestätigt");
  });

  test("eine nicht gesetzte Sperre ist ein Befund, eine ausstehende nicht", async ({
    page,
  }) => {
    await mock(page, { device: VICKI_SPERRE_FEHLT, nutzer: ADMIN });
    await page.goto("/devices/77");

    const status = page.getByTestId("child-lock-status");
    await expect(status).toHaveAttribute("data-zustand", "fehlgeschlagen");
    await expect(status).toContainText("meldet es als frei");
  });

  test("auch ohne Rolle und ohne Sperre steht da, dass das Rad frei ist", async ({ page }) => {
    /**
     * **Befund des Betreibers, 01.11.2026.** Hier prüfte dieser Test bis
     * dahin das Gegenteil: „soll frei sein und ist frei" wurde
     * verschwiegen, mit der Begründung „eine Aussage ohne Frage".
     *
     * Die Frage gibt es aber, und zwar nach dem Lösen einer Sperre:
     * **ist das Rad in diesem Zimmer wieder bedienbar?** Eine leere
     * Karte beantwortet sie nicht — sie sieht aus wie „dazu wissen wir
     * nichts". Eine Information, die aus dem **Fehlen** einer Anzeige
     * gelesen werden muss, ist die Falle aus §5.57.
     */
    await mock(page, {
      device: { ...VICKI, child_lock_state: "bestaetigt" as const },
      nutzer: ADMIN,
    });
    await page.goto("/devices/77");

    await expect(page.getByTestId("measure-only-card")).toBeVisible();
    await expect(page.getByTestId("child-lock-status")).toContainText("Rad frei · bestätigt");
  });

  // **Die Breiten sind gemessen, nicht gewählt** (01.11.2026).
  //
  // Befund des Betreibers: „der Knopf ragt über den Kartenrand". Die
  // erste Vermutung war der lange Text — der macht 240 px und hätte in
  // jede Karte gepasst. Zu schmal war der **Slot**: die Rollen-Karte
  // stand im KPI-Raster mit vier Spalten und hatte bei **768 px**
  // Fensterbreite 118 px, bei **375 px** 155 px.
  //
  // Bei 1024 px und darüber ist die Karte breit genug — eine Prüfung nur
  // in der Standard-Breite hätte den Befund **nicht** gefangen. Genau das
  // ist beim ersten Anlauf passiert: die Probe gegen den langen Text
  // blieb grün.
  for (const breite of [768, 375]) {
    test(`der Umschalt-Knopf bleibt bei ${breite} px in der Karte`, async ({ page }) => {
      await page.setViewportSize({ width: breite, height: 900 });
      await mock(page, { device: VICKI, nutzer: ADMIN });
      await page.goto("/devices/77");

      const karte = page.getByTestId("measure-only-card");
      const knopf = page.getByTestId("measure-only-toggle");
      await expect(knopf).toBeVisible();

      const k = await karte.boundingBox();
      const b = await knopf.boundingBox();
      expect(k, "Karte muss sichtbar sein").not.toBeNull();
      expect(b, "Knopf muss sichtbar sein").not.toBeNull();
      if (k === null || b === null) return;

      expect(b.x + b.width, "rechter Rand des Knopfes").toBeLessThanOrEqual(k.x + k.width);
      expect(b.x, "linker Rand des Knopfes").toBeGreaterThanOrEqual(k.x);
    });
  }

  test("ein gast-gesperrtes Thermostat zeigt den Sperr-Status", async ({ page }) => {
    /**
     * **Der Befund, der diese Prüfung nötig gemacht hat.**
     *
     * Die Karte zeigte den Sperr-Status nur für Fühler. Mit Sprint 23
     * T4-B hat ein **normales** Thermostat in einem gast-gesperrten
     * Zimmer ein gesperrtes Rad — und die Karte zeigte dafür nichts.
     *
     * Damit wären die Schritte der Pflicht-Stop-Prüfung in RUNBOOK §10ar
     * nicht ablesbar gewesen: sie liest an genau dieser Stelle „Rad
     * gesperrt · ausstehend" und später „· bestätigt".
     *
     * Die alte Bedingung war nicht falsch, sie ist zu eng geworden
     * (§5.77).
     */
    await mock(page, {
      device: {
        ...VICKI,
        measure_only: false as const,
        rad_gesperrt_gewollt: true,
        child_lock_state: "ausstehend" as const,
      },
      nutzer: ADMIN,
    });
    await page.goto("/devices/77");

    const status = page.getByTestId("child-lock-status");
    await expect(status).toHaveAttribute("data-zustand", "ausstehend");
    await expect(status).toContainText("Rad gesperrt · ausstehend");
    // Und die Rolle steht weiter auf „normal" — die Sperre kommt nicht
    // von ihr, und die Karte darf das nicht vermischen.
    await expect(page.getByTestId("measure-only-zustand")).toContainText("Normal");
  });

  test("ein Rad, das gegen den Willen gesperrt meldet, ist ein Befund", async ({ page }) => {
    // Die Gegenrichtung von „fehlgeschlagen": gewollt frei, gemeldet
    // gesperrt. Vorher war dieser Fall unsichtbar, weil die Karte für ein
    // normales Thermostat gar nichts zeigte — und ein Gast, dessen Rad
    // ohne Grund still ist, ruft an der Rezeption an.
    await mock(page, {
      device: {
        ...VICKI,
        measure_only: false as const,
        rad_gesperrt_gewollt: false,
        child_lock_state: "fehlgeschlagen" as const,
      },
      nutzer: ADMIN,
    });
    await page.goto("/devices/77");

    const status = page.getByTestId("child-lock-status");
    await expect(status).toContainText("meldet es als gesperrt");
  });

  test("ein Mitarbeiter sieht die Rolle, aber keinen Umschalter", async ({ page }) => {
    await mock(page, { device: VICKI_FUEHLER, nutzer: MITARBEITER, audit: AUDIT });
    await page.goto("/devices/77");

    // Lesen darf er: Zustand, Sperr-Status und Historie.
    await expect(page.getByTestId("measure-only-zustand")).toBeVisible();
    await expect(page.getByTestId("child-lock-status")).toBeVisible();
    await expect(page.getByTestId("device-audit-zeile")).toHaveCount(1);

    // **Mutationsprobe M14.**
    await expect(page.getByTestId("measure-only-toggle")).toHaveCount(0);
  });

  test("die Historie nennt den Handgriff und wer ihn getan hat", async ({ page }) => {
    await mock(page, { device: VICKI_FUEHLER, nutzer: ADMIN, audit: AUDIT });
    await page.goto("/devices/77");

    const zeile = page.getByTestId("device-audit-zeile");
    await expect(zeile).toHaveCount(1);
    await expect(zeile).toContainText("Rolle");
    await expect(zeile).toContainText("gesetzt");
    await expect(zeile).toContainText("admin@hotel.example.com");
  });

  test("eine leere Historie sagt das, statt leer zu bleiben", async ({ page }) => {
    await mock(page, { device: VICKI, nutzer: ADMIN });
    await page.goto("/devices/77");

    await expect(page.getByTestId("device-audit-leer")).toContainText("Noch kein Handgriff");
  });
});
