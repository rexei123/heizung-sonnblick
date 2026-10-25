import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Das Formular zeigt den Raumtyp, der links ausgewählt ist (25.10.2026).
 *
 * **Der Befund des Betreibers.** Auf der Raumtypen-Seite war links „Raum
 * intern" ausgewählt, „Was davon gilt" zeigte korrekt 21/19 — und das
 * Bearbeitungsformular darunter zeigte „Raum mit Exit" mit 19/17. Bei
 * jedem Aufruf der Seite. Ein Klick auf „Aktualisieren" hätte die Werte
 * des einen Raumtyps in den anderen geschrieben.
 *
 * **Die Ursache.** `RoomTypeForm` baut seinen Zustand mit
 * `useState(initial ?? …)` auf, und das läuft **einmal je Montage**. Ohne
 * `key` blieb die Komponente beim Wechsel der Auswahl montiert und
 * behielt die Werte des vorher gewählten Raumtyps.
 *
 * **Warum drei Fälle und nicht einer.** Der erste prüft den Wechsel, der
 * zweite den Neuaufruf (der Betreiber hat es dort gesehen), und der
 * dritte, dass ein Speichern den **ausgewählten** Datensatz trifft und
 * keinen anderen — das ist der Schaden, um den es ging.
 *
 * **Mutationsprobe M28** greift am `key` an: ohne ihn sind der erste und
 * der dritte Fall rot.
 */

const ADMIN = {
  id: 1,
  email: "chef@hotel.example.com",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-25T06:00:00Z",
  last_login_at: "2026-10-25T06:00:00Z",
};

/** „Raum intern" — die Bar. */
const A = {
  id: 5,
  name: "Raum intern",
  description: null,
  is_bookable: false,
  default_t_occupied: "21.0",
  default_t_vacant: "21.0",
  default_t_night: "19.0",
  max_temp_celsius: "25.0",
  min_temp_celsius: "16.0",
  treat_unoccupied_as_vacant_after_hours: null,
  created_at: "2026-04-01T10:00:00Z",
  updated_at: "2026-10-24T06:00:00Z",
};

/** „Raum mit Exit" — die Rezeption. Andere Werte, damit sie zu erkennen sind. */
const B = {
  ...A,
  id: 6,
  name: "Raum mit Exit",
  default_t_occupied: "19.0",
  default_t_vacant: "19.0",
  default_t_night: "17.0",
};

const WIRKSAMKEIT = [A, B].map((rt) => ({
  room_type_id: rt.id,
  name: rt.name,
  is_bookable: rt.is_bookable,
  zeile_vorhanden: false,
  wuerde_sich_aendern: false,
  felder: [
    {
      feld: "default_t_occupied",
      angezeigt: Number(rt.default_t_occupied),
      wirksam: Number(rt.default_t_occupied),
      quelle: "raumtyp",
    },
    {
      feld: "default_t_vacant",
      angezeigt: Number(rt.default_t_vacant),
      wirksam: Number(rt.default_t_vacant),
      quelle: "raumtyp",
    },
    {
      feld: "default_t_night",
      angezeigt: Number(rt.default_t_night),
      wirksam: Number(rt.default_t_night),
      quelle: "raumtyp",
    },
  ],
}));

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function mock(page: Page): Promise<void> {
  await page.route("**/api/v1/**", (r: Route) => json(r, []));
  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) => json(r, ADMIN));
  await page.route(/.*\/api\/v1\/room-types(\?.*)?$/, (r: Route) => json(r, [A, B]));
  // Hinter der Liste — das Muster auf ``room-types`` greift sonst mit.
  await page.route(/.*\/api\/v1\/room-types\/sollwert-wirksamkeit$/, (r: Route) =>
    json(r, WIRKSAMKEIT),
  );
}

/** Das Namensfeld des Formulars — die eindeutigste Probe. */
function nameFeld(page: Page) {
  return page.locator("#rt-name");
}

