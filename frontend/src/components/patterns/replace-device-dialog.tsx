"use client";

/**
 * ReplaceDeviceDialog — atomarer Pool-Reassign-Tausch (Sprint 13b.2 T4
 * + B-Sprint13b2-4 error_code-Migration).
 *
 * Konsumiert ``useReplaceFromPool`` + ``useDevicePool`` + ``FormDialog``
 * + shadcn ``Select``. Backend-Endpoint ist AE-57 Entscheidung 6
 * (POST /api/v1/devices/{old}/replace/from-pool).
 *
 * Subtype-Distinktion via ``error_code``-Feld im Backend-Response-Body
 * (AE-59, B-Sprint13b2-4). Vier Codes mit klarem Toast +
 * Invalidate-Verhalten — siehe ``handleConfirm``-catch-Block. Frueheres
 * String-Regex-Match (RE_POOL_UNAVAILABLE / RE_DEVICE_STATE) ist
 * entfernt; der App-weite FastAPI-Handler liefert seit
 * ``B-Sprint13b2-4`` das maschinen-lesbare ``error_code``-Feld.
 *
 * Pool-Cache wird onError bei ``POOL_DEVICE_UNAVAILABLE`` im Dialog
 * explizit invalidiert — ``useReplaceFromPool`` macht nur onSuccess
 * (T1.b), Error-Specific-Refetch liegt UI-seitig.
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
import { ERROR_CODES, getErrorCode } from "@/lib/api/error-codes";
import {
  useDevicePool,
  useReplaceFromPool,
} from "@/lib/api/hooks-devices-lifecycle";
import { showErrorToast, showSuccessToast } from "@/lib/toast";

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
      // B-Sprint13b2-4 (AE-59): error_code-basierte Distinktion.
      // getErrorCode liefert null bei unbekannten Server-Codes oder
      // wenn das Feld nicht gesetzt ist (404 / 500 / Netzwerk-Fehler
      // / 4xx ohne unseren App-weiten Handler).
      const code = getErrorCode(err);
      switch (code) {
        case ERROR_CODES.POOL_DEVICE_UNAVAILABLE:
          // Pool-Race: Reserve wurde parallel vergeben. Dialog bleibt
          // offen, Pool sofort neu laden, Auswahl zuruecksetzen, User
          // waehlt erneut.
          showErrorToast(
            "Reserve bereits vergeben. Bitte Auswahl erneut treffen.",
          );
          qc.invalidateQueries({ queryKey: ["devices", "pool"] });
          setSelectedPoolId("");
          return;
        case ERROR_CODES.DEVICE_STATE_ERROR:
          // Alter Thermostat war beim Submit nicht mehr aktiv (z.B.
          // bereits retired durch andere Session). Dialog schliessen,
          // Voll-Refetch.
          showErrorToast(
            "Thermostat ist nicht mehr aktiv. Bitte Liste neu laden.",
          );
          qc.invalidateQueries({ queryKey: ["devices"] });
          onClose();
          return;
        case ERROR_CODES.SELF_REPLACEMENT_FORBIDDEN:
          // Defensiv — UI-seitig sollte das nicht erreichbar sein,
          // weil das Dropdown nur Pool-Devices (heating_zone_id IS
          // NULL) anbietet und das aktuelle Device aktiv-zugewiesen
          // ist. Falls doch (Race + Refresh + falscher State): klarer
          // Toast, Dialog schliessen.
          showErrorToast(
            "Tausch nicht möglich: Quell- und Zielgerät identisch.",
          );
          onClose();
          return;
        case ERROR_CODES.DEVICE_NOT_FOUND:
          // alter oder neuer Device-Row existiert nicht mehr —
          // typischerweise nach DB-Cleanup oder parallel Migration.
          // Voll-Refetch, Dialog schliessen.
          showErrorToast(
            "Thermostat nicht gefunden. Bitte Liste neu laden.",
          );
          qc.invalidateQueries({ queryKey: ["devices"] });
          onClose();
          return;
        default:
          // 404 / 500 / Netzwerk-Fehler / unbekannter Server-Code
          showErrorToast("Tausch fehlgeschlagen.");
          onClose();
      }
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
