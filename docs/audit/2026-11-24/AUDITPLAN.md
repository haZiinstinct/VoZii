# Audit November 2026 — Auditplan

Arbeitspakete zu [AUDIT-BERICHT.md](AUDIT-BERICHT.md), in empfohlener
Reihenfolge. Je Paket ein Branch und ein PR. Zeilennummern: Commit `7121da4`.

Vorab: Branch `refactor/live-vorschau-simplify` (Commit `132e94f`,
Vereinfachungen ohne Verhaltensänderung) mergen oder verwerfen — Paket 1
baut auf denselben Dateien auf.

## Offene Entscheidungen

- **E1 · Dependabot** — `.github/dependabot.yml` wurde in `0e3bfcf` mit
  entfernt. (a) wieder anlegen, monatlich statt wöchentlich; (b) bewusst
  weglassen und Pins bei jedem Release von Hand prüfen (dann in der
  Oktober-Maßnahmenliste A2 korrigieren). Empfehlung: (a).
- **E2 · Tastaturbedienung** — (a) Minimal: Enter/Escape/Tab-Fix, etwa 1 h;
  (b) vollständig: alle Bedienelemente fokussierbar mit sichtbarem Fokus,
  halber Tag, greift in CTk-Interna. Empfehlung: (a) jetzt, (b) als eigenes
  Paket.
- **E3 · RTL** — (a) Arabisch spiegeln (halber Tag); (b) Arabisch als
  „linksbündig, aber übersetzt“ belassen und `is_rtl()` entfernen.
- **E4 · Overlay-Texte** — längere, verständliche Texte (T4) oder kurze
  Codes behalten und im README erklären.
- **E5 · Anrede und Begriffe** — Glossar festlegen (Status-Anzeige,
  Grafikkarte, Erkennung, Verlauf, herunterladen), bevor T1–T7 angefasst
  werden.

## Pakete

### 1 · Live-Vorschau robust (C1, C3, C4, C5, S2) — M
Startsatz: „Arbeite Paket 1 aus docs/audit/2026-11-24/AUDITPLAN.md ab:
Vorschau-Thread an shutdown_event binden, Pausen-RMS nur über die letzten
1,5 s, Overlay-Monitor beim Aufnahmestart merken, Live-Schalter bei
ausgeschalteter Status-Anzeige deaktivieren, Halluzinations-Log ohne Text.
Je Punkt ein Test in tests/test_session.py.“
Abnahme: neue Tests grün; kein Thread `live-preview` nach Zyklusende.

### 2 · Vorschau-Latenz messen (C2) — M
Startsatz: „Paket 2: Miss mit scripts/bench_stt.py oder einem neuen Skript
die Zeit Hotkey-los → Text für 20 Aufnahmen mit und ohne Live-Vorschau
(Parakeet). Passe LIVE_WINDOW_S an, bis der Median-Unterschied unter 100 ms
liegt, und halte die Messwerte im PR fest.“
Abnahme: Messtabelle im PR, Median-Differenz < 100 ms.

### 3 · Kontrast und Hover (A1, A3, A6, A8 „Bereit“-Button) — S
Startsatz: „Paket 3: Segment-Farben auf #007a99/#006680, Ollama-Abbrechen-
Hover auf card_hover, hover_color in allen Zweigen von _update_dl_button,
border heller, text_color_disabled grün für ‚Bereit‘. Kontraste nachrechnen
und im PR als Tabelle belegen.“
Abnahme: alle geänderten Paare ≥ 4,5:1 (Text) bzw. ≥ 3:1 (Rahmen angestrebt).

### 4 · Tastatur und Tooltips (A2 nach E2, A4, A5) — M bis L
Startsatz: „Paket 4: Enter speichert, Escape bricht ab, Tab verlässt die
Vokabel-Textbox; Tooltips auch bei Fokus, mit 400 ms Verzögerung und
Randschutz; Hinweis-Schrift auf 12 px. Danach das Fenster ohne Maus
durchgehen und das Ergebnis je Bedienelement notieren.“
Abnahme: Protokoll „ohne Maus“ im PR, kein Fokus-Hänger.

### 5 · Deutsche Texte (T1, T5, T7 nach E5) — M
Startsatz: „Paket 5: In STRINGS['de'] alle ae/oe/ue/ss-Ersatzschreibungen
durch echte Umlaute ersetzen (Liste im Bericht T1), Begriffe nach Glossar
vereinheitlichen, ‚Sicher?‘ und ‚Starten‘ wie in T7. Test ergänzen, der
Ersatzschreibungen findet.“
Abnahme: neuer Test grün, `test_i18n.py` grün.

### 6 · Fehlermeldungen und hart kodierte Texte (T2, T3, T4 nach E4, T6) — L
Startsatz: „Paket 6: Texte aus src/text_processor.py:330-459 in i18n-Keys
überführen (9 Sprachen), Fehlermeldungen nach dem Muster ‚was, warum, was
tun‘ neu fassen, Overlay-Codes und Engine-Bezeichnungen laienverständlich.
Overlay-Breite mit dem längsten Text je Sprache prüfen.“
Abnahme: kein deutsches Literal mehr an `progress_callback`; Key-Test grün.

### 7 · Stil aufräumen (D1–D5, M1, M2, B1) — M
Startsatz: „Paket 7: _MENU_STYLE und _SWITCH_STYLE einführen, Buttonhöhe 32,
Abstände 4/8/16, Fortschrittsbalken nur bei Aktivität, Hover für
Einklapp-Köpfe, Animations-Job abbrechbar, ein geometry()-Aufruf,
ruff --fix für scripts.“
Abnahme: Screenshot vorher/nachher, ruff ohne Meldung.

### 8 · Overlay und Tray (A7, A8 Rest) — M
Startsatz: „Paket 8: Overlay klick-durchlässig und NOACTIVATE, Fehler 8 s
sichtbar, Tray-Titel mit Zustand, eine Farbe für Transkribieren,
Animationseinstellung von Windows respektieren.“
Abnahme: Klick auf das Vorschau-Panel erreicht das Fenster darunter.

### 9 · Download-Härtung (S1, S3, E1) — S
Startsatz: „Paket 9: Hash auf der .part prüfen und erst dann umbenennen
(Test mit Abbruch), Ollama zuerst unter festen Pfaden suchen, Dependabot
nach E1.“
Abnahme: Test „Abbruch nach Download → keine Zieldatei“ grün.

### 10 · RTL und Screenshots (D6 nach E3, D7) — M
Startsatz: „Paket 10: Layout-Richtung aus is_rtl() ableiten, arabische
Oberfläche prüfen, alle drei Screenshots mit 1.12 neu aufnehmen.“
Abnahme: neue Screenshots im Repo.
