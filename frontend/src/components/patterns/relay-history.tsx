"use client";

/**
 * Relais-Verlauf (17.11.2026): wie lange lief das Panel, und wurde es warm?
 *
 * **Die Frage, für die es diese Ansicht gibt.** Bis heute war der
 * Einschaltanteil nur über ein Werkzeug im Container zu bekommen
 * (`scripts/relais_auswertung`), und das beantwortet „reicht das Gerät"
 * einmal. Diese Seite beantwortet „wie lief es gestern" — jeden Tag, ohne
 * SSH.
 *
 * **Balken und Linien, nicht zwei Diagramme.** Der Einschaltanteil ist
 * eine Dauer (Balken, linke Achse in Prozent), Ist und Soll sind
 * Temperaturen (Linien, rechte Achse in °C). Nebeneinander in einem Bild,
 * weil genau der Zusammenhang die Aussage ist: ein Panel, das nahe 100
 * Prozent läuft und das Soll trotzdem nicht hält, ist zu schwach — eines
 * mit niedrigem Anteil sagt nichts über seine Leistung, sondern über die
 * Steuerung.
 *
 * **Der Sollwert ist eine Stufenlinie** (`stepAfter`), wie im
 * Zimmer-Verlauf: er gilt bis zur nächsten Änderung, eine interpolierte
 * Linie zeigte eine Rampe, die es nie gab.
 *
 * **Was diese Komponente nicht tut: rechnen.** Eimer, Tageszeilen,
 * Gewichtung und Energie kommen fertig vom Server
 * (`services/relais_verlauf`) — dieselbe Rechnung, die auch das Werkzeug
 * benutzt (§5.53). Hier wird formatiert und gezeichnet.
 *
 * **Die x-Achse ist eine Kategorie-Achse und trägt fertige Beschriftungen.**
 * Der Kalendertag einer Tageszeile ist ein String (`2026-11-17`) und darf
 * nicht durch `new Date(...)` laufen: das wäre UTC-Mitternacht und in
 * westlichen Zonen der Vortag (§5.65). Die Stunden-Beschriftung formatiert
 * `Intl` mit der Zone **aus der Antwort**, nicht mit einer Konstante hier —
 * der Server rechnet die Tageszeilen mit derselben Zone, und zwei Quellen
 * dafür wären zwei Wahrheiten.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChartContainer } from "@/components/patterns/chart-container";
import { Button } from "@/components/ui/button";
import {
  BEREICH_TEXT,
  RELAIS_BEREICHE,
  fetchRelaisVerlauf,
  relaisVerlaufCsvPfad,
  type RelaisBereich,
  type RelaisVerlauf,
} from "@/lib/api/relais-verlauf";
import { formatCalendarDate } from "@/lib/format";

interface Punkt {
  label: string;
  ein: number | null;
  ist: number | null;
  soll: number | null;
}

/** „2 h 35 min" — die Form, in der ein Mensch eine Heizdauer liest. */
export function formatDauer(minuten: number): string {
  if (minuten <= 0) return "0 min";
  const h = Math.floor(minuten / 60);
  const m = minuten % 60;
  if (h === 0) return `${m} min`;
  if (m === 0) return `${h} h`;
  return `${h} h ${m} min`;
}

/**
 * Wh in kWh mit einer Stelle. `null` bleibt ein Strich.
 *
 * Eine 0 wäre hier eine Aussage („es lief und hat nichts verbraucht"),
 * und die ist bei einem Zähler, der nichts gemeldet hat, nicht gedeckt.
 */
export function formatEnergie(wh: number | null): string {
  if (wh === null) return "–";
  return `${(wh / 1000).toFixed(1)} kWh`;
}

function formatAnteil(prozent: number | null): string {
  return prozent === null ? "–" : `${prozent} %`;
}

function formatGrad(wert: number | null): string {
  return wert === null ? "–" : `${wert.toFixed(1)} °C`;
}

/**
 * Gehäusetemperatur: Mittel und in Klammern der größte Wert.
 *
 * **Ohne Einheit.** Der Wert ist ein Rohwert; der Hersteller-Dekoder
 * liest ein Byte und nennt keine Einheit (AE-78). Ein „°C" dahinter wäre
 * eine Behauptung, die niemand geprüft hat — und die Zahl wird für die
 * Frage „steigt sie über die Tage" auch ohne Einheit gelesen.
 */
