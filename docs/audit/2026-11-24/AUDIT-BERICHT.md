# Audit November 2026 — Bericht

Stand: Commit `7121da4` (master, VoZii 1.12.0), geprüft am 24.11.2026.
Folge-Audit zu [AUDIT-2026-10.md](../../AUDIT-2026-10.md); dort Erledigtes wird
nicht wiederholt. Schwerpunkt: alles seit Oktober (Parakeet, Sparmodus,
Live-Vorschau) sowie erstmals Oberfläche, Barrierefreiheit und UI-Texte.

VoZii ist eine Desktop-App, keine Website. Die Web-Ebenen des
Full-Stack-Audits (SEO, lokales SEO, strukturierte Daten, KI-Sichtbarkeit,
Impressum/Consent, Lighthouse) und der Neubau einer animierten Landingpage
sind **nicht anwendbar** und wurden nicht geprüft. Übertragen wurden: Build &
Code, Sicherheit, Barrierefreiheit, Inhalt/Texte, Design, Animation.

## Kurzfassung

| Ebene | Ampel | Kern |
|---|---|---|
| Build & Code | grün | 236 Tests grün, ruff sauber in `src`/`tests` (2 Kleinigkeiten in `scripts/build.py`) |
| Live-Vorschau (Code-Review PR 12) | gelb | 3 Fehler, 2 Kleinigkeiten (C1–C5) |
| Sicherheit | grün | kein Befund über der Meldeschwelle; 5 Härtungspunkte (S1–S5) |
| Barrierefreiheit | rot | aktives Segment 1,69:1; Fenster nur per Maus bedienbar (A1, A2) |
| Design | gelb | uneinheitliche Maße, RTL nicht umgesetzt, Stil-Duplikate (D1–D6) |
| UI-Texte | gelb | 46 Umlaut-Ersatzschreibungen, deutsche Reste in allen Sprachen, Fehlermeldungen ohne Handlungsweg (T1–T7) |
| Animation | grün | sparsam und zweckmäßig; 2 Kleinigkeiten (M1, M2) |

Prioritäten: **P0** blockiert Nutzer, **P1** spürbar, **P2** sollte, **P3** Kleinkram.

## Nicht prüfbar / offen

- Das Programm lief während des Audits nicht. Tab-Reihenfolge, Fokus,
  Disabled-Farben und RTL-Darstellung sind aus dem Code und aus den
  Screenshots in `docs/` geschlossen (die zeigen noch v1.6.0).
- Kontrastwerte von Hand nach WCAG-Formel gerechnet (±0,05), nicht gemessen.
- Screenreader (Narrator/NVDA) nicht getestet. Tk liefert kein UIA/MSAA —
  das ist eine Grenze des Toolkits, kein Fehler im Code.
- Mehr-Latenz durch die Live-Vorschau (C2) ist hergeleitet, nicht gemessen.
- `pip-audit` ist in der venv nicht installiert; Abhängigkeiten wurden nicht
  gegen CVE-Listen geprüft.
- D2 aus dem Oktober (Tests auf Linux) weiterhin unverifiziert.

---

## C — Code-Review Live-Vorschau

**C1 · P1 · Vorschau-Thread überlebt das Zyklusende**
Beleg: `src/session.py:180-187` (`_live_loop` endet nur über `stop`),
`src/app.py:324-334` (das `finally` ruft `_stop_live` nicht).
Endet der Zyklus während einer Aufnahme (Umschalt-Modus, Tray → Einstellungen),
liefert `snapshot()` nur noch `None`, der Thread wacht aber weiter alle 0,7 s
auf und hält Session, Recorder, Transcriber und Overlay fest.
Fix: `while not stop.wait(...)` um `and not self.shutdown_event.is_set()`
ergänzen.
Prüfkriterium: Test „shutdown_event gesetzt → `_live_loop` kehrt zurück“;
nach Einstellungs-Wechsel während der Aufnahme zeigt `threading.enumerate()`
keinen Thread `live-preview`.