test.describe("Raumtyp-Formular zeigt den ausgewählten Datensatz", () => {
  test("Wechsel der Auswahl: A wählen, dann B — das Formular zeigt B", async ({ page }) => {
    await mock(page);
    await page.goto("/raumtypen");

    await page.getByRole("listitem").filter({ hasText: "Raum intern" }).click();
    await expect(nameFeld(page)).toHaveValue("Raum intern");
    await expect(page.getByLabel("Betrieb", { exact: true })).toHaveValue("21.0");

    await page.getByRole("listitem").filter({ hasText: "Raum mit Exit" }).click();

    // **Hier war der Fehler:** ohne `key` stand hier weiter „Raum intern".
    await expect(nameFeld(page)).toHaveValue("Raum mit Exit");
    await expect(page.getByLabel("Betrieb", { exact: true })).toHaveValue("19.0");
    await expect(page.getByLabel("Absenkung", { exact: true })).toHaveValue("17.0");
  });

  test("Neuaufruf der Seite: B wählen — das Formular zeigt B", async ({ page }) => {
    // Der Fall, den der Betreiber gesehen hat: „tritt bei jedem neuen
    // Aufruf der Seite auf".
    await mock(page);
    await page.goto("/raumtypen");
    await page.getByRole("listitem").filter({ hasText: "Raum intern" }).click();
    await expect(nameFeld(page)).toHaveValue("Raum intern");

    await page.reload();
    await page.getByRole("listitem").filter({ hasText: "Raum mit Exit" }).click();

    await expect(nameFeld(page)).toHaveValue("Raum mit Exit");
    await expect(page.getByLabel("Absenkung", { exact: true })).toHaveValue("17.0");
  });

  test("Speichern trifft den ausgewählten Datensatz und keinen anderen", async ({
    page,
  }) => {
    await mock(page);

    const geschrieben: { pfad: string; koerper: Record<string, unknown> }[] = [];
    await page.route(/.*\/api\/v1\/room-types\/\d+$/, async (r: Route) => {
      if (r.request().method() !== "PATCH") return r.fallback();
      const url = new URL(r.request().url());
      geschrieben.push({
        pfad: url.pathname,
        koerper: JSON.parse(r.request().postData() ?? "{}") as Record<string, unknown>,
      });
      return json(r, { ...B, default_t_vacant: "20.0" });
    });

    await page.goto("/raumtypen");
    await page.getByRole("listitem").filter({ hasText: "Raum intern" }).click();
    await expect(nameFeld(page)).toHaveValue("Raum intern");
    await page.getByRole("listitem").filter({ hasText: "Raum mit Exit" }).click();
    await expect(nameFeld(page)).toHaveValue("Raum mit Exit");

    await page.getByLabel("Betrieb", { exact: true }).fill("20.0");
    await page.getByRole("button", { name: "Aktualisieren" }).click();

    await expect.poll(() => geschrieben.length).toBe(1);
    const [anfrage] = geschrieben;
    // Der Weg trägt die ID von B — nicht die von A.
    expect(anfrage.pfad).toBe("/api/v1/room-types/6");
    // Und der Körper trägt den Namen von B und das Echo seiner ID.
    expect(anfrage.koerper.name).toBe("Raum mit Exit");
    expect(anfrage.koerper.id).toBe(6);
    expect(anfrage.koerper.default_t_vacant).toBe(20);
  });

  test("beim Anlegen gibt es kein ID-Echo", async ({ page }) => {
    // Die Gegenprobe zum Echo: ein neuer Raumtyp hat keine ID, und ein
    // mitgesendetes `id: null` wäre ein Feld, das der Server prüfen
    // müsste, obwohl es nichts bedeutet.
    await mock(page);

    let koerper: Record<string, unknown> | null = null;
    await page.route(/.*\/api\/v1\/room-types$/, async (r: Route) => {
      if (r.request().method() !== "POST") return r.fallback();
      koerper = JSON.parse(r.request().postData() ?? "{}") as Record<string, unknown>;
      return json(r, { ...A, id: 9, name: "Spa" }, 201);
    });

    await page.goto("/raumtypen");
    await page.getByRole("button", { name: "Neuer Raumtyp" }).click();
    await nameFeld(page).fill("Spa");
    await page.getByRole("button", { name: "Anlegen" }).click();

    await expect.poll(() => koerper).not.toBeNull();
    expect(koerper!.name).toBe("Spa");
    expect("id" in koerper!).toBe(false);
  });
});
