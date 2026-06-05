"use client";

import Link from "next/link";
import { notFound, useParams } from "next/navigation";
import { useMemo, useState, type KeyboardEvent, type ReactNode } from "react";

import { BatteryBadge } from "@/components/patterns/battery-badge";
import { HardwareStatusBadge } from "@/components/patterns/hardware-status-badge";
import { SensorReadingsChart } from "@/components/patterns/sensor-readings-chart";
import { ZoneHealthBadge } from "@/components/patterns/zone-health-badge";
import { Input } from "@/components/ui/input";
import { useDevice, useSensorReadings, useUpdateDevice } from "@/lib/api/hooks";
import {
  formatDateTime,
  formatPercent,
  formatRssi,
  formatSnr,
  formatTemperature,
} from "@/lib/format";
import type {
  ApiError,
  Device,
  DeviceActiveOverride,
  OverrideSource,
} from "@/lib/api/types";

function toMessage(e: unknown): string {
  if (typeof e === "object" && e !== null && "detail" in e) {
    const d = (e as ApiError).detail;
    return typeof d === "string" ? d : JSON.stringify(d);
  }
  return e instanceof Error ? e.message : "Unbekannter Fehler";
}

export default function DeviceDetailPage() {
  const params = useParams<{ device_id: string }>();
  const id = Number.parseInt(params.device_id, 10);
  const idValid = Number.isFinite(id) && id > 0;

  const deviceQ = useDevice(idValid ? id : null);
  // Default-Filter: letzte 24 h, max 200 Eintraege.
  const since = useMemo(
    () => new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
    [],
  );
  const readingsQ = useSensorReadings(idValid ? id : null, {
    from: since,
    limit: 200,
  });

  if (!idValid) {
    notFound();
  }

  const error404 =
    deviceQ.error && (deviceQ.error as unknown as ApiError).status === 404
      ? true
      : false;

  if (error404) {
    return (
      <div className="p-6 max-w-content mx-auto">
        <h1 className="text-2xl font-medium">Gerät nicht gefunden</h1>
        <p className="mt-2 text-sm text-text-secondary">
          Geräte-ID {id} existiert nicht oder wurde gelöscht.
        </p>
        <Link
          href="/devices"
          className="mt-4 inline-flex items-center gap-2 text-sm text-primary"
        >
          <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
            arrow_back
          </span>
          Zur Geräteliste
        </Link>
      </div>
    );
  }

  const device = deviceQ.data;
  const readings = readingsQ.data ?? [];
  const latest = readings[0];
  const snapshot = device?.latest_reading ?? null;

  return (
    <div className="p-6 max-w-content mx-auto space-y-6">
      <div>
        <Link
          href="/devices"
          className="inline-flex items-center gap-1 text-sm text-text-secondary hover:text-primary"
        >
          <span className="material-symbols-outlined" style={{ fontSize: 18 }} aria-hidden="true">
            arrow_back
          </span>
          Geräte
        </Link>
      </div>

      {deviceQ.isLoading ? (
        <div className="h-32 rounded-lg bg-surface-alt animate-pulse" />
      ) : device ? (
        <>
          <header className="bg-surface rounded-lg border border-border p-6">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="min-w-0">
                <DeviceLabelEdit device={device} />
                <p className="mt-1 text-sm text-text-secondary">
                  {device.vendor} {device.model} · {device.kind}
                </p>
                {device.retired_at !== null ? (
                  <span className="mt-2 inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-xs font-medium bg-danger-soft text-danger w-fit">
                    <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 14 }}>
                      block
                    </span>
                    Stillgelegt
                  </span>
                ) : null}
              </div>
              <div className="flex flex-col items-end gap-2 text-sm">
                <div className="text-text-secondary text-right">
                  <div className="mb-1">Status</div>
                  <HardwareStatusBadge deviceId={device.id} variant="detailed" />
                </div>
                {device.heating_zone ? (
                  <ZoneHealthBadge
                    healthState={device.heating_zone.health_state}
                    variant="detailed"
                  />
                ) : null}
              </div>
            </div>
          </header>

          {/* Zwei Karten: Zuordnung + Identifikation (D5) */}
          <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <InfoCard title="Zuordnung" icon="meeting_room">
              <InfoRow label="Zimmer" value={device.heating_zone?.room.number ?? "Nicht zugeordnet"} />
              <InfoRow
                label="Raumtyp"
                value={device.heating_zone?.room.room_type.name ?? "—"}
              />
              <InfoRow label="Zone" value={device.heating_zone?.name ?? "—"} />
            </InfoCard>

            <InfoCard title="Identifikation" icon="badge">
              <div
                className="flex items-center justify-between gap-4 py-1.5 border-b border-border/60 last:border-0"
                data-testid="hardware-number-row"
              >
                <span className="text-sm text-text-tertiary">Hardware-Nummer</span>
                <HardwareNumberEdit device={device} />
              </div>
              <InfoRow label="DevEUI" value={device.dev_eui} mono />
              <InfoRow label="Hersteller" value={device.vendor} />
              <InfoRow label="Modell" value={device.model} />
              <InfoRow label="Firmware" value={device.firmware_version ?? "—"} />
            </InfoCard>
          </section>

          {/* Sieben Diagnose-Kacheln: 4 bestehende + 3 neue (D5) */}
          <section className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <KpiCard
              icon="thermostat"
              label="Temperatur"
              value={formatTemperature(latest?.temperature ?? null)}
              tone="primary"
            />
            <KpiCard
              icon="adjust"
              label="Sollwert"
              value={formatTemperature(latest?.setpoint ?? null)}
              tone="info"
            />
            {/* Sprint 15d PR3: Batterie als Badge (detailed) statt Prozent-
                Wert — konsistent zu Liste/Bubble, Prozent nur im Tooltip.
                Card-Chrome wie die Geschwister-Kacheln, Badge ersetzt den
                grossen Wert. */}
            <div
              className="bg-surface rounded-lg border border-border p-4"
              data-testid="battery-card"
            >
              <div className="flex items-center gap-2 text-text-tertiary text-xs">
                <span
                  className="material-symbols-outlined"
                  aria-hidden="true"
                  style={{ fontSize: 18 }}
                >
                  battery_horiz_075
                </span>
                <span>Batterie</span>
              </div>
              <div className="mt-2">
                <BatteryBadge
                  batteryState={device.battery_state}
                  batteryPercent={latest?.battery_percent ?? null}
                  variant="detailed"
                />
              </div>
            </div>
            <KpiCard
              icon="signal_cellular_alt"
              label="Signal"
              value={formatRssi(latest?.rssi_dbm ?? null)}
              hint={formatSnr(latest?.snr_db ?? null)}
              tone="default"
            />
            <KpiCard
              icon="valve"
              label="Ventilstellung"
              value={formatValve(snapshot?.valve_position ?? null)}
              tone="default"
              testId="kpi-ventilstellung"
            />
            <WindowBackplateCard reading={snapshot} />
            <OverrideCard override={device.active_override} />
          </section>

          <section className="bg-surface rounded-lg border border-border p-6">
            <header className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-lg font-medium text-text-primary">
                  Verlauf der letzten 24 Stunden
                </h2>
                <p className="text-xs text-text-tertiary">
                  {readings.length} Reading{readings.length === 1 ? "" : "s"} ·
                  Aktualisierung alle 30 Sek.
                </p>
              </div>
            </header>
            {readingsQ.isLoading ? (
              <div className="h-72 rounded bg-surface-alt animate-pulse" />
            ) : (
              <SensorReadingsChart readings={readings} />
            )}
          </section>

          <section className="bg-surface rounded-lg border border-border overflow-hidden">
            <header className="px-6 py-4 border-b border-border">
              <h2 className="text-lg font-medium text-text-primary">
                Letzte Einzelmessungen
              </h2>
            </header>
            {readings.length === 0 ? (
              <div className="p-6 text-center text-sm text-text-tertiary">
                Noch keine Messwerte für dieses Gerät vorhanden.
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead className="bg-surface-alt text-text-secondary">
                  <tr>
                    <th className="text-left px-6 py-2 font-medium">Zeit</th>
                    <th className="text-left px-6 py-2 font-medium">Temp</th>
                    <th className="text-left px-6 py-2 font-medium">Sollwert</th>
                    <th className="text-left px-6 py-2 font-medium">Ventil</th>
                    <th className="text-left px-6 py-2 font-medium">Batt</th>
                    <th className="text-left px-6 py-2 font-medium">RSSI</th>
                  </tr>
                </thead>
                <tbody>
                  {readings.slice(0, 20).map((r) => (
                    <tr key={r.time} className="border-t border-border">
                      <td className="px-6 py-2 text-text-secondary">
                        {formatDateTime(r.time)}
                      </td>
                      <td className="px-6 py-2">{formatTemperature(r.temperature)}</td>
                      <td className="px-6 py-2 text-text-secondary">
                        {formatTemperature(r.setpoint)}
                      </td>
                      <td className="px-6 py-2 text-text-secondary">
                        {formatPercent(r.valve_position)}
                      </td>
                      <td className="px-6 py-2 text-text-secondary">
                        {formatPercent(r.battery_percent)}
                      </td>
                      <td className="px-6 py-2 text-text-secondary">
                        {formatRssi(r.rssi_dbm)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Inline-Edit (LabelCell-Pattern, Sprint 14a D5) — Bezeichnung + Hardware-Nr.
// AE-61: nur Stamm-Daten editierbar, keine Steuer-Aktionen auf Geräte-Seiten.
// ---------------------------------------------------------------------------

interface InlineTextEditProps {
  value: string | null;
  emptyDisplay: string;
  ariaLabel: string;
  displayClassName: string;
  /** Anzeige-Element im Display-Modus. "h1" fuer die Seiten-Headline. */
  as?: "h1" | "span";
  /** null = Feld leeren. */
  onSave: (next: string | null) => Promise<void>;
}

function InlineTextEdit({
  value,
  emptyDisplay,
  ariaLabel,
  displayClassName,
  as = "span",
  onSave,
}: InlineTextEditProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const save = async () => {
    const trimmed = draft.trim();
    const next = trimmed.length === 0 ? null : trimmed;
    if (next === (value ?? null)) {
      setEditing(false);
      return;
    }
    setError(null);
    setPending(true);
    try {
      await onSave(next);
      setEditing(false);
    } catch (e) {
      setError(toMessage(e));
    } finally {
      setPending(false);
    }
  };

  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      e.preventDefault();
      void save();
    } else if (e.key === "Escape") {
      e.preventDefault();
      setDraft(value ?? "");
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
            disabled={pending}
            className="h-8 text-sm"
            aria-label={`${ariaLabel} bearbeiten`}
            aria-invalid={error !== null}
          />
          {pending ? (
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

  const isEmpty = value === null;
  const valueClass = `${displayClassName} ${isEmpty ? "text-text-tertiary italic" : ""}`.trim();
  return (
    <div className="flex items-center gap-2">
      {as === "h1" ? (
        <h1 className={valueClass}>{value ?? emptyDisplay}</h1>
      ) : (
        <span className={valueClass}>{value ?? emptyDisplay}</span>
      )}
      <button
        type="button"
        onClick={() => {
          setDraft(value ?? "");
          setError(null);
          setEditing(true);
        }}
        className="text-text-tertiary hover:text-primary"
        aria-label={`${ariaLabel} bearbeiten`}
        title={`${ariaLabel} bearbeiten`}
      >
        <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 16 }}>
          edit
        </span>
      </button>
    </div>
  );
}

function DeviceLabelEdit({ device }: { device: Device }) {
  const updateMut = useUpdateDevice(device.id);
  return (
    <InlineTextEdit
      value={device.label}
      emptyDisplay={`Device ${device.id}`}
      ariaLabel="Bezeichnung"
      as="h1"
      displayClassName="text-2xl font-medium text-text-primary"
      onSave={(next) => updateMut.mutateAsync({ label: next }).then(() => undefined)}
    />
  );
}

function HardwareNumberEdit({ device }: { device: Device }) {
  const updateMut = useUpdateDevice(device.id);
  return (
    <InlineTextEdit
      value={device.hardware_number}
      emptyDisplay="Nicht erfasst"
      ariaLabel="Hardware-Nummer"
      displayClassName="text-sm font-mono text-text-primary"
      onSave={(next) =>
        updateMut.mutateAsync({ hardware_number: next }).then(() => undefined)
      }
    />
  );
}

// ---------------------------------------------------------------------------
// Karten + Kacheln
// ---------------------------------------------------------------------------

function InfoCard({
  title,
  icon,
  children,
}: {
  title: string;
  icon: string;
  children: ReactNode;
}) {
  return (
    <div className="bg-surface rounded-lg border border-border p-6">
      <div className="flex items-center gap-2 mb-3">
        <span className="material-symbols-outlined text-text-tertiary" aria-hidden style={{ fontSize: 18 }}>
          {icon}
        </span>
        <h2 className="text-sm font-medium text-text-primary">{title}</h2>
      </div>
      <dl className="space-y-0">{children}</dl>
    </div>
  );
}

function InfoRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 py-1.5 border-b border-border/60 last:border-0">
      <dt className="text-sm text-text-tertiary">{label}</dt>
      <dd className={`text-sm text-text-primary ${mono ? "font-mono text-xs" : ""}`.trim()}>
        {value}
      </dd>
    </div>
  );
}

interface KpiCardProps {
  icon: string;
  label: string;
  value: string;
  hint?: string;
  tone: "default" | "primary" | "info" | "danger";
  testId?: string;
}

function KpiCard({ icon, label, value, hint, tone, testId }: KpiCardProps) {
  const toneClass = {
    default: "text-text-primary",
    primary: "text-primary",
    info: "text-info",
    danger: "text-danger",
  }[tone];

  return (
    <div className="bg-surface rounded-lg border border-border p-4" data-testid={testId}>
      <div className="flex items-center gap-2 text-text-tertiary text-xs">
        <span
          className="material-symbols-outlined"
          aria-hidden="true"
          style={{ fontSize: 18 }}
        >
          {icon}
        </span>
        <span>{label}</span>
      </div>
      <div className={`mt-2 text-2xl font-medium ${toneClass}`}>{value}</div>
      {hint ? <div className="mt-1 text-xs text-text-tertiary">{hint}</div> : null}
    </div>
  );
}

/** D7: Ventilstellung defensiv — Werte ausserhalb 0..100 als „nicht verfügbar". */
function formatValve(v: number | null): string {
  if (v === null || v < 0 || v > 100) return "nicht verfügbar";
  return `${v} %`;
}

function WindowBackplateCard({
  reading,
}: {
  reading: { open_window: boolean | null; attached_backplate: boolean | null } | null;
}) {
  const fenster =
    reading?.open_window === true ? "offen" : reading?.open_window === false ? "zu" : "—";
  const montage =
    reading?.attached_backplate === true
      ? "montiert"
      : reading?.attached_backplate === false
        ? "abgenommen"
        : "—";
  return (
    <div className="bg-surface rounded-lg border border-border p-4" data-testid="window-backplate-card">
      <div className="flex items-center gap-2 text-text-tertiary text-xs">
        <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 18 }}>
          sensor_window
        </span>
        <span>Fenster + Backplate</span>
      </div>
      <div className="mt-2 space-y-1 text-sm">
        <div className="flex justify-between">
          <span className="text-text-tertiary">Fenster</span>
          <span className="font-medium text-text-primary">{fenster}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-text-tertiary">Montage</span>
          <span className="font-medium text-text-primary">{montage}</span>
        </div>
      </div>
    </div>
  );
}

const OVERRIDE_SOURCE_LABEL: Record<OverrideSource, string> = {
  device: "Drehring am Thermostat",
  frontend_4h: "Rezeption (4 h)",
  frontend_midnight: "Rezeption (bis Mitternacht)",
  frontend_checkout: "Rezeption (bis Check-out)",
};

/** D5: Override-Status read-only (AE-61) — keine Aktion auf Geräte-Seite. */
function OverrideCard({ override }: { override: DeviceActiveOverride | null }) {
  return (
    <div
      className="bg-surface rounded-lg border border-border p-4 md:col-span-2"
      data-testid="override-card"
    >
      <div className="flex items-center gap-2 text-text-tertiary text-xs">
        <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 18 }}>
          touch_app
        </span>
        <span>Override</span>
      </div>
      {!override ? (
        <div className="mt-2 text-sm text-text-secondary">Kein Override aktiv</div>
      ) : (
        <div className="mt-2 space-y-1 text-sm">
          <div className="text-text-primary font-medium">
            Override aktiv · {override.setpoint_celsius.toFixed(1)} °C
          </div>
          <div className="text-text-tertiary text-xs">
            Quelle: {OVERRIDE_SOURCE_LABEL[override.source]} · läuft bis:{" "}
            {override.source === "frontend_checkout"
              ? "Check-out"
              : formatDateTime(override.expires_at)}
          </div>
        </div>
      )}
    </div>
  );
}
