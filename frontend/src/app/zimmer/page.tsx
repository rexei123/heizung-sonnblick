"use client";

/**
 * Zimmer-Liste (Sprint 8.10) mit Filtern + Anlege-Drawer.
 */

import Link from "next/link";
import { useState } from "react";

import { RoomForm } from "@/components/patterns/room-form";
import { useRoomTypes } from "@/lib/api/hooks-room-types";
import { useCreateRoom, useRooms } from "@/lib/api/hooks-rooms";
import type {
  ApiError,
  Room,
  RoomCreate,
  RoomStatus,
  RoomUpdate,
} from "@/lib/api/types";

const STATUS_LABEL: Record<RoomStatus, string> = {
  vacant: "Frei",
  occupied: "Belegt",
  reserved: "Reserviert",
  cleaning: "Reinigung",
  blocked: "Gesperrt",
};

const STATUS_COLOR: Record<RoomStatus, string> = {
  vacant: "text-text-tertiary",
  occupied: "text-domain-heating-on",
  reserved: "text-domain-preheat",
  cleaning: "text-domain-preheat",
  blocked: "text-domain-heating-off",
};

export default function ZimmerPage() {
  const [filterRoomTypeId, setFilterRoomTypeId] = useState<number | "">("");
  const [filterStatus, setFilterStatus] = useState<RoomStatus | "">("");
  const [filterFloor, setFilterFloor] = useState<string>("");
  const [showCreate, setShowCreate] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const roomTypes = useRoomTypes();
  const list = useRooms({
    room_type_id: filterRoomTypeId === "" ? undefined : filterRoomTypeId,
    status: filterStatus === "" ? undefined : filterStatus,
    floor: filterFloor.trim() === "" ? undefined : parseInt(filterFloor, 10),
    limit: 200,
  });
  const createMut = useCreateRoom();

  const handleCreate = async (payload: RoomCreate | RoomUpdate) => {
    setError(null);
    try {
      await createMut.mutateAsync(payload as RoomCreate);
      setShowCreate(false);
    } catch (e) {
      setError(toMessage(e));
    }
  };

  return (
    <div className="p-6 max-w-6xl mx-auto">
        <header className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-medium text-text-primary">Zimmer</h1>
            <p className="text-sm text-text-secondary mt-1">
              {list.data?.length ?? 0} Zimmer angezeigt.
            </p>
          </div>
          <button
            type="button"
            onClick={() => {
              setError(null);
              setShowCreate((s) => !s);
            }}
            className="px-4 py-2 bg-primary text-on-primary rounded-md flex items-center gap-2"
          >
            <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
              add
            </span>
            {showCreate ? "Abbrechen" : "Neues Zimmer"}
          </button>
        </header>

        {showCreate ? (
          <div className="bg-surface border border-border rounded-md p-5 mb-6">
            <h2 className="text-lg font-medium text-text-primary mb-4">Neues Zimmer</h2>
            <RoomForm
              onSubmit={handleCreate}
              onCancel={() => setShowCreate(false)}
              submitting={createMut.isPending}
              error={error}
            />
          </div>
        ) : null}

        <div className="bg-surface border border-border rounded-md p-4 mb-4 grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div>
            <label className="block text-xs text-text-secondary mb-1">Raumtyp</label>
            <select
              value={filterRoomTypeId}
              onChange={(e) =>
                setFilterRoomTypeId(e.target.value === "" ? "" : parseInt(e.target.value, 10))
              }
              className="w-full px-2 py-1.5 border border-border rounded-md bg-surface text-sm"
            >
              <option value="">Alle</option>
              {(roomTypes.data ?? []).map((rt) => (
                <option key={rt.id} value={rt.id}>
                  {rt.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Status</label>
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus((e.target.value || "") as RoomStatus | "")}
              className="w-full px-2 py-1.5 border border-border rounded-md bg-surface text-sm"
            >
              <option value="">Alle</option>
              <option value="vacant">Frei</option>
              <option value="occupied">Belegt</option>
              <option value="reserved">Reserviert</option>
              <option value="cleaning">Reinigung</option>
              <option value="blocked">Gesperrt</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-text-secondary mb-1">Etage</label>
            <input
              type="number"
              value={filterFloor}
              onChange={(e) => setFilterFloor(e.target.value)}
              placeholder="Alle"
              className="w-full px-2 py-1.5 border border-border rounded-md bg-surface text-sm"
            />
          </div>
        </div>

        <RoomTable list={list.data ?? []} loading={list.isLoading} error={list.isError} />
      </div>
  );
}

interface TableProps {
  list: Room[];
  loading: boolean;
  error: boolean;
}

function RoomTable({ list, loading, error }: TableProps) {
  if (loading) {
    return (
      <div className="bg-surface border border-border rounded-md p-4 text-sm text-text-secondary">
        Lade…
      </div>
    );
  }
  if (error) {
    return (
      <div className="bg-surface border border-border rounded-md p-4 text-sm text-domain-heating-off">
        Fehler beim Laden.
      </div>
    );
  }
  if (list.length === 0) {
    return (
      <div className="bg-surface border border-border rounded-md p-4 text-sm text-text-secondary">
        Keine Zimmer mit diesen Filtern.
      </div>
    );
  }
  return (
    <div className="bg-surface border border-border rounded-md overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-surface-alt border-b border-border">
          <tr>
            <th className="text-left px-3 py-2 font-medium text-text-secondary">Nummer</th>
            <th className="text-left px-3 py-2 font-medium text-text-secondary">Etage</th>
            <th className="text-left px-3 py-2 font-medium text-text-secondary">Orient.</th>
            <th className="text-left px-3 py-2 font-medium text-text-secondary">Status</th>
            <th className="text-left px-3 py-2 font-medium text-text-secondary"></th>
          </tr>
        </thead>
        <tbody>
          {list.map((r) => (
            <tr key={r.id} className="border-b border-border last:border-b-0 hover:bg-surface-alt">
              <td className="px-3 py-2">
                <Link
                  href={{ pathname: "/zimmer/[id]", query: { id: r.id } } as never}
                  className="font-medium text-text-primary hover:text-primary"
                >
                  {r.number}
                </Link>
                {r.display_name ? (
                  <div className="text-xs text-text-tertiary">{r.display_name}</div>
                ) : null}
              </td>
              <td className="px-3 py-2 text-text-secondary">{r.floor ?? "—"}</td>
              <td className="px-3 py-2 text-text-secondary">{r.orientation ?? "—"}</td>
              <td className="px-3 py-2">
                <span className={STATUS_COLOR[r.status]}>{STATUS_LABEL[r.status]}</span>
              </td>
              <td className="px-3 py-2 text-right">
                <Link
                  href={{ pathname: "/zimmer/[id]", query: { id: r.id } } as never}
                  className="text-xs text-primary hover:underline"
                >
                  Detail →
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
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
