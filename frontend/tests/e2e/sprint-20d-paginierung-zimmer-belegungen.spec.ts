import { test, expect, type Page, type Route } from "@playwright/test";

/**
 * Sprint 20d (B-20c-2) — Zimmer vollständig, Belegungen geblättert.
 *
 * **Befund, 02.10.2026 auf dem Server gemessen:** `SELECT count(*) FROM
 * occupancy WHERE is_active` ergab **959**. Die Belegungen-Seite stand auf
 * `limit: 200` und hat im Bereich „Alle" 200 davon gezeigt, ohne das zu
 * sagen. 759 fehlten — derselbe Befund wie bei den Geräten (20c), nur vier
 * Mal so groß.
 *
 * Zimmer und Raumtypen hatten denselben Default 100 und vier Aufrufer mit
 * drei verschiedenen Antworten darauf (1000, 1000, 200, nichts).
 *
 * **Die beiden Fälle werden absichtlich verschieden gelöst**, und diese
 * Datei prüft beides getrennt:
 *
 * - Zimmer und Raumtypen sind nach oben gebunden (45 Zimmer, eine Handvoll
 *   Typen) → der Client holt **alle** Seiten, die Oberfläche blättert nicht.
 * - Belegungen wachsen unbegrenzt → **echte** Paginierung mit Gesamtzahl,
 *   „N von M" und „Weitere laden".
 *
 * Die Mocks werten `limit` und `offset` aus und liefern echte Teilmengen.
 * Ein Mock, der unabhängig von den Parametern alles zurückgibt, hätte den
 * Bug nie gezeigt — er war ja genau die Annahme, die falsch war. Und die
 * **Zahl der Aufrufe** gehört mit zur Prüfung: ohne sie wäre „alle Zeilen
 * sichtbar" auch mit einem Mock erfüllt, der `limit` ignoriert.
 *
 * Route-Muster sind **Regex mit `$`** (§5.54): sie erfassen die URL mit und
 * ohne Query-String und treffen Unterpfade wie `/rooms/101/heating-zones`
 * nicht.
 */

/** Seitengröße im Client. Muss zu `alle-seiten.ts` passen. */
const SEITE = 100;

/** Seitengröße der Belegungen. Muss zu `hooks-occupancies.ts` passen. */
const BELEGUNGEN_SEITE = 100;

const MOCK_MITARBEITER = {
  id: 2,
  email: "rezeption@hotel.example.com",
  role: "mitarbeiter" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-02T10:00:00Z",
  last_login_at: "2026-10-02T18:00:00Z",
};

function roomMock(id: number): Record<string, unknown> {
  return {
    id,
    number: `Z${String(id).padStart(4, "0")}`,
    display_name: null,
    room_type_id: 1,
    floor: 1,
    orientation: null,
    status: "occupied",
    guest_override_blocked: false,
    has_active_override: false,
    notes: null,
    created_at: "2026-04-01T10:00:00Z",
    updated_at: "2026-10-02T10:00:00Z",
  };
}

function roomTypeMock(id: number): Record<string, unknown> {
  return {
    id,
    name: `Typ ${String(id).padStart(4, "0")}`,
    description: null,
    is_bookable: true,
    default_t_occupied: "21.0",
    default_t_vacant: "18.0",
    default_t_night: "19.0",
    max_temp_celsius: null,
    min_temp_celsius: null,
    treat_unoccupied_as_vacant_after_hours: null,
    created_at: "2026-04-01T10:00:00Z",
    updated_at: "2026-10-02T10:00:00Z",
  };
}

function occupancyMock(id: number): Record<string, unknown> {
  // Alle mit **demselben** check_in — der Fall, in dem die Sortierung
  // eindeutig sein muss, damit über Seiten nichts doppelt oder verloren
  // geht (Backend: `order_by(check_in, id)`).
  return {
    id,
    room_id: 1,
    check_in: "2026-07-01T12:00:00Z",
    check_out: "2026-07-02T10:00:00Z",
    guest_count: 2,
    source: "pms",
    external_id: null,
    is_active: true,
    cancelled_at: null,
    created_at: "2026-06-01T10:00:00Z",
    updated_at: "2026-06-01T10:00:00Z",
  };
}

