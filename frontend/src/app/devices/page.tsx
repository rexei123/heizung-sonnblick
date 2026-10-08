"use client";

import type { Route } from "next";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type KeyboardEvent } from "react";

import { BatteryBadge } from "@/components/patterns/battery-badge";
import { HardwareStatusBadge } from "@/components/patterns/hardware-status-badge";
import { ValveHintBadge } from "@/components/patterns/valve-hint-badge";
import { ZoneHealthBadge } from "@/components/patterns/zone-health-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDevices, useUpdateDevice } from "@/lib/api/hooks";
import type { ApiError, Device } from "@/lib/api/types";

type SortMode = "status" | "label";

function toMessage(e: unknown): string {
  if (typeof e === "object" && e !== null && "detail" in e) {
    const d = (e as ApiError).detail;
    return typeof d === "string" ? d : JSON.stringify(d);
  }
  return e instanceof Error ? e.message : "Unbekannter Fehler";
}

/**
 * Fehlerstatus-Score absteigend: hoeher = problematischer.
 *
 * Pro Geraet der HOECHSTE zutreffende Wert ueber alle Achsen:
 *
 *   retired_at gesetzt                -> 6
 *   health_state silent               -> 4  (meldet sich nicht — Tausch-Ausloeser)
 *   valve_state ventil_klemmt_zu      -> 3  ("Ventil pruefen")
 *   battery_state kritisch            -> 2  (Spannung niedrig — Information)
 *   valve_state zimmer_zu_warm        -> 2  (**Uebergang**, siehe
 *                                            RANG_ZIMMER_ZU_WARM; ab 20e-b 5)
 *   battery_state warn                -> 1  (Information)
 *   health_state degraded|suspicious  -> 1  (unplausibel)
 *   sonst                             -> 0
 *
 * **Die Rangfolge ist die Betriebsentscheidung.** Wer sie aendern will,
 * aendert diese Tabelle und sonst nichts; die e2e-Tests pruefen sie gegen
 * das `data-status-score`-Attribut der Zeile.
 *
 * ---
 *
 * **Befund 08.10.2026, und er hatte zwei Ursachen.** Auf `/devices` stand
 * Geraet 001 oben, waehrend keines der 14 mit „Zimmer zu warm" nach oben
 * kam — und 102 („Tauschen · 2,6 V"), das am 05.10. noch oben stand, war
 * nach unten gerutscht.
 *
 * **Erstens: die Ventil-Achse fehlte ganz.** Sprint 20e T7/T10 hat
 * `valve_state` eingefuehrt und diesen Konsumenten nicht nachgezogen —
 * dieselbe Auslassung wie der fehlende TypeScript-Typ in 20f-b und der
 * fehlende `field_serializer` im Hotfix vom 07.10. Eine neue Achse zu bauen
 * heisst, **alle** Stellen zu finden, die Achsen lesen.
 *
 * **Zweitens, und das ist der interessantere Teil: die alte Rangfolge liess
 * `health_state` grundsaetzlich gewinnen** („die health_state-Achse schlaegt
 * die Batterie-Achse"). Das war vertretbar, solange `silent` erst nach
 * **24 Stunden** eintrat — dann war es ein echter Ausfall. Sprint 20e T6 hat
 * die Grenze auf **3 Stunden** gesenkt (guter Grund: der Funkstille-Alarm
 * kam sonst einen Tag zu spaet). Seither ist `silent` haeufig und oft
 * voruebergehend — und verdeckt als Trumpf ueber allem genau die Geraete,
 * bei denen jemand etwas tun muss.
 *
 * 102 ist also nicht abgerutscht, sondern **ueberholt worden** von Geraeten,
 * die durch die neue Schwelle auf `silent` oder `degraded` gekippt sind. Die
 * Nebenwirkung von T6 war im PR fuer die Dashboard-Kachel „Geraete online"
 * benannt, fuer die Sortierung nicht.
 *
 * **Daraus die Rangfolge: Handlungsbedarf vor Information.** Oben die
 * Zustaende, zu denen es einen Handgriff gibt. Darunter das, was nur
 * Auskunft ist.
 *
 * Innerhalb des Handlungsbedarfs nach **Kosten des Nichtstuns**:
 *
 * - `zimmer_zu_warm` **gehoert** ganz oben, weil dort jede Stunde Energie
 *   gegen das Fenster geheizt wird und es seit AE-74 der einzige
 *   automatische Melder fuer ein abgefallenes Geraet ist. Es steht heute
 *   trotzdem im Informations-Band, weil die Regel noch Fehlalarme liefert —
 *   Begruendung an `RANG_ZIMMER_ZU_WARM`, Hebung mit Sprint 20e-b.
 * - `silent` darueber: drei Stunden ohne Meldung heisst, dass die Engine
 *   das Geraet nicht mehr sieht — und es ist seit der Betriebsregel vom
 *   08.10. der **Ausloeser fuer den Batteriewechsel**.
 * - `ventil_klemmt_zu` darunter, weil es Komfort in **einem** Zimmer kostet
 *   und nicht Energie im ganzen Haus.
 *
 * ---
 *
 * **Korrektur vom 08.10.2026, und sie betrifft meine eigene Begruendung
 * von einem Tag vorher.**
 *
 * Diese Tabelle stellte `battery_state kritisch` (4) **ueber** `silent` (3),
 * mit dem Argument: „‚Batterie unter 2,6 V' ist ein Befund ueber einen Tag
 * (24-h-Median), `silent` oft ein Funkloch von drei Stunden."
 *
 * Die Betriebsregel des Hoteliers sagt das Gegenteil, und sie hat einen
 * Befund hinter sich: **getauscht wird bei drei Stunden Funkstille, nicht
 * bei einer Spannung.** Geraet 102 meldete am 04.10. 2,6 V — ein gehaltener
 * Einzelwert unter Last, `fCnt` lueckenlos, seit dem 06.10. wieder 3,5 V.
 * Ein Tausch waere unnoetig gewesen.
 *
 * Damit ist `kritisch` **Information** und `silent` der Auftrag. Die
 * Reihenfolge dreht sich, und `kritisch` wandert in das Informations-Band
 * zu `warn` — mit 2 statt 1, weil eine niedrigere Spannung mehr sagt als
 * eine knapp niedrige.
 *
 * Mein Argument von gestern war nicht falsch in der Mechanik (der Median
 * ist tatsaechlich robuster als ein Einzelwert), aber es traf die Sache
 * nicht: ein Einbruch, der **ueber Stunden** anhaelt, ueberlebt auch den
 * 24-h-Median. Die Stufe ist schwaecher, als ihr Name versprach.
 *
 * Was von #276 bleibt: die Ventil-Achse ueberhaupt (sie fehlte ganz), und
 * dass `degraded`/`suspicious` von 3 auf 1 faellt — unplausible Messwerte
 * sind eine Datenlage, kein Handgriff, und die Engine schliesst solche
 * Geraete ohnehin aus (`health_state == "healthy"`-Filter an drei Stellen).
 *
 * `retired_at` (6) bleibt Schutz fuer `?include_retired=true`-Sichten; die
 * Default-Liste blendet retired aus (AE-57).
 */
