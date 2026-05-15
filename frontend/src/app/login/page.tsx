"use client";

/**
 * Login-Page (Sprint 9.17, AE-50). FastAPI-native Cookie-Auth.
 *
 * Nach erfolgreichem Login:
 *  - ``must_change_password=true`` ⇒ Redirect auf
 *    ``/auth/change-password``
 *  - sonst ⇒ Dashboard (``/``)
 *
 * Bei Fehler: generische Inline-Meldung „E-Mail oder Passwort falsch"
 * (kein User-Enumeration).
 */

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PasswordInput } from "@/components/ui/password-input";
import { useAuth } from "@/contexts/auth-context";
import type { ApiError } from "@/lib/api/types";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const user = await login(email, password);
      if (user.must_change_password) {
        router.replace("/auth/change-password");
      } else {
        router.replace("/");
      }
    } catch (e) {
      const err = e as ApiError;
      if (err?.status === 429) {
        setError("Zu viele Versuche. Bitte 60 Sekunden warten.");
      } else if (err?.status === 503) {
        setError(
          "Anmeldung gerade nicht möglich. Bitte später erneut versuchen oder die Verwaltung kontaktieren.",
        );
      } else {
        setError("E-Mail oder Passwort falsch.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-bg px-4">
      <div className="w-full max-w-sm bg-surface border border-border rounded-lg shadow-sm p-6">
        <div className="flex items-center gap-2 mb-6">
          <span
            className="material-symbols-outlined text-primary"
            aria-hidden
            style={{ fontSize: 28 }}
          >
            thermostat
          </span>
          <h1 className="text-xl font-medium text-text-primary">
            Heizung Sonnblick
          </h1>
        </div>

        <form className="space-y-4" onSubmit={handleSubmit} noValidate>
          <div className="space-y-1">
            <Label htmlFor="email">E-Mail</Label>
            <Input
              id="email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={submitting}
              autoFocus
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="password">Passwort</Label>
            <PasswordInput
              id="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={submitting}
            />
          </div>

          {error ? (
            <p role="alert" className="text-sm text-error">
              {error}
            </p>
          ) : null}

          <Button type="submit" disabled={submitting} className="w-full">
            {submitting ? "Anmelden…" : "Anmelden"}
          </Button>
        </form>
      </div>
    </div>
  );
}
