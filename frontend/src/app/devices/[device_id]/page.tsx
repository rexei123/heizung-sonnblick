"use client";

import Link from "next/link";
import { notFound, useParams } from "next/navigation";
import { useMemo } from "react";

import { HardwareStatusBadge } from "@/components/patterns/hardware-status-badge";
import { SensorReadingsChart } from "@/components/patterns/sensor-readings-chart";
import { useDevice, useSensorReadings } from "@/lib/api/hooks";
import {
  formatDateTime,
  formatPercent,
  formatRssi,
  formatSnr,
  formatTemperature,
} from "@/lib/format";
import type { ApiError } from "@/lib/api/types";

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
              <div>
                <h1 className="text-2xl font-medium text-text-primary">
                  {device.label ?? `Device ${device.id}`}
                </h1>
                <p className="mt-1 text-sm text-text-secondary">
                  {device.vendor} {device.model} · {device.kind}
                </p>
                <p className="mt-2 font-mono text-xs text-text-tertiary">
                  DevEUI {device.dev_eui}
                </p>
              </div>
              <div className="text-right text-sm space-y-2">
                <div>
                  {device.is_active ? (
                    <span className="px-2 py-0.5 rounded-sm bg-success-soft text-success text-xs font-medium">
                      aktiv
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-sm bg-surface-alt text-text-tertiary text-xs font-medium">
                      inaktiv
                    </span>
                  )}
                </div>
                <div className="text-text-secondary">
                  <div className="mb-1">Hardware-Status</div>
                  <HardwareStatusBadge deviceId={device.id} variant="detailed" />
                </div>
              </div>
            </div>
          </header>

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
            <KpiCard
              icon="battery_horiz_075"
              label="Batterie"
              value={formatPercent(latest?.battery_percent ?? null)}
              tone={
                latest?.battery_percent != null && latest.battery_percent < 20
                  ? "danger"
                  : "default"
              }
            />
            <KpiCard
              icon="signal_cellular_alt"
              label="Signal"
              value={formatRssi(latest?.rssi_dbm ?? null)}
              hint={formatSnr(latest?.snr_db ?? null)}
              tone="default"
            />
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

interface KpiCardProps {
  icon: string;
  label: string;
  value: string;
  hint?: string;
  tone: "default" | "primary" | "info" | "danger";
}

function KpiCard({ icon, label, value, hint, tone }: KpiCardProps) {
  const toneClass = {
    default: "text-text-primary",
    primary: "text-primary",
    info: "text-info",
    danger: "text-danger",
  }[tone];

  return (
    <div className="bg-surface rounded-lg border border-border p-4">
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
