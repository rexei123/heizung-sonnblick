/**
 * TanStack-Query-Hooks fuer Devices und SensorReadings.
 *
 * Konvention:
 * - Query-Keys: ["devices", { filters }] / ["device", id] / ["sensor-readings", deviceId, opts]
 * - refetchInterval fuer Live-Update auf der Detail-Seite (30 s)
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { devicesApi } from "./devices";
import type {
  Device,
  DeviceCreate,
  DeviceListQuery,
  DeviceUpdate,
  SensorReading,
  SensorReadingsQuery,
} from "./types";

const KEYS = {
  devicesAll: ["devices"] as const,
  devicesList: (q: DeviceListQuery) => ["devices", q] as const,
  device: (id: number) => ["device", id] as const,
  sensorReadings: (id: number, q: SensorReadingsQuery) =>
    ["sensor-readings", id, q] as const,
};

/** Liste aller Geraete. Aktualisiert sich beim Tab-Focus. */
export function useDevices(q: DeviceListQuery = {}): UseQueryResult<Device[]> {
  return useQuery({
    queryKey: KEYS.devicesList(q),
    queryFn: () => devicesApi.list(q),
  });
}

/** Einzelnes Geraet, refetch alle 30 s fuer near-realtime auf Detail-Seite. */
export function useDevice(
  id: number | null,
  opts: { refetchInterval?: number } = {},
): UseQueryResult<Device> {
  return useQuery({
    queryKey: KEYS.device(id ?? -1),
    queryFn: () => devicesApi.get(id!),
    enabled: id !== null && id > 0,
    refetchInterval: opts.refetchInterval ?? 30_000,
  });
}

/** Zeitreihen-Readings, refetch alle 30 s. */
export function useSensorReadings(
  deviceId: number | null,
  q: SensorReadingsQuery = {},
  opts: { refetchInterval?: number } = {},
): UseQueryResult<SensorReading[]> {
  return useQuery({
    queryKey: KEYS.sensorReadings(deviceId ?? -1, q),
    queryFn: () => devicesApi.sensorReadings(deviceId!, q),
    enabled: deviceId !== null && deviceId > 0,
    refetchInterval: opts.refetchInterval ?? 30_000,
  });
}

/** Device anlegen. Invalidiert die devices-Liste danach. */
export function useCreateDevice(): UseMutationResult<Device, Error, DeviceCreate> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: DeviceCreate) => devicesApi.create(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.devicesAll });
    },
  });
}

/** Device updaten. Invalidiert das einzelne Device + die Liste. */
export function useUpdateDevice(
  id: number,
): UseMutationResult<Device, Error, DeviceUpdate> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: DeviceUpdate) => devicesApi.update(id, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEYS.device(id) });
      qc.invalidateQueries({ queryKey: KEYS.devicesAll });
    },
  });
}
