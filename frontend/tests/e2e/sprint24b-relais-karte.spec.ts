import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Sprint 24b, Paket 6 — die Relais-Karte auf der Geräteseite.
 *
 * Drei Dinge werden geprüft:
 *
 * 1. Die Karte sagt **zuerst**, ob das Relais schalten darf, und warum
 *    nicht. Das ist die Frage, mit der jemand auf diese Seite kommt.
 * 2. Die Rolle entscheidet über die Knöpfe — und zwar **beide**
 *    Richtungen, ausdrücklich gesetzt, nicht über den Standard der Hülle
 *    (`fixtures.ts`).
 * 3. „nicht bestätigt" ist kein Fehler. Eine Rücklesung, deren Antwort
 *    noch nicht da ist, ist bei einem Funkgerät der Normalfall.
 *
 * **Was hier nicht geprüft wird: der Schutz.** Die Knöpfe auszublenden
 * ist Bedienung. Abgewiesen wird serverseitig, und das prüft
 * `test_api_relays.py` (Mutationsprobe M12).
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

const DEVICE = {
  id: 77,
  dev_eui: "beef000000000077",
  app_eui: null,
  kind: "relay" as const,
  vendor: "mclimate" as const,
  model: "16ASPM",
  label: "Panel Barbereich",
  heating_zone_id: 9,
  retired_at: null,
  retired_reason: null,
  replaced_by_device_id: null,
  last_seen_at: "2026-10-24T07:55:00Z",
  firmware_version: "1.5",
  health_state: "healthy" as const,
  valve_state: "ok" as const,
  valve_delta_k: null,
  battery_state: "unbekannt" as const,
  created_at: "2026-10-20T10:00:00Z",
  updated_at: "2026-10-24T07:55:00Z",
  hardware_number: null,
  heating_zone: {
    id: 9,
    name: "Barbereich",
    health_state: "healthy",
    room: { id: 3, number: "Bar", room_type: { id: 5, name: "Raum intern" } },
  },
  active_override: null,
  latest_reading: null,
};

const HW_STATUS = {
  device_id: 77,
  status: "ok" as const,
  source: "window" as const,
  mounted_confirmed_at: null,
  frames_in_window: 3,
  window_minutes: 30,
};

/** Ein Relais, das noch nicht in Betrieb genommen ist. */
const STAND_NEU = {
  device_id: 77,
  dev_eui: "beef000000000077",
  label: "Panel Barbereich",
  firmware_version: "1.5",
  last_seen_at: "2026-10-24T07:55:00Z",
  commissioned_at: null,
  power_return_verified: false,
  overheating_recovery_verified: false,
  protection_tripped_at: null,
  protection_kind: null,
  switch_cycles: 0,
  watchdog_strategy: "expire_and_resend",
  darf_schalten: false,
  provisionierung_laeuft: false,
  relay_on: null,
  power_w: null,
  energy_wh: null,
  internal_temperature_raw: null,
  gehaeusetemperatur_alarm: false,
  reading_time: null,
  change_reason: null,
  offener_befehl: null,
};

/** Dasselbe Relais in Betrieb, eingeschaltet. */
const STAND_LAEUFT = {
  ...STAND_NEU,
  commissioned_at: "2026-10-24T06:00:00Z",
  power_return_verified: true,
  overheating_recovery_verified: true,
  darf_schalten: true,
  relay_on: true,
  power_w: 1600,
  energy_wh: 1234567,
  internal_temperature_raw: 31,
  switch_cycles: 4,
  reading_time: "2026-10-24T07:55:00Z",
  change_reason: "radio_timer",
};

/** Mit einem EIN, das seit vier Versuchen nicht bestaetigt ist. */
const STAND_UNBESTAETIGT = {
  ...STAND_LAEUFT,
  relay_on: false,
  power_w: 0,
  offener_befehl: {
    ziel_ein: true,
    seit: "2026-10-24T07:50:00Z",
    versuche: 2,
    gemeldet: false,
  },
};

/** Dasselbe, nachdem der Alarm heraus ist. */
const STAND_GEMELDET = {
  ...STAND_UNBESTAETIGT,
  offener_befehl: {
    ziel_ein: true,
    seit: "2026-10-24T07:20:00Z",
    versuche: 5,
    gemeldet: true,
  },
};

