---
titel: Hotel-Stammdaten
kategorie: Die Seiten
stichworte: Hotel, Zeitzone, Check-in, Check-out, Warnungen, E-Mail, offline
rollen: admin
stand: 2026-11-21
route: /einstellungen/hotel
---

Die Angaben, die für das ganze Haus gelten. Drei Gruppen: Allgemein,
Standardzeiten, Warnungen.

## Allgemein

**Hotel-Name** steht in Mails und in Berichten.

**Zeitzone** ist die Grundlage **aller** Zeitangaben in der Steuerung.
Die Nachtabsenkung, die Betriebszeiten und das Vorheizen rechnen in
dieser Zone; intern speichert die Steuerung in Weltzeit und rechnet vor
jedem Vergleich um. Die Umstellung auf Winter- und Sommerzeit ist damit
mitgedacht. Die Zone zu ändern verschiebt jede eingetragene Uhrzeit in
ihrer Wirkung — das ist keine Anzeigeeinstellung.

## Standardzeiten

**Default Check-in** und **Default Check-out**. Eine Belegung wird mit
Kalendertagen eingetragen; diese beiden Zeiten machen daraus Zeitpunkte.
Check-in ist auch der Bezugspunkt für das Vorheizen: „Vorheizen vor
Check-In" zählt von hier zurück.

## Warnungen

**E-Mail für Warnungen** ist die Adresse, an die **alle** Melder dieser
Steuerung schreiben: die fehlende Belegungsliste, die Engine-Alarme, ein
Gerät das schweigt, eine Zone ohne Messwert, die volle Festplatte und —
seit dem 18.11.2026 — ein Relais, dessen Gehäuse warm wird oder das sich
selbst abgeschaltet hat. Steht hier keine Adresse, laufen die Melder
weiter und schreiben ins Protokoll, aber niemand erfährt davon.

> **Ein abgeschaltetes Relais ist der dringendste dieser Fälle.** Das
> Gerät schaltet sich bei Überhitzung, Überspannung, Überstrom oder
> Überlast selbst ab, und die Steuerung sperrt es danach, bis ein
> Administrator die Sperre auf der Geräteseite aufhebt. So lange heizt
> dieser Bereich nicht. In der Mail steht, was zuerst zu tun ist: die
> Ursache suchen, nicht die Sperre aufheben.

> **Das Feld „Gerät offline nach (Min)" ist am 07.11.2026 entfernt
> worden, weil es nichts getan hat.** Hier stand, es steuere die Anzeige
> auf der Geräteseite — auch das war falsch: eine Suche über Backend und
> Frontend fand den Wert im Schema und in diesem Formular, und **keine
> Stelle, die ihn liest**.
>
> Was tatsächlich gilt, ist die Betriebsregel, die hier schon richtig
> stand: **ab drei Stunden Funkstille** gilt ein Gerät als still. Diese
> Grenze ist nicht in der Oberfläche verstellbar, und zwar mit Absicht —
> an ihr hängt der Funkstille-Alarm.

## Speichern

Der Knopf bleibt untätig, solange sich nichts geändert hat („Keine
Änderungen."). Nach dem Speichern wirken die Werte beim nächsten Lauf
der Steuerung.