**C2 · P1 · Laufende Vorschau verzögert die echte Transkription**
Beleg: `src/parakeet.py:163-171` (Lock während `recognize`),
`src/parakeet.py:146` (`transcribe` wartet darauf), `src/session.py:117`.
Loslassen stoppt nur künftige Durchläufe. Ein laufender Durchlauf über bis
zu 12 s Audio hält den Lock; beim whisper-server reiht sich die echte Anfrage
genauso hinten an. Der Docstring verspricht das Gegenteil.
Fix: `LIVE_WINDOW_S` auf 6–8 s senken und/oder vor jedem Durchlauf prüfen,
ob seit dem letzten genug neues Audio da ist. Vorher messen.
Prüfkriterium: Zeit Hotkey-los → Text eingefügt, 20 Diktate mit und ohne
Live-Vorschau; Median-Differenz unter 100 ms.

*Gemessen am 24.11.2026* mit `scripts/bench_live.py` (whisper-server,
large-v3-turbo, Vulkan, je 8 Durchläufe, synthetische Sprache):

| Fenster | Median | Max | mittlere Mehr-Latenz |
|---|---|---|---|
| 4 s | 568 ms | 592 ms | ~127 ms |
| 6 s | 574 ms | 578 ms | ~129 ms |
| 8 s | 602 ms | 619 ms | ~139 ms |
| 12 s | 643 ms | 661 ms | ~154 ms |

Ergebnis: Bei Whisper ist die Fenstergröße fast egal (das Modell rechnet
intern immer auf 30 s). Das Fenster zu verkleinern bringt also nichts; das
Ziel „unter 100 ms“ wäre nur mit einem Intervall von etwa 1,5 s erreichbar,
dann wirkt die Vorschau träge. **Entscheidung: Parameter bleiben**, die
Docstrings versprechen nicht mehr „bremst nie“. Im Mittel kostet die
Live-Vorschau hier rund 0,15 s je Diktat, im ungünstigsten Fall 0,65 s.
Parakeet wurde nicht gemessen (Modell auf dem Prüfrechner nicht installiert).

**C3 · P1 · Sprechpausen-Erkennung greift nicht**
Beleg: `src/session.py:167-169`. Der RMS wird über das ganze 12-s-Fenster
gebildet. 3 s Sprache (RMS 0,05) plus 8 s Stille ergeben rund 0,025, also
über der Schwelle 0,008 — es wird alle 0,7 s dasselbe Audio neu gerechnet.
Fix: RMS nur über die letzten 1–1,5 s bilden.
Prüfkriterium: Test mit Fenster „Sprache + 5 s Stille“ → `transcriber.preview`
wird nicht gerufen.

**C4 · P3 · Overlay springt beim Diktieren zwischen Monitoren**
Beleg: `src/overlay.py:239` → `_layout` → `_position` (`:166`) bei jedem
Vorschau-Update. Fix: Monitor beim Aufnahmestart merken.
Prüfkriterium: zwei Monitore, Maus beim Diktieren wechseln, Overlay bleibt.

**C5 · P2 · Schalter „Live-Vorschau“ aktiv, obwohl wirkungslos**
Beleg: `src/settings_gui.py:748-754`, Bedingung in `src/session.py:140-145`.
Bei ausgeschalteter Status-Anzeige oder Whisper auf der CPU erscheint nie
eine Vorschau, der Schalter zeigt das nicht.
Fix: Schalter deaktivieren und Grund in der Zeile darunter nennen.
Prüfkriterium: Status-Anzeige aus → Schalter grau.

Bereits erledigt (Branch `refactor/live-vorschau-simplify`, Commit `132e94f`):
ein Backend-Wahlpunkt `_live_backend()`, vereinfachtes `snapshot()`, tote
Guards entfernt, kein Neuzeichnen bei unverändertem Vorschautext.

## S — Sicherheit

Kein Befund mit konkretem Angriffsweg. Geprüft und unauffällig: Parakeet-Download
(HF-Commit und SHA-256 je Datei gepinnt, kein Archiv), onnx-asr lädt nichts
nach, Subprozesse ohne Shell und mit absoluten Pfaden, Live-Vorschau nur im
RAM und nur an 127.0.0.1, kein Diktat-Text in Logs der Vorschau,
`yaml.safe_load`, Update-Check mit festem Host, Workflows nur per Tag bzw.
`workflow_dispatch`.

Härtung (alle P2/P3):

