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

export const devicesApi = {
  list: (q: DeviceListQuery = {}): Promise<Device[]> =>
    apiClient.get<Device[]>(`${BASE}${queryString(q)}`),

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
