/**
 * API-Funktionen fuer Devices + zugehoerige Zeitreihen.
 */

import { apiClient, queryString } from "./client";
import type {
  Device,
  DeviceCreate,
  DeviceListQuery,
  DeviceUpdate,
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

  sensorReadings: (
    id: number,
    q: SensorReadingsQuery = {},
  ): Promise<SensorReading[]> =>
    apiClient.get<SensorReading[]>(`${BASE}/${id}/sensor-readings${queryString(q)}`),
};