- **S1 · P2** `src/downloader.py:196-203, 403-405` — Hash wird erst nach dem
  Umbenennen geprüft; danach zählt nur noch die Größe. Stirbt der Prozess
  dazwischen, gilt eine ungeprüfte Datei als installiert.
  Fix: Hash auf der `.part` prüfen, dann umbenennen.
  Prüfkriterium: Test, der nach dem Download eine Exception wirft — Zieldatei
  existiert nicht.
- **S2 · P2** `src/session.py:215-216` — verworfene „Halluzination“ wird im
  Klartext auf INFO geloggt; der Substring `amara` (`src/filters.py:47`) kann
  ein echtes Kurzdiktat treffen. Fix: nur Länge loggen.
  Prüfkriterium: `grep -n "%r" src/session.py` ohne Treffer mit Diktat-Text.
- **S3 · P3** `src/text_processor.py:168, 231-241` — `shutil.which("ollama")`
  wird jetzt bei jedem Start automatisch ausgeführt. Fix: feste
  Installationspfade zuerst, PATH als Fallback.
- **S4 · P2** `.github/dependabot.yml` fehlt seit Commit `0e3bfcf`, obwohl A2
  im Oktober abgehakt wurde. SHA- und pip-Pins altern still. Siehe E1.
- **S5 · P3** `src/text_processor.py:298-333` — Ollama-Installer unter festem
  Namen in `%TEMP%`, Lücke zwischen Signaturprüfung und Start. Nur durch
  Prozesse desselben Nutzers ausnutzbar.

## A — Barrierefreiheit (WCAG 2.1 AA, sinngemäß)

**A1 · P0 · Aktives Segment unlesbar (1.4.3)**
Beleg: `src/settings_gui.py:73-78` — `text_bright #f8fafc` auf `cyan #00d4ff`
= 1,69:1, im Hover auf `cyan_dim` 2,69:1 (Soll 4,5). Sichtbar in
`docs/screenshot-en.png`.
Fix: `selected_color="#007a99"`, `selected_hover_color="#006680"` (Weiß
darauf 4,7:1).
Prüfkriterium: nachgerechnetes Verhältnis ≥ 4,5 für beide Zustände.

**A2 · P0 · Einstellungsfenster nur per Maus bedienbar (2.1.1, 2.4.7)**
Beleg: alle `bind`-Aufrufe sind Maus-Events (`src/settings_gui.py:100-102,
219, 259, 428`); kein `<Return>`, `<Escape>`, `<space>`. In der
Vokabel-Textbox (`:600`) bleibt der Fokus hängen.
Fix: `<Return>` → Speichern, `<Escape>` → Abbrechen, `<Tab>` in der Textbox
weiterreichen; Buttons und Switches fokussierbar machen, `<space>` binden,
Fokus über `border_color=BRAND["cyan"]` zeigen.
Prüfkriterium: Maus weglegen — Sprache, Modell, Hotkey und „Starten“ sind
nur mit Tab/Leertaste/Enter erreichbar, der Fokus ist immer sichtbar.

**A3 · P1 · Hover-Zustände mit zu wenig Kontrast (1.4.3)**
- `src/settings_gui.py:679-685` Ollama-Abbrechen im Hover: `text_dim` auf
  `red` = 1,47:1. Fix: `hover_color=BRAND["card_hover"]`.
- `src/settings_gui.py:1018` setzt `hover_color="#dc2626"` (4,09:1);
  `_update_dl_button` (`:998-1005`) setzt ihn nie zurück — der cyane
  Download-Button hovert nach einem Abbruch rot.
  Fix: in allen Zweigen `hover_color` mitsetzen.
Prüfkriterium: Download starten, abbrechen, über den Button fahren → cyan.

**A4 · P1 · Tooltips nur per Maus (1.4.13)**
Beleg: `src/settings_gui.py:92-125`. Erklärungen zu Auto-Stop, Sparmodus und
Zwischenablage stehen nur dort. Fix: zusätzlich `<FocusIn>`/`<FocusOut>`,
400 ms Verzögerung, Position auf den Arbeitsbereich begrenzen.

**A5 · P2 · Kleine Schrift** — Hinweise und Status 11 px, Version 10 px
(`src/settings_gui.py:190, 529, 539, 594, 607, 621`). Fix: 12–13 bzw. 11.

