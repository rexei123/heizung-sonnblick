"use client";

/**
 * Umschalter „nur messen“ (Sprint 24c).
 *
 * **Warum ein Bestätigungsdialog und kein einfacher Schalter.** Das
 * Umschalten hat drei Folgen, und keine davon ist am Schalter zu sehen:
 * das Gerät bekommt keine Sollwerte mehr, eine Drehung am Rad wird
 * ignoriert, und es zählt nicht mehr für die Geräte-Sicherheit. Wer das
 * nicht weiß, hält es für eine Anzeige-Einstellung. Der Dialog nennt
 * alle drei im Klartext.
 *
 * **Die Kindersicherung gehört zum Einschalten, nicht daneben.** Ein
 * Fühler liegt unmontiert im Raum und hat ein drehbares Rad; ohne Sperre
 * verstellt der erste Gast, der ihn findet, einen Sollwert, den niemand
 * umsetzt. Der Downlink geht deshalb mit dem Umschalten hinaus, und die
 * Karte zeigt, ob er angekommen ist.
 *
 * **„ausstehend" ist kein Fehler.** Die Bestätigung kommt mit dem
 * nächsten Keepalive; bei einem Funkgerät ist das der Normalfall. Nur
 * „fehlgeschlagen" ist ein Befund — dann hat das Gerät das Gegenteil
 * gemeldet.
 *
 * **Knöpfe sind Bedienung, nicht Sicherheit.** Für einen Mitarbeiter
 * erscheint der Umschalter nicht; abgewiesen wird serverseitig, auch
 * wenn jemand den Weg direkt aufruft (`lib/auth/rechte.ts`, §5.30).
 * Mutationsprobe M14 prüft die Sichtbarkeit, M12 aus Sprint 24b die
 * Server-Seite.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useAuth } from "@/contexts/auth-context";
import { setzeMessrolle } from "@/lib/api/relays";
import { darfRelaisSchalten } from "@/lib/auth/rechte";
import type { Device } from "@/lib/api/types";

/** Der Kindersicherungs-Status als Satz, den ein Mensch liest. */
function sperrText(zustand: Device["child_lock_state"]): {
  text: string;
  icon: string;
  klasse: string;
} {
  if (zustand === "bestaetigt") {
    return {
      text: "Kindersicherung bestätigt",
      icon: "lock",
      klasse: "text-text-primary",
    };
  }
  if (zustand === "fehlgeschlagen") {
    return {
      text: "Kindersicherung nicht gesetzt — das Gerät meldet das Rad als frei",
      icon: "lock_open",
      klasse: "text-error",
    };
  }
  return {
    text: "Kindersicherung ausstehend — Bestätigung kommt mit dem nächsten Keepalive",
    icon: "schedule",
    klasse: "text-text-tertiary",
  };
}

export function MeasureOnlyToggle({ device }: { device: Device }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [dialogOffen, setDialogOffen] = useState(false);
  const [meldung, setMeldung] = useState<string | null>(null);

  const ziel = !device.measure_only;

  const mut = useMutation({
    mutationFn: () => setzeMessrolle(device.id, ziel),
    onSuccess: (ergebnis) => {
      setMeldung(ergebnis.hinweis);
      setDialogOffen(false);
      void queryClient.invalidateQueries({ queryKey: ["device", device.id] });
      void queryClient.invalidateQueries({ queryKey: ["devices"] });
      void queryClient.invalidateQueries({ queryKey: ["device-audit", device.id] });
    },
    onError: (fehler: Error) => {
      setMeldung(`Umschalten fehlgeschlagen: ${fehler.message}`);
      setDialogOffen(false);
    },
  });

  // Ein Relais misst nicht — die Rolle gilt nur für Thermostate, und der
  // Server weist es mit 422 ab. Den Umschalter dort gar nicht zu zeigen
  // ist die ehrlichere Variante.
  if (device.kind === "relay") {
    return null;
  }

  const sperre = sperrText(device.child_lock_state);

  return (
    <div
      className="bg-surface rounded-lg border border-border p-4"
      data-testid="measure-only-card"
    >
      <div className="flex items-center gap-2 text-text-tertiary text-xs">
        <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 18 }}>
          sensors
        </span>
        <span>Rolle</span>
      </div>

      <div className="mt-2">
        <span
          className="text-text-primary text-sm font-medium"
          data-testid="measure-only-zustand"
          data-measure-only={device.measure_only ? "true" : "false"}
        >
          {device.measure_only ? "Nur messen (Fühler)" : "Normal: stellt und misst"}
        </span>
      </div>

      {/* Der Sperr-Status nur dann, wenn die Rolle gesetzt ist. Bei einem
          normalen Thermostat ist das Rad absichtlich frei, und ein
          "bestätigt" dafür wäre eine Aussage ohne Frage. */}
      {device.measure_only && (
        <div
          className={`mt-2 flex items-center gap-1 text-xs ${sperre.klasse}`}
          data-testid="child-lock-status"
          data-zustand={device.child_lock_state}
        >
          <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 16 }}>
            {sperre.icon}
          </span>
          {sperre.text}
        </div>
      )}

      {darfRelaisSchalten(user) && (
        <div className="mt-3 border-t border-border pt-3">
          <Button
            type="button"
            variant="secondary"
            onClick={() => setDialogOffen(true)}
            disabled={mut.isPending}
            data-testid="measure-only-toggle"
          >
            {device.measure_only ? "Rolle zurücknehmen" : "Auf „nur messen“ umstellen"}
          </Button>
        </div>
      )}

      {meldung !== null && (
        <p className="text-text-secondary mt-3 text-xs" data-testid="measure-only-meldung">
          {meldung}
        </p>
      )}

      <ConfirmDialog
        open={dialogOffen}
        title={
          ziel ? "Gerät auf „nur messen“ umstellen?" : "Rolle „nur messen“ zurücknehmen?"
        }
        message={
          ziel
            ? "Das Gerät erhält danach keine Sollwerte mehr. Eine Drehung am Rad wird ignoriert und erzeugt keine Übersteuerung. Es zählt nicht mehr für die Geräte-Sicherheit — ein abgenommenes Gerät löst dann keinen Frostschutz aus. Die Kindersicherung wird mitgesendet und sperrt das Rad."
            : "Das Gerät erhält danach wieder Sollwerte und stellt das Ventil. Eine Drehung am Rad erzeugt wieder eine Übersteuerung, und es zählt wieder für die Geräte-Sicherheit. Die Kindersicherung wird gelöst, damit das Rad bedienbar ist."
        }
        confirmLabel={ziel ? "Umstellen" : "Zurücknehmen"}
        intent="primary"
        loading={mut.isPending}
        onConfirm={() => mut.mutate()}
        onCancel={() => setDialogOffen(false)}
      />
    </div>
  );
}
