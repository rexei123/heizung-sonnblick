"use client";

/**
 * ReplaceDeviceDialog — atomarer Pool-Reassign-Tausch (Sprint 13b.2 T4).
 *
 * Konsumiert ``useReplaceFromPool`` + ``useDevicePool`` + ``FormDialog``
 * + shadcn ``Select``. Backend-Endpoint ist AE-57 Entscheidung 6
 * (POST /api/v1/devices/{old}/replace/from-pool).
 *
 * 409-Subtype-Distinktion ohne ``exception_class``-Diskriminator
 * (verifiziert 2026-05-23 gegen backend/services/device_service.py +
 * api/v1/devices.py:474-481): das Backend liefert beide 409-Faelle nur
 * als ``{detail: <string>}``. String-Pattern-Match am detail-Feld
 * disambiguiert die zwei Faelle. Pool-Match zuerst, weil im
 * Hotelier-Alltag der haeufigere Race-Fall.
 *
 * Pool-Cache wird onError bei Pool-Race im Dialog explizit
 * invalidiert — useReplaceFromPool macht nur onSuccess (T1.b),
 * Error-Specific-Refetch liegt UI-seitig.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { FormDialog } from "@/components/ui/form-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  useDevicePool,
  useReplaceFromPool,
} from "@/lib/api/hooks-devices-lifecycle";
import type { ApiError } from "@/lib/api/types";
import { showErrorToast, showSuccessToast } from "@/lib/toast";

const RE_POOL_UNAVAILABLE = /Pool|parallel vergeben/i;
const RE_DEVICE_STATE = /retired|nicht zugewiesen|Re-Replace/i;

export interface ReplaceDeviceDialogProps {
  deviceId: number;
  deviceLabel: string;
  roomId: number;
  open: boolean;
  onClose: () => void;
}

export function ReplaceDeviceDialog({
  deviceId,
  deviceLabel,
  roomId,
  open,
  onClose,
}: ReplaceDeviceDialogProps) {
  const qc = useQueryClient();
  const pool = useDevicePool();
  const replaceMut = useReplaceFromPool(deviceId, roomId);
  const [selectedPoolId, setSelectedPoolId] = useState<string>("");

  const poolDevices = pool.data ?? [];
  const poolEmpty = !pool.isLoading && poolDevices.length === 0;

  const handleConfirm = async () => {
    const idNum = Number.parseInt(selectedPoolId, 10);
    if (!Number.isFinite(idNum) || idNum <= 0) return;

    try {
      await replaceMut.mutateAsync({ new_pool_device_id: idNum });
      showSuccessToast("Thermostat getauscht — Engine übernimmt in ≤ 60 s");
      setSelectedPoolId("");
      onClose();
    } catch (err) {
      const apiErr = err as ApiError;
      const detail =
        typeof apiErr?.detail === "string" ? apiErr.detail : "";
      const status = apiErr?.status;

      if (status === 409 && RE_POOL_UNAVAILABLE.test(detail)) {
        // Pool-Race: Reserve wurde parallel vergeben. Dialog bleibt
        // offen, Pool sofort neu laden, Auswahl zuruecksetzen, User
        // waehlt erneut.
        showErrorToast(
          "Reserve bereits vergeben. Bitte Auswahl erneut treffen.",
        );
        qc.invalidateQueries({ queryKey: ["devices", "pool"] });
        setSelectedPoolId("");
        return;
      }
      if (status === 409 && RE_DEVICE_STATE.test(detail)) {
        // Alter Thermostat war beim Submit nicht mehr aktiv (z.B.
        // bereits retired durch andere Session). Dialog schliessen,
        // Voll-Refetch.
        showErrorToast(
          "Thermostat ist nicht mehr aktiv. Bitte Liste neu laden.",
        );
        qc.invalidateQueries({ queryKey: ["devices"] });
        onClose();
        return;
      }
      // 404 / 500 / Netzwerk-Fehler / ueberraschende 409-Strings
      // (z.B. Selbst-Tausch-ValueError aus api/v1/devices.py:480-481)
      showErrorToast("Tausch fehlgeschlagen.");
      onClose();
    }
  };

  return (
    <FormDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setSelectedPoolId("");
          onClose();
        }
      }}
      title="Thermostat tauschen"
      description={`„${deviceLabel}" wird stillgelegt, ein Reserve-Thermostat aus dem Lager übernimmt die Heizzone.`}
      confirmLabel="Tauschen"
      onConfirm={handleConfirm}
      confirmDisabled={poolEmpty || selectedPoolId === ""}
      isPending={replaceMut.isPending}
    >
      <div className="space-y-3 py-2">
        <label
          htmlFor="replace-device-pool-select"
          className="block text-sm font-medium text-text-primary"
        >
          Reserve-Thermostat
        </label>
        {pool.isLoading ? (
          <p className="text-sm text-text-secondary">Lade Reserve-Pool…</p>
        ) : poolEmpty ? (
          <p className="text-sm text-text-secondary">
            Kein Reserve-Thermostat verfügbar. Reserve über CLI-Skript
            hinzufügen (siehe RUNBOOK §10h).
          </p>
        ) : (
          <Select
            value={selectedPoolId}
            onValueChange={setSelectedPoolId}
            disabled={replaceMut.isPending}
          >
            <SelectTrigger id="replace-device-pool-select">
              <SelectValue placeholder="Reserve auswählen…" />
            </SelectTrigger>
            <SelectContent>
              {poolDevices.map((d) => (
                <SelectItem
                  key={d.id}
                  value={String(d.id)}
                  title={`DevEUI ${d.dev_eui}`}
                >
                  {d.label ?? d.dev_eui}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>
    </FormDialog>
  );
}