**A6 · P2 · Rahmen und Flächen kaum sichtbar (1.4.11)** — `border` auf
`bg`/`card` 1,2:1 bzw. 1,13:1, Soll 3:1 (`src/theme.py:16`).
Fix: `border` Richtung `#3a3a4d`.

**A7 · P2 · Overlay fängt Klicks ab** — `src/overlay.py:94-100`: das bis zu
452 px breite Vorschau-Panel ist weder klick-durchlässig noch `NOACTIVATE`.
Fix: `WS_EX_NOACTIVATE | WS_EX_TRANSPARENT` per `SetWindowLongW`.
Prüfkriterium: Klick auf das Panel trifft das Fenster darunter.

**A8 · P3 · Kleinkram** — Tray zeigt den Zustand nur über Farbe
(`src/tray.py:11-15, 128`, Titel fest „VoZii“); Transkribieren ist im Tray
amber, im Overlay cyan; Fehler im Overlay verschwinden nach 5 s
(`src/session.py:77`); „Bereit“-Button wird deaktiviert grau statt grün
(`src/settings_gui.py:1001-1002`); Windows-Einstellung „Animationseffekte“
wird nicht abgefragt.

Bestanden: alle Fließtext-Paare (7,0–18,9:1), Statusfarben, Live-Vorschau
(15,1:1), Skalierung 150–200 %, Blinkfrequenz. Rot auf Card im Overlay liegt
mit 4,95:1 knapp darüber, über hellem Hintergrund (Alpha 0,92) rechnerisch
bei etwa 4,4.

## D — Design

Gut: klare Marke, eine Akzentfarbe, Start-Button fixiert, Seltenes
eingeklappt, Status immer mit Text, Farben fast vollständig als Tokens
(1 verstreuter Hex-Wert).

- **D1 · P2** Stil-Duplikate: OptionMenu-Farbblock 6-mal
  (`src/settings_gui.py:195, 475, 513, 554, 574, 710`), Switch-Stil 9-mal
  (`:464-788`). Fix: `_MENU_STYLE`, `_SWITCH_STYLE` wie `_SEG_STYLE`.
- **D2 · P2** Uneinheitliche Maße: Buttonhöhen 26/30/32/44, Radien
  2/4/8/10/12/13, acht Schriftgrößen. Fix: Zeilenhöhe 32, Abstände 4/8/16.
- **D3 · P2** Leere Fortschrittsbalken dauerhaft sichtbar
  (`src/settings_gui.py:535-541, 590-596`). Fix: nur bei Aktivität zeigen.
- **D4 · P2** Zwei gleich starke Cyan-Buttons (Download, Starten).
  Fix: Starten abschwächen, solange das Modell fehlt.
- **D5 · P3** Einklapp-Köpfe und Links ohne Hover-Rückmeldung
  (`src/settings_gui.py:399-407, 256`).
- **D6 · P1** RTL nicht umgesetzt: `is_rtl()` (`src/i18n.py:49`) wird nur in
  Tests benutzt; in `docs/screenshot-ar.png` bleibt alles linksbündig.
  Fix: `side`/`anchor`/`justify` aus einem Helfer beziehen.
  Prüfkriterium: arabische Oberfläche ist gespiegelt, neuer Screenshot.
- **D7 · P3** Screenshots in `docs/` zeigen v1.6.0.

## T — UI-Texte

Gut: 138 Keys in allen 9 Sprachen vollständig, Platzhalter identisch;
`dialog.vcredist.body` und `err.disk_space` vorbildlich; ehrliche Angaben zu
Datenschutz und Speicherbedarf in den Tooltips.

- **T1 · P1** 46 Umlaut-Ersatzschreibungen in den deutschen Texten
  (`src/i18n.py`, u. a. Zeilen 84, 87, 106–110, 116, 130, 133, 136, 142, 152,
  156–157, 163, 166–167, 179, 193, 197, 200, 203–206, 218–219, 223, 227,
  232–234, 237–238), während 119, 122, 146, 209 echte Umlaute haben.
  Prüfkriterium: Test, der in `STRINGS["de"]` nach `ae|oe|ue` an
  Umlaut-Stellen sucht (Ausnahmeliste: neue, Dauer, manuell, Issue, Steuerung).
- **T2 · P1** Deutsche Texte in allen Sprachen: `src/text_processor.py:330,
  340, 383, 389`; Ollamas roher englischer Pull-Status wird durchgereicht
  (`:449-459`). Fix: neue i18n-Keys.
