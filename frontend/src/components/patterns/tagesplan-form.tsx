"use client";

/**
 * Tagesplan eines Allgemeinbereichs (21.11.2026).
 *
 * **Wozu.** Die Bar soll von 06:00 bis 08:00 auf 25 °C stehen, von 08:00
 * bis 21:00 auf 22 °C, und sonst abgesenkt sein. Die Betriebszeit kann das
 * nicht: sie ist **ein** Fenster mit **einem** Wert.
 *
 * **Warum hier und nicht auf der Seite „Profile".** Der Brief in #421 hat
 * die leere Seite `/profile` vorgeschlagen, die seit Monaten „Tag-, Nacht-
 * und Wochenend-Heizprofile" verspricht. Der Betreiber wollte den Plan am
 * Zimmer, und das ist richtig: die Betriebszeit steht seit Sprint 24d
 * direkt darüber, und ihre Begründung gilt wörtlich weiter — „die Zeit
 * gehört zum Ort, nicht zur Art". Zwei Orte für eine Frage wären der
 * Zustand, in dem man künftig an beiden sucht. `/profile` verweist
 * stattdessen hierher.
 *
 * **Die Tagesleiste ist nicht Zierde.** Eine Tabelle mit fünf Zeilen sagt
 * nicht, ob 21:00 noch drin ist; der Balken sagt es. Er zeigt auch die
 * **Lücken**, und die sind der Teil, über den man sich sonst irrt: nicht
 * eingezeichnete Zeit ist Absenkung.
 *
 * **Grenzen stoßen an, sie überschneiden sich nicht** (`[von, bis)`). Endet
 * ein Fenster um 08:00 und beginnt das nächste dort, gehört 08:00 zum
 * nächsten. Dieselbe Lesart in Zod, in Pydantic und in der
 * `EXCLUDE`-Bedingung der Tabelle.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/contexts/auth-context";
import {
  MAX_FENSTER,
  TAGESPLAN_KEY,
  alsUhrzeit,
  luecken,
  minuten,
  pruefeEingabe,
  setzeTagesplan,
  useTagesplan,
  type FensterEingabe,
} from "@/lib/api/tagesplan";
import { darfStammdatenAendern } from "@/lib/auth/rechte";
import { fehlerText } from "@/lib/api/fehler";

const TAG_MINUTEN = 24 * 60;

/** Eine neue, leere Zeile. Vorbelegt mit dem Vorschlag aus dem Wunsch. */
function neueZeile(vorige: FensterEingabe | undefined): FensterEingabe {
  const von = vorige ? vorige.bis : "06:00";
  return { von: von === "24:00" ? "00:00" : von, bis: "", temperatur: "" };
}

/**
 * Die 24 Stunden als Balken, die Fenster eingezeichnet.
 *
 * Gezeichnet wird aus den **eingetippten** Zeilen und nicht aus dem
 * gespeicherten Plan: wer eine Zeit ändert, soll sofort sehen, welche Lücke
 * dabei entsteht. Unvollständige oder unsinnige Zeilen werden
 * übersprungen — der Balken ist eine Hilfe, kein Prüfer.
 */
function Tagesleiste({ zeilen }: { zeilen: FensterEingabe[] }) {
  const gueltig = zeilen.filter(
    (z) =>
      /^(?:(?:[01]\d|2[0-3]):[0-5]\d|24:00)$/.test(z.von) &&
      /^(?:(?:[01]\d|2[0-3]):[0-5]\d|24:00)$/.test(z.bis) &&
      minuten(z.von) < minuten(z.bis),
  );
  const offen = luecken(gueltig);

  return (
    <div className="mt-4" data-testid="tagesplan-leiste">
      <div className="bg-surface-alt relative h-8 w-full overflow-hidden rounded-md border border-border">
        {gueltig.map((z, i) => (
          <div
            key={`f-${i}-${z.von}`}
            className="bg-primary-soft border-primary absolute top-0 bottom-0 border-l"
            style={{
              left: `${(minuten(z.von) / TAG_MINUTEN) * 100}%`,
              width: `${((minuten(z.bis) - minuten(z.von)) / TAG_MINUTEN) * 100}%`,
            }}
            title={`${z.von}–${z.bis}: ${z.temperatur || "?"} °C`}
          />
        ))}
        {offen.map(([von, bis]) => (
          <div
            key={`l-${von}`}
            className="absolute top-0 bottom-0 bg-[repeating-linear-gradient(45deg,transparent,transparent_4px,var(--color-border)_4px,var(--color-border)_5px)]"
            style={{
              left: `${(von / TAG_MINUTEN) * 100}%`,
              width: `${((bis - von) / TAG_MINUTEN) * 100}%`,
            }}
            title={`${alsUhrzeit(von)}–${alsUhrzeit(bis)}: Absenkung`}
          />
        ))}
      </div>
      <div className="text-text-tertiary mt-1 flex justify-between text-[10px]">
        <span>00:00</span>
        <span>06:00</span>
        <span>12:00</span>
        <span>18:00</span>
        <span>24:00</span>
      </div>
      <p className="text-text-tertiary mt-1 text-xs">
        Gefüllt = Fenster, schraffiert = Absenkung.
      </p>
    </div>
  );
}

