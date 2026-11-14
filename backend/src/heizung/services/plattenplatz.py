"""Wie voll ist die Platte des Servers? (14.11.2026)

**Der Anlass, 13./14.11.2026.** Bei der Vorarbeit zum Relais-Verlauf war
die Platte zu **94 %** voll — 4,5 GB frei von 75 GB, am naechsten Morgen
4,1 GB. Aufgefallen ist es niemandem; gefunden wurde es beim Nachsehen
nach etwas anderem.

**Was bei 100 % passiert:** Postgres nimmt keine Schreibvorgaenge mehr
an. Dann gibt es keine Messwerte, keine Engine-Auswertung und keine
Relais-Bestaetigungen — mitten in der Heizperiode. Der Weg dorthin ist
nicht dramatisch, sondern gleichmaessig: jeder Merge erzeugt ein
Image-Paar von rund 400 MB (Paragraph 5.4, zwei Tags je Image), und
``event_log`` waechst um etwa 4,8 GB im Monat. Bei 4,1 GB frei waren das
noch rund zehn Merges.

**Dieses Modul misst die Wirkung, nicht die Mechanik** (Paragraph 5.76).
Nicht „laeuft das Aufraeumen", nicht „wie viele Images liegen da",
sondern **wie viel Platz noch frei ist**. Das greift unabhaengig davon,
welche der Ursachen gerade zunimmt — und es greift auch bei einer, an die
heute niemand denkt.

Warum ``used / (used + free)`` und nicht ``used / total``
--------------------------------------------------------

Weil die Grenze in der Sprache des Betreibers steht und er ``df`` liest.
``df`` rechnet den Belegungsgrad **ohne** die fuer root reservierten
Bloecke (bei ext4 rund 5 %) und rundet auf. Gemessen am 14.11.2026 auf
dem Server:

======================== ===============
``df`` sagt              **64 %**
``used / total``         60,6 %
``used / (used + free)`` 63,2 % -> 64 %
======================== ===============

Drei Prozentpunkte Unterschied klingen harmlos und sind es nicht: eine
Warnung bei „85 %" wuerde mit der falschen Rechnung erst anschlagen, wenn
``df`` schon 88 % zeigt. Dann steht in der Mail eine andere Zahl als auf
dem Server, und die erste Frage ist nicht „was raeumen wir auf", sondern
„welche Zahl stimmt" (Paragraph 5.53).

Warum das im Container ueberhaupt funktioniert
----------------------------------------------

``shutil.disk_usage("/")`` im api-Container fragt das Dateisystem des
Containers ab — und das ist ein overlay2-Aufbau, dessen ``statfs`` die
Werte des **darunterliegenden** Dateisystems liefert. Nachgemessen am
14.11.2026, Host und beide Container auf Byte-Ebene identisch:

    /dev/sda1  total=80307429376  used=48690868224  free=28293947392

Deshalb braucht dieses Modul **keinen** Bind-Mount des Host-Dateisystems.
Das ist ausdruecklich eine Eigenschaft des Aufbaus und keine Zusicherung
von Docker: laege ``/var/lib/docker`` eines Tages auf einer eigenen
Platte, maesse dieser Code jene und nicht mehr die, auf der die
Datenbank liegt. Wer den Aufbau aendert, prueft diese Zeile mit

    docker exec deploy-api-1 python -c "import shutil; print(shutil.disk_usage('/'))"

gegen ``df -B1 /`` auf dem Host.

Was dieses Modul nicht tut
--------------------------

* **Es raeumt nicht auf.** Das tut ``infra/deploy/deploy-pull.sh`` nach
  jedem Deploy, und von Hand steht es im RUNBOOK Paragraph 10az. Ein
  Melder, der selbst loescht, verschweigt den Grund — und die naechste
  Ursache ist vielleicht nicht die, fuer die das Aufraeumen gebaut war.
* **Es nennt keine Ursache.** Ob die Images, ``event_log`` oder ein
  Backup den Platz braucht, sagt der Befehl in der Mail. Eine Vermutung
  im Melder waere eine Behauptung (Paragraph 5.68).
"""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass

#: Der Pfad, dessen Dateisystem gemessen wird. Im Container ist es der
#: overlay-Aufbau, und der liefert die Werte der Platte darunter (siehe
#: Modul-Kopf).
MESSPFAD = "/"


@dataclass(frozen=True, slots=True)
class PlattenStand:
    """Der Stand der Platte, in der Rechenart von ``df``."""

    gesamt_b: int
    belegt_b: int
    frei_b: int
    #: Belegung in ganzen Prozent, aufgerundet — wie ``df``.
    prozent: int
    #: Ob die Grenze ueberschritten ist. Das Urteil wird **mitgefuehrt**
    #: und nicht in einer Eigenschaft nachgerechnet: die Grenze kommt aus
    #: den Settings, und ein Befund, der sie noch braucht, waere ohne sie
    #: nicht lesbar (dieselbe Haltung wie bei ``relais_zone_melder``).
    warnt: bool

    @property
    def frei_gb(self) -> float:
        """Freier Platz in GB, auf eine Stelle gerundet — fuer die Mail."""
        return round(self.frei_b / 1_000_000_000, 1)


