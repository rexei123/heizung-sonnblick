"use client";

/**
 * Hotel-Stammdaten-Seite (Sprint 8.12, Sprint 8.15 Design-Fixes).
 * Bedient Singleton global_config. Cards: Allgemein / Standardzeiten / Alerts.
 */

import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { useGlobalConfig, useUpdateGlobalConfig } from "@/lib/api/hooks-global-config";
import type { ApiError, GlobalConfigUpdate } from "@/lib/api/types";

export default function HotelSettingsPage() {
  const cfg = useGlobalConfig();
  const updateMut = useUpdateGlobalConfig();

  const [hotelName, setHotelName] = useState("");
  const [timezone, setTimezone] = useState("");
  const [checkIn, setCheckIn] = useState("");
  const [checkOut, setCheckOut] = useState("");
  const [alertEmail, setAlertEmail] = useState("");
  const [offlineMin, setOfflineMin] = useState("");
  const [batteryWarn, setBatteryWarn] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Hydrate form state when data arrives.
  useEffect(() => {
    if (!cfg.data) return;
    setHotelName(cfg.data.hotel_name);
    setTimezone(cfg.data.timezone);
    setCheckIn(cfg.data.default_checkin_time.slice(0, 5));
    setCheckOut(cfg.data.default_checkout_time.slice(0, 5));
    setAlertEmail(cfg.data.alert_email ?? "");
    setOfflineMin(String(cfg.data.alert_device_offline_minutes));
    setBatteryWarn(String(cfg.data.alert_battery_warn_percent));
  }, [cfg.data]);

  const handle = async (e: FormEvent) => {
    e.preventDefault();
    if (!cfg.data) return;
    setError(null);
    setSuccess(null);

    // Nur geaenderte Felder ans API senden.
    const payload: GlobalConfigUpdate = {};
    if (hotelName !== cfg.data.hotel_name) payload.hotel_name = hotelName;
    if (timezone !== cfg.data.timezone) payload.timezone = timezone;
    if (checkIn !== cfg.data.default_checkin_time.slice(0, 5)) {
      payload.default_checkin_time = `${checkIn}:00`;
    }
    if (checkOut !== cfg.data.default_checkout_time.slice(0, 5)) {
      payload.default_checkout_time = `${checkOut}:00`;
    }
    if ((cfg.data.alert_email ?? "") !== alertEmail) {
      payload.alert_email = alertEmail.trim() || null;
    }
    if (parseInt(offlineMin, 10) !== cfg.data.alert_device_offline_minutes) {
      payload.alert_device_offline_minutes = parseInt(offlineMin, 10);
    }
    if (parseInt(batteryWarn, 10) !== cfg.data.alert_battery_warn_percent) {
      payload.alert_battery_warn_percent = parseInt(batteryWarn, 10);
    }

    if (Object.keys(payload).length === 0) {
      setSuccess("Keine Änderungen.");
      return;
    }

    try {
      await updateMut.mutateAsync(payload);
      setSuccess(`${Object.keys(payload).length} Feld(er) aktualisiert.`);
    } catch (e) {
      setError(toMessage(e));
    }
  };

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <header className="mb-6">
        <h1 className="text-2xl font-medium text-text-primary">Hotel-Stammdaten</h1>
        <p className="text-sm text-text-secondary mt-1">
          Globale Konfiguration. Änderungen wirken auf die Engine ab dem nächsten Evaluations-Zyklus.
        </p>
      </header>

      {cfg.isLoading ? (
        <p className="text-sm text-text-secondary">Lade…</p>
      ) : cfg.isError ? (
        <p className="text-sm text-error">Fehler beim Laden.</p>
      ) : cfg.data ? (
        <form onSubmit={handle} className="space-y-5">
          <Card title="Allgemein">
            <Field id="cfg-name" label="Hotel-Name" value={hotelName} onChange={setHotelName} />
            <Field
              id="cfg-tz"
              label="Zeitzone"
              value={timezone}
              onChange={setTimezone}
              hint="z.B. Europe/Vienna"
            />
          </Card>

          <Card title="Standardzeiten">
            <div className="grid grid-cols-2 gap-3">
              <TimeField id="cfg-ci" label="Default Check-in" value={checkIn} onChange={setCheckIn} />
              <TimeField id="cfg-co" label="Default Check-out" value={checkOut} onChange={setCheckOut} />
            </div>
          </Card>

          <Card title="Alerts">
            <Field
              id="cfg-mail"
              label="E-Mail für Warnungen"
              value={alertEmail}
              onChange={setAlertEmail}
              type="email"
              placeholder="hotelsonnblick@gmail.com"
            />
            <div className="grid grid-cols-2 gap-3">
              <NumField
                id="cfg-off"
                label="Gerät offline nach (Min)"
                value={offlineMin}
                onChange={setOfflineMin}
                min={1}
                max={1440}
              />
              <NumField
                id="cfg-bat"
                label="Batterie-Warnung unter (%)"
                value={batteryWarn}
                onChange={setBatteryWarn}
                min={1}
                max={100}
              />
            </div>
          </Card>

          {error ? (
            <div
              role="alert"
              className="text-sm text-error bg-error-soft border border-error rounded-md px-3 py-2"
            >
              {error}
            </div>
          ) : null}
          {success ? (
            <div className="text-sm text-success bg-success-soft border border-success rounded-md px-3 py-2">
              {success}
            </div>
          ) : null}

          <div className="flex justify-end">
            <Button type="submit" variant="primary" loading={updateMut.isPending}>
              Speichern
            </Button>
          </div>
        </form>
      ) : null}
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-surface border border-border rounded-md p-5 space-y-3">
      <h2 className="text-base font-medium text-text-primary">{title}</h2>
      {children}
    </div>
  );
}

interface FieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
  hint?: string;
}

function Field({ id, label, value, onChange, type = "text", placeholder, hint }: FieldProps) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-text-primary mb-1">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
      />
      {hint ? <p className="mt-1 text-xs text-text-tertiary">{hint}</p> : null}
    </div>
  );
}

function TimeField({ id, label, value, onChange }: Omit<FieldProps, "type">) {
  return <Field id={id} label={label} value={value} onChange={onChange} type="time" />;
}

interface NumFieldProps extends Omit<FieldProps, "type"> {
  min?: number;
  max?: number;
}

function NumField({ id, label, value, onChange, min, max }: NumFieldProps) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-text-primary mb-1">
        {label}
      </label>
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
      />
    </div>
  );
}

function toMessage(err: unknown): string {
  const e = err as ApiError | Error;
  if (typeof e === "object" && e !== null && "detail" in e) {
    const d = (e as ApiError).detail;
    return typeof d === "string" ? d : JSON.stringify(d);
  }
  return e instanceof Error ? e.message : "Unbekannter Fehler";
}
