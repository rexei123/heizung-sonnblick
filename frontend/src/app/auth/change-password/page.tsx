"use client";

/**
 * /auth/change-password (Sprint 9.17, AE-50; 9.17a B-9.17-5/-7/-8/-9).
 *
 * Eingeloggte User können ihr eigenes Passwort wechseln. Bei
 * ``must_change_password=true`` wird man nach Login automatisch
 * hierher geleitet.
 *
 * Sprint 9.17a:
 *  - Inline-Fehler pro Feld (current_password, new_password, repeat).
 *  - Password-Sichtbarkeits-Toggle pro Feld.
 *  - Differenzierte Server-Fehler-Texte (400/429/503).
 *  - Mojibake "Passwoerter ueberein" → "Passwörter überein".
 */

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { PasswordInput } from "@/components/ui/password-input";
import { useAuth } from "@/contexts/auth-context";
import { authApi } from "@/lib/api/auth";
import type { ApiError } from "@/lib/api/types";

const MIN_PASSWORD_LENGTH = 12;

type FieldErrors = {
  current?: string;
  next?: string;
  repeat?: string;
};

export default function ChangePasswordPage() {
  const { user, loading, refreshUser } = useAuth();
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [serverError, setServerError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!loading && user === null) router.replace("/login");
  }, [loading, user, router]);

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setServerError(null);

    const errors: FieldErrors = {};
    if (next.length < MIN_PASSWORD_LENGTH) {
      errors.next = `Passwort zu kurz (mindestens ${MIN_PASSWORD_LENGTH} Zeichen).`;
    }
    if (next !== repeat) {
      errors.repeat = "Passwörter stimmen nicht überein.";
    }
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }
    setFieldErrors({});

    setSubmitting(true);
    try {
      await authApi.changePassword({
        current_password: current,
        new_password: next,
      });
      await refreshUser();
      router.replace("/");
    } catch (e) {
      const err = e as ApiError;
      if (err?.status === 400) {
        setFieldErrors({ current: "Aktuelles Passwort falsch." });
      } else if (err?.status === 429) {
        setServerError("Zu viele Versuche. Bitte 60 Sekunden warten.");
      } else if (err?.status === 503) {
        setServerError(
          "Anmeldung gerade nicht möglich. Bitte später erneut versuchen oder die Verwaltung kontaktieren.",
        );
      } else {
        setServerError("Speichern fehlgeschlagen.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="p-6 max-w-md mx-auto">
      <header className="mb-6">
        <h1 className="text-2xl font-medium text-text-primary">
          Passwort ändern
        </h1>
        <p className="text-sm text-text-secondary mt-1">
          Mindestens {MIN_PASSWORD_LENGTH} Zeichen. Beide Eingaben müssen übereinstimmen.
        </p>
      </header>

      <form className="space-y-4" onSubmit={handleSubmit} noValidate>
        <div className="space-y-1">
          <Label htmlFor="current">Aktuelles Passwort</Label>
          <PasswordInput
            id="current"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            disabled={submitting}
            required
            autoFocus
            aria-invalid={fieldErrors.current ? "true" : undefined}
            aria-describedby={fieldErrors.current ? "current-error" : undefined}
          />
          {fieldErrors.current ? (
            <p id="current-error" role="alert" className="text-sm text-error">
              {fieldErrors.current}
            </p>
          ) : null}
        </div>
        <div className="space-y-1">
          <Label htmlFor="new">Neues Passwort</Label>
          <PasswordInput
            id="new"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            disabled={submitting}
            required
            aria-invalid={fieldErrors.next ? "true" : undefined}
            aria-describedby={fieldErrors.next ? "new-error" : undefined}
          />
          {fieldErrors.next ? (
            <p id="new-error" role="alert" className="text-sm text-error">
              {fieldErrors.next}
            </p>
          ) : null}
        </div>
        <div className="space-y-1">
          <Label htmlFor="repeat">Neues Passwort wiederholen</Label>
          <PasswordInput
            id="repeat"
            autoComplete="new-password"
            value={repeat}
            onChange={(e) => setRepeat(e.target.value)}
            disabled={submitting}
            required
            aria-invalid={fieldErrors.repeat ? "true" : undefined}
            aria-describedby={fieldErrors.repeat ? "repeat-error" : undefined}
          />
          {fieldErrors.repeat ? (
            <p id="repeat-error" role="alert" className="text-sm text-error">
              {fieldErrors.repeat}
            </p>
          ) : null}
        </div>

        {serverError ? (
          <p role="alert" className="text-sm text-error">
            {serverError}
          </p>
        ) : null}

        <Button type="submit" disabled={submitting} className="w-full">
          {submitting ? "Speichern…" : "Passwort ändern"}
        </Button>
      </form>
    </div>
  );
}