/**
 * Rang von `zimmer_zu_warm` — **Übergangswert bis Sprint 20e-b.**
 *
 * Gehört nach AE-74 nach oben: es ist der einzige automatische Melder für
 * ein abgefallenes Gerät, und dort läuft jede Stunde Energie gegen das
 * Fenster. **Solange die Regel aber Fehlalarme liefert, gehört sie nicht
 * nach oben, sondern nach unten.**
 *
 * Stand 08.10.2026: die Kachel meldet **15** Geräte, zwei davon sind echt.
 * Mit Rang 5 besetzen also 13 Falschmeldungen die Spitze der Liste und
 * verdecken jedes stille Gerät und jeden echten Ventil-Fall — genau das
 * Verdecken, das diese Sortierung beenden sollte, nur mit anderer Ursache.
 *
 * Die Ursache ist bekannt und in Arbeit: das absolute Kriterium
 * (`Ist >= Soll + 5 K`) kann einen klemmenden Kopf nicht von einem warmen
 * Herbsttag unterscheiden. Sprint 20e-b ergänzt den Vergleich gegen den
 * Median der unbelegten Zimmer; die Messung vom 08.10. senkt damit 15 auf 1
 * (`docs/features/2026-10-08-sprint20eb-regel3b-relativ.md`).
 *
 * **Mit 20e-b wird dieser Wert auf 5 gesetzt.** Der Test
 * `der Übergangswert ist bewusst und wird mit 20e-b gehoben` fällt dann und
 * verlangt, dass es jemand absichtlich tut.
 */
