"use client";

/**
 * Raumtyp-Form (Sprint 8.9, Sprint 8.15 Design-Fixes).
 * Universell für Anlegen + Bearbeiten.
 *
 * **Sprint 24d: die Felder heißen jetzt, was sie bedeuten.** Bei einem
 * nicht buchbaren Raumtyp — einem Allgemeinbereich wie Bar, Rezeption
 * oder Spa — gibt es kein „Belegt": der Bereich hat keinen Gast und
 * keinen Check-in. Er hat **Betrieb** und **Nacht**. Intern ist „Betrieb"
 * der Frei-Wert, weil ein nie belegtes Zimmer ohnehin diesen Zweig der
 * Engine nimmt; „Belegt" zieht der Server beim Speichern gleich mit
 * (`_betrieb_gleichziehen`), damit nicht ein unsichtbarer Wert in der
 * Spalte zurückbleibt.
 *
 * **Und ein Feld sagt jetzt, dass es nichts tut.** „Langzeit-Absenkung
 * nach Stunden" (`treat_unoccupied_as_vacant_after_hours`) hat im ganzen
 * Repo keinen Konsumenten — nachgesehen, nicht vermutet: kein Treffer in
 * `rules/`, `services/`, `tasks/`. Es stand seit Sprint 8 als normales
 * Eingabefeld da. Ein Schalter ohne Wirkung ist schlimmer als kein
 * Schalter (§5.77), und das Gegenmittel ist nicht, ihn zu verstecken,
 * sondern ihn zu beschriften.
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
  /**
   * Sprint 22 T4: ohne Recht zum Speichern bleiben die Werte lesbar, der
   * Knopf ist gesperrt und sagt warum. Gleiche Form wie `RoomForm`
   * (Sprint 21 A2) — `POST`/`PATCH /room-types` sind `require_admin`.
   */
  readOnly?: boolean;
}

export function RoomTypeForm({
  initial,
  onSubmit,
  onCancel,
  submitting = false,
  error,
  readOnly = false,
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

  // Sprint 24d: Allgemeinbereich — „Betrieb" statt „Belegt"/„Frei".
  const istBereich = !isBookable;

  const handle = async (e: FormEvent) => {
    e.preventDefault();
    const payload: RoomTypeCreate | RoomTypeUpdate = {
      // Sprint 24e (PR A): das Echo der bearbeiteten ID. Der Server weist
      // die Anfrage ab, wenn sie nicht zum Pfad passt — eine zweite
      // Sicherung gegen genau den Fehler, der diesen Fix ausgeloest hat.
      // Beim Anlegen gibt es keine ID; ``undefined`` faellt aus dem JSON.
      ...(initial !== undefined ? { id: initial.id } : {}),
      name: name.trim(),
      description: description.trim() || null,
      is_bookable: isBookable,
      // Bei einem Bereich ist „Betrieb" (= der Frei-Wert) beides. Der
      // Server zieht es ohnehin gleich; es hier mitzusenden hält die
      // Antwort frei von einer Überraschung.
      default_t_occupied: parseFloat(istBereich ? tVacant : tOccupied),
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
          {istBereich ? "Sollwerte des Bereichs (°C)" : "Standardtemperaturen (°C)"}
        </legend>

        <div
          className={istBereich ? "grid grid-cols-2 gap-3" : "grid grid-cols-3 gap-3"}
          data-testid="rt-sollwerte"
          data-bereich={istBereich ? "true" : "false"}
        >
          {istBereich ? null : (
            <TempField
              id="rt-t-occupied"
              label="Belegt"
              value={tOccupied}
              onChange={setTOccupied}
              required
            />
          )}
          <TempField
            id="rt-t-vacant"
            label={istBereich ? "Betrieb" : "Frei"}
            value={tVacant}
            onChange={setTVacant}
            required
          />
          <TempField
            id="rt-t-night"
            label={istBereich ? "Absenkung" : "Nacht"}
            value={tNight}
            onChange={setTNight}
            required
          />
        </div>

        {istBereich ? (
          <p className="text-xs text-text-tertiary" data-testid="rt-bereich-hinweis">
            Allgemeinbereich: kein Check-in, keine Belegung. „Betrieb" gilt
            während der Betriebszeit des Zimmers, „Absenkung" außerhalb.
          </p>
        ) : null}
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
            Langzeit-Absenkung nach Stunden{" "}
            <span className="text-text-tertiary font-normal">
              (wirkt noch nicht)
            </span>
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
          {/* Sprint 24d: nachgesehen und nicht vermutet — das Feld hat in
              `rules/`, `services/` und `tasks/` keinen Konsumenten. Es
              wird gespeichert und von niemandem gelesen. Stehenlassen
              ohne Hinweis wäre der Fehler aus §5.77. */}
          <p className="text-xs text-text-tertiary mt-1" data-testid="rt-langzeit-hinweis">
            Wird gespeichert, aber von der Regelung noch nicht gelesen.
          </p>
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
          disabled={readOnly || !name.trim()}
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
