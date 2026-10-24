/**
 * Betriebszeit eines Allgemeinbereichs (Sprint 24d).
 *
 * Der Pfad trägt ``/api/v1`` selbst — ``apiClient`` setzt kein Präfix.
 *
 * Gesendet werden **Strings**, nicht Uhrzeiten: „24:00" ist erlaubt und
 * wäre als `time` nicht darstellbar. Das Backend bildet sie auf 00:00 ab
 * (`services/betriebszeit.parse_uhrzeit`).
 *
 * Beide Felder `null` löscht die Betriebszeit. Eine **halbe** Angabe
 * weist der Server mit 422 ab — ein Fenster mit einem Ende und ohne
 * Anfang ist keins, und es würde stillschweigend nicht wirken.
 */

import { apiClient } from "./client";
import type { Room } from "./types";

export async function setzeBetriebszeit(
  roomId: number,
  werte: { von: string | null; bis: string | null },
): Promise<Room> {
  return apiClient.patch<Room>(`/api/v1/rooms/${roomId}/betriebszeit`, {
    von: werte.von === "" ? null : werte.von,
    bis: werte.bis === "" ? null : werte.bis,
  });
}
