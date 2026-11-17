/**
 * Relais-Verlauf (17.11.2026): Einschaltdauer, Ist/Soll, Energie.
 *
 * Zod-Spiegel zu ``RelaisVerlaufRead`` in
 * ``backend/src/heizung/api/v1/relays.py`` (§5.63).
 *
 * **Eigene Datei und nicht in ``relays.ts``.** Dort stehen der Stand und
 * die fünf Handgriffe; hier steht eine Zeitreihe mit zwei Auflösungen.
 * Der Schnitt ist nicht Ordnung um ihrer selbst willen: die
 * Verlaufs-Abfrage hängt am Zeitraum und wird bei jedem Umschalten neu
 * geholt, der Stand nicht.
 *
 * **Alles ist Lesen.** Kein Weg hier verändert etwas, und deshalb reicht
 * `require_user` im Backend — die Zahlen darf jeder Angemeldete sehen.
 */

import { z } from "zod";

import { apiClient } from "./client";
import { zahlOderNull } from "./zahlen";

/** Die drei Fenster. Die Reihenfolge ist die der Knöpfe. */
export const RELAIS_BEREICHE = ["24h", "7d", "30d"] as const;

export type RelaisBereich = (typeof RELAIS_BEREICHE)[number];

export const BEREICH_TEXT: Record<RelaisBereich, string> = {
  "24h": "24 Stunden",
  "7d": "7 Tage",
  "30d": "30 Tage",
};

/**
 * Ein `Decimal` der API — es kommt als **String** (`"20.00"`), wenn das
 * Feld keinen `field_serializer` hat.
 *
 * Das ist nicht Vorsicht ohne Anlass: genau diese Lücke hat am
 * 07.10.2026 die Geräteliste abgeschossen (`a.toFixed is not a
 * function`, siehe `zahlen.ts`). Hier wird daraus eine Zahl, bevor sie
 * jemand formatiert.
 */
const dezimal = z
  .union([z.number(), z.string()])
  .nullable()
  .transform(zahlOderNull);

export const verlaufStundeSchema = z.object({
  /** Beginn der Stunde, UTC-ISO. */
  t: z.string(),
  /**
   * Einschaltanteil in Prozent. `null` heißt „in dieser Stunde keine
   * Meldung" — nicht 0. Eine 0 wäre eine Aussage über ein Gerät, von
   * dem wir nichts gehört haben.
   */
  ein_prozent: z.number().nullable(),
  ein_minuten: z.number().nullable(),
  /** Wie viel der Stunde überhaupt durch Meldungen belegt ist. */
  erfasste_minuten: z.number(),
  einschaltungen: z.number(),
  /** Verbrauch in Wh. `null` heißt „der Zähler sagt dazu nichts". */
  energie_wh: z.number().nullable(),
  ist_mittel: dezimal,
  ist_min: dezimal,
  ist_max: dezimal,
  soll: dezimal,
});

export const verlaufTagSchema = z.object({
  /** Kalendertag in **Ortszeit** des Hotels, `YYYY-MM-DD`. */
  tag: z.string(),
  ein_minuten: z.number(),
  ein_prozent: z.number().nullable(),
  erfasste_minuten: z.number(),
  einschaltungen: z.number(),
  energie_wh: z.number().nullable(),
  ist_mittel: dezimal,
  ist_min: dezimal,
  ist_max: dezimal,
  soll_mittel: dezimal,
});

export const relaisVerlaufSchema = z.object({
  device_id: z.number(),
  zone_id: z.number(),
  zone_name: z.string(),
  zimmer: z.string(),
  /** Die Etiketten **aller** Relais der Zone — die Zahlen gelten für die Zone. */
  relais: z.array(z.string()),
  range: z.enum(RELAIS_BEREICHE),
  range_from: z.string(),
  range_to: z.string(),
  timezone: z.string(),
  stunden: z.array(verlaufStundeSchema),
  tage: z.array(verlaufTagSchema),
  ein_minuten_gesamt: z.number(),
  anteil_gesamt: z.number().nullable(),
  einschaltungen_gesamt: z.number(),
  energie_wh_gesamt: z.number().nullable(),
  /**
   * Rücksprünge des Energiezählers (Überlauf, `0x26`, Gerätetausch).
   * **Nicht** vom Verbrauch abgezogen, sondern gezählt: eine kWh-Zahl,
   * die kleiner ist als erwartet, muss erklärbar sein.
   */
  ruecksprunge: z.number(),
});

export type RelaisVerlauf = z.infer<typeof relaisVerlaufSchema>;
export type VerlaufStunde = z.infer<typeof verlaufStundeSchema>;
export type VerlaufTag = z.infer<typeof verlaufTagSchema>;

export async function fetchRelaisVerlauf(
  deviceId: number,
  bereich: RelaisBereich,
): Promise<RelaisVerlauf> {
  const daten = await apiClient.get<unknown>(
    `/api/v1/devices/${deviceId}/relay/history?range=${bereich}`,
  );
  return relaisVerlaufSchema.parse(daten);
}

/**
 * Der Pfad der CSV-Datei — **kein** `fetch`.
 *
 * Die Datei geht als normaler Link an den Browser: der schickt das
 * Sitzungs-Cookie mit (`same-origin`), kennt den Dateinamen aus
 * `Content-Disposition` und legt sie in die Downloads. Ein `fetch` mit
 * Blob und `URL.createObjectURL` wäre derselbe Weg mit drei weiteren
 * Fehlerquellen und ohne den Namen.
 */
export function relaisVerlaufCsvPfad(
  deviceId: number,
  bereich: RelaisBereich,
): string {
  return `/api/v1/devices/${deviceId}/relay/history.csv?range=${bereich}`;
}