def beurteile(*, belegt_b: int, frei_b: int, gesamt_b: int, grenze_prozent: int) -> PlattenStand:
    """Urteil ohne Dateisystem — die Zahlen kommen von aussen.

    ``prozent`` ist ``ceil(belegt / (belegt + frei) * 100)``: dieselbe
    Rechnung und dieselbe Rundung wie ``df`` (Begruendung im Modul-Kopf).
    Der Nenner ist **nicht** ``gesamt_b``; die reservierten Bloecke
    gehoeren niemandem, der hier gemeint ist.

    ``gesamt_b`` wird trotzdem mitgefuehrt, weil die Mail die Groesse der
    Platte nennen soll — eine Warnung „87 % belegt" ohne Bezugsgroesse
    sagt nicht, ob noch 2 oder 200 GB frei sind.

    Die Grenze ist **inklusiv**: „ueber 85 %" meldet bei 85 noch nicht
    und bei 86 schon. Dieselbe Kante wie bei allen anderen Grenzen
    dieses Projekts.

    Ein leeres Dateisystem (``belegt + frei == 0``) gilt als 0 % und
    warnt nicht. Der Fall kann nur bei einem Messfehler entstehen, und
    eine Division waere dann ein Absturz im Dashboard-Endpunkt.
    """
    nutzbar = belegt_b + frei_b
    prozent = 0 if nutzbar <= 0 else math.ceil(belegt_b / nutzbar * 100)
    return PlattenStand(
        gesamt_b=gesamt_b,
        belegt_b=belegt_b,
        frei_b=frei_b,
        prozent=prozent,
        warnt=prozent > grenze_prozent,
    )


def lies_plattenstand(*, grenze_prozent: int, pfad: str = MESSPFAD) -> PlattenStand:
    """Misst das Dateisystem und urteilt.

    ``grenze_prozent`` ist Pflicht-Argument (Paragraph 5.73): ein Default
    waere eine zweite Wahrheit neben der Einstellung und liefe beim ersten
    Nachjustieren stumm auseinander.
    """
    stand = shutil.disk_usage(pfad)
    return beurteile(
        belegt_b=stand.used,
        frei_b=stand.free,
        gesamt_b=stand.total,
        grenze_prozent=grenze_prozent,
    )


# ---------------------------------------------------------------------------
# Mail-Texte
# ---------------------------------------------------------------------------


def betreff_alarm(stand: PlattenStand) -> str:
    return f"Heizung Sonnblick: Platte zu {stand.prozent} % belegt ({stand.frei_gb} GB frei)"


def betreff_entwarnung(stand: PlattenStand) -> str:
    return f"Heizung Sonnblick: Platte wieder unter der Grenze ({stand.prozent} %)"


def nachricht_alarm(stand: PlattenStand, *, grenze_prozent: int) -> str:
    """Die Folge zuerst, die Zahlen danach, der Handgriff zuletzt."""
    return (
        f"Die Platte des Servers ist zu {stand.prozent} % belegt, es sind "
        f"{stand.frei_gb} GB frei.\n\n"
        f"WAS PASSIERT, WENN SIE VOLLLAEUFT\n"
        f"Postgres nimmt keine Schreibvorgaenge mehr an. Dann gibt es keine "
        f"Messwerte, keine Engine-Auswertung und keine Relais-"
        f"Bestaetigungen — die Steuerung steht, und zwar nicht teilweise.\n\n"
        f"DER STAND\n"
        f"Belegt: {round(stand.belegt_b / 1_000_000_000, 1)} GB von "
        f"{round(stand.gesamt_b / 1_000_000_000, 1)} GB\n"
        f"Frei:   {stand.frei_gb} GB\n"
        f"Grenze: {grenze_prozent} %\n\n"
        f"WAS ZU TUN IST — in dieser Reihenfolge\n"
        f"1. Nachsehen, was den Platz braucht:\n"
        f"   df -h / ; docker system df\n"
        f"2. Das automatische Aufraeumen laeuft nach jedem Deploy und "
        f"loescht Deploy-Images, die aelter als sieben Tage sind. Kommt "
        f"diese Mail trotzdem, reicht es nicht — dann sind es nicht die "
        f"Images.\n"
        f"3. Die Checkliste von Hand steht im RUNBOOK Paragraph 10az "
        f"(mit Sicherheitsprobe, ohne 'prune').\n"
        f"4. Waechst 'event_log', ist es die Verdichtung — Vorschlag in "
        f"docs/status/.\n\n"
        f"WAS DIESE MELDUNG NICHT IST\n"
        f"Kein Hinweis auf einen Fehler. Die Platte fuellt sich im Betrieb, "
        f"gleichmaessig und vorhersagbar; diese Mail kommt, damit das "
        f"Aufraeumen ein Termin ist und kein Zufallsbefund.\n"
    )


def nachricht_entwarnung(stand: PlattenStand, *, grenze_prozent: int) -> str:
    """Die Entwarnung ist Pflicht, nicht Hoeflichkeit (Paragraph 5.79)."""
    return (
        f"Die Platte liegt wieder unter der Grenze: {stand.prozent} % belegt, "
        f"{stand.frei_gb} GB frei (Grenze {grenze_prozent} %).\n\n"
        f"Ob das vom Aufraeumen kommt oder davon, dass etwas anderes "
        f"geloescht wurde, sagt diese Meldung nicht.\n"
    )
