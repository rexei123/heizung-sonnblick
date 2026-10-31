"use client";

/**
 * Zimmer-Verlauf (Sprint 21 A1).
 *
 * Je Heizzone eine Linie Ist-Temperatur und eine Stufenlinie Sollwert,
 * dahinter hinterlegt: Belegungen und die Nachtabsenkung. Umschalter
 * 24 Stunden / 7 Tage.
 *
 * **Eine dritte Linie je Zone, die meist nicht da ist** (31.10.2026):
 * „Gerät meldet", gepunktet, nur für Eimer, in denen der gemeldete Wert
 * vom Sollwert abweicht. Der Sollwert ist seither der der Engine — bis
 * dahin trug die Soll-Linie den **Geräte**-Wert und zeigte damit in
 * Zimmer 107 eine abgewiesene Drehung als Sollwert an. Begründung in
 * `services/room_history`.
 *
 * **Was diese Komponente nicht tut: rechnen.** Die Zusammenfassung in
 * Zehn-Minuten- bzw. Stunden-Eimer macht der Server, und die
 * Nacht-Bänder kommen als fertige UTC-Zeitspannen — die Umrechnung von
 * Ortszeit samt Sommerzeit liegt dort, wo auch die Engine sie macht
 * (§5.65). Hier würde sie ohne Testlauf stehen; das Frontend hat nur
 * Playwright, keinen Unit-Test-Rahmen.
 *
 * **Der Sollwert ist eine Stufenlinie** (`type="stepAfter"`), weil er
 * genau das ist: er gilt bis zur nächsten Änderung. Eine interpolierte
 * Linie würde eine Rampe zeigen, die es nie gab.
 *
 * **Jede Uhrzeit trägt die Zone des Hotels**, nicht die des Betrachters
 * (`HOTEL_TIMEZONE`, §5.79). Die Achsen-Teilung überlässt die Komponente
 * Recharts: eigene Ticks auf lokale Mitternacht zu legen hieße, die
 * Zeitzonen-Rechnung doch im Browser zu machen.
 */

import { useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceArea,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ChartContainer } from "@/components/patterns/chart-container";
import { Button } from "@/components/ui/button";
import { useOccupanciesFenster } from "@/lib/api/hooks-occupancies";
import { useRoomHistory } from "@/lib/api/hooks-rooms";
import type { Occupancy, RoomHistory, RoomHistoryRange } from "@/lib/api/types";
import { HOTEL_TIMEZONE } from "@/lib/format";

/**
 * Bis zu vier Zonen je Zimmer (Schlafzimmer, Bad, Wohnen, Flur). Die
 * Reihenfolge ist stabil, weil der Server die Zonen nach `id` sortiert —
 * sonst wechselten die Farben zwischen zwei Abrufen.
 */
const ZONEN_FARBEN = [
  "var(--color-primary)",
  "var(--color-info)",
  "var(--color-success)",
  "var(--color-warning)",
];

const ZEIT_KURZ = new Intl.DateTimeFormat("de-AT", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: HOTEL_TIMEZONE,
});

const TAG_UND_ZEIT = new Intl.DateTimeFormat("de-AT", {
  weekday: "short",
  hour: "2-digit",
  timeZone: HOTEL_TIMEZONE,
});

const VOLL_MIT_ZONE = new Intl.DateTimeFormat("de-AT", {
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: HOTEL_TIMEZONE,
  timeZoneName: "short",
});

interface Reihe {
  ms: number;
  [serie: string]: number | undefined;
}

