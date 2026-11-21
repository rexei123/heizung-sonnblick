/**
 * Tagesplan eines Allgemeinbereichs (21.11.2026).
 *
 * Zod-Spiegel zu `TagesplanRead` in
 * `backend/src/heizung/schemas/tagesplan.py` (§5.63), dazu die Prüfung der
 * **Eingabe** — und die ist hier der eigentliche Inhalt.
 *
 * **Warum die Überschneidungsprüfung dreimal existiert** (Zod hier,
 * Pydantic im Schema, `EXCLUDE` an der Tabelle) und das keine
 * §5.53-Verdopplung ist: es sind drei verschiedene Fragen.
 *
 * - Zod beantwortet „ist das, was ich gerade tippe, sinnvoll" — **vor**
 *   dem Speichern, ohne Netz, neben dem Feld.
 * - Pydantic beantwortet „ist das, was angekommen ist, sinnvoll" — denn
 *   der Browser ist keine Zusicherung, und `curl` gibt es auch.
 * - Die Datenbank beantwortet „gilt das auch noch, wenn zwei Leute
 *   gleichzeitig speichern" — und nur sie kann das (§5.60).
 *
 * Eine Regel, drei Reichweiten. Was sie gemeinsam haben, ist die
 * Grenzauslegung: Fenster stoßen aneinander an (`[von, bis)`), sie
 * überschneiden sich nicht. 08:00 gehört zum Fenster, das dort beginnt.
 */

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { z } from "zod";

import { apiClient } from "./client";
import { dezimalFeld as dezimal } from "./zahlen";

/** `HH:MM`, mit `24:00` als erlaubtem Sonderfall — wie bei der Betriebszeit. */
export const UHRZEIT_MUSTER = /^(?:(?:[01]\d|2[0-3]):[0-5]\d|24:00)$/;

/** Dieselbe Grenze wie `MAX_FENSTER` im Backend-Schema. */
export const MAX_FENSTER = 12;

export const MIN_TEMPERATUR = 10;
export const MAX_TEMPERATUR = 30;

export const tagesplanFensterSchema = z.object({
  id: z.number(),
  /** Beginn in Ortszeit, `HH:MM`. */
  von: z.string(),
  /** Ende in Ortszeit, `HH:MM` — `24:00` ist möglich und heißt Mitternacht. */
  bis: z.string(),
  /**
   * Der Sollwert dieses Fensters.
   *
   * `dezimal` und nicht `z.number()`: das Feld ist im Backend ein
   * `Decimal`. Es **steht** im `field_serializer`, kommt also als Zahl —
   * aber genau diese Annahme hat am 18.11.2026 die Relais-Karte gekostet
   * (§5.93). Die zweite Linie kostet hier nichts.
   */
  temperatur: dezimal,
});

export const tagesplanSchema = z.object({
  room_id: z.number(),
  fenster: z.array(tagesplanFensterSchema),
});

export type TagesplanFenster = z.infer<typeof tagesplanFensterSchema>;
export type Tagesplan = z.infer<typeof tagesplanSchema>;

/** Eine Zeile im Formular — alles Text, auch die Temperatur. */
export interface FensterEingabe {
  von: string;
  bis: string;
  temperatur: string;
}

/**
 * `"06:00"` zu `360`, `"24:00"` zu `1440`.
 *
 * Setzt ein geprüftes Muster voraus — die eine Stelle, an der diese
 * Umrechnung im Frontend steht (Spiegel von `heizung.uhrzeit`).
 */
export function minuten(uhrzeit: string): number {
  const [stunde, minute] = uhrzeit.split(":");
  return Number(stunde) * 60 + Number(minute);
}

