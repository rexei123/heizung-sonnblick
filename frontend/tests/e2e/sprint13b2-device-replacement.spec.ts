import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Sprint 13b.2 T8 — Playwright E2E fuer Device-Lifecycle-Workflow
 * (Replace + Retire) auf /zimmer/[id] Geraete-Tab.
 *
 * Backend wird via ``page.route()`` gemockt (Pattern aus Sprint 12b
 * T5 manual-override-zone.spec.ts). §5.54-Regex-URLs mit ``(\?.*)?$``
 * fuer Query-String-tolerantes Match.
 *
 * Cases:
 *   1. Replace Happy-Path: Click "Tauschen" -> Reserve waehlen -> Submit
 *      -> Success-Toast + Dialog close + POST-Body-Assertion
 *   2. Pool-leer: Empty-State sichtbar + Submit-Button disabled
 *   3. 409 Pool-Race: Error-Toast "Reserve bereits vergeben" + Dialog
 *      bleibt offen + Pool-Refetch (zweiter GET /pool nach 409)
 *   4. Retire Happy-Path: Click "Stilllegen" -> Reason waehlen -> Submit
 *      -> Success-Toast + Dialog close
 *   5. Retire Last-Active-Warning: Warning-Box sichtbar wenn Zone nur
 *      einen aktiven Vicki hat
 */

const MOCK_ADMIN = {
  id: 1,
  email: "admin@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-14T10:00:00Z",
  last_login_at: "2026-05-22T18:00:00Z",
};

const ROOM = {
  id: 101,
  number: "101",
  display_name: "Gartenblick",
  room_type_id: 1,
  floor: 1,
  orientation: null,
  status: "occupied",
  guest_override_blocked: false,
  notes: null,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-05-15T10:00:00Z",
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

const NOW = new Date().toISOString();

const DEVICE_IN_ROOM = {
  id: 42,
  dev_eui: "aabbccddeeff0011",
  app_eui: null,
  kind: "thermostat" as const,
  vendor: "mclimate" as const,
  model: "Vicki",
  label: "Vicki Schlafzimmer 101",
  heating_zone_id: ZONE.id,
  retired_at: null,
  retired_reason: null,
  replaced_by_device_id: null,
  last_seen_at: NOW,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-15T10:00:00Z",
};

const POOL_DEVICE_A = {
  id: 81,
  dev_eui: "aabbccddeeff1001",
  app_eui: null,
  kind: "thermostat" as const,
  vendor: "mclimate" as const,
  model: "Vicki",
  label: "Reserve Vicki A",
  heating_zone_id: null,
  retired_at: null,
  retired_reason: null,
  replaced_by_device_id: null,
  last_seen_at: NOW,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-01T10:00:00Z",
};

const POOL_DEVICE_B = {
  id: 82,
  dev_eui: "aabbccddeeff1002",
  app_eui: null,
  kind: "thermostat" as const,
  vendor: "mclimate" as const,
  model: "Vicki",
  label: "Reserve Vicki B",
  heating_zone_id: null,
  retired_at: null,
  retired_reason: null,
  replaced_by_device_id: null,
  last_seen_at: NOW,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-05-01T10:00:00Z",
};

const SAMPLE_HARDWARE_STATUS = {
  status: "active" as const,
  last_seen: NOW,
  frames_in_window: 3,
  window_minutes: 30,
};

/**
 * Mock-Skelett: Auth + Room + Zone + Hardware-Status. Devices-Listen +
 * Pool werden per Test ueberschrieben (catch-all darunter liefert []).
 */
async function mockBaseRoom(page: Page): Promise<void> {
  // Catch-all zuerst registrieren (Playwright: zuletzt registriert greift zuerst).
  await page.route("**/api/v1/**", async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "[]",
    });
  });

  await page.route("**/api/v1/auth/me", async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_ADMIN),
    });
  });

  await page.route(/.*\/api\/v1\/rooms\/101(\?.*)?$/, async (route: Route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(ROOM),
    });
  });

  await page.route(
    /.*\/api\/v1\/rooms\/101\/heating-zones(\?.*)?$/,
    async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([ZONE]),
      });
    },
  );

  await page.route(
    /.*\/api\/v1\/devices\/\d+\/hardware-status(\?.*)?$/,
    async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(SAMPLE_HARDWARE_STATUS),
      });
    },
  );
}

