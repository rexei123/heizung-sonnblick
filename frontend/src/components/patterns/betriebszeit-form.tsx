"use client";

/**
 * Betriebszeit eines Allgemeinbereichs (Sprint 24d).
 *
 * **Wozu.** Eine Bar ist von 15:00 bis 24:00 offen, die Rezeption von
 * 07:00 bis 22:00. Außerhalb dieser Zeiten soll der Bereich abgesenkt
 * werden — und das ist dieselbe Rechnung, die bei einem Gästezimmer die
 * Nachtabsenkung macht. Deshalb kein neues Feld in der Engine, sondern
 * ein anderer Name an der Oberfläche: `von` ist das Ende der Absenkung,
 * `bis` ihr Beginn (`services/betriebszeit` im Backend).
 *
 * **Warum am Zimmer und nicht am Raumtyp.** Bar und Rezeption haben
 * denselben Charakter und verschiedene Zeiten. Die Zeit gehört zum Ort,
 * nicht zur Art. Ist sie hier leer, greift die Kette weiter — Raumtyp,
 * dann hausweit.
 *
 * **„24:00" ist erlaubt** und die natürliche Schreibweise für „bis
 * Mitternacht". Das Backend bildet sie auf 00:00 ab; wer 00:00 eingibt,
 * meint dasselbe und bekommt dasselbe.
 *
 * **Der Knopf ist Bedienung, nicht Sicherheit.** `PATCH
 * /rooms/{id}/betriebszeit` ist `require_admin`, und der Endpunkt weist
 * ein Gästezimmer mit 422 ab — die Felder erscheinen dort ohnehin nicht.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/contexts/auth-context";
import { fehlerText } from "@/lib/api/fehler";
import { setzeBetriebszeit } from "@/lib/api/betriebszeit";
import { darfStammdatenAendern } from "@/lib/auth/rechte";
import type { Room } from "@/lib/api/types";

/** `"15:00:00"` aus dem Backend zu `"15:00"` für das Eingabefeld.
 *
 * Bewusst `== null` (deckt `undefined` mit ab): ein Mock oder eine
 * Antwort ohne das Feld darf die Seite nicht umwerfen. Genau das ist beim
 * ersten Lauf passiert — `undefined.slice()` nimmt den ganzen Baum mit,
 * und übrig bleibt eine leere Seite ohne Fehlermeldung.
 */
function kurz(wert: string | null | undefined): string {
  return wert == null ? "" : wert.slice(0, 5);
}

