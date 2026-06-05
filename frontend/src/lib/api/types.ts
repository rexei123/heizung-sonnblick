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

/** Device-Health (AE-53): aus Uplink-Latenz + Plausibilitaet abgeleitet. */
export type DeviceHealthState = "healthy" | "degraded" | "silent" | "suspicious";

// Sprint 15d (AE-65): Batterie als orthogonale dritte Health-Achse neben
// DeviceHealthState (offline/implausible). Abgeleitet aus battery_percent +
// alert_battery_warn_percent; Spiegel zu DeviceRead.battery_state.
export type BatteryHealthState = "ok" | "warn" | "kritisch" | "unbekannt";

/** Zone-Health (AE-53): aus den Devices der Zone aggregiert (no_device statt suspicious). */
export type ZoneHealthState = "healthy" | "degraded" | "silent" | "no_device";

// ---------------------------------------------------------------------------
// Sprint 14a (D2/D9): Nested-Zuordnung + Diagnose-Felder im Device-Response.
// Spiegelt schemas/device.py (DeviceZoneRead / DeviceRoomRead /
// DeviceRoomTypeRead / DeviceActiveOverrideRead / DeviceLatestReadingRead).
// ---------------------------------------------------------------------------

export interface DeviceRoomType {
  id: number;
  name: string;
}

export interface DeviceRoom {
  id: number;
  number: string;
  room_type: DeviceRoomType;
}

export interface DeviceZone {
  id: number;
  name: string;
  health_state: ZoneHealthState;
  room: DeviceRoom;
}

/**
 * Aktiver Override fuer die Zone des Geraets (read-only Diagnose, AE-61).
 * `setpoint_celsius` kommt als JSON-Number (Backend-field_serializer
 * Decimal->float). `expires_at` ist non-null (Backend-Model NOT NULL).
 */
export interface DeviceActiveOverride {
  source: OverrideSource;
  setpoint_celsius: number;
  started_at: string;
  expires_at: string;
}

/** Juengster SensorReading-Frame fuer die Diagnose-Kacheln (D5). */
export interface DeviceLatestReading {
  valve_position: number | null;
  open_window: boolean | null;
  attached_backplate: boolean | null;
  // Sprint 14b: temperature (Backend field_serializer Decimal->float => number)
  // + battery_percent fuer Thermostat-Bubbles (Ist-Temp + Batterie).
  temperature: number | null;
  battery_percent: number | null;
  recorded_at: string;
}

export interface Device {
  id: number;
  dev_eui: string;
  app_eui: string | null;
  kind: DeviceKind;
  vendor: DeviceVendor;
  model: string;
  label: string | null;
  heating_zone_id: number | null;
  /**
   * Sprint 13b.1 (AE-57): Lifecycle-Marker. `null` = aktiv, Timestamp =
   * stillgelegt. Listen-Endpoint blendet retired Rows per Default aus
   * (Opt-in via `?include_retired=true`). Frueheres `is_active` wurde
   * in Migration 0018 gedroppt.
   */
  retired_at: string | null;
  retired_reason: string | null;
  replaced_by_device_id: number | null;
  last_seen_at: string | null;
  /** Sprint 9.11x.b: vom MQTT-Subscriber aus FW-Reply gepflegt. */
  firmware_version: string | null;
  /** Sprint 11 (AE-53): Device-Health-Aggregat (offline/implausible). */
  health_state: DeviceHealthState;
  /**
   * Sprint 15d (AE-65): Batterie-Health-Achse, orthogonal zu health_state.
   * Read-time abgeleitet aus latest_reading.battery_percent + Config-Schwelle.
   */
  battery_state: BatteryHealthState;
  created_at: string;
  updated_at: string;
  // Sprint 14a (D1/D2): Cross-Sicht-Felder.
  hardware_number: string | null;
  heating_zone: DeviceZone | null;
  active_override: DeviceActiveOverride | null;
  latest_reading: DeviceLatestReading | null;
}

export interface DeviceCreate {
  dev_eui: string;
  app_eui?: string | null;
  kind: DeviceKind;
  vendor: DeviceVendor;
  model: string;
  label?: string | null;
  heating_zone_id?: number | null;
}

