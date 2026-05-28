"use client";

/**
 * Startseite / Dashboard (Sprint 14c).
 *
 * Begruessung (tageszeit-aware, Browser-Lokalzeit — R3: KEIN SSR-Zeitwert)
 * + 6 KPI-Kacheln aus ``GET /api/v1/dashboard/kpi`` (60-s-Refresh via
 * ``useDashboardKpi``). Ersetzt den frueheren ``redirect("/devices")``.
 *
 * Wording: „Thermostat"/„Geraete" generisch, nicht „Vicki" (§5.20);
 * „Algorithmen-Lauf" konsistent zum Sidebar-Eintrag „Algorithmenverlauf".
 * Zeit-Anzeige lokalisiert (de-AT), Backend liefert UTC (§5.65).
 */

import { KpiCard, type KpiTone } from "@/components/patterns/kpi-card";
import { useAuth } from "@/contexts/auth-context";
import { useDashboardKpi } from "@/lib/api/hooks-dashboard";
import type { DashboardKpi } from "@/lib/api/types";
import { formatDateTime, formatRelative, formatTemperature } from "@/lib/format";

/** Engine-Tick gilt als „alt", wenn aelter als 10 Minuten (T0-Erwartung < 10 min). */
const TICK_STALE_MS = 10 * 60 * 1000;

const CARD_META: { label: string; icon: string }[] = [
  { label: "Belegte Zimmer", icon: "bed" },
  { label: "Ø Raumtemperatur", icon: "thermostat" },
  { label: "Geräte online", icon: "device_thermostat" },
  { label: "Aktive Übersteuerungen", icon: "tune" },
  { label: "Fenster offen", icon: "sensor_window" },
  { label: "Letzter Algorithmen-Lauf", icon: "history" },
];

function greetingPrefix(now: Date): string {
  const h = now.getHours();
  if (h >= 5 && h <= 11) return "Guten Morgen";
  if (h >= 12 && h <= 17) return "Guten Tag";
  return "Guten Abend";
}

interface CardConfig {
  label: string;
  value: string | number;
  subValue?: string;
  icon: string;
  tone: KpiTone;
}

function buildCards(data: DashboardKpi): CardConfig[] {
  const tick = data.last_engine_tick;
  const tickStale = tick === null || Date.now() - new Date(tick).getTime() > TICK_STALE_MS;
  return [
    {
      label: "Belegte Zimmer",
      value: data.rooms_occupied,
      subValue: `von ${data.rooms_total}`,
      icon: "bed",
      tone: "neutral",
    },
    {
      label: "Ø Raumtemperatur",
      value: formatTemperature(data.avg_temperature_celsius),
      icon: "thermostat",
      tone: "neutral",
    },
    {
      label: "Geräte online",
      value: data.devices_online,
      subValue: `von ${data.devices_total}`,
      icon: "device_thermostat",
      tone: data.devices_online < data.devices_total ? "warning-soft" : "neutral",
    },
    {
      label: "Aktive Übersteuerungen",
      value: data.active_overrides,
      icon: "tune",
      tone: "neutral",
    },
    {
      label: "Fenster offen",
      value: data.zones_window_open,
      icon: "sensor_window",
      tone: data.zones_window_open > 0 ? "warning-soft" : "neutral",
    },
    {
      label: "Letzter Algorithmen-Lauf",
      value: tick ? formatRelative(tick) : "—",
      subValue: tick ? formatDateTime(tick) : undefined,
      icon: "history",
      tone: tickStale ? "warning-soft" : "neutral",
    },
  ];
}

export default function Home() {
  const { user } = useAuth();
  const kpiQ = useDashboardKpi();

  const name = user?.email ?? null;
  const heading = name ? `${greetingPrefix(new Date())}, ${name}!` : "Hallo!";

  return (
    <div className="p-6 max-w-content mx-auto">
      <header className="mb-6">
        <h1 className="text-2xl font-medium text-text-primary">{heading}</h1>
        <p className="text-sm text-text-secondary mt-1">
          Hier ist die Übersicht für Ihre Heizung.
        </p>
      </header>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {kpiQ.isLoading
          ? CARD_META.map((m) => (
              <KpiCard key={m.label} loading label={m.label} value="" icon={m.icon} />
            ))
          : kpiQ.isError || !kpiQ.data
            ? CARD_META.map((m) => (
                <KpiCard key={m.label} error label={m.label} value="" icon={m.icon} />
              ))
            : buildCards(kpiQ.data).map((c) => (
                <KpiCard
                  key={c.label}
                  label={c.label}
                  value={c.value}
                  subValue={c.subValue}
                  icon={c.icon}
                  tone={c.tone}
                />
              ))}
      </div>
    </div>
  );
}
