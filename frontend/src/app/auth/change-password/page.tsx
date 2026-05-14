"use client";

/**
 * /auth/change-password (Sprint 9.17, AE-50).
 *
 * Eingeloggte User koennen ihr eigenes Passwort wechseln. Bei
 * ``must_change_password=true`` wird man nach Login automatisch
 * hierher geleitet.
 *
 * Validierung clientseitig: min 12 Zeichen, neues + wiederholtes
 * Passwort gleich.
 */

import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/contexts/auth-context";
import { authApi } from "@/lib/api/auth";
import type { ApiError } from "@/lib/api/types";

export default function ChangePasswordPage() {
  const { user, loading, refreshUser } = useAuth();
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!loading && user === null) router.replace("/login");
  }, [loading, user, router]);

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    if (next.length < 12) {
      setError("Neues Passwort muss mindestens 12 Zeichen lang sein.");
      return;
    }
    if (next !== repeat) {
      setError("Die beiden Passwoerter stimmen nicht ueberein.");
      return;
    }
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
        setError("Aktuelles Passwort ist falsch.");
      } else {
        setError("Speichern fehlgeschlagen.");
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
          Mindestens 12 Zeichen. Beide Eingaben müssen übereinstimmen.
        </p>
      </header>

      <form className="space-y-4" onSubmit={handleSubmit} noValidate>
        <div className="space-y-1">
          <Label htmlFor="current">Aktuelles Passwort</Label>
          <Input
            id="current"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            disabled={submitting}
            required
            autoFocus
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="new">Neues Passwort</Label>
          <Input
            id="new"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            disabled={submitting}
            required
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="repeat">Neues Passwort wiederholen</Label>
          <Input
            id="repeat"
            type="password"
            autoComplete="new-password"
            value={repeat}
            onChange={(e) => setRepeat(e.target.value)}
            disabled={submitting}
            required
          />
        </div>

        {error ? (
          <p role="alert" className="text-sm text-error">
            {error}
          </p>
        ) : null}

        <Button type="submit" disabled={submitting} className="w-full">
          {submitting ? "Speichern…" : "Passwort ändern"}
        </Button>
      </form>
    </div>
  );
}