function formatGehaeuse(mittel: number | null, max: number | null): string {
  if (mittel === null && max === null) return "–";
  const m = mittel === null ? "–" : mittel.toFixed(1);
  return max === null ? m : `${m} (${max})`;
}

export function RelayHistory({ deviceId }: { deviceId: number }) {
  const [bereich, setBereich] = useState<RelaisBereich>("24h");
  const { data, isLoading, isError } = useQuery({
    queryKey: ["relay", deviceId, "history", bereich],
    queryFn: () => fetchRelaisVerlauf(deviceId, bereich),
    refetchOnWindowFocus: true,
  });

  return (
    <section
      className="bg-surface rounded-lg border border-border p-4 sm:p-6"
      data-testid="relay-history"
    >
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-text-primary text-lg font-medium">
            Verlauf der Heizzone
          </h2>
          <p className="text-text-secondary mt-1 text-sm">
            Einschaltdauer, Ist und Soll — Stunde für Stunde.{" "}
            {data ? <Herkunft daten={data} /> : null}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div
            className="flex items-center gap-2"
            role="group"
            aria-label="Zeitraum"
          >
            {RELAIS_BEREICHE.map((b) => (
              <Button
                key={b}
                size="sm"
                variant={bereich === b ? "primary" : "secondary"}
                onClick={() => setBereich(b)}
                aria-pressed={bereich === b}
                data-testid={`relay-history-bereich-${b}`}
              >
                {BEREICH_TEXT[b]}
              </Button>
            ))}
          </div>
          {/* Ein Link und kein Knopf: der Browser lädt die Datei selbst,
              mit dem Namen aus `Content-Disposition`. */}
          <Button size="sm" variant="secondary" icon="download" asChild>
            <a
              href={relaisVerlaufCsvPfad(deviceId, bereich)}
              data-testid="relay-history-csv"
            >
              CSV (Stundenzeilen)
            </a>
          </Button>
        </div>
      </header>

      {isLoading ? (
        <div
          className="bg-surface-alt mt-4 h-72 animate-pulse rounded"
          aria-busy="true"
        />
      ) : isError || data === undefined ? (
        <p role="alert" className="text-error mt-4 text-sm">
          Der Verlauf ist nicht abrufbar.
        </p>
      ) : (
        <>
          <Kennzahlen daten={data} />
          <Diagramm daten={data} />
          <Tagestabelle daten={data} />
        </>
      )}
    </section>
  );
}

/**
 * „Eingang · Relais 108" — wofür die Zahlen gelten.
 *
 * **Die Zone und nicht das Gerät**, und das ist keine Feinheit: zwei
 * Panels in einem Raum heizen gemeinsam, ein Einschaltanteil je Gerät
 * würde zu einer Summe verleiten, die 200 Prozent ergibt.
 */
function Herkunft({ daten }: { daten: RelaisVerlauf }) {
  const geraete =
    daten.relais.length === 1
      ? `Relais ${daten.relais[0]}`
      : `Relais ${daten.relais.join(", ")}`;
  return (
    <span className="text-text-tertiary">
      Zone „{daten.zone_name}" · {geraete} · Ortszeit {daten.timezone}
    </span>
  );
}

function Kennzahlen({ daten }: { daten: RelaisVerlauf }) {
  return (
    <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Kennzahl
        bezeichnung="Heizdauer"
        wert={formatDauer(daten.ein_minuten_gesamt)}
        testId="relay-history-heizdauer"
      />
      <Kennzahl
        bezeichnung="Einschaltanteil"
        wert={formatAnteil(daten.anteil_gesamt)}
        hinweis="zeitgewichtet"
      />
      <Kennzahl
        bezeichnung="Einschaltungen"
        wert={String(daten.einschaltungen_gesamt)}
        hinweis="gemeldet"
      />
      <Kennzahl
        bezeichnung="Energie"
        wert={formatEnergie(daten.energie_wh_gesamt)}
        testId="relay-history-energie"
        // **Der Rücksprung steht neben der Zahl, nicht darin.** Der
        // Zähler im Gerät läuft bei 0xFFFFFFFF über, ein `0x26` setzt
        // ihn auf 0, ein Gerätetausch beginnt bei 0 — in diesem Haus
        // bisher nie vorgekommen (gemessen 17.11.2026). Träte es ein,
        // wäre die kWh-Zahl zu klein, und ohne diesen Hinweis wüsste
        // niemand, warum.
        hinweis={
          daten.ruecksprunge > 0
            ? `${daten.ruecksprunge} Zählerrücksprung${daten.ruecksprunge === 1 ? "" : "e"} — Verbrauch davor fehlt`
            : "aus dem Gerätezähler"
        }
      />
    </div>
  );
}

