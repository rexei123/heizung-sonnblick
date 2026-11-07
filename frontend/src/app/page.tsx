"use client";

/**
 * Startseite / Dashboard (Sprint 14c).
 *
 * Begruessung (tageszeit-aware, Browser-Lokalzeit — R3: KEIN SSR-Zeitwert)
 * + 7 KPI-Kacheln aus ``GET /api/v1/dashboard/kpi`` (60-s-Refresh via
 * ``useDashboardKpi``; Sprint 15d ergänzt „Schwache Batterie"). Ersetzt den
 * frueheren ``redirect("/devices")``.
 *
 * Wording: „Thermostat"/„Geraete" generisch, nicht „Vicki" (§5.20);
 * „Algorithmen-Lauf" konsistent zum Sidebar-Eintrag „Algorithmenverlauf".
 * Zeit-Anzeige lokalisiert (de-AT), Backend liefert UTC (§5.65).
 */

import type { Route } from "next";
import Link from "next/link";

import { KpiCard, type KpiTone } from "@/components/patterns/kpi-card";
import { useAuth } from "@/contexts/auth-context";
import { useDashboardKpi } from "@/lib/api/hooks-dashboard";
import { useOccupancyImportLog } from "@/lib/api/hooks-occupancy-import";
import type { DashboardKpi, OccupancyImportStatus } from "@/lib/api/types";
import { formatDateTime, formatRelative, formatTemperature } from "@/lib/format";

/** Engine-Tick gilt als „alt", wenn aelter als 10 Minuten (T0-Erwartung < 10 min). */
const TICK_STALE_MS = 10 * 60 * 1000;

/**
 * Das Lade-Skelett. **Die Reihenfolge und die Zahl muessen zu
 * ``buildCards`` passen**, sonst springt die Seite in dem Moment, in dem
 * die Daten eintreffen.
 *
 * Diese Liste stand bis zum 07.11.2026 auf **acht** Eintraegen, waehrend
 * ``buildCards`` **zehn** Karten baute: „Ventil pruefen" und „Zimmer zu
 * warm" sind mit Sprint 20e dazugekommen und hier nie eingetragen
 * worden. Der Kommentar daneben behauptete dabei ausdruecklich, beide
 * Listen seien synchron (CLAUDE.md Paragraph 5.77 — ein Vermerk, der
 * das Gegenteil des Codes sagt).
 *
 * **Eine Ausnahme bleibt, und sie ist beabsichtigt:** die Kachel
 * „Belegungsliste" entsteht nur, wenn der Import eingerichtet ist. Sie
 * gehoert nicht hierher — ein Skelett fuer eine Karte, die es in diesem
 * Haus nie geben wird, waere ein Platzhalter fuer nichts.
 *
 * Wer eine Karte in ``buildCards`` ergaenzt, ergaenzt sie hier an
 * derselben Stelle.
 */
const CARD_META: { label: string; icon: string }[] = [
  { label: "Belegte Zimmer", icon: "bed" },
  { label: "Ø Raumtemperatur", icon: "thermostat" },
  { label: "Geräte online", icon: "device_thermostat" },
  { label: "Aktive Übersteuerungen", icon: "tune" },
  { label: "Fenster offen", icon: "sensor_window" },
  // Sprint 25 T8
  { label: "Funk-Empfang", icon: "settings_input_antenna" },
  { label: "Letzter Algorithmen-Lauf", icon: "history" },
  // Sprint 15d (AE-65)
  { label: "Schwache Batterie", icon: "battery_alert" },
  // Sprint 20e (T7/T10) — nachgetragen am 07.11.2026, siehe oben.
  { label: "Ventil prüfen", icon: "build" },
  { label: "Zimmer zu warm", icon: "local_fire_department" },
];