- **T3 · P1** Fehlermeldungen ohne Handlungsweg: `src/i18n.py:128, 129, 131,
  132, 143, 169, 197, 220–222, 225, 226`. Muster: was ist passiert, warum,
  was tun. Beispiel 129: „Download fehlgeschlagen. Internetverbindung prüfen
  und erneut versuchen. ({error})“.
- **T4 · P2** Overlay-Codes kryptisch (`src/i18n.py:183-190, 236`): „CLIP“,
  „LEER“, „KURZ“, „FEHLER: WHISPER“ (auch bei Parakeet). Vorschlag: „KOPIERT –
  STRG+V“, „NICHTS ERKANNT“, „ZU KURZ“, „ERKENNUNG FEHLGESCHLAGEN“. In
  es/fr/pt unverständliche Abkürzungen („PORTAP.“, „PRESSE-P.“, „ÁREA T.“).
- **T5 · P2** Begriffe uneinheitlich: Overlay / Status-Anzeige;
  Grafikkarte / GPU / Beschleunigung / Backend; Transkription / Erkennung /
  Diktat; Historie / Verlauf; Download / laden / herunterladen.
- **T6 · P2** Jargon ohne Einordnung: „Parakeet (CPU)“, „Whisper“, „Ollama“,
  „NVIDIA (CUDA)“, „Vulkan (AMD / Intel)“, „whisper-server“.
- **T7 · P3** Buttons und Bestätigung: „Sicher?“ nennt keine Aktion (→
  „Endgültig löschen?“); „Starten“ speichert auch (→ „Speichern & starten“);
  en „Correct“ mehrdeutig (→ „Correction“); „...“ statt „…“, „1.5 GB“ statt
  „1,5 GB“.

## M — Animation

Zweckmäßig: einzige Bewegung sind die Punkte beim Transkribieren, Dauern
nach Zweck gestaffelt, CPU-Last vernachlässigbar.

- **M1 · P3** `src/overlay.py:275` — Animationskette ohne `after_cancel`;
  Transkribieren → Flash → Transkribieren binnen 300 ms lässt zwei Ketten
  laufen. Fix: Job-ID merken und abbrechen wie bei `_flash_job`.
- **M2 · P3** `src/overlay.py:165, 186` — zwei `geometry()`-Aufrufe je
  Update, Hintergrund wird jedes Mal neu erzeugt.

## B — Build

- **B1 · P3** `scripts/build.py:100-101` — zwei f-Strings ohne Platzhalter
  (ruff F541). Fix: `ruff check --fix scripts`.

## Checkliste

Stand 24.11.2026: alle Pakete umgesetzt (PRs 15–24). Abweichungen: C2 nur
gemessen, Parameter unverändert; A6 Rahmen 1,78:1 statt 3:1; Tray- und
Overlay-Farben bleiben verschieden; E1 Dependabot bleibt entfernt; Abstände
und Eckenradien (D2) nur teilweise vereinheitlicht; Übersetzungen der sieben
weiteren Sprachen nicht gegengelesen.

- [x] C1 Vorschau-Thread endet mit dem Zyklus
- [x] C2 Mehr-Latenz gemessen, Fenster angepasst
- [x] C3 Pausen-Erkennung über die letzten Sekunden
- [x] C4 Overlay bleibt auf dem Monitor
- [x] C5 Schalter zeigt, wann die Vorschau nicht geht
- [x] S1 Hash vor dem Umbenennen
- [x] S2 kein Diktat-Text im Log
- [x] S3 Ollama-Pfad fest
- [x] S4 / E1 Dependabot entschieden
- [x] A1 Segment-Kontrast
- [x] A2 Tastaturbedienung
- [x] A3 Hover-Farben
- [x] A4 Tooltips per Fokus
- [x] A5–A8 Schrift, Rahmen, Overlay, Kleinkram
- [x] D1–D5 Stil und Maße
- [x] D6 RTL
- [x] D7 Screenshots neu
- [x] T1 Umlaute
- [x] T2 hart kodierte Texte
- [x] T3 Fehlermeldungen
- [x] T4–T7 Overlay-Codes, Begriffe, Jargon, Buttons
- [x] M1, M2, B1