function Kennzahl({
  bezeichnung,
  wert,
  hinweis,
  testId,
}: {
  bezeichnung: string;
  wert: string;
  hinweis?: string;
  testId?: string;
}) {
  return (
    <div
      className="border-border bg-surface-alt rounded-md border p-3"
      data-testid={testId}
    >
      <div className="text-text-tertiary text-xs">{bezeichnung}</div>
      <div className="text-text-primary mt-1 text-lg font-medium">{wert}</div>
      {hinweis ? (
        <div className="text-text-tertiary mt-0.5 text-xs">{hinweis}</div>
      ) : null}
    </div>
  );
}

/**
 * Die Punkte des Diagramms.
 *
 * **24 Stunden und 7 Tage zeichnen Stunden, 30 Tage zeichnet Tage.** 720
 * Balken auf 600 Pixeln sind kein Bild mehr; die Stundenzeilen bleiben in
 * der CSV erhalten, wer sie braucht.
 */
function punkte(daten: RelaisVerlauf): Punkt[] {
  if (daten.range === "30d") {
    return daten.tage.map((t) => ({
      label: formatCalendarDate(t.tag).slice(0, 6),
      ein: t.ein_prozent,
      ist: t.ist_mittel,
      soll: t.soll_mittel,
    }));
  }
  const uhr = new Intl.DateTimeFormat("de-AT", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: daten.timezone,
  });
  const tagUndStunde = new Intl.DateTimeFormat("de-AT", {
    weekday: "short",
    hour: "2-digit",
    timeZone: daten.timezone,
  });
  const form = daten.range === "24h" ? uhr : tagUndStunde;
  return daten.stunden.map((s) => ({
    label: form.format(new Date(s.t)),
    ein: s.ein_prozent,
    ist: s.ist_mittel,
    soll: s.soll,
  }));
}

function Diagramm({ daten }: { daten: RelaisVerlauf }) {
  const reihen = useMemo(() => punkte(daten), [daten]);

  if (reihen.length === 0) {
    return (
      <div className="text-text-tertiary mt-4 flex h-72 items-center justify-center text-sm">
        Für diesen Zeitraum liegen keine Meldungen vor.
      </div>
    );
  }

  // Rund ein Dutzend Beschriftungen, egal wie viele Punkte. `interval`
  // zählt die Punkte, die recharts zwischen zwei Ticks überspringt.
  const abstand = Math.max(0, Math.ceil(reihen.length / 12) - 1);

  return (
    <div className="mt-4">
      <ChartContainer testId="relay-history-chart">
        <ComposedChart
          data={reihen}
          margin={{ top: 8, right: 8, bottom: 8, left: 0 }}
        >
          <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" />
          <XAxis
            dataKey="label"
            interval={abstand}
            tick={{ fill: "var(--color-text-tertiary)", fontSize: 12 }}
            stroke="var(--color-border)"
          />
          <YAxis
            yAxisId="anteil"
            domain={[0, 100]}
            unit=" %"
            width={52}
            tick={{ fill: "var(--color-text-tertiary)", fontSize: 12 }}
            stroke="var(--color-border)"
          />
          <YAxis
            yAxisId="grad"
            orientation="right"
            unit=" °C"
            width={60}
            tick={{ fill: "var(--color-text-tertiary)", fontSize: 12 }}
            stroke="var(--color-border)"
          />
          <Tooltip
            contentStyle={{
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: 6,
              fontSize: 12,
            }}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar
            yAxisId="anteil"
            dataKey="ein"
            name="ein %"
            fill="var(--color-primary)"
            fillOpacity={0.55}
          />
          <Line
            yAxisId="grad"
            type="monotone"
            dataKey="ist"
            name="Ist"
            stroke="var(--color-info)"
            dot={false}
            strokeWidth={2}
            connectNulls={false}
          />
          {/* Stufenlinie: der Sollwert gilt bis zur nächsten Änderung. */}
          <Line
            yAxisId="grad"
            type="stepAfter"
            dataKey="soll"
            name="Soll"
            stroke="var(--color-success)"
            dot={false}
            strokeWidth={2}
            strokeDasharray="5 3"
            connectNulls={false}
          />
        </ComposedChart>
      </ChartContainer>
    </div>
  );
}