export function TagesplanForm({ roomId }: { roomId: number }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const plan = useTagesplan(roomId);
  const [zeilen, setZeilen] = useState<FensterEingabe[] | null>(null);
  const [meldung, setMeldung] = useState<string | null>(null);
  const [fehler, setFehler] = useState<string | null>(null);

  // Der gespeicherte Plan füllt das Formular **einmal**, sobald er da ist.
  // Danach gehört der Zustand dem Formular: ein `useState`-Initialwert aus
  // einer Abfrage, die beim ersten Lauf noch `undefined` ist, bliebe sonst
  // für immer leer.
  useEffect(() => {
    if (plan.data && zeilen === null) {
      setZeilen(
        plan.data.fenster.map((f) => ({
          von: f.von,
          bis: f.bis,
          temperatur: f.temperatur === null ? "" : String(f.temperatur),
        })),
      );
    }
  }, [plan.data, zeilen]);

  const darfAendern = darfStammdatenAendern(user);
  const aktuell = zeilen ?? [];

  const mut = useMutation({
    mutationFn: (werte: FensterEingabe[]) => setzeTagesplan(roomId, werte),
    onSuccess: (gespeichert) => {
      setFehler(null);
      setMeldung(
        gespeichert.fenster.length === 0
          ? "Tagesplan gelöscht — es gilt wieder die Betriebszeit."
          : "Tagesplan gespeichert. Die Engine übernimmt ihn beim nächsten Durchlauf (≤ 60 s).",
      );
      setZeilen(
        gespeichert.fenster.map((f) => ({
          von: f.von,
          bis: f.bis,
          temperatur: f.temperatur === null ? "" : String(f.temperatur),
        })),
      );
      // Dieselben Schlüssel wie beim Betriebszeit-Formular, aus demselben
      // Grund (Befund vom 25.10.2026): ein Schlüssel, der auf nichts zeigt,
      // wirft keinen Fehler — er tut nichts, und die Anzeige bleibt alt.
      void queryClient.invalidateQueries({ queryKey: TAGESPLAN_KEY(roomId) });
      void queryClient.invalidateQueries({ queryKey: ["room", roomId] });
      void queryClient.invalidateQueries({ queryKey: ["room", roomId, "engine-trace"] });
    },
    onError: (e: unknown) => {
      setMeldung(null);
      setFehler(fehlerText(e));
    },
  });

  function speichern() {
    const befund = pruefeEingabe(aktuell);
    if (befund !== null) {
      setMeldung(null);
      setFehler(befund);
      return;
    }
    setFehler(null);
    mut.mutate(aktuell);
  }

  return (
    <section
      className="bg-surface rounded-lg border border-border p-4"
      data-testid="tagesplan-form"
    >
      <header className="mb-3">
        <h3 className="text-sm font-medium text-text-primary">Tagesplan</h3>
        <p className="text-text-tertiary text-xs">
          Mehrere Zeitfenster am Tag, je Fenster ein eigener Sollwert. Außerhalb
          aller Fenster gilt der Absenkwert des Raumtyps. <strong>Solange hier
          ein Fenster steht, bestimmt der Tagesplan die Zeiten</strong> — die
          Betriebszeit darüber wirkt dann nicht.
        </p>
      </header>

      {plan.isLoading ? (
        <p className="text-text-tertiary text-xs">Wird geladen …</p>
      ) : (
        <>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-text-secondary text-left text-xs">
                <th className="pb-1 font-normal">von</th>
                <th className="pb-1 font-normal">bis</th>
                <th className="pb-1 font-normal">Soll °C</th>
                <th className="pb-1" />
              </tr>
            </thead>
            <tbody data-testid="tagesplan-zeilen">
              {aktuell.map((zeile, index) => (
                <tr key={index}>
                  <td className="py-1 pr-2">
                    <Input
                      type="text"
                      inputMode="numeric"
                      placeholder="06:00"
                      value={zeile.von}
                      onChange={(e) =>
                        setZeilen(
                          aktuell.map((z, i) =>
                            i === index ? { ...z, von: e.target.value } : z,
                          ),
                        )
                      }
                      disabled={!darfAendern || mut.isPending}
                      aria-label={`Fenster ${index + 1} von`}
                      data-testid={`tagesplan-von-${index}`}
                      className="w-24"
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <Input
                      type="text"
                      inputMode="numeric"
                      placeholder="08:00"
                      value={zeile.bis}
                      onChange={(e) =>
                        setZeilen(
                          aktuell.map((z, i) =>
                            i === index ? { ...z, bis: e.target.value } : z,
                          ),
                        )
                      }
                      disabled={!darfAendern || mut.isPending}
                      aria-label={`Fenster ${index + 1} bis`}
                      data-testid={`tagesplan-bis-${index}`}
                      className="w-24"
                    />
                  </td>
                  <td className="py-1 pr-2">
                    <Input
                      type="text"
                      inputMode="decimal"
                      placeholder="22.0"
                      value={zeile.temperatur}
                      onChange={(e) =>
                        setZeilen(
                          aktuell.map((z, i) =>
                            i === index ? { ...z, temperatur: e.target.value } : z,
                          ),
                        )
                      }
                      disabled={!darfAendern || mut.isPending}
                      aria-label={`Fenster ${index + 1} Sollwert`}
                      data-testid={`tagesplan-temperatur-${index}`}
                      className="w-20"
                    />
                  </td>
                  <td className="py-1">
                    {darfAendern ? (
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() => setZeilen(aktuell.filter((_, i) => i !== index))}
                        disabled={mut.isPending}
                        aria-label={`Fenster ${index + 1} entfernen`}
                        data-testid={`tagesplan-entfernen-${index}`}
                      >
                        Entfernen
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {aktuell.length === 0 ? (
            <p className="text-text-tertiary py-2 text-xs" data-testid="tagesplan-leer">
              Kein Tagesplan. Es gilt die Betriebszeit darüber.
            </p>
          ) : (
            <Tagesleiste zeilen={aktuell} />
          )}

          {darfAendern ? (
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <Button
                type="button"
                variant="secondary"
                onClick={() => setZeilen([...aktuell, neueZeile(aktuell[aktuell.length - 1])])}
                disabled={mut.isPending || aktuell.length >= MAX_FENSTER}
                data-testid="tagesplan-hinzufuegen"
              >
                Fenster hinzufügen
              </Button>
              <Button
                type="button"
                variant="primary"
                onClick={speichern}
                disabled={mut.isPending}
                data-testid="tagesplan-speichern"
              >
                Speichern
              </Button>
              {aktuell.length > 0 ? (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => {
                    setZeilen([]);
                    mut.mutate([]);
                  }}
                  disabled={mut.isPending}
                  data-testid="tagesplan-loeschen"
                >
                  Plan löschen
                </Button>
              ) : null}
            </div>
          ) : (
            <p className="text-text-tertiary mt-3 text-xs">
              Änderungen sind Administratoren vorbehalten.
            </p>
          )}

          <p className="text-text-tertiary mt-2 text-xs">
            HH:MM in Ortszeit. „24:00" ist erlaubt und bedeutet Mitternacht. Ein
            Fenster über Mitternacht gibt es nicht — dafür zwei Zeilen,
            23:00–24:00 und 00:00–01:00.
          </p>
        </>
      )}

      {meldung !== null ? (
        <p
          className="border-success bg-success-soft text-success mt-3 flex items-start gap-2 rounded-md border px-3 py-2 text-sm"
          role="status"
          data-testid="tagesplan-meldung"
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
          data-testid="tagesplan-fehler"
        >
          <span className="material-symbols-outlined shrink-0" aria-hidden style={{ fontSize: 18 }}>
            error
          </span>
          <span>
            Tagesplan <strong>nicht</strong> gespeichert: {fehler}
          </span>
        </p>
      ) : null}
    </section>
  );
}
