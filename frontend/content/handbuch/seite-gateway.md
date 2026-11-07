---
titel: Gateway
kategorie: Die Seiten
stichworte: Gateway, Funk, LoRaWAN, ChirpStack, Empfang, in Vorbereitung
rollen: admin
stand: 2026-11-07
route: /einstellungen/gateway
---

> **Nicht mehr im Menü (ab 07.11.2026).** Diese Seite steht nicht mehr in
> der Seitenleiste, weil sie nichts anzeigt — ein Menüpunkt, der zu „In
> Vorbereitung" führt, kostet bei jedem Blick eine Enttäuschung. Über
> einen Lesezeichen-Link ist sie weiter erreichbar und sagt dann, was sie
> ist. Sie kommt zurück, wenn es etwas zu bedienen gibt.

> **Diese Seite ist leer.** Der Zustand des Funk-Gateways ist vorgesehen;
> bis dahin zeigt sie nur ihren Namen.

## Was das Gateway tut

Die Thermostate funken nicht ins Internet, sondern an ein Gateway im
Haus. Das Gateway gibt die Meldungen an die Funkverwaltung weiter, und
von dort kommen sie in die Steuerung. Umgekehrt nimmt es die Befehle und
sendet sie an die Köpfe.

**Folge für den Betrieb:** fällt das Gateway aus, sind **alle** Geräte
auf einmal still. Ein einzelnes stilles Gerät ist ein Gerätefehler,
hundert stille Geräte sind ein Gateway- oder Funkfehler. Die Zahl
unterscheidet die beiden Fälle, und sie steht auf dem Dashboard als
„Geräte online".

## Wo man heute nachsieht

- **Dashboard**, Kachel „Geräte online" — die schnelle Antwort auf
  „einer oder alle".
- **Thermostate**, sortiert nach Fehlerstatus — welche genau.
- Alles darunter ist Server-Arbeit und steht im Betriebshandbuch
  (RUNBOOK).