interface Aufrufe {
  /** Je Request das Paar, mit dem er kam — in Eintreff-Reihenfolge. */
  seiten: { limit: number; offset: number }[];
}

/** Liest `limit`/`offset` aus der URL; fehlendes `limit` = Server-Default. */
function seitenParameter(
  route: Route,
  standard: number,
): { limit: number; offset: number } {
  const url = new URL(route.request().url());
  return {
    limit: Number(url.searchParams.get("limit") ?? String(standard)),
    offset: Number(url.searchParams.get("offset") ?? "0"),
  };
}

/** Grundrauschen: Auth plus eine leere Antwort für alles Übrige. */
async function mockGrundlage(page: Page): Promise<void> {
  await page.route("**/api/v1/**", (route: Route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_MITARBEITER),
    }),
  );
}

/** Mockt `/rooms` als echte Paginierung über `gesamt` Zimmer. */
async function mockZimmer(page: Page, gesamt: number): Promise<Aufrufe> {
  const alle = Array.from({ length: gesamt }, (_, i) => roomMock(i + 1));
  const aufrufe: Aufrufe = { seiten: [] };
  await page.route(/.*\/api\/v1\/rooms(\?.*)?$/, (route: Route) => {
    const { limit, offset } = seitenParameter(route, SEITE);
    aufrufe.seiten.push({ limit, offset });
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(alle.slice(offset, offset + limit)),
    });
  });
  return aufrufe;
}

/** Mockt `/room-types` als echte Paginierung über `gesamt` Typen. */
async function mockRaumtypen(page: Page, gesamt: number): Promise<Aufrufe> {
  const alle = Array.from({ length: gesamt }, (_, i) => roomTypeMock(i + 1));
  const aufrufe: Aufrufe = { seiten: [] };
  await page.route(/.*\/api\/v1\/room-types(\?.*)?$/, (route: Route) => {
    const { limit, offset } = seitenParameter(route, SEITE);
    aufrufe.seiten.push({ limit, offset });
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(alle.slice(offset, offset + limit)),
    });
  });
  return aufrufe;
}

/**
 * Mockt `/occupancies` als Envelope mit Gesamtzahl.
 *
 * `total` ist **immer** `gesamt`, unabhängig von der Seite — genau wie im
 * Backend, wo es mit denselben Filtern gezählt wird. Die Oberfläche liest
 * es aus der ersten Seite; dass es auf jeder steht, hält der Backend-Test
 * fest.
 */
async function mockBelegungen(page: Page, gesamt: number): Promise<Aufrufe> {
  const alle = Array.from({ length: gesamt }, (_, i) => occupancyMock(i + 1));
  const aufrufe: Aufrufe = { seiten: [] };
  await page.route(/.*\/api\/v1\/occupancies(\?.*)?$/, (route: Route) => {
    const { limit, offset } = seitenParameter(route, BELEGUNGEN_SEITE);
    aufrufe.seiten.push({ limit, offset });
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: alle.slice(offset, offset + limit),
        total: gesamt,
        limit,
        offset,
      }),
    });
  });
  return aufrufe;
}

// ---------------------------------------------------------------------------
// 1. Zimmer und Raumtypen: alles holen
// ---------------------------------------------------------------------------

