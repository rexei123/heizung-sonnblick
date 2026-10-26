"use client";

/**
 * Die aktuellen Werte des Hauses, im Handbuch (Paket 1).
 *
 * **Die Zahlen stehen nicht im Text.** Der Auftrag sagt es ausdrücklich:
 * „aktuelle Werte (aus der DB gelesen, nicht hart codiert)". Der Grund ist
 * §5.77 in Reinform — eine Zahl in einem Handbuch ist eine Aussage über
 * den **heutigen** Stand, und sie verfällt beim ersten Nachjustieren. Wer
 * sie dann liest, glaubt sie, weil sie wie ein Befund aussieht.
 *
 * Deshalb steht im Artikel die Marke `{{werte}}`, und hier wird gelesen,
 * was gilt: der Hausstandard aus `rule-configs/global` und die Sollwerte
 * je Raumtyp mit ihrer **Wirksamkeit** (Sprint 24d). Letzteres ist der
 * wichtigere Teil: „21 °C steht beim Raumtyp" und „21 °C wirkt" sind
 * zwei Aussagen, und das Handbuch soll nicht die erste für die zweite
 * nehmen.
 */

import { useQuery } from "@tanstack/react-query";

import { fetchWirksamkeit, QUELLE_LABEL } from "@/lib/api/raumtyp-wirksamkeit";
import { ruleConfigsApi } from "@/lib/api/rule-configs";

const FELD_NAME: Record<string, string> = {
  default_t_occupied: "Belegt",
  default_t_vacant: "Frei / Betrieb",
  default_t_night: "Nacht / Absenkung",
};

/**
 * Die drei Temperatur-Felder kommen als **String** aus der API
 * (Pydantic-Decimal, bewusst nicht als Zahl — Float-Rundungsfreiheit,
 * §5.63). `null` heißt „nicht festgelegt", und das ist eine Aussage und
 * keine fehlende Zahl: dann entscheidet der Raumtyp.
 */
function zahl(v: string | null): string {
  if (v === null) return "nicht festgelegt";
  const n = Number.parseFloat(v);
  return Number.isNaN(n)
    ? v
    : `${n.toLocaleString("de-AT", { minimumFractionDigits: 1 })} °C`;
}

export function LebendeWerte() {
  const hausstandard = useQuery({
    queryKey: ["rule-config", "global"],
    queryFn: () => ruleConfigsApi.getGlobal(),
  });
  const wirksamkeit = useQuery({
    queryKey: ["sollwert-wirksamkeit"],
    queryFn: fetchWirksamkeit,
  });

  if (hausstandard.isLoading || wirksamkeit.isLoading) {
    return <p className="text-text-tertiary mb-4 text-sm">Werte werden geladen …</p>;
  }
  if (hausstandard.isError || wirksamkeit.isError) {
    return (
      <p className="text-error mb-4 text-sm">
        Die aktuellen Werte sind gerade nicht abrufbar. Der Text darüber gilt
        unabhängig davon — nur die Zahlen fehlen.
      </p>
    );
  }

  const hs = hausstandard.data;
  const typen = wirksamkeit.data ?? [];

  return (
    <div className="bg-surface-alt border-border mb-4 rounded-md border p-4" data-testid="handbuch-werte">
      <p className="text-text-tertiary mb-3 text-xs">
        Diese Tabelle wird beim Öffnen gelesen und steht nicht im Text — was
        hier steht, gilt jetzt.
      </p>

      <h3 className="text-text-primary mb-2 text-sm font-medium">Hausstandard</h3>
      <table className="mb-4 w-full text-sm">
        <thead>
          <tr className="text-text-tertiary text-xs">
            <th scope="col" className="pb-1 text-left font-medium">Feld</th>
            <th scope="col" className="pb-1 text-right font-medium">Wert</th>
          </tr>
        </thead>
        <tbody className="divide-border divide-y">
          <tr>
            <td className="py-1">Zimmer belegt</td>
            <td className="py-1 text-right tabular-nums">{zahl(hs?.t_occupied ?? null)}</td>
          </tr>
          <tr>
            <td className="py-1">Zimmer frei</td>
            <td className="py-1 text-right tabular-nums">{zahl(hs?.t_vacant ?? null)}</td>
          </tr>
          <tr>
            <td className="py-1">Nachtabsenkung</td>
            <td className="py-1 text-right tabular-nums">{zahl(hs?.t_night ?? null)}</td>
          </tr>
          <tr>
            <td className="py-1">Nachtfenster</td>
            <td className="py-1 text-right tabular-nums">
              {hs?.night_start !== null && hs?.night_start !== undefined
                ? `${hs.night_start.slice(0, 5)} – ${(hs.night_end ?? "").slice(0, 5)}`
                : "nicht festgelegt"}
            </td>
          </tr>
          <tr>
            <td className="py-1">Vorheizen vor Anreise</td>
            <td className="py-1 text-right tabular-nums">
              {hs?.preheat_minutes_before_checkin !== null &&
              hs?.preheat_minutes_before_checkin !== undefined
                ? `${hs.preheat_minutes_before_checkin} Min`
                : "nicht festgelegt"}
            </td>
          </tr>
        </tbody>
      </table>

      <h3 className="text-text-primary mb-2 text-sm font-medium">
        Raumtypen — was eingetragen ist und was wirkt
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-text-tertiary text-xs">
              <th scope="col" className="pb-1 text-left font-medium">Raumtyp</th>
              <th scope="col" className="pb-1 text-left font-medium">Feld</th>
              <th scope="col" className="pb-1 text-right font-medium">eingetragen</th>
              <th scope="col" className="pb-1 text-right font-medium">wirksam</th>
              <th scope="col" className="pb-1 pl-3 text-left font-medium">Quelle</th>
            </tr>
          </thead>
          <tbody className="divide-border divide-y">
            {typen.flatMap((typ) =>
              typ.felder
                // Bei einem Allgemeinbereich ist „Belegt" ungenutzt.
                .filter((f) => typ.is_bookable || f.feld !== "default_t_occupied")
                .map((f) => (
                  <tr key={`${typ.room_type_id}-${f.feld}`}>
                    <td className="py-1">{typ.name}</td>
                    <td className="py-1">{FELD_NAME[f.feld] ?? f.feld}</td>
                    <td className="py-1 text-right tabular-nums">{f.angezeigt.toFixed(1)} °C</td>
                    <td
                      className={`py-1 text-right tabular-nums ${
                        f.wirksam !== f.angezeigt ? "text-warning font-medium" : ""
                      }`}
                    >
                      {f.wirksam === null ? "—" : `${f.wirksam.toFixed(1)} °C`}
                    </td>
                    <td className="text-text-tertiary py-1 pl-3 text-xs">
                      {QUELLE_LABEL[f.quelle] ?? f.quelle}
                    </td>
                  </tr>
                )),
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
