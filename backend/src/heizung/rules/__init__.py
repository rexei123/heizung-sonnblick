"""Regel-Engine (5-Schichten-Modell, siehe AE-06).

Wird in Sprint 7/8 befüllt. Die Struktur folgt der in
``docs/ARCHITEKTUR-ENTSCHEIDUNGEN.md`` festgelegten Pipeline:

    1. Base Target         (R1, R7)
    2. Temporal Override   (R2, R3, R4)
    3. Guest Override      (R6)
    4. Window Safety       (R5)
    5. Hard Clamp          (R8 + Gäste-Grenzen)
"""
