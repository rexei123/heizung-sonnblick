/**
 * Relais-Karte (Sprint 24b, Paket 6).
 *
 * Zeigt den Stand eines 16ASPM und bietet einem Admin die vier
 * Handgriffe: provisionieren, in Betrieb nehmen, zurücknehmen,
 * Schutz-Sperre aufheben.
 *
 * **Die Reihenfolge der Karte ist die Reihenfolge der Entscheidung.**
 * Oben steht, ob das Relais schalten darf, und warum nicht — das ist
 * die Frage, mit der jemand auf diese Karte kommt. Die Messwerte stehen
 * darunter; sie sind interessant, aber sie beantworten nichts.
 *
 * **Knöpfe sind Bedienung, nicht Sicherheit.** Für einen Mitarbeiter
 * erscheinen sie nicht; abgewiesen wird serverseitig, und zwar auch
 * dann, wenn jemand den Knopf nie gesehen hat (`lib/auth/rechte.ts`,
 * §5.30). Mutationsprobe M12 prüft die Server-Seite.
 *
 * **„nicht bestätigt" heißt nicht „falsch".** Eine Rücklesung, deren
 * Antwort noch nicht da ist, ist bei einem Funkgerät der Normalfall. Die
 * Karte sagt das, damit niemand daraus einen Fehler liest — dieselbe
 * Formulierung wie bei den Gerätegrenzen (Sprint 23, T1.5).
 */

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useAuth } from "@/contexts/auth-context";
import { fehlerText } from "@/lib/api/fehler";
import { darfRelaisSchalten } from "@/lib/auth/rechte";
import {
  fetchRelaisStand,
  hebeSchutzSperreAuf,
  nimmRelaisAusserBetrieb,
  nimmRelaisInBetrieb,
  provisioniereRelais,
  type RelaisStand,
} from "@/lib/api/relays";
import { formatDateTime } from "@/lib/format";

/** Warum ein Relais nicht schalten darf — in der Reihenfolge, in der es zählt. */
function sperrgrund(stand: RelaisStand): string | null {
  if (stand.protection_tripped_at !== null) {
    return `Schutz-Sperre seit ${formatDateTime(stand.protection_tripped_at)} (${
      stand.protection_kind ?? "unbekannte Art"
    }) — Freigabe nur durch einen Administrator`;
  }
  if (stand.commissioned_at === null) {
    return "Nicht in Betrieb genommen — es gehen nur Lese- und Konfigurationsbefehle hinaus";
  }
  return null;
}

function Zeile({ bezeichnung, wert }: { bezeichnung: string; wert: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1">
      <span className="text-text-tertiary text-xs">{bezeichnung}</span>
      <span className="text-text-primary text-sm font-medium">{wert}</span>
    </div>
  );
}

function Pruefzeile({
  bezeichnung,
  bestanden,
  testId,
}: {
  bezeichnung: string;
  bestanden: boolean;
  testId: string;
}) {
  // ``data-bestanden`` statt eines Text-Vergleichs: der Text steht im
  // selben Element wie die Material-Ikone, und ein genauer Vergleich auf
  // "bestätigt" findet deshalb nichts. Dasselbe Muster wie ``data-health``
  // am Zonen-Badge.
  return (
    <div
      className="flex items-center justify-between gap-4 py-1"
      data-testid={testId}
      data-bestanden={bestanden ? "true" : "false"}
    >
      <span className="text-text-tertiary text-xs">{bezeichnung}</span>
      <span
        className={`flex items-center gap-1 text-sm font-medium ${
          bestanden ? "text-text-primary" : "text-text-tertiary"
        }`}
      >
        <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 16 }}>
          {bestanden ? "check_circle" : "schedule"}
        </span>
        {bestanden ? "bestätigt" : "nicht bestätigt"}
      </span>
    </div>
  );
}