test.describe("Sprint 13b.2 — Device-Lifecycle Frontend", () => {
  test("Case 1 Replace Happy: Pool-Reassign + Toast + POST-Body", async ({
    page,
  }) => {
    await mockBaseRoom(page);

    let postedBody: Record<string, unknown> | null = null;

    await page.route(/.*\/api\/v1\/devices(\?.*)?$/, async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([DEVICE_IN_ROOM]),
      });
    });

    await page.route(
      /.*\/api\/v1\/devices\/pool(\?.*)?$/,
      async (route: Route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([POOL_DEVICE_A, POOL_DEVICE_B]),
        });
      },
    );

    await page.route(
      /.*\/api\/v1\/devices\/\d+\/replace\/from-pool$/,
      async (route: Route) => {
        if (route.request().method() !== "POST") {
          await route.continue();
          return;
        }
        postedBody = JSON.parse(route.request().postData() ?? "{}") as Record<
          string,
          unknown
        >;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ...DEVICE_IN_ROOM,
            heating_zone_id: null,
            retired_at: new Date().toISOString(),
            retired_reason: "replaced_by_pool",
            replaced_by_device_id: POOL_DEVICE_A.id,
          }),
        });
      },
    );

    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Geräte", exact: true }).click();

    await page
      .getByRole("button", { name: "Thermostat tauschen", exact: true })
      .click();

    await expect(
      page.getByRole("heading", { name: "Thermostat tauschen" }),
    ).toBeVisible();

    await page.getByLabel("Reserve-Thermostat").click();
    await page
      .getByRole("option", { name: "Reserve Vicki A", exact: true })
      .click();

    await page
      .getByRole("button", { name: "Tauschen", exact: true })
      .click();

    await expect(
      page.getByText("Thermostat getauscht — Engine übernimmt in ≤ 60 s"),
    ).toBeVisible();

    await expect(
      page.getByRole("heading", { name: "Thermostat tauschen" }),
    ).toBeHidden();

    await expect.poll(() => postedBody).not.toBeNull();
    expect(postedBody).toEqual({ new_pool_device_id: POOL_DEVICE_A.id });
  });

  test("Case 2 Pool-leer: Empty-State + Submit-Button disabled", async ({
    page,
  }) => {
    await mockBaseRoom(page);

    await page.route(/.*\/api\/v1\/devices(\?.*)?$/, async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([DEVICE_IN_ROOM]),
      });
    });

    await page.route(
      /.*\/api\/v1\/devices\/pool(\?.*)?$/,
      async (route: Route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: "[]",
        });
      },
    );

    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Geräte", exact: true }).click();

    await page
      .getByRole("button", { name: "Thermostat tauschen", exact: true })
      .click();

    await expect(
      page.getByText(
        "Kein Reserve-Thermostat verfügbar. Reserve über CLI-Skript hinzufügen (siehe RUNBOOK §10h).",
      ),
    ).toBeVisible();

    await expect(
      page.getByRole("button", { name: "Tauschen", exact: true }),
    ).toBeDisabled();
  });

  test("Case 3 Replace 409 Pool-Race: Error-Toast + Dialog bleibt offen + Pool-Refetch", async ({
    page,
  }) => {
    await mockBaseRoom(page);

    let poolCallCount = 0;

    await page.route(/.*\/api\/v1\/devices(\?.*)?$/, async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([DEVICE_IN_ROOM]),
      });
    });

    await page.route(
      /.*\/api\/v1\/devices\/pool(\?.*)?$/,
      async (route: Route) => {
        poolCallCount += 1;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify([POOL_DEVICE_A]),
        });
      },
    );

    await page.route(
      /.*\/api\/v1\/devices\/\d+\/replace\/from-pool$/,
      async (route: Route) => {
        if (route.request().method() !== "POST") {
          await route.continue();
          return;
        }
        await route.fulfill({
          status: 409,
          contentType: "application/json",
          body: JSON.stringify({
            detail:
              "new_pool_device_id=81 wurde parallel vergeben (race-Schutz: UPDATE-Rowcount=0).",
          }),
        });
      },
    );

    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Geräte", exact: true }).click();

    await page
      .getByRole("button", { name: "Thermostat tauschen", exact: true })
      .click();

    await page.getByLabel("Reserve-Thermostat").click();
    await page
      .getByRole("option", { name: "Reserve Vicki A", exact: true })
      .click();

    const callsBeforeSubmit = poolCallCount;
    await page
      .getByRole("button", { name: "Tauschen", exact: true })
      .click();

    await expect(
      page.getByText(
        "Reserve bereits vergeben. Bitte Auswahl erneut treffen.",
      ),
    ).toBeVisible();

    // Dialog bleibt offen (Header weiter sichtbar).
    await expect(
      page.getByRole("heading", { name: "Thermostat tauschen" }),
    ).toBeVisible();

    // Pool wurde nach 409 erneut geladen (qc.invalidateQueries im Dialog).
    await expect.poll(() => poolCallCount).toBeGreaterThan(callsBeforeSubmit);
  });

  test("Case 4 Retire Happy: Reason waehlen + Toast + Dialog close + POST-Body", async ({
    page,
  }) => {
    await mockBaseRoom(page);

    let postedBody: Record<string, unknown> | null = null;
    // Zwei aktive Vickis in derselben Zone -> isLastActiveInZone === false,
    // kein Warning-Block (deckt Case 4 ab; Case 5 testet das Gegenteil).
    const SECOND_DEVICE_IN_ZONE = {
      ...DEVICE_IN_ROOM,
      id: 43,
      dev_eui: "aabbccddeeff0012",
      label: "Vicki Schlafzimmer 101 (2)",
    };

    await page.route(/.*\/api\/v1\/devices(\?.*)?$/, async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([DEVICE_IN_ROOM, SECOND_DEVICE_IN_ZONE]),
      });
    });

    await page.route(
      /.*\/api\/v1\/devices\/\d+\/retire$/,
      async (route: Route) => {
        if (route.request().method() !== "POST") {
          await route.continue();
          return;
        }
        postedBody = JSON.parse(route.request().postData() ?? "{}") as Record<
          string,
          unknown
        >;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            ...DEVICE_IN_ROOM,
            retired_at: new Date().toISOString(),
            retired_reason: "Defekt",
          }),
        });
      },
    );

    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Geräte", exact: true }).click();

    // Erster Vicki-Row -> erster "Stilllegen"-Button.
    await page
      .getByRole("button", { name: "Thermostat stilllegen", exact: true })
      .first()
      .click();

    await expect(
      page.getByRole("heading", { name: "Thermostat stilllegen" }),
    ).toBeVisible();

    // Warning-Box darf NICHT erscheinen (2 aktive Vickis in der Zone).
    await expect(
      page.getByText("Letzter aktiver Thermostat dieser Zone."),
    ).toBeHidden();

    await page.getByLabel("Grund").click();
    await page.getByRole("option", { name: "Defekt", exact: true }).click();

    await page
      .getByRole("button", { name: "Stilllegen", exact: true })
      .click();

    await expect(page.getByText("Thermostat stillgelegt")).toBeVisible();

    await expect(
      page.getByRole("heading", { name: "Thermostat stilllegen" }),
    ).toBeHidden();

    await expect.poll(() => postedBody).not.toBeNull();
    expect(postedBody).toEqual({ reason: "Defekt" });
  });

  test("Case 5 Retire Last-Active-Warning: Warning-Box sichtbar bei 1-Vicki-Zone", async ({
    page,
  }) => {
    await mockBaseRoom(page);

    // Genau ein aktiver Vicki in der Zone -> isLastActiveInZone === true.
    await page.route(/.*\/api\/v1\/devices(\?.*)?$/, async (route: Route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([DEVICE_IN_ROOM]),
      });
    });

    await page.goto("/zimmer/101");
    await page.getByRole("button", { name: "Geräte", exact: true }).click();

    await page
      .getByRole("button", { name: "Thermostat stilllegen", exact: true })
      .click();

    await expect(
      page.getByText("Letzter aktiver Thermostat dieser Zone."),
    ).toBeVisible();
    await expect(
      page.getByText(
        /Heizung in dieser Zone wird nach Stilllegung inaktiv/,
      ),
    ).toBeVisible();
  });
});