const RANG_ZIMMER_ZU_WARM = 2;

function statusScore(d: Device): number {
  if (d.retired_at !== null) return 6;

  let ventil = 0;
  if (d.valve_state === "zimmer_zu_warm") ventil = RANG_ZIMMER_ZU_WARM;
  else if (d.valve_state === "ventil_klemmt_zu") ventil = 3;

  let battery = 0;
  if (d.battery_state === "kritisch") battery = 2;
  else if (d.battery_state === "warn") battery = 1;

  let health = 0;
  if (d.health_state === "silent") health = 4;
  else if (d.health_state === "degraded" || d.health_state === "suspicious") health = 1;

  return Math.max(ventil, battery, health);
}

export default function DevicesPage() {
  return (
    <Suspense fallback={<DevicesSkeletonPage />}>
      <DevicesPageInner />
    </Suspense>
  );
}

function DevicesSkeletonPage() {
  return (
    <div className="p-6 max-w-content mx-auto">
      <DevicesSkeleton />
    </div>
  );
}

function DevicesPageInner() {
  const { data, isLoading, error, refetch, isFetching } = useDevices();
  const router = useRouter();
  const params = useSearchParams();
  const sort: SortMode = params?.get("sort") === "label" ? "label" : "status";

  const setSort = (next: SortMode) => {
    const usp = new URLSearchParams(params?.toString() ?? "");
    if (next === "status") usp.delete("sort");
    else usp.set("sort", next);
    const q = usp.toString();
    router.replace((q ? `/devices?${q}` : "/devices") as Route);
  };

  const sorted = (() => {
    if (!data) return [];
    const copy = [...data];
    if (sort === "label") {
      copy.sort((a, b) => (a.label ?? a.dev_eui).localeCompare(b.label ?? b.dev_eui));
    } else {
      copy.sort((a, b) => {
        const diff = statusScore(b) - statusScore(a);
        if (diff !== 0) return diff;
        return (a.label ?? a.dev_eui).localeCompare(b.label ?? b.dev_eui);
      });
    }
    return copy;
  })();

  return (
    <div className="p-6 max-w-content mx-auto">
      <header className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-medium text-text-primary">Geräte</h1>
          <p className="text-sm text-text-secondary mt-1">
            Übersicht aller LoRaWAN-Geräte (Thermostate, Sensoren) im System.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            icon="sort"
            onClick={() => setSort(sort === "status" ? "label" : "status")}
          >
            Sortierung: {sort === "status" ? "Fehlerstatus" : "Bezeichnung"}
          </Button>
          <Button
            variant="secondary"
            icon="refresh"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            {isFetching ? "Aktualisiere…" : "Aktualisieren"}
          </Button>
          <Button asChild variant="add" icon="add">
            <Link href="/devices/pair">Gerät hinzufügen</Link>
          </Button>
        </div>
      </header>

      {isLoading ? <DevicesSkeleton /> : null}

      {error ? (
        <div
          role="alert"
          className="p-4 rounded-md bg-danger-soft text-danger border border-danger/20"
        >
          <p className="font-medium">Geräteliste konnte nicht geladen werden.</p>
          <p className="text-sm mt-1 opacity-80">
            Bitte später erneut versuchen oder Verbindung zur API prüfen.
          </p>
        </div>
      ) : null}

      {!isLoading && !error && data?.length === 0 ? <EmptyState /> : null}

      {!isLoading && !error && data && data.length > 0 ? (
        <DevicesTable devices={sorted} />
      ) : null}
    </div>
  );
}