export function BetriebszeitForm({ room }: { room: Room }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [von, setVon] = useState(() => kurz(room.betriebszeit_von));
  const [bis, setBis] = useState(() => kurz(room.betriebszeit_bis));
  const [meldung, setMeldung] = useState<string | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);

  const darfAendern = darfStammdatenAendern(user);
  const gesetzt = room.betriebszeit_von !== null && room.betriebszeit_bis !== null;

  const mut = useMutation({
    mutationFn: (werte: { von: string | null; bis: string | null }) =>
      setzeBetriebszeit(room.id, werte),
    onSuccess: (aktualisiert) => {
      setFehler(null);
      setMeldung(
        aktualisiert.betriebszeit_von === null
          ? "Betriebszeit gelöscht — es gilt wieder, was Raumtyp oder Haus vorgeben."
          : "Betriebszeit gespeichert. Die Engine übernimmt sie beim nächsten Durchlauf (≤ 60 s).",
      );
      // **Die Schlüssel sind hier der Fix** (Befund des Betreibers,
      // 25.10.2026: „kein Knopf Löschen, keine Bestätigung; globale Seite
      // meldet weiterhin nur 1 Zimmer").
      //
      // `["engine-trace", id]` war **falsch**: der Schlüssel heißt
      // `["room", id, "engine-trace"]` (`ROOM_KEYS.engineTrace`). Ein
      // Schlüssel, der auf nichts zeigt, wirft keinen Fehler — er tut
      // einfach nichts, und der Trace zeigte weiter den alten Stand.
      //
      // Und die Zählung auf der globalen Seite („wie viele Zimmer haben
      // eine eigene Einstellung") wurde nie ungültig gemacht. Sie ist der
      // einzige Ort, an dem man eine gesetzte Betriebszeit von außen
      // sieht — genau dort stand die alte Zahl.
      void queryClient.invalidateQueries({ queryKey: ["room", room.id] });
      void queryClient.invalidateQueries({ queryKey: ["room", room.id, "engine-trace"] });
      void queryClient.invalidateQueries({ queryKey: ["hausstandard-nutzung"] });
    },
    onError: (e: unknown) => {
      setMeldung(null);
      // ``apiClient`` wirft ein einfaches Objekt, keine ``Error``-Instanz —
      // ``e.message`` war ``undefined`` und der Kasten damit leer.
      setFehler(fehlerText(e));
    },
  });

  return (
    <section
      className="bg-surface rounded-lg border border-border p-4"
      data-testid="betriebszeit-form"
    >
      <header className="mb-3">
        <h3 className="text-sm font-medium text-text-primary">Betriebszeit</h3>
        <p className="text-text-tertiary text-xs">
          Außerhalb dieser Zeit wird der Bereich auf den Absenkwert seines
          Raumtyps gefahren. Leer = es gilt, was Raumtyp oder Haus vorgeben.
        </p>
      </header>

      <div className="flex flex-wrap items-end gap-3">
        <label className="block">
          <span className="text-text-secondary mb-1 block text-xs">von</span>
          <Input
            type="text"
            inputMode="numeric"
            placeholder="07:00"
            value={von}
            onChange={(e) => setVon(e.target.value)}
            disabled={!darfAendern || mut.isPending}
            aria-label="Betriebszeit von"
            data-testid="betriebszeit-von"
            className="w-24"
          />
        </label>
        <label className="block">
          <span className="text-text-secondary mb-1 block text-xs">bis</span>
          <Input
            type="text"
            inputMode="numeric"
            placeholder="22:00"
            value={bis}
            onChange={(e) => setBis(e.target.value)}
            disabled={!darfAendern || mut.isPending}
            aria-label="Betriebszeit bis"
            data-testid="betriebszeit-bis"
            className="w-24"
          />
        </label>

        {darfAendern ? (
          <>
            <Button
              type="button"
              variant="primary"
              onClick={() => mut.mutate({ von: von.trim(), bis: bis.trim() })}
              disabled={mut.isPending}
              data-testid="betriebszeit-speichern"
            >
              Speichern
            </Button>
            {gesetzt ? (
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setVon("");
                  setBis("");
                  mut.mutate({ von: null, bis: null });
                }}
                disabled={mut.isPending}
                data-testid="betriebszeit-loeschen"
              >
                Löschen
              </Button>
            ) : null}
          </>
        ) : (
          <span className="text-text-tertiary text-xs">
            Änderungen sind Administratoren vorbehalten.
          </span>
        )}
      </div>

      {/* „24:00" steht hier und nicht nur im Fehlerfall: wer eine
          Betriebszeit bis Mitternacht eintragen will, soll nicht erst
          raten müssen, ob 24:00 erlaubt ist. */}
      <p className="text-text-tertiary mt-2 text-xs">
        HH:MM. „24:00" ist erlaubt und bedeutet Mitternacht.
      </p>

      {/* **Nicht mehr elf Pixel grau.** Der Betreiber hat am 25.10.2026
          gemeldet, es sei „keine Bestätigung" gekommen — und ein Satz in
          der kleinsten Schriftgröße unter einem Formular ist von „nichts
          passiert" nicht zu unterscheiden. Ein Fehler erst recht nicht:
          ein Melder, den man übersieht, meldet nichts (§5.79). */}
      {meldung !== null ? (
        <p
          className="border-success bg-success-soft text-success mt-3 flex items-start gap-2 rounded-md border px-3 py-2 text-sm"
          role="status"
          data-testid="betriebszeit-meldung"
        >
          <span className="material-symbols-outlined shrink-0" aria-hidden style={{ fontSize: 18 }}>
            check_circle
          </span>
          {meldung}
        </p>
      ) : null}
      {fehler !== null ? (
        <p
          className="border-error bg-error-soft text-error mt-3 flex items-start gap-2 rounded-md border px-3 py-2 text-sm font-medium"
          role="alert"
          data-testid="betriebszeit-fehler"
        >
          <span className="material-symbols-outlined shrink-0" aria-hidden style={{ fontSize: 18 }}>
            error
          </span>
          <span>
            Betriebszeit <strong>nicht</strong> gespeichert: {fehler}
          </span>
        </p>
      ) : null}
    </section>
  );
}
