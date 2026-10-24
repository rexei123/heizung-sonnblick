/**
 * Wer nimmt den Hausstandard wirklich? (Sprint 24d)
 *
 * Zod-Spiegel zu ``HausstandardNutzung`` in
 * ``backend/src/heizung/schemas/rule_config.py`` (§5.63).
 *
 * **Wozu.** Ein hausweiter Wert sieht aus wie eine Einstellung für das
 * ganze Haus und ist in Wirklichkeit eine Vorgabe **für den Rest** — für
 * alles, was nichts eigenes sagt. Ohne diese Zahlen ist nicht zu sehen, ob
 * eine Änderung dort 45 Zimmer bewegt oder keines.
 *
 * Der Pfad trägt ``/api/v1`` selbst — ``apiClient`` setzt kein Präfix.
 */

import { z } from "zod";

import { apiClient } from "./client";

const nutzungSchema = z.object({
  feld: z.string(),
  gesetzt: z.boolean(),
  raumtypen_nutzen: z.number(),
  raumtypen_eigen: z.number(),
  zimmer_eigen: z.number(),
});

export type HausstandardNutzung = z.infer<typeof nutzungSchema>;

export async function fetchHausstandardNutzung(): Promise<HausstandardNutzung[]> {
  const data = await apiClient.get<unknown>("/api/v1/rule-configs/global/nutzung");
  return z.array(nutzungSchema).parse(data);
}
