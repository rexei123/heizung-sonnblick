"use client";

/**
 * RetireDeviceDialog — Stilllegung ohne Ersatz (Sprint 13b.2 T5).
 *
 * Konsumiert ``useRetireDevice`` + ``FormDialog`` + shadcn ``Select``.
 * Backend-Endpoint ist AE-57 Entscheidung 6 (POST
 * /api/v1/devices/{id}/retire): setzt ``retired_at`` +
 * ``retired_reason``; ``heating_zone_id`` bleibt am alten Device-Row
 * als Historie-Anker (Reading-FK).
 *
 * Reason-Dropdown: vier feste Optionen (Defekt / Batterie leer /
 * Verlust / Wartung); Backend ``DeviceRetireRequest.reason`` akzeptiert
 * Freitext 1-255 chars, die vier Strings sind in dieser Range.
 *
 * Bei ``isLastActiveInZone`` (Zone hat heute nur diesen einen aktiven
 * Thermostat): Warning-Box im Body, weil Heizung in der Zone bis zur
 * Neu-Zuweisung inaktiv bleibt.
 *
 * 409-Distinktion vs. T4: hier nur ``DeviceStateError`` moeglich
 * (Device bereits retired durch parallele Session). Backend
 * api/v1/devices.py:531-534 mapt nur DeviceNotFound -> 404,
 * DeviceStateError -> 409. Kein Pool-Race-Pfad.
 */

import { useState } from "react";

import { FormDialog } from "@/components/ui/form-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useRetireDevice } from "@/lib/api/hooks-devices-lifecycle";
import type { ApiError } from "@/lib/api/types";
import { showErrorToast, showSuccessToast } from "@/lib/toast";

const REASON_OPTIONS = [
  "Defekt",
  "Batterie leer",
  "Verlust",
  "Wartung",
] as const;

type RetireReason = (typeof REASON_OPTIONS)[number];

export interface RetireDeviceDialogProps {
  deviceId: number;
  deviceLabel: string;
  roomId: number;
  isLastActiveInZone: boolean;
  open: boolean;
  onClose: () => void;
}

export function RetireDeviceDialog({
  deviceId,
  deviceLabel,
  roomId,
  isLastActiveInZone,
  open,
  onClose,
}: RetireDeviceDialogProps) {
  const retireMut = useRetireDevice(deviceId, roomId);
  const [reason, setReason] = useState<RetireReason | "">("");

  const handleConfirm = async () => {
    if (reason === "") return;

    try {
      await retireMut.mutateAsync({ reason });
      showSuccessToast("Thermostat stillgelegt");
      setReason("");
      onClose();
    } catch (err) {
      const apiErr = err as ApiError;
      const detail =
        typeof apiErr?.detail === "string" ? apiErr.detail : "";
      const status = apiErr?.status;

      if (status === 409 && /retired/i.test(detail)) {
        showErrorToast("Thermostat ist bereits stillgelegt.");
        onClose();
        return;
      }
      // 404 / 500 / Netzwerk-Fehler
      showErrorToast("Stilllegung fehlgeschlagen.");
      onClose();
    }
  };

  return (
    <FormDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setReason("");
          onClose();
        }
      }}
      title="Thermostat stilllegen"
      description={`Möchten Sie „${deviceLabel}" dauerhaft stilllegen?`}
      confirmLabel="Stilllegen"
      confirmVariant="destructive"
      onConfirm={handleConfirm}
      confirmDisabled={reason === ""}
      isPending={retireMut.isPending}
    >
      <div className="space-y-3 py-2">
        {isLastActiveInZone ? (
          <div
            role="alert"
            className="rounded-md border border-warning bg-warning-soft p-3 text-sm text-warning"
          >
            <strong className="block font-medium">
              Letzter aktiver Thermostat dieser Zone.
            </strong>
            Heizung in dieser Zone wird nach Stilllegung inaktiv, bis ein
            neuer Thermostat zugewiesen wird.
          </div>
        ) : null}

        <label
          htmlFor="retire-device-reason-select"
          className="block text-sm font-medium text-text-primary"
        >
          Grund
        </label>
        <Select
          value={reason}
          onValueChange={(v) => setReason(v as RetireReason)}
          disabled={retireMut.isPending}
        >
          <SelectTrigger id="retire-device-reason-select">
            <SelectValue placeholder="Grund auswählen…" />
          </SelectTrigger>
          <SelectContent>
            {REASON_OPTIONS.map((r) => (
              <SelectItem key={r} value={r}>
                {r}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </FormDialog>
  );
}
