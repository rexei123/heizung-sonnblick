"""Importierbares Sub-Package fuer CLI-Skripte (Sprint 13a+).

Alle Hotelier-Skripte laufen ueber einen einzigen Aufruf-Pfad
``python -m heizung.scripts.<name>``:

- ``seed_rooms`` — Zimmer-Stammdaten-Seed (Sprint 15-Vorlauf)
- ``pair_devices`` — CSV-Import, Eingangstest, Pool-Liste, ``assign``
- ``activate_open_window_detection`` — OW-Rollout mit FW-Gate
  (Sprint 17 / B-Sprint13a-1 hierher migriert)
- ``sync_room_statuses`` — Sofort-Sync (Sprint 15g)

Unter ``backend/scripts/`` liegen nur noch Hand-Smoke-Tools ohne
Test-Coverage (``smoke_engine_lock.py``).
"""
