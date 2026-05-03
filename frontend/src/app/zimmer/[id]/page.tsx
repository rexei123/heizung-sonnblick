"use client";

/**
 * Zimmer-Detail (Sprint 8.10) mit Tabs:
 *   - Stammdaten (RoomForm)
 *   - Heizzonen (HeatingZoneList)
 *   - Geraete (Liste der Devices, die der Zone in diesem Zimmer zugeordnet sind)
 *   - Belegungen (Liste, anlegen + stornieren — Sprint 8.11 bringt eigene Seite)
 */

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { HeatingZoneList } from "@/components/patterns/heating-zone-list";
import { RoomForm } from "@/components/patterns/room-form";
import { useDevices } from "@/lib/api/hooks";
import {
  useDeleteRoom,
  useHeatingZones,
  useRoom,
  useUpdateRoom,
} from "@/lib/api/hooks-rooms";
import type { ApiError, RoomCreate, RoomUpdate } from "@/lib/api/types";

type Tab = "stammdaten" | "zonen" | "geraete";

export default function ZimmerDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const id = params?.id ? parseInt(params.id, 10) : null;
  const room = useRoom(id);
  const updateMut = useUpdateRoom(id ?? 0);
  const deleteMut = useDeleteRoom();
  const [tab, setTab] = useState<Tab>("stammdaten");
  const [error, setError] = useState<string | null>(null);

  const handleUpdate = async (payload: RoomCreate | RoomUpdate) => {
    setError(null);
    try {
      await updateMut.mutateAsync(payload as RoomUpdate);
    } catch (e) {
      setError(toMessage(e));
    }
  };

  const handleDelete = async () => {
    if (!id) return;
    if (
      !confirm(
        "Zimmer wirklich loeschen? Nur moeglich, wenn keine aktiven Belegungen existieren.",
      )
    ) {
      return;
    }
    setError(null);
    try {
      await deleteMut.mutateAsync(id);
      router.push("/zimmer" as never);
    } catch (e) {
      setError(toMessage(e));
    }
  };

  if (!id) {
    return (
          <div className="p-6">Ungueltige Zimmer-ID.</div>
      );
  }

  if (room.isLoading) {
    return (
          <div className="p-6 text-text-secondary">Lade…</div>
      );
  }

  if (room.isError || !room.data) {
    return (
          <div className="p-6">
          <p className="text-domain-heating-off mb-4">Zimmer nicht gefunden.</p>
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

        <header className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-medium text-text-primary">
              Zimmer {room.data.number}
            </h1>
            {room.data.display_name ? (
              <p className="text-sm text-text-secondary mt-1">{room.data.display_name}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={handleDelete}
            disabled={deleteMut.isPending}
            className="text-sm text-domain-heating-off hover:underline"
          >
            {deleteMut.isPending ? "Loesche…" : "Zimmer loeschen"}
          </button>
        </header>

        <div className="border-b border-border mb-4 flex gap-4 text-sm">
          {(["stammdaten", "zonen", "geraete"] as const).map((t) => (
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
              {t === "stammdaten" ? "Stammdaten" : t === "zonen" ? "Heizzonen" : "Geraete"}
            </button>
          ))}
        </div>

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
          ) : (
            <DevicesInRoom roomId={id} />
          )}
        </div>
      </div>
  );
}

function DevicesInRoom({ roomId }: { roomId: number }) {
  const zones = useHeatingZones(roomId);
  const allDevices = useDevices();

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
        Bitte zuerst Heizzonen anlegen, dann koennen Geraete zugeordnet werden.
      </p>
    );
  }
  if (devicesInRoom.length === 0) {
    return (
      <p className="text-sm text-text-secondary italic">
        Noch keine Geraete den Zonen dieses Zimmers zugeordnet. Geraet-Zuordnung
        erfolgt in der Geraete-Detailseite (PATCH heating_zone_id).
      </p>
    );
  }
  return (
    <ul className="bg-surface border border-border rounded-md overflow-hidden">
      {devicesInRoom.map((d) => {
        const zone = (zones.data ?? []).find((z) => z.id === d.heating_zone_id);
        return (
          <li
            key={d.id}
            className="flex items-center justify-between px-3 py-2 border-b border-border last:border-b-0"
          >
            <div>
              <div className="font-medium text-text-primary text-sm">
                {d.label ?? d.dev_eui}
              </div>
              <div className="text-xs text-text-tertiary">
                {d.vendor} {d.model} · Zone {zone?.name ?? "?"}
              </div>
            </div>
            <Link
              href={{ pathname: "/devices/[device_id]", query: { device_id: d.id } } as never}
              className="text-xs text-primary hover:underline"
            >
              Detail →
            </Link>
          </li>
        );
      })}
    </ul>
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