export function RoomHistoryChart({ roomId }: { roomId: number }) {
  const [bereich, setBereich] = useState<RoomHistoryRange>("24h");
  const verlauf = useRoomHistory(roomId, bereich);
  const belegungen = useOccupanciesFenster(
    roomId,
    verlauf.data?.range_from ?? null,
    verlauf.data?.range_to ?? null,
  );

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-medium text-text-primary">Verlauf</h2>
          <p className="text-sm text-text-secondary mt-1">
            Ist-Temperatur und Sollwert je Heizzone.{" "}
            {verlauf.data ? <Zusammenfassung daten={verlauf.data} /> : null}
          </p>
        </div>
        <div className="flex items-center gap-2" role="group" aria-label="Zeitraum">
          {(["24h", "7d"] as const).map((b) => (
            <Button
              key={b}
              variant={bereich === b ? "primary" : "secondary"}
              onClick={() => setBereich(b)}
              aria-pressed={bereich === b}
            >
              {b === "24h" ? "24 Stunden" : "7 Tage"}
            </Button>
          ))}
        </div>
      </header>

      {verlauf.isLoading ? (
        <div className="h-72 rounded bg-surface-alt animate-pulse" aria-busy="true" />
      ) : verlauf.isError ? (
        <p role="alert" className="text-sm text-error">
          Verlauf konnte nicht geladen werden.
        </p>
      ) : verlauf.data ? (
        <Diagramm daten={verlauf.data} belegungen={belegungsSpannen(belegungen.data?.items)} />
      ) : null}
    </div>
  );
}

/** „Alle 10 Minuten · Absenkung 22:00–06:00 MESZ" — die Zusagen in Worten. */
function Zusammenfassung({ daten }: { daten: RoomHistory }) {
  const takt =
    daten.bucket_minutes >= 60
      ? `Alle ${daten.bucket_minutes / 60} Stunde${daten.bucket_minutes >= 120 ? "n" : ""}`
      : `Alle ${daten.bucket_minutes} Minuten`;
  const nacht = daten.night_window
    ? ` · Absenkung ${daten.night_window.start.slice(0, 5)}–${daten.night_window.end.slice(0, 5)} Ortszeit`
    : null;
  return (
    <span className="text-text-tertiary">
      {takt} zusammengefasst{nacht}
    </span>
  );
}

