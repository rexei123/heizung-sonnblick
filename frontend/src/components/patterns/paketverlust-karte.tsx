"use client";

/**
 * „Paketverlust" (02.11.2026).
 *
 * **Eine Messung, keine Schätzung.** Der LoRaWAN-Zähler läuft lückenlos
 * hoch — auch über die Uplinks, die das Gateway nie gehört hat. Wer die
 * Spanne kennt und die Zeilen zählt, kennt den Verlust.
 *
 * Anlass ist Relais 109: zwischen `fCnt` 8 und `fCnt` 13 fehlten vier
 * Frames, rund 30 %, während das Gateway die Vickis im selben Zeitraum
 * normal hörte. Diese Rechnung stand in keiner Oberfläche; sie wurde von
 * Hand aus den ChirpStack-Ereignissen gelesen.
 *
 * **„—" ist nicht 0 %.** Unter zwei Frames im Fenster gibt es keine
 * Lücke, die man sehen könnte, und eine Null wäre eine Behauptung über
 * einen Funk, der nicht gemessen wurde (dieselbe Unterscheidung wie bei
 * der Batterie, §5.73).
 *
 * **Eine Rücksetzung des Zählers ist kein Verlust.** Sie steht im
 * Hinweistext, damit ein Neustart nicht als Funkproblem gelesen wird —
 * und damit sichtbar ist, dass die Rechnung ihn kennt.
 *
 * Die Schwellen für die Farbe sind **Anzeige**, keine Steuerung: nichts
 * im Backend hängt daran. Über 10 % ist der Bereich, in dem ein
 * Schaltbefehl regelmäßig unbestätigt bleibt (der Wächter wiederholt
 * dann, AE-78 §14); über 25 % war der Zustand von 109 am provisorischen
 * Platz.
 */

import { useQuery } from "@tanstack/react-query";

import { devicesApi } from "@/lib/api/devices";
import { formatRelative } from "@/lib/format";

const WARNEN_AB = 10;
const KRITISCH_AB = 25;

function ton(anteil: number | null): string {
  if (anteil === null) return "text-text-tertiary";
  if (anteil >= KRITISCH_AB) return "text-error";
  if (anteil >= WARNEN_AB) return "text-warning";
  return "text-text-primary";
}

export function PaketverlustKarte({ deviceId }: { deviceId: number }) {
  const abfrage = useQuery({
    queryKey: ["devices", deviceId, "paketverlust"],
    queryFn: () => devicesApi.paketverlust(deviceId),
    // Dieselbe Kadenz wie die übrigen Diagnose-Kacheln. Ein kürzeres
    // Intervall brächte nichts: ein Vicki meldet sich alle zehn Minuten.
    refetchInterval: 60_000,
  });

  const v = abfrage.data;

  // **Eine Kachel darf die Seite nicht mitnehmen.**
  //
  // Der Befund kam aus CI (02.11.2026): zwölf Tests der Geräteseite
  // fielen um, weil ihr Catch-all-Mock `[]` für diesen Weg liefert.
  // `[].anteil_prozent` ist `undefined`, `undefined.toFixed()` wirft, und
  // die ganze Seite bleibt leer — in den Tests fehlte dann die Karte, die
  // sie eigentlich prüfen.
  //
  // Der Mock ist nicht die Lehre, sondern der Anlass: eine Antwort, die
  // nicht zum Typ passt, kommt im Betrieb genauso vor (alter Server,
  // halber Deploy, Proxy-Fehlerseite). Geprüft wird deshalb der **Typ
  // zur Laufzeit** und nicht nur beim Übersetzen — die Annotation gilt
  // für den Code, nicht für die Antwort.
  const anteil = typeof v?.anteil_prozent === "number" ? v.anteil_prozent : null;
  const zahlenDa =
    typeof v?.verloren === "number" &&
    typeof v?.erwartet === "number" &&
    typeof v?.stunden === "number";

  return (
    <div
      className="bg-surface rounded-lg border border-border p-4"
      data-testid="paketverlust-karte"
    >
      <div className="flex items-center gap-2 text-text-tertiary text-xs">
        <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 18 }}>
          network_check
        </span>
        <span>Paketverlust</span>
      </div>

      <div className="mt-2">
        <p
          className={`text-base font-medium ${ton(anteil)}`}
          data-testid="paketverlust-anteil"
        >
          {abfrage.isLoading ? "…" : anteil === null ? "—" : `${anteil.toFixed(1)} %`}
        </p>

        {zahlenDa && v !== undefined && (
          <p className="text-text-tertiary text-xs mt-1" data-testid="paketverlust-hinweis">
            {anteil === null ? (
              <>
                Unter zwei Frames in {v.stunden} h — noch keine Lücke zu sehen.
                Das ist nicht 0 %.
              </>
            ) : (
              <>
                {v.verloren} von {v.erwartet} Frames fehlen, {v.stunden} h
                {typeof v.bis === "string" && <> · zuletzt {formatRelative(v.bis)}</>}
              </>
            )}
          </p>
        )}

        {typeof v?.neustarts === "number" && v.neustarts > 0 && (
          <p className="text-text-tertiary text-xs mt-1" data-testid="paketverlust-neustarts">
            {v.neustarts === 1 ? "Ein Neustart" : `${v.neustarts} Neustarts`} des
            Zählers — nicht als Verlust gerechnet.
          </p>
        )}
      </div>
    </div>
  );
}
