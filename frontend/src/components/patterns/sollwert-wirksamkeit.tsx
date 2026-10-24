"use client";

/**
 * Was von den Sollwerten dieses Raumtyps wirklich gilt (Sprint 24d).
 *
 * **Wozu.** Auf der Raumtyp-Seite standen drei Temperaturen, die nicht
 * wirkten — die hausweite `rule_config`-Zeile steht in der Kette über den
 * Spalten des Raumtyps. Diese Karte stellt die Zahl neben ihre Geltung:
 * angezeigt, wirksam, und woher der wirksame Wert kommt.
 *
 * **Für einen Allgemeinbereich ist das nach diesem Sprint eine
 * Bestätigung** — Speichern schreibt die Zeile, also stimmt beides. Für
 * ein Gästezimmer ist es eine Frage: dort entsteht die Zeile bewusst
 * nicht beim Speichern, weil eine Änderung an der Beschreibung sonst
 * nebenbei die Sollwerte von zwanzig Zimmern umstellen würde. Der Knopf
 * ist der ausdrückliche Weg, und er steht erst da, wenn es etwas zu
 * entscheiden gibt.
 *
 * **Der Knopf ist Bedienung, nicht Sicherheit.** `POST
 * /room-types/{id}/sollwerte-uebernehmen` ist `require_admin`; wer den Weg
 * direkt aufruft, bekommt 403, auch ohne den Knopf gesehen zu haben
 * (§5.30).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/auth-context";
import {
  FELD_LABEL,
  FELD_LABEL_BEREICH,
  QUELLE_LABEL,
  fetchWirksamkeit,
  sollwerteUebernehmen,
} from "@/lib/api/raumtyp-wirksamkeit";
import { darfStammdatenAendern } from "@/lib/auth/rechte";

function zahl(v: number | null): string {
  return v === null ? "—" : v.toLocaleString("de-AT", { minimumFractionDigits: 1 });
}

export function SollwertWirksamkeit({ roomTypeId }: { roomTypeId: number }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [meldung, setMeldung] = useState<string | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["sollwert-wirksamkeit"],
    queryFn: fetchWirksamkeit,
  });

  const mut = useMutation({
    mutationFn: () => sollwerteUebernehmen(roomTypeId),
    onSuccess: (ergebnis) => {
      setMeldung(
        ergebnis.ergebnis === "unveraendert"
          ? "Die Werte waren schon wirksam."
          : "Die Werte dieses Raumtyps sind jetzt wirksam.",
      );
      void queryClient.invalidateQueries({ queryKey: ["sollwert-wirksamkeit"] });
    },
    onError: (fehler: Error) => setMeldung(`Übernehmen fehlgeschlagen: ${fehler.message}`),
  });

  if (isLoading) {
    return <p className="text-text-tertiary text-sm">Wirksamkeit wird geladen …</p>;
  }
  if (isError || data === undefined) {
    return (
      <p className="text-error text-sm">
        Die Wirksamkeit der Sollwerte ist nicht abrufbar.
      </p>
    );
  }

  const befund = data.find((b) => b.room_type_id === roomTypeId);
  if (befund === undefined) {
    return null;
  }

  const labels = befund.is_bookable ? FELD_LABEL : FELD_LABEL_BEREICH;
  // Bei einem Bereich ist „Belegt" ungenutzt — es steht gleichgezogen in
  // der Spalte und wird nie gelesen. Es in der Tabelle zu zeigen wäre eine
  // Zeile, die zum Nachdenken einlädt, wo es nichts zu entscheiden gibt.
  const felder = befund.is_bookable
    ? befund.felder
    : befund.felder.filter((f) => f.feld !== "default_t_occupied");

  return (
    <section
      className="bg-surface rounded-lg border border-border p-4 mb-4"
      data-testid="sollwert-wirksamkeit"
      data-wuerde-sich-aendern={befund.wuerde_sich_aendern ? "true" : "false"}
    >
      <header className="mb-3">
        <h3 className="text-sm font-medium text-text-primary">Was davon gilt</h3>
        <p className="text-text-tertiary text-xs">
          Die Regelung löst Sollwerte in der Reihenfolge Zimmer → Raumtyp →
          hausweit auf.
        </p>
      </header>

      <table className="w-full text-sm">
        <thead>
          <tr className="text-text-tertiary text-xs">
            <th scope="col" className="text-left font-medium pb-1">
              Feld
            </th>
            <th scope="col" className="text-right font-medium pb-1">
              hier eingetragen
            </th>
            <th scope="col" className="text-right font-medium pb-1">
              wirksam
            </th>
            <th scope="col" className="text-left font-medium pb-1 pl-3">
              Quelle
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {felder.map((f) => {
            const abweichend = f.wirksam !== f.angezeigt;
            return (
              <tr key={f.feld} data-testid="wirksamkeit-zeile" data-feld={f.feld}>
                <td className="py-1 text-text-primary">{labels[f.feld] ?? f.feld}</td>
                <td className="py-1 text-right tabular-nums text-text-secondary">
                  {zahl(f.angezeigt)} °C
                </td>
                <td
                  className={`py-1 text-right tabular-nums ${
                    abweichend ? "text-warning font-medium" : "text-text-primary"
                  }`}
                  data-abweichend={abweichend ? "true" : "false"}
                >
                  {zahl(f.wirksam)} °C
                </td>
                <td className="py-1 pl-3 text-text-tertiary text-xs">
                  {QUELLE_LABEL[f.quelle] ?? f.quelle}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {befund.wuerde_sich_aendern ? (
        <div className="mt-3 border-t border-border pt-3">
          <p className="text-text-secondary text-xs" data-testid="wirksamkeit-hinweis">
            {befund.is_bookable
              ? "Die Werte hier gelten noch nicht — es wirkt der hausweite Wert. Das Übernehmen verschiebt den Sollwert aller Zimmer dieses Typs."
              : "Die Werte hier gelten noch nicht. Einmal speichern genügt."}
          </p>
          {darfStammdatenAendern(user) ? (
            <Button
              type="button"
              variant="secondary"
              className="mt-2"
              onClick={() => mut.mutate()}
              disabled={mut.isPending}
              data-testid="wirksamkeit-uebernehmen"
            >
              Werte wirksam machen
            </Button>
          ) : null}
        </div>
      ) : null}

      {meldung !== null ? (
        <p className="text-text-secondary mt-3 text-xs" data-testid="wirksamkeit-meldung">
          {meldung}
        </p>
      ) : null}
    </section>
  );
}
