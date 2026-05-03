"use client";

/**
 * Raumtyp-Form (Sprint 8.9, Sprint 8.15 Design-Fixes).
 * Universell für Anlegen + Bearbeiten.
 */

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import type { RoomType, RoomTypeCreate, RoomTypeUpdate } from "@/lib/api/types";

interface Props {
  initial?: RoomType;
  onSubmit: (payload: RoomTypeCreate | RoomTypeUpdate) => Promise<void>;
  onCancel?: () => void;
  submitting?: boolean;
  error?: string | null;
}

export function RoomTypeForm({
  initial,
  onSubmit,
  onCancel,
  submitting = false,
  error,
}: Props) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [isBookable, setIsBookable] = useState(initial?.is_bookable ?? true);
  const [tOccupied, setTOccupied] = useState(
    String(initial?.default_t_occupied ?? "21.0"),
  );
  const [tVacant, setTVacant] = useState(
    String(initial?.default_t_vacant ?? "18.0"),
  );
  const [tNight, setTNight] = useState(
    String(initial?.default_t_night ?? "19.0"),
  );
  const [maxTemp, setMaxTemp] = useState(
    initial?.max_temp_celsius != null ? String(initial.max_temp_celsius) : "",
  );
  const [minTemp, setMinTemp] = useState(
    initial?.min_temp_celsius != null ? String(initial.min_temp_celsius) : "",
  );
  const [longVacantHours, setLongVacantHours] = useState(
    initial?.treat_unoccupied_as_vacant_after_hours != null
      ? String(initial.treat_unoccupied_as_vacant_after_hours)
      : "",
  );

  const handle = async (e: FormEvent) => {
    e.preventDefault();
    const payload: RoomTypeCreate | RoomTypeUpdate = {
      name: name.trim(),
      description: description.trim() || null,
      is_bookable: isBookable,
      default_t_occupied: parseFloat(tOccupied),
      default_t_vacant: parseFloat(tVacant),
      default_t_night: parseFloat(tNight),
      max_temp_celsius: maxTemp.trim() === "" ? null : parseFloat(maxTemp),
      min_temp_celsius: minTemp.trim() === "" ? null : parseFloat(minTemp),
      treat_unoccupied_as_vacant_after_hours:
        longVacantHours.trim() === "" ? null : parseInt(longVacantHours, 10),
    };
    await onSubmit(payload);
  };

  return (
    <form onSubmit={handle} className="space-y-4">
      <div>
        <label
          htmlFor="rt-name"
          className="block text-sm font-medium text-text-primary mb-1"
        >
          Name *
        </label>
        <input
          id="rt-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          maxLength={100}
          className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
        />
      </div>

      <div>
        <label
          htmlFor="rt-description"
          className="block text-sm font-medium text-text-primary mb-1"
        >
          Beschreibung
        </label>
        <textarea
          id="rt-description"
          value={description ?? ""}
          onChange={(e) => setDescription(e.target.value)}
          maxLength={500}
          rows={2}
          className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
        />
      </div>

      <div className="flex items-center gap-2">
        <input
          id="rt-bookable"
          type="checkbox"
          checked={isBookable}
          onChange={(e) => setIsBookable(e.target.checked)}
          className="rounded"
        />
        <label htmlFor="rt-bookable" className="text-sm text-text-primary">
          Buchbar (Hotelzimmer — Check-in/Check-out triggert Heizregeln)
        </label>
      </div>

      <fieldset className="border border-border rounded-md p-3 space-y-3">
        <legend className="text-sm font-medium text-text-primary px-1">
          Standardtemperaturen (°C)
        </legend>

        <div className="grid grid-cols-3 gap-3">
          <TempField
            id="rt-t-occupied"
            label="Belegt"
            value={tOccupied}
            onChange={setTOccupied}
            required
          />
          <TempField
            id="rt-t-vacant"
            label="Frei"
            value={tVacant}
            onChange={setTVacant}
            required
          />
          <TempField
            id="rt-t-night"
            label="Nacht"
            value={tNight}
            onChange={setTNight}
            required
          />
        </div>
      </fieldset>

      <fieldset className="border border-border rounded-md p-3 space-y-3">
        <legend className="text-sm font-medium text-text-primary px-1">
          Override-Grenzen (optional)
        </legend>

        <div className="grid grid-cols-2 gap-3">
          <TempField
            id="rt-max"
            label="Obergrenze"
            value={maxTemp}
            onChange={setMaxTemp}
            placeholder="z.B. 25.0"
          />
          <TempField
            id="rt-min"
            label="Untergrenze"
            value={minTemp}
            onChange={setMinTemp}
            placeholder="z.B. 15.0"
          />
        </div>

        <div>
          <label
            htmlFor="rt-long-vacant"
            className="block text-sm font-medium text-text-primary mb-1"
          >
            Langzeit-Absenkung nach Stunden
          </label>
          <input
            id="rt-long-vacant"
            type="number"
            min={1}
            max={240}
            value={longVacantHours}
            onChange={(e) => setLongVacantHours(e.target.value)}
            placeholder="z.B. 24"
            className="w-full px-3 py-2 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus"
          />
        </div>
      </fieldset>

      {error ? (
        <div
          role="alert"
          className="text-sm text-error bg-error-soft border border-error rounded-md px-3 py-2"
        >
          {error}
        </div>
      ) : null}

      <div className="flex gap-2 justify-end">
        {onCancel ? (
          <Button variant="secondary" onClick={onCancel}>
            Abbrechen
          </Button>
        ) : null}
        <Button
          type="submit"
          variant={initial ? "primary" : "add"}
          icon={initial ? undefined : "add"}
          loading={submitting}
          disabled={!name.trim()}
        >
          {initial ? "Aktualisieren" : "Anlegen"}
        </Button>
      </div>
    </form>
  );
}

interface TempFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  required?: boolean;
  placeholder?: string;
}

function TempField({
  id,
  label,
  value,
  onChange,
  required,
  placeholder,
}: TempFieldProps) {
  return (
    <div>
      <label
        htmlFor={id}
        className="block text-xs font-medium text-text-secondary mb-1"
      >
        {label}
      </label>
      <input
        id={id}
        type="number"
        step="0.1"
        min={5}
        max={30}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        placeholder={placeholder}
        className="w-full px-2 py-1.5 border border-border rounded-md bg-surface focus:outline-none focus:border-border-focus text-sm"
      />
    </div>
  );
}
