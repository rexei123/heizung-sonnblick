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

// ---------------------------------------------------------------------------
// Sprint 8 Stammdaten — Spiegel zu backend/src/heizung/schemas/*.py
// ---------------------------------------------------------------------------

/**
 * Raumtyp (Sprint 8.4). Hotelzimmer oder andere Einheiten (Tagungsraum, etc.).
 * Default-Sollwerte werden in der Engine als Layer-1-Basis verwendet.
 */
export interface RoomType {
  id: number;
  name: string;
  description: string | null;
  is_bookable: boolean;
  default_t_occupied: number;
  default_t_vacant: number;
  default_t_night: number;
  max_temp_celsius: number | null;
  min_temp_celsius: number | null;
  treat_unoccupied_as_vacant_after_hours: number | null;
  created_at: string;
  updated_at: string;
}

export interface RoomTypeCreate {
  name: string;
  description?: string | null;
  is_bookable?: boolean;
  default_t_occupied?: number;
  default_t_vacant?: number;
  default_t_night?: number;
  max_temp_celsius?: number | null;
  min_temp_celsius?: number | null;
  treat_unoccupied_as_vacant_after_hours?: number | null;
}

export interface RoomTypeUpdate {
  name?: string;
  description?: string | null;
  is_bookable?: boolean;
  default_t_occupied?: number;
  default_t_vacant?: number;
  default_t_night?: number;
  max_temp_celsius?: number | null;
  min_temp_celsius?: number | null;
  treat_unoccupied_as_vacant_after_hours?: number | null;
}

export interface RoomTypeListQuery {
  is_bookable?: boolean;
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------------------
// Zimmer (Sprint 8.4)
// ---------------------------------------------------------------------------

export type Orientation =
  | "N"
  | "NE"
  | "E"
  | "SE"
  | "S"
  | "SW"
  | "W"
  | "NW";

export type RoomStatus =
  | "vacant"
  | "occupied"
  | "reserved"
  | "cleaning"
  | "blocked";

export interface Room {
  id: number;
  number: string;
  display_name: string | null;
  room_type_id: number;
  floor: number | null;
  orientation: Orientation | null;
  status: RoomStatus;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface RoomCreate {
  number: string;
  display_name?: string | null;
  room_type_id: number;
  floor?: number | null;
  orientation?: Orientation | null;
  notes?: string | null;
}

export interface RoomUpdate {
  number?: string;
  display_name?: string | null;
  room_type_id?: number;
  floor?: number | null;
  orientation?: Orientation | null;
  status?: RoomStatus;
  notes?: string | null;
}

export interface RoomListQuery {
  room_type_id?: number;
  status?: RoomStatus;
  floor?: number;
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------------------
// Heizzonen (Sprint 8.4)
// ---------------------------------------------------------------------------

export type HeatingZoneKind =
  | "bedroom"
  | "bathroom"
  | "living"
  | "hallway"
  | "other";

export interface HeatingZone {
  id: number;
  room_id: number;
  kind: HeatingZoneKind;
  name: string;
  is_towel_warmer: boolean;
  created_at: string;
  updated_at: string;
}

export interface HeatingZoneCreate {
  kind: HeatingZoneKind;
  name: string;
  is_towel_warmer?: boolean;
}

export interface HeatingZoneUpdate {
  kind?: HeatingZoneKind;
  name?: string;
  is_towel_warmer?: boolean;
}

// ---------------------------------------------------------------------------
// Belegungen (Sprint 8.5)
// ---------------------------------------------------------------------------

export type OccupancySource = "manual" | "pms";

export interface Occupancy {
  id: number;
  room_id: number;
  check_in: string;
  check_out: string;
  guest_count: number | null;
  source: OccupancySource;
  external_id: string | null;
  is_active: boolean;
  cancelled_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface OccupancyCreate {
  room_id: number;
  check_in: string;
  check_out: string;
  guest_count?: number | null;
  source?: OccupancySource;
  external_id?: string | null;
}

export interface OccupancyListQuery {
  from?: string;
  to?: string;
  room_id?: number;
  active?: boolean;
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------------------
// global_config (Sprint 8.6 — Singleton)
// ---------------------------------------------------------------------------

export interface GlobalConfig {
  id: number;
  hotel_name: string;
  timezone: string;
  default_checkin_time: string;
  default_checkout_time: string;
  summer_mode_active: boolean;
  summer_mode_starts_on: string | null;
  summer_mode_ends_on: string | null;
  alert_email: string | null;
  alert_device_offline_minutes: number;
  alert_battery_warn_percent: number;
  created_at: string;
  updated_at: string;
}

export interface GlobalConfigUpdate {
  hotel_name?: string;
  timezone?: string;
  default_checkin_time?: string;
  default_checkout_time?: string;
  summer_mode_active?: boolean;
  summer_mode_starts_on?: string | null;
  summer_mode_ends_on?: string | null;
  alert_email?: string | null;
  alert_device_offline_minutes?: number;
  alert_battery_warn_percent?: number;
}
