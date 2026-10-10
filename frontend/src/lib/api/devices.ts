/**
 * API-Funktionen fuer Devices + zugehoerige Zeitreihen.
 */

import { alleSeiten } from "./alle-seiten";
import { apiClient, queryString } from "./client";
import { zahlenfelderNormalisieren } from "./zahlen";
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
 * Zahlenfelder von ``Device``, die aus einem Backend-``Decimal`` kommen.
 *
 * Sie werden an der Grenze normalisiert, weil ein ``Decimal`` ohne
 * ``field_serializer`` als JSON-String ankommt und das Frontend damit
 * rechnet. Am 07.10.2026 hat das ``/devices`` abgeschossen
 * (``TypeError: a.toFixed is not a function``); die Ursache ist im Backend
 * behoben, das hier ist die zweite Linie. Begründung in ``zahlen.ts``.
 *
 * **Wer ein Zahlenfeld zu ``Device`` hinzufügt, trägt es hier ein.** Das ist
 * dieselbe Pflicht wie der Serializer im Backend — und sie ist bewusst
 * doppelt: zwei Listen, die beide vergessen werden können, sind besser als
 * eine, deren Vergessen die Seite zerstört.
 */
const DEVICE_ZAHLENFELDER = [
  "valve_delta_k",
  // 20e-b: zwei weitere Decimal-Felder derselben Antwort. Dieselbe Falle,
  // dieselbe Liste — wer hier eins vergisst, bekommt im Hinweistext einen
  // String, auf dem `.toFixed()` wirft.
  "valve_referenz_median_c",
  "valve_referenz_delta_k",
  "battery_voltage_median",
  "battery_last_voltage",
] as const;

/** Normalisiert die Zahlenfelder eines Geräts. */
const geraetNormalisieren = (d: Device): Device =>
  zahlenfelderNormalisieren(d, DEVICE_ZAHLENFELDER);

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
  list: async (q: DeviceListQuery = {}): Promise<Device[]> =>
    (
      await alleSeiten(
        (limit, offset) =>
          apiClient.get<Device[]>(`${BASE}${queryString({ ...q, limit, offset })}`),
        "Geräteliste",
      )
    ).map(geraetNormalisieren),

  get: async (id: number): Promise<Device> =>
    geraetNormalisieren(await apiClient.get<Device>(`${BASE}/${id}`)),

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
  getPool: async (): Promise<Device[]> =>
    (await apiClient.get<Device[]>(`${BASE}/pool`)).map(geraetNormalisieren),

  replaceFromPool: (
    id: number,
    payload: DeviceReplaceFromPoolRequest,
  ): Promise<Device> =>
    apiClient.post<Device>(`${BASE}/${id}/replace/from-pool`, payload),

  retireDevice: (id: number, payload: DeviceRetireRequest): Promise<Device> =>
    apiClient.post<Device>(`${BASE}/${id}/retire`, payload),
};
