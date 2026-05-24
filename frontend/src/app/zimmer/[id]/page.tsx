"use client";

/**
 * Zimmer-Detail (Sprint 8.10, Sprint 8.15 Design-Fixes).
 * Tabs: Stammdaten / Heizzonen / Geräte.
 */

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { EngineDecisionPanel } from "@/components/patterns/engine-decision-panel";
import { HardwareStatusBadge } from "@/components/patterns/hardware-status-badge";
import { HeatingZoneList } from "@/components/patterns/heating-zone-list";
import { ManualOverridePanelList } from "@/components/patterns/manual-override-panel-list";
import { RoomForm } from "@/components/patterns/room-form";
import { RoomOverrideBlockToggle } from "@/components/patterns/room-override-block-toggle";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useDetachDeviceZone, useDevices } from "@/lib/api/hooks";
import { useRoomOverrides } from "@/lib/api/hooks-overrides";
import {
  useDeleteRoom,
  useHeatingZones,
  useRoom,
  useUpdateRoom,
} from "@/lib/api/hooks-rooms";
import type { ApiError, RoomCreate, RoomUpdate } from "@/lib/api/types";

type Tab = "stammdaten" | "zonen" | "geraete" | "engine" | "override";

export default function ZimmerDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params?.id ? parseInt(params.id, 10) : null;
  const room = useRoom(id);
  const updateMut = useUpdateRoom(id ?? 0);
  const deleteMut = useDeleteRoom();
  // Sprint 12c: aktive Override-Anzahl fuer Confirm-Dialog im Toggle.
  const overridesQuery = useRoomOverrides(id ?? 0, { include_expired: false });
  const activeOverridesCount = (overridesQuery.data ?? []).filter(
    (o) =>
      o.revoked_at === null && new Date(o.expires_at).getTime() > Date.now(),
  ).length;
  const [tab, setTab] = useState<Tab>("stammdaten");
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const handleUpdate = async (payload: RoomCreate | RoomUpdate) => {
    setError(null);
    try {
      await updateMut.mutateAsync(payload as RoomUpdate);
    } catch (e) {
      setError(toMessage(e));
    }
  };

  const performDelete = async () => {
    if (!id) return;
    setError(null);
    try {
      await deleteMut.mutateAsync(id);
      router.push("/zimmer" as never);
    } catch (e) {
      setError(toMessage(e));
      setConfirmDelete(false);
    }
  };

  if (!id) {
    return <div className="p-6">Ungültige Zimmer-ID.</div>;
  }

  if (room.isLoading) {
    return <div className="p-6 text-text-secondary">Lade…</div>;
  }

  if (room.isError || !room.data) {
    return (
      <div className="p-6">
        <p className="text-error mb-4">Zimmer nicht gefunden.</p>
        <Link href={"/zimmer" as never} className="text-primary hover:underline">
          ← Zur Liste
        </Link>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      <div className="mb-4">
        <Link
          href={"/zimmer" as never}
          className="text-sm text-text-secondary hover:text-primary flex items-center gap-1"
        >
          <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
            arrow_back
          </span>
          Zur Zimmerliste
        </Link>
      </div>

      <header className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-medium text-text-primary">
            Zimmer {room.data.number}
          </h1>
          {room.data.display_name ? (
            <p className="text-sm text-text-secondary mt-1">{room.data.display_name}</p>
          ) : null}
        </div>
        <div className="flex items-start gap-3">
          <RoomOverrideBlockToggle
            room={room.data}
            activeOverridesCount={activeOverridesCount}
          />
          <Button
            variant="destructive"
            icon="delete"
            onClick={() => setConfirmDelete(true)}
            disabled={deleteMut.isPending}
          >
            Zimmer löschen
          </Button>
        </div>
      </header>

      <div className="border-b border-border mb-4 flex gap-4 text-sm">
        {(["stammdaten", "zonen", "geraete", "engine", "override"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`pb-2 -mb-px border-b-2 transition-colors ${
              tab === t
                ? "border-primary text-primary font-medium"
                : "border-transparent text-text-secondary hover:text-text-primary"
            }`}
          >
            {t === "stammdaten"
              ? "Stammdaten"
              : t === "zonen"
                ? "Heizzonen"
                : t === "geraete"
                  ? "Geräte"
                  : t === "engine"
                    ? "Engine"
                    : "Übersteuerung"}
          </button>
        ))}
      </div>

      {tab === "override" ? (
        <ManualOverridePanelList roomId={id} />
      ) : (
        <div className="bg-surface border border-border rounded-md p-5">
          {tab === "stammdaten" ? (
            <RoomForm
              initial={room.data}
              onSubmit={handleUpdate}
              submitting={updateMut.isPending}
              error={error}
            />
          ) : tab === "zonen" ? (
            <HeatingZoneList roomId={id} />
          ) : tab === "geraete" ? (
            <DevicesInRoom roomId={id} />
          ) : (
            <EngineDecisionPanel roomId={id} />
          )}
        </div>
      )}

      <ConfirmDialog
        open={confirmDelete}
        title="Zimmer löschen?"
        message={`Zimmer „${room.data.number}“ wird endgültig entfernt. Nur möglich, wenn keine aktiven Belegungen existieren.`}
        confirmLabel="Endgültig löschen"
        loading={deleteMut.isPending}
        onConfirm={performDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}

function DevicesInRoom({ roomId }: { roomId: number }) {
  const zones = useHeatingZones(roomId);
  const allDevices = useDevices();
  const [detachTarget, setDetachTarget] = useState<{
    id: number;
    label: string;
    zoneName: string;
  } | null>(null);
  const [detachError, setDetachError] = useState<string | null>(null);
  // Sprint 13b.2 T3: State-Anker fuer Replace + Retire-Dialog. Buttons
  // setzen die device_id, der Dialog (T4/T5) liest sie und setzt nach
  // close oder Erfolg wieder null. Pre-Stop-1: State-Reader unten als
  // sr-only-Status-Placeholder, T4/T5 ersetzen ihn durch echte Dialoge.
  const [openReplaceDialog, setOpenReplaceDialog] = useState<number | null>(
    null,
  );
  const [openRetireDialog, setOpenRetireDialog] = useState<number | null>(null);

  const zoneIds = new Set((zones.data ?? []).map((z) => z.id));
  const devicesInRoom = (allDevices.data ?? []).filter(
    (d) => d.heating_zone_id !== null && zoneIds.has(d.heating_zone_id),
  );

  if (zones.isLoading || allDevices.isLoading) {
    return <p className="text-sm text-text-secondary">Lade…</p>;
  }
  if (zones.data && zones.data.length === 0) {
    return (
      <p className="text-sm text-text-secondary italic">
        Bitte zuerst Heizzonen anlegen, dann können Geräte zugeordnet werden.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-end">
        <Link
          href={`/devices/pair?room_id=${roomId}` as never}
          className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
        >
          <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 18 }}>
            add
          </span>
          Gerät zuordnen
        </Link>
      </div>

      {detachError ? (
        <p role="alert" className="text-sm text-error">
          {detachError}
        </p>
      ) : null}

      {devicesInRoom.length === 0 ? (
        <p className="text-sm text-text-secondary italic">
          Noch keine Geräte den Zonen dieses Zimmers zugeordnet.
        </p>
      ) : (
        <ul className="bg-surface border border-border rounded-md overflow-hidden">
          {devicesInRoom.map((d) => {
            const zone = (zones.data ?? []).find((z) => z.id === d.heating_zone_id);
            return (
              <li
                key={d.id}
                className="flex items-center justify-between px-3 py-2 border-b border-border last:border-b-0"
              >
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-text-primary text-sm">
                      {d.label ?? d.dev_eui}
                    </span>
                    <HardwareStatusBadge deviceId={d.id} variant="compact" />
                  </div>
                  <div className="text-xs text-text-tertiary">
                    {d.vendor} {d.model} · Zone {zone?.name ?? "?"}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Link
                    href={`/devices/${d.id}` as never}
                    className="text-xs text-primary hover:underline"
                  >
                    Detail →
                  </Link>
                  <ReplaceDeviceButton
                    onClick={() => setOpenReplaceDialog(d.id)}
                  />
                  <RetireDeviceButton
                    onClick={() => setOpenRetireDialog(d.id)}
                  />
                  <DetachButton
                    onClick={() =>
                      setDetachTarget({
                        id: d.id,
                        label: d.label ?? d.dev_eui,
                        zoneName: zone?.name ?? "?",
                      })
                    }
                  />
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {detachTarget !== null ? (
        <DetachConfirm
          target={detachTarget}
          onClose={() => setDetachTarget(null)}
          onError={setDetachError}
        />
      ) : null}

      {/* Sprint 13b.2 T3 Pre-Stop-1-Reader: T4 + T5 ersetzen diese
          sr-only-Bloecke durch <ReplaceDeviceDialog /> bzw.
          <RetireDeviceDialog /> mit deviceId={openReplaceDialog|
          openRetireDialog} + onClose, das den State auf null setzt. */}
      {openReplaceDialog !== null ? (
        <span className="sr-only" role="status">
          Tausch-Dialog wird vorbereitet für Gerät #{openReplaceDialog}
        </span>
      ) : null}
      {openRetireDialog !== null ? (
        <span className="sr-only" role="status">
          Stilllegen-Dialog wird vorbereitet für Gerät #{openRetireDialog}
        </span>
      ) : null}
    </div>
  );
}

function ReplaceDeviceButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 text-xs text-text-secondary hover:text-primary transition-colors"
      aria-label="Thermostat tauschen"
      title="Thermostat tauschen"
    >
      <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 18 }}>
        swap_horiz
      </span>
      Tauschen
    </button>
  );
}

function RetireDeviceButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 text-xs text-text-secondary hover:text-error transition-colors"
      aria-label="Thermostat stilllegen"
      title="Thermostat stilllegen"
    >
      <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 18 }}>
        power_off
      </span>
      Stilllegen
    </button>
  );
}

function DetachButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 text-xs text-text-secondary hover:text-error transition-colors"
      aria-label="Gerät von Heizzone trennen"
    >
      <span className="material-symbols-outlined" aria-hidden style={{ fontSize: 18 }}>
        link_off
      </span>
      Trennen
    </button>
  );
}

function DetachConfirm({
  target,
  onClose,
  onError,
}: {
  target: { id: number; label: string; zoneName: string };
  onClose: () => void;
  onError: (msg: string | null) => void;
}) {
  const detachMut = useDetachDeviceZone(target.id);
  return (
    <ConfirmDialog
      open={true}
      title="Gerät von Heizzone trennen?"
      message={`Gerät „${target.label}" wird von Heizzone „${target.zoneName}" getrennt. Das Gerät bleibt im System, ist aber keiner Heizzone mehr zugeordnet.`}
      confirmLabel="Trennen"
      loading={detachMut.isPending}
      onConfirm={async () => {
        onError(null);
        try {
          await detachMut.mutateAsync();
          onClose();
        } catch (e) {
          onError(toMessage(e));
          onClose();
        }
      }}
      onCancel={onClose}
    />
  );
}

function toMessage(err: unknown): string {
  const e = err as ApiError | Error;
  if (typeof e === "object" && e !== null && "detail" in e) {
    const d = (e as ApiError).detail;
    return typeof d === "string" ? d : JSON.stringify(d);
  }
  return e instanceof Error ? e.message : "Unbekannter Fehler";
}
