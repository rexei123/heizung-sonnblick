"use client";

/**
 * /einstellungen/benutzer (Sprint 9.17, AE-50).
 *
 * Admin-only Benutzerverwaltung: Liste, Anlegen, Rolle wechseln,
 * Passwort zurücksetzen, Aktivieren/Deaktivieren, Löschen.
 * Mitarbeiter und nicht-eingeloggte User werden auf /login bzw. die
 * 403-Hinweis-Seite umgeleitet (Frontend-Guard + Backend-403).
 */

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PasswordInput } from "@/components/ui/password-input";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import { useAuth } from "@/contexts/auth-context";
import {
  useCreateUser,
  useDeleteUser,
  useResetUserPassword,
  useUpdateUser,
  useUsers,
} from "@/lib/api/hooks-users";
import { formatRelative } from "@/lib/format";
import type { User, UserRole } from "@/lib/api/types";

type DialogState =
  | { kind: "none" }
  | { kind: "create" }
  | { kind: "reset"; user: User }
  | { kind: "delete"; user: User }
  | { kind: "toggle-active"; user: User };

const ROLE_LABEL: Record<UserRole, string> = {
  admin: "Administrator",
  mitarbeiter: "Mitarbeiter",
};

export default function BenutzerPage() {
  const { user: me, loading } = useAuth();
  const router = useRouter();
  const usersQ = useUsers();
  const [dialog, setDialog] = useState<DialogState>({ kind: "none" });
  const [toast, setToast] = useState<string | null>(null);
  const [errorToast, setErrorToast] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && me === null) router.replace("/login");
    if (!loading && me !== null && me.role !== "admin") router.replace("/");
  }, [loading, me, router]);

  if (loading || me === null || me.role !== "admin") {
    return (
      <div className="p-6">
        <p className="text-sm text-text-secondary">Wird geladen…</p>
      </div>
    );
  }

  const showSuccess = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3500);
  };

  return (
    <div className="p-6 max-w-content mx-auto">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-medium text-text-primary">Benutzer</h1>
          <p className="text-sm text-text-secondary mt-1">
            Mitarbeiter- und Admin-Konten. Mitarbeiter dürfen Belegungen
            und Manual-Overrides bedienen; Admins können alles.
          </p>
        </div>
        <Button onClick={() => setDialog({ kind: "create" })} icon="add">
          Neuer Benutzer
        </Button>
      </header>

      {usersQ.isLoading ? (
        <div className="h-48 rounded-lg bg-surface-alt animate-pulse" />
      ) : usersQ.error || !usersQ.data ? (
        <div
          role="alert"
          className="p-4 rounded-md bg-danger-soft text-danger border border-danger/20"
        >
          Benutzerliste konnte nicht geladen werden.
        </div>
      ) : (
        <UsersTable
          users={usersQ.data}
          selfId={me.id}
          onOpenDialog={setDialog}
          onError={setErrorToast}
          onSuccess={showSuccess}
        />
      )}

      {dialog.kind === "create" ? (
        <CreateUserDialog
          onClose={() => setDialog({ kind: "none" })}
          onSuccess={() => {
            showSuccess("Benutzer angelegt.");
            setDialog({ kind: "none" });
          }}
          onError={setErrorToast}
        />
      ) : null}

      {dialog.kind === "reset" ? (
        <ResetPasswordDialog
          user={dialog.user}
          onClose={() => setDialog({ kind: "none" })}
          onSuccess={() => {
            showSuccess(`Passwort für ${dialog.user.email} zurückgesetzt.`);
            setDialog({ kind: "none" });
          }}
          onError={setErrorToast}
        />
      ) : null}

      {dialog.kind === "delete" ? (
        <DeleteUserDialog
          user={dialog.user}
          onClose={() => setDialog({ kind: "none" })}
          onSuccess={() => {
            showSuccess(`Benutzer ${dialog.user.email} gelöscht.`);
            setDialog({ kind: "none" });
          }}
          onError={setErrorToast}
        />
      ) : null}

      {dialog.kind === "toggle-active" ? (
        <ToggleActiveDialog
          user={dialog.user}
          onClose={() => setDialog({ kind: "none" })}
          onSuccess={(activated) => {
            showSuccess(
              activated
                ? `${dialog.user.email} aktiviert.`
                : `${dialog.user.email} deaktiviert.`,
            );
            setDialog({ kind: "none" });
          }}
          onError={setErrorToast}
        />
      ) : null}

      {toast ? (
        <div
          role="status"
          className="fixed bottom-6 right-6 z-50 rounded-md bg-success-soft text-success border border-success/20 px-4 py-3 shadow-md text-sm"
        >
          {toast}
        </div>
      ) : null}
      {errorToast ? (
        <div
          role="alert"
          className="fixed bottom-6 right-6 z-50 rounded-md bg-danger-soft text-danger border border-danger/20 px-4 py-3 shadow-md text-sm"
        >
          {errorToast}
          <button
            type="button"
            className="ml-3 text-danger/70"
            onClick={() => setErrorToast(null)}
          >
            ×
          </button>
        </div>
      ) : null}
    </div>
  );
}