export interface DeviceUpdate {
  app_eui?: string | null;
  kind?: DeviceKind;
  vendor?: DeviceVendor;
  model?: string;
  label?: string | null;
  /** Sprint 14a (D1/D5): Hardware-Nummer per Inline-Edit (Detail-Seite). */
  hardware_number?: string | null;
  heating_zone_id?: number | null;
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
  // Sprint 14a (D9): Codec-Felder, vom Backend in SensorReadingRead
  // gespiegelt (NULL wenn das Feld im Frame fehlte / alter Codec).
  open_window: boolean | null;
  attached_backplate: boolean | null;
}

export interface SensorReadingsQuery {
  from?: string;
  to?: string;
  limit?: number;
}

export interface DeviceListQuery {
  vendor?: DeviceVendor;
  limit?: number;
  offset?: number;
}

export interface DeviceAssignZoneRequest {
  heating_zone_id: number;
}

export interface DeviceAssignZoneResponse {
  device_id: number;
  dev_eui: string;
  heating_zone_id: number | null;
  label: string | null;
  updated_at: string;
}

/**
 * Sprint 13b.1 (AE-57): atomarer Pool-Reassign-Tausch. Body fuer
 * POST /api/v1/devices/{device_id}/replace/from-pool.
 */
export interface DeviceReplaceFromPoolRequest {
  new_pool_device_id: number;
}

/**
 * Sprint 13b.1 (AE-57): Stilllegung ohne Ersatz. Body fuer
 * POST /api/v1/devices/{device_id}/retire. ``reason`` ist Backend-
 * Freitext (1-255 chars); Frontend-Dropdown sendet einen der vier
 * Strings "Defekt" / "Batterie leer" / "Verlust" / "Wartung".
 */
export interface DeviceRetireRequest {
  reason: string;
}

/**
 * Hardware-Status-Snapshot (Sprint 9.13c). Spiegelt
 * ``HardwareStatusResponse`` aus ``schemas/device.py``. Datenquelle ist
 * ``sensor_reading.attached_backplate`` der letzten ``window_minutes``
 * Minuten — siehe Backend-Docstring.
 */
export interface HardwareStatusResponse {
  status: "active" | "inactive";
  last_seen: string | null;
  frames_in_window: number;
  window_minutes: number;
}

/**
 * API-Fehler-Schema (FastAPI default: { detail: string | object[] }).
 *
 * Sprint 13b.2 B-Sprint13b2-4 (AE-59): optionales ``error_code``-Feld
 * aus dem Backend-Body. Heute ausschliesslich von Lifecycle-Endpoints
 * gesetzt (4 Codes, siehe ``lib/api/error-codes.ts``). FastAPI-
 * Default-Pfade (ValidationError, generische ``HTTPException``-Aufrufe
 * ohne unseren App-weiten Handler) liefern das Feld NICHT;
 * ``undefined`` ist der Normalfall fuer andere Endpoint-Familien.
 */
export interface ApiError {
  status: number;
  detail: string | unknown;
  error_code?: string;
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
  guest_override_blocked: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
  // Sprint 14d (R-A, §5.63): Bool-Indikator „>= 1 aktive Übersteuerung".
  // Backend RoomRead befüllt es nur im Listen-Endpoint (sonst false).
  has_active_override: boolean;
}