function DevicesTable({ devices }: { devices: Device[] }) {
  return (
    <div className="bg-surface rounded-lg border border-border overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-alt text-text-secondary">
          <tr>
            <th className="text-left px-4 py-3 font-medium">Bezeichnung</th>
            <th className="text-left px-4 py-3 font-medium">Zuordnung</th>
            <th className="text-left px-4 py-3 font-medium">Gerät</th>
            <th className="text-left px-4 py-3 font-medium">Batterie</th>
            <th className="text-left px-4 py-3 font-medium">Zone</th>
          </tr>
        </thead>
        <tbody>
          {devices.map((d) => (
            <DeviceRow key={d.id} device={d} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DeviceRow({ device: d }: { device: Device }) {
  return (
    // `data-status-score` macht die Rangfolge pruefbar und im Browser
    // nachlesbar. Ohne das Attribut liesse sich nur die Reihenfolge testen —
    // und die ist bei Gleichstand von der alphabetischen Zweitsortierung
    // bestimmt, also nicht von dem, was man prueft. Beim Befund vom
    // 08.10. haette es die Diagnose auf einen Blick erledigt: 001 trug
    // einen Score, keines der 14 „Zimmer zu warm"-Geraete.
    <tr
      className="border-t border-border hover:bg-surface-alt transition-colors"
      data-status-score={statusScore(d)}
    >
      <td className="px-4 py-3">
        <LabelCell device={d} />
      </td>
      <td className="px-4 py-3">
        <ZuordnungCell device={d} />
      </td>
      <td className="px-4 py-3" data-testid="device-hardware-cell">
        <HardwareStatusBadge
          deviceId={d.id}
          isPool={d.heating_zone_id === null}
          variant="detailed"
        />
        {/*
          Sprint 20e (T7/T10): der Ventil-Hinweis steht unter dem
          Montage-Status, nicht in einer eigenen Spalte. Grund: er rendert
          nur in zwei von vier Zuständen, eine eigene Spalte wäre also
          meistens leer — und eine leere Spalte mit Kopfzeile liest sich wie
          fehlende Daten (§5.57 ist die Schwester-Lesson: ein Kopf ohne
          Inhalt ist schlimmer als keiner).

          Dieselbe Zelle ist vertretbar, weil beide Badges dieselbe Frage
          beantworten — sitzt das Gerät und tut es, was es soll. §5.66
          (feste Spalten-Slots) greift hier nicht: die Badges stehen
          untereinander, nicht nebeneinander, es gibt also keinen geteilten
          Inline-Slot, dessen Breite driften könnte.
        */}
        <ValveHintBadge valveState={d.valve_state} valveDeltaK={d.valve_delta_k} />
      </td>
      <td className="px-4 py-3" data-testid="device-battery-cell">
        <BatteryBadge
          batteryState={d.battery_state}
          batteryVolts={d.battery_voltage_median}
          batteryJumpAt={d.battery_jump_at}
          batteryLastVolts={d.battery_last_voltage}
          batteryLastAt={d.battery_last_at}
          variant="compact"
        />
      </td>
      <td className="px-4 py-3" data-testid="device-zone-cell">
        {d.heating_zone ? (
          <ZoneHealthBadge healthState={d.heating_zone.health_state} variant="compact" />
        ) : (
          <span className="text-text-tertiary" aria-label="Keine Zone zugeordnet">
            —
          </span>
        )}
      </td>
    </tr>
  );
}

/**
 * Zuordnung-Spalte (Sprint 14a, D4): Zimmer · Zone aus dem Nested-Response.
 * Pool-Geraete (keiner Zone zugewiesen) zeigen „— Reserve-Pool".
 */
function ZuordnungCell({ device: d }: { device: Device }) {
  if (!d.heating_zone) {
    return (
      <span data-testid="device-zuordnung" className="text-sm text-text-tertiary italic">
        — Reserve-Pool
      </span>
    );
  }
  return (
    <span data-testid="device-zuordnung" className="text-sm text-text-secondary">
      <span className="text-text-primary font-medium">{d.heating_zone.room.number}</span>
      {" · "}
      {d.heating_zone.name}
    </span>
  );
}

/**
 * Inline-Edit fuer device.label (TA3, AE-43-Pattern aus Betterspace).
 * Klick aufs Label oeffnet Input, Enter speichert, Esc bricht ab.
 */
function LabelCell({ device: d }: { device: Device }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(d.label ?? "");
  const [error, setError] = useState<string | null>(null);
  const updateMut = useUpdateDevice(d.id);

  const display = d.label ?? `Device ${d.id}`;

  const save = async () => {
    const trimmed = draft.trim();
    const next = trimmed.length === 0 ? null : trimmed;
    if (next === (d.label ?? null)) {
      setEditing(false);
      return;
    }
    setError(null);
    try {
      await updateMut.mutateAsync({ label: next });
      setEditing(false);
    } catch (e) {
      setError(toMessage(e));
    }
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void save();
    } else if (e.key === "Escape") {
      e.preventDefault();
      setDraft(d.label ?? "");
      setError(null);
      setEditing(false);
    }
  };

  if (editing) {
    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <Input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKey}
            onBlur={() => void save()}
            autoFocus
            autoComplete="off"
            disabled={updateMut.isPending}
            className="h-8 text-sm"
            aria-label="Bezeichnung bearbeiten"
          />
          {updateMut.isPending ? (
            <span
              className="material-symbols-outlined text-text-tertiary animate-spin"
              aria-hidden
              style={{ fontSize: 16 }}
            >
              progress_activity
            </span>
          ) : null}
        </div>
        {error ? (
          <span role="alert" className="text-xs text-error">
            {error}
          </span>
        ) : null}
      </div>
    );
  }

  // Sprint 14a (D4): Reserve-Marker wandert in die Zuordnung-Spalte
  // („— Reserve-Pool"); der bisherige Inline-Badge entfaellt zugunsten
  // der drei-spaltigen Liste.
  return (
    <div className="flex items-center gap-2">
      <Link
        href={`/devices/${d.id}` as Route}
        className="font-medium text-text-primary hover:text-primary"
      >
        {display}
      </Link>
      <button
        type="button"
        onClick={() => {
          setDraft(d.label ?? "");
          setEditing(true);
        }}
        className="text-text-tertiary hover:text-primary"
        aria-label="Bezeichnung bearbeiten"
        title="Bezeichnung bearbeiten"
      >
        <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 16 }}>
          edit
        </span>
      </button>
    </div>
  );
}

