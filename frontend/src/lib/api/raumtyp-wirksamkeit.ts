/**
 * Wirksamkeit der Raumtyp-Sollwerte (Sprint 24d).
 *
 * Zod-Spiegel zu ``WirksamkeitRaumtyp`` und ``SollwertUebernahme`` in
 * ``backend/src/heizung/schemas/room_type.py`` (§5.63).
 *
 * **Warum es diese Abfrage überhaupt gibt.** Die Raumtyp-Seite zeigt drei
 * Temperaturen, und bis zum 24.10.2026 wirkte keine davon: die
 * Auflösungskette `ROOM > ROOM_TYPE > GLOBAL` liest `rule_config`-Zeilen,
 * die Spalten des Raumtyps stehen darunter. Diese Abfrage sagt je Feld,
 * **welcher Wert gilt und woher er kommt** — damit die Seite eine Aussage
 * machen kann statt einer Zahl ohne Geltung.
 *
 * Die Zahlen kommen aus der Datenbank des Hauses, nicht aus einer Tabelle
 * in der Doku: eine Tabelle wäre eine Momentaufnahme von dem Tag, an dem
 * jemand sie geschrieben hat (§5.79).
 *
 * Der Pfad trägt ``/api/v1`` selbst — ``apiClient`` setzt kein Präfix.
 */

import { z } from "zod";

import { apiClient } from "./client";

/** Woher der wirksame Wert kommt. Dieselben Marken wie im Engine-Trace. */
export type SollwertQuelle = "zimmer" | "raumtyp" | "global" | "raumtyp_vorgabe";

const feldSchema = z.object({
  feld: z.string(),
  angezeigt: z.coerce.number(),
  // ``null`` heisst „keine Zeile setzt das Feld"; dann steht in
  // ``angezeigt`` der Wert, der gilt, und ``quelle`` sagt es.
  wirksam: z.coerce.number().nullable(),
  quelle: z.string(),
});

const raumtypSchema = z.object({
  room_type_id: z.number(),
  name: z.string(),
  is_bookable: z.boolean(),
  zeile_vorhanden: z.boolean(),
  wuerde_sich_aendern: z.boolean(),
  felder: z.array(feldSchema),
});

export type WirksamkeitFeld = z.infer<typeof feldSchema>;
export type WirksamkeitRaumtyp = z.infer<typeof raumtypSchema>;

const uebernahmeSchema = z.object({
  room_type_id: z.number(),
  ergebnis: z.string(),
  t_occupied: z.coerce.number(),
  t_vacant: z.coerce.number(),
  t_night: z.coerce.number(),
});

export type SollwertUebernahme = z.infer<typeof uebernahmeSchema>;

/** Deutsche Namen der drei Felder, wie die Seite sie zeigt. */
export const FELD_LABEL: Record<string, string> = {
  default_t_occupied: "Belegt",
  default_t_vacant: "Frei",
  default_t_night: "Nacht",
};

/** Dieselben Namen für einen Allgemeinbereich. */
export const FELD_LABEL_BEREICH: Record<string, string> = {
  default_t_occupied: "Belegt (ungenutzt)",
  default_t_vacant: "Betrieb",
  default_t_night: "Absenkung",
};

export const QUELLE_LABEL: Record<string, string> = {
  zimmer: "Zimmer",
  raumtyp: "Raumtyp",
  global: "hausweit",
  raumtyp_vorgabe: "Raumtyp (Vorgabe)",
};

export async function fetchWirksamkeit(): Promise<WirksamkeitRaumtyp[]> {
  const data = await apiClient.get<unknown>("/api/v1/room-types/sollwert-wirksamkeit");
  return z.array(raumtypSchema).parse(data);
}

export async function sollwerteUebernehmen(
  roomTypeId: number,
): Promise<SollwertUebernahme> {
  const data = await apiClient.post<unknown>(
    `/api/v1/room-types/${roomTypeId}/sollwerte-uebernehmen`,
    {},
  );
  return uebernahmeSchema.parse(data);
}