/** `360` zu `"06:00"`, `1440` zu `"24:00"`. */
export function alsUhrzeit(minutenWert: number): string {
  if (minutenWert >= 24 * 60) return "24:00";
  const stunde = Math.floor(minutenWert / 60);
  const minute = minutenWert % 60;
  return `${String(stunde).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

const eingabeSchema = z.object({
  von: z.string().regex(UHRZEIT_MUSTER, "Beginn muss HH:MM sein, zum Beispiel 06:00."),
  bis: z
    .string()
    .regex(UHRZEIT_MUSTER, "Ende muss HH:MM sein, zum Beispiel 21:00 (24:00 ist erlaubt)."),
  temperatur: z
    .string()
    .transform((wert) => Number(wert.replace(",", ".")))
    .refine((wert) => Number.isFinite(wert), "Die Temperatur muss eine Zahl sein.")
    .refine(
      (wert) => wert >= MIN_TEMPERATUR && wert <= MAX_TEMPERATUR,
      `Die Temperatur muss zwischen ${MIN_TEMPERATUR} und ${MAX_TEMPERATUR} Grad liegen.`,
    ),
});

/**
 * Prüft die Zeilen des Formulars. `null` heißt: in Ordnung.
 *
 * Gibt **einen** Satz zurück und nicht eine Liste: der Kasten unter dem
 * Formular hat Platz für einen, und der erste Fehler ist der, den man
 * beheben muss, bevor der nächste überhaupt noch einer ist.
 *
 * Das Komma wird vorher zum Punkt — wer „22,5" tippt, meint 22.5, und eine
 * Fehlermeldung über ein Dezimaltrennzeichen wäre Erziehung statt Hilfe.
 */
export function pruefeEingabe(zeilen: FensterEingabe[]): string | null {
  if (zeilen.length > MAX_FENSTER) {
    return `Mehr als ${MAX_FENSTER} Fenster sind nicht vorgesehen.`;
  }
  for (const [index, zeile] of zeilen.entries()) {
    const ergebnis = eingabeSchema.safeParse(zeile);
    if (!ergebnis.success) {
      return `Zeile ${index + 1}: ${ergebnis.error.issues[0].message}`;
    }
    if (minuten(zeile.von) >= minuten(zeile.bis)) {
      return (
        `Zeile ${index + 1}: ${zeile.von} liegt nicht vor ${zeile.bis}. Ein Fenster über ` +
        `Mitternacht gibt es nicht — legen Sie zwei an, zum Beispiel 23:00–24:00 und 00:00–01:00.`
      );
    }
  }

  const sortiert = [...zeilen].sort((a, b) => minuten(a.von) - minuten(b.von));
  for (let i = 1; i < sortiert.length; i += 1) {
    if (minuten(sortiert[i].von) < minuten(sortiert[i - 1].bis)) {
      return (
        `Die Fenster überschneiden sich: ${sortiert[i].von} liegt noch in einem Fenster, ` +
        `das erst um ${sortiert[i - 1].bis} endet. Aneinander stoßen dürfen sie — ` +
        `endet eines um ${sortiert[i - 1].bis}, darf das nächste dort beginnen.`
      );
    }
  }
  return null;
}

/** Die Lücken des Tages, in Minuten — das ist die Absenkung. */
export function luecken(zeilen: { von: string; bis: string }[]): [number, number][] {
  if (zeilen.length === 0) return [];
  const sortiert = [...zeilen].sort((a, b) => minuten(a.von) - minuten(b.von));
  const ergebnis: [number, number][] = [];
  let grenze = 0;
  for (const zeile of sortiert) {
    if (minuten(zeile.von) > grenze) ergebnis.push([grenze, minuten(zeile.von)]);
    grenze = Math.max(grenze, minuten(zeile.bis));
  }
  if (grenze < 24 * 60) ergebnis.push([grenze, 24 * 60]);
  return ergebnis;
}

export async function ladeTagesplan(roomId: number): Promise<Tagesplan> {
  return tagesplanSchema.parse(
    await apiClient.get<unknown>(`/api/v1/rooms/${roomId}/tagesplan`),
  );
}

/**
 * Schickt den **ganzen** Plan. Leere Liste löscht ihn.
 *
 * `PUT` und nicht vier Wege für anlegen, ändern, löschen und sortieren:
 * zwei Fenster zu tauschen verletzt sonst bei jedem Einzelschritt die
 * `EXCLUDE`-Bedingung der Tabelle (die Begründung steht im Backend-Schema
 * `TagesplanUpdate`).
 */
export async function setzeTagesplan(
  roomId: number,
  zeilen: FensterEingabe[],
): Promise<Tagesplan> {
  return tagesplanSchema.parse(
    await apiClient.put<unknown>(`/api/v1/rooms/${roomId}/tagesplan`, {
      fenster: zeilen.map((z) => ({
        von: z.von.trim(),
        bis: z.bis.trim(),
        temperatur: Number(z.temperatur.replace(",", ".")),
      })),
    }),
  );
}

export const TAGESPLAN_KEY = (roomId: number) => ["room", roomId, "tagesplan"] as const;

/**
 * Der Plan eines Zimmers.
 *
 * **Auch für Gästezimmer abgefragt** und dort immer leer: der Endpunkt
 * weist ein Gästezimmer beim *Lesen* nicht ab (die Begründung steht dort).
 * Ein `enabled`-Schalter nach Raumtyp wäre eine zweite Stelle, die
 * entscheidet, wer einen Plan haben darf.
 */
export function useTagesplan(roomId: number | null): UseQueryResult<Tagesplan> {
  return useQuery<Tagesplan>({
    queryKey: roomId !== null ? TAGESPLAN_KEY(roomId) : ["room", "tagesplan", "noop"],
    queryFn: () => ladeTagesplan(roomId as number),
    enabled: roomId !== null && roomId > 0,
  });
}
