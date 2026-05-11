"use client";

/**
 * Geraete-Pairing-Wizard (Sprint 9.13a TA1).
 *
 * 4 Schritte: Geraet -> Zimmer -> Heizzone -> Label + Bestaetigen.
 * Erreichbar via CTA-Button auf /devices.
 */

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";

import { MultiStepForm } from "@/components/patterns/multi-step-form";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useAssignDeviceZone,
  useCreateDevice,
  useDevices,
  useUpdateDevice,
} from "@/lib/api/hooks";
import { useHeatingZones, useRooms } from "@/lib/api/hooks-rooms";
import type {
  ApiError,
  Device,
  DeviceCreate,
  DeviceKind,
  DeviceVendor,
} from "@/lib/api/types";

const HEX16 = /^[0-9a-fA-F]{16}$/;

function toMessage(e: unknown): string {
  if (typeof e === "object" && e !== null && "detail" in e) {
    const detail = (e as ApiError).detail;
    return typeof detail === "string" ? detail : JSON.stringify(detail);
  }
  return e instanceof Error ? e.message : "Unbekannter Fehler";
}

export default function DevicePairPage() {
  return (
    <Suspense fallback={<PairFallback />}>
      <DevicePairPageInner />
    </Suspense>
  );
}

function PairFallback() {
  return (
    <div className="p-6 max-w-content mx-auto">
      <h1 className="text-2xl font-medium text-text-primary">Gerät hinzufügen</h1>
      <p className="text-sm text-text-secondary mt-1">Lade…</p>
    </div>
  );
}