/** Und mit stehender Schutz-Sperre. */
const STAND_GESPERRT = {
  ...STAND_LAEUFT,
  darf_schalten: false,
  relay_on: false,
  power_w: 0,
  protection_tripped_at: "2026-10-24T07:40:00Z",
  protection_kind: "overheating",
};

function json(route: Route, body: unknown) {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function mock(
  page: Page,
  { stand, nutzer }: { stand: unknown; nutzer: unknown },
) {
  // Auffangnetz zuerst: alles Unbekannte bekommt ein leeres Objekt. Die
  // spezifischen Wege darunter gewinnen, weil Playwright die ZULETZT
  // registrierte Route zuerst trifft.
  await page.route("**/api/v1/**", (r: Route) => json(r, {}));
  await page.route("**/api/v1/auth/me", (r: Route) => json(r, nutzer));
  await page.route("**/api/v1/devices/77/hardware-status", (r: Route) =>
    json(r, HW_STATUS),
  );
  await page.route("**/api/v1/devices/77/sensor-readings*", (r: Route) =>
    json(r, []),
  );
  await page.route("**/api/v1/devices/77", (r: Route) => {
    if (r.request().method() !== "GET") return r.fallback();
    return json(r, DEVICE);
  });
  // **Die Relais-Route zuletzt, und das ist nicht Geschmack.** Playwright
  // trifft die ZULETZT registrierte Route zuerst, und das Muster
  // ``**/api/v1/devices/77`` greift auch auf ``/devices/77/relay``.
  // Andersherum bekam die Karte das Geraete-Objekt, scheiterte an der
  // Zod-Pruefung und zeigte ihren Fehler-Zustand — eine Stunde Suche
  // (Verwandtschaft zu §5.54: Playwright-Routen matchen anders als
  // erwartet).
  await page.route("**/api/v1/devices/77/relay", (r: Route) => json(r, stand));
}

test.describe("Relais-Karte", () => {
  test("ein nicht in Betrieb genommenes Relais nennt den Grund", async ({
    page,
  }) => {
    await mock(page, { stand: STAND_NEU, nutzer: ADMIN });
    await page.goto("/devices/77");

    const karte = page.getByTestId("relay-card");
    await expect(karte).toBeVisible();
    await expect(page.getByTestId("relay-sperrgrund")).toContainText(
      "Nicht in Betrieb genommen",
    );
    // Und die Begründung, warum das kein Totalausfall ist.
    await expect(page.getByTestId("relay-sperrgrund")).toContainText(
      "Lese- und Konfigurationsbefehle",
    );
  });

  test("nicht bestätigte Rücklesungen stehen als solche da, nicht als Fehler", async ({
    page,
  }) => {
    await mock(page, { stand: STAND_NEU, nutzer: ADMIN });
    await page.goto("/devices/77");

    const karte = page.getByTestId("relay-card");
    await expect(karte).toContainText("Aus nach Stromrückkehr");
    await expect(karte).toContainText("Aus nach Überhitzungs-Erholung");
    // Beide Zeilen „nicht bestätigt" — und das Wort „Fehler" kommt nicht
    // vor. Geprueft am Kennzeichen, nicht am Text: die Material-Ikone
    // steht im selben Element.
    await expect(
      page.getByTestId("relay-pruefung-stromrueckkehr"),
    ).toHaveAttribute("data-bestanden", "false");
    await expect(
      page.getByTestId("relay-pruefung-ueberhitzung"),
    ).toHaveAttribute("data-bestanden", "false");
    await expect(karte).toContainText("nicht bestätigt");
    await expect(karte).not.toContainText("Fehler");
  });

  test("ein laufendes Relais zeigt Zustand, Leistung und Zähler", async ({
    page,
  }) => {
    await mock(page, { stand: STAND_LAEUFT, nutzer: ADMIN });
    await page.goto("/devices/77");

    const karte = page.getByTestId("relay-card");
    await expect(page.getByTestId("relay-darf-schalten")).toBeVisible();
    await expect(karte).toContainText("1600 W");
    await expect(karte).toContainText("1234567 Wh");
    await expect(
      page.getByTestId("relay-pruefung-stromrueckkehr"),
    ).toHaveAttribute("data-bestanden", "true");
    await expect(
      page.getByTestId("relay-pruefung-ueberhitzung"),
    ).toHaveAttribute("data-bestanden", "true");
  });

  test("der Zaehler sagt, was er zaehlt", async ({ page }) => {
    // **Zwei Befunde, zwei Etiketten.**
    //
    // 01.11.2026: Die Geraeteseite zeigte „Schaltzyklen 0", obwohl 109
    // im T3.0-Lauf mehrfach geschaltet hatte. Der Zaehler war richtig --
    // gezaehlt wurde nur, was der Orchestrator gesendet und das Geraet
    // bestaetigt hat, und T3.0 lief von Hand daran vorbei. Daraufhin
    // hiess die Zeile „Schaltzyklen der Steuerung".
    //
    // 12.11.2026: Dieselbe Buchfuehrung hat auch einen Zyklus der
    // Steuerung verloren -- der Wunsch kippte, bevor die Bestaetigung
    // ankam. Seit dem 13.11. zaehlt die **gemeldete** Zustandsaenderung,
    // und das Etikett sagt das: „Einschaltungen (gemeldet)".
    await mock(page, { stand: STAND_LAEUFT, nutzer: ADMIN });
    await page.goto("/devices/77");

    await expect(page.getByTestId("relay-card")).toContainText(
      "Einschaltungen (gemeldet)",
    );
    // Und das alte Etikett ist weg, nicht nur ergaenzt: „der Steuerung"
    // waere jetzt die Falschaussage, die es vorher nicht war.
    await expect(page.getByTestId("relay-card")).not.toContainText(
      "Schaltzyklen der Steuerung",
    );
  });

  test("ein unbestaetigter Befehl ist sichtbar", async ({ page }) => {
    // Bis zum 02.11.2026 hatte dieser Zustand keinen Leser ausser dem
    // Orchestrator: ein Relais, das seit Stunden nicht bestaetigt, stand
    // als Alarm im Log und sonst nirgends.
    await mock(page, { stand: STAND_UNBESTAETIGT, nutzer: ADMIN });
    await page.goto("/devices/77");

    const karte = page.getByTestId("relay-card");
    await expect(karte).toContainText("Unbestätigter Befehl");
    await expect(karte).toContainText("EIN, 2 Versuche");
    await expect(karte).not.toContainText("gedrosselt");
  });

  test("nach dem Alarm sagt die Karte, dass nur noch gedrosselt gesendet wird", async ({
    page,
  }) => {
    await mock(page, { stand: STAND_GEMELDET, nutzer: ADMIN });
    await page.goto("/devices/77");

    const karte = page.getByTestId("relay-card");
    await expect(karte).toContainText("EIN, 5 Versuche");
    await expect(karte).toContainText("gemeldet, wird nur noch gedrosselt");
  });

  test("eine stehende Schutz-Sperre nennt Art und Zeitpunkt", async ({
    page,
  }) => {
    await mock(page, { stand: STAND_GESPERRT, nutzer: ADMIN });
    await page.goto("/devices/77");

    await expect(page.getByTestId("relay-sperrgrund")).toContainText(
      "Schutz-Sperre",
    );
    await expect(page.getByTestId("relay-sperrgrund")).toContainText(
      "overheating",
    );
    await expect(page.getByTestId("relay-sperrgrund")).toContainText(
      "nur durch einen Administrator",
    );
    // Und der Freigabe-Knopf erscheint nur in diesem Fall.
    await expect(page.getByTestId("relay-release")).toBeVisible();
  });

  test("ein Administrator sieht die Handgriffe", async ({ page }) => {
    await mock(page, { stand: STAND_NEU, nutzer: ADMIN });
    await page.goto("/devices/77");

    await expect(page.getByTestId("relay-provision")).toBeVisible();
    await expect(page.getByTestId("relay-commission")).toBeVisible();
    // Kein Freigabe-Knopf ohne Sperre.
    await expect(page.getByTestId("relay-release")).toHaveCount(0);
  });

  test("ein Mitarbeiter sieht keinen einzigen Handgriff", async ({ page }) => {
    await mock(page, { stand: STAND_GESPERRT, nutzer: MITARBEITER });
    await page.goto("/devices/77");

    // Die Karte selbst ist da — lesen darf jeder angemeldete Nutzer.
    await expect(page.getByTestId("relay-card")).toBeVisible();
    await expect(page.getByTestId("relay-sperrgrund")).toBeVisible();

    // Aber keine Handlung, auch nicht die Freigabe bei stehender Sperre.
    await expect(page.getByTestId("relay-provision")).toHaveCount(0);
    await expect(page.getByTestId("relay-commission")).toHaveCount(0);
    await expect(page.getByTestId("relay-decommission")).toHaveCount(0);
    await expect(page.getByTestId("relay-release")).toHaveCount(0);
  });

  test("der Provisionierungs-Hinweis behauptet kein Ergebnis", async ({
    page,
  }) => {
    await mock(page, { stand: STAND_NEU, nutzer: ADMIN });
    await page.route("**/api/v1/devices/77/relay/provision", (r: Route) =>
      json(r, {
        device_id: 77,
        // „geplant", nicht „gesendet": der Endpunkt kehrt zurück, bevor
        // der erste Downlink hinaus ist (01.11.2026).
        geplant: ["0x04", "0x5E 02", "0x59 01", "0x5F", "0x5A"],
        laeuft: true,
        hinweis:
          "Laeuft — fuenf Befehle mit je 15 Sekunden Abstand, rund 75 Sekunden. " +
          "Die Antworten kommen mit dem naechsten Uplink; erst danach zeigt die " +
          "Geraeteseite beide Ruecklesungen als bestanden, und erst dann laesst " +
          "sich das Relais in Betrieb nehmen.",
      }),
    );
    await page.goto("/devices/77");

    await page.getByTestId("relay-provision").click();
    // Der Hinweis sagt, dass das Ergebnis noch nicht da ist — alles
    // andere waere eine Zusicherung ohne Deckung.
    await expect(page.getByTestId("relay-meldung")).toContainText("Laeuft");
  });

  test("ein Thermostat zeigt keine Relais-Karte", async ({ page }) => {
    await mock(page, { stand: STAND_NEU, nutzer: ADMIN });
    // Dieselbe Seite, nur ein Thermostat. Die Route wird NACH dem
    // Mock-Satz registriert und gewinnt deshalb.
    await page.route("**/api/v1/devices/77", (r: Route) => {
      if (r.request().method() !== "GET") return r.fallback();
      return json(r, { ...DEVICE, kind: "thermostat", model: "vicki" });
    });
    await page.goto("/devices/77");

    // Erst pruefen, dass die SEITE da ist -- sonst waere die Zusicherung
    // darunter falsch-gruen, und genau das ist beim ersten Versuch
    // passiert (§5.55).
    await expect(
      page.getByRole("heading", { name: "Panel Barbereich" }),
    ).toBeVisible();
    await expect(page.getByTestId("relay-card")).toHaveCount(0);
  });

  test("ein laufender Auftrag ist sichtbar und sperrt den Knopf", async ({
    page,
  }) => {
    // **Der Befund vom 01.11.2026, 10:26.** Der Handgriff dauert rund 75
    // Sekunden, die Oberfläche brach nach etwa 30 ab — und zeigte danach
    // nichts, was ihn von „noch nicht angestoßen" unterschied. Genau in
    // diesem Zustand macht man ihn zweimal, und zwei Läufe gleichzeitig
    // wären zehn Downlinks ohne Pause.
    await mock(page, {
      stand: { ...STAND_NEU, provisionierung_laeuft: true },
      nutzer: ADMIN,
    });
    await page.goto("/devices/77");

    await expect(
      page.getByTestId("relay-provisionierung-laeuft"),
    ).toContainText("fünf Befehle");
    const knopf = page.getByTestId("relay-provision");
    await expect(knopf).toBeDisabled();
    await expect(knopf).toContainText("läuft");
  });

  test("ohne laufenden Auftrag ist der Knopf bedienbar", async ({ page }) => {
    // Die Gegenprobe, und sie ist nicht überflüssig: ein Knopf, der
    // **immer** gesperrt ist, hätte denselben Test oben grün gemacht.
    await mock(page, { stand: STAND_NEU, nutzer: ADMIN });
    await page.goto("/devices/77");

    await expect(page.getByTestId("relay-provisionierung-laeuft")).toHaveCount(
      0,
    );
    const knopf = page.getByTestId("relay-provision");
    await expect(knopf).toBeEnabled();
    await expect(knopf).toContainText("Provisionieren");
  });
});