function Diagramm({
  daten,
  belegungen,
}: {
  daten: RoomHistory;
  belegungen: { start: number; end: number }[];
}) {
  const vonMs = Date.parse(daten.range_from);
  const bisMs = Date.parse(daten.range_to);

  const reihen = useMemo<Reihe[]>(() => {
    const nachZeit = new Map<number, Reihe>();
    for (const zone of daten.zones) {
      for (const punkt of zone.points) {
        const ms = Date.parse(punkt.t);
        const reihe = nachZeit.get(ms) ?? { ms };
        // `null` heisst "in diesem Eimer kein Wert" und darf nicht zu 0
        // werden — `undefined` laesst Recharts die Linie unterbrechen.
        if (punkt.temperature !== null) reihe[`temp_${zone.zone_id}`] = punkt.temperature;
        if (punkt.setpoint !== null) reihe[`soll_${zone.zone_id}`] = punkt.setpoint;
        // Der gemeldete Wert kommt nur, wo er abweicht — der Server
        // schickt sonst `null`. Die Reihe ist damit im Normalfall leer.
        if (punkt.geraet_setpoint !== null && punkt.geraet_setpoint !== undefined)
          reihe[`geraet_${zone.zone_id}`] = punkt.geraet_setpoint;
        nachZeit.set(ms, reihe);
      }
    }
    return [...nachZeit.values()].sort((a, b) => a.ms - b.ms);
  }, [daten.zones]);

  if (reihen.length === 0) {
    return (
      <div className="h-72 flex items-center justify-center text-sm text-text-tertiary">
        Für diesen Zeitraum liegen keine Messwerte vor.
      </div>
    );
  }

  const beschriftung = (ms: number) =>
    daten.range === "24h" ? ZEIT_KURZ.format(new Date(ms)) : TAG_UND_ZEIT.format(new Date(ms));

  /**
   * Sprint 24e (P7): die Zeitzone **steht** an der Achse.
   *
   * Die Achse rechnet in UTC-Millisekunden und beschriftet in Ortszeit —
   * das ist richtig und in der Umstellungsnacht nicht zu erkennen: Ende
   * Oktober trägt die Achse **zweimal** „02:00", und das sieht wie ein
   * Fehler aus. Die Linie ist dort lückenlos, weil zwei verschiedene
   * Augenblicke zwei verschiedene x-Werte haben; nur die Beschriftung
   * wiederholt sich.
   *
   * Eine Uhrzeit, die neben einer anderen steht, trägt ihre Zone (§5.79,
   * dritter Teil). Hier ist es der einzige Hinweis darauf, dass die
   * doppelte Stunde keine doppelten Daten sind.
   */
  // Die Zone kommt aus der **Antwort** (`daten.timezone`) und nicht aus
  // einer Konstante hier: der Server rechnet die Nacht-Bänder damit, und
  // zwei Quellen für dieselbe Zone wären zwei Wahrheiten (§5.53).
  const zonenKuerzel = new Intl.DateTimeFormat("de-AT", {
    timeZone: daten.timezone,
    timeZoneName: "short",
  })
    .formatToParts(new Date(bisMs))
    .find((t) => t.type === "timeZoneName")?.value;

  return (
    <div className="space-y-3">
      <ChartContainer testId="room-history-chart">
        <LineChart data={reihen} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          {/* Hinterlegte Bereiche zuerst: sie gehoeren hinter die Linien. */}
          {belegungen.map((b) => (
            <ReferenceArea
              key={`belegt-${b.start}`}
              x1={b.start}
              x2={b.end}
              fill="var(--color-info)"
              fillOpacity={0.1}
              ifOverflow="hidden"
            />
          ))}
          {daten.night_bands.map((b) => (
            <ReferenceArea
              key={`nacht-${b.start}`}
              x1={Date.parse(b.start)}
              x2={Date.parse(b.end)}
              fill="var(--color-text-primary)"
              fillOpacity={0.06}
              ifOverflow="hidden"
            />
          ))}

          <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" />
          <XAxis
            dataKey="ms"
            type="number"
            scale="time"
            domain={[vonMs, bisMs]}
            tickFormatter={beschriftung}
            tick={{ fontSize: 11, fill: "var(--color-text-secondary)" }}
            stroke="var(--color-border-strong)"
          />
          <YAxis
            unit=" °C"
            width={60}
            domain={["auto", "auto"]}
            tick={{ fontSize: 11, fill: "var(--color-text-secondary)" }}
            stroke="var(--color-border-strong)"
          />
          <Tooltip
            contentStyle={{
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: 6,
              fontSize: 12,
            }}
            labelStyle={{ color: "var(--color-text-primary)", fontWeight: 500 }}
            labelFormatter={(ms) => VOLL_MIT_ZONE.format(new Date(Number(ms)))}
            formatter={(wert) => `${Number(wert).toFixed(1)} °C`}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: "var(--color-text-secondary)" }} />

          {/* `flatMap`: Recharts prueft seine Kinder der Reihe nach, und
              verschachtelte Arrays sind dabei eine Quelle stiller
              Ausfaelle — die Linien je Zone kommen deshalb flach. */}
          {daten.zones.flatMap((zone, i) => {
            const farbe = ZONEN_FARBEN[i % ZONEN_FARBEN.length];
            // Weicht diese Zone im Fenster irgendwo ab? Entscheidet, ob es
            // die dritte Linie ueberhaupt gibt — Begruendung an ihr.
            const weichtAb = zone.points.some((p) => p.geraet_setpoint !== null);
            const linien = [
              <Line
                key={`temp-${zone.zone_id}`}
                type="monotone"
                dataKey={`temp_${zone.zone_id}`}
                name={zone.name}
                stroke={farbe}
                strokeWidth={2}
                dot={false}
                connectNulls={false}
              />,
              <Line
                key={`soll-${zone.zone_id}`}
                // Der Sollwert gilt bis zur naechsten Aenderung — also
                // Stufe, nicht Rampe.
                type="stepAfter"
                dataKey={`soll_${zone.zone_id}`}
                name={`${zone.name} (Soll)`}
                stroke={farbe}
                strokeWidth={1.5}
                strokeDasharray="4 4"
                dot={false}
                connectNulls
              />,
            ];
            /**
             * Die dritte Linie: **was das Gerät meldet, wenn es
             * abweicht** (31.10.2026).
             *
             * Sie ist meist nicht da. Der Server schickt den Wert nur
             * für Eimer, in denen Gerät und Sollwert auseinanderliegen
             * — im Normalfall sieht das Diagramm deshalb aus wie
             * vorher, zwei Linien je Zone.
             *
             * Erscheint sie, ist das der Befund: in Zimmer 107 lagen
             * zwei Stunden zwischen „Soll 23" und „Gerät meldet 25",
             * und bis dahin stand die 25 **als** Sollwert da.
             *
             * `connectNulls={false}` ist hier das Gegenteil der
             * Soll-Linie, und zwar absichtlich: eine Lücke heißt „hier
             * stimmte es", und die darf nicht überbrückt werden.
             * Durchverbunden wäre aus der Abweichung eine Dauerlinie
             * geworden, die nichts mehr unterscheidet.
             *
             * Gepunktet statt gestrichelt, damit die drei Linien einer
             * Zone in derselben Farbe auseinanderzuhalten sind.
             *
             * **Die Linie wird gar nicht angelegt, wenn die Zone im
             * Fenster nirgends abweicht.** Recharts setzt fuer jedes
             * `<Line>` einen Legenden-Eintrag, auch fuer eines ohne
             * einen einzigen Punkt — ohne diese Bedingung stuende
             * „(Gerät meldet)" dauerhaft in der Legende und
             * versprach eine Linie, die es nicht gibt. Aufgefallen
             * ist das in der e2e-Pruefung, die genau das
             * ausschliesst.
             */
            if (weichtAb) {
              linien.push(
                <Line
                  key={`geraet-${zone.zone_id}`}
                  type="stepAfter"
                  dataKey={`geraet_${zone.zone_id}`}
                  name={`${zone.name} (Gerät meldet)`}
                  stroke={farbe}
                  strokeWidth={1.5}
                  strokeDasharray="1 3"
                  dot={false}
                  connectNulls={false}
                />,
              );
            }
            return linien;
          })}
        </LineChart>
      </ChartContainer>

      {/* Die hinterlegten Flaechen brauchen eine sichtbare Beschriftung.
          Ein Tooltip allein waere die Falle aus §5.57: Semantik, die nur
          beim Darueberfahren existiert. */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-text-secondary">
        {/* Sprint 24e (P7): die Zeitzone gehoert zur Achse.
            In der Umstellungsnacht Ende Oktober steht dort zweimal
            „02:00" — die Linie ist lueckenlos, nur die Beschriftung
            wiederholt sich. Ohne diesen Hinweis sieht das wie ein Fehler
            aus (§5.79, dritter Teil: eine Uhrzeit neben einer anderen
            traegt ihre Zone). */}
        {zonenKuerzel !== undefined ? (
          <span data-testid="verlauf-zeitzone">Zeiten in {zonenKuerzel}</span>
        ) : null}
        <span className="flex items-center gap-2">
          <span
            className="inline-block h-3 w-5 rounded-sm"
            style={{ background: "var(--color-info)", opacity: 0.25 }}
            aria-hidden
          />
          Belegt
        </span>
        <span className="flex items-center gap-2">
          <span
            className="inline-block h-3 w-5 rounded-sm"
            style={{ background: "var(--color-text-primary)", opacity: 0.12 }}
            aria-hidden
          />
          Nachtabsenkung
        </span>
        <span className="text-text-tertiary">
          Gestrichelt: Sollwert · gepunktet: gemeldeter Gerätewert, wo er dem Soll
          nicht entspricht · Zeiten in Ortszeit des Hotels
        </span>
      </div>
    </div>
  );
}

/**
 * Belegungen zu Zeitspannen in Millisekunden.
 *
 * Stornierte Belegungen (`cancelled_at`) werden **nicht** hinterlegt: das
 * Zimmer war dann nicht belegt, und eine Flaeche dafuer wuerde den
 * Temperaturverlauf falsch erklaeren.
 */
function belegungsSpannen(
  items: Occupancy[] | undefined,
): { start: number; end: number }[] {
  if (!items) return [];
  return items
    .filter((o) => o.cancelled_at === null)
    .map((o) => ({ start: Date.parse(o.check_in), end: Date.parse(o.check_out) }));
}