function DevicePairPageInner() {
  const router = useRouter();
  const params = useSearchParams();
  // Optional: ?room_id=42 vorausgewaehlt (Tieflink von /zimmer/[id]).
  const preselectRoomId = params?.get("room_id");

  const allDevices = useDevices();
  const rooms = useRooms();
  const createDeviceMut = useCreateDevice();

  const [deviceId, setDeviceId] = useState<number | null>(null);
  const [roomId, setRoomId] = useState<number | null>(
    preselectRoomId ? Number(preselectRoomId) : null,
  );
  const [zoneId, setZoneId] = useState<number | null>(null);
  const [label, setLabel] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);

  const zones = useHeatingZones(roomId);
  const assignMut = useAssignDeviceZone(deviceId ?? 0);
  const labelMut = useUpdateDevice(deviceId ?? 0);

  // Reset abhaengiger Felder bei Aenderung weiter oben.
  const onChangeRoom = (next: number | null) => {
    setRoomId(next);
    setZoneId(null);
  };

  const unassigned = useMemo(
    () => (allDevices.data ?? []).filter((d) => d.heating_zone_id === null),
    [allDevices.data],
  );

  const selectedDevice: Device | undefined = useMemo(
    () =>
      deviceId !== null ? allDevices.data?.find((d) => d.id === deviceId) : undefined,
    [allDevices.data, deviceId],
  );

  const selectedRoom = rooms.data?.find((r) => r.id === roomId);
  const selectedZone = zones.data?.find((z) => z.id === zoneId);

  const onComplete = async () => {
    if (deviceId === null || zoneId === null) return;
    setSubmitError(null);
    try {
      await assignMut.mutateAsync({ heating_zone_id: zoneId });
      const trimmed = label.trim();
      if (trimmed && trimmed !== selectedDevice?.label) {
        await labelMut.mutateAsync({ label: trimmed });
      }
      const target = roomId
        ? `/zimmer/${roomId}?paired=${encodeURIComponent(trimmed || selectedDevice?.dev_eui || "device")}`
        : "/devices";
      router.push(target as never);
    } catch (e) {
      setSubmitError(toMessage(e));
    }
  };

  const submitting = assignMut.isPending || labelMut.isPending;

  return (
    <div className="p-6 max-w-content mx-auto">
      <header className="mb-6">
        <h1 className="text-2xl font-medium text-text-primary">Gerät hinzufügen</h1>
        <p className="text-sm text-text-secondary mt-1">
          Ein Gerät einer Heizzone zuordnen. Vier Schritte: Gerät, Zimmer,
          Heizzone, Label.
        </p>
      </header>

      <MultiStepForm
        loading={submitting}
        error={submitError}
        onCancel={() => router.push("/devices" as never)}
        steps={[
          {
            id: "device",
            label: "Gerät",
            valid: deviceId !== null,
            component: (
              <DeviceStep
                devices={unassigned}
                allLoading={allDevices.isLoading}
                value={deviceId}
                onChange={setDeviceId}
                onCreate={async (payload) => {
                  const created = await createDeviceMut.mutateAsync(payload);
                  setDeviceId(created.id);
                }}
                creating={createDeviceMut.isPending}
              />
            ),
          },
          {
            id: "room",
            label: "Zimmer",
            valid: roomId !== null,
            component: (
              <RoomStep
                rooms={rooms.data ?? []}
                loading={rooms.isLoading}
                value={roomId}
                onChange={onChangeRoom}
              />
            ),
          },
          {
            id: "zone",
            label: "Heizzone",
            valid: zoneId !== null,
            component: (
              <ZoneStep
                roomId={roomId}
                zones={zones.data ?? []}
                loading={zones.isLoading}
                value={zoneId}
                onChange={setZoneId}
              />
            ),
          },
          {
            id: "label",
            label: "Label & Bestätigen",
            valid: true, // Label ist optional
            component: (
              <ConfirmStep
                device={selectedDevice}
                roomLabel={
                  selectedRoom
                    ? `${selectedRoom.number}${selectedRoom.display_name ? ` · ${selectedRoom.display_name}` : ""}`
                    : ""
                }
                zoneLabel={selectedZone?.name ?? ""}
                label={label}
                onLabelChange={setLabel}
              />
            ),
          },
        ]}
        onComplete={onComplete}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 1: Geraet
// ---------------------------------------------------------------------------

function DeviceStep({
  devices,
  allLoading,
  value,
  onChange,
  onCreate,
  creating,
}: {
  devices: Device[];
  allLoading: boolean;
  value: number | null;
  onChange: (id: number) => void;
  onCreate: (payload: DeviceCreate) => Promise<void>;
  creating: boolean;
}) {
  const [createMode, setCreateMode] = useState(false);
  const [devEui, setDevEui] = useState("");
  const [model, setModel] = useState("");
  const [vendor, setVendor] = useState<DeviceVendor>("mclimate");
  const [kind, setKind] = useState<DeviceKind>("thermostat");
  const [createError, setCreateError] = useState<string | null>(null);

  if (allLoading) {
    return <p className="text-sm text-text-secondary">Lade Geräte…</p>;
  }

  if (createMode || devices.length === 0) {
    const submit = async () => {
      setCreateError(null);
      if (!HEX16.test(devEui)) {
        setCreateError("DevEUI muss 16 Hex-Zeichen sein (0-9, a-f).");
        return;
      }
      if (!model.trim()) {
        setCreateError("Modell ist Pflicht.");
        return;
      }
      try {
        await onCreate({
          dev_eui: devEui.toLowerCase(),
          kind,
          vendor,
          model: model.trim(),
        });
        setCreateMode(false);
      } catch (e) {
        setCreateError(toMessage(e));
      }
    };
    return (
      <div className="space-y-3">
        {devices.length === 0 ? (
          <p className="text-sm text-text-secondary">
            Alle Geräte sind zugeordnet. Neues Gerät anlegen:
          </p>
        ) : (
          <p className="text-sm text-text-secondary">
            Neues Gerät anlegen (DevEUI, Modell):
          </p>
        )}
        <div className="grid grid-cols-2 gap-3">
          <label className="text-sm">
            DevEUI (16 Hex)
            <Input
              value={devEui}
              onChange={(e) => setDevEui(e.target.value)}
              placeholder="z.B. 70b3d52dd3034de4"
              className="mt-1 font-mono"
              autoComplete="off"
            />
          </label>
          <label className="text-sm">
            Modell
            <Input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="z.B. Vicki"
              className="mt-1"
            />
          </label>
          <label className="text-sm">
            Hersteller
            <Select value={vendor} onValueChange={(v) => setVendor(v as DeviceVendor)}>
              <SelectTrigger className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="mclimate">mclimate</SelectItem>
                <SelectItem value="milesight">milesight</SelectItem>
                <SelectItem value="manual">manual</SelectItem>
              </SelectContent>
            </Select>
          </label>
          <label className="text-sm">
            Art
            <Select value={kind} onValueChange={(v) => setKind(v as DeviceKind)}>
              <SelectTrigger className="mt-1">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="thermostat">Thermostat</SelectItem>
                <SelectItem value="sensor">Sensor</SelectItem>
              </SelectContent>
            </Select>
          </label>
        </div>
        {createError ? (
          <p role="alert" className="text-sm text-error">
            {createError}
          </p>
        ) : null}
        <div className="flex items-center gap-2">
          <Button onClick={submit} loading={creating}>
            Gerät anlegen
          </Button>
          {devices.length > 0 ? (
            <Button variant="ghost" onClick={() => setCreateMode(false)}>
              Aus Liste auswählen
            </Button>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-text-secondary">
        {devices.length} Gerät(e) noch keiner Heizzone zugeordnet:
      </p>
      <Select
        value={value !== null ? String(value) : ""}
        onValueChange={(v) => onChange(Number(v))}
      >
        <SelectTrigger>
          <SelectValue placeholder="Gerät wählen" />
        </SelectTrigger>
        <SelectContent>
          {devices.map((d) => (
            <SelectItem key={d.id} value={String(d.id)}>
              {d.label ?? d.dev_eui} · {d.vendor}/{d.model}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button variant="ghost" onClick={() => setCreateMode(true)} icon="add">
        Stattdessen neues Gerät anlegen
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2: Zimmer
// ---------------------------------------------------------------------------

function RoomStep({
  rooms,
  loading,
  value,
  onChange,
}: {
  rooms: { id: number; number: string; display_name: string | null }[];
  loading: boolean;
  value: number | null;
  onChange: (id: number) => void;
}) {
  if (loading) return <p className="text-sm text-text-secondary">Lade Zimmer…</p>;
  if (rooms.length === 0) {
    return (
      <p className="text-sm text-text-secondary">
        Keine Zimmer vorhanden. Erst ein Zimmer anlegen.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-sm text-text-secondary">In welchem Zimmer ist das Gerät?</p>
      <Select
        value={value !== null ? String(value) : ""}
        onValueChange={(v) => onChange(Number(v))}
      >
        <SelectTrigger>
          <SelectValue placeholder="Zimmer wählen" />
        </SelectTrigger>
        <SelectContent>
          {rooms.map((r) => (
            <SelectItem key={r.id} value={String(r.id)}>
              {r.number}
              {r.display_name ? ` · ${r.display_name}` : ""}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 3: Heizzone
// ---------------------------------------------------------------------------

function ZoneStep({
  roomId,
  zones,
  loading,
  value,
  onChange,
}: {
  roomId: number | null;
  zones: { id: number; name: string; kind: string }[];
  loading: boolean;
  value: number | null;
  onChange: (id: number) => void;
}) {
  if (roomId === null) {
    return (
      <p className="text-sm text-text-secondary">Bitte zuerst ein Zimmer wählen.</p>
    );
  }
  if (loading) {
    return <p className="text-sm text-text-secondary">Lade Heizzonen…</p>;
  }
  if (zones.length === 0) {
    return (
      <p className="text-sm text-text-secondary">
        Dieses Zimmer hat keine Heizzone. Erst eine Heizzone im Zimmer anlegen
        (auf der Zimmer-Detailseite, Tab „Heizzonen").
      </p>
    );
  }
  return (
    <div className="space-y-3">
      <p className="text-sm text-text-secondary">
        Welcher Heizzone soll das Gerät zugeordnet werden?
      </p>
      <Select
        value={value !== null ? String(value) : ""}
        onValueChange={(v) => onChange(Number(v))}
      >
        <SelectTrigger>
          <SelectValue placeholder="Heizzone wählen" />
        </SelectTrigger>
        <SelectContent>
          {zones.map((z) => (
            <SelectItem key={z.id} value={String(z.id)}>
              {z.name} · {z.kind}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 4: Label + Bestaetigen
// ---------------------------------------------------------------------------

function ConfirmStep({
  device,
  roomLabel,
  zoneLabel,
  label,
  onLabelChange,
}: {
  device: Device | undefined;
  roomLabel: string;
  zoneLabel: string;
  label: string;
  onLabelChange: (v: string) => void;
}) {
  return (
    <div className="space-y-4">
      <div>
        <label className="text-sm">
          Label (optional)
          <Input
            value={label}
            onChange={(e) => onLabelChange(e.target.value)}
            placeholder={device?.label ?? `Vicki ${device?.dev_eui.slice(-4) ?? ""}`}
            className="mt-1"
          />
        </label>
        <p className="text-xs text-text-tertiary mt-1">
          Leer lassen, um den bestehenden Label zu behalten.
        </p>
      </div>
      <dl className="grid grid-cols-[120px_1fr] gap-y-2 text-sm bg-surface-alt rounded-md p-4">
        <dt className="text-text-secondary">Gerät</dt>
        <dd className="text-text-primary font-medium">
          {device?.label ?? device?.dev_eui ?? "—"}
        </dd>
        <dt className="text-text-secondary">Zimmer</dt>
        <dd className="text-text-primary">{roomLabel || "—"}</dd>
        <dt className="text-text-secondary">Heizzone</dt>
        <dd className="text-text-primary">{zoneLabel || "—"}</dd>
        <dt className="text-text-secondary">Neuer Label</dt>
        <dd className="text-text-primary">{label.trim() || "(unverändert)"}</dd>
      </dl>
    </div>
  );
}
