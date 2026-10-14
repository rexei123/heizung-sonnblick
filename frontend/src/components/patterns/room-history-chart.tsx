"use client";

/**
 * Zimmer-Verlauf (Sprint 21 A1).
 *
 * Je Heizzone eine Linie Ist-Temperatur und eine Stufenlinie Sollwert,
 * dahinter hinterlegt: Belegungen und die Nachtabsenkung. Umschalter
 * 24 Stunden / 7 Tage.
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
              Ausfaelle — zwei Linien je Zone kommen deshalb flach. */}
          {daten.zones.flatMap((zone, i) => {
            const farbe = ZONEN_FARBEN[i % ZONEN_FARBEN.length];
            return [
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
          })}
        </LineChart>
      </ChartContainer>

      {/* Die hinterlegten Flaechen brauchen eine sichtbare Beschriftung.
          Ein Tooltip allein waere die Falle aus §5.57: Semantik, die nur
          beim Darueberfahren existiert. */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-text-secondary">
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
          Gestrichelt: Sollwert · Zeiten in Ortszeit des Hotels
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