// Sprint 15f (AE-66): Ampel-Status -> KpiCard-Tone. tone kommt AUSSCHLIESSLICH
// aus dem backend-berechneten ``status`` — keine Schwellen im Frontend.
const IMPORT_STATUS_TONE: Record<OccupancyImportStatus, KpiTone> = {
  green: "success-soft",
  yellow: "warning-soft",
  red: "danger-soft",
};

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
  /**
   * Zweite, kleinere Zeile (Sprint 21, B-21-2) — heute „N im Lager".
   *
   * Muss unten an `KpiCard` weitergereicht werden. Ein deklariertes Feld,
   * das niemand übergibt, ist genau B-18-3: typseitig erlaubt, wortlos
   * verworfen, und der Compiler kann es nicht melden.
   */
  note?: string;
  icon: string;
  tone: KpiTone;
  /**
   * Ziel, wenn die Kachel anklickbar sein soll (Sprint 21 A3).
   *
   * Gerendert wird das wie bei der Belegungsliste-Kachel weiter unten: ein
   * `Link` **um** die Karte. Mein Brief (§4.3) hatte dafuer eine neue
   * `href`-Eigenschaft an `KpiCard` vorgesehen — das waere ein zweiter
   * Mechanismus fuer etwas, das das Repo seit Sprint 15f schon kann.
   *
   * Nicht jede Kachel bekommt ein Ziel: „Belegte Zimmer", „Ø
   * Raumtemperatur", „Aktive Übersteuerungen", „Fenster offen" und
   * „Letzter Algorithmen-Lauf" fuehren nirgends hin, wo die Zahl sich
   * aufloest. Eine Karte, die manchmal klickbar ist, muss das sichtbar
   * unterscheiden — dafuer steht die Hover-Umrandung unten.
   */
  href?: string;
}

/**
 * Beschriftung und Farbe der Kachel „Funk-Empfang" (Sprint 25 T8).
 *
 * Die **Stufe** entscheidet das Backend (die Schwellen stehen in den
 * Settings), hier steht nur, wie sie heißt und welchen Ton sie bekommt.
 *
 * `unbekannt` ist bewusst **neutral** und nicht rot: es heißt „noch keine
 * einzige Meldung", also ein frisch aufgesetztes Haus. Rot zu zeigen wäre
 * eine Behauptung über eine Anlage, die es noch nicht gibt.
 */
const FUNK_TEXT: Record<DashboardKpi["funkempfang_stufe"], string> = {
  online: "online",
  verzoegert: "verzögert",
  keine_meldungen: "keine Meldungen",
  unbekannt: "—",
};

const FUNK_TON: Record<DashboardKpi["funkempfang_stufe"], KpiTone> = {
  online: "neutral",
  verzoegert: "warning-soft",
  keine_meldungen: "danger-soft",
  unbekannt: "neutral",
};

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
      // Sprint 21 (B-21-2): Zähler und Nenner über **zugeordnete** Geräte.
      // Vorher zählte der Nenner Pool und Lager mit — die Kachel stand
      // damit dauerhaft auf Gelb, weil ein Ersatzteil ohne Batterie
      // korrekt "nicht online" ist. Eine Warnung, die immer leuchtet,
      // warnt nicht (§5.79).
      //
      // Das Lager steht als eigene, kleinere Zeile darunter und färbt
      // nichts. Es erscheint nur, wenn es etwas zu sagen hat: eine Zeile
      // "0 im Lager" ist Platz ohne Inhalt.
      label: "Geräte online",
      value: data.devices_online,
      subValue: `von ${data.devices_assigned}`,
      note: data.devices_pool > 0 ? `${data.devices_pool} im Lager` : undefined,
      icon: "device_thermostat",
      tone: data.devices_online < data.devices_assigned ? "warning-soft" : "neutral",
      // Das Gegenteil dessen, was diese Kachel zaehlt: zugeordnet und
      // nicht healthy/degraded. Die Auswahl dort heisst entsprechend.
      href: "/devices?zeige=nicht-online",
    },
    {
      label: "Aktive Übersteuerungen",
      value: data.active_overrides,
      icon: "tune",
      tone: "neutral",
    },
    {
      // Sprint 25 T8: solange **kein** Gerät bestätigt hat, dass die
      // Fenstererkennung bei ihm eingeschaltet ist, steht hier
      // „Erkennung inaktiv" und **keine Zahl**.
      //
      // Eine 0 an dieser Stelle liest sich als „es ist kein Fenster
      // offen". Richtig ist „niemand hat gemessen": am 07.11.2026 stand
      // hausweit keine einzige Zeile mit `open_window = true` — bei
      // 604.694 Zeilen `false` und 49 belegten Temperatureinbrüchen
      // allein in Zimmer 306. Die 0 ist hier die gefährlichere Zahl,
      // weil sie wie ein Befund aussieht (§5.77).
      label: "Fenster offen",
      value: data.fenstererkennung_aktiv ? data.zones_window_open : "Erkennung inaktiv",
      subValue: data.fenstererkennung_aktiv ? undefined : "keine Rückmeldung vom Gerät",
      icon: "sensor_window",
      tone:
        data.fenstererkennung_aktiv && data.zones_window_open > 0 ? "warning-soft" : "neutral",
    },
    {
      // Sprint 25 T8: die Kachel, die den Ausfall vom 07.11.2026 gezeigt
      // hätte. Sie liest das **Ende** der Kette (`sensor_reading`) und
      // bewusst nicht den ChirpStack-Gateway-Status: an diesem Tag war
      // das Gateway in Ordnung, Port 1883 gesperrt und die Zahl der
      // Meldungen null. Ein Gateway-Status hätte grün gezeigt.
      //
      // Die **Stufe** kommt aus dem Backend, weil die Schwellen in den
      // Settings stehen. Sie hier zu rechnen hieße, sie zu wiederholen —
      // eine zweite Wahrheit (§5.53).
      label: "Funk-Empfang",
      value: FUNK_TEXT[data.funkempfang_stufe],
      subValue:
        data.funkempfang_alter_min !== null
          ? `letzte Meldung vor ${data.funkempfang_alter_min} min`
          : undefined,
      note: `${data.funkempfang_meldungen_10min} Meldungen in 10 min`,
      icon: "settings_input_antenna",
      tone: FUNK_TON[data.funkempfang_stufe],
    },
    {
      label: "Letzter Algorithmen-Lauf",
      value: tick ? formatRelative(tick) : "—",
      subValue: tick ? formatDateTime(tick) : undefined,
      icon: "history",
      tone: tickStale ? "warning-soft" : "neutral",
    },
    {
      // Sprint 15d (AE-65): aktive Geräte mit schwacher Batterie (warn∪kritisch),
      // dieselbe Achse wie die BatteryBadges — warning-soft sobald > 0.
      label: "Schwache Batterie",
      value: data.battery_low_count,
      icon: "battery_alert",
      tone: data.battery_low_count > 0 ? "warning-soft" : "neutral",
      href: "/devices?zeige=batterie",
    },
    {
      // Sprint 20e (T7): dieselbe Achse wie der gelbe ValveHintBadge.
      label: "Ventil prüfen",
      value: data.valve_check_count,
      icon: "build",
      tone: data.valve_check_count > 0 ? "warning-soft" : "neutral",
      href: "/devices?zeige=ventil",
    },
    {
      // Sprint 20e (T10): der Ersatz-Melder für Layer 4 Detached. Rot, nicht
      // gelb — ein offenes Ventil ohne Kopf heizt gegen das Fenster,
      // solange es niemand sieht. Dieselbe Achse wie der rote
      // ValveHintBadge; die Kachel zählt genau die Geräte, die ihn tragen.
      label: "Zimmer zu warm",
      value: data.room_too_warm_count,
      icon: "local_fire_department",
      tone: data.room_too_warm_count > 0 ? "danger-soft" : "neutral",
      href: "/devices?zeige=zu-warm",
    },
  ];
}