export function RelayCard({ deviceId }: { deviceId: number }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [meldung, setMeldung] = useState<string | null>(null);
  const darfHandeln = darfRelaisSchalten(user);

  const schluessel = ["relay", deviceId] as const;
  const { data, isLoading, isError } = useQuery({
    queryKey: schluessel,
    queryFn: () => fetchRelaisStand(deviceId),
  });

  function nachAktion(text: string) {
    setMeldung(text);
    void queryClient.invalidateQueries({ queryKey: schluessel });
  }

  const provision = useMutation({
    mutationFn: () => provisioniereRelais(deviceId),
    onSuccess: (ergebnis) => nachAktion(ergebnis.hinweis),
    onError: (fehler: unknown) =>
      setMeldung(`Provisionierung fehlgeschlagen: ${fehlerText(fehler)}`),
  });

  const inBetrieb = useMutation({
    mutationFn: () => nimmRelaisInBetrieb(deviceId),
    onSuccess: () => nachAktion("In Betrieb genommen. Der Regler darf jetzt schalten."),
    onError: (fehler: unknown) => setMeldung(fehlerText(fehler)),
  });

  const ausserBetrieb = useMutation({
    mutationFn: () => nimmRelaisAusserBetrieb(deviceId),
    onSuccess: () =>
      nachAktion(
        "Zurückgenommen. Das Relais wird nicht ausgeschaltet — ein laufender Timer läuft ab.",
      ),
    onError: (fehler: unknown) => setMeldung(fehlerText(fehler)),
  });

  const freigabe = useMutation({
    mutationFn: () => hebeSchutzSperreAuf(deviceId),
    onSuccess: () => nachAktion("Schutz-Sperre aufgehoben."),
    onError: (fehler: unknown) => setMeldung(fehlerText(fehler)),
  });

  if (isLoading) {
    return (
      <div className="bg-surface rounded-lg border border-border p-4" data-testid="relay-card">
        <span className="text-text-tertiary text-sm">Relais wird geladen …</span>
      </div>
    );
  }

  if (isError || data === undefined) {
    return (
      <div className="bg-surface rounded-lg border border-border p-4" data-testid="relay-card">
        <span className="text-error text-sm">Der Stand des Relais ist nicht abrufbar.</span>
      </div>
    );
  }

  const grund = sperrgrund(data);
  const laeuft =
    provision.isPending || inBetrieb.isPending || ausserBetrieb.isPending || freigabe.isPending;

  return (
    <div className="bg-surface rounded-lg border border-border p-4" data-testid="relay-card">
      <div className="flex items-center gap-2 text-text-tertiary text-xs">
        <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 18 }}>
          power_settings_new
        </span>
        <span>Relais {data.label ?? data.dev_eui}</span>
      </div>

      {/* Die Frage, mit der jemand auf diese Karte kommt. */}
      <div className="mt-2">
        {data.darf_schalten ? (
          <span className="text-text-primary text-sm font-medium" data-testid="relay-darf-schalten">
            Darf schalten
          </span>
        ) : (
          <span className="text-warning text-sm font-medium" data-testid="relay-sperrgrund">
            {grund ?? "Darf nicht schalten"}
          </span>
        )}
      </div>

      <div className="mt-3 border-t border-border pt-2">
        <Zeile
          bezeichnung="Zustand"
          wert={
            data.relay_on === null
              ? "unbekannt — keine Meldung"
              : data.relay_on
                ? "ein"
                : "aus"
          }
        />
        <Zeile
          bezeichnung="Leistung"
          wert={data.power_w === null ? "keine Meldung" : `${data.power_w} W`}
        />
        <Zeile
          bezeichnung="Energiezähler (roh)"
          wert={data.energy_wh === null ? "keine Meldung" : `${data.energy_wh} Wh`}
        />
        <Zeile
          bezeichnung="Gehäusetemperatur"
          wert={
            data.internal_temperature_raw === null
              ? "keine Meldung"
              : `${data.internal_temperature_raw}${data.gehaeusetemperatur_alarm ? " — über der Warnschwelle" : ""}`
          }
        />
        <Zeile bezeichnung="Schaltzyklen" wert={String(data.switch_cycles)} />
        <Zeile bezeichnung="Wächter" wert={data.watchdog_strategy} />
        <Zeile bezeichnung="Firmware" wert={data.firmware_version ?? "unbekannt"} />
        <Zeile
          bezeichnung="Letzter Kontakt"
          wert={data.last_seen_at === null ? "nie" : formatDateTime(data.last_seen_at)}
        />
        {data.change_reason !== null && (
          <Zeile bezeichnung="Letzte Änderung durch" wert={data.change_reason} />
        )}
      </div>

      <div className="mt-3 border-t border-border pt-2">
        <div className="text-text-tertiary mb-1 text-xs">Provisionierung</div>
        <Pruefzeile
          bezeichnung="Aus nach Stromrückkehr"
          bestanden={data.power_return_verified}
          testId="relay-pruefung-stromrueckkehr"
        />
        <Pruefzeile
          bezeichnung="Aus nach Überhitzungs-Erholung"
          bestanden={data.overheating_recovery_verified}
          testId="relay-pruefung-ueberhitzung"
        />
      </div>

      {darfHandeln && (
        <div className="mt-3 flex flex-wrap gap-2 border-t border-border pt-3">
          <button
            type="button"
            onClick={() => provision.mutate()}
            disabled={laeuft}
            data-testid="relay-provision"
            className="bg-surface-alt text-text-primary rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50"
          >
            Provisionieren
          </button>
          {data.commissioned_at === null ? (
            <button
              type="button"
              onClick={() => inBetrieb.mutate()}
              disabled={laeuft}
              data-testid="relay-commission"
              className="bg-surface-alt text-text-primary rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50"
            >
              In Betrieb nehmen
            </button>
          ) : (
            <button
              type="button"
              onClick={() => ausserBetrieb.mutate()}
              disabled={laeuft}
              data-testid="relay-decommission"
              className="bg-surface-alt text-text-primary rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50"
            >
              Zurücknehmen
            </button>
          )}
          {data.protection_tripped_at !== null && (
            <button
              type="button"
              onClick={() => freigabe.mutate()}
              disabled={laeuft}
              data-testid="relay-release"
              className="bg-surface-alt text-text-primary rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50"
            >
              Schutz-Sperre aufheben
            </button>
          )}
        </div>
      )}

      {meldung !== null && (
        <p className="text-text-secondary mt-3 text-xs" data-testid="relay-meldung">
          {meldung}
        </p>
      )}
    </div>
  );
}
