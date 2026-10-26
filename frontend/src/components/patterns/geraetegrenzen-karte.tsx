"use client";

/**
 * „Grenzen am Gerät" (Sprint 23 T1.5).
 *
 * **Die Quelle ist die Antwort des Geräts, nicht das, was wir gesendet
 * haben.** Das ist der ganze Punkt der Karte: `control_command` sagt, was
 * wir wollten, die `0x15`-Antwort sagt, was am Gerät steht. Eine Anzeige,
 * die das Gesendete zeigt, wäre eine Zusicherung ohne Deckung — und zwar
 * genau die, die wir vor Sprint 20f für den Sollwert hatten.
 *
 * **„nicht bestätigt" heißt nicht „falsch".** Es heißt, dass noch keine
 * Antwort kam. Bei einem Class-A-Gerät ist das normal, solange es nicht
 * gesendet hat; der Text sagt das, damit niemand daraus einen Fehler
 * liest.
 *
 * **Weicht die Antwort vom Soll ab, steht beides da.** Nicht nur das
 * Gemeldete: wer die Abweichung sehen soll, braucht den Vergleich. Und
 * nicht nur das Soll — das wäre wieder die Zusicherung ohne Deckung.
 *
 * Ein Gerät **ohne Zone** (Reserve-Pool) hat kein Soll. Die Karte sagt
 * das, statt eine Grenze zu erfinden: ohne Einsatzort gibt es keine.
 */

import { formatRelative } from "@/lib/format";
import type { Device } from "@/lib/api/types";

function spanne(min: number | null, max: number | null): string | null {
  if (min === null || max === null) return null;
  return `${min}–${max} °C`;
}

export function GeraetegrenzenKarte({ device }: { device: Device }) {
  // Ein Relais hat kein Drehrad — die Karte sagt dort nichts.
  if (device.kind === "relay") {
    return null;
  }

  const soll = spanne(device.grenzen_soll_min_c, device.grenzen_soll_max_c);
  const ist = spanne(device.grenzen_ist_min_c, device.grenzen_ist_max_c);
  const abweichung = soll !== null && ist !== null && soll !== ist;

  return (
    <div
      className="bg-surface rounded-lg border border-border p-4"
      data-testid="geraetegrenzen-karte"
    >
      <div className="flex items-center gap-2 text-text-tertiary text-xs">
        <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 18 }}>
          vertical_align_center
        </span>
        <span>Grenzen am Gerät</span>
      </div>

      <div className="mt-2">
        {ist === null ? (
          <>
            <p className="text-text-primary text-base" data-testid="geraetegrenzen-ist">
              nicht bestätigt
            </p>
            <p className="text-text-tertiary mt-1 text-xs">
              Das Gerät hat noch nicht geantwortet. Das ist kein Fehler —
              es meldet sich von selbst, bis zu einige Minuten.
            </p>
          </>
        ) : (
          <>
            <p
              className={`text-base tabular-nums ${
                abweichung ? "text-warning font-medium" : "text-text-primary"
              }`}
              data-testid="geraetegrenzen-ist"
            >
              {ist}
            </p>
            {device.grenzen_bestaetigt_um !== null ? (
              <p className="text-text-tertiary mt-1 text-xs">
                bestätigt {formatRelative(device.grenzen_bestaetigt_um)}
              </p>
            ) : null}
          </>
        )}

        {soll === null ? (
          <p className="text-text-tertiary mt-2 text-xs">
            Kein Soll — das Gerät ist keiner Zone zugeordnet.
          </p>
        ) : abweichung ? (
          <p className="text-warning mt-2 text-xs" data-testid="geraetegrenzen-abweichung">
            Soll wäre {soll}.
          </p>
        ) : (
          <p className="text-text-tertiary mt-2 text-xs">Soll {soll}</p>
        )}
      </div>

      <p className="text-text-tertiary mt-3 text-xs">
        Die Grenze gilt nur für das Drehrad am Gerät. Die Steuerung darf
        darüber hinaus stellen — Frostschutz und Fenster-Sicherheit
        bleiben wirksam.
      </p>
    </div>
  );
}
