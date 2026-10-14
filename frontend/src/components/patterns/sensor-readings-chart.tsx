"use client";

import { useMemo } from "react";
import { CartesianGrid, Legend, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";

import { ChartContainer } from "@/components/patterns/chart-container";
import type { SensorReading } from "@/lib/api/types";

interface Props {
  readings: SensorReading[];
}

interface ChartPoint {
  ts: number;
  label: string;
  temperature: number | null;
  setpoint: number | null;
}

export function SensorReadingsChart({ readings }: Props) {
  const data: ChartPoint[] = useMemo(() => {
    // Recharts will Daten in chronologischer Reihenfolge (alt → neu).
    // API liefert DESC, wir reverse.
    return [...readings]
      .reverse()
      .map((r) => {
        const ts = new Date(r.time).getTime();
        return {
          ts,
          label: new Intl.DateTimeFormat("de-AT", {
            hour: "2-digit",
            minute: "2-digit",
            day: "2-digit",
            month: "2-digit",
          }).format(ts),
          temperature: r.temperature,
          setpoint: r.setpoint,
        };
      });
  }, [readings]);

  if (data.length === 0) {
    return (
      <div className="h-64 flex items-center justify-center text-sm text-text-tertiary">
        Noch keine Reading-Daten vorhanden.
      </div>
    );
  }

  return (
    // Sprint 21 A1: gemeinsame Huelle. Die Hoehe ist dieselbe wie vorher
    // (h-72 = 288 px); neu sind minWidth/minHeight am ResponsiveContainer,
    // die die width(-1)-Warnung verursacht haben.
    <ChartContainer testId="sensor-readings-chart">
      <LineChart
          data={data}
          margin={{ top: 16, right: 24, bottom: 8, left: 0 }}
        >
          <CartesianGrid stroke="var(--color-border)" strokeDasharray="3 3" />
          <XAxis
            dataKey="label"
            tick={{ fontSize: 11, fill: "var(--color-text-secondary)" }}
            stroke="var(--color-border-strong)"
          />
          <YAxis
            tick={{ fontSize: 11, fill: "var(--color-text-secondary)" }}
            stroke="var(--color-border-strong)"
            unit=" °C"
            domain={["dataMin - 1", "dataMax + 1"]}
          />
          <Tooltip
            contentStyle={{
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-md)",
              fontSize: 12,
            }}
            labelStyle={{ color: "var(--color-text-primary)", fontWeight: 500 }}
            formatter={(value, name) => {
              const num = typeof value === "number" ? value : Number(value);
              const formatted = Number.isFinite(num) ? `${num.toFixed(1)} °C` : "–";
              const label = name === "temperature" ? "Temperatur" : "Sollwert";
              return [formatted, label];
            }}
          />
          <Legend
            verticalAlign="top"
            height={28}
            wrapperStyle={{ fontSize: 12, color: "var(--color-text-secondary)" }}
            formatter={(v) => (v === "temperature" ? "Temperatur" : "Sollwert")}
          />
          <Line
            type="monotone"
            dataKey="temperature"
            stroke="var(--color-primary)"
            strokeWidth={2}
            dot={false}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="setpoint"
            stroke="var(--color-info)"
            strokeWidth={2}
            strokeDasharray="4 4"
            dot={false}
            connectNulls
          />
      </LineChart>
    </ChartContainer>
  );
}
