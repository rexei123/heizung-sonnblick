/**
 * API-Funktionen fuer Devices + zugehoerige Zeitreihen.
 */

import { apiClient, queryString } from "./client";
import type {
  Device,
  DeviceAssignZoneRequest,
  DeviceAssignZoneResponse,
  DeviceCreate,
  DeviceListQuery,
  DeviceReplaceFromPoolRequest,
  DeviceRetireRequest,
  DeviceUpdate,
  HardwareStatusResponse,
  SensorReading,
  SensorReadingsQuery,
} from "./types";

const BASE = "/api/v1/devices";

/**
 * Seitengröße für `list`. **100 — dieselbe Zahl wie der Server-Default**
 * (`api/v1/devices.py:247`).
 *
 * Die naheliegende Wahl wäre eine Seite, die so groß ist, dass sie den
 * ganzen Bestand trägt (etwa 500 bei 104 Vickis) — ein Aufruf, Schleife nur
 * als Absicherung. Verworfen: dann läuft die Schleife im Betrieb **nie**,
 * und eine Paginierung, die nur im Test greift, ist genau die Sorte Code,
 * die beim Wachsen des Bestands das erste Mal scharf wird. Bei 100 sind es
 * heute zwei Aufrufe, und der zweite Durchlauf ist belegt — jeden Tag.
 *
 * Der Preis ist ein zusätzlicher Roundtrip pro Listenaufruf. Die Arbeit je
 * Gerät bleibt dieselbe; der Endpoint lädt pro Zeile ohnehin Override und
 * Reading nach (AE-72 §3, akzeptiertes N+1).
 */
const SEITE = 100;

/**
 * Sicherheitsnetz gegen eine Endlosschleife. Greift nur, wenn das Backend
 * eine volle Seite zurückgibt, obwohl keine weiteren Daten da sind — also
 * bei einem Fehler, nicht bei großen Beständen: 100 × 100 = 10 000 Geräte,
 * das Hundertfache des Bestands.
 *
 * Erreicht die Schleife das Limit, **wirft** sie. Der Aufrufer bekommt
 * einen Fehler zu sehen statt einer Liste, die vollständig aussieht und es
 * nicht ist — das ist der ganze Punkt dieses Fixes.
 */
const MAX_SEITEN = 100;

export const devicesApi = {
  /**
   * **Alle** Geräte, über so viele Seiten wie nötig.
   *
   * Hintergrund (Sprint 20c, B-20c-1): Der Endpoint ist paginiert und
   * liefert ohne `limit` **100** Zeilen (`api/v1/devices.py:247`), sortiert
   * nach `id` aufsteigend. Bei 104 Geräten im Hotel fehlten damit die vier
   * mit den höchsten IDs — und das sind die zuletzt eingepairten, also
   * genau die, die bei der Montage gebraucht werden. Die Liste sah
   * vollständig aus; es gab keine Fehlermeldung und keinen Hinweis.
   *
   * Es gibt hier bewusst **keine** Variante, die eine Seite holt. Eine
   * Funktion, die still abschneidet, wird irgendwann aus Versehen benutzt;
   * wer später echte Paginierung braucht, schreibt eine zweite Funktion mit
   * einem Namen, der das sagt.
   *
   * Die Paginierung ist nur verlässlich, weil die Sortierung
   * **serverseitig** und auf einem eindeutigen Schlüssel liegt
   * (`order_by(Device.id)`, `device_service.py:108`). Bei einer Sortierung
   * nach einem mehrfach vorkommenden Wert — etwa `label` — könnte zwischen
   * zwei Seiten eine Zeile doppelt oder gar nicht erscheinen.
   */
  list: async (q: DeviceListQuery = {}): Promise<Device[]> => {
    const alle: Device[] = [];
    for (let seite = 0; seite < MAX_SEITEN; seite += 1) {
      const teil = await apiClient.get<Device[]>(
        `${BASE}${queryString({ ...q, limit: SEITE, offset: seite * SEITE })}`,
      );
      alle.push(...teil);
      // Kürzere Seite als angefragt = letzte Seite. Bei genau SEITE Treffern
      // folgt noch ein Aufruf, der leer zurückkommt — ein Roundtrip mehr,
      // dafür keine Annahme darüber, wie viele es insgesamt sind.
      if (teil.length < SEITE) return alle;
    }
    throw new Error(
      `Geräteliste nicht vollständig geladen: mehr als ${MAX_SEITEN * SEITE} ` +
        "Einträge oder das Backend liefert dauerhaft volle Seiten. " +
        "Die Liste wird NICHT angezeigt, weil sie unvollständig wäre.",
    );
  },

  get: (id: number): Promise<Device> => apiClient.get<Device>(`${BASE}/${id}`),

  create: (payload: DeviceCreate): Promise<Device> =>
    apiClient.post<Device>(BASE, payload),

  update: (id: number, payload: DeviceUpdate): Promise<Device> =>
    apiClient.patch<Device>(`${BASE}/${id}`, payload),

  assignZone: (
    id: number,
    payload: DeviceAssignZoneRequest,
  ): Promise<DeviceAssignZoneResponse> =>
    apiClient.put<DeviceAssignZoneResponse>(`${BASE}/${id}/heating-zone`, payload),

  detachZone: (id: number): Promise<DeviceAssignZoneResponse> =>
    apiClient.delete<DeviceAssignZoneResponse>(`${BASE}/${id}/heating-zone`),

  sensorReadings: (
    id: number,
    q: SensorReadingsQuery = {},
  ): Promise<SensorReading[]> =>
    apiClient.get<SensorReading[]>(`${BASE}/${id}/sensor-readings${queryString(q)}`),

  hardwareStatus: (id: number): Promise<HardwareStatusResponse> =>
    apiClient.get<HardwareStatusResponse>(`${BASE}/${id}/hardware-status`),

  // Sprint 13b.1 (AE-57): Lifecycle-Endpoints — Pool-Lookup, atomarer
  // Tausch (alte Vicki retired + Pool-Device uebernimmt Zone in einer
  // Transaktion, race-safe via UPDATE-WHERE auf Pool-Cell), Retire
  // ohne Ersatz. Beide Mutationen liefern den aktualisierten alten
  // Device-Row zurueck (mit gesetztem retired_at).
  getPool: (): Promise<Device[]> => apiClient.get<Device[]>(`${BASE}/pool`),

  replaceFromPool: (
    id: number,
    payload: DeviceReplaceFromPoolRequest,
  ): Promise<Device> =>
    apiClient.post<Device>(`${BASE}/${id}/replace/from-pool`, payload),

  retireDevice: (id: number, payload: DeviceRetireRequest): Promise<Device> =>
    apiClient.post<Device>(`${BASE}/${id}/retire`, payload),
};
