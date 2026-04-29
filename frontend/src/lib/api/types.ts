/**
 * Domain-Typen aus dem Backend.
 *
 * Spiegeln direkt die Pydantic-Schemas in
 *   backend/src/heizung/schemas/device.py
 *   backend/src/heizung/schemas/sensor_reading.py
 *
 * Sollten Backend und Frontend auseinanderlaufen, generieren wir spaeter
 * via openapi-typescript automatisch.
 */

export type DeviceKind = "thermostat" | "sensor";

export type DeviceVendor = "mclimate" | "milesight" | "manual";

export interface Device {
  id: number;
  dev_eui: string;
  app_eui: string | null;
  kind: DeviceKind;
  vendor: DeviceVendor;
  model: string;
  label: string | null;
  heating_zone_id: number | null;
  is_active: boolean;
  last_seen_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface DeviceCreate {
  dev_eui: string;
  app_eui?: string | null;
  kind: DeviceKind;
  vendor: DeviceVendor;
  model: string;
  label?: string | null;
  heating_zone_id?: number | null;
  is_active?: boolean;
}

export interface DeviceUpdate {
  app_eui?: string | null;
  kind?: DeviceKind;
  vendor?: DeviceVendor;
  model?: string;
  label?: string | null;
  heating_zone_id?: number | null;
  is_active?: boolean;
}

export interface SensorReading {
  time: string;
  fcnt: number | null;
  temperature: number | null;
  setpoint: number | null;
  valve_position: number | null;
  battery_percent: number | null;
  rssi_dbm: number | null;
  snr_db: number | null;
}

export interface SensorReadingsQuery {
  from?: string;
  to?: string;
  limit?: number;
}

export interface DeviceListQuery {
  is_active?: boolean;
  vendor?: DeviceVendor;
  limit?: number;
  offset?: number;
}

/**
 * API-Fehler-Schema (FastAPI default: { detail: string | object[] }).
 */
export interface ApiError {
  status: number;
  detail: string | unknown;
}