function DevicesSkeleton() {
  return (
    <div className="bg-surface rounded-lg border border-border overflow-hidden">
      <div className="h-12 bg-surface-alt" />
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="h-14 border-t border-border flex items-center gap-4 px-4"
        >
          <div className="h-4 w-32 rounded bg-surface-alt animate-pulse" />
          <div className="h-3 w-40 rounded bg-surface-alt animate-pulse" />
          <div className="h-3 w-28 rounded bg-surface-alt animate-pulse" />
          <div className="h-5 w-12 rounded bg-surface-alt animate-pulse" />
          <div className="h-3 w-20 rounded bg-surface-alt animate-pulse ml-auto" />
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="bg-surface rounded-lg border border-border p-8 text-center">
      <span
        className="material-symbols-outlined text-text-tertiary"
        style={{ fontSize: 48 }}
        aria-hidden
      >
        thermostat
      </span>
      <h2 className="mt-3 text-lg font-medium text-text-primary">Noch keine Geräte</h2>
      <p className="mt-1 text-sm text-text-secondary max-w-md mx-auto">
        Im System sind noch keine LoRaWAN-Geräte gepairt. Über „Gerät hinzufügen"
        oben rechts ein neues Gerät anlegen oder die RUNBOOK-Pairing-Anleitung
        (§10) befolgen.
      </p>
      <div className="mt-4">
        <Button asChild variant="add" icon="add">
          <Link href="/devices/pair">Gerät hinzufügen</Link>
        </Button>
      </div>
    </div>
  );
}