export default function Home() {
  const { user } = useAuth();
  const kpiQ = useDashboardKpi();
  const importQ = useOccupancyImportLog();

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
            : buildCards(kpiQ.data).map((c) => {
                const karte = (
                  <KpiCard
                    label={c.label}
                    value={c.value}
                    subValue={c.subValue}
                    note={c.note}
                    icon={c.icon}
                    tone={c.tone}
                  />
                );
                // Sprint 21 A3: dieselbe Form wie die Belegungsliste-Kachel
                // unten — ein Link um die Karte, kein zweiter Mechanismus.
                // Die Hover-Umrandung ist die sichtbare Unterscheidung
                // zwischen klickbar und nicht (§5.57: Semantik, die nur beim
                // Darueberfahren existiert, ist keine).
                return c.href ? (
                  <Link
                    key={c.label}
                    href={c.href as Route}
                    className="block rounded-lg ring-offset-background transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                  >
                    {karte}
                  </Link>
                ) : (
                  <div key={c.label}>{karte}</div>
                );
              })}

        {/* Sprint 15f (AE-66): Belegungsliste-Kachel — eigene Datenquelle
            (GET .../occupancy-import/log), klickbar zur Detailseite. */}
        <Link href="/einstellungen/api" className="block">
          {importQ.isLoading ? (
            <KpiCard loading label="Belegungsliste" value="" icon="event_available" />
          ) : importQ.isError || !importQ.data ? (
            <KpiCard error label="Belegungsliste" value="" icon="event_available" />
          ) : (
            <KpiCard
              label="Belegungsliste"
              value={
                importQ.data.last_success_at
                  ? formatRelative(importQ.data.last_success_at)
                  : "Noch nie"
              }
              subValue={
                importQ.data.last_success_at
                  ? formatDateTime(importQ.data.last_success_at)
                  : undefined
              }
              icon="event_available"
              tone={IMPORT_STATUS_TONE[importQ.data.status]}
            />
          )}
        </Link>
      </div>
    </div>
  );
}