// Sprint 12c (AE-58): Body fuer PATCH /rooms/{id}/override-block-state.
// Eigener Endpoint, NICHT Teil von RoomUpdate.
export interface RoomOverrideBlockUpdate {
  blocked: boolean;
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
  // Sprint 14b (§5.63): Backend HeatingZoneRead liefert health_state seit
  // Sprint 11 (AE-53); Frontend-Type-Spiegel war bislang lückenhaft.
  health_state: ZoneHealthState;
  created_at: string;
  updated_at: string;
  // Sprint 14d FU-5 (§5.63): aktiver Zone-Override read-only. Gleiche Form wie
  // DeviceActiveOverride. Ersetzt den useZoneOverride-Roundtrip in ZoneCard.
  active_override: DeviceActiveOverride | null;
  // Sprint 14e FU-1 (§5.63): Zone-Aggregat-Ist-Temperatur (arithm. Mittel ueber
  // healthy + aktive Vickis, AE-51 §4.1). Backend serialisiert Decimal->number.
  // null = keine healthy Vicki mit Temperatur in der Zone.
  mean_temperature_c: number | null;
  // Sprint 14e FU-2 (§5.63): zuletzt von der Engine als HARD_CLAMP gesetzter
  // Setpoint des Zimmers (AE-55 P1). Alle Zonen eines Zimmers teilen den Wert
  // (AE-51 §4.2). null = kein HARD_CLAMP-Eval im 1h-Fenster.
  engine_setpoint_c: number | null;
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

// ---------------------------------------------------------------------------
// Auth + User (Sprint 9.17, AE-50)
// ---------------------------------------------------------------------------

export type UserRole = "admin" | "mitarbeiter";

export interface User {
  id: number;
  email: string;
  role: UserRole;
  is_active: boolean;
  must_change_password: boolean;
  created_at: string;
  updated_at: string;
  last_login_at: string | null;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  user: User;
}

export interface ChangePasswordRequest {
  current_password: string;
  new_password: string;
}

export interface UserCreate {
  email: string;
  role: UserRole;
  initial_password: string;
}

export interface UserUpdate {
  role?: UserRole;
  is_active?: boolean;
}

export interface UserPasswordReset {
  new_password: string;
}

// ---------------------------------------------------------------------------
// Szenarien (Sprint 9.16, AE-48)
// ---------------------------------------------------------------------------

/**
 * Szenario-Listen-Item mit aktuellem GLOBAL-Aktivierungs-Status.
 * Spiegelt `ScenarioListItem` aus `backend/src/heizung/api/v1/scenarios.py`.
 */
export interface Scenario {
  id: number;
  code: string;
  name: string;
  description: string | null;
  is_system: boolean;
  default_active: boolean;
  parameter_schema: Record<string, unknown> | null;
  default_parameters: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  current_global_assignment_active: boolean;
}

export type ScenarioScopeApi = "global";

export interface ScenarioToggleRequest {
  scope: ScenarioScopeApi;
}

/**
 * Globale RuleConfig — die 6 Engine-gelesenen Felder (Sprint 9.14, AE-46).
 * Spiegelt `RuleConfigGlobalRead` aus
 * `backend/src/heizung/schemas/rule_config.py`.
 *
 * Decimal-Werte kommen als String (volle Praezision aus Pydantic-Serialisierung).
 * Time-Werte kommen als ISO-String `HH:MM:SS`.
 */
export interface RuleConfigGlobal {
  id: number;
  t_occupied: string | null;
  t_vacant: string | null;
  t_night: string | null;
  night_start: string | null;
  night_end: string | null;
  preheat_minutes_before_checkin: number | null;
  created_at: string;
  updated_at: string;
}

export interface RuleConfigGlobalUpdate {
  t_occupied?: string;
  t_vacant?: string;
  t_night?: string;
  night_start?: string;
  night_end?: string;
  preheat_minutes_before_checkin?: number;
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

// ---------------------------------------------------------------------------
// event_log (Sprint 9.5 — Engine-Audit-Trace pro Layer)
// ---------------------------------------------------------------------------

export type EventLogLayer =
  | "summer_mode_fast_path"
  | "base_target"
  | "temporal_override"
  | "manual_override"
  // Sprint 12a T4 (AE-58): Off-Pipeline-Audit fuer device_adapter
  // Pre-Insert-Skip (VACANT-Raum oder Fenster offen). Eigene
  // synthetische ``evaluation_id``, gehoert keiner Engine-Tick-Eval.
  | "manual_override_blocked"
  | "guest_override"
  | "window_safety"
  | "device_detached"
  | "hard_clamp";

export type CommandReason =
  | "occupied_setpoint"
  | "vacant_setpoint"
  | "night_setback"
  | "day_setback"
  | "preheat_checkin"
  | "checkout_setback"
  | "window_open"
  | "device_detached"
  | "guest_override"
  | "long_vacant"
  | "frost_protection"
  | "summer_mode"
  | "manual"
  | "manual_event"
  // Sprint 12a T4 (AE-58): Reasons fuer MANUAL_OVERRIDE_BLOCKED-Layer-
  // Rows. Beide nur im Device-Adapter-Off-Pipeline-Pfad geschrieben.
  | "device_blocked_vacant"
  | "device_blocked_window"
  // Sprint 12c (AE-58): Uebersteuerungs-Sperre aktiv -> Vicki-Drehring
  // silent geskippt.
  | "device_blocked_room_blocked";

// ---------------------------------------------------------------------------
// Manual Override (Sprint 9.9 - Engine Layer 3)
// ---------------------------------------------------------------------------

export type OverrideSource =
  | "device"
  | "frontend_4h"
  | "frontend_midnight"
  | "frontend_checkout";

/**
 * Quellen, die das Frontend selbst anlegen darf. ``device``-Overrides
 * werden ausschliesslich vom Backend ``device_adapter`` aus Vicki-
 * Uplinks erzeugt.
 */
export type FrontendOverrideSource =
  | "frontend_4h"
  | "frontend_midnight"
  | "frontend_checkout";

/**
 * Spiegelt ``ManualOverrideResponse`` aus
 * ``backend/src/heizung/schemas/manual_override.py``. ``setpoint`` kommt
 * als String aus Pydantic-Decimal-Serialisierung — bewusst nicht in
 * Number umwandeln (Float-Rundungsfreiheit).
 *
 * Sprint 12a T3 (AE-58): ``heating_zone_id`` traegt optionalen Zone-
 * Scope. ``null`` = Room-Scope-Override (Backward-Compat fuer
 * Bestandsrows aus Lazy-Migration 0016).
 */
export interface ManualOverride {
  id: number;
  room_id: number;
  heating_zone_id: number | null;
  setpoint: string;
  source: OverrideSource;
  expires_at: string;
  reason: string | null;
  created_at: string;
  created_by: string | null;
  revoked_at: string | null;
  revoked_reason: string | null;
}

export interface ManualOverrideCreate {
  setpoint: string;
  source: FrontendOverrideSource;
  reason?: string | null;
  /**
   * Sprint 12a T3 (AE-58): optionaler Zone-Scope. ``undefined`` /
   * weggelassen = Room-Scope-Override (Backward-Compat). Gesetzt =
   * Zone-Match (Backend FK-404-Check verifiziert, dass Zone zum Pfad-
   * Room gehoert).
   */
  heating_zone_id?: number;
}

export interface ManualOverrideListQuery {
  limit?: number;
  include_expired?: boolean;
  /**
   * Sprint 12a T3 (AE-58): optionaler Zone-Filter. Wenn gesetzt liefert
   * Backend Zone-Match + Room-Scope-Fallback (Zone > Room sortiert).
   * Ohne Param: alle Overrides des Raums (Backward-Compat).
   */
  zone_id?: number;
}

export interface EventLogEntry {
  time: string;
  room_id: number;
  evaluation_id: string;
  layer: EventLogLayer;
  device_id: number | null;
  setpoint_in: string | null; // Decimal — Backend liefert string
  setpoint_out: string | null;
  reason: CommandReason | null;
  details: Record<string, unknown> | null;
}

/**
 * Sprint 14c: Aggregierte Dashboard-KPIs (GET /api/v1/dashboard/kpi).
 * Spiegel zu ``schemas/dashboard.DashboardKpiRead`` (§5.63). Zod-Validierung
 * in ``lib/api/dashboard.ts``. ``avg_temperature_celsius`` ist eine Zahl
 * (Backend field_serializer->float), ``last_engine_tick`` UTC ISO-8601.
 */
export interface DashboardKpi {
  rooms_occupied: number;
  rooms_total: number;
  avg_temperature_celsius: number | null;
  devices_online: number;
  devices_total: number;
  active_overrides: number;
  zones_window_open: number;
  last_engine_tick: string | null;
  // Sprint 15d (AE-65): aktive Geräte mit schwacher Batterie (warn∪kritisch).
  battery_low_count: number;
}
