import { test, expect, type Page, type Route } from "./fixtures";

/**
 * Sprint 23 T4-A — die Gast-Sperre und ihre Form.
 *
 * Geprüft wird, was man ohne Backend sehen kann und was im Betrieb
 * schiefgehen würde:
 *
 * 1. Die Auswahl steht vor dem Sperren, und „Bis Check-out" schickt das
 *    Feld wirklich mit.
 * 2. Ist gesperrt, **steht dabei, in welcher Form** — das ist die
 *    Information, die an der Rezeption gebraucht wird: muss sich jemand
 *    nach der Abreise darum kümmern oder nicht.
 * 3. Im Allgemeinbereich wird „bis Check-out" **nicht angeboten**. Der
 *    Server weist es mit 422 ab (dort endet die Sperre nie), und eine
 *    Oberfläche, die anbietet, was der Server abweist, ist die
 *    Fehlerklasse aus Sprint 22.
 * 4. Ein 422 vom Server erscheint **mit seinem Satz**. `apiClient` wirft
 *    ein einfaches Objekt; wer `e.message` liest, zeigt einen leeren
 *    Kasten (§24e) — und ein leerer Kasten ist von „nichts passiert"
 *    nicht zu unterscheiden.
 */

const MOCK_MITARBEITER = {
  id: 2,
  email: "rezeption@hotel.example.com",
  role: "mitarbeiter" as const,
  is_active: true,
  must_change_password: false,
  created_at: "2026-05-01T10:00:00Z",
  updated_at: "2026-10-25T10:00:00Z",
  last_login_at: "2026-10-25T10:00:00Z",
};

function roomMock(opts: {
  blocked: boolean;
  bisCheckout: boolean;
  bereich: boolean;
}): Record<string, unknown> {
  return {
    id: 101,
    number: "101",
    display_name: "Gartenblick",
    room_type_id: 1,
    floor: 1,
    orientation: null,
    status: opts.bereich ? "allgemeinbereich" : "occupied",
    guest_override_blocked: opts.blocked,
    guest_block_bis_checkout: opts.bisCheckout,
    ist_allgemeinbereich: opts.bereich,
    notes: null,
    created_at: "2026-04-01T10:00:00Z",
    updated_at: "2026-10-25T10:00:00Z",
  };
}

interface Steuerung {
  gesendet: () => { blocked: boolean; bis_checkout: boolean } | null;
}

async function mockApi(
  page: Page,
  opts: {
    blocked?: boolean;
    bisCheckout?: boolean;
    bereich?: boolean;
    patchStatus?: number;
    patchDetail?: string;
  } = {},
): Promise<Steuerung> {
  let raum = roomMock({
    blocked: opts.blocked ?? false,
    bisCheckout: opts.bisCheckout ?? false,
    bereich: opts.bereich ?? false,
  });
  let gesendet: { blocked: boolean; bis_checkout: boolean } | null = null;

  // Catch-all leer. Playwright trifft die zuletzt registrierte Route
  // zuerst, deshalb steht er hier oben.
  await page.route("**/api/v1/**", (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );

  await page.route(/.*\/api\/v1\/auth\/me(\?.*)?$/, (r: Route) =>
    r.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK_MITARBEITER),
    }),
  );

  // Muss VOR /rooms/101 stehen (zuletzt registriert trifft zuerst).
  await page.route(
    /.*\/api\/v1\/rooms\/101\/override-block-state(\?.*)?$/,
    async (r: Route) => {
      if (r.request().method() !== "PATCH") {
        await r.fulfill({ status: 405, body: "" });
        return;
      }
      const body = JSON.parse(r.request().postData() ?? "{}") as {
        blocked: boolean;
        bis_checkout?: boolean;
      };
      gesendet = { blocked: body.blocked, bis_checkout: body.bis_checkout ?? false };

      if (opts.patchStatus !== undefined && opts.patchStatus >= 400) {
        await r.fulfill({
          status: opts.patchStatus,
          contentType: "application/json",
          body: JSON.stringify({ detail: opts.patchDetail ?? "abgewiesen" }),
        });
        return;
      }

      raum = roomMock({
        blocked: body.blocked,
        bisCheckout: body.blocked && (body.bis_checkout ?? false),
        bereich: opts.bereich ?? false,
      });
      await r.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(raum),
      });
    },
  );

  await page.route(/.*\/api\/v1\/rooms\/101(\?.*)?$/, (r: Route) =>
    r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(raum) }),
  );

  return { gesendet: () => gesendet };
}

test.describe("Sprint 23 T4-A Gast-Sperre", () => {
  test("die Auswahl steht vor dem Sperren und schickt bis_checkout mit", async ({
    page,
  }) => {
    const ctrl = await mockApi(page);
    await page.goto("/zimmer/101");

    await page.getByTestId("sperre-knopf").click();
    await expect(page.getByTestId("sperre-auswahl")).toBeVisible();

    await page.getByRole("button", { name: "Bis Check-out sperren" }).click();

    await expect.poll(() => ctrl.gesendet()).toEqual({
      blocked: true,
      bis_checkout: true,
    });
    await expect(page.getByText("Gesperrt bis zur Abreise.")).toBeVisible();
  });

  test("bei gesperrtem Zimmer steht die Form dabei", async ({ page }) => {
    await mockApi(page, { blocked: true, bisCheckout: true });
    await page.goto("/zimmer/101");

    await expect(page.getByTestId("sperre-form")).toHaveText("endet mit der Abreise");
  });

  test("eine dauerhafte Sperre sagt, dass sie bleibt", async ({ page }) => {
    // Das ist der Satz, der den Fall benennt, den T4-A behebt: eine
    // Sperre, die den nächsten Gast trifft.
    await mockApi(page, { blocked: true, bisCheckout: false });
    await page.goto("/zimmer/101");

    await expect(page.getByTestId("sperre-form")).toContainText("nächsten Gast");
  });

  test("im Allgemeinbereich gibt es kein bis Check-out", async ({ page }) => {
    await mockApi(page, { bereich: true });
    await page.goto("/zimmer/101");

    await page.getByTestId("sperre-knopf").click();
    await expect(page.getByTestId("sperre-auswahl")).toBeVisible();

    await expect(
      page.getByRole("button", { name: "Bis Check-out sperren" }),
    ).toHaveCount(0);
    await expect(page.getByText(/hat keine Abreise/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Dauerhaft sperren" })).toBeVisible();
  });

  test("ein 422 erscheint mit dem Satz des Servers", async ({ page }) => {
    const satz = "Ein Allgemeinbereich hat keine Abreise — hier gilt nur die dauerhafte Sperre.";
    await mockApi(page, { patchStatus: 422, patchDetail: satz });
    await page.goto("/zimmer/101");

    await page.getByTestId("sperre-knopf").click();
    await page.getByRole("button", { name: "Bis Check-out sperren" }).click();

    // Nicht „Aktion fehlgeschlagen." und nicht leer — der Satz selbst.
    await expect(page.getByText(satz)).toBeVisible();
  });

  test("Abbrechen schickt nichts", async ({ page }) => {
    const ctrl = await mockApi(page);
    await page.goto("/zimmer/101");

    await page.getByTestId("sperre-knopf").click();
    await page.getByRole("button", { name: "Abbrechen" }).click();

    await expect(page.getByTestId("sperre-auswahl")).toHaveCount(0);
    expect(ctrl.gesendet()).toBeNull();
  });
});