function UsersTable({
  users,
  selfId,
  onOpenDialog,
  onError,
  onSuccess,
}: {
  users: User[];
  selfId: number;
  onOpenDialog: (d: DialogState) => void;
  onError: (msg: string) => void;
  onSuccess: (msg: string) => void;
}) {
  return (
    <div className="bg-surface rounded-lg border border-border overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-surface-alt text-text-secondary">
          <tr>
            <th className="text-left px-4 py-3 font-medium">E-Mail</th>
            <th className="text-left px-4 py-3 font-medium">Rolle</th>
            <th className="text-left px-4 py-3 font-medium">Eingerichtet</th>
            <th className="text-left px-4 py-3 font-medium">Letzter Login</th>
            <th className="text-left px-4 py-3 font-medium">Aktionen</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <UserRow
              key={u.id}
              user={u}
              isSelf={u.id === selfId}
              onOpenDialog={onOpenDialog}
              onError={onError}
              onSuccess={onSuccess}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function UserRow({
  user,
  isSelf,
  onOpenDialog,
  onError,
  onSuccess,
}: {
  user: User;
  isSelf: boolean;
  onOpenDialog: (d: DialogState) => void;
  onError: (msg: string) => void;
  onSuccess: (msg: string) => void;
}) {
  const updateMut = useUpdateUser(user.id);

  const handleRoleToggle = async () => {
    if (isSelf) {
      onError("Admin darf eigene Rolle nicht ändern.");
      return;
    }
    try {
      const next = user.role === "admin" ? "mitarbeiter" : "admin";
      await updateMut.mutateAsync({ role: next });
      onSuccess(`${user.email} ist jetzt ${ROLE_LABEL[next]}.`);
    } catch (e) {
      onError(e instanceof Error ? e.message : "Rolle konnte nicht geändert werden.");
    }
  };

  return (
    <tr className="border-t border-border">
      <td className="px-4 py-3 font-medium text-text-primary">
        {user.email}
        {isSelf ? (
          <span className="ml-2 text-xs text-text-tertiary">(Du)</span>
        ) : null}
      </td>
      <td className="px-4 py-3">
        <button
          type="button"
          onClick={() => void handleRoleToggle()}
          disabled={isSelf || updateMut.isPending}
          className="text-text-primary hover:text-primary disabled:cursor-not-allowed disabled:opacity-60"
          title={
            isSelf ? "Eigene Rolle nicht änderbar" : "Klick zum Rolle wechseln"
          }
        >
          {ROLE_LABEL[user.role]}
        </button>
      </td>
      <td className="px-4 py-3">
        <span
          className={
            user.is_active
              ? "inline-flex items-center gap-1 text-text-primary"
              : "inline-flex items-center gap-1 text-text-tertiary"
          }
        >
          <span
            className="material-symbols-outlined"
            aria-hidden
            style={{ fontSize: 16 }}
          >
            {user.is_active ? "check_circle" : "cancel"}
          </span>
          {user.is_active ? "ja" : "nein"}
        </span>
      </td>
      <td className="px-4 py-3 text-text-secondary">
        {user.last_login_at ? formatRelative(user.last_login_at) : "noch nie"}
      </td>
      <td className="px-4 py-3">
        <div className="flex gap-2 flex-wrap">
          <Button
            variant="secondary"
            onClick={() => onOpenDialog({ kind: "reset", user })}
          >
            Passwort
          </Button>
          <Button
            variant="secondary"
            onClick={() => onOpenDialog({ kind: "toggle-active", user })}
            disabled={isSelf}
          >
            {user.is_active ? "Deaktivieren" : "Aktivieren"}
          </Button>
          <Button
            variant="destructive"
            onClick={() => onOpenDialog({ kind: "delete", user })}
            disabled={isSelf}
          >
            Löschen
          </Button>
        </div>
      </td>
    </tr>
  );
}

function CreateUserDialog({
  onClose,
  onSuccess,
  onError,
}: {
  onClose: () => void;
  onSuccess: () => void;
  onError: (msg: string) => void;
}) {
  const createMut = useCreateUser();
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<UserRole>("mitarbeiter");
  const [initialPassword, setInitialPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  return (
    <Tabs defaultValue="anlegen">
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Neuen Benutzer anlegen"
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      >
        <div className="w-full max-w-md bg-surface border border-border rounded-lg shadow-md p-6">
          <h2 className="text-lg font-medium text-text-primary mb-4">
            Neuer Benutzer
          </h2>
          <TabsList className="hidden">
            <TabsTrigger value="anlegen">Anlegen</TabsTrigger>
          </TabsList>
          <TabsContent value="anlegen" className="space-y-4">
            <div className="space-y-1">
              <Label htmlFor="new-email">E-Mail</Label>
              <Input
                id="new-email"
                type="email"
                autoComplete="off"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={submitting}
                autoFocus
                required
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="new-role">Rolle</Label>
              <select
                id="new-role"
                value={role}
                onChange={(e) => setRole(e.target.value as UserRole)}
                disabled={submitting}
                className="w-full h-10 rounded-md border border-border bg-surface px-3 text-sm"
              >
                <option value="mitarbeiter">Mitarbeiter</option>
                <option value="admin">Administrator</option>
              </select>
            </div>
            <div className="space-y-1">
              <Label htmlFor="new-pw">Initiales Passwort (min. 12 Zeichen)</Label>
              <Input
                id="new-pw"
                type="text"
                autoComplete="off"
                value={initialPassword}
                onChange={(e) => setInitialPassword(e.target.value)}
                disabled={submitting}
                required
              />
              <p className="text-xs text-text-tertiary">
                Wird dem Benutzer einmalig kommuniziert. User muss beim ersten
                Login wechseln.
              </p>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="secondary" onClick={onClose} disabled={submitting}>
                Abbrechen
              </Button>
              <Button
                onClick={async () => {
                  if (initialPassword.length < 12) {
                    onError("Initiales Passwort muss mindestens 12 Zeichen lang sein.");
                    return;
                  }
                  setSubmitting(true);
                  try {
                    await createMut.mutateAsync({
                      email,
                      role,
                      initial_password: initialPassword,
                    });
                    onSuccess();
                  } catch (e) {
                    onError(
                      e instanceof Error ? e.message : "Anlegen fehlgeschlagen.",
                    );
                  } finally {
                    setSubmitting(false);
                  }
                }}
                disabled={submitting || !email || !initialPassword}
              >
                Anlegen
              </Button>
            </div>
          </TabsContent>
        </div>
      </div>
    </Tabs>
  );
}

function ResetPasswordDialog({
  user,
  onClose,
  onSuccess,
  onError,
}: {
  user: User;
  onClose: () => void;
  onSuccess: () => void;
  onError: (msg: string) => void;
}) {
  const resetMut = useResetUserPassword(user.id);
  const [pw, setPw] = useState("");
  const [submitting, setSubmitting] = useState(false);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Passwort zurücksetzen"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    >
      <div className="w-full max-w-md bg-surface border border-border rounded-lg shadow-md p-6 space-y-4">
        <h2 className="text-lg font-medium text-text-primary">
          Passwort zurücksetzen
        </h2>
        <p className="text-sm text-text-secondary">
          Für <span className="font-medium">{user.email}</span>. User wird beim
          nächsten Login zum Wechsel gezwungen.
        </p>
        <div className="space-y-1">
          <Label htmlFor="reset-pw">Neues Passwort (min. 12 Zeichen)</Label>
          <PasswordInput
            id="reset-pw"
            autoComplete="off"
            value={pw}
            onChange={(e) => setPw(e.target.value)}
            disabled={submitting}
            autoFocus
          />
        </div>
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={onClose} disabled={submitting}>
            Abbrechen
          </Button>
          <Button
            onClick={async () => {
              if (pw.length < 12) {
                onError("Passwort muss mindestens 12 Zeichen lang sein.");
                return;
              }
              setSubmitting(true);
              try {
                await resetMut.mutateAsync({ new_password: pw });
                onSuccess();
              } catch (e) {
                onError(
                  e instanceof Error
                    ? e.message
                    : "Zurücksetzen fehlgeschlagen.",
                );
              } finally {
                setSubmitting(false);
              }
            }}
            disabled={submitting || !pw}
          >
            Speichern
          </Button>
        </div>
      </div>
    </div>
  );
}

function DeleteUserDialog({
  user,
  onClose,
  onSuccess,
  onError,
}: {
  user: User;
  onClose: () => void;
  onSuccess: () => void;
  onError: (msg: string) => void;
}) {
  const deleteMut = useDeleteUser();
  return (
    <ConfirmDialog
      open={true}
      title={`${user.email} löschen?`}
      message="Der Benutzer wird endgültig entfernt. Audit-Einträge mit der user_id bleiben in config_audit/business_audit erhalten."
      confirmLabel="Endgültig löschen"
      intent="destructive"
      loading={deleteMut.isPending}
      onCancel={onClose}
      onConfirm={async () => {
        try {
          await deleteMut.mutateAsync(user.id);
          onSuccess();
        } catch (e) {
          onError(e instanceof Error ? e.message : "Löschen fehlgeschlagen.");
        }
      }}
    />
  );
}

function ToggleActiveDialog({
  user,
  onClose,
  onSuccess,
  onError,
}: {
  user: User;
  onClose: () => void;
  onSuccess: (activated: boolean) => void;
  onError: (msg: string) => void;
}) {
  const updateMut = useUpdateUser(user.id);
  const next = !user.is_active;
  return (
    <ConfirmDialog
      open={true}
      title={next ? `${user.email} aktivieren?` : `${user.email} deaktivieren?`}
      message={
        next
          ? "User kann sich wieder einloggen."
          : "User wird beim nächsten Login abgewiesen. Bestehende Sessions laufen bis 12h-JWT-Ablauf weiter."
      }
      confirmLabel={next ? "Aktivieren" : "Deaktivieren"}
      intent={next ? "primary" : "destructive"}
      loading={updateMut.isPending}
      onCancel={onClose}
      onConfirm={async () => {
        try {
          await updateMut.mutateAsync({ is_active: next });
          onSuccess(next);
        } catch (e) {
          onError(
            e instanceof Error ? e.message : "Aktualisieren fehlgeschlagen.",
          );
        }
      }}
    />
  );
}