/**
 * Eine Zeile je **Ortszeit**-Kalendertag.
 *
 * Die Tabelle ist der Teil, den der Betreiber weitergibt: „am 16. lief es
 * vier Stunden und wurde 21,4 statt 23 Grad warm" ist ein Satz, ein
 * Diagramm nicht.
 */
function Tagestabelle({ daten }: { daten: RelaisVerlauf }) {
  if (daten.tage.length === 0) return null;
  return (
    <div className="mt-6 overflow-x-auto">
      <table className="w-full text-sm" data-testid="relay-history-tabelle">
        <thead>
          <tr className="text-text-tertiary border-border border-b text-left text-xs">
            <th className="py-2 pr-3 font-medium">Tag</th>
            <th className="py-2 pr-3 font-medium">Heizdauer</th>
            <th className="py-2 pr-3 font-medium">ein %</th>
            <th className="py-2 pr-3 font-medium">Einsch.</th>
            <th className="py-2 pr-3 font-medium">Energie</th>
            <th className="py-2 pr-3 font-medium">Ist Ø (min–max)</th>
            <th className="py-2 pr-3 font-medium">Soll Ø</th>
            <th className="py-2 pr-3 font-medium">Gehäuse Ø (max)</th>
            <th className="py-2 font-medium">Gehäuse ein Ø (max)</th>
          </tr>
        </thead>
        <tbody>
          {daten.tage.map((t) => (
            <tr key={t.tag} className="border-border/60 border-b last:border-0">
              <td className="text-text-primary py-2 pr-3 font-medium">
                {formatCalendarDate(t.tag)}
              </td>
              <td className="text-text-secondary py-2 pr-3">
                {formatDauer(t.ein_minuten)}
              </td>
              <td className="text-text-secondary py-2 pr-3">
                {formatAnteil(t.ein_prozent)}
              </td>
              <td className="text-text-secondary py-2 pr-3">
                {t.einschaltungen}
              </td>
              <td className="text-text-secondary py-2 pr-3">
                {formatEnergie(t.energie_wh)}
              </td>
              <td className="text-text-secondary py-2 pr-3">
                {formatGrad(t.ist_mittel)}
                {t.ist_min !== null && t.ist_max !== null ? (
                  <span className="text-text-tertiary">
                    {" "}
                    ({t.ist_min.toFixed(1)}–{t.ist_max.toFixed(1)})
                  </span>
                ) : null}
              </td>
              <td className="text-text-secondary py-2 pr-3">
                {formatGrad(t.soll_mittel)}
              </td>
              <td
                className="text-text-secondary py-2 pr-3"
                data-testid={`relay-history-gehaeuse-${t.tag}`}
              >
                {formatGehaeuse(t.gehaeuse_mittel, t.gehaeuse_max)}
              </td>
              <td
                className="text-text-secondary py-2"
                data-testid={`relay-history-gehaeuse-ein-${t.tag}`}
              >
                {formatGehaeuse(t.gehaeuse_mittel_ein, t.gehaeuse_max_ein)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {/* **Die erfassten Minuten gehören zur Zahl.** Ein Tag, von dem nur
          zwei Stunden Meldungen vorliegen, hat eine Heizdauer, die nach
          wenig aussieht und keine ist. Steht hier und nicht in jeder
          Zeile, weil es im Normalfall 1440 ist. */}
      <p className="text-text-tertiary mt-2 text-xs">
        „ein %" ist zeitgewichtet über die erfassten Minuten. Das Relais meldet
        alle zehn Minuten; Stunden ohne Meldung erscheinen als Lücke und nicht
        als 0 Prozent.
      </p>
      {/* **Die Einheit ist nicht belegt** (AE-78), und dieser Satz ist der
          Grund, warum in der Spalte keine steht. „ein" meint: nur aus
          Meldungen, in denen das Relais geschaltet war. */}
      <p className="text-text-tertiary mt-1 text-xs">
        Die Gehäusetemperatur ist ein{" "}
        <strong>Rohwert ohne belegte Einheit</strong> — der Hersteller-Dekoder
        liest ein Byte und nennt keine. „ein" sind nur die Meldungen mit
        eingeschaltetem Relais; steht dort deutlich mehr als in der Spalte
        daneben, kommt die Wärme vom Schalten.
      </p>
    </div>
  );
}