test.describe("Sprint 20d — Zimmer und Raumtypen über alle Seiten", () => {
  test("101 Zimmer: alle sichtbar, zwei Seiten geholt", async ({ page }) => {
    await mockGrundlage(page);
    await mockRaumtypen(page, 1);
    const aufrufe = await mockZimmer(page, 101);

    await page.goto("/zimmer");

    await expect(page.locator("tbody tr")).toHaveCount(101);
    // Das Zimmer auf der zweiten Seite ist das, das vorher gefehlt hätte.
    await expect(page.locator("tbody tr").last()).toContainText("Z0101");

    expect(aufrufe.seiten).toEqual([
      { limit: SEITE, offset: 0 },
      { limit: SEITE, offset: SEITE },
    ]);
  });

  test("Grenzfall genau 100 Zimmer: zweite Seite leer, Liste komplett", async ({
    page,
  }) => {
    // Hier entscheidet die Abbruchbedingung: die erste Seite kommt VOLL
    // zurück, damit ist offen, ob es weitergeht. Wer „voll" als „fertig"
    // liest, hat den Befund von 20c — nur ohne sichtbare Lücke, weil es
    // zufällig passt. Die Zeilenzahl ist in beiden Fällen gleich; **nur
    // die Zahl der Aufrufe** unterscheidet sie.
    await mockGrundlage(page);
    await mockRaumtypen(page, 1);
    const aufrufe = await mockZimmer(page, 100);

    await page.goto("/zimmer");

    await expect(page.locator("tbody tr")).toHaveCount(100);
    expect(aufrufe.seiten).toEqual([
      { limit: SEITE, offset: 0 },
      { limit: SEITE, offset: SEITE },
    ]);
  });

  test("99 Zimmer: ein Aufruf genügt, es wird nicht blind weitergeblättert", async ({
    page,
  }) => {
    await mockGrundlage(page);
    await mockRaumtypen(page, 1);
    const aufrufe = await mockZimmer(page, 99);

    await page.goto("/zimmer");

    await expect(page.locator("tbody tr")).toHaveCount(99);
    expect(aufrufe.seiten).toEqual([{ limit: SEITE, offset: 0 }]);
  });

  test("101 Raumtypen: alle sichtbar, zwei Seiten geholt", async ({ page }) => {
    await mockGrundlage(page);
    const aufrufe = await mockRaumtypen(page, 101);

    await page.goto("/raumtypen");

    // Die Raumtypen-Seite rendert eine Liste, keine Tabelle — und die
    // Seitenleiste bringt eigene `li` mit, deshalb auf den Knopf je
    // Eintrag eingegrenzt.
    const eintraege = page.locator("ul > li > button");
    await expect(eintraege).toHaveCount(101);
    await expect(eintraege.last()).toContainText("Typ 0101");
    expect(aufrufe.seiten).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// 2. Die Zimmerauswahl im Belegungs-Formular
// ---------------------------------------------------------------------------

test.describe("Sprint 20d — Zimmerauswahl im Belegungs-Formular", () => {
  test("Auswahlfeld bietet alle 101 Zimmer an", async ({ page }) => {
    // Der Aufrufer mit der härtesten Folge: ein Zimmer, das hier fehlt,
    // kann keine Belegung bekommen. Vorher stand hier `limit: 1000` — am
    // `le`-Anschlag des Endpoints, also eine Zahl, die bei 1001 Zimmern
    // still abschneidet und bei 100 Zimmern plus einem Server-Default-
    // Wechsel sofort.
    await mockGrundlage(page);
    const zimmerAufrufe = await mockZimmer(page, 101);
    await mockBelegungen(page, 0);

    await page.goto("/belegungen");
    await page.getByRole("button", { name: "Neue Belegung" }).click();

    const auswahl = page.locator("select").first();
    // 101 Zimmer plus die Platzhalter-Option.
    await expect(auswahl.locator("option")).toHaveCount(102);
    await expect(auswahl.locator("option", { hasText: "Z0101" })).toHaveCount(1);
    expect(zimmerAufrufe.seiten).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// 3. Belegungen: echte Paginierung mit „N von M"
// ---------------------------------------------------------------------------

test.describe("Sprint 20d — Belegungen seitenweise", () => {
  test("201 Belegungen: 100 von 201 → 200 von 201 → 201 von 201, Knopf weg", async ({
    page,
  }) => {
    // Der Befund selbst, in klein: 201 statt 959, damit drei Klicks reichen.
    // Entscheidend ist nicht die Zahl, sondern dass die Seite **sagt**, wie
    // viele es insgesamt sind — vorher zeigte sie 200 und schwieg.
    await mockGrundlage(page);
    await mockZimmer(page, 1);
    const aufrufe = await mockBelegungen(page, 201);

    await page.goto("/belegungen");

    await expect(page.getByText("100 von 201 aktive Belegung(en)")).toBeVisible();
    await expect(page.locator("tbody tr")).toHaveCount(100);

    const weitere = page.getByRole("button", { name: "Weitere laden" });
    await expect(weitere).toBeVisible();
    await weitere.click();

    await expect(page.getByText("200 von 201 aktive Belegung(en)")).toBeVisible();
    await expect(page.locator("tbody tr")).toHaveCount(200);

    await page.getByRole("button", { name: "Weitere laden" }).click();

    await expect(page.getByText("201 von 201 aktive Belegung(en)")).toBeVisible();
    await expect(page.locator("tbody tr")).toHaveCount(201);
    // Der Knopf ist selbst die Antwort auf „fehlt noch etwas".
    await expect(page.getByRole("button", { name: "Weitere laden" })).toHaveCount(0);

    expect(aufrufe.seiten).toEqual([
      { limit: BELEGUNGEN_SEITE, offset: 0 },
      { limit: BELEGUNGEN_SEITE, offset: BELEGUNGEN_SEITE },
      { limit: BELEGUNGEN_SEITE, offset: 2 * BELEGUNGEN_SEITE },
    ]);
  });

  test("12 Belegungen: kein Knopf, und es wird nicht weitergeblättert", async ({
    page,
  }) => {
    // Die Gegenprobe. Ohne sie könnte die Seite bei jedem Aufruf eine
    // überflüssige leere Seite holen, oder einen Knopf zeigen, der nichts
    // tut — beides würde niemandem auffallen.
    await mockGrundlage(page);
    await mockZimmer(page, 1);
    const aufrufe = await mockBelegungen(page, 12);

    await page.goto("/belegungen");

    await expect(page.getByText("12 von 12 aktive Belegung(en)")).toBeVisible();
    await expect(page.locator("tbody tr")).toHaveCount(12);
    await expect(page.getByRole("button", { name: "Weitere laden" })).toHaveCount(0);
    expect(aufrufe.seiten).toEqual([{ limit: BELEGUNGEN_SEITE, offset: 0 }]);
  });

  test("Grenzfall genau 200: der Knopf verschwindet erst nach der zweiten Seite", async ({
    page,
  }) => {
    // 200 ist die Zahl, auf der die Seite vorher stand. Mit dem alten Code
    // sah diese Ansicht **vollständig** aus und war es bei 959 Zeilen nicht.
    await mockGrundlage(page);
    await mockZimmer(page, 1);
    await mockBelegungen(page, 200);

    await page.goto("/belegungen");

    await expect(page.getByText("100 von 200 aktive Belegung(en)")).toBeVisible();
    await page.getByRole("button", { name: "Weitere laden" }).click();

    await expect(page.getByText("200 von 200 aktive Belegung(en)")).toBeVisible();
    await expect(page.locator("tbody tr")).toHaveCount(200);
    await expect(page.getByRole("button", { name: "Weitere laden" })).toHaveCount(0);
  });

  test("Bereich Alle fragt absteigend, enge Fenster aufsteigend", async ({
    page,
  }) => {
    // Gate-Entscheidung zu 20d: bei „Alle" zuerst die jüngsten. Sonst
    // zeigt die erste Seite bei 959 Zeilen den Juni, und wer heute sehen
    // will, klickt neun Mal.
    await mockGrundlage(page);
    await mockZimmer(page, 1);
    const richtungen: (string | null)[] = [];
    await page.route(/.*\/api\/v1\/occupancies(\?.*)?$/, (route: Route) => {
      const url = new URL(route.request().url());
      richtungen.push(url.searchParams.get("order"));
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], total: 0, limit: 100, offset: 0 }),
      });
    });

    await page.goto("/belegungen");
    // Vorgabe ist „Nächste 7 Tage" — ein enges Fenster, chronologisch.
    await expect.poll(() => richtungen).toContain("asc");

    await page.getByRole("button", { name: "Alle", exact: true }).click();
    await expect.poll(() => richtungen).toContain("desc");
  });
});
